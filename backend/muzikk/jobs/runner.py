"""Background worker and periodic scheduler."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from ..config import get_env_config
from ..db import session_scope
from ..models import Download, MetadataAlbum, Request, RequestStatus, utcnow
from ..pipeline.orchestrator import orchestrator
from ..services import coverfiles as coverfiles_service
from ..services import indexers as indexers_service
from ..services import jellyfincovers as jellyfincovers_service
from ..services import jellyfinmeta as jellyfinmeta_service
from ..services import library_sync as library_sync_service
from ..services import metadata as metadata_service
from ..services import mode as mode_service
from ..services import settings as settings_service
from ..services import users as users_service
from ..services import watchlist as watchlist_service
from . import queue

logger = logging.getLogger(__name__)

IDLE_SLEEP_SECONDS = 2.0
TICK_SECONDS = 60.0


async def _process_request(payload: dict[str, Any]) -> None:
    request_id = int(payload.get("request_id") or 0)
    if request_id:
        await orchestrator.process_request(request_id)


async def _resume_download(payload: dict[str, Any]) -> None:
    request_id = int(payload.get("request_id") or 0)
    download_id = int(payload.get("download_id") or 0)
    if request_id and download_id:
        await orchestrator.resume_download(request_id, download_id)


async def _library_sync(_: dict[str, Any]) -> None:
    with session_scope() as session:
        result = await library_sync_service.sync(session)
    logger.info("Library sync finished: %s", result)


async def _users_sync(_: dict[str, Any]) -> None:
    with session_scope() as session:
        result = await users_service.sync_users(session)
    logger.info("User import finished: %s", result)


async def _indexers_sync(_: dict[str, Any]) -> None:
    with session_scope() as session:
        result = await indexers_service.sync_indexers(session)
    logger.info("Indexer sync finished: %s", result)


async def _watchlist_check(_: dict[str, Any]) -> None:
    with session_scope() as session:
        result = await watchlist_service.check_watched_artists(session)
    logger.info("Watchlist check finished: %s", result)


async def _wishlist_refresh(_: dict[str, Any]) -> None:
    with session_scope() as session:
        result = await watchlist_service.refresh_wishlist(session)
    logger.info("Wishlist refresh finished: %s", result)


async def _retry_failed(_: dict[str, Any]) -> None:
    with session_scope() as session:
        result = await watchlist_service.retry_failed_requests(session)
    if result.get("requeued"):
        logger.info("Failed requests requeued: %s", result)


async def _metadata_scan(_: dict[str, Any]) -> None:
    with session_scope() as session:
        result = await metadata_service.scan_library(session)
    logger.info("Metadata scan finished: %s", result)


async def _artwork_sync(_: dict[str, Any]) -> None:
    with session_scope() as session:
        result = await coverfiles_service.sync_library(session)
    logger.info("Artwork sync finished: %s", result)


async def _jellyfin_covers(_: dict[str, Any]) -> None:
    with session_scope() as session:
        result = await jellyfincovers_service.repair_covers(session)
    logger.info("Jellyfin cover repair finished: %s", result)


async def _jellyfin_metadata(payload: dict[str, Any]) -> None:
    album_id = payload.get("album_id")
    chain = int(payload.get("chain") or 0)
    with session_scope() as session:
        result = await jellyfinmeta_service.align_metadata(
            session, album_id=int(album_id) if album_id else None
        )
        # A pass is capped, so a library with hundreds of albums out of step
        # needs several. It queues its own follow-up rather than waiting for
        # someone to press the button again, and the chain is bounded so a
        # value Jellyfin refuses to keep cannot loop for ever.
        if not album_id and result.get("left") and chain < jellyfinmeta_service.MAX_CHAINED_PASSES:
            queue.enqueue(
                session, queue.JELLYFIN_METADATA, {"chain": chain + 1}, priority=3, unique=False
            )
    logger.info("Jellyfin metadata alignment finished: %s", result)


async def _prune_events(_: dict[str, Any]) -> None:
    from ..models import RequestEvent

    with session_scope() as session:
        general = settings_service.load(session, "general")
        cutoff = utcnow() - timedelta(days=max(1, general.keep_events_days))
        stale = (
            session.execute(select(RequestEvent).where(RequestEvent.created_at < cutoff))
            .scalars()
            .all()
        )
        for event in stale:
            session.delete(event)
        removed_jobs = queue.prune(session)
    if stale or removed_jobs:
        logger.info("Pruned %s events and %s jobs", len(stale), removed_jobs)


HANDLERS: dict[str, Callable[[dict[str, Any]], Awaitable[None]]] = {
    queue.PROCESS_REQUEST: _process_request,
    queue.RESUME_DOWNLOAD: _resume_download,
    queue.LIBRARY_SYNC: _library_sync,
    queue.USERS_SYNC: _users_sync,
    queue.INDEXERS_SYNC: _indexers_sync,
    queue.WATCHLIST_CHECK: _watchlist_check,
    queue.WISHLIST_RETRY: _wishlist_refresh,
    queue.RETRY_FAILED: _retry_failed,
    queue.PRUNE_EVENTS: _prune_events,
    queue.METADATA_SCAN: _metadata_scan,
    queue.ARTWORK_SYNC: _artwork_sync,
    queue.JELLYFIN_COVERS: _jellyfin_covers,
    queue.JELLYFIN_METADATA: _jellyfin_metadata,
}


class Worker:
    """Consumes the job table with a small pool of coroutines."""

    def __init__(self, concurrency: int | None = None) -> None:
        env = get_env_config()
        self.concurrency = concurrency or env.worker_concurrency
        self._tasks: list[asyncio.Task[None]] = []
        self._stopping = asyncio.Event()
        self._last_run: dict[str, float] = {}

    async def start(self) -> None:
        self._recover()
        for index in range(self.concurrency):
            self._tasks.append(asyncio.create_task(self._consume(index), name=f"muzikk-worker-{index}"))
        self._tasks.append(asyncio.create_task(self._tick(), name="muzikk-scheduler"))
        logger.info("Worker started with %s slots", self.concurrency)

    async def stop(self) -> None:
        self._stopping.set()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001
                logger.debug("Worker task ended with an error", exc_info=True)
        self._tasks.clear()

    def _recover(self) -> None:
        """Pick up whatever was in flight when the process stopped."""
        with session_scope() as session:
            requeued = queue.requeue_running(session)

            for request in (
                session.execute(
                    select(Request).where(Request.status.in_(RequestStatus.ACTIVE))
                )
                .scalars()
                .all()
            ):
                download = (
                    session.execute(
                        select(Download)
                        .where(Download.request_id == request.id)
                        .order_by(Download.id.desc())
                    )
                    .scalars()
                    .first()
                )
                if request.status == RequestStatus.DOWNLOADING and download is not None:
                    queue.enqueue(
                        session,
                        queue.RESUME_DOWNLOAD,
                        {"request_id": request.id, "download_id": download.id},
                        request_id=request.id,
                        priority=5,
                    )
                else:
                    request.status = RequestStatus.APPROVED
                    session.commit()
                    queue.enqueue(
                        session,
                        queue.PROCESS_REQUEST,
                        {"request_id": request.id},
                        request_id=request.id,
                    )

            for request in (
                session.execute(
                    select(Request).where(Request.status == RequestStatus.APPROVED)
                )
                .scalars()
                .all()
            ):
                queue.enqueue(
                    session,
                    queue.PROCESS_REQUEST,
                    {"request_id": request.id},
                    request_id=request.id,
                )

        if requeued:
            logger.info("%s interrupted job(s) put back in the queue", requeued)

    async def _consume(self, index: int) -> None:
        while not self._stopping.is_set():
            job_id: int | None = None
            kind = ""
            payload: dict[str, Any] = {}
            try:
                with session_scope() as session:
                    job = queue.claim_next(session)
                    if job is not None:
                        job_id = job.id
                        kind = job.kind
                        payload = dict(job.payload or {})
            except Exception:  # noqa: BLE001
                logger.exception("Unable to claim a job")
                await asyncio.sleep(IDLE_SLEEP_SECONDS)
                continue

            if job_id is None:
                await asyncio.sleep(IDLE_SLEEP_SECONDS)
                continue

            handler = HANDLERS.get(kind)
            error: str | None = None
            if handler is None:
                error = f"unknown job kind: {kind}"
            else:
                try:
                    await handler(payload)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Job %s (%s) failed", job_id, kind)
                    error = str(exc)

            try:
                with session_scope() as session:
                    queue.finish(session, job_id, error=error)
            except Exception:  # noqa: BLE001
                logger.exception("Unable to close job %s", job_id)

    def _due(self, key: str, interval_seconds: float) -> bool:
        now = time.monotonic()
        last = self._last_run.get(key)
        if last is None or now - last >= interval_seconds:
            self._last_run[key] = now
            return True
        return False

    def _metadata_scan_due(self, session) -> bool:
        """Whether tonight's library analysis still has to run.

        Freshness is read from the database rather than kept in memory, so a
        restart during the night does not trigger a second full scan.
        """
        config = settings_service.load(session, "metadata")
        if not config.nightly_scan:
            return False
        if datetime.now().hour != max(0, min(23, config.scan_hour)):
            return False

        last = session.execute(select(func.max(MetadataAlbum.scanned_at))).scalar()
        if last is None:
            return True
        return utcnow().replace(tzinfo=None) - last > timedelta(hours=20)

    async def _tick(self) -> None:
        # Give the API a moment to finish starting before hitting the network.
        await asyncio.sleep(15)
        while not self._stopping.is_set():
            try:
                with session_scope() as session:
                    general = settings_service.load(session, "general")
                    local = mode_service.is_local(session)
                    jellyfin = settings_service.load(session, "jellyfin")

                    # In local mode the index is ours to keep fresh. In
                    # Jellyfin mode there is nothing to pull until the server
                    # is reachable, and the accounts come along with it.
                    # Before the wizard finishes the music folder is still
                    # the default, so a tick would only fail or lock SQLite.
                    indexable = local or bool(jellyfin.url and jellyfin.api_key)
                    if (
                        general.setup_completed
                        and indexable
                        and self._due(
                            "library", max(5, general.library_scan_interval_minutes) * 60
                        )
                    ):
                        queue.enqueue(session, queue.LIBRARY_SYNC)
                        if not local:
                            queue.enqueue(session, queue.USERS_SYNC)

                    if self._due("watchlist", max(1, general.watchlist_check_interval_hours) * 3600):
                        queue.enqueue(session, queue.WATCHLIST_CHECK)
                        queue.enqueue(session, queue.WISHLIST_RETRY)

                    if self._due("retry", 15 * 60):
                        queue.enqueue(session, queue.RETRY_FAILED)

                    if self._metadata_scan_due(session):
                        queue.enqueue(session, queue.METADATA_SCAN)

                    if self._due("prune", 12 * 3600):
                        queue.enqueue(session, queue.PRUNE_EVENTS)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("Scheduler tick failed")

            await asyncio.sleep(TICK_SECONDS)


worker = Worker()
