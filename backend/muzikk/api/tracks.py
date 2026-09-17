"""Track level search.

Downloads always happen at album level, but people remember songs. Finding the
album that holds a given track is therefore a search entry point of its own,
looking both at the library and at MusicBrainz.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..matching.normalize import fuzzy_key
from ..models import LibraryAlbum
from ..schemas import TrackSearchResponse, TrackSearchResult
from ..services import catalog, clients
from ..services.base import ServiceError
from .deps import CurrentUser, SessionDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tracks", tags=["tracks"])


def _library_results(
    session: Session, items: list[dict[str, Any]]
) -> list[TrackSearchResult]:
    albums = {
        row.jellyfin_id: row
        for row in session.execute(select(LibraryAlbum)).scalars()
    }
    results: list[TrackSearchResult] = []

    for item in items:
        if not item.get("Id"):
            continue
        album = albums.get(item.get("AlbumId") or "")
        ticks = item.get("RunTimeTicks") or 0
        artists = item.get("Artists") or []
        results.append(
            TrackSearchResult(
                title=item.get("Name") or "",
                artist=(artists[0] if artists else "") or item.get("AlbumArtist") or "",
                album=item.get("Album") or (album.name if album else ""),
                year=album.year if album else None,
                duration=round(ticks / 10_000_000, 3) if ticks else None,
                owned=True,
                jellyfin_id=item.get("Id"),
                album_jellyfin_id=item.get("AlbumId"),
                release_group_mbid=album.release_group_mbid if album else None,
                cover_url=catalog.cover_url(
                    album.release_group_mbid if album else None,
                    album.release_mbid if album else None,
                    item.get("AlbumId"),
                ),
            )
        )
    return results


def _owned_keys(session: Session) -> tuple[set[str], set[str]]:
    rows = session.execute(
        select(LibraryAlbum.release_group_mbid, LibraryAlbum.fuzzy_key)
    ).all()
    return (
        {row.release_group_mbid for row in rows if row.release_group_mbid},
        {row.fuzzy_key for row in rows if row.fuzzy_key},
    )


def _musicbrainz_results(
    session: Session, recordings: list[dict[str, Any]], *, limit: int
) -> list[TrackSearchResult]:
    """One result per (recording, release group), best releases first."""
    owned_groups, owned_keys = _owned_keys(session)
    results: list[TrackSearchResult] = []
    seen: set[tuple[str, str]] = set()

    for recording in recordings:
        credits = recording.get("artist-credit") or []
        artist = (credits[0].get("name") if credits else "") or ""
        length = recording.get("length")

        for release in recording.get("releases") or []:
            group = release.get("release-group") or {}
            group_mbid = group.get("id")
            if not group_mbid:
                continue
            # A song appears on the album, the single, three compilations and a
            # live record: keep the studio albums in front.
            key = (recording.get("id") or "", group_mbid)
            if key in seen:
                continue
            seen.add(key)

            date = release.get("date") or group.get("first-release-date") or ""
            title = group.get("title") or release.get("title") or ""
            owned = group_mbid in owned_groups or fuzzy_key(artist, title) in owned_keys
            results.append(
                TrackSearchResult(
                    title=recording.get("title") or "",
                    artist=artist,
                    album=title,
                    year=int(date[:4]) if date[:4].isdigit() else None,
                    duration=round(length / 1000, 3) if length else None,
                    owned=owned,
                    release_group_mbid=group_mbid,
                    recording_mbid=recording.get("id"),
                    cover_url=catalog.cover_url(group_mbid, release.get("id")),
                )
            )

    def rank(item: TrackSearchResult) -> tuple[int, int]:
        primary = 0 if item.owned else 1
        return (primary, item.year or 9999)

    results.sort(key=rank)
    return results[:limit]


@router.get("/search", response_model=TrackSearchResponse)
async def search_tracks(
    session: SessionDep,
    user: CurrentUser,
    q: str = Query(default="", max_length=300),
    scope: str = Query(default="all", pattern="^(all|library|musicbrainz)$"),
    limit: int = Query(default=40, ge=1, le=100),
) -> TrackSearchResponse:
    """Search tracks in the library, in MusicBrainz, or in both."""
    query = q.strip()
    if not query:
        return TrackSearchResponse(count=0, items=[])

    results: list[TrackSearchResult] = []
    errors: list[str] = []

    if scope in ("all", "library"):
        jellyfin = clients.jellyfin(session)
        if jellyfin.configured and jellyfin.api_key:
            try:
                items = await jellyfin.search_audio(query, limit=limit)
                results.extend(_library_results(session, items))
            except ServiceError as exc:
                errors.append(f"Jellyfin: {exc.message}")

    if scope in ("all", "musicbrainz"):
        client = clients.musicbrainz(session)
        if client.configured:
            try:
                payload = await client.search_recordings(query, limit=limit)
                results.extend(
                    _musicbrainz_results(
                        session, (payload or {}).get("recordings") or [], limit=limit
                    )
                )
            except ServiceError as exc:
                errors.append(f"MusicBrainz: {exc.message}")

    if not results and errors:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="; ".join(errors)
        )
    return TrackSearchResponse(count=len(results), items=results[: limit * 2])


@router.get("/library/{album_id}", response_model=TrackSearchResponse)
async def album_tracks(
    album_id: str, session: SessionDep, user: CurrentUser
) -> TrackSearchResponse:
    """Track list of an album we own, read from Jellyfin."""
    jellyfin = clients.jellyfin(session)
    if not jellyfin.configured or not jellyfin.api_key:
        raise HTTPException(status_code=400, detail="Jellyfin is not configured")
    try:
        items = await asyncio.wait_for(jellyfin.get_album_tracks(album_id), timeout=30)
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Jellyfin took too long") from exc
    except ServiceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message) from exc

    results = _library_results(session, items)
    results.sort(key=lambda item: item.title.lower())
    return TrackSearchResponse(count=len(results), items=results)
