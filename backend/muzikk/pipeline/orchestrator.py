"""Acquisition state machine.

One request goes through: searching -> matched -> downloading -> verifying ->
tagging -> importing -> imported. Any failure moves to the next candidate, then
to the next provider group, and finally schedules a retry.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import session_scope
from ..matching.release_picker import pick_release
from ..matching.scorer import MatchResult, rank_candidates, score_candidate
from ..models import Download, DownloadAttempt, Indexer, Request, RequestEvent, RequestStatus, utcnow
from ..providers.base import AlbumQuery, Candidate, DownloadHandle, Provider
from ..providers.prowlarr import ProwlarrClient, TorrentProvider, group_for_privacy
from ..providers.qbittorrent import QbittorrentClient
from ..providers.slskd import SlskdProvider
from ..jobs import queue
from ..services import clients
from ..services import mode as mode_service
from ..services import settings as settings_service
from ..services.base import ServiceError
from . import cleanup, salvage, verify
from .importer import ImportRequest, import_album

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 6
MAX_CANDIDATES_PER_PROVIDER = 6
STALL_TOLERANCE_BYTES = 1024
ACTIVE_TRANSFER_STATES = frozenset({"queued", "downloading", "stalled"})


class PipelineAborted(RuntimeError):
    """Raised when the request was cancelled while the pipeline was running."""


class PipelineBlocked(RuntimeError):
    """Raised when trying another candidate cannot possibly help.

    A transfer that completes and then cannot be imported points at the setup,
    not at the peer: retrying would re-download the same album for nothing.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(slots=True)
class ProviderBundle:
    providers: list[Provider]
    qbittorrent: QbittorrentClient | None

    async def close(self) -> None:
        if self.qbittorrent is not None:
            await self.qbittorrent.close()


def log_event(
    session: Session,
    request_id: int,
    stage: str,
    message: str,
    *,
    level: str = "info",
    data: dict[str, Any] | None = None,
) -> None:
    session.add(
        RequestEvent(
            request_id=request_id, stage=stage, message=message, level=level, data=data
        )
    )
    session.commit()
    if level == "error":
        logger.warning("[request %s/%s] %s", request_id, stage, message)
    else:
        logger.info("[request %s/%s] %s", request_id, stage, message)


def set_status(
    session: Session,
    request_id: int,
    status: str,
    *,
    error: str | None = None,
    progress: float | None = None,
    provider: Provider | None = None,
) -> None:
    request = session.get(Request, request_id)
    if request is None:
        return
    request.status = status
    if error is not None:
        request.error = error or None
    if progress is not None:
        request.progress = progress
    if provider is not None:
        request.provider_key = provider.key
        request.provider_label = provider.label
    if status in (RequestStatus.IMPORTED, RequestStatus.CANCELLED, RequestStatus.REJECTED):
        request.completed_at = utcnow()
    session.commit()


def build_providers(session: Session) -> ProviderBundle:
    """Instantiate the enabled providers in the configured priority order."""
    order = list(settings_service.load(session, "providers").order or [])
    slskd_settings = settings_service.load(session, "slskd")
    prowlarr_settings = settings_service.load(session, "prowlarr")
    qbittorrent_settings = settings_service.load(session, "qbittorrent")

    indexers = list(session.execute(select(Indexer)).scalars())
    prowlarr = ProwlarrClient(prowlarr_settings)
    qbittorrent = QbittorrentClient(qbittorrent_settings)

    available: dict[str, Provider] = {}

    slskd_provider = SlskdProvider(slskd_settings)
    if slskd_provider.enabled:
        available["slskd"] = slskd_provider

    for group in ("torrent_public", "torrent_private"):
        group_indexers = [
            indexer
            for indexer in indexers
            if indexer.enabled and group_for_privacy(indexer.privacy) == group
        ]
        if not group_indexers:
            continue
        group_indexers.sort(key=lambda item: (-item.priority, item.name.lower()))
        provider = TorrentProvider(
            group, group_indexers, prowlarr, qbittorrent, prowlarr_settings
        )
        if provider.enabled:
            available[group] = provider

    ordered: list[Provider] = [available[key] for key in order if key in available]
    ordered.extend(provider for key, provider in available.items() if key not in order)

    needs_qbittorrent = any(provider.kind == "torrent" for provider in ordered)
    return ProviderBundle(providers=ordered, qbittorrent=qbittorrent if needs_qbittorrent else None)


