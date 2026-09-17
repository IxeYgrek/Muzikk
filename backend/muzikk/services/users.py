"""User import and authentication against Jellyfin."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import User, utcnow
from ..security import decrypt_secret, encrypt_secret
from . import settings as settings_service
from .base import ServiceError
from .jellyfin import JellyfinClient

logger = logging.getLogger(__name__)


class AuthError(RuntimeError):
    """Raised when a login attempt must be refused."""

    def __init__(self, message: str, *, code: str = "invalid_credentials") -> None:
        super().__init__(message)
        self.code = code


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


async def authenticate(session: Session, username: str, password: str) -> User:
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
