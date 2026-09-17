"""Thirty second previews of the tracks the library does not hold.

Deezer answers first: its public search needs no key and hands back an MP3 any
browser decodes. iTunes is the fallback, with an AAC file. ListenBrainz is not
in the list on purpose — it catalogues listens, it hosts no audio.

Both services answer whatever their search engine feels like, karaoke covers
and tribute bands included, so every hit is scored against the artist and the
title asked for and anything unconvincing is dropped.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx
from rapidfuzz import fuzz

from ..matching.normalize import normalize_artist, normalize_title
from .base import DEFAULT_TIMEOUT, ServiceError

logger = logging.getLogger(__name__)

DEEZER_SEARCH = "https://api.deezer.com/search"
ITUNES_SEARCH = "https://itunes.apple.com/search"

# Both services hand out extracts of this length.
PREVIEW_SECONDS = 30.0
# Out of 100, mixing the title and the artist similarity.
MATCH_THRESHOLD = 70.0
# A karaoke version or a tribute band answers the title perfectly, and
# `token_set_ratio` forgives the extra words, so the artist decides alone
# whether a hit is even worth scoring.
MIN_ARTIST_SCORE = 55.0
RESULT_LIMIT = 10
# A preview URL is signed and short lived, so the answer is only worth keeping
# for the few minutes a reader spends going through a tracklist.
CACHE_TTL_SECONDS = 600
CACHE_MAX_ENTRIES = 500

# Hosts the stream proxy is allowed to fetch. The URL never comes from the
# caller, but it does come from the outside, and a redirect elsewhere is not
# something this server has any reason to follow.
ALLOWED_HOSTS = (
    "dzcdn.net",
    "deezer.com",
    "mzstatic.com",
    "apple.com",
)


@dataclass(slots=True)
class Preview:
    """One playable extract, already judged to be the right track."""

    source: str
    url: str
    title: str
    artist: str
    album: str
    cover_url: str | None
    score: float
    content_type: str


_cache: dict[str, tuple[float, Preview | None]] = {}


def cache_key(artist: str | None, title: str | None, album: str | None = None) -> str:
    return "|".join(
        (normalize_artist(artist), normalize_title(title), normalize_title(album))
    )


def _cached(key: str) -> tuple[bool, Preview | None]:
    entry = _cache.get(key)
    if entry is None:
        return False, None
    stored_at, preview = entry
    if time.monotonic() - stored_at > CACHE_TTL_SECONDS:
        _cache.pop(key, None)
        return False, None
    return True, preview


def _remember(key: str, preview: Preview | None) -> None:
    if len(_cache) >= CACHE_MAX_ENTRIES:
        oldest = min(_cache, key=lambda item: _cache[item][0])
        _cache.pop(oldest, None)
    _cache[key] = (time.monotonic(), preview)


def host_allowed(url: str) -> bool:
    host = httpx.URL(url).host.lower()
    return any(host == allowed or host.endswith(f".{allowed}") for allowed in ALLOWED_HOSTS)


def score_hit(
    *, wanted_artist: str, wanted_title: str, artist: str, title: str
) -> float:
    """How much a search hit looks like the track that was asked for.

    The title then carries more weight than the artist: a featuring credit
    written one way here and another way there must not sink an otherwise
    exact match.
    """
    title_score = fuzz.token_set_ratio(normalize_title(wanted_title), normalize_title(title))
    if not normalize_artist(wanted_artist):
        return float(title_score)

    artist_score = fuzz.token_set_ratio(normalize_artist(wanted_artist), normalize_artist(artist))
    if artist_score < MIN_ARTIST_SCORE:
        return 0.0
    return 0.6 * title_score + 0.4 * artist_score


async def _search(client: httpx.AsyncClient, url: str, params: dict[str, Any]) -> Any:
    try:
        response = await client.get(url, params=params)
    except httpx.HTTPError as exc:
        raise ServiceError("previews", f"unreachable ({exc.__class__.__name__})") from exc
    if response.status_code >= 400:
        raise ServiceError("previews", f"HTTP {response.status_code}", response.status_code)
    try:
        return response.json()
    except ValueError as exc:
        raise ServiceError("previews", "invalid JSON response") from exc


def _best(
    hits: list[Preview], *, artist: str, title: str
) -> Preview | None:
    best = max(hits, key=lambda hit: hit.score, default=None)
    if best is None:
        return None
    if best.score < MATCH_THRESHOLD:
        logger.debug(
            "No convincing preview for %s - %s (best %.0f from %s)",
            artist,
            title,
            best.score,
            best.source,
        )
        return None
    return best


async def _deezer(
    client: httpx.AsyncClient, artist: str, title: str
) -> Preview | None:
    payload = await _search(
        client, DEEZER_SEARCH, {"q": f"{artist} {title}".strip(), "limit": RESULT_LIMIT}
    )
    hits: list[Preview] = []
    for item in (payload or {}).get("data") or []:
        url = item.get("preview") or ""
        if not url:
            continue
        found_artist = (item.get("artist") or {}).get("name") or ""
        album = item.get("album") or {}
        hits.append(
            Preview(
                source="deezer",
                url=url,
                title=item.get("title") or "",
                artist=found_artist,
                album=album.get("title") or "",
                cover_url=album.get("cover_medium") or album.get("cover") or None,
                score=score_hit(
                    wanted_artist=artist,
                    wanted_title=title,
                    artist=found_artist,
                    title=item.get("title") or "",
                ),
                content_type="audio/mpeg",
            )
        )
    return _best(hits, artist=artist, title=title)


async def _itunes(
    client: httpx.AsyncClient, artist: str, title: str, *, country: str
) -> Preview | None:
    payload = await _search(
        client,
        ITUNES_SEARCH,
        {
            "term": f"{artist} {title}".strip(),
            "media": "music",
            "entity": "song",
            "limit": RESULT_LIMIT,
            "country": country,
        },
    )
    hits: list[Preview] = []
    for item in (payload or {}).get("results") or []:
        url = item.get("previewUrl") or ""
        if not url:
            continue
        found_artist = item.get("artistName") or ""
        found_title = item.get("trackName") or ""
        hits.append(
            Preview(
                source="itunes",
                url=url,
                title=found_title,
                artist=found_artist,
                album=item.get("collectionName") or "",
                cover_url=item.get("artworkUrl100") or None,
                score=score_hit(
                    wanted_artist=artist,
                    wanted_title=title,
                    artist=found_artist,
                    title=found_title,
                ),
                content_type="audio/mp4",
            )
        )
    return _best(hits, artist=artist, title=title)


async def find(
    artist: str, title: str, *, album: str | None = None, country: str = "FR"
) -> Preview | None:
    """The best extract for one track, Deezer first then iTunes.

    A miss is remembered like a hit: a tracklist nobody has an extract for
    would otherwise ask both services again on every redraw.
    """
    if not title.strip():
        return None

    key = cache_key(artist, title, album)
    known, cached = _cached(key)
    if known:
        return cached

    preview: Preview | None = None
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, follow_redirects=True) as client:
        for lookup in (
            lambda: _deezer(client, artist, title),
            lambda: _itunes(client, artist, title, country=country),
        ):
            try:
                preview = await lookup()
            except ServiceError as exc:
                # One service being down is not a reason to skip the other.
                logger.info("Preview lookup failed: %s", exc.message)
                continue
            if preview is not None:
                break

    _remember(key, preview)
    return preview


def forget_all() -> None:
    """Drop the cache, so a test never reads what another one left behind."""
    _cache.clear()
