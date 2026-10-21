"""Implementation-focused checks, separate from the unexecuted Step 5 benchmark."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import http.client
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import unittest
import uuid

from sehataman.bootstrap import bootstrap
from sehataman.crypto import canonical, digest, iso, timestamp, totp
from sehataman.domain import Service
from sehataman.server import LocalServer
from sehataman.storage import IntegrityFailure

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / ".local" / "test-runs" / uuid.uuid4().hex


class MvpChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        RUN.mkdir(parents=True)
        cls.base = RUN / "baseline"
        bootstrap(cls.base)

    def setUp(self):
        # Keep isolated fixture paths within Windows limits after ZIP extraction.
        self.home = RUN / hashlib.sha256(self._testMethodName.encode()).hexdigest()[:16]
        shutil.copytree(self.base, self.home)
        self.store = bootstrap(self.home)
        self.service = Service(self.store)
        with self.store.transaction() as tx:
            self.initial = deepcopy(tx.state)
        self.accounts = json.loads((self.store.protected / "demo-accounts.json").read_text("utf-8"))
        self.clients = {}
        self.users = {user["alias"]: user for user in self.initial["users"].values()}
        self.p01, self.p02, self.d01 = [self.users[key]["id"] for key in ("P01", "P02", "D01")]
        self.r01 = next(value for value in self.initial["versions"].values()
                        if self.initial["series"][value["series_id"]]["alias"] == "R01")
        self.v1 = self.r01["id"]

    def call(self, actor, method, path, data=None, expected=None, extra=None):
        if actor != "anonymous" and actor not in self.clients:
            self.login(actor)
        headers = {"Origin": self.service.origin}
        if actor != "anonymous":
            headers.update(self.clients[actor])
        headers.update(extra or {})
        result = self.service.handle(method, "/api" + path, headers, data)
        if expected is not None:
            self.assertEqual(result.status, expected, result.body)
        return result

    def login(self, alias):
        row = next(item for item in self.accounts if item["alias"] == alias)
        result = self.service.handle("POST", "/api/sessions", {"Origin": self.service.origin},
                                     {"username": row["username"], "password": row["password"], "totp": totp(row["totp_secret"])})
        self.assertEqual(result.status, 200, result.body)
        self.clients[alias] = {"Cookie": result.headers["Set-Cookie"].split(";")[0], "X-CSRF-Token": result.body["csrf"]}
        return result

    def state(self):
        with self.store.transaction() as tx:
            return deepcopy(tx.state)

    def book(self):
        profiles = self.call("P01", "GET", "/directory/physicians", expected=200).body["physicians"]
        profile = next(item for item in profiles if item["id"] == self.d01)
        return self.call("P01", "POST", "/appointments", {"physician_id": self.d01, "starts_at": profile["slots"][0]}, 201).body["appointment"]

    def share(self, appointment=None, versions=None):
        appointment = appointment or self.book()
        return self.call("P01", "POST", "/grants", {"appointment_id": appointment["id"], "version_ids": versions or [self.v1],
                        "purpose": "consultation", "starts_at": self.initial["clock"],
                        "expires_at": iso(timestamp(self.initial["clock"]) + 5400), "acknowledged": True}, 201).body["grant"]

    def source(self, amendment=False, message=None):
        order = self.initial["orders"][self.r01["package"]["manifest"]["order_id"]]
        patient = self.initial["patients"][self.p01]
        return {"order_id": order["id"], "cnic": patient["cnic"], "dob": patient["dob"],
                "specimen_alias": order["specimen_alias"], "source_report_id": self.r01["package"]["manifest"]["source_report_id"] if amendment else "SIM-NEW-REPORT",
                "message_id": message or "MSG-" + uuid.uuid4().hex, "result": "Detected (synthetic)",
                "approver_id": self.users["L01-A02"]["id"], "version": 2 if amendment else 1,
                "predecessor_id": self.v1 if amendment else None, "correction_reason": "Invented correction" if amendment else ""}

    def submit(self, data=None, amendment=False):
        route = "/lab/reports/" + self.r01["series_id"] + "/amendments" if amendment else "/lab/submissions"
        return self.call("L01-S01", "POST", route, data or self.source(amendment), 201).body["submission"]

    def approve(self, submission, expected=200):
        return self.call("L01-A02", "POST", "/lab/submissions/" + submission["id"] + "/approve",
                         {"expected_predecessor_id": submission["expected_predecessor_id"]}, expected)

    def test_synthetic_inventory_encryption_and_persistence(self):
        self.assertEqual(len(self.initial["patients"]), 5)
        self.assertEqual(len(self.initial["profiles"]), 3)
        self.assertEqual(len(self.initial["organizations"]), 3)
        raw = self.store.db_path.read_bytes()
        for patient in self.initial["patients"].values():
            self.assertNotIn(patient["cnic"].encode(), raw)
        self.assertNotIn(b"Not detected (synthetic)", raw)
        grant = self.share()
        self.service = Service(bootstrap(self.home))
        self.call("D01", "GET", "/report-versions/" + self.v1, expected=200)
        self.assertIn(grant["id"], self.state()["grants"])

    def test_authentication_factor_replay_and_generic_errors(self):
        row = self.accounts[0]
        invalid = {"username": row["username"], "password": "wrong", "totp": "000000"}
        result = self.call("anonymous", "POST", "/sessions", invalid, 401)
        unknown = self.call("anonymous", "POST", "/sessions", {**invalid, "username": "missing"}, 401)
        self.assertEqual(result.body, unknown.body)
        self.login("P01")
        row = next(item for item in self.accounts if item["alias"] == "P01")
        self.call("anonymous", "POST", "/sessions", {"username": "p01", "password": row["password"], "totp": totp(row["totp_secret"])}, 401)

    def test_login_throttling_and_cnic_only_recovery(self):
        for _ in range(8):
            self.call("anonymous", "POST", "/sessions", {"username": "p01", "password": "wrong", "totp": "000000"}, 401)
        self.call("anonymous", "POST", "/sessions", {"username": "p01", "password": "wrong", "totp": "000000"}, 429)
        self.call("anonymous", "POST", "/recovery-requests", {"account": self.initial["patients"][self.p01]["cnic"]}, 202)
        self.call("anonymous", "GET", "/report-versions/" + self.v1, expected=401)

    def test_ownership_hospital_lab_and_direct_file_boundaries(self):
        self.call("P01", "GET", "/report-versions/" + self.v1, expected=200)
        for alias in ("P02", "D02", "H01-M01", "L02-A02"):
            denied = self.call(alias, "GET", "/report-versions/" + self.v1 + "/file", expected=404)
            self.assertNotIsInstance(denied.body, bytes)
            missing = self.call(alias, "GET", "/report-versions/" + str(uuid.uuid4()) + "/file", expected=404)
            self.assertEqual(denied.body, missing.body)
        self.call("L01-A02", "GET", "/report-versions/" + self.v1 + "/file", expected=200)

    def test_booking_has_no_implicit_grant_and_unverified_doctors_cannot_be_booked(self):
        appointment = self.book()
        self.call("D01", "GET", "/report-versions/" + self.v1, expected=404)
        listed = self.call("D01", "GET", "/physician/appointments/" + appointment["id"] + "/records", expected=200)
        self.assertEqual(listed.body["records"], [])
        self.assertEqual(self.state()["grants"], {})
        self.call("P01", "POST", "/appointments", {"physician_id": self.users["D02"]["id"], "starts_at": appointment["starts_at"]}, 409)

    def test_exact_grant_withdrawal_affects_existing_session_and_file(self):
        grant = self.share()
        self.call("D01", "GET", "/report-versions/" + self.v1, expected=200)
        self.call("P01", "POST", "/grants/" + grant["id"] + "/withdraw", {}, 200)
        self.call("D01", "GET", "/report-versions/" + self.v1 + "/file", expected=404)
        self.call("P01", "POST", "/grants/" + grant["id"] + "/withdraw", {}, 200)

    def test_cancelled_appointment_blocks_same_session(self):
        appointment = self.book()
        self.share(appointment)
        self.call("D01", "GET", "/report-versions/" + self.v1, expected=200)
        self.call("P01", "PATCH", "/appointments/" + appointment["id"] + "/status", {"status": "cancelled", "expected_revision": 1}, 200)
        self.call("D01", "GET", "/report-versions/" + self.v1, expected=404)

    def test_affiliation_revocation_is_separate_from_registration(self):
        self.share()
        self.call("D01", "GET", "/report-versions/" + self.v1, expected=200)
        profile = next(item for item in self.call("H01-M01", "GET", "/hospital/profiles", expected=200).body["profiles"] if item["id"] == self.d01)
        registration = deepcopy(self.state()["profiles"][self.d01]["registration"])
        self.call("H01-M01", "POST", "/hospital/affiliations/" + profile["affiliation_id"] + "/status",
                  {"status": "revoked", "reason": "Synthetic revocation", "expected_revision": 1}, 200)
        self.assertEqual(self.state()["profiles"][self.d01]["registration"], registration)
        self.call("D01", "GET", "/report-versions/" + self.v1, expected=404)

    def test_independent_registration_cli_blocks_existing_physician_session(self):
        self.share()
        self.call("D01", "GET", "/report-versions/" + self.v1, expected=200)
        completed = subprocess.run([sys.executable, str(ROOT / "manage.py"), "--home", str(self.home), "registration", "D01", "stale"],
                                   capture_output=True, text=True, cwd=ROOT, timeout=20)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.call("D01", "GET", "/report-versions/" + self.v1 + "/file", expected=404)
        affiliation = next(item for item in self.state()["affiliations"].values() if item["physician_id"] == self.d01)
        self.assertEqual(affiliation["evidence"]["status"], "valid")

    def test_exclusive_expiry_boundary(self):
        grant = self.share()
        with self.store.transaction() as tx:
            tx.state["clock"] = iso(timestamp(grant["expires_at"]) - 1)
            tx.audit("synthetic_clock_changed")
        self.call("D01", "GET", "/report-versions/" + self.v1, expected=200)
        with self.store.transaction() as tx:
            tx.state["clock"] = grant["expires_at"]
            tx.audit("synthetic_clock_changed")
        self.call("D01", "GET", "/report-versions/" + self.v1, expected=404)

    def test_mismatch_is_held_and_cannot_be_overridden(self):
        source = self.source()
        source["cnic"] = self.initial["patients"][self.p02]["cnic"]
        submission = self.submit(source)
        self.assertEqual(submission["status"], "held")
        self.approve(submission, 409)
        self.assertEqual(len(self.state()["versions"]), 3)

    def test_distinct_approval_and_cross_lab_isolation(self):
        submission = self.submit()
        self.call("L01-S01", "POST", "/lab/submissions/" + submission["id"] + "/approve", {"expected_predecessor_id": None}, 404)
        self.call("L02-A02", "POST", "/lab/submissions/" + submission["id"] + "/approve", {"expected_predecessor_id": None}, 404)
        self.approve(submission)
        self.assertEqual(len(self.state()["versions"]), 4)

    def test_correction_preserves_v1_and_requires_new_consent(self):
        self.share()
        submission = self.submit(amendment=True)
        approved = self.approve(submission)
        v2 = approved.body["version"]["id"]
        old = self.call("D01", "GET", "/report-versions/" + self.v1, expected=200)
        self.assertEqual(old.body["report"]["status"], "superseded")
        self.assertNotIn(v2, canonical(old.body).decode())
        self.call("D01", "GET", "/report-versions/" + v2, expected=404)
        self.share(versions=[v2])
        self.call("D01", "GET", "/report-versions/" + v2, expected=200)
        versions = self.call("P01", "GET", "/me/reports/" + self.r01["series_id"] + "/versions", expected=200).body["versions"]
        self.assertEqual({item["version"] for item in versions}, {1, 2})
        self.assertEqual(self.state()["versions"][self.v1]["package"], self.r01["package"])

    def test_replay_and_changed_message_conflict(self):
        source = self.source()
        initial = self.submit(source)
        replay = self.call("L01-S01", "POST", "/lab/submissions", source, 200)
        self.assertEqual(initial["id"], replay.body["submission"]["id"])
        self.call("L01-S01", "POST", "/lab/submissions", {**source, "result": "Changed"}, 409)
        self.assertEqual(len(self.state()["submissions"]), 1)

    def test_changed_bytes_and_recomputed_hash_do_not_replace_signature(self):
        submission = self.submit()
        package = deepcopy(self.state()["submissions"][submission["id"]]["package"])
        package["content"] += "Altered content"
        package["manifest"]["content_digest"] = digest(package["content"].encode())
        package["manifest"]["message_id"] = "TAMPERED-MSG"
        result = self.call("L01-S01", "POST", "/lab/ingest", {"package": package}, 201)
        self.assertEqual(result.body["submission"]["status"], "held")
        self.approve(result.body["submission"], 409)

    def test_two_competing_corrections_cannot_silently_overwrite(self):
        first = self.submit(amendment=True)
        second = self.submit(amendment=True)
        self.login("L01-A02")
        def approve(item):
            return self.call("L01-A02", "POST", "/lab/submissions/" + item["id"] + "/approve", {"expected_predecessor_id": self.v1}).status
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(approve, [first, second]))
        self.assertEqual(sorted(statuses), [200, 409])
        self.assertEqual(len([item for item in self.state()["versions"].values() if item["series_id"] == self.r01["series_id"]]), 2)

    def test_audit_write_failure_blocks_read_and_rolls_back_mutation(self):
        self.share()
        self.login("D01")
        previous = self.state()
        self.store.inject_audit_failure = True
        result = self.call("D01", "GET", "/report-versions/" + self.v1, expected=503)
        self.assertNotIn("report", result.body)
        appointment = next(iter(previous["appointments"].values()))
        self.call("P01", "PATCH", "/appointments/" + appointment["id"] + "/status", {"status": "cancelled", "expected_revision": 1}, 503)
        self.store.inject_audit_failure = False
        self.assertEqual(self.state()["appointments"][appointment["id"]]["status"], "booked")
        self.store.verify()

    def test_checkpoint_failure_retains_committed_withdrawal_and_holds_release(self):
        grant = self.share()
        self.login("D01")
        self.store.inject_checkpoint_failure = True
        self.call("P01", "POST", "/grants/" + grant["id"] + "/withdraw", {}, 503)
        self.store.inject_checkpoint_failure = False
        with sqlite3.connect(self.store.db_path) as db:
            encoded = db.execute("SELECT body FROM state").fetchone()[0]
        state = json.loads(self.store.cipher.decrypt(encoded))
        self.assertEqual(state["grants"][grant["id"]]["status"], "revoked")
        self.call("D01", "GET", "/report-versions/" + self.v1, expected=503)
        with self.assertRaises(IntegrityFailure):
            bootstrap(self.home)

    def test_audit_truncation_is_detected(self):
        self.share()
        self.login("D01")
        with sqlite3.connect(self.store.db_path) as db:
            db.execute("DELETE FROM audit WHERE seq=(SELECT MAX(seq) FROM audit)")
        self.call("D01", "GET", "/report-versions/" + self.v1, expected=503)

    def test_saved_state_rollback_is_detected(self):
        with sqlite3.connect(self.store.db_path) as db:
            original = db.execute("SELECT body FROM state").fetchone()[0]
        self.share()
        self.login("D01")
        with sqlite3.connect(self.store.db_path) as db:
            db.execute("UPDATE state SET body=?", (original,))
        self.call("D01", "GET", "/report-versions/" + self.v1, expected=503)

    def test_csrf_origin_and_client_verified_flags(self):
        self.login("P01")
        self.call("P01", "POST", "/grants", {}, 403, {"X-CSRF-Token": "wrong"})
        self.call("P01", "POST", "/grants", {}, 403, {"Origin": "https://untrusted.invalid"})
        self.call("H01-M01", "POST", "/hospital/profiles", {"verified": True, "role": "admin"}, 422)
        self.call("P01", "POST", "/appointments", {"physician_id": [], "starts_at": "x"}, 422)
        self.call("H01-M01", "POST", "/registration", {"verified": True}, 404)

    def test_logout_and_expired_sessions_do_not_keep_access(self):
        self.login("P01")
        self.call("P01", "DELETE", "/session", {}, 200)
        self.call("P01", "GET", "/report-versions/" + self.v1, expected=401)
        self.login("P02")
        with self.store.transaction() as tx:
            for session in tx.state["users"][self.p02]["sessions"].values():
                session["expires_at"] = time.time() - 1
            tx.audit("test_session_expired")
        self.call("P02", "GET", "/me/reports", expected=401)

    def test_redacted_access_history_and_no_full_cnic_in_responses(self):
        self.share()
        self.call("D01", "GET", "/report-versions/" + self.v1, expected=200)
        own = self.call("P01", "GET", "/me/access-history", expected=200)
        other = self.call("P02", "GET", "/me/access-history", expected=200)
        self.assertTrue(any(item["action"] == "release_prepared" for item in own.body["events"]))
        self.assertFalse(any(item["actor_label"] == "Demo Physician D01" for item in other.body["events"]))
        for path, actor in [("/me/identity", "P01"), ("/directory/physicians", "P01"), ("/lab/workspace", "L01-S01"), ("/hospital/profiles", "H01-M01")]:
            encoded = canonical(self.call(actor, "GET", path, expected=200).body)
            for patient in self.initial["patients"].values():
                self.assertNotIn(patient["cnic"].encode(), encoded)
            self.assertNotIn(b"factor_secret", encoded)
            self.assertNotIn(b"password_hash", encoded)

    def test_denied_access_history_names_exact_version_without_foreign_patient_name(self):
        self.call("P02", "GET", "/report-versions/" + self.v1, expected=404)
        events = self.call("P01", "GET", "/me/access-history", expected=200).body["events"]
        denial = next(item for item in events if item["action"] == "clinical_access_denied")
        self.assertEqual(denial["record_label"], "R01 v1")
        self.assertEqual(denial["actor_label"], "Another account")
        self.assertTrue(denial["server_time"])

    def test_totp_matches_published_rfc6238_sha1_vector(self):
        self.assertEqual(totp("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", 59), "287082")

    def test_concurrent_read_and_withdrawal_respect_committed_order(self):
        grant = self.share()
        self.login("D01")
        def read(_index):
            return self.call("D01", "GET", "/report-versions/" + self.v1).status
        with ThreadPoolExecutor(max_workers=4) as pool:
            pending = [pool.submit(read, index) for index in range(6)]
            self.call("P01", "POST", "/grants/" + grant["id"] + "/withdraw", {}, 200)
            statuses = [item.result() for item in pending]
        self.assertTrue(all(item in (200, 404) for item in statuses))
        self.call("D01", "GET", "/report-versions/" + self.v1, expected=404)
        with self.store.transaction() as tx:
            withdrawal = next(item["sequence"] for item in tx.history if item["action"] == "grant_withdrawn")
            self.assertFalse(any(item["action"] == "release_prepared" and item["sequence"] > withdrawal for item in tx.history))

    def test_http_headers_host_origin_size_and_private_files(self):
        server = LocalServer(self.store, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def send_http(method, path, body=None, headers=None):
            client = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            client.request(method, path, body=body, headers=headers or {})
            response = client.getresponse()
            result = (response.status, dict(response.getheaders()), response.read())
            client.close()
            return result
        try:
            status, headers, body = send_http("GET", "/")
            self.assertEqual(status, 200)
            self.assertIn(b"SehatAman", body)
            self.assertIn("no-store", headers["Cache-Control"])
            self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
            self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
            self.assertEqual(send_http("GET", "/.local/protected/keys.json")[0], 404)
            self.assertEqual(send_http("GET", "/", headers={"Host": "untrusted.invalid"})[0], 400)
            self.assertEqual(send_http("POST", "/api/sessions", "{}", {"Content-Type": "application/json", "Origin": "https://untrusted.invalid"})[0], 403)
            self.assertEqual(send_http("POST", "/api/sessions", "x", {"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{server.server_port}"})[0], 422)
            self.assertEqual(send_http("POST", "/api/lab/submissions", None, {"Content-Length": "70000", "Content-Type": "application/json"})[0], 413)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(MvpChecks)
    runner = unittest.TextTestRunner(verbosity=2)
    started = time.time()
    result = runner.run(suite)
    report = {"stage": "Step 4 implementation checks only", "tests_run": result.testsRun,
              "failures": len(result.failures), "errors": len(result.errors), "seconds": round(time.time() - started, 2),
              "passed": result.wasSuccessful(), "test_home": str(RUN),
              "formal_120_case_benchmark": "not executed; Step 5 approval pending",
              "formal_500_trace_benchmark": "not executed", "reference_comparison": "not executed",
              "direct_stakeholder_validation": "pending"}
    (ROOT / "planning" / "step4_implementation_checks.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    raise SystemExit(0 if result.wasSuccessful() else 1)
