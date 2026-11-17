"""Password hashing and signed tokens using only the standard library (no extra packages to install).

* Passwords: PBKDF2-HMAC-SHA256, random salt, stored as  pbkdf2_sha256$<iterations>$<salt hex>$<hash hex>
* Tokens: standard HS256 JWT (header.payload.signature, base64url) with an expiry.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Optional

from app.core.config import settings

_ITERATIONS = 200_000
_DUMMY_HASH = "pbkdf2_sha256$1000$00$00"          # verified against when the user does not exist (timing)


class AuthError(Exception):
    pass


# ---------------------------------------------------------------- passwords
def hash_password(password: str, iterations: int = _ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: Optional[str]) -> bool:
    """False for a wrong password AND for anything that is not a valid hash (e.g. the seed's dummy value)."""
    try:
        scheme, iters, salt_hex, hash_hex = (stored or _DUMMY_HASH).split("$")
        if scheme != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(dk, bytes.fromhex(hash_hex)) and stored is not None
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------- tokens
def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(signing_input: str, secret: str) -> str:
    return _b64(hmac.new(secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest())


def create_token(user_id: int, username: str, role: str, minutes: Optional[int] = None,
                 secret: Optional[str] = None, now: Optional[float] = None) -> str:
    now = time.time() if now is None else now
    exp = int(now + 60 * (settings.token_minutes if minutes is None else minutes))
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64(json.dumps({"sub": str(user_id), "name": username, "role": role, "exp": exp},
                              separators=(",", ":")).encode())
    signing_input = f"{header}.{payload}"
    return f"{signing_input}.{_sign(signing_input, secret or settings.secret_key)}"


def decode_token(token: str, secret: Optional[str] = None, now: Optional[float] = None) -> dict:
    """Returns the claims or raises AuthError (bad format, bad signature, expired)."""
    try:
        header_b64, payload_b64, sig = token.split(".")
        expected = _sign(f"{header_b64}.{payload_b64}", secret or settings.secret_key)
        if not hmac.compare_digest(sig, expected):
            raise AuthError("invalid token signature")
        if json.loads(_unb64(header_b64)).get("alg") != "HS256":
            raise AuthError("unsupported token algorithm")
        claims = json.loads(_unb64(payload_b64))
    except AuthError:
        raise
    except Exception as exc:                                   # malformed base64 / json / wrong number of parts
        raise AuthError("malformed token") from exc
    if (time.time() if now is None else now) >= float(claims.get("exp", 0)):
        raise AuthError("token expired")
    return claims
