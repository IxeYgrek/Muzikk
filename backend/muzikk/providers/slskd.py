"""Soulseek provider, driven through the slskd REST API."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any, NamedTuple

from ..matching.normalize import basename, is_audio_file, normalize_title
from ..services.base import HttpService, ServiceError, ServiceNotConfigured, normalize_base_url
from ..services.settings import SlskdSettings
from .base import AlbumQuery, Candidate, CandidateFile, DownloadHandle, DownloadStatus, Provider

logger = logging.getLogger(__name__)

SEARCH_POLL_INTERVAL = 1.5
TERMINAL_SEARCH_STATES = ("Completed", "Cancelled", "Errored", "TimedOut")
# One Soulseek wording can return hundreds of folders. Scoring them all is
# how a 1-track request accepted a bootleg that merely shared two common words.
MAX_SEARCH_CANDIDATES = 80

# The 5s wait slskd gives up on is a round trip to the Soulseek server asking
# for the peer address, and that server is regularly slower than that. Waiting
# longer between attempts costs nothing and usually catches a quieter moment.
ENQUEUE_ATTEMPTS = 3
ENQUEUE_RETRY_DELAY = 4.0
# Time given to slskd to show the files it queued while it was answering 500.
ENQUEUE_SETTLE_DELAY = 2.0

# slskd moves each file out of its incomplete folder once the transfer ends, so
# the last tracks can still be in flight when the API already reports success.
LOCATE_ATTEMPTS = 4
LOCATE_DELAY_SECONDS = 2.5


class ContentLookup(NamedTuple):
    """Where the finished transfer landed, or why it could not be found."""

    path: str | None
    problem: str
    worth_retrying: bool = False


def _remote_dir(filename: str) -> str:
    parts = re.split(r"[\\/]", filename)
    return "\\".join(parts[:-1]) if len(parts) > 1 else ""


def _minimum_files(query: AlbumQuery) -> int:
    """How many audio files a folder must hold to be worth looking at.

    Two, normally: a lone track that happens to carry the album name is noise,
    not the album. But a single is one file, and asking two of it means never
    finding one — the release is then dropped before it can even be scored.

    A track request is the other case entirely: one file is exactly what it
    wants, and it may well sit in a folder holding a whole record.
    """
    if query.is_track:
        return 1
    return 1 if 0 < query.track_count < 2 else 2


class SlskdProvider(Provider):
    key = "slskd"
    label = "Soulseek (slskd)"
    kind = "soulseek"
    group = "slskd"
    max_attempts = 12

    def __init__(self, settings: SlskdSettings) -> None:
        self.settings = settings
        self.http = HttpService(
            normalize_base_url(settings.url, settings.url_base),
            headers={"X-API-Key": settings.api_key, "Accept": "application/json"},
        )
        self.http.service_name = "slskd"

    @property
    def enabled(self) -> bool:
        return bool(self.settings.enabled and self.settings.url and self.settings.api_key)

    def _api(self, path: str) -> str:
        return f"/api/v0{path}"

    # -------------------------------------------------------------- search

    async def _run_search(self, text: str, minimum_files: int = 2) -> list[dict[str, Any]]:
        search_id = str(uuid.uuid4())
        payload = {
            "id": search_id,
            "searchText": text,
            # slskd interprets this value as milliseconds.
            "searchTimeout": self.settings.search_timeout_ms,
            "responseLimit": self.settings.response_limit,
            "filterResponses": True,
            "minimumPeerUploadSpeed": self.settings.min_peer_upload_speed,
            "maximumPeerQueueLength": self.settings.max_peer_queue_length,
            "minimumResponseFileCount": minimum_files,
        }
        try:
            await self.http.request("POST", self._api("/searches"), json=payload)

            deadline = self.settings.search_timeout_ms / 1000 + 20
            waited = 0.0
            while waited < deadline:
                await asyncio.sleep(SEARCH_POLL_INTERVAL)
                waited += SEARCH_POLL_INTERVAL
                state = await self.http.request("GET", self._api(f"/searches/{search_id}"))
                current = (state or {}).get("state") or ""
                if any(marker in current for marker in TERMINAL_SEARCH_STATES):
                    break

            responses = await self.http.request(
                "GET", self._api(f"/searches/{search_id}/responses")
            )
            return responses or []
        finally:
            try:
                await self.http.request(
                    "DELETE", self._api(f"/searches/{search_id}"), expect_json=False
                )
            except ServiceError:
                pass

    async def purge_searches(self) -> None:
        """Drop leftover slskd searches, including ones whose id we never saw.

        A poll that fails, or a search slskd registered under another id, would
        otherwise sit in its list until someone cleaned it by hand.
        """
        try:
            searches = await self.http.request("GET", self._api("/searches"))
        except ServiceError:
            return
        if isinstance(searches, dict):
            searches = searches.get("searches") or searches.get("items") or []
        if not isinstance(searches, list):
            return
        for item in searches:
            if not isinstance(item, dict):
                continue
            search_id = item.get("id")
            if not search_id:
                continue
            try:
                await self.http.request(
                    "DELETE", self._api(f"/searches/{search_id}"), expect_json=False
                )
            except ServiceError:
                continue

    async def search(self, query: AlbumQuery) -> list[Candidate]:
        if not self.enabled:
            raise ServiceNotConfigured("slskd")

        seen_directories: set[tuple[str, str]] = set()
        candidates: list[Candidate] = []
        minimum_files = _minimum_files(query)

        try:
            for term in query.search_terms():
                try:
                    responses = await self._run_search(term, minimum_files)
                except ServiceError as exc:
                    logger.warning("slskd search failed for %r: %s", term, exc.message)
                    continue

                for response in responses:
                    username = response.get("username")
                    if not username:
                        continue

                    if query.is_track:
                        # One candidate per file, not per folder: the folder may
                        # hold a whole record and only one file is wanted.
                        for entry in response.get("files") or []:
                            filename = entry.get("filename") or ""
                            if not filename or not is_audio_file(filename):
                                continue
                            marker = (username, filename)
                            if marker in seen_directories:
                                continue
                            seen_directories.add(marker)
                            item = CandidateFile(
                                filename=filename,
                                size=int(entry.get("size") or 0),
                                length_seconds=entry.get("length"),
                                bitrate=entry.get("bitRate"),
                                bit_depth=entry.get("bitDepth"),
                                sample_rate=entry.get("sampleRate"),
                            )
                            candidates.append(
                                Candidate(
                                    provider_key=self.key,
                                    provider_label=self.label,
                                    kind=self.kind,
                                    title=basename(filename) or filename,
                                    directory=_remote_dir(filename),
                                    username=username,
                                    size=item.size,
                                    files=[item],
                                    files_inspected=True,
                                    upload_speed=response.get("uploadSpeed"),
                                    queue_length=response.get("queueLength"),
                                    extra={
                                        "has_free_upload_slot": response.get("hasFreeUploadSlot"),
                                        "search_term": term,
                                    },
                                )
                            )
                            if len(candidates) >= MAX_SEARCH_CANDIDATES:
                                return candidates
                        continue

                    grouped: dict[str, list[dict[str, Any]]] = {}
                    for entry in response.get("files") or []:
                        filename = entry.get("filename") or ""
                        if not filename:
                            continue
                        grouped.setdefault(_remote_dir(filename), []).append(entry)

                    for directory, entries in grouped.items():
                        marker = (username, directory)
                        if marker in seen_directories:
                            continue
                        audio = [item for item in entries if is_audio_file(item.get("filename") or "")]
                        if len(audio) < minimum_files:
                            continue
                        seen_directories.add(marker)
                        files = [
                            CandidateFile(
                                filename=item.get("filename") or "",
                                size=int(item.get("size") or 0),
                                length_seconds=item.get("length"),
                                bitrate=item.get("bitRate"),
                                bit_depth=item.get("bitDepth"),
                                sample_rate=item.get("sampleRate"),
                            )
                            for item in entries
                        ]
                        candidates.append(
                            Candidate(
                                provider_key=self.key,
                                provider_label=self.label,
                                kind=self.kind,
                                title=basename(directory) or directory,
                                directory=directory,
                                username=username,
                                size=sum(item.size for item in files),
                                files=files,
                                files_inspected=True,
                                upload_speed=response.get("uploadSpeed"),
                                queue_length=response.get("queueLength"),
                                extra={
                                    "has_free_upload_slot": response.get("hasFreeUploadSlot"),
                                    "search_term": term,
                                },
                            )
                        )
                        if len(candidates) >= MAX_SEARCH_CANDIDATES:
                            return candidates

                if len(candidates) >= MAX_SEARCH_CANDIDATES:
                    break
        finally:
            await self.purge_searches()

        return candidates

    # ------------------------------------------------------------ transfers

    async def enqueue(self, candidate: Candidate) -> DownloadHandle:
        if not candidate.username:
            raise ServiceError("slskd", "candidate has no peer username")

        wanted = [
            item
            for item in candidate.files
            if item.is_audio or item.extension in ("jpg", "jpeg", "png")
        ]
        body = [{"filename": item.filename, "size": item.size} for item in wanted]
        handle = DownloadHandle(
            client="slskd",
            external_id=candidate.directory or candidate.title,
            username=candidate.username,
            payload={
                "filenames": [item.filename for item in wanted],
                "directory": candidate.directory,
                "expected_audio": [
                    basename(item.filename) for item in wanted if item.is_audio
                ],
                "total_size": sum(item.size for item in wanted),
            },
        )
        for attempt in range(ENQUEUE_ATTEMPTS):
            try:
                await self.http.request(
                    "POST",
                    self._api(f"/transfers/downloads/{candidate.username}"),
                    json=body,
                    expect_json=False,
                )
                return handle
            except ServiceError as exc:
                timeout = exc.status_code == 500 and "timed out" in (exc.message or "").lower()
                if timeout and await self._queued_anyway(handle):
                    logger.info(
                        "slskd timed out enqueueing for %s but the files are queued",
                        candidate.username,
                    )
                    return handle
                if not timeout or attempt + 1 >= ENQUEUE_ATTEMPTS:
                    # slskd often queues the files anyway, then answers 500.
                    await self.abort(handle)
                    raise
                logger.info(
                    "slskd enqueue timed out for %s (attempt %s/%s), retrying",
                    candidate.username,
                    attempt + 1,
                    ENQUEUE_ATTEMPTS,
                )
                await asyncio.sleep(ENQUEUE_RETRY_DELAY * (attempt + 1))
        raise ServiceError("slskd", "unable to start the transfer")

    async def _queued_anyway(self, handle: DownloadHandle) -> bool:
        """Whether the files are queued even though slskd answered a timeout.

        slskd gives up on the peer address lookup before it gives up on the
        queue request itself, so a 500 does not mean nothing happened. Asking
        again for a transfer that is already running would only duplicate it.
        """
        if not handle.username:
            return False
        await asyncio.sleep(ENQUEUE_SETTLE_DELAY)
        try:
            transfers = await self._transfers(handle.username)
        except ServiceError:
            return False

        wanted = set(handle.payload.get("filenames") or [])
        for item in transfers:
            if item.get("filename") not in wanted:
                continue
            state = str(item.get("state") or "")
            # A leftover from an earlier attempt is not a live transfer.
            if any(dead in state for dead in ("Errored", "Rejected", "Cancelled")):
                continue
            return True
        return False

    async def _transfers(self, username: str) -> list[dict[str, Any]]:
        payload = await self.http.request("GET", self._api(f"/transfers/downloads/{username}"))
        files: list[dict[str, Any]] = []
        for directory in (payload or {}).get("directories") or []:
            files.extend(directory.get("files") or [])
        return files

    async def status(self, handle: DownloadHandle) -> DownloadStatus:
        if not handle.username:
            return DownloadStatus(state="failed", message="missing peer username")

        wanted = set(handle.payload.get("filenames") or [])
        try:
            transfers = await self._transfers(handle.username)
        except ServiceError as exc:
            return DownloadStatus(state="downloading", message=exc.message)

        ours = [item for item in transfers if item.get("filename") in wanted]
        if not ours:
            return DownloadStatus(state="queued", message="waiting for the peer queue")

        total = sum(int(item.get("size") or 0) for item in ours)
        done = sum(int(item.get("bytesTransferred") or 0) for item in ours)
        speed = int(sum(float(item.get("averageSpeed") or 0) for item in ours))
        states = [str(item.get("state") or "") for item in ours]

        errored = [state for state in states if "Errored" in state or "Rejected" in state]
        cancelled = [state for state in states if "Cancelled" in state]
        succeeded = [state for state in states if "Succeeded" in state]

        if len(succeeded) == len(ours):
            lookup = await self._await_content(handle)
            return DownloadStatus(
                state="completed",
                progress=100.0,
                size=total,
                downloaded=done,
                content_path=lookup.path,
                message=lookup.problem,
            )

        if errored and len(errored) + len(succeeded) == len(ours):
            return DownloadStatus(
                state="failed",
                progress=(done / total * 100) if total else 0.0,
                size=total,
                downloaded=done,
                message=f"peer refused or aborted the transfer ({errored[0]})",
            )
        if cancelled and len(cancelled) + len(succeeded) == len(ours):
            return DownloadStatus(state="failed", message="transfer cancelled")

        progress = (done / total * 100) if total else 0.0
        active = any("InProgress" in state for state in states)
        return DownloadStatus(
            state="downloading" if active else "queued",
            progress=progress,
            size=total,
            downloaded=done,
            speed=speed,
            message="" if active else "queued on the peer",
        )

    async def _await_content(self, handle: DownloadHandle) -> ContentLookup:
        """Locate the files, tolerating slskd still moving the last ones."""
        lookup = self._locate_content(handle)
        attempts = 1
        while lookup.path is None and lookup.worth_retrying and attempts < LOCATE_ATTEMPTS:
            await asyncio.sleep(LOCATE_DELAY_SECONDS)
            lookup = self._locate_content(handle)
            attempts += 1
        if lookup.path is None:
            logger.warning("slskd transfer finished but %s", lookup.problem)
        return lookup

    def _locate_content(self, handle: DownloadHandle) -> ContentLookup:
        """Find where slskd actually wrote the files.

        slskd sanitises names and its folder layout changed across versions, so
        the directory holding the most expected tracks wins.
        """
        root = Path(self.settings.downloads_dir)
        if not root.is_dir():
            return ContentLookup(
                None,
                f'the slskd download folder "{root}" does not exist inside the Muzikk '
                "container. Set it in Administration > slskd to the path where Muzikk sees "
                "the folder slskd downloads into, and mount that volume in both containers.",
            )

        expected = {
            normalize_title(Path(name).stem)
            for name in handle.payload.get("expected_audio") or []
            if name
        }
        if not expected:
            return ContentLookup(None, "the candidate carried no audio file to look for")

        best_path: Path | None = None
        best_hits = 0
        directories = [root]
        directories.extend(item for item in root.rglob("*") if item.is_dir())
        for directory in directories:
            hits = 0
            try:
                children = list(directory.iterdir())
            except OSError:
                continue
            for child in children:
                if child.is_file() and is_audio_file(child.name):
                    if normalize_title(child.stem) in expected:
                        hits += 1
            if hits > best_hits:
                best_hits = hits
                best_path = directory

        if best_path is None or best_hits == 0:
            return ContentLookup(
                None,
                f"none of the {len(expected)} downloaded track(s) could be found under "
                f'"{root}". Check that this folder is the one slskd writes into, and that '
                "Muzikk can read it (PUID/PGID).",
                worth_retrying=True,
            )
        return ContentLookup(str(best_path), "")

    async def abort(self, handle: DownloadHandle) -> None:
        if not handle.username:
            return
        try:
            transfers = await self._transfers(handle.username)
        except ServiceError:
            return
        wanted = set(handle.payload.get("filenames") or [])
        for item in transfers:
            if item.get("filename") in wanted and item.get("id"):
                try:
                    await self.http.request(
                        "DELETE",
                        self._api(f"/transfers/downloads/{handle.username}/{item['id']}"),
                        params={"remove": "true"},
                        expect_json=False,
                    )
                except ServiceError:
                    continue

    async def finalize(self, handle: DownloadHandle, *, keep_source: bool) -> None:
        if not self.settings.remove_completed or not handle.username:
            return
        try:
            transfers = await self._transfers(handle.username)
        except ServiceError:
            return
        wanted = set(handle.payload.get("filenames") or [])
        for item in transfers:
            if item.get("filename") in wanted and item.get("id") and "Completed" in str(item.get("state")):
                try:
                    await self.http.request(
                        "DELETE",
                        self._api(f"/transfers/downloads/{handle.username}/{item['id']}"),
                        params={"remove": "true"},
                        expect_json=False,
                    )
                except ServiceError:
                    continue

    async def test_connection(self) -> dict[str, Any]:
        state = await self.http.request("GET", self._api("/application"))
        server = (state or {}).get("server") or {}
        # A wrong download folder only shows up once an album has been fetched
        # for nothing, so the test checks it upfront.
        root = Path(self.settings.downloads_dir)
        return {
            "version": (state or {}).get("version"),
            "connected": bool(server.get("isConnected")),
            "logged_in": bool(server.get("isLoggedIn")),
            "username": server.get("username"),
            "downloads_dir": str(root),
            "downloads_dir_readable": root.is_dir() and os.access(root, os.R_OK),
        }
