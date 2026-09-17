"""First run wizard.

Muzikk authenticates against Jellyfin, so nobody can log in before Jellyfin is
configured. These endpoints are therefore open until the wizard is completed,
after which they refuse every call.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, HTTPException, status
from sqlalchemy import func, select

from ..jobs import queue
from ..models import User
from ..schemas import TestResult
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


@router.get("/status")
async def setup_status(session: SessionDep) -> dict[str, Any]:
    general = settings_service.load(session, "general")
    jellyfin = settings_service.load(session, "jellyfin")
    users = session.execute(select(func.count()).select_from(User)).scalar() or 0
    return {
        "setup_completed": general.setup_completed,
        "jellyfin_configured": bool(jellyfin.url and jellyfin.api_key),
        "users": users,
    }


@router.post("/jellyfin", response_model=TestResult)
async def configure_jellyfin(
    session: SessionDep, payload: dict[str, Any] = Body(default_factory=dict)
) -> TestResult:
    _guard(session)
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
    jellyfin = settings_service.load(session, "jellyfin")
    if not jellyfin.url or not jellyfin.api_key:
        raise HTTPException(status_code=400, detail="Configure Jellyfin first")
    try:
        return await JellyfinClient(jellyfin).get_music_libraries()
    except ServiceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message) from exc


@router.post("/finish")
async def finish_setup(
    session: SessionDep, payload: dict[str, Any] = Body(default_factory=dict)
) -> dict[str, Any]:
    _guard(session)
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

    settings_service.save(session, "general", {"setup_completed": True})
    queue.enqueue(session, queue.LIBRARY_SYNC)
    return {"ok": True, **imported}
