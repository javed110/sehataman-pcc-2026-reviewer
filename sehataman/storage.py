"""Encrypted SQLite state, transactional audit, and a separately protected checkpoint.

The protected directory and its keys are outside the writable-store attacker model.
A same-user/OS compromise is explicitly outside this local demonstration's assurance.
"""

import contextlib
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time
import uuid

from cryptography.fernet import Fernet, InvalidToken

from .crypto import canonical, digest, keyed, iso


class IntegrityFailure(Exception):
    pass


def storage_head(previous, sequence, body, predecessor, event_digest):
    """Bind every encrypted row to the separately authenticated checkpoint."""
    return hashlib.sha256(bytes.fromhex(previous) + sequence.to_bytes(8, "big")
                          + len(body).to_bytes(8, "big") + body
                          + bytes.fromhex(predecessor) + bytes.fromhex(event_digest)).hexdigest()


class AuditHistory:
    """Decrypt the already checkpoint-verified log only when a caller needs it."""
    def __init__(self, rows, cipher, audit_key):
        self.rows, self.cipher, self.audit_key = rows, cipher, audit_key
        self.decoded = None

    def _all(self):
        if self.decoded is None:
            events, previous = [], "0" * 64
            try:
                for seq, body, prev, current in self.rows:
                    event = json.loads(self.cipher.decrypt(bytes(body)))
                    expected = keyed(self.audit_key, previous.encode() + canonical(event))
                    if prev != previous or not secrets.compare_digest(current, expected):
                        raise IntegrityFailure("Audit sequence or signature failed.")
                    events.append({**event, "sequence": seq})
                    previous = current
            except (InvalidToken, ValueError, TypeError, KeyError) as exc:
                raise IntegrityFailure("Audit contents failed verification.") from exc
            self.decoded = events
        return self.decoded

    def __iter__(self):
        return iter(self._all())

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, key):
        return self._all()[key]

    def __deepcopy__(self, memo):
        return deepcopy(self._all(), memo)


def private_write(path, data):
    path = Path(path)
    temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


class Transaction:
    def __init__(self, store, state, history):
        self.store, self.state, self.history = store, state, history
        self.pending = []

    def audit(self, action, actor=None, outcome="ok", object_id=None, patient_id=None,
              version_id=None, reason=None, request_id=None):
        bases = {"login_succeeded": "password_and_current_second_factor_verified",
                 "recovery_requested": "review_receipt_only_no_access_granted",
                 "identity_summary_viewed": "authenticated_patient_own_identity",
                 "own_history_viewed": "authenticated_patient_own_accepted_history",
                 "grant_created": "owner_explicit_exact_versions_current_eligibility",
                 "grant_withdrawn": "authenticated_grant_owner_withdrawal",
                 "report_accepted": "distinct_bound_approver_source_linkage_integrity_predecessor_verified",
                 "hospital_profile_submitted": "authorized_hospital_current_account_binding_revision",
                 "logout": "authenticated_session_invalidated",
                 "submission_returned": "authorized_distinct_source_reviewer",
                 "independent_registration_review_requested": "hospital_request_only_no_status_change"}
        if action.startswith("affiliation_"):
            basis = "authorized_hospital_separate_affiliation_attestation"
        elif action.startswith("appointment_"):
            basis = "authenticated_appointment_participant_permitted_transition"
        else:
            basis = bases.get(action, "local_fixture_operation" if actor is None or actor.get("role") == "local_fixture"
                              else "authenticated_scoped_operation")
        event = {"action": action, "actor_id": actor["id"] if actor else "anonymous",
                 "actor_label": actor["label"] if actor else "Anonymous",
                 "role": actor["role"] if actor else "anonymous", "outcome": outcome,
                 "object_id": object_id, "patient_id": patient_id, "version_id": version_id,
                 "reason_code": reason or basis, "request_id": request_id or str(uuid.uuid4()),
                 "server_time": iso(time.time()), "test_time": self.state["clock"],
                 "policy_revision": "sehataman-policy-v1", "synthetic": True}
        self.pending.append(event)
        return event


