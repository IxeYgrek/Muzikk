"""Discovery: new releases, genres and albums missing from the library."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from ..models import LibraryArtist
from ..schemas import AlbumCard, SearchResponse
from ..services import catalog, clients
from ..services.base import ServiceError
from .deps import CurrentUser, SessionDep

router = APIRouter(prefix="/discover", tags=["discover"])

FALLBACK_GENRES = [
    "rock", "pop", "electronic", "hip hop", "jazz", "metal", "classical",
    "folk", "soul", "funk", "punk", "reggae", "blues", "ambient",
    "techno", "house", "indie rock", "rap", "disco", "country",
]


@router.get("/new-releases", response_model=SearchResponse)
async def new_releases(
    session: SessionDep,
    user: CurrentUser,
    months: int = Query(default=3, ge=1, le=24),
    primary_type: str = Query(default="album"),
    limit: int = Query(default=40, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> SearchResponse:
    client = clients.musicbrainz(session)
    end = datetime.now(UTC).date()
    start = end - timedelta(days=months * 31)
    try:
        payload = await client.search_recent_release_groups(
            start=start.isoformat(),
            end=end.isoformat(),
            limit=limit,
            offset=offset,
            primary_type=primary_type,
        )
    except ServiceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message) from exc

    groups = (payload or {}).get("release-groups") or []
    groups.sort(key=lambda item: item.get("first-release-date") or "", reverse=True)
    return SearchResponse(
        count=(payload or {}).get("count") or len(groups),
        offset=offset,
        items=await catalog.hydrate_and_build(session, client, groups),
    )


@router.get("/genres")
async def genres(session: SessionDep, user: CurrentUser) -> list[str]:
    from ..models import LibraryAlbum

    counter: dict[str, int] = {}
    for values in session.execute(select(LibraryAlbum.genres)).scalars():
        for genre in values or []:
            key = genre.strip().lower()
            if key:
                counter[key] = counter.get(key, 0) + 1

    ranked = [name for name, _ in sorted(counter.items(), key=lambda item: (-item[1], item[0]))]
    for genre in FALLBACK_GENRES:
        if genre not in ranked:
            ranked.append(genre)
    return ranked[:40]


@router.get("/genre/{tag}", response_model=SearchResponse)
async def by_genre(
    tag: str,
    session: SessionDep,
    user: CurrentUser,
    primary_type: str = Query(default="album"),
    limit: int = Query(default=40, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> SearchResponse:
    client = clients.musicbrainz(session)
    try:
        payload = await client.search_release_groups_by_tag(
            tag, limit=limit, offset=offset, primary_type=primary_type
        )
    except ServiceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message) from exc

    groups = (payload or {}).get("release-groups") or []
    return SearchResponse(
        count=(payload or {}).get("count") or len(groups),
        offset=offset,
        items=await catalog.hydrate_and_build(session, client, groups),
    )


@router.get("/missing", response_model=list[AlbumCard])
async def missing_from_library(
    session: SessionDep,
    user: CurrentUser,
    artists: int = Query(default=4, ge=1, le=10),
    seed: int = Query(default=0),
) -> list[AlbumCard]:
    """Albums of the artists already in the library that are still missing.

    The draw is seeded so that refreshing the page, or requesting one of the
    albums, returns the same selection instead of shuffling under the reader.
    """
    candidates = list(
        session.execute(
            select(LibraryArtist).where(LibraryArtist.mbid.is_not(None))
        ).scalars()
    )
    if not candidates:
        return []

    candidates.sort(key=lambda artist: artist.mbid or "")
    random.Random(seed).shuffle(candidates)
    client = clients.musicbrainz(session)
    groups: list[dict] = []

    for artist in candidates[:artists]:
        try:
            payload = await client.browse_artist_release_groups(artist.mbid, limit=100)
        except ServiceError:
            continue
        for group in (payload or {}).get("release-groups") or []:
            if (group.get("primary-type") or "").lower() != "album":
                continue
            if group.get("secondary-types"):
                continue
            groups.append(group)

    cards = catalog.build_cards(session, groups)
    missing = [card for card in cards if not card.ownership.status and not card.request_status]
    missing.sort(key=lambda card: card.year or 0, reverse=True)
    return missing[:60]