async def build_query(session: Session, request: Request) -> tuple[AlbumQuery, dict[str, Any]]:
    """Fetch the MusicBrainz release and derive the matching criteria."""
    client = clients.musicbrainz(session)
    release_mbid = request.release_mbid

    if not release_mbid:
        browse = await client.browse_releases_for_group(request.release_group_mbid)
        group = await client.get_release_group(request.release_group_mbid)
        recommended, _ = pick_release(
            (browse or {}).get("releases") or [],
            group_first_date=(group or {}).get("first-release-date"),
        )
        if recommended is None:
            raise ServiceError("musicbrainz", "this release group has no usable release")
        release_mbid = recommended.mbid

    release = await client.get_release(release_mbid)
    tracks: list[str] = []
    durations: list[int] = []
    artists: list[str] = []
    disc_count = 0
    for medium in release.get("media") or []:
        disc_count += 1
        for entry in medium.get("tracks") or []:
            recording = entry.get("recording") or {}
            tracks.append(entry.get("title") or recording.get("title") or "")
            length = entry.get("length") or recording.get("length")
            durations.append(int(length) if length else 0)
            credits = entry.get("artist-credit") or recording.get("artist-credit") or []
            if credits:
                artists.append(credits[0].get("name") or "")

    group_payload = release.get("release-group") or {}
    artist_credit = release.get("artist-credit") or []
    artist_name = "".join(
        [(credit.get("name") or "") + (credit.get("joinphrase") or "") for credit in artist_credit]
    ).strip()

    query = AlbumQuery(
        release_group_mbid=request.release_group_mbid,
        release_mbid=release_mbid,
        album=release.get("title") or request.album_title,
        artist=artist_name or request.artist_name,
        artist_mbid=request.artist_mbid,
        year=int((release.get("date") or group_payload.get("first-release-date") or "0000")[:4] or 0)
        or None,
        track_count=len(tracks),
        disc_count=max(1, disc_count),
        track_titles=tracks,
        track_durations_ms=durations,
        track_artists=artists,
    )
    return query, release


def latest_completed_download(session: Session, request_id: int) -> Download | None:
    """The most recent transfer that already finished for this request."""
    return (
        session.execute(
            select(Download)
            .where(Download.request_id == request_id, Download.state == "completed")
            .order_by(Download.id.desc())
        )
        .scalars()
        .first()
    )


def handle_from_download(row: Download) -> DownloadHandle:
    return DownloadHandle(
        client=row.client,
        external_id=row.external_id,
        username=row.username,
        payload=row.payload or {},
    )


def provider_for_download(providers: list[Provider], row: Download) -> Provider | None:
    key = (row.payload or {}).get("provider_key")
    if key:
        found = next((item for item in providers if item.key == key), None)
        if found is not None:
            return found
    if row.client == "slskd":
        return next((item for item in providers if item.key == "slskd"), None)
    if row.client == "qbittorrent":
        return next((item for item in providers if item.kind == "torrent"), None)
    return None


def record_attempt(
    session: Session,
    request_id: int,
    provider: Provider,
    candidate: Candidate,
    result: MatchResult,
    *,
    decision: str,
    reason: str = "",
) -> None:
    session.add(
        DownloadAttempt(
            request_id=request_id,
            provider_key=provider.key,
            provider_label=candidate.provider_label or provider.label,
            candidate_title=candidate.title[:1000],
            score=result.score,
            decision=decision,
            reason=reason or result.reason,
            details={
                **result.details,
                "size": candidate.size,
                "seeders": candidate.seeders,
                "username": candidate.username,
                "files": len(candidate.audio_files),
            },
        )
    )
    session.commit()