class Store:
    def __init__(self, home):
        self.home = Path(home).resolve()
        self.data = self.home / "data"
        self.protected = self.home / "protected"
        self.db_path = self.data / "sehataman.sqlite3"
        self.checkpoint = self.protected / "audit-head.json"
        self.key_path = self.protected / "keys.json"
        self.lock = threading.RLock()
        self.inject_audit_failure = False
        self.inject_checkpoint_failure = False

    def initialize(self, state_factory):
        self.data.mkdir(parents=True, exist_ok=True)
        self.protected.mkdir(parents=True, exist_ok=True)
        with self._exclusive():
            if self.db_path.exists():
                self._load_keys()
                with self._connect() as db:
                    self._verify(db)
                return False
            if self.key_path.exists() or self.checkpoint.exists():
                raise IntegrityFailure("Incomplete initialization; use a new demo home, not automatic repair.")
            keys = {"encryption": Fernet.generate_key().decode(), "audit": secrets.token_hex(32),
                    "lookup": secrets.token_hex(32)}
            private_write(self.key_path, canonical(keys))
            self._load_keys()
            state = state_factory(self)
            blob = self.cipher.encrypt(canonical(state))
            with self._connect() as db:
                db.execute("CREATE TABLE state (id INTEGER PRIMARY KEY CHECK(id=1), body BLOB NOT NULL)")
                db.execute("CREATE TABLE audit (seq INTEGER PRIMARY KEY, body BLOB NOT NULL, previous TEXT NOT NULL, digest TEXT NOT NULL)")
                db.execute("INSERT INTO state VALUES (1, ?)", (blob,))
                db.commit()
                self._anchor(0, "0" * 64, blob)
            return True

    def _load_keys(self):
        try:
            keys = json.loads(self.key_path.read_text("utf-8"))
            self.cipher = Fernet(keys["encryption"].encode())
            self.audit_key = bytes.fromhex(keys["audit"])
            self.lookup_key = bytes.fromhex(keys["lookup"])
        except (OSError, ValueError, KeyError) as exc:
            raise IntegrityFailure("Protected keys are unavailable.") from exc

    def _connect(self):
        try:
            db = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA foreign_keys=ON")
            return db
        except sqlite3.Error as exc:
            raise IntegrityFailure("Durable store unavailable.") from exc

    @contextlib.contextmanager
    def _exclusive(self):
        self.protected.mkdir(parents=True, exist_ok=True)
        with self.lock, open(self.protected / "operation.lock", "a+b") as lockfile:
            lockfile.seek(0, 2)
            if lockfile.tell() == 0:
                lockfile.write(b"0")
                lockfile.flush()
            deadline = time.monotonic() + 10
            while True:
                try:
                    lockfile.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(lockfile.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(lockfile.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise IntegrityFailure("Local store busy; release held.")
                    time.sleep(0.01)
            try:
                yield
            finally:
                if os.name == "nt":
                    import msvcrt
                    lockfile.seek(0)
                    msvcrt.locking(lockfile.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lockfile.fileno(), fcntl.LOCK_UN)

    def _anchor(self, sequence, head, blob, encrypted_audit_head="0" * 64):
        if self.inject_checkpoint_failure:
            raise IntegrityFailure("Checkpoint unavailable; committed state retained, recovery required.")
        contents = {"sequence": sequence, "head": head, "state_digest": digest(blob),
                    "encrypted_audit_head": encrypted_audit_head}
        envelope = {"checkpoint": contents, "mac": keyed(self.audit_key, canonical(contents))}
        try:
            private_write(self.checkpoint, canonical(envelope))
        except OSError as exc:
            raise IntegrityFailure("Protected checkpoint cannot be advanced; recovery required.") from exc

    def _verify(self, db):
        try:
            row = db.execute("SELECT body FROM state WHERE id=1").fetchone()
            if row is None:
                raise IntegrityFailure("Missing state.")
            blob = bytes(row[0])
            state = json.loads(self.cipher.decrypt(blob))
            envelope = json.loads(self.checkpoint.read_text("utf-8"))
            if not secrets.compare_digest(envelope["mac"], keyed(self.audit_key, canonical(envelope["checkpoint"]))):
                raise IntegrityFailure("Protected checkpoint signature failed.")
            previous, encrypted_head, sequence = "0" * 64, "0" * 64, 0
            rows = db.execute("SELECT seq,body,previous,digest FROM audit ORDER BY seq").fetchall()
            for seq, body, prev, current in rows:
                if seq != sequence + 1 or prev != previous:
                    raise IntegrityFailure("Audit sequence or signature failed.")
                encrypted_head = storage_head(encrypted_head, seq, bytes(body), prev, current)
                previous, sequence = current, seq
            expected = {"sequence": sequence, "head": previous, "state_digest": digest(blob)}
            history = AuditHistory(rows, self.cipher, self.audit_key)
            if "encrypted_audit_head" in envelope["checkpoint"]:
                expected["encrypted_audit_head"] = encrypted_head
            else:
                # Existing Step 4 checkpoints migrate only after full legacy
                # verification. No old event or checkpoint is silently repaired.
                history._all()
            if envelope["checkpoint"] != expected:
                raise IntegrityFailure("Store does not match protected head; recovery required.")
            if state.get("synthetic") is not True:
                raise IntegrityFailure("Synthetic-only marker missing.")
            return state, history, sequence, previous, encrypted_head
        except (OSError, sqlite3.Error, ValueError, KeyError, TypeError, InvalidToken) as exc:
            raise IntegrityFailure("Integrity verification unavailable; release held.") from exc

    @contextlib.contextmanager
    def transaction(self):
        with self._exclusive():
            self._load_keys()
            db = self._connect()
            try:
                db.execute("BEGIN IMMEDIATE")
                state, history, sequence, previous, encrypted_head = self._verify(db)
                initial = canonical(state)
                tx = Transaction(self, state, history)
                yield tx
                if tx.pending or canonical(tx.state) != initial:
                    if self.inject_audit_failure:
                        raise IntegrityFailure("Required audit writer unavailable.")
                    for event in tx.pending:
                        sequence += 1
                        current = keyed(self.audit_key, previous.encode() + canonical(event))
                        event_blob = self.cipher.encrypt(canonical(event))
                        db.execute("INSERT INTO audit VALUES (?,?,?,?)", (sequence, event_blob, previous, current))
                        encrypted_head = storage_head(encrypted_head, sequence, event_blob, previous, current)
                        previous = current
                    blob = self.cipher.encrypt(canonical(tx.state))
                    db.execute("UPDATE state SET body=? WHERE id=1", (blob,))
                    db.commit()
                    self._anchor(sequence, previous, blob, encrypted_head)
                else:
                    db.commit()
            except (OSError, sqlite3.Error) as exc:
                db.rollback()
                raise IntegrityFailure("Required durable state or audit writer unavailable.") from exc
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()

    def verify(self):
        with self.transaction() as tx:
            list(tx.history)  # A requested full verification checks plaintext MACs too.
            return {"synthetic": True, "events": len(tx.history), "integrity": "verified",
                    "clock": tx.state["clock"]}
