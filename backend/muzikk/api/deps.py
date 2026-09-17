"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import User
from ..security import decode_access_token

SESSION_COOKIE = "muzikk_token"

SessionDep = Annotated[Session, Depends(get_session)]


def _extract_token(request: Request) -> str | None:
    header = request.headers.get("Authorization") or ""
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return request.cookies.get(SESSION_COOKIE)


def get_current_user_optional(request: Request, session: SessionDep) -> User | None:
    token = _extract_token(request)
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload:
        return None
    try:
        user_id = int(payload.get("sub", ""))
    except (TypeError, ValueError):
        return None
    user = session.get(User, user_id)
    if user is None or not user.is_enabled:
        return None
    return user


def get_current_user(request: Request, session: SessionDep) -> User:
    user = get_current_user_optional(request, session)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def authorize_media(request: Request, session: Session, token: str | None) -> User:
    """Authenticate a request coming from an ``<img>`` or ``<audio>`` tag.

    Those elements cannot carry an Authorization header, so a short lived
    session token passed in the query string is accepted as well.
    """
    user = get_current_user_optional(request, session)
    if user is not None:
        return user

    payload = decode_access_token(token or "")
    if payload:
        try:
            user = session.get(User, int(payload.get("sub", "")))
        except (TypeError, ValueError):
            user = None
        if user is not None and user.is_enabled:
            return user
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")


def require_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator only")
    return user


def require_import(user: Annotated[User, Depends(get_current_user)]) -> User:
    if not user.can_import:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Local import is not allowed for this account",
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
AdminUser = Annotated[User, Depends(require_admin)]
ImportUser = Annotated[User, Depends(require_import)]
OptionalUser = Annotated[User | None, Depends(get_current_user_optional)]
