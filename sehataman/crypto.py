"""Small protocol helpers; cryptographic primitives come from maintained libraries."""

import base64
import hashlib
import hmac
import json
import re
import secrets
import struct
import time
from datetime import datetime, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError

PASSWORDS = PasswordHasher()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(value).hexdigest()


def keyed(key, value):
    return hmac.new(key, value, hashlib.sha256).hexdigest()


def normalize_cnic(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:\d{5}-\d{7}-\d|\d{13})", value):
        raise ValueError("Enter a 13-digit synthetic CNIC fixture.")
    return value.replace("-", "")


def timestamp(value):
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("An explicit timezone is required.")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("An explicit timezone is required.")
    return parsed.timestamp()


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def token():
    return secrets.token_urlsafe(32)


def new_factor():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def totp(secret, at=None):
    at = time.time() if at is None else at
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    raw = hmac.new(key, struct.pack(">Q", int(at // 30)), hashlib.sha1).digest()
    offset = raw[-1] & 15
    return f"{(struct.unpack('>I', raw[offset:offset + 4])[0] & 0x7fffffff) % 1000000:06d}"


def valid_factor(secret, value, last_counter, at=None):
    if not isinstance(value, str) or not re.fullmatch(r"\d{6}", value):
        return None
    at = time.time() if at is None else at
    for counter in range(int(at // 30) - 1, int(at // 30) + 2):
        if counter > last_counter and hmac.compare_digest(totp(secret, counter * 30), value):
            return counter
    return None


def password_ok(encoded, supplied):
    try:
        return PASSWORDS.verify(encoded, supplied)
    except (VerificationError, InvalidHashError):
        return False
