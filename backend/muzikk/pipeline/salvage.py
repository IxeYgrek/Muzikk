"""Reuse an album that is already sitting in a download folder.

A failed import leaves a complete copy behind: a wrong download path, a crash,
a full disk. Fetching the same album again costs hours of somebody else's
bandwidth, so the pipeline looks on disk first and scores what it finds exactly
like a remote candidate — same format rules, same track count, same threshold.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..matching.normalize import is_audio_file
from ..matching.scorer import MatchResult, score_candidate
from ..providers.base import (
    AlbumQuery,
    Candidate,
    CandidateFile,
    DownloadHandle,
    DownloadStatus,
    Provider,
)
from ..services.settings import QualitySettings

logger = logging.getLogger(__name__)

# Folders holding partial data or client bookkeeping, never a finished album.
SKIP_DIRECTORIES = frozenset(
    {"incomplete", ".incomplete", "@eadir", ".stfolder", ".stversions", ".trash-1000"}
)
MAX_DIRECTORIES = 5000


class LocalProvider(Provider):
    """Stand-in for files already on disk.

    The import path expects a provider to abort and finalise transfers, and
    there is nothing to do here. ``kind`` matters though: anything but
    ``torrent`` tells the importer the source folder may be consumed.
    """

    key = "local"
    label = "Download folder"
    kind = "local"
    group = "local"

    async def search(self, query: AlbumQuery) -> list[Candidate]:
        return []

    async def enqueue(self, candidate: Candidate) -> DownloadHandle:
        raise NotImplementedError("the files are already on disk")

    async def status(self, handle: DownloadHandle) -> DownloadStatus:
        return DownloadStatus(state="completed", progress=100.0)


PROVIDER = LocalProvider()
HANDLE = DownloadHandle(client="local", external_id="")


def _directories(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    found = [root]
    for item in root.rglob("*"):
        if len(found) >= MAX_DIRECTORIES:
            logger.warning("Stopped scanning %s after %s folders", root, MAX_DIRECTORIES)
            break
        if not item.is_dir():
            continue
        if any(part.lower() in SKIP_DIRECTORIES for part in item.relative_to(root).parts):
            continue
        found.append(item)
    return found


def _candidate(directory: Path) -> Candidate | None:
    """Describe a folder as if a provider had offered it."""
    try:
        children = sorted(directory.iterdir())
    except OSError:
        return None

    files: list[CandidateFile] = []
    total = 0
    for child in children:
        if not child.is_file() or not is_audio_file(child.name):
            continue
        try:
            size = child.stat().st_size
        except OSError:
            continue
        # An aborted transfer leaves empty shells behind; ignoring them lets
        # the track count catch the incomplete album.
        if size <= 0:
            continue
        files.append(CandidateFile(filename=child.name, size=size))
        total += size

    if not files:
        return None
    return Candidate(
        provider_key=PROVIDER.key,
        provider_label=PROVIDER.label,
        kind=PROVIDER.kind,
        title=directory.name,
        size=total,
        files=files,
        directory=str(directory),
        files_inspected=True,
    )


def find_local_album(
    roots: list[Path], query: AlbumQuery, quality: QualitySettings
) -> tuple[Candidate, MatchResult] | None:
    """Best already-downloaded copy of the album, when one is good enough.

    Walks the filesystem, so call it from a worker thread.
    """
    best: tuple[Candidate, MatchResult] | None = None
    for root in roots:
        for directory in _directories(root):
            candidate = _candidate(directory)
            if candidate is None:
                continue
            result = score_candidate(candidate, query, quality)
            candidate.score = result.score
            if not result.accepted:
                continue
            if best is None or result.score > best[1].score:
                best = (candidate, result)
    return best
