"""Authoritative application policy. All release decisions use current durable state."""

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from http.cookies import SimpleCookie, CookieError
import re
import time
import uuid

from .crypto import (canonical, digest, iso, keyed, normalize_cnic, password_ok,
                     timestamp, token, valid_factor)
from .issuer import report_text, sign_package, verify_package
from .storage import IntegrityFailure


class ApiError(Exception):
    def __init__(self, status=404, code="unavailable", message="This resource is unavailable."):
        self.status, self.code, self.message = status, code, message


@dataclass
class Reply:
    status: int = 200
    body: object = field(default_factory=dict)
    headers: dict = field(default_factory=dict)


def uid():
    return str(uuid.uuid4())


def fields(data, allowed, required=()):
    if not isinstance(data, dict) or set(data) - set(allowed) or set(required) - set(data):
        raise ApiError(422, "invalid_fields", "Check the required fields; extra fields are not accepted.")
    for name, value in data.items():
        if name.endswith("_id") and value is not None and (not isinstance(value, str) or len(value) > 100):
            raise ApiError(422, "invalid_identifier", "Use the identifier supplied by the application.")
        if name == "expected_revision" and (not isinstance(value, int) or isinstance(value, bool)):
            raise ApiError(422, "invalid_revision", "Refresh the current revision before continuing.")


def text(value, maximum=200, empty=False):
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()):
        raise ApiError(422, "invalid_text", "Enter a bounded text value for each required field.")
    return value.strip()


def valid_evidence(item, now):
    try:
        return (item["status"] == "valid" and item.get("person_match") is True
                and timestamp(item["valid_from"]) <= now < timestamp(item["valid_until"]))
    except (ValueError, KeyError, TypeError):
        return False


def evidence_view(item, now):
    status = item.get("status", "unknown")
    if status == "valid" and not valid_evidence(item, now):
        status = "expired_or_unavailable"
    return {"status": status, "source": "SIMULATED ONLY", "source_ref": item.get("source_ref"),
            "checked_at": item.get("checked_at"), "valid_from": item.get("valid_from"),
            "valid_until": item.get("valid_until")}


