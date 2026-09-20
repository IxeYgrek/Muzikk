"""Login, logout and session introspection."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status

from ..schemas import LoginRequest, PasswordChange, SessionOut, UserOut
from ..security import create_access_token, verify_password
from ..services import mode as mode_service
from ..services import settings as settings_service
from ..services import users as users_service
from ..services.jellyfin import JellyfinClient
from .deps import SESSION_COOKIE, CurrentUser, SessionDep

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=SessionOut)
async def login(payload: LoginRequest, response: Response, session: SessionDep) -> SessionOut:
    try:
        user = await users_service.authenticate(session, payload.username, payload.password)
    except users_service.AuthError as exc:
        code = status.HTTP_401_UNAUTHORIZED
        if exc.code in ("not_configured", "unreachable"):
            code = status.HTTP_503_SERVICE_UNAVAILABLE
        elif exc.code in ("forbidden", "disabled"):
            code = status.HTTP_403_FORBIDDEN
        raise HTTPException(status_code=code, detail=str(exc)) from exc

    token, expires_at = create_access_token(str(user.id), {"admin": user.is_admin})
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        expires=expires_at,
        path="/",
    )
    return SessionOut(
        token=token,
        expires_at=expires_at,
        user=UserOut.model_validate(user),
        auto_approve=users_service.effective_auto_approve(session, user),
    )


@router.post("/logout")
async def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me", response_model=SessionOut)
async def me(user: CurrentUser, session: SessionDep) -> SessionOut:
    token, expires_at = create_access_token(str(user.id), {"admin": user.is_admin})
    return SessionOut(
        token=token,
        expires_at=expires_at,
        user=UserOut.model_validate(user),
        auto_approve=users_service.effective_auto_approve(session, user),
    )


@router.post("/password")
async def change_password(
    payload: PasswordChange, user: CurrentUser, session: SessionDep
) -> dict[str, bool]:
    """Let a local account change its own password."""
    if user.username is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This account is managed by Jellyfin, change its password there",
        )
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="The current password is wrong"
        )
    try:
        users_service.set_password(session, user, payload.password)
    except users_service.AccountError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True}


@router.get("/server")
async def server_info(session: SessionDep) -> dict[str, object]:
    """Public information used by the login screen."""
    active_mode = mode_service.current(session)
    if active_mode == mode_service.LOCAL:
        # Nothing to probe: the accounts live here.
        return {"mode": active_mode, "jellyfin_configured": False, "jellyfin_server_name": None}

    jellyfin_settings = settings_service.load(session, "jellyfin")
    configured = bool(jellyfin_settings.url)
    server_name = None
    if configured:
        try:
            info = await JellyfinClient(jellyfin_settings).get_public_system_info()
            server_name = (info or {}).get("ServerName")
        except Exception:  # noqa: BLE001 - the login page must render regardless
            server_name = None
    return {
        "mode": active_mode,
        "jellyfin_configured": configured,
        "jellyfin_server_name": server_name,
    }
