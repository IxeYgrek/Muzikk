"""Live activity: server sent events, counters and recent history."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Query
from fastapi import Request as HttpRequest
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from ..db import session_scope
from ..models import (
    Download,
    LibraryAlbum,
    Request,
    RequestEvent,
    RequestStatus,
    User,
    WatchedArtist,
    WatchedRelease,
    WishlistItem,
)
from ..schemas import StatsOut
from ..services import catalog
from .deps import CurrentUser, SessionDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/activity", tags=["activity"])

STREAM_INTERVAL_SECONDS = 2.5


def _snapshot(user_id: int | None) -> dict[str, Any]:
    with session_scope() as session:
        statement = select(Request).where(
            Request.status.in_(
                (RequestStatus.PENDING, RequestStatus.APPROVED, *RequestStatus.ACTIVE)
            )
        )
        if user_id is not None:
            statement = statement.where(Request.user_id == user_id)

        # Ordered by request date: sorting on progress or on updated_at made the
        # tiles jump around on every refresh, which is unreadable.
        statement = statement.order_by(Request.created_at.asc(), Request.id.asc()).limit(50)
        rows = session.execute(statement).scalars().all()
        items = []
        for request in rows:
            download = (
                session.execute(
                    select(Download)
                    .where(Download.request_id == request.id)
                    .order_by(Download.id.desc())
                    .limit(1)
                )
                .scalars()
                .first()
            )
            items.append(
                {
                    "id": request.id,
                    "artist": request.artist_name,
                    "album": request.album_title,
                    "status": request.status,
                    "progress": round(request.progress, 1),
                    "provider": request.provider_label,
                    "cover_url": catalog.cover_url(
                        request.release_group_mbid, request.release_mbid
                    ),
                    "error": request.error,
                    "speed": download.speed if download else 0,
                    "eta": download.eta if download else None,
                    "size": download.size if download else 0,
                    "downloaded": download.downloaded if download else 0,
                    "client": download.client if download else None,
                }
            )

        counts = {
            "pending": session.execute(
                select(func.count()).select_from(Request).where(Request.status == RequestStatus.PENDING)
            ).scalar()
            or 0,
            "active": session.execute(
                select(func.count())
                .select_from(Request)
                .where(Request.status.in_(RequestStatus.ACTIVE))
            ).scalar()
            or 0,
            "failed": session.execute(
                select(func.count()).select_from(Request).where(Request.status == RequestStatus.FAILED)
            ).scalar()
            or 0,
        }

    return {"items": items, "counts": counts}


@router.get("/summary")
async def summary(user: CurrentUser) -> dict[str, Any]:
    return _snapshot(None if user.is_admin else user.id)


@router.get("/stream")
async def stream(http_request: HttpRequest, user: CurrentUser) -> StreamingResponse:
    user_id = None if user.is_admin else user.id

    async def event_source():
        last_payload: str | None = None
        try:
            while True:
                if await http_request.is_disconnected():
                    break
                payload = json.dumps(_snapshot(user_id), default=str)
                if payload != last_payload:
                    last_payload = payload
                    yield f"data: {payload}\n\n"
                else:
                    yield ": keep-alive\n\n"
                await asyncio.sleep(STREAM_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Activity stream interrupted")

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/events")
async def recent_events(
    session: SessionDep,
    user: CurrentUser,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, Any]]:
    statement = (
        select(RequestEvent, Request)
        .join(Request, Request.id == RequestEvent.request_id)
        .order_by(RequestEvent.id.desc())
        .limit(limit)
    )
    if not user.is_admin:
        statement = statement.where(Request.user_id == user.id)

    return [
        {
            "id": event.id,
            "request_id": event.request_id,
            "created_at": event.created_at,
            "level": event.level,
            "stage": event.stage,
            "message": event.message,
            "artist": request.artist_name,
            "album": request.album_title,
        }
        for event, request in session.execute(statement).all()
    ]


@router.get("/stats", response_model=StatsOut)
async def stats(session: SessionDep, user: CurrentUser) -> StatsOut:
    def count(model, *conditions) -> int:
        statement = select(func.count()).select_from(model)
        for condition in conditions:
            statement = statement.where(condition)
        return session.execute(statement).scalar() or 0

    return StatsOut(
        users=count(User),
        library_albums=count(LibraryAlbum),
        library_lossless=count(LibraryAlbum, LibraryAlbum.is_lossless.is_(True)),
        requests_total=count(Request),
        requests_pending=count(Request, Request.status == RequestStatus.PENDING),
        requests_active=count(Request, Request.status.in_(RequestStatus.ACTIVE)),
        # Only the caller's own, unless they administer: an upgrade is validated
        # by whoever asked for it, and the badge has to speak to that person.
        requests_to_validate=count(
            Request,
            Request.status == RequestStatus.AWAITING_VALIDATION,
            *([] if user.is_admin else [Request.user_id == user.id]),
        ),
        requests_failed=count(Request, Request.status == RequestStatus.FAILED),
        requests_imported=count(Request, Request.status == RequestStatus.IMPORTED),
        watched_artists=count(WatchedArtist),
        # The follow tab speaks to one follower at a time, admin or not.
        watchlist_missing=(
            session.execute(
                select(func.count())
                .select_from(WatchedRelease)
                .join(WatchedArtist, WatchedArtist.id == WatchedRelease.watch_id)
                .where(WatchedArtist.user_id == user.id)
                .where(WatchedRelease.ignored.is_(False))
            ).scalar()
            or 0
        ),
        wishlist_items=count(WishlistItem, WishlistItem.is_active.is_(True)),
    )