class Service:
    def __init__(self, store, origin="http://127.0.0.1:8787"):
        self.store, self.origin = store, origin
        self.allowed_origins = {origin, origin.replace("127.0.0.1", "localhost")}

    def now(self, state):
        return timestamp(state["clock"])

    def handle(self, method, path, headers=None, body=None, request_id=None):
        headers = {key.lower(): value for key, value in (headers or {}).items()}
        request_id = request_id or uid()
        data = {} if body is None else body
        try:
            with self.store.transaction() as tx:
                actor, session = None, None
                if method == "GET" and path == "/api/meta":
                    return Reply(body={"name": "SehatAman", "urdu_name": "صحت امان",
                                       "tagline": "Apni sehat. Apna ikhtiyar.", "version": "0.5.0",
                                       "synthetic": True, "clock": tx.state["clock"],
                                       "local_stakeholder_validation": "pending", "step5_authorized": True,
                                       "engineering_validation": "120 scenarios and 500 coordinated traces passed; human review pending"})
                if method not in ("GET", "HEAD"):
                    if headers.get("origin") not in self.allowed_origins:
                        tx.audit("origin_rejected", outcome="denied", reason="origin", request_id=request_id)
                        return Reply(403, {"error": "origin", "message": "Use the local application to make changes."})
                if method == "POST" and path == "/api/sessions":
                    return self._login(tx, data, request_id)
                if method == "POST" and path == "/api/recovery-requests":
                    fields(data, ["account"], ["account"])
                    account = text(data["account"], 100)
                    key = keyed(self.store.lookup_key, ("recovery:" + account.casefold()).encode())
                    tx.state["recoveries"].append({"id": uid(), "account_ref": key,
                                                  "status": "pending_local_identity_review", "time": tx.state["clock"]})
                    tx.state["recoveries"] = tx.state["recoveries"][-100:]
                    tx.audit("recovery_requested", request_id=request_id)
                    return Reply(202, {"message": "If eligible, recovery will require a separate local identity review. No access has been granted."})
                try:
                    actor, session = self._authenticate(tx, headers)
                except ApiError as error:
                    tx.audit("authentication_required", outcome="denied", reason=error.code, request_id=request_id)
                    return Reply(error.status, {"error": error.code, "message": error.message})
                if method not in ("GET", "HEAD"):
                    supplied = headers.get("x-csrf-token", "")
                    if not supplied or digest(supplied.encode()) != session["csrf_hash"]:
                        tx.audit("csrf_rejected", actor, "denied", reason="csrf", request_id=request_id)
                        return Reply(403, {"error": "csrf", "message": "Refresh the application and try again."})
                before = deepcopy(tx.state)
                pending_length = len(tx.pending)
                try:
                    reply = self._dispatch(tx, actor, session, method, path, data, request_id)
                    if len(tx.pending) == pending_length:
                        tx.audit("scoped_request_completed", actor, object_id=actor["org_id"] or actor["id"],
                                 reason="authenticated_scope", request_id=request_id)
                except ApiError as error:
                    tx.state = before
                    del tx.pending[pending_length:]
                    clinical = re.fullmatch(r"/api/report-versions/([a-f0-9-]{36})(/file)?", path)
                    version = tx.state["versions"].get(clinical[1]) if clinical else None
                    if version:
                        tx.audit("clinical_access_denied", actor, "denied", object_id=version["series_id"],
                                 patient_id=version["package"]["manifest"]["patient_id"], version_id=version["id"],
                                 reason=error.code, request_id=request_id)
                    else:
                        tx.audit("request_denied", actor, "denied", reason=error.code, request_id=request_id)
                    reply = Reply(error.status, {"error": error.code, "message": error.message})
                return reply
        except IntegrityFailure:
            return Reply(503, {"error": "integrity_or_audit_unavailable",
                               "message": "Release is held because required integrity or audit evidence is unavailable. Local review is required."})
        except ApiError as error:
            return Reply(error.status, {"error": error.code, "message": error.message})

    def _login(self, tx, data, request_id):
        fields(data, ["username", "password", "totp"], ["username", "password", "totp"])
        username = text(data["username"], 100).casefold()
        password, factor = text(data["password"], 200, empty=True), text(data["totp"], 30, empty=True)
        now = time.time()
        failure_key = keyed(self.store.lookup_key, ("login:" + username).encode())
        failures = tx.state["failures"]
        for old in list(failures):
            if now - failures[old]["since"] > 300:
                del failures[old]
        bucket = failures.get(failure_key, {"count": 0, "since": now})
        if bucket["count"] >= 8:
            tx.audit("login_throttled", outcome="denied", reason="rate_limit", request_id=request_id)
            return Reply(429, {"error": "rate_limit", "message": "Too many attempts. Try again later."}, {"Retry-After": "300"})
        actor = next((item for item in tx.state["users"].values() if item["username"] == username), None)
        encoded = actor["password_hash"] if actor else tx.state["dummy_password"]
        verified = password_ok(encoded, password)
        counter = valid_factor(actor["factor_secret"], factor, actor["last_factor_counter"], now) if actor else None
        if not actor or not verified or counter is None or not actor["active"]:
            failures[failure_key] = {"since": bucket["since"], "count": bucket["count"] + 1}
            tx.audit("login_failed", outcome="denied", reason="invalid_credentials", request_id=request_id)
            return Reply(401, {"error": "invalid_credentials", "message": "The account details or verification code could not be confirmed."})
        actor["last_factor_counter"] = counter
        failures.pop(failure_key, None)
        cookie, csrf = token(), token()
        for key in list(actor["sessions"]):
            if actor["sessions"][key]["expires_at"] <= now:
                del actor["sessions"][key]
        if len(actor["sessions"]) >= 5:
            del actor["sessions"][min(actor["sessions"], key=lambda key: actor["sessions"][key]["created_at"])]
        actor["sessions"][digest(cookie.encode())] = {"created_at": now, "last_seen": now,
                                                     "expires_at": now + 28800, "csrf": csrf,
                                                     "csrf_hash": digest(csrf.encode()), "second_factor": True}
        tx.audit("login_succeeded", actor, request_id=request_id)
        return Reply(200, {"user": self._user(actor), "csrf": csrf},
                     {"Set-Cookie": "sa_session=" + cookie + "; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800"})

    def _authenticate(self, tx, headers):
        try:
            cookie = SimpleCookie()
            cookie.load(headers.get("cookie", ""))
            value = cookie["sa_session"].value
        except (CookieError, KeyError):
            raise ApiError(401, "sign_in_required", "Sign in to continue.")
        if len(value) > 100:
            raise ApiError(401, "sign_in_required", "Sign in to continue.")
        key, now = digest(value.encode()), time.time()
        for actor in tx.state["users"].values():
            session = actor["sessions"].get(key)
            if session:
                if (not actor["active"] or not session.get("second_factor") or now >= session["expires_at"]
                        or now - session["last_seen"] >= 1200):
                    actor["sessions"].pop(key, None)
                    raise ApiError(401, "session_expired", "Your session has ended. Sign in again.")
                session["last_seen"] = now
                return actor, session
        raise ApiError(401, "sign_in_required", "Sign in to continue.")

    @staticmethod
    def _user(actor):
        return {key: actor[key] for key in ("id", "alias", "username", "label", "role", "org_id")}

    @staticmethod
    def _role(actor, *roles):
        if actor["role"] not in roles:
            raise ApiError()

    def _org_valid(self, state, actor):
        org = state["organizations"].get(actor["org_id"])
        if not org or not valid_evidence(org["evidence"], self.now(state)):
            raise ApiError(403, "source_unavailable", "Current organization verification is required.")
        return org

    def _affiliation(self, state, physician, hospital):
        return next((item for item in state["affiliations"].values()
                     if item["physician_id"] == physician and item["hospital_id"] == hospital), None)

    def _eligible(self, state, physician, affiliation=None):
        profile = state["profiles"].get(physician)
        if not profile or not state["users"].get(physician, {}).get("active"):
            return False
        now = self.now(state)
        affiliation = affiliation or self._affiliation(state, physician, profile["hospital_id"])
        org = state["organizations"].get(profile["hospital_id"])
        return bool(affiliation and org and profile["profile_status"] == "submitted"
                    and valid_evidence(profile["binding_evidence"], now)
                    and valid_evidence(profile["registration"], now)
                    and valid_evidence(affiliation["evidence"], now)
                    and valid_evidence(org["evidence"], now))

    def _slots(self, state, physician):
        start = (int(self.now(state)) // 1800 + 1) * 1800
        busy = {item["starts_at"] for item in state["appointments"].values()
                if item["physician_id"] == physician and item["status"] != "cancelled"}
        return [iso(start + offset * 1800) for offset in range(3) if iso(start + offset * 1800) not in busy]

    def _profile(self, state, item, internal=False):
        now = self.now(state)
        aff = self._affiliation(state, item["id"], item["hospital_id"])
        result = {key: item[key] for key in ("id", "alias", "label", "hospital_id", "specialty", "languages", "location", "fee", "profile_revision")}
        result.update({"hospital_label": state["organizations"][item["hospital_id"]]["label"],
                       "registration": evidence_view(item["registration"], now),
                       "affiliation": evidence_view(aff["evidence"], now) if aff else {"status": "unknown"},
                       "bookable": self._eligible(state, item["id"]),
                       "slots": self._slots(state, item["id"]) if self._eligible(state, item["id"]) else []})
        if internal:
            result.update({"affiliation_id": aff["id"] if aff else None,
                           "affiliation_revision": aff["revision"] if aff else None,
                           "affiliation_role": aff["role"] if aff else None,
                           "binding": evidence_view(item["binding_evidence"], now),
                           "profile_status": item["profile_status"], "submitted_at": item["submitted_at"]})
        return result

    def _patient_valid(self, state, patient):
        return bool(patient and patient["adult"] and valid_evidence(patient["identity"], self.now(state)))

    def _package_valid(self, state, version):
        package = version["package"]
        manifest = package["manifest"]
        series = state["series"].get(version["series_id"])
        if not series:
            return False
        order = state["orders"].get(manifest.get("order_id"))
        patient = state["patients"].get(manifest.get("patient_id"))
        lab = state["organizations"].get(manifest.get("lab_id"))
        submitter = state["users"].get(manifest.get("submitter_id"))
        approver = state["users"].get(manifest.get("approver_id"))
        try:
            return bool(order and patient and lab and submitter and approver
                        and manifest["synthetic"] is True
                        and manifest["lab_id"] == series["lab_id"] == order["lab_id"]
                        and manifest["patient_id"] == series["patient_id"] == order["patient_id"]
                        and manifest["order_id"] == series["order_id"]
                        and manifest["specimen_id"] == order["specimen_id"]
                        and manifest["specimen_alias"] == order["specimen_alias"]
                        and manifest["lab_patient_id"] == order["lab_patient_id"]
                        and manifest["cnic_lookup"] == patient["cnic_lookup"]
                        and manifest["secondary_dob"] == patient["dob"]
                        and manifest["source_report_id"] == series["source_report_id"]
                        and submitter["role"] == "lab_submitter" and approver["role"] == "lab_approver"
                        and submitter["org_id"] == approver["org_id"] == lab["id"]
                        and submitter["id"] != approver["id"]
                        and package["content"] == report_text(manifest)
                        and verify_package(self.store, lab["alias"], package))
        except (KeyError, ValueError, TypeError):
            return False

    def _grant_ok(self, state, grant, version, physician):
        manifest = version["package"]["manifest"]
        appointment = state["appointments"].get(grant["appointment_id"])
        aff = state["affiliations"].get(grant["affiliation_id"])
        now = self.now(state)
        return bool(appointment and aff and grant["status"] == "active"
                    and grant["physician_id"] == physician and grant["patient_id"] == manifest["patient_id"]
                    and version["id"] in grant["version_ids"] and grant["purpose"] == "consultation"
                    and timestamp(grant["starts_at"]) <= now < timestamp(grant["expires_at"])
                    and appointment["status"] in ("booked", "confirmed")
                    and appointment["patient_id"] == grant["patient_id"]
                    and appointment["physician_id"] == physician
                    and appointment["hospital_id"] == grant["hospital_id"] == aff["hospital_id"]
                    and appointment["affiliation_id"] == aff["id"] and aff["physician_id"] == physician
                    and self._eligible(state, physician, aff))

    def _access(self, state, actor, version):
        if not version or version["status"] not in ("accepted", "superseded"):
            return False
        manifest = version["package"]["manifest"]
        patient = state["patients"].get(manifest.get("patient_id"))
        if actor["role"] == "patient":
            allowed = manifest.get("patient_id") == actor["id"] and self._patient_valid(state, patient)
        elif actor["role"] in ("lab_submitter", "lab_approver"):
            order = state["orders"].get(manifest.get("order_id"))
            allowed = bool(order and actor["org_id"] == manifest.get("lab_id") and actor["id"] in order["assigned_staff"])
        elif actor["role"] == "physician":
            allowed = self._patient_valid(state, patient) and any(self._grant_ok(state, grant, version, actor["id"])
                                                                  for grant in state["grants"].values())
        else:
            allowed = False
        if allowed and not self._package_valid(state, version):
            raise ApiError(503, "report_integrity", "The report is held for an integrity review.")
        return bool(allowed)

    def _version(self, state, version, full=False):
        manifest = version["package"]["manifest"]
        series = state["series"][version["series_id"]]
        item = {"id": version["id"], "series_id": series["id"], "report_alias": series["alias"],
                "patient_label": state["patients"][manifest["patient_id"]]["label"],
                "lab_label": state["organizations"][manifest["lab_id"]]["label"],
                "version": manifest["version"], "status": version["status"],
                "issued_at": manifest["issued_at"], "received_at": version["received_at"],
                "target": manifest["target"], "specimen_alias": manifest["specimen_alias"], "synthetic": True}
        if full:
            item.update({key: manifest[key] for key in ("result", "source_report_id", "order_alias", "specimen_type",
                                                       "method", "correction_reason", "predecessor_id", "content_digest")})
            item.update({"submitter": state["users"][manifest["submitter_id"]]["label"],
                         "approver": state["users"][manifest["approver_id"]]["label"],
                         "source_integrity": "Issuer signature and content verified (synthetic)",
                         "accepted_at": version["accepted_at"]})
        return item

    def _release(self, tx, actor, version, request_id, full=False):
        if not self._access(tx.state, actor, version):
            raise ApiError()
        manifest = version["package"]["manifest"]
        tx.audit("release_prepared", actor, object_id=version["series_id"], patient_id=manifest["patient_id"],
                 version_id=version["id"], reason="current_policy_satisfied", request_id=request_id)
        result = self._version(tx.state, version, full)
        if actor["role"] == "physician":
            grants = [grant for grant in tx.state["grants"].values() if self._grant_ok(tx.state, grant, version, actor["id"])]
            grant = max(grants, key=lambda item: timestamp(item["expires_at"]))
            result["permission_expires_at"] = grant["expires_at"]
            result["appointment_alias"] = tx.state["appointments"][grant["appointment_id"]]["alias"]
        return result

    def _appointment(self, state, item):
        return {**{key: item[key] for key in ("id", "alias", "physician_id", "hospital_id", "affiliation_id", "starts_at", "ends_at", "status", "revision")},
                "patient_label": state["patients"][item["patient_id"]]["label"],
                "physician_label": state["profiles"][item["physician_id"]]["label"],
                "hospital_label": state["organizations"][item["hospital_id"]]["label"]}

    def _dispatch(self, tx, actor, session, method, path, data, request_id):
        state, now = tx.state, self.now(tx.state)
        role = actor["role"]
        if method == "GET" and path == "/api/session":
            return Reply(body={"user": self._user(actor), "csrf": session["csrf"], "clock": state["clock"]})
        if method == "DELETE" and path == "/api/session":
            actor["sessions"] = {key: value for key, value in actor["sessions"].items() if value is not session}
            tx.audit("logout", actor, request_id=request_id)
            return Reply(body={"message": "Signed out."}, headers={"Set-Cookie": "sa_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"})
        if method == "GET" and path == "/api/me/identity":
            self._role(actor, "patient")
            patient = state["patients"][actor["id"]]
            tx.audit("identity_summary_viewed", actor, patient_id=actor["id"], request_id=request_id)
            return Reply(body={"masked_cnic": patient["masked_cnic"], "alias": patient["alias"],
                               "identity": evidence_view(patient["identity"], now), "adult": True})
        if method == "GET" and path == "/api/me/reports":
            self._role(actor, "patient")
            if not self._patient_valid(state, state["patients"].get(actor["id"])):
                raise ApiError()
            reports = []
            for series in state["series"].values():
                if series["patient_id"] == actor["id"]:
                    version = state["versions"][series["current_version_id"]]
                    if self._access(state, actor, version):
                        reports.append(self._release(tx, actor, version, request_id))
            tx.audit("own_history_viewed", actor, patient_id=actor["id"], request_id=request_id)
            return Reply(body={"reports": sorted(reports, key=lambda item: item["issued_at"], reverse=True)})
        match = re.fullmatch(r"/api/me/reports/([a-f0-9-]{36})/versions", path)
        if method == "GET" and match:
            self._role(actor, "patient")
            series = state["series"].get(match[1])
            if not series or series["patient_id"] != actor["id"]:
                raise ApiError()
            versions = [self._release(tx, actor, version, request_id, True) for version in state["versions"].values()
                        if version["series_id"] == series["id"] and version["status"] in ("accepted", "superseded")]
            return Reply(body={"versions": sorted(versions, key=lambda item: item["version"], reverse=True)})
        match = re.fullmatch(r"/api/report-versions/([a-f0-9-]{36})(/file)?", path)
        if method == "GET" and match:
            version = state["versions"].get(match[1])
            released = self._release(tx, actor, version, request_id, True)
            if match[2]:
                return Reply(body=version["package"]["content"].encode("utf-8"),
                             headers={"Content-Type": "text/plain; charset=utf-8",
                                      "Content-Disposition": 'attachment; filename="synthetic-report-v' + str(released["version"]) + '.txt"'})
            return Reply(body={"report": released})
        if method == "GET" and path == "/api/directory/physicians":
            self._role(actor, "patient")
            return Reply(body={"physicians": [self._profile(state, profile) for profile in state["profiles"].values()
                                               if profile["profile_status"] == "submitted"]})
        if method == "GET" and path in ("/api/me/appointments", "/api/physician/appointments"):
            self._role(actor, "patient" if path.startswith("/api/me/") else "physician")
            key = "patient_id" if role == "patient" else "physician_id"
            return Reply(body={"appointments": [self._appointment(state, item) for item in state["appointments"].values()
                                                 if item[key] == actor["id"]]})
        if method == "POST" and path == "/api/appointments":
            self._role(actor, "patient")
            fields(data, ["physician_id", "starts_at"], ["physician_id", "starts_at"])
            profile = state["profiles"].get(data["physician_id"])
            if not self._patient_valid(state, state["patients"].get(actor["id"])) or not self._eligible(state, data["physician_id"]):
                raise ApiError(409, "recipient_unavailable", "Both independent credential checks and your identity must be current.")
            if data["starts_at"] not in self._slots(state, data["physician_id"]):
                raise ApiError(409, "slot_unavailable", "Choose a currently available appointment slot.")
            aff = self._affiliation(state, profile["id"], profile["hospital_id"])
            identity = uid()
            item = {"id": identity, "alias": f"A{len(state['appointments']) + 1:02d}", "patient_id": actor["id"],
                    "physician_id": profile["id"], "hospital_id": profile["hospital_id"], "affiliation_id": aff["id"],
                    "starts_at": data["starts_at"], "ends_at": iso(timestamp(data["starts_at"]) + 1800),
                    "status": "booked", "revision": 1}
            state["appointments"][identity] = item
            tx.audit("appointment_created", actor, object_id=identity, patient_id=actor["id"], request_id=request_id)
            return Reply(201, {"appointment": self._appointment(state, item), "message": "Appointment booked. No records have been shared."})
        match = re.fullmatch(r"/api/appointments/([a-f0-9-]{36})/status", path)
        if method == "PATCH" and match:
            fields(data, ["status", "expected_revision"], ["status", "expected_revision"])
            item = state["appointments"].get(match[1])
            owner = item and ((role == "patient" and item["patient_id"] == actor["id"])
                              or (role == "physician" and item["physician_id"] == actor["id"]))
            if not owner:
                raise ApiError()
            if data["expected_revision"] != item["revision"] or item["status"] in ("cancelled", "completed"):
                raise ApiError(409, "state_changed", "Appointment status changed. Refresh before continuing.")
            permitted = ["cancelled"] if role == "patient" else ["cancelled", "confirmed", "completed"]
            if data["status"] not in permitted:
                raise ApiError(422, "invalid_status", "Choose a permitted appointment status.")
            item["status"], item["revision"] = data["status"], item["revision"] + 1
            tx.audit("appointment_" + item["status"], actor, object_id=item["id"], patient_id=item["patient_id"], request_id=request_id)
            return Reply(body={"appointment": self._appointment(state, item)})
        if method == "POST" and path == "/api/grants":
            return self._create_grant(tx, actor, data, request_id)
        if method == "GET" and path == "/api/me/sharing":
            self._role(actor, "patient")
            return Reply(body={"grants": [self._grant_view(state, grant) for grant in state["grants"].values() if grant["patient_id"] == actor["id"]]})
        match = re.fullmatch(r"/api/grants/([a-f0-9-]{36})/withdraw", path)
        if method == "POST" and match:
            self._role(actor, "patient")
            fields(data, [])
            grant = state["grants"].get(match[1])
            if not grant or grant["patient_id"] != actor["id"]:
                raise ApiError()
            if grant["status"] != "revoked":
                grant["status"], grant["revoked_at"] = "revoked", state["clock"]
                tx.audit("grant_withdrawn", actor, object_id=grant["id"], patient_id=actor["id"], request_id=request_id)
            return Reply(body={"grant": self._grant_view(state, grant)})
        if method == "GET" and path == "/api/me/access-history":
            self._role(actor, "patient")
            events = []
            for event in tx.history:
                if event.get("patient_id") != actor["id"] or event["action"] not in (
                        "release_prepared", "clinical_access_denied", "appointment_created", "appointment_cancelled",
                        "appointment_confirmed", "appointment_completed", "grant_created", "grant_withdrawn", "report_accepted"):
                    continue
                if event["action"] == "release_prepared" and event["actor_id"] == actor["id"]:
                    continue  # The protected raw audit retains the patient's own browsing.
                item = {key: event.get(key) for key in ("sequence", "action", "actor_label", "role", "outcome", "version_id", "server_time", "test_time")}
                if event["role"] == "patient" and event["actor_id"] != actor["id"]:
                    item["actor_label"] = "Another account"
                version = state["versions"].get(event.get("version_id"))
                if version:
                    item["record_label"] = state["series"][version["series_id"]]["alias"] + " v" + str(version["package"]["manifest"]["version"])
                elif event["action"] in ("grant_created", "grant_withdrawn") and event["object_id"] in state["grants"]:
                    grant = state["grants"][event["object_id"]]
                    item["record_label"] = ", ".join(state["series"][state["versions"][identity]["series_id"]]["alias"]
                                                     + " v" + str(state["versions"][identity]["package"]["manifest"]["version"]) for identity in grant["version_ids"])
                else:
                    item["record_label"] = "Appointment / source event"
                events.append(item)
            return Reply(body={"events": events[-100:][::-1], "meaning": "Release prepared is a server decision; it does not prove human reading."})
        match = re.fullmatch(r"/api/physician/appointments/([a-f0-9-]{36})/records", path)
        if method == "GET" and match:
            self._role(actor, "physician")
            appointment = state["appointments"].get(match[1])
            if not appointment or appointment["physician_id"] != actor["id"]:
                raise ApiError()
            candidates = {version_id for grant in state["grants"].values() if grant["appointment_id"] == appointment["id"]
                          and grant["physician_id"] == actor["id"] for version_id in grant["version_ids"]
                          if version_id in state["versions"] and self._grant_ok(state, grant, state["versions"][version_id], actor["id"])}
            records = [self._release(tx, actor, state["versions"][version_id], request_id) for version_id in candidates
                       if version_id in state["versions"] and self._access(state, actor, state["versions"][version_id])]
            tx.audit("appointment_records_requested", actor, "release_prepared" if records else "no_release",
                     object_id=appointment["id"], patient_id=appointment["patient_id"],
                     reason="current_exact_versions_only", request_id=request_id)
            return Reply(body={"records": records, "message": "Only currently authorized exact versions are included."})
        if method == "GET" and path == "/api/physician/status":
            self._role(actor, "physician")
            return Reply(body={"profile": self._profile(state, state["profiles"][actor["id"]])})
        if path.startswith("/api/lab/"):
            return self._lab(tx, actor, method, path, data, request_id)
        if path.startswith("/api/hospital/"):
            return self._hospital(tx, actor, method, path, data, request_id)
        raise ApiError()

    def _create_grant(self, tx, actor, data, request_id):
        self._role(actor, "patient")
        fields(data, ["appointment_id", "version_ids", "purpose", "starts_at", "expires_at", "acknowledged"],
               ["appointment_id", "version_ids", "purpose", "starts_at", "expires_at", "acknowledged"])
        state, now = tx.state, self.now(tx.state)
        appointment = state["appointments"].get(data["appointment_id"])
        if not appointment or appointment["patient_id"] != actor["id"]:
            raise ApiError()
        if (appointment["status"] not in ("booked", "confirmed")
                or not self._eligible(state, appointment["physician_id"], state["affiliations"][appointment["affiliation_id"]])):
            raise ApiError(409, "recipient_unavailable", "Recipient eligibility or appointment status changed. Review before sharing.")
        versions = data["version_ids"]
        if (not isinstance(versions, list) or not 1 <= len(versions) <= 20
                or not all(isinstance(item, str) for item in versions) or len(set(versions)) != len(versions)
                or data["acknowledged"] is not True or data["purpose"] != "consultation"):
            raise ApiError(422, "explicit_scope_required", "Select exact versions and explicitly confirm consultation sharing.")
        try:
            start, end = timestamp(data["starts_at"]), timestamp(data["expires_at"])
        except (ValueError, TypeError):
            raise ApiError(422, "invalid_interval", "Choose timezone-aware start and expiry times.")
        if not now - 60 <= start < end <= now + 86400:
            raise ApiError(422, "invalid_interval", "Choose an interval starting now or later, ending within 24 hours.")
        for identity in versions:
            version = state["versions"].get(identity)
            if not self._access(state, actor, version):
                raise ApiError()
        identity = uid()
        grant = {"id": identity, "alias": f"G{len(state['grants']) + 1:02d}", "patient_id": actor["id"],
                 "physician_id": appointment["physician_id"], "hospital_id": appointment["hospital_id"],
                 "affiliation_id": appointment["affiliation_id"], "appointment_id": appointment["id"],
                 "version_ids": list(versions), "purpose": "consultation", "starts_at": iso(start),
                 "expires_at": iso(end), "created_at": state["clock"], "status": "active", "revoked_at": None}
        state["grants"][identity] = grant
        tx.audit("grant_created", actor, object_id=identity, patient_id=actor["id"], request_id=request_id)
        return Reply(201, {"grant": self._grant_view(state, grant)})

    def _grant_view(self, state, grant):
        now = self.now(state)
        status = grant["status"]
        if status == "active":
            status = "expired" if now >= timestamp(grant["expires_at"]) else "scheduled" if now < timestamp(grant["starts_at"]) else "active"
        appointment = state["appointments"].get(grant["appointment_id"])
        eligible = bool(appointment and appointment["status"] in ("booked", "confirmed") and self._eligible(state, grant["physician_id"]))
        return {**grant, "effective_status": status if eligible or status != "active" else "blocked_by_eligibility",
                "physician_label": state["profiles"][grant["physician_id"]]["label"],
                "hospital_label": state["organizations"][grant["hospital_id"]]["label"],
                "versions": [self._version(state, state["versions"][identity]) for identity in grant["version_ids"]]
                if self._patient_valid(state, state["patients"].get(grant["patient_id"])) else []}

    def _submission_view(self, state, item):
        manifest = item["package"]["manifest"]
        order = state["orders"].get(manifest.get("order_id"))
        patient = (state["patients"].get(order["patient_id"]) if order and order["lab_id"] == item["lab_id"]
                   and manifest.get("patient_id") == order["patient_id"] else None)
        return {"id": item["id"], "message_id": manifest.get("message_id"), "source_report_id": manifest.get("source_report_id"),
                "version": manifest.get("version"), "status": item["status"], "findings": item["findings"],
                "submitted_at": item["submitted_at"], "submitter": state["users"][item["submitter_id"]]["label"],
                "expected_predecessor_id": manifest.get("predecessor_id"),
                "masked_cnic": patient["masked_cnic"] if patient else "Unresolved synthetic linkage",
                "order_alias": manifest.get("order_alias"), "specimen_alias": manifest.get("specimen_alias"),
                "accepted_version_id": item.get("accepted_version_id")}

    def _source_findings(self, state, actor, package):
        manifest = package.get("manifest", {})
        org = state["organizations"][actor["org_id"]]
        findings = []
        if not verify_package(self.store, org["alias"], package):
            findings.append("issuer_or_content_integrity_failed")
        order = state["orders"].get(manifest.get("order_id"))
        if not order or order["lab_id"] != actor["org_id"] or actor["id"] not in order["assigned_staff"]:
            return findings + ["source_order_unavailable"]
        patient = state["patients"][order["patient_id"]]
        approver = state["users"].get(manifest.get("approver_id"))
        submitter = state["users"].get(manifest.get("submitter_id"))
        if (not submitter or submitter["role"] != "lab_submitter" or submitter["org_id"] != org["id"]
                or not approver or approver["role"] != "lab_approver" or approver["org_id"] != org["id"]
                or approver["id"] == submitter["id"]):
            findings.append("distinct_source_approval_required")
        if (manifest.get("lab_id") != org["id"] or manifest.get("lab_alias") != org["alias"]
                or manifest.get("patient_id") != order["patient_id"]
                or manifest.get("cnic_lookup") != patient["cnic_lookup"]
                or manifest.get("secondary_dob") != patient["dob"]
                or manifest.get("specimen_id") != order["specimen_id"]
                or manifest.get("specimen_alias") != order["specimen_alias"]
                or manifest.get("lab_patient_id") != order["lab_patient_id"]
                or not self._patient_valid(state, patient)):
            findings.append("identity_order_or_specimen_mismatch")
        try:
            if (manifest["synthetic"] is not True or package["content"] != report_text(manifest)
                    or not manifest["target"] or not manifest["method"] or not manifest["specimen_type"]
                    or not isinstance(manifest["version"], int) or isinstance(manifest["version"], bool)
                    or timestamp(manifest["issued_at"]) > self.now(state)):
                findings.append("report_context_invalid")
        except (KeyError, ValueError, TypeError):
            findings.append("report_context_invalid")
        series = next((item for item in state["series"].values() if item["lab_id"] == org["id"]
                       and item["source_report_id"] == manifest.get("source_report_id")), None)
        if series:
            head = state["versions"][series["current_version_id"]]
            if (series["patient_id"] != order["patient_id"] or series["order_id"] != order["id"]
                    or manifest.get("predecessor_id") != head["id"]
                    or manifest.get("version") != head["package"]["manifest"]["version"] + 1
                    or not manifest.get("correction_reason")):
                findings.append("predecessor_or_correction_conflict")
        elif manifest.get("version") != 1 or manifest.get("predecessor_id") is not None:
            findings.append("initial_version_invalid")
        return list(dict.fromkeys(findings))

    def _submit(self, tx, actor, data, request_id, report_id=None, raw=False):
        self._role(actor, "lab_submitter")
        state = tx.state
        org = self._org_valid(state, actor)
        if raw:
            fields(data, ["package"], ["package"])
            package = data["package"]
            if not isinstance(package, dict) or set(package) != {"manifest", "content", "signature"} or not isinstance(package.get("manifest"), dict):
                raise ApiError(422, "invalid_package", "Use a bounded structured synthetic report package.")
            manifest = package["manifest"]
            if any(not isinstance(value, (str, int, bool, type(None))) for value in manifest.values()):
                raise ApiError(422, "invalid_package", "Manifest fields must be bounded scalar values.")
            if any(isinstance(value, str) and len(value) > 1000 for value in manifest.values()):
                raise ApiError(422, "invalid_package", "Manifest fields exceed the permitted length.")
            for name in ("order_id", "patient_id", "lab_id", "submitter_id"):
                if not isinstance(manifest.get(name), str):
                    raise ApiError(422, "invalid_package", "Manifest identity fields are required.")
            if manifest.get("approver_id") is not None and not isinstance(manifest["approver_id"], str):
                raise ApiError(422, "invalid_package", "Approver reference must be an identifier or absent.")
            if (not isinstance(package["content"], str) or len(package["content"]) > 16000
                    or not isinstance(package["signature"], str) or len(package["signature"]) > 200):
                raise ApiError(422, "invalid_package", "The structured package is invalid.")
        else:
            allowed = ["order_id", "cnic", "dob", "specimen_alias", "lab_patient_id", "source_report_id", "message_id",
                       "target", "result", "method", "approver_id", "predecessor_id", "version", "correction_reason"]
            fields(data, allowed, ["order_id", "cnic", "dob", "specimen_alias", "source_report_id", "message_id", "result", "approver_id"])
            order = state["orders"].get(data["order_id"])
            if not order or order["lab_id"] != org["id"] or actor["id"] not in order["assigned_staff"]:
                raise ApiError()
            try:
                cnic = normalize_cnic(data["cnic"])
                datetime.strptime(data["dob"], "%Y-%m-%d")
            except (ValueError, TypeError):
                raise ApiError(422, "invalid_identity_input", "Check the synthetic CNIC and birth-date format.")
            predecessor, number, source_id = data.get("predecessor_id"), data.get("version", 1), text(data["source_report_id"], 64)
            if report_id:
                series = state["series"].get(report_id)
                if not series or series["lab_id"] != org["id"]:
                    raise ApiError()
                source_id = series["source_report_id"]
            if not isinstance(number, int) or isinstance(number, bool) or not 1 <= number <= 1000:
                raise ApiError(422, "invalid_version", "Choose a whole-number source version.")
            if number > 1 and not text(data.get("correction_reason", ""), 300):
                raise ApiError(422, "reason_required", "A correction reason is required.")
            approver = state["users"].get(data["approver_id"])
            if not approver or approver["role"] != "lab_approver" or approver["org_id"] != org["id"]:
                raise ApiError(422, "approver_required", "Select the authorized distinct approver for your laboratory.")
            patient = state["patients"][order["patient_id"]]
            manifest = {"lab_id": org["id"], "lab_alias": org["alias"], "patient_id": patient["id"],
                        "patient_alias": patient["alias"], "cnic_lookup": keyed(self.store.lookup_key, cnic.encode()),
                        "secondary_dob": data["dob"], "order_id": order["id"], "order_alias": order["alias"],
                        "specimen_id": order["specimen_id"], "specimen_alias": text(data["specimen_alias"], 50),
                        "lab_patient_id": text(data.get("lab_patient_id", order["lab_patient_id"]), 80),
                        "specimen_type": order["specimen_type"], "source_report_id": source_id,
                        "message_id": text(data["message_id"], 80), "version": number, "predecessor_id": predecessor,
                        "correction_reason": text(data.get("correction_reason", ""), 300, empty=True),
                        "method": text(data.get("method", "Simulated qualitative PCR"), 100),
                        "target": text(data.get("target", "Invented target X"), 100),
                        "result": text(data["result"], 500), "issued_at": state["clock"],
                        "submitter_id": actor["id"], "approver_id": approver["id"], "synthetic": True}
            package = sign_package(self.store, org["alias"], manifest, report_text(manifest))
        message_id = text(manifest.get("message_id"), 80)
        fingerprint = digest(canonical({"input": data, "report_context": report_id, "raw_ingest": raw}))
        previous = next((item for item in state["submissions"].values() if item["lab_id"] == org["id"]
                         and item["package"]["manifest"].get("message_id") == message_id), None)
        if previous:
            if previous["request_digest"] != fingerprint:
                raise ApiError(409, "message_conflict", "This source message identifier already has a different payload.")
            tx.audit("submission_replayed", actor, object_id=previous["id"], reason="same_payload_no_effect", request_id=request_id)
            return Reply(body={"submission": self._submission_view(state, previous), "replay": True})
        order = state["orders"].get(manifest.get("order_id"))
        if not order or order["lab_id"] != org["id"] or actor["id"] not in order["assigned_staff"]:
            raise ApiError()
        findings = self._source_findings(state, actor, package)
        if manifest.get("submitter_id") != actor["id"]:
            findings.append("authenticated_submitter_mismatch")
        identity = uid()
        item = {"id": identity, "lab_id": org["id"], "submitter_id": actor["id"], "package": package,
                "request_digest": fingerprint, "status": "held" if findings else "awaiting_approval",
                "findings": findings, "submitted_at": state["clock"], "accepted_version_id": None}
        state["submissions"][identity] = item
        tx.audit("submission_" + item["status"], actor, object_id=identity, reason="validation_failed" if findings else "pending_distinct_approval", request_id=request_id)
        return Reply(201, {"submission": self._submission_view(state, item)})

    def _lab(self, tx, actor, method, path, data, request_id):
        self._role(actor, "lab_submitter", "lab_approver")
        state = tx.state
        if method == "GET" and path == "/api/lab/workspace":
            orders = []
            for order in state["orders"].values():
                if order["lab_id"] == actor["org_id"] and actor["id"] in order["assigned_staff"]:
                    patient = state["patients"][order["patient_id"]]
                    orders.append({key: order[key] for key in ("id", "alias", "specimen_alias", "specimen_type", "lab_patient_id")}
                                  | {"patient_label": patient["label"], "masked_cnic": patient["masked_cnic"], "dob": patient["dob"]})
            versions = [self._release(tx, actor, version, request_id) for version in state["versions"].values()
                        if self._access(state, actor, version)]
            approvers = [{"id": user["id"], "label": user["label"]} for user in state["users"].values()
                         if user["org_id"] == actor["org_id"] and user["role"] == "lab_approver" and user["active"]]
            return Reply(body={"orders": orders, "reports": versions, "approvers": approvers,
                               "organization": state["organizations"][actor["org_id"]]["label"]})
        if method == "GET" and path == "/api/lab/submissions":
            items = [self._submission_view(state, item) for item in state["submissions"].values() if item["lab_id"] == actor["org_id"]]
            return Reply(body={"submissions": items[::-1]})
        if method == "POST" and path in ("/api/lab/submissions", "/api/lab/ingest"):
            return self._submit(tx, actor, data, request_id, raw=path.endswith("ingest"))
        match = re.fullmatch(r"/api/lab/reports/([a-f0-9-]{36})/amendments", path)
        if method == "POST" and match:
            return self._submit(tx, actor, data, request_id, report_id=match[1])
        match = re.fullmatch(r"/api/lab/reports/([a-f0-9-]{36})/versions", path)
        if method == "GET" and match:
            series = state["series"].get(match[1])
            if not series or series["lab_id"] != actor["org_id"]:
                raise ApiError()
            return Reply(body={"versions": [self._release(tx, actor, version, request_id, True) for version in state["versions"].values()
                                            if version["series_id"] == series["id"]]})
        match = re.fullmatch(r"/api/lab/submissions/([a-f0-9-]{36})/(approve|return)", path)
        if method == "POST" and match:
            self._role(actor, "lab_approver")
            self._org_valid(state, actor)
            item = state["submissions"].get(match[1])
            if not item or item["lab_id"] != actor["org_id"] or item["submitter_id"] == actor["id"]:
                raise ApiError()
            if match[2] == "return":
                fields(data, ["reason"], ["reason"])
                if item["status"] == "accepted":
                    raise ApiError(409, "already_accepted", "Accepted versions cannot be returned or edited.")
                item["return_reason"] = text(data["reason"], 300)
                item["status"] = "returned"
                tx.audit("submission_returned", actor, object_id=item["id"], request_id=request_id)
                return Reply(body={"submission": self._submission_view(state, item)})
            fields(data, ["expected_predecessor_id"], ["expected_predecessor_id"])
            manifest = item["package"]["manifest"]
            if manifest.get("approver_id") != actor["id"]:
                raise ApiError(409, "approval_binding", "This source package names a different approver.")
            if item["status"] == "accepted":
                return Reply(body={"submission": self._submission_view(state, item), "replay": True})
            if item["status"] != "awaiting_approval" or data["expected_predecessor_id"] != manifest.get("predecessor_id"):
                raise ApiError(409, "validation_required", "Correct and resubmit this package before approval.")
            findings = self._source_findings(state, actor, item["package"])
            if findings:
                raise ApiError(409, "validation_changed", "Identity, integrity or predecessor validation no longer passes.")
            series = next((value for value in state["series"].values() if value["lab_id"] == actor["org_id"]
                           and value["source_report_id"] == manifest["source_report_id"]), None)
            if series is None:
                series_id = uid()
                series = {"id": series_id, "alias": "R" + str(len(state["series"]) + 1).zfill(2),
                          "lab_id": actor["org_id"], "patient_id": manifest["patient_id"],
                          "source_report_id": manifest["source_report_id"], "order_id": manifest["order_id"],
                          "current_version_id": None}
                state["series"][series_id] = series
            else:
                state["versions"][series["current_version_id"]]["status"] = "superseded"
            identity = uid()
            version = {"id": identity, "series_id": series["id"], "status": "accepted", "package": deepcopy(item["package"]),
                       "received_at": item["submitted_at"], "accepted_at": state["clock"], "synthetic": True}
            state["versions"][identity] = version
            series["current_version_id"] = identity
            item["status"], item["accepted_version_id"] = "accepted", identity
            tx.audit("report_accepted", actor, object_id=series["id"], patient_id=manifest["patient_id"],
                     version_id=identity, request_id=request_id)
            return Reply(body={"submission": self._submission_view(state, item), "version": self._version(state, version)})
        raise ApiError()

    def _hospital(self, tx, actor, method, path, data, request_id):
        self._role(actor, "hospital")
        state = tx.state
        if method == "GET" and path in ("/api/hospital/profiles", "/api/hospital/affiliations"):
            return Reply(body={"profiles": [self._profile(state, profile, True) for profile in state["profiles"].values()
                                           if profile["hospital_id"] == actor["org_id"]]})
        match = re.fullmatch(r"/api/hospital/profiles/([a-f0-9-]{36})", path)
        if (method == "PATCH" and match) or (method == "POST" and path == "/api/hospital/profiles"):
            self._org_valid(state, actor)
            allowed = ["specialty", "languages", "location", "fee", "expected_revision"]
            if method == "POST":
                allowed += ["physician_id"]
            fields(data, allowed, ["specialty", "languages", "location", "fee", "expected_revision"] + (["physician_id"] if method == "POST" else []))
            identity = match[1] if match else data["physician_id"]
            profile = state["profiles"].get(identity)
            if not profile or profile["hospital_id"] != actor["org_id"]:
                raise ApiError()
            if not valid_evidence(profile["binding_evidence"], self.now(state)):
                raise ApiError(409, "binding_review", "Independent account binding needs review before profile submission.")
            if data["expected_revision"] != profile["profile_revision"]:
                raise ApiError(409, "state_changed", "Profile changed. Refresh before submitting.")
            if (not isinstance(data["languages"], list) or not 1 <= len(data["languages"]) <= 5
                    or not all(isinstance(value, str) and value in ("Urdu", "English", "Punjabi", "Sindhi", "Pashto", "Balochi") for value in data["languages"])
                    or isinstance(data["fee"], bool) or not isinstance(data["fee"], int) or not 0 <= data["fee"] <= 100000):
                raise ApiError(422, "invalid_profile", "Choose permitted language and synthetic fee values.")
            state["profile_history"].append(deepcopy(profile))
            profile.update({"specialty": text(data["specialty"], 100), "location": text(data["location"], 100),
                            "languages": data["languages"], "fee": data["fee"], "submitted_by": actor["id"],
                            "submitted_at": state["clock"], "profile_status": "submitted",
                            "profile_revision": profile["profile_revision"] + 1})
            tx.audit("hospital_profile_submitted", actor, object_id=identity, request_id=request_id)
            return Reply(body={"profile": self._profile(state, profile, True)})
        match = re.fullmatch(r"/api/hospital/profiles/([a-f0-9-]{36})/registration-review", path)
        if method == "POST" and match:
            fields(data, [])
            profile = state["profiles"].get(match[1])
            if not profile or profile["hospital_id"] != actor["org_id"]:
                raise ApiError()
            state.setdefault("verification_requests", []).append({"id": uid(), "physician_id": profile["id"],
                                                                    "status": "pending_independent_local_review", "time": state["clock"]})
            tx.audit("independent_registration_review_requested", actor, object_id=profile["id"], request_id=request_id)
            return Reply(202, {"message": "Independent simulated review requested. Registration status has not changed."})
        match = re.fullmatch(r"/api/hospital/affiliations/([a-f0-9-]{36})/status", path)
        if method == "POST" and match:
            self._org_valid(state, actor)
            fields(data, ["status", "reason", "expected_revision", "valid_from", "valid_until"], ["status", "reason", "expected_revision"])
            aff = state["affiliations"].get(match[1])
            if not aff or aff["hospital_id"] != actor["org_id"]:
                raise ApiError()
            if aff["revision"] != data["expected_revision"]:
                raise ApiError(409, "state_changed", "Affiliation changed. Refresh before continuing.")
            if data["status"] not in ("valid", "pending", "suspended", "revoked", "stale"):
                raise ApiError(422, "invalid_status", "Choose a permitted affiliation status.")
            text(data["reason"], 300)
            start = data.get("valid_from", aff["evidence"]["valid_from"])
            end = data.get("valid_until", aff["evidence"]["valid_until"])
            try:
                if not timestamp(start) < timestamp(end) or timestamp(end) - timestamp(start) > 86400 * 90:
                    raise ValueError()
            except (TypeError, ValueError):
                raise ApiError(422, "invalid_interval", "Choose a valid synthetic evidence interval, at most 90 days.")
            state["credential_history"].append({"kind": "hospital_affiliation", "subject_id": aff["id"], "evidence": deepcopy(aff["evidence"])})
            aff["evidence"] = {**aff["evidence"], "id": uid(), "status": data["status"],
                               "valid_from": start, "valid_until": end, "checked_at": state["clock"]}
            aff["revision"], aff["attester_id"] = aff["revision"] + 1, actor["id"]
            tx.audit("affiliation_" + data["status"], actor, object_id=aff["id"], request_id=request_id)
            return Reply(body={"message": "Hospital affiliation saved. Independent professional registration is unchanged.",
                               "profile": self._profile(state, state["profiles"][aff["physician_id"]], True)})
        raise ApiError()