class Orchestrator:
    """Runs one request at a time through the whole acquisition pipeline."""

    async def process_request(self, request_id: int) -> None:
        with session_scope() as session:
            request = session.get(Request, request_id)
            if request is None:
                return
            if request.status in RequestStatus.TERMINAL:
                return
            if request.status == RequestStatus.AWAITING_VALIDATION:
                return
            if request.status == RequestStatus.PENDING:
                log_event(session, request_id, "queue", "waiting for administrator approval")
                return
            request.attempts += 1
            request.error = None
            request.exhausted_providers = []
            session.commit()

        bundle: ProviderBundle | None = None
        try:
            with session_scope() as session:
                set_status(session, request_id, RequestStatus.SEARCHING, progress=0.0)
                request = session.get(Request, request_id)
                log_event(
                    session,
                    request_id,
                    "search",
                    f"looking for {request.artist_name} - {request.album_title}",
                )
                query, release = await build_query(session, request)
                if request.release_mbid != query.release_mbid:
                    request.release_mbid = query.release_mbid
                request.track_count = query.track_count
                session.commit()
                log_event(
                    session,
                    request_id,
                    "search",
                    f"edition {query.release_mbid} selected: "
                    f"{query.track_count} tracks on {query.disc_count} disc(s)",
                    data={"release_mbid": query.release_mbid, "tracks": query.track_count},
                )
                bundle = build_providers(session)
                quality = settings_service.load(session, "quality")

            if await self._salvage_local_copy(request_id, query, release, quality):
                return
            if await self._reuse_completed_transfer(request_id, query, release):
                return
            with session_scope() as session:
                leftover = latest_completed_download(session, request_id)
            if leftover is not None:
                await self._abort_other_transfers(request_id, leftover.id)
                await self._fail(
                    request_id,
                    "a transfer already completed; the files could not be imported",
                    retry=False,
                )
                return

            if not bundle.providers:
                await self._fail(request_id, "no provider is configured or enabled")
                return

            blocked: str | None = None
            for provider in bundle.providers:
                try:
                    success = await self._try_provider(
                        request_id, provider, query, release, quality
                    )
                except PipelineBlocked as exc:
                    # The album did arrive: stop hammering this provider with
                    # the remaining candidates, but let the next one try.
                    blocked = exc.message
                    success = False
                if success:
                    return
                with session_scope() as session:
                    request = session.get(Request, request_id)
                    if request is not None:
                        request.exhausted_providers = [
                            *(request.exhausted_providers or []),
                            provider.key,
                        ]
                        session.commit()

            if blocked:
                # No automatic retry: an admin has to fix the setup first, or
                # every attempt downloads the whole album again for nothing.
                await self._fail(request_id, blocked, retry=False)
                return
            await self._fail(request_id, "no matching release found on any provider")

        except PipelineAborted:
            logger.info("Request %s was cancelled while running", request_id)
        except ServiceError as exc:
            await self._fail(request_id, exc.message)
        except Exception as exc:  # noqa: BLE001 - the worker must survive anything
            logger.exception("Unexpected failure while processing request %s", request_id)
            await self._fail(request_id, f"internal error: {exc}")
        finally:
            if bundle is not None:
                await bundle.close()

    # ------------------------------------------------------------- providers

    async def _abort_other_transfers(self, request_id: int, keep_id: int | None) -> None:
        """Stop every transfer of this request except the one that already won."""
        bundle: ProviderBundle | None = None
        with session_scope() as session:
            bundle = build_providers(session)
            rows = list(
                session.execute(select(Download).where(Download.request_id == request_id)).scalars()
            )
        try:
            for row in rows:
                if keep_id is not None and row.id == keep_id:
                    continue
                if row.state not in ACTIVE_TRANSFER_STATES:
                    continue
                provider = provider_for_download(bundle.providers, row)
                if provider is None:
                    continue
                try:
                    await provider.abort(handle_from_download(row))
                except Exception:  # noqa: BLE001 - still mark it cancelled
                    logger.warning(
                        "Unable to abort transfer %s of request %s", row.id, request_id,
                        exc_info=True,
                    )
                with session_scope() as session:
                    current = session.get(Download, row.id)
                    if current is not None and current.state in ACTIVE_TRANSFER_STATES:
                        current.state = "cancelled"
                        session.commit()
                    log_event(
                        session,
                        request_id,
                        "download",
                        f"cancelling {row.client}: another transfer already completed",
                        level="warning",
                    )
        finally:
            if bundle is not None:
                await bundle.close()

    async def _reuse_completed_transfer(
        self, request_id: int, query: AlbumQuery, release: dict[str, Any]
    ) -> bool:
        """Import a transfer that already finished, instead of starting a new one.

        An upgrade request still downloads once: this only blocks a second
        download of the same request after one source already completed.
        """
        bundle: ProviderBundle | None = None
        with session_scope() as session:
            row = latest_completed_download(session, request_id)
            if row is None:
                return False
            download_id = row.id
            path = row.content_path
            handle = handle_from_download(row)
            bundle = build_providers(session)
            provider = provider_for_download(bundle.providers, row)

        try:
            if provider is None:
                return False
            if not path or not Path(path).exists():
                status = await provider.status(handle)
                path = status.content_path
            if not path or not Path(path).exists():
                return False
            with session_scope() as session:
                log_event(
                    session,
                    request_id,
                    "download",
                    "a transfer already completed, importing it instead of downloading again",
                )
            await self._abort_other_transfers(request_id, download_id)
            return await self._verify_and_import(
                request_id, provider, handle, Path(path), query, release
            )
        finally:
            if bundle is not None:
                await bundle.close()

    async def _salvage_local_copy(
        self,
        request_id: int,
        query: AlbumQuery,
        release: dict[str, Any],
        quality,
    ) -> bool:
        """Import the album if a complete copy is already in the download folder."""
        with session_scope() as session:
            slskd_settings = settings_service.load(session, "slskd")

        # Only the Soulseek folder: a torrent still seeding must not be moved
        # out from under its client.
        if not slskd_settings.enabled:
            return False
        roots = [Path(slskd_settings.downloads_dir)]

        found = await asyncio.to_thread(salvage.find_local_album, roots, query, quality)
        if found is None:
            return False

        candidate, result = found
        with session_scope() as session:
            record_attempt(
                session, request_id, salvage.PROVIDER, candidate, result, decision="accepted"
            )
            log_event(
                session,
                request_id,
                "match",
                f"already downloaded in {candidate.directory} (score {result.score}), "
                "importing it instead of downloading it again",
                data=result.details,
            )
        return await self._verify_and_import(
            request_id,
            salvage.PROVIDER,
            salvage.HANDLE,
            Path(candidate.directory or ""),
            query,
            release,
        )

    async def _try_provider(
        self,
        request_id: int,
        provider: Provider,
        query: AlbumQuery,
        release: dict[str, Any],
        quality,
    ) -> bool:
        with session_scope() as session:
            # Back to zero: the percentage of the candidate we just gave up on
            # must not linger on the bar.
            set_status(session, request_id, RequestStatus.SEARCHING, provider=provider, progress=0.0)
            log_event(session, request_id, "search", f"querying {provider.label}")

        try:
            candidates = await provider.search(query)
        except ServiceError as exc:
            with session_scope() as session:
                log_event(
                    session, request_id, "search",
                    f"{provider.label} unavailable: {exc.message}", level="warning",
                )
            return False
        finally:
            purge = getattr(provider, "purge_searches", None)
            if callable(purge):
                try:
                    await purge()
                except Exception:  # noqa: BLE001 - leftover searches must not fail the request
                    logger.debug("unable to purge leftover searches on %s", provider.key)

        if not candidates:
            with session_scope() as session:
                log_event(session, request_id, "search", f"{provider.label}: no result")
            return False

        ranked = rank_candidates(candidates, query, quality)
        with session_scope() as session:
            accepted = sum(1 for _, result in ranked if result.accepted)
            log_event(
                session,
                request_id,
                "match",
                f"{provider.label}: {len(candidates)} candidates, {accepted} above the threshold",
                data={"candidates": len(candidates), "accepted": accepted},
            )

        tried = 0
        for candidate, result in ranked:
            if await self._reuse_completed_transfer(request_id, query, release):
                return True
            if tried >= getattr(provider, "max_attempts", MAX_CANDIDATES_PER_PROVIDER):
                break

            if not candidate.files_inspected:
                candidate = await provider.inspect(candidate)
                result = score_candidate(candidate, query, quality)
                candidate.score = result.score

            if not result.accepted:
                with session_scope() as session:
                    record_attempt(
                        session, request_id, provider, candidate, result, decision="rejected"
                    )
                continue

            tried += 1
            with session_scope() as session:
                record_attempt(
                    session, request_id, provider, candidate, result, decision="accepted"
                )
                log_event(
                    session,
                    request_id,
                    "match",
                    f"candidate accepted on {candidate.provider_label} "
                    f"(score {result.score}): {candidate.title}",
                    data=result.details,
                )

            if await self._download_and_import(request_id, provider, candidate, query, release):
                return True

        return False

    async def _download_and_import(
        self,
        request_id: int,
        provider: Provider,
        candidate: Candidate,
        query: AlbumQuery,
        release: dict[str, Any],
    ) -> bool:
        if await self._reuse_completed_transfer(request_id, query, release):
            return True

        # One transfer at a time: drop leftovers a previous candidate left
        # behind (slskd often keeps downloading after a timed-out enqueue).
        await self._abort_other_transfers(request_id, keep_id=None)

        with session_scope() as session:
            set_status(session, request_id, RequestStatus.MATCHED, provider=provider, progress=0.0)

        try:
            handle = await provider.enqueue(candidate)
        except ServiceError as exc:
            with session_scope() as session:
                log_event(
                    session, request_id, "download",
                    f"unable to start the transfer: {exc.message}", level="error",
                )
            return False

        with session_scope() as session:
            download = Download(
                request_id=request_id,
                client=handle.client,
                external_id=handle.external_id,
                username=handle.username,
                state="queued",
                size=candidate.size,
                payload={**handle.payload, "provider_key": provider.key},
            )
            session.add(download)
            session.commit()
            download_id = download.id
            set_status(session, request_id, RequestStatus.DOWNLOADING, provider=provider)
            log_event(
                session, request_id, "download",
                f"transfer started on {candidate.provider_label}",
                data={"client": handle.client, "external_id": handle.external_id},
            )

        status = await self._wait_for_download(request_id, download_id, provider, handle)
        if status is None:
            return False

        content_path = status.content_path
        if not content_path:
            detail = status.message or "the downloaded files could not be located on disk"
            with session_scope() as session:
                log_event(session, request_id, "download", detail, level="error")
            await provider.abort(handle)
            raise PipelineBlocked(detail)

        return await self._verify_and_import(
            request_id, provider, handle, Path(content_path), query, release
        )

    async def _wait_for_download(
        self, request_id: int, download_id: int, provider: Provider, handle: DownloadHandle
    ):
        with session_scope() as session:
            if provider.kind == "soulseek":
                config = settings_service.load(session, "slskd")
            else:
                config = settings_service.load(session, "qbittorrent")
            wait_timeout = timedelta(minutes=config.wait_timeout_minutes)
            stall_timeout = timedelta(minutes=config.stall_timeout_minutes)

        started = datetime.now(UTC)
        last_progress_at = started
        last_downloaded = -1

        while True:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            status = await provider.status(handle)
            now = datetime.now(UTC)

            with session_scope() as session:
                request = session.get(Request, request_id)
                if request is None or request.status == RequestStatus.CANCELLED:
                    await provider.abort(handle)
                    raise PipelineAborted
                download = session.get(Download, download_id)
                if download is not None:
                    download.state = status.state
                    download.progress = status.progress
                    download.size = status.size or download.size
                    download.downloaded = status.downloaded
                    download.speed = status.speed
                    download.eta = status.eta
                    download.content_path = status.content_path
                request.progress = round(status.progress, 2)
                session.commit()

            if status.downloaded > last_downloaded + STALL_TOLERANCE_BYTES:
                last_downloaded = status.downloaded
                last_progress_at = now

            if status.state == "completed":
                with session_scope() as session:
                    log_event(session, request_id, "download", "transfer completed")
                await self._abort_other_transfers(request_id, download_id)
                return status

            if status.state == "failed":
                with session_scope() as session:
                    log_event(
                        session, request_id, "download",
                        f"transfer failed: {status.message or 'unknown reason'}", level="error",
                    )
                await provider.abort(handle)
                return None

            if now - started > wait_timeout:
                with session_scope() as session:
                    log_event(
                        session, request_id, "download",
                        f"giving up after {config.wait_timeout_minutes} minutes", level="error",
                    )
                await provider.abort(handle)
                return None

            if now - last_progress_at > stall_timeout:
                with session_scope() as session:
                    log_event(
                        session, request_id, "download",
                        f"no progress for {config.stall_timeout_minutes} minutes, "
                        "moving to the next candidate",
                        level="error",
                    )
                await provider.abort(handle)
                return None

    async def _verify_and_import(
        self,
        request_id: int,
        provider: Provider,
        handle: DownloadHandle,
        content_path: Path,
        query: AlbumQuery,
        release: dict[str, Any],
    ) -> bool:
        with session_scope() as session:
            quality = settings_service.load(session, "quality")
            naming = settings_service.load(session, "naming")
            coverart_settings = settings_service.load(session, "coverart")
            jellyfin_settings = settings_service.load(session, "jellyfin")
            local_mode = mode_service.is_local(session)
            set_status(session, request_id, RequestStatus.VERIFYING)
            request = session.get(Request, request_id)
            is_upgrade = bool(request.is_upgrade)
            replaces_path = request.replaces_path
            cover_client = clients.coverart(session)
            jellyfin_client = clients.jellyfin(session)

        audio_files = cleanup.collect_audio_files(content_path)
        if not audio_files:
            with session_scope() as session:
                log_event(
                    session, request_id, "verify",
                    f"no audio file found in {content_path}", level="error",
                )
            return False

        verification = await verify.verify_files(
            audio_files, enabled=quality.verify_audio_integrity
        )
        with session_scope() as session:
            if not verification.ok:
                log_event(
                    session, request_id, "verify",
                    f"integrity check failed: {verification.message}", level="error",
                    data={"failures": verification.failures},
                )
            else:
                log_event(
                    session, request_id, "verify",
                    f"{verification.checked} file(s) verified"
                    + (f", {verification.skipped} skipped" if verification.skipped else ""),
                )
        if not verification.ok:
            await provider.abort(handle)
            return False

        cover = await cover_client.get_front_with_fallback(
            query.release_mbid, query.release_group_mbid, size=coverart_settings.preferred_size
        )

        with session_scope() as session:
            set_status(session, request_id, RequestStatus.TAGGING)
            log_event(session, request_id, "tag", "applying MusicBrainz metadata")

        keep_source = provider.kind == "torrent" and _keep_seeding(provider)
        result = await import_album(
            ImportRequest(
                source_path=content_path,
                release=release,
                release_group_mbid=query.release_group_mbid,
                naming=naming,
                coverart=coverart_settings,
                cover=cover,
                keep_source=keep_source,
                is_upgrade=is_upgrade,
                replaces_path=replaces_path,
                confirm_replace=is_upgrade and naming.confirm_upgrade_replace,
            )
        )

        with session_scope() as session:
            set_status(session, request_id, RequestStatus.IMPORTING)
            for warning in result.warnings:
                log_event(session, request_id, "import", warning, level="warning")

        if not result.ok:
            with session_scope() as session:
                log_event(session, request_id, "import", result.error, level="error")
            return False

        await provider.finalize(handle, keep_source=keep_source)

        if local_mode:
            # Nobody else will notice the new folder, and waiting for the
            # periodic walk would keep the album out of the library for hours.
            with session_scope() as session:
                queue.enqueue(session, queue.LIBRARY_SYNC, priority=2)
        elif jellyfin_settings.trigger_scan_on_import and jellyfin_client.api_key:
            try:
                await jellyfin_client.refresh_library()
                with session_scope() as session:
                    log_event(session, request_id, "import", "Jellyfin library scan triggered")
            except ServiceError as exc:
                with session_scope() as session:
                    log_event(
                        session, request_id, "import",
                        f"unable to trigger the Jellyfin scan: {exc.message}", level="warning",
                    )

        with session_scope() as session:
            request = session.get(Request, request_id)
            request.destination_path = result.destination
            request.progress = 100.0
            request.upgrade_review = result.review
            session.commit()
            log_event(
                session, request_id, "import",
                f"{len(result.files)} track(s) imported into {result.destination}",
                data={"files": result.files[:50], "removed": result.removed},
            )
            if result.review:
                set_status(session, request_id, RequestStatus.AWAITING_VALIDATION, error="")
                log_event(
                    session, request_id, "import",
                    f"{len(result.review['remove'])} file(s) of the previous copy are kept "
                    "until someone confirms the new release is the right one",
                    level="warning",
                )
            else:
                set_status(session, request_id, RequestStatus.IMPORTED, error="")
        return True

    # ----------------------------------------------------------------- retry

    async def _fail(self, request_id: int, message: str, *, retry: bool = True) -> None:
        with session_scope() as session:
            general = settings_service.load(session, "general")
            request = session.get(Request, request_id)
            if request is None:
                return
            request.status = RequestStatus.FAILED
            request.error = message
            request.progress = 0.0
            if not retry:
                request.retry_after = None
                session.commit()
                log_event(session, request_id, "failed", message, level="error")
                return
            if request.attempts < general.max_retry_attempts:
                request.retry_after = utcnow() + timedelta(hours=general.retry_failed_after_hours)
                suffix = (
                    f", next attempt in {general.retry_failed_after_hours} h "
                    f"({request.attempts}/{general.max_retry_attempts})"
                )
            else:
                request.retry_after = None
                suffix = ", no attempt left"
            session.commit()
            log_event(session, request_id, "failed", f"{message}{suffix}", level="error")

    async def resume_download(self, request_id: int, download_id: int) -> None:
        """Reattach to a transfer that was running when Muzikk restarted."""
        bundle: ProviderBundle | None = None
        try:
            with session_scope() as session:
                download = session.get(Download, download_id)
                request = session.get(Request, request_id)
                if download is None or request is None:
                    return
                provider_key = (download.payload or {}).get("provider_key")
                bundle = build_providers(session)
                provider = next(
                    (item for item in bundle.providers if item.key == provider_key), None
                )
                handle = DownloadHandle(
                    client=download.client,
                    external_id=download.external_id,
                    username=download.username,
                    payload=download.payload or {},
                )
                log_event(
                    session, request_id, "download",
                    f"resuming the transfer started on {download.client}",
                )

            if provider is None:
                await self._fail(request_id, "the provider used for this transfer is gone")
                return

            with session_scope() as session:
                request = session.get(Request, request_id)
                query, release = await build_query(session, request)

            status = await self._wait_for_download(request_id, download_id, provider, handle)
            if status is None:
                await self._fail(request_id, "the resumed transfer did not complete")
                return
            if not status.content_path:
                await self._fail(
                    request_id,
                    status.message or "the downloaded files could not be located on disk",
                    retry=False,
                )
                return

            if not await self._verify_and_import(
                request_id, provider, handle, Path(status.content_path), query, release
            ):
                await self._fail(request_id, "import failed after resuming the transfer")
        except PipelineAborted:
            return
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unable to resume request %s", request_id)
            await self._fail(request_id, f"internal error while resuming: {exc}")
        finally:
            if bundle is not None:
                await bundle.close()


def _keep_seeding(provider: Provider) -> bool:
    if isinstance(provider, TorrentProvider):
        return bool(provider.qbittorrent.settings.keep_seeding)
    return False


orchestrator = Orchestrator()
