"""Invented entities only. No external source or real identifiers are imported."""

from datetime import datetime, timedelta
import secrets
import uuid

from .crypto import PASSWORDS, canonical, keyed, new_factor, normalize_cnic
from .issuer import initialize_issuers, report_text, sign_package
from .storage import private_write


def uid():
    return str(uuid.uuid4())


def evidence(reference, status="valid", verifier="Local synthetic fixture verifier"):
    return {"id": uid(), "source_ref": reference, "source": "SIMULATED ONLY",
            "status": status, "valid_from": "2026-10-21T00:00:00+05:00",
            "valid_until": "2026-10-22T00:00:00+05:00",
            "checked_at": "2026-10-21T08:00:00+05:00", "verifier": verifier,
            "person_match": True, "synthetic": True}


def make_seed(store):
    initialize_issuers(store)
    state = {"synthetic": True, "schema": 1, "clock": "2026-10-21T10:00:00+05:00",
             "fixture_profile": "clean-live-demo-v1", "users": {}, "patients": {},
             "organizations": {}, "profiles": {}, "affiliations": {}, "orders": {},
             "series": {}, "versions": {}, "submissions": {}, "appointments": {},
             "grants": {}, "recoveries": [], "failures": {}, "credential_history": [],
             "profile_history": [], "dummy_password": PASSWORDS.hash(secrets.token_urlsafe(24))}
    credentials = []

    def user(alias, label, role, org=None):
        identity, password, factor = uid(), "Demo-" + secrets.token_urlsafe(12), new_factor()
        state["users"][identity] = {"id": identity, "alias": alias, "username": alias.lower(),
                                  "label": label, "role": role, "org_id": org,
                                  "password_hash": PASSWORDS.hash(password), "factor_secret": factor,
                                  "last_factor_counter": -1, "active": True, "sessions": {}}
        credentials.append({"username": alias.lower(), "alias": alias, "role": role,
                            "password": password, "totp_secret": factor})
        return identity

    orgs = {}
    for alias, kind, label in [("L01", "laboratory", "Demo Molecular Lab L01"),
                               ("L02", "laboratory", "Demo Molecular Lab L02"),
                               ("H01", "hospital", "Demo Hospital H01")]:
        identity = uid()
        orgs[alias] = identity
        state["organizations"][identity] = {"id": identity, "alias": alias, "kind": kind,
                                             "label": label, "evidence": evidence("SIM-ORG-" + alias)}
    staff = {}
    for lab in ("L01", "L02"):
        staff[lab] = {"submitter": user(lab + "-S01", "Demo Lab Submitter " + lab + "-S01", "lab_submitter", orgs[lab]),
                      "approver": user(lab + "-A02", "Demo Lab Approver " + lab + "-A02", "lab_approver", orgs[lab])}
    manager = user("H01-M01", "Demo Hospital Manager H01-M01", "hospital", orgs["H01"])
    patient_ids = {}
    for number in range(1, 6):
        alias = f"P{number:02d}"
        identity = user(alias, "Demo Patient " + alias, "patient")
        patient_ids[alias] = identity
        cnic = f"00000-000000{number}-0"
        state["patients"][identity] = {"id": identity, "alias": alias, "label": "Demo Patient " + alias,
                                       "cnic": cnic, "cnic_lookup": keyed(store.lookup_key, normalize_cnic(cnic).encode()),
                                       "masked_cnic": "Test CNIC ending " + normalize_cnic(cnic)[-4:],
                                       "dob": f"{1989 + number}-01-01", "adult": True,
                                       "identity": evidence("SIM-ID-" + alias)}
    for number in range(1, 4):
        alias = f"D{number:02d}"
        identity = user(alias, "Demo Physician " + alias, "physician", orgs["H01"])
        reg = evidence("SIM-PMDC-" + alias, "pending" if number == 3 else "valid")
        reg.update({"registered_qualifications": "Invented postgraduate qualification",
                    "person_match": True, "professional_reference": "SIM-PMDC-" + alias})
        state["profiles"][identity] = {"id": identity, "alias": alias, "label": "Demo Physician " + alias,
                                      "hospital_id": orgs["H01"], "specialty": "Pulmonology" if number == 2 else "Internal medicine",
                                      "languages": ["Urdu", "English"] if number == 1 else ["Urdu"] if number == 2 else ["English"],
                                      "location": "Demo City", "fee": [1500, 1800, 1600][number - 1],
                                      "profile_status": "submitted", "profile_revision": 1,
                                      "submitted_by": manager, "submitted_at": state["clock"],
                                      "binding_evidence": evidence("SIM-BIND-" + alias), "registration": reg}
        affiliation_id = uid()
        state["affiliations"][affiliation_id] = {"id": affiliation_id, "physician_id": identity,
                                                "hospital_id": orgs["H01"], "revision": 1,
                                                "role": "Synthetic consultant", "attester_id": manager,
                                                "evidence": evidence("SIM-AFF-H01-" + alias,
                                                                     "pending" if number == 2 else "valid",
                                                                     "Authorized demo hospital office H01")}
    orders_by_alias = {}
    for number, (lab, patient) in enumerate([("L01", "P01"), ("L02", "P01"), ("L01", "P02"),
                                            ("L02", "P03"), ("L01", "P04"), ("L02", "P05")], 1):
        identity = uid()
        order = {"id": identity, "alias": f"O{number:02d}", "specimen_id": uid(),
                 "specimen_alias": f"S{number:02d}", "lab_id": orgs[lab], "patient_id": patient_ids[patient],
                 "lab_patient_id": f"SIM-{lab}-{patient}", "specimen_type": "Respiratory swab (synthetic)",
                 "collected_at": "2026-10-20T12:00:00+05:00", "assigned_staff": list(staff[lab].values())}
        state["orders"][identity] = order
        orders_by_alias[order["alias"]] = order
    for report_alias, order_alias in [("R01", "O01"), ("R02", "O02"), ("R03", "O03")]:
        order = orders_by_alias[order_alias]
        org = state["organizations"][order["lab_id"]]
        patient = state["patients"][order["patient_id"]]
        lab = org["alias"]
        series_id, version_id = uid(), uid()
        manifest = {"lab_id": org["id"], "lab_alias": lab, "patient_id": patient["id"],
                    "patient_alias": patient["alias"], "cnic_lookup": patient["cnic_lookup"],
                    "secondary_dob": patient["dob"],
                    "order_id": order["id"], "order_alias": order_alias,
                    "specimen_id": order["specimen_id"], "specimen_alias": order["specimen_alias"],
                    "specimen_type": order["specimen_type"], "lab_patient_id": order["lab_patient_id"],
                    "source_report_id": "SIM-" + lab + "-" + report_alias,
                    "message_id": "SIM-MSG-" + report_alias + "-V1", "version": 1,
                    "predecessor_id": None, "correction_reason": "", "method": "Simulated qualitative PCR",
                    "target": "Invented target X", "result": "Not detected (synthetic)",
                    "issued_at": "2026-10-20T14:10:00+05:00", "submitter_id": staff[lab]["submitter"],
                    "approver_id": staff[lab]["approver"], "synthetic": True}
        package = sign_package(store, lab, manifest, report_text(manifest))
        state["series"][series_id] = {"id": series_id, "alias": report_alias, "lab_id": org["id"],
                                      "patient_id": patient["id"], "source_report_id": manifest["source_report_id"],
                                      "order_id": order["id"], "current_version_id": version_id}
        state["versions"][version_id] = {"id": version_id, "series_id": series_id, "status": "accepted",
                                        "package": package, "received_at": "2026-10-20T14:11:00+05:00",
                                        "accepted_at": "2026-10-20T14:12:00+05:00", "synthetic": True}
    private_write(store.protected / "demo-accounts.json", canonical(credentials))
    return state
