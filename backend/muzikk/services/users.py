"""Accounts: imported from Jellyfin, or owned by Muzikk itself."""

from __future__ import annotations

import logging
import re
import secrets
from functools import lru_cache
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from ..models import User, utcnow
from ..security import (
    MIN_PASSWORD_LENGTH,
    decrypt_secret,
    encrypt_secret,
    hash_password,
    verify_password,
)
from . import mode as mode_service
from . import settings as settings_service
from .base import ServiceError
from .jellyfin import JellyfinClient

logger = logging.getLogger(__name__)

USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,64}$")


class AuthError(RuntimeError):
    """Raised when a login attempt must be refused."""

    def __init__(self, message: str, *, code: str = "invalid_credentials") -> None:
        super().__init__(message)
        self.code = code


class AccountError(RuntimeError):
    """Raised when an account cannot be created or changed as asked."""


def _is_allowed(jellyfin_settings, jellyfin_user: dict[str, Any]) -> bool:
    if jellyfin_settings.allow_all_users:
        return True
    return jellyfin_user.get("Id") in set(jellyfin_settings.allowed_user_ids or [])


def store_jellyfin_token(session: Session, user: User, token: str | None) -> None:
    """Keep the Jellyfin session token so Muzikk can stream as this user."""
    if not token:
        return
    user.jellyfin_token = encrypt_secret(token)
    session.commit()


def jellyfin_token(user: User) -> str:
    return decrypt_secret(user.jellyfin_token or "") or ""


def listenbrainz_token(user: User) -> str:
    return decrypt_secret(user.listenbrainz_token or "") or ""


def lastfm_session_key(user: User) -> str:
    return decrypt_secret(user.lastfm_session_key or "") or ""


def set_listening_accounts(
    session: Session,
    user: User,
    *,
    listenbrainz_user: str | None = None,
    listenbrainz_token_value: str | None = None,
    lastfm_user: str | None = None,
    lastfm_session_key_value: str | None = None,
) -> None:
    """Store the listener's own service accounts.

    Passing ``None`` leaves a field alone; passing an empty string disconnects
    it, which is the only way to take a token back out.
    """
    if listenbrainz_user is not None:
        user.listenbrainz_user = listenbrainz_user.strip() or None
    if listenbrainz_token_value is not None:
        cleaned = listenbrainz_token_value.strip()
        user.listenbrainz_token = encrypt_secret(cleaned) if cleaned else None
    if lastfm_user is not None:
        user.lastfm_user = lastfm_user.strip() or None
    if lastfm_session_key_value is not None:
        cleaned = lastfm_session_key_value.strip()
        user.lastfm_session_key = encrypt_secret(cleaned) if cleaned else None
    session.commit()


def upsert_user(session: Session, jellyfin_user: dict[str, Any], *, touch_login: bool = False) -> User:
    jellyfin_id = jellyfin_user.get("Id")
    if not jellyfin_id:
        raise AuthError("Jellyfin returned a user without an id", code="invalid_response")

    user = session.execute(
        select(User).where(User.jellyfin_user_id == jellyfin_id)
    ).scalar_one_or_none()

    policy = jellyfin_user.get("Policy") or {}
    is_admin = bool(policy.get("IsAdministrator"))
    is_disabled = bool(policy.get("IsDisabled"))

    if user is None:
        general = settings_service.load(session, "general")
        user = User(
            jellyfin_user_id=jellyfin_id,
            name=jellyfin_user.get("Name") or jellyfin_id,
            is_admin=is_admin,
            is_enabled=not is_disabled,
            weekly_quota=general.default_weekly_quota,
        )
        session.add(user)
    else:
        user.name = jellyfin_user.get("Name") or user.name
        user.is_admin = is_admin
        if is_disabled:
            user.is_enabled = False

    user.primary_image_tag = (jellyfin_user.get("PrimaryImageTag") or None)
    if touch_login:
        user.last_login_at = utcnow()
    session.commit()
    session.refresh(user)
    return user


@lru_cache(maxsize=1)
def _decoy_hash() -> str:
    """A hash no password matches, to keep a failed login slow either way.

    Without it, an unknown name answers instantly while a known one pays for a
    scrypt round, which is enough to enumerate the accounts of the server.
    """
    return hash_password(secrets.token_urlsafe(32))


def normalize_username(value: str) -> str:
    name = (value or "").strip()
    if not USERNAME_RE.match(name):
        raise AccountError(
            "A username is 3 to 64 characters long and holds only letters, "
            "digits, dots, dashes and underscores"
        )
    return name


def check_password(value: str) -> str:
    if len(value or "") < MIN_PASSWORD_LENGTH:
        raise AccountError(f"A password is at least {MIN_PASSWORD_LENGTH} characters long")
    return value


