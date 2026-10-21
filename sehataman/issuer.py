"""Local synthetic issuer adapter, separate from the ingest verifier.

No private signing keys are sent to browsers. The trusted ingest keyring contains
public keys only. Runtime/OS isolation is not claimed for this single-laptop MVP.
"""

import base64
import json

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, PublicFormat, NoEncryption

from .crypto import canonical, digest
from .storage import private_write


def report_text(manifest):
    return "\n".join([
        "SehatAman | SYNTHETIC DEMONSTRATION ONLY",
        "Invented report; not for clinical use.",
        "Patient: " + manifest["patient_alias"],
        "Issuer: Demo Molecular Lab " + manifest["lab_alias"],
        "Source report: " + manifest["source_report_id"],
        "Order / specimen: " + manifest["order_alias"] + " / " + manifest["specimen_alias"],
        "Specimen: " + manifest["specimen_type"],
        "Method: " + manifest["method"],
        "Target: " + manifest["target"],
        "Result: " + manifest["result"],
        "Version: " + str(manifest["version"]),
        "Issued: " + manifest["issued_at"],
        "Correction reason: " + (manifest["correction_reason"] or "Original version"),
        "",
    ])


def initialize_issuers(store):
    private_dir = store.home / "issuer-secrets"
    private_dir.mkdir(exist_ok=True)
    public = {}
    for lab in ("L01", "L02"):
        key = Ed25519PrivateKey.generate()
        private_write(private_dir / (lab + ".key"), key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()))
        public[lab] = base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
    private_write(store.protected / "issuer-public-keys.json", canonical(public))


def sign_package(store, lab_alias, manifest, content):
    key = Ed25519PrivateKey.from_private_bytes((store.home / "issuer-secrets" / (lab_alias + ".key")).read_bytes())
    manifest = {**manifest, "content_digest": digest(content.encode()), "schema": "synthetic-report-manifest-v1"}
    return {"manifest": manifest, "content": content,
            "signature": base64.b64encode(key.sign(canonical(manifest))).decode()}


def verify_package(store, lab_alias, package):
    try:
        manifest = package["manifest"]
        public = json.loads((store.protected / "issuer-public-keys.json").read_text("utf-8"))
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public[lab_alias], validate=True))
        key.verify(base64.b64decode(package["signature"], validate=True), canonical(manifest))
        return (manifest["schema"] == "synthetic-report-manifest-v1"
                and manifest["content_digest"] == digest(package["content"].encode()))
    except (OSError, KeyError, ValueError, TypeError, InvalidSignature):
        return False
