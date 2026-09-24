"""Administration: settings, service tests, users, indexers and jobs."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import __version__
from ..jobs import queue
from ..models import Indexer, Job, User
from ..pipeline import namer
from ..providers.prowlarr import ProwlarrClient
from ..providers.qbittorrent import QbittorrentClient
from ..providers.slskd import SlskdProvider
from ..schemas import (
    IndexerOut,
    IndexerUpdate,
    NamingPreviewOut,
    NamingPreviewRequest,
    PasswordReset,
    TestResult,
    UserCreate,
    UserOut,
    UserUpdate,
)
from ..security import MASK
from ..services import coverart
from ..services import indexers as indexers_service
from ..services import mode as mode_service
from ..services import settings as settings_service
from ..services import users as users_service
from ..services.base import ServiceError
from ..services.coverart import CoverArtClient
from ..services.jellyfin import JellyfinClient
from ..services.lastfm import LastfmClient
from ..services.listenbrainz import ListenBrainzClient
from ..services.musicbrainz import MusicBrainzClient
from .deps import AdminUser, SessionDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


def _section_with_overrides(session: Session, section: str, overrides: dict[str, Any] | None):
    """Build a section instance without persisting it, for connection tests."""
    current = settings_service.load(session, section)
    if not overrides:
        return current
    model = settings_service.SECTION_MODELS[section]
    merged = current.model_dump()
    for key, value in overrides.items():
        if key not in merged:
            continue
        if key in model.secret_fields and isinstance(value, str) and value.strip() in (MASK, ""):
            continue
        merged[key] = value
    return model.model_validate(merged)


@router.get("/settings")
async def get_all_settings(session: SessionDep, admin: AdminUser) -> dict[str, Any]:
    return {
        name: settings_service.to_public(name, instance)
        for name, instance in settings_service.load_all(session).items()
    }


@router.get("/settings/{section}")
async def get_settings(section: str, session: SessionDep, admin: AdminUser) -> dict[str, Any]:
    if section not in settings_service.SECTION_MODELS:
        raise HTTPException(status_code=404, detail="Unknown settings section")
    return settings_service.to_public(section, settings_service.load(session, section))


@router.put("/settings/{section}")
async def update_settings(
    section: str,
    session: SessionDep,
    admin: AdminUser,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    if section not in settings_service.SECTION_MODELS:
        raise HTTPException(status_code=404, detail="Unknown settings section")
    if section == "jellyfin" and mode_service.is_local(session):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This installation runs without Jellyfin",
        )
    # The mode is decided once, by the wizard. Flipping it on a live install
    # would strand every account: a Jellyfin one has no password stored here,
    # a local one has no Jellyfin identity there.
    payload.pop("mode", None)
    previous = settings_service.load(session, section)
    try:
        updated = settings_service.save(session, section, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if section == "coverart" and previous.url != updated.url:
        # A wrong URL answers 404 and poisons the "no cover" markers for a week.
        removed = coverart.purge_cache()
        logger.info("Cover art URL changed, %s cached file(s) dropped", removed)
    if section == "prowlarr" and updated.url and updated.api_key:
        queue.enqueue(session, queue.INDEXERS_SYNC)
    if section == "jellyfin" and updated.url and updated.api_key:
        queue.enqueue(session, queue.USERS_SYNC)
        queue.enqueue(session, queue.LIBRARY_SYNC)

    return settings_service.to_public(section, updated)


# ---------------------------------------------------------------- self tests


@router.post("/test/{service}", response_model=TestResult)
async def test_service(
    service: str,
    session: SessionDep,
    admin: AdminUser,
    overrides: dict[str, Any] = Body(default_factory=dict),
) -> TestResult:
    if service == "jellyfin" and mode_service.is_local(session):
        return TestResult(ok=False, message="This installation runs without Jellyfin")
    try:
        if service == "jellyfin":
            client = JellyfinClient(_section_with_overrides(session, "jellyfin", overrides))
            details = await client.test_connection()
            return TestResult(
                ok=True,
                message=f"Connected to {details.get('server_name')} "
                f"({details.get('version')}), "
                f"{len(details.get('music_libraries') or [])} music library(ies)",
                details=details,
            )

        if service == "musicbrainz":
            client = MusicBrainzClient(_section_with_overrides(session, "musicbrainz", overrides))
            details = await client.test_connection()
            message = "Lookup available"
            if details.get("search"):
                message += ", text search available"
                if details.get("fallback_used"):
                    message += " through the public server"
            else:
                message += ", but text search is unavailable (Solr missing?)"
            return TestResult(ok=True, message=message, details=details)

        if service == "listenbrainz":
            client = ListenBrainzClient(
                _section_with_overrides(session, "listenbrainz", overrides)
            )
            details = await client.test_connection()
            message = "ListenBrainz reachable"
            if details.get("labs"):
                message += ", similar artists available"
            else:
                message += ", but the Labs API did not answer: recommendations will be empty"
            return TestResult(ok=True, message=message, details=details)

        if service == "lastfm":
            client = LastfmClient(_section_with_overrides(session, "lastfm", overrides))
            details = await client.test_connection()
            message = "API key accepted"
            if not details.get("has_secret"):
                message += ". Add the shared secret to allow scrobbling"
            return TestResult(ok=True, message=message, details=details)

        if service == "coverart":
            client = CoverArtClient(_section_with_overrides(session, "coverart", overrides))
            details = await client.test_connection()
            found = bool(details.get("cover_found"))
            return TestResult(
                ok=True,
                message=(
                    f"Cover Art Archive reachable at {client.base_url}"
                    if found
                    else f"{client.base_url} answers (HTTP {details.get('status')}) but returned "
                    "no image for the test album"
                ),
                details=details,
            )

        if service == "slskd":
            provider = SlskdProvider(_section_with_overrides(session, "slskd", overrides))
            details = await provider.test_connection()
            connected = details.get("logged_in")
            readable = details.get("downloads_dir_readable")
            if not connected:
                message = "slskd answers but is not logged in to the Soulseek network"
            elif not readable:
                message = (
                    f"slskd {details.get('version')} connected as {details.get('username')}, "
                    f"but Muzikk cannot read \"{details.get('downloads_dir')}\". Downloads would "
                    "succeed and then be lost: point this field at the folder slskd downloads "
                    "into, as Muzikk sees it, and mount that volume in both containers."
                )
            else:
                message = (
                    f"slskd {details.get('version')} connected as {details.get('username')}, "
                    f"downloads read from {details.get('downloads_dir')}"
                )
            return TestResult(ok=bool(connected and readable), message=message, details=details)

        if service == "prowlarr":
            client = ProwlarrClient(_section_with_overrides(session, "prowlarr", overrides))
            details = await client.test_connection()
            return TestResult(
                ok=True,
                message=f"{details.get('music_indexers')} music indexer(s) "
                f"out of {details.get('indexers')}",
                details=details,
            )

        if service == "qbittorrent":
            client = QbittorrentClient(_section_with_overrides(session, "qbittorrent", overrides))
            try:
                details = await client.test_connection()
            finally:
                await client.close()
            return TestResult(
                ok=True,
                message=f"qBittorrent {details.get('version')} reachable",
                details=details,
            )
    except ServiceError as exc:
        return TestResult(ok=False, message=exc.message)
    except Exception as exc:  # noqa: BLE001 - a failed test must never 500
        logger.exception("Connection test failed for %s", service)
        return TestResult(ok=False, message=str(exc))

    raise HTTPException(status_code=404, detail="Unknown service")


@router.post("/jellyfin/libraries")
async def jellyfin_libraries(
    session: SessionDep,
    admin: AdminUser,
    overrides: dict[str, Any] = Body(default_factory=dict),
) -> list[dict[str, Any]]:
    if mode_service.is_local(session):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This installation runs without Jellyfin"
        )
    client = JellyfinClient(_section_with_overrides(session, "jellyfin", overrides))
    try:
        return await client.get_music_libraries()
    except ServiceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message) from exc


# -------------------------------------------------------------------- users


def _require_local_accounts(session: Session) -> None:
    if not mode_service.is_local(session):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Accounts come from Jellyfin on this installation",
        )


def _admin_count(session: Session) -> int:
    return (
        session.execute(
            select(func.count())
            .select_from(User)
            .where(User.is_admin.is_(True))
            .where(User.is_enabled.is_(True))
        ).scalar()
        or 0
    )


@router.get("/users", response_model=list[UserOut])
async def list_users(session: SessionDep, admin: AdminUser) -> list[UserOut]:
    rows = session.execute(select(User).order_by(User.name.asc())).scalars().all()
    return [UserOut.model_validate(row) for row in rows]


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(payload: UserCreate, session: SessionDep, admin: AdminUser) -> UserOut:
    _require_local_accounts(session)
    try:
        user = users_service.create_local_user(
            session,
            username=payload.username,
            password=payload.password,
            display_name=payload.name,
            is_admin=payload.is_admin,
            can_request=payload.can_request,
            can_upgrade=payload.can_upgrade,
            can_import=payload.can_import,
            weekly_quota=payload.weekly_quota,
        )
    except users_service.AccountError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return UserOut.model_validate(user)


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int, payload: UserUpdate, session: SessionDep, admin: AdminUser
) -> UserOut:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id and payload.is_admin is False:
        raise HTTPException(status_code=400, detail="You cannot remove your own admin rights")
    if user.id == admin.id and payload.is_enabled is False:
        raise HTTPException(status_code=400, detail="You cannot disable your own account")

    changes = payload.model_dump(exclude_unset=True)
    username = changes.pop("username", None)
    if username is not None:
        try:
            users_service.rename_local_user(session, user, username)
        except users_service.AccountError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    display_name = changes.pop("name", None)
    if display_name is not None:
        if user.username is None:
            raise HTTPException(status_code=422, detail="Jellyfin owns the name of this account")
        if not display_name.strip():
            raise HTTPException(status_code=422, detail="A display name cannot be empty")
        user.name = display_name.strip()[:255]

    for field, value in changes.items():
        setattr(user, field, value)
    session.commit()
    session.refresh(user)
    return UserOut.model_validate(user)


@router.post("/users/{user_id}/password")
async def reset_password(
    user_id: int, payload: PasswordReset, session: SessionDep, admin: AdminUser
) -> dict[str, bool]:
    _require_local_accounts(session)
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        users_service.set_password(session, user, payload.password)
    except users_service.AccountError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True}


@router.delete("/users/{user_id}")
async def delete_user(user_id: int, session: SessionDep, admin: AdminUser) -> dict[str, bool]:
    _require_local_accounts(session)
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")
    if user.is_admin and _admin_count(session) <= 1:
        raise HTTPException(status_code=400, detail="The last administrator cannot be deleted")
    # The requests, follows and wishlist of this account go with it.
    session.delete(user)
    session.commit()
    return {"ok": True}


@router.post("/users/sync")
async def sync_users(session: SessionDep, admin: AdminUser) -> dict[str, int]:
    try:
        return await users_service.sync_users(session)
    except (RuntimeError, ServiceError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ----------------------------------------------------------------- indexers


@router.get("/indexers", response_model=list[IndexerOut])
async def list_indexers(session: SessionDep, admin: AdminUser) -> list[IndexerOut]:
    grouped = indexers_service.grouped_indexers(session)
    ordered = grouped.get("torrent_public", []) + grouped.get("torrent_private", [])
    return [IndexerOut.model_validate(row) for row in ordered]


@router.patch("/indexers/{indexer_id}", response_model=IndexerOut)
async def update_indexer(
    indexer_id: int, payload: IndexerUpdate, session: SessionDep, admin: AdminUser
) -> IndexerOut:
    row = session.get(Indexer, indexer_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Indexer not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    session.commit()
    session.refresh(row)
    return IndexerOut.model_validate(row)


@router.post("/indexers/sync")
async def sync_indexers(session: SessionDep, admin: AdminUser) -> dict[str, int]:
    try:
        return await indexers_service.sync_indexers(session)
    except (RuntimeError, ServiceError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ------------------------------------------------------------------- naming


@router.post("/naming/preview", response_model=NamingPreviewOut)
async def naming_preview(
    payload: NamingPreviewRequest, session: SessionDep, admin: AdminUser
) -> NamingPreviewOut:
    naming = settings_service.load(session, "naming")
    template = payload.template or naming.album_template
    try:
        return NamingPreviewOut(template=template, examples=namer.preview(naming, template))
    except ValueError as exc:
        return NamingPreviewOut(template=template, examples=[], error=str(exc))


# --------------------------------------------------------------------- jobs


@router.get("/jobs")
async def list_jobs(
    session: SessionDep,
    admin: AdminUser,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict[str, Any]]:
    rows = session.execute(select(Job).order_by(Job.id.desc()).limit(limit)).scalars().all()
    return [
        {
            "id": row.id,
            "kind": row.kind,
            "state": row.state,
            "request_id": row.request_id,
            "attempts": row.attempts,
            "run_after": row.run_after,
            "started_at": row.started_at,
            "finished_at": row.finished_at,
            "error": row.error,
        }
        for row in rows
    ]


@router.post("/jobs/{kind}")
async def run_job(kind: str, session: SessionDep, admin: AdminUser) -> dict[str, Any]:
    allowed = {
        queue.LIBRARY_SYNC,
        queue.USERS_SYNC,
        queue.INDEXERS_SYNC,
        queue.WATCHLIST_CHECK,
        queue.WISHLIST_RETRY,
        queue.RETRY_FAILED,
        queue.PRUNE_EVENTS,
        queue.RECOMMENDATIONS,
    }
    if mode_service.is_local(session):
        allowed.discard(queue.USERS_SYNC)
    if kind not in allowed:
        raise HTTPException(status_code=400, detail="This job cannot be triggered manually")
    job = queue.enqueue(session, kind)
    return {"queued": True, "job_id": job.id if job else None}


@router.post("/covers/purge")
async def purge_covers(session: SessionDep, admin: AdminUser) -> dict[str, int]:
    return {"removed": coverart.purge_cache()}


@router.get("/system")
async def system_info(session: SessionDep, admin: AdminUser) -> dict[str, Any]:
    from ..config import get_env_config

    env = get_env_config()
    all_settings = settings_service.load_all(session)
    active_mode = mode_service.current(session)
    configured = {
        "musicbrainz": bool(all_settings["musicbrainz"].url),
        "slskd": bool(all_settings["slskd"].url and all_settings["slskd"].api_key),
        "prowlarr": bool(all_settings["prowlarr"].url and all_settings["prowlarr"].api_key),
        "qbittorrent": bool(all_settings["qbittorrent"].url),
        "listenbrainz": bool(all_settings["listenbrainz"].enabled),
        "lastfm": bool(all_settings["lastfm"].enabled and all_settings["lastfm"].api_key),
    }
    if active_mode == mode_service.JELLYFIN:
        configured["jellyfin"] = bool(
            all_settings["jellyfin"].url and all_settings["jellyfin"].api_key
        )
    return {
        "version": __version__,
        "mode": active_mode,
        "config_dir": str(env.config_dir),
        "music_dir": all_settings["naming"].music_dir,
        "worker_concurrency": env.worker_concurrency,
        "configured": configured,
        "provider_order": all_settings["providers"].order,
    }