def find_by_username(session: Session, username: str) -> User | None:
    key = (username or "").strip().lower()
    if not key:
        return None
    return session.execute(
        select(User).where(func.lower(User.username) == key)
    ).scalar_one_or_none()


def create_local_user(
    session: Session,
    *,
    username: str,
    password: str,
    display_name: str = "",
    is_admin: bool = False,
    can_request: bool = True,
    can_upgrade: bool | None = None,
    can_import: bool | None = None,
    weekly_quota: int | None = None,
) -> User:
    """Add an account Muzikk owns. Only ever called in local mode."""
    name = normalize_username(username)
    check_password(password)
    if find_by_username(session, name) is not None:
        raise AccountError(f'The username "{name}" is already taken')

    general = settings_service.load(session, "general")
    user = User(
        username=name,
        password_hash=hash_password(password),
        name=(display_name or "").strip() or name,
        is_admin=is_admin,
        is_enabled=True,
        can_request=can_request,
        # An administrator manages the library, so the two powers that write to
        # it come switched on rather than hidden behind a second visit.
        can_upgrade=is_admin if can_upgrade is None else can_upgrade,
        can_import=is_admin if can_import is None else can_import,
        weekly_quota=general.default_weekly_quota if weekly_quota is None else weekly_quota,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def set_password(session: Session, user: User, password: str) -> None:
    if user.username is None:
        raise AccountError("This account is managed by Jellyfin, set its password there")
    check_password(password)
    user.password_hash = hash_password(password)
    session.commit()


def rename_local_user(session: Session, user: User, username: str) -> None:
    if user.username is None:
        raise AccountError("This account is managed by Jellyfin, rename it there")
    name = normalize_username(username)
    existing = find_by_username(session, name)
    if existing is not None and existing.id != user.id:
        raise AccountError(f'The username "{name}" is already taken')
    user.username = name
    if not user.name.strip():
        user.name = name
    session.commit()


def authenticate_local(session: Session, username: str, password: str) -> User:
    user = find_by_username(session, username)
    stored = user.password_hash if user is not None else _decoy_hash()
    if not verify_password(password, stored) or user is None:
        raise AuthError("Invalid username or password")
    if not user.is_enabled:
        raise AuthError("This account is disabled", code="disabled")
    user.last_login_at = utcnow()
    try:
        session.commit()
        session.refresh(user)
    except OperationalError:
        # A first-run library scan can hold SQLite for a moment. The password
        # already checked out; refusing the session for a stamp is worse.
        session.rollback()
        logger.warning("Could not record last login for %s while the database is busy", username)
        user = find_by_username(session, username) or user
    return user


async def authenticate(session: Session, username: str, password: str) -> User:
    if mode_service.is_local(session):
        return authenticate_local(session, username, password)

    jellyfin_settings = settings_service.load(session, "jellyfin")
    client = JellyfinClient(jellyfin_settings)
    if not client.configured:
        raise AuthError("Jellyfin is not configured yet", code="not_configured")

    try:
        payload = await client.authenticate_by_name(username, password)
    except ServiceError as exc:
        if exc.status_code in (401, 403):
            raise AuthError("Invalid username or password") from exc
        raise AuthError(f"Jellyfin unreachable: {exc.message}", code="unreachable") from exc

    jellyfin_user = (payload or {}).get("User") or {}
    if not jellyfin_user:
        raise AuthError("Unexpected Jellyfin response", code="invalid_response")

    if not _is_allowed(jellyfin_settings, jellyfin_user):
        raise AuthError("This Jellyfin account is not allowed to use Muzikk", code="forbidden")

    user = upsert_user(session, jellyfin_user, touch_login=True)
    if not user.is_enabled:
        raise AuthError("This account is disabled", code="disabled")
    store_jellyfin_token(session, user, (payload or {}).get("AccessToken"))
    return user


async def sync_users(session: Session) -> dict[str, int]:
    """Import every Jellyfin user, honouring the allow list."""
    if mode_service.is_local(session):
        raise RuntimeError("This installation manages its own accounts")

    jellyfin_settings = settings_service.load(session, "jellyfin")
    client = JellyfinClient(jellyfin_settings)
    if not client.configured or not client.api_key:
        raise RuntimeError("Jellyfin URL and API key are required to import users")

    jellyfin_users = await client.get_users()
    imported = 0
    for jellyfin_user in jellyfin_users:
        if not _is_allowed(jellyfin_settings, jellyfin_user):
            continue
        upsert_user(session, jellyfin_user)
        imported += 1

    return {"jellyfin_users": len(jellyfin_users), "imported": imported}


def effective_auto_approve(session: Session, user: User) -> bool:
    """Whether this user's requests start already approved."""
    general = settings_service.load(session, "general")
    if user.is_admin and general.admins_bypass_approval:
        return True
    if user.auto_approve is not None:
        return user.auto_approve
    return not general.require_approval
