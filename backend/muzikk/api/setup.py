"""First run wizard.

Nobody can log in before Muzikk knows where its accounts come from, so these
endpoints are open until the wizard is completed, after which they refuse
every call. The first question they ask is the only one that cannot be
revisited later: whether Jellyfin owns the users and the library, or whether
Muzikk handles both on its own.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, HTTPException, status
from sqlalchemy import func, select

from ..jobs import queue
from ..models import User
from ..schemas import TestResult
from ..services import mode as mode_service
from ..services import settings as settings_service
from ..services import users as users_service
from ..services.base import ServiceError
from ..services.jellyfin import JellyfinClient
from .deps import SessionDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/setup", tags=["setup"])


def _guard(session: SessionDep) -> None:
    general = settings_service.load(session, "general")
    if general.setup_completed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Setup is already completed, use the administration pages",
        )


def _require_jellyfin_mode(session: SessionDep) -> None:
    if mode_service.is_local(session):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This installation is being set up without Jellyfin",
        )


def _music_dir(payload: dict[str, Any]) -> str:
    """The library folder, checked before it becomes the whole library.

    An empty folder is fine, a fresh install has nothing in it yet. A folder
    Muzikk cannot see is not: in local mode it would leave the interface
    permanently empty with no explanation.
    """
    value = str(payload.get("music_dir") or "").strip()
    if not value:
        raise HTTPException(status_code=422, detail="A music folder is required")
    if not Path(value).is_dir():
        raise HTTPException(
            status_code=422,
            detail=f'Muzikk cannot see the folder "{value}": check the volume mounted '
            "on the container",
        )
    return value


@router.get("/status")
async def setup_status(session: SessionDep) -> dict[str, Any]:
    general = settings_service.load(session, "general")
    jellyfin = settings_service.load(session, "jellyfin")
    users = session.execute(select(func.count()).select_from(User)).scalar() or 0
    return {
        "setup_completed": general.setup_completed,
        "mode": mode_service.current(session),
        "jellyfin_configured": bool(jellyfin.url and jellyfin.api_key),
        "users": users,
    }


@router.post("/mode")
async def choose_mode(
    session: SessionDep, payload: dict[str, Any] = Body(default_factory=dict)
) -> dict[str, Any]:
    _guard(session)
    value = str(payload.get("mode") or "").strip().lower()
    if value not in mode_service.MODES:
        raise HTTPException(status_code=422, detail="Unknown mode")
    settings_service.save(session, "general", {"mode": value})
    return {"mode": value}


@router.post("/jellyfin", response_model=TestResult)
async def configure_jellyfin(
    session: SessionDep, payload: dict[str, Any] = Body(default_factory=dict)
) -> TestResult:
    _guard(session)
    _require_jellyfin_mode(session)
    url = str(payload.get("url") or "").strip()
    api_key = str(payload.get("api_key") or "").strip()
    if not url or not api_key:
        raise HTTPException(status_code=422, detail="A Jellyfin URL and API key are required")

    model = settings_service.SECTION_MODELS["jellyfin"]
    probe = model.model_validate(
        {**settings_service.load(session, "jellyfin").model_dump(), "url": url, "api_key": api_key}
    )
    client = JellyfinClient(probe)
    try:
        details = await client.test_connection()
    except ServiceError as exc:
        return TestResult(ok=False, message=exc.message)

    settings_service.save(session, "jellyfin", {"url": url, "api_key": api_key})
    return TestResult(
        ok=True,
        message=f"Connected to {details.get('server_name')} ({details.get('version')})",
        details=details,
    )


@router.get("/libraries")
async def setup_libraries(session: SessionDep) -> list[dict[str, Any]]:
    _guard(session)
    _require_jellyfin_mode(session)
    jellyfin = settings_service.load(session, "jellyfin")
    if not jellyfin.url or not jellyfin.api_key:
        raise HTTPException(status_code=400, detail="Configure Jellyfin first")
    try:
        return await JellyfinClient(jellyfin).get_music_libraries()
    except ServiceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message) from exc


async def _finish_jellyfin(session: SessionDep, payload: dict[str, Any]) -> dict[str, Any]:
    jellyfin = settings_service.load(session, "jellyfin")
    if not jellyfin.url or not jellyfin.api_key:
        raise HTTPException(status_code=400, detail="Configure Jellyfin first")

    library_ids = [str(item) for item in payload.get("music_library_ids") or []]
    if library_ids:
        settings_service.save(session, "jellyfin", {"music_library_ids": library_ids})

    music_dir = str(payload.get("music_dir") or "").strip()
    if music_dir:
        settings_service.save(session, "naming", {"music_dir": music_dir})

    try:
        imported = await users_service.sync_users(session)
    except (RuntimeError, ServiceError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not imported.get("imported"):
        raise HTTPException(
            status_code=400,
            detail="No Jellyfin user could be imported; check the API key permissions",
        )
    return dict(imported)


def _finish_local(session: SessionDep, payload: dict[str, Any]) -> dict[str, Any]:
    music_dir = _music_dir(payload)
    existing = session.execute(select(func.count()).select_from(User)).scalar() or 0
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This installation already has accounts"
        )

    try:
        admin = users_service.create_local_user(
            session,
            username=str(payload.get("username") or ""),
            password=str(payload.get("password") or ""),
            display_name=str(payload.get("name") or ""),
            is_admin=True,
        )
    except users_service.AccountError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    settings_service.save(session, "naming", {"music_dir": music_dir})
    return {"administrator": admin.username, "music_dir": music_dir}


@router.post("/finish")
async def finish_setup(
    session: SessionDep, payload: dict[str, Any] = Body(default_factory=dict)
) -> dict[str, Any]:
    _guard(session)
    if mode_service.is_local(session):
        result = _finish_local(session, payload)
    else:
        result = await _finish_jellyfin(session, payload)

    language = str(payload.get("language") or "en").strip().lower()
    if language not in ("fr", "en"):
        language = "en"
    settings_service.save(session, "general", {"setup_completed": True, "default_language": language})
    queue.enqueue(session, queue.LIBRARY_SYNC)
    return {"ok": True, **result}
