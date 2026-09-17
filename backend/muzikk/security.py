"""Secret encryption at rest and session tokens."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

import jwt
from cryptography.fernet import Fernet, InvalidToken

from .config import get_env_config, read_or_create_key

logger = logging.getLogger(__name__)

ENCRYPTED_PREFIX = "enc:v1:"
MASK = "••••••••"


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
