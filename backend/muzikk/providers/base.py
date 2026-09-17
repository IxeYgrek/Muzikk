"""Provider contract.

Every acquisition source implements the same three steps: search for
candidates, enqueue the accepted one, then report progress until the files are
on disk. The orchestrator does not know anything else about them.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ..matching.normalize import extension_of, is_audio_file, normalize_artist, normalize_title

VARIOUS_ARTISTS = ("various artists", "various", "va", "verschiedene", "diverse")

# The kind of release, which catalogues write into the title and peers leave out
# of their folder names.
_RELEASE_TYPE_RE = re.compile(r"\b(ep|lp|single|mixtape)\b", re.IGNORECASE)
_EMPTY_BRACKETS_RE = re.compile(r"[\(\[\{]\s*[\)\]\}]")
_EDGE_PUNCT_RE = re.compile(r"^[\s\-–—_,.:;/&+]+|[\s\-–—_,.:;/&+]+$")


def _without_release_type(album: str) -> str:
    """The album title as a peer would have written it on disk.

    MusicBrainz names a release group "Pharaoh EP" where the folder shared on
    Soulseek is simply "Eekoz - Pharaoh". Soulseek only answers when every word
    of the query is somewhere in the path, so keeping that "EP" hides the
    release altogether. A title made of nothing else is left alone: a few
    records really are called "EP".
    """
    without = _EMPTY_BRACKETS_RE.sub(" ", _RELEASE_TYPE_RE.sub(" ", album))
    return _EDGE_PUNCT_RE.sub("", " ".join(without.split())) or album


@dataclass(slots=True)
class AlbumQuery:
    """Everything MusicBrainz knows about the album we want."""

    release_group_mbid: str
    album: str
    artist: str
    release_mbid: str | None = None
    artist_mbid: str | None = None
    year: int | None = None
    track_count: int = 0
    disc_count: int = 1
    track_titles: list[str] = field(default_factory=list)
    track_durations_ms: list[int] = field(default_factory=list)
    track_artists: list[str] = field(default_factory=list)

    @property
    def is_various(self) -> bool:
        return normalize_artist(self.artist) in {normalize_artist(name) for name in VARIOUS_ARTISTS}

    @property
    def total_duration_ms(self) -> int:
        return sum(duration for duration in self.track_durations_ms if duration)

    @property
    def normalized_artist(self) -> str:
        return normalize_artist(self.artist)

    @property
    def normalized_album(self) -> str:
        return normalize_title(self.album)

    def search_terms(self) -> list[str]:
        """Query strings to try, from the most to the least specific.

        Every variant drops something the peer may not have written: the kind of
        release first, then the edition noise. The album on its own comes last
        on purpose — it is the one term that brings back hundreds of unrelated
        folders, and asking it early filled the candidate list before the terms
        naming the artist ever got their turn.
        """
        album = self.album.strip()
        artist = self.artist.strip()
        credited = artist if artist and not self.is_various else ""
        terms: list[str] = []

        def add(*parts: str) -> None:
            cleaned = " ".join(" ".join(parts).split())
            if cleaned and cleaned.lower() not in {item.lower() for item in terms}:
                terms.append(cleaned)

        plain_album = _without_release_type(album)
        # Titles carrying edition noise rarely appear verbatim in shares.
        simplified_album = normalize_title(album)
        simplified_artist = normalize_artist(artist)

        add(credited, album)
        add(credited, plain_album)
        if simplified_album and simplified_album != album.lower():
            add(credited, simplified_album)
        if simplified_artist and simplified_album:
            add(simplified_artist, simplified_album)
        add(album)
        add(plain_album)
        return terms[:4]


@dataclass(slots=True)
class CandidateFile:
    filename: str
    size: int = 0
    length_seconds: int | None = None
    bitrate: int | None = None
    bit_depth: int | None = None
    sample_rate: int | None = None

    @property
    def extension(self) -> str:
        return extension_of(self.filename)

    @property
    def is_audio(self) -> bool:
        return is_audio_file(self.filename)


@dataclass(slots=True)
class Candidate:
    """A possible source for the requested album."""

    provider_key: str
    provider_label: str
    kind: str  # "soulseek" or "torrent"
    title: str
    size: int = 0
    files: list[CandidateFile] = field(default_factory=list)
    seeders: int | None = None
    leechers: int | None = None
    username: str | None = None
    directory: str | None = None
    download_url: str | None = None
    magnet_url: str | None = None
    info_hash: str | None = None
    indexer_id: int | None = None
    indexer_privacy: str = "public"
    upload_speed: int | None = None
    queue_length: int | None = None
    files_inspected: bool = False
    publish_date: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    # Filled by the scorer.
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)

    @property
    def audio_files(self) -> list[CandidateFile]:
        return [item for item in self.files if item.is_audio]

    @property
    def extensions(self) -> set[str]:
        return {item.extension for item in self.audio_files}


@dataclass(slots=True)
class DownloadHandle:
    client: str
    external_id: str
    username: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DownloadStatus:
    state: str  # queued, downloading, completed, failed, stalled
    progress: float = 0.0
    size: int = 0
    downloaded: int = 0
    speed: int = 0
    eta: int | None = None
    content_path: str | None = None
    message: str = ""

    @property
    def finished(self) -> bool:
        return self.state in ("completed", "failed")


class Provider(ABC):
    """Base class for an acquisition source."""

    key: str = "provider"
    label: str = "Provider"
    kind: str = "torrent"
    group: str = "torrent_public"
    # How many accepted candidates the orchestrator will actually enqueue
    # before giving this source up. Soulseek overrides it: many peers answer
    # the search and then refuse the transfer, so six tries is not enough.
    max_attempts: int = 6

    @property
    def enabled(self) -> bool:
        return True

    @abstractmethod
    async def search(self, query: AlbumQuery) -> list[Candidate]:
        """Return every plausible candidate, unscored."""

    @abstractmethod
    async def enqueue(self, candidate: Candidate) -> DownloadHandle:
        """Start the transfer and return a handle for polling."""

    @abstractmethod
    async def status(self, handle: DownloadHandle) -> DownloadStatus:
        """Report the current transfer state."""

    async def inspect(self, candidate: Candidate) -> Candidate:
        """Optionally fill ``candidate.files`` before scoring."""
        return candidate

    async def abort(self, handle: DownloadHandle) -> None:
        """Cancel a transfer that timed out or is being replaced."""
        return None

    async def finalize(self, handle: DownloadHandle, *, keep_source: bool) -> None:
        """Called after a successful import."""
        return None
