"""Secret encryption at rest, password hashing and session tokens."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

import jwt
from cryptography.fernet import Fernet, InvalidToken

from .config import get_env_config, read_or_create_key

logger = logging.getLogger(__name__)

ENCRYPTED_PREFIX = "enc:v1:"
MASK = "••••••••"

# scrypt comes with Python, so local accounts cost the image no extra
# dependency. These parameters ask for about 16 MB and a tenth of a second per
# attempt, which is plenty against an offline attack on a self-hosted box.
SCRYPT_N = 1 << 14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
SCRYPT_MAXMEM = 64 * 1024 * 1024
PASSWORD_PREFIX = "scrypt$"
MIN_PASSWORD_LENGTH = 8


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    env = get_env_config()
    key = read_or_create_key(env.secret_key_path, generator=lambda: Fernet.generate_key().decode())
    return Fernet(key.encode())


@lru_cache(maxsize=1)
def _jwt_secret() -> str:
    return read_or_create_key(get_env_config().jwt_key_path)


def encrypt_secret(value: str | None) -> str | None:
    """Encrypt a secret unless it is empty or already encrypted."""
    if not value:
        return value
    if value.startswith(ENCRYPTED_PREFIX):
        return value
    return ENCRYPTED_PREFIX + _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str | None) -> str | None:
    if not value:
        return value
    if not value.startswith(ENCRYPTED_PREFIX):
        # Value written before encryption was in place, or set by hand.
        return value
    try:
        return _fernet().decrypt(value[len(ENCRYPTED_PREFIX) :].encode()).decode()
    except InvalidToken:
        logger.error("Unable to decrypt a stored secret: the encryption key changed")
        return None


def _scrypt(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
        maxmem=SCRYPT_MAXMEM,
    )


def hash_password(password: str) -> str:
    """Derive a storable hash, parameters included so they can be raised later."""
    salt = os.urandom(16)
    digest = _scrypt(password, salt)
    return "$".join(
        (
            "scrypt",
            str(SCRYPT_N),
            str(SCRYPT_R),
            str(SCRYPT_P),
            base64.b64encode(salt).decode(),
            base64.b64encode(digest).decode(),
        )
    )


def verify_password(password: str, stored: str | None) -> bool:
    """Whether a password matches a hash produced by ``hash_password``.

    An account without a hash always fails: that is a Jellyfin account, and it
    has no password Muzikk could check.
    """
    if not password or not stored or not stored.startswith(PASSWORD_PREFIX):
        return False
    try:
        _, raw_n, raw_r, raw_p, raw_salt, raw_digest = stored.split("$")
        salt = base64.b64decode(raw_salt)
        expected = base64.b64decode(raw_digest)
        candidate = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(raw_n),
            r=int(raw_r),
            p=int(raw_p),
            dklen=len(expected),
            maxmem=SCRYPT_MAXMEM,
        )
    except (ValueError, TypeError, MemoryError):
        logger.warning("Unreadable password hash, refusing the login")
        return False
    return hmac.compare_digest(candidate, expected)


def create_access_token(subject: str, extra: dict[str, Any] | None = None) -> tuple[str, datetime]:
    env = get_env_config()
    expires_at = datetime.now(UTC) + timedelta(hours=env.session_hours)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": int(datetime.now(UTC).timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256"), expires_at


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, _jwt_secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
