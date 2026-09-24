"""Discovery: suggestions, new releases, genres and albums missing here.

Every tab is built on MusicBrainz, which is the only catalogue that can be
navigated by identifier. The listening services are layered on top where they
know something MusicBrainz does not: what is popular in a genre, and what has
just come out that people are actually playing.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from ..jobs import queue
from ..matching.normalize import fuzzy_key
from ..models import (
    LibraryArtist,
    Recommendation,
    RecommendationKind,
    RecommendationRun,
    RecommendationSection,
)
from ..schemas import (
    AlbumCard,
    RecommendationResponse,
    SearchResponse,
    SuggestedAlbum,
    SuggestedArtist,
)
from ..services import catalog, clients
from ..services import settings as settings_service
from ..services.base import ServiceError
from ..services.lastfm import LastfmClient
from ..services.listenbrainz import ListenBrainzClient
from .deps import CurrentUser, SessionDep

router = APIRouter(prefix="/discover", tags=["discover"])

FALLBACK_GENRES = [
    "rock", "pop", "electronic", "hip hop", "jazz", "metal", "classical",
    "folk", "soul", "funk", "punk", "reggae", "blues", "ambient",
    "techno", "house", "indie rock", "rap", "disco", "country",
]


def _group_from_service(entry: dict[str, Any]) -> dict[str, Any]:
    """A MusicBrainz-shaped release group built from what a service returned.

    Everything downstream reads ws/2 keys, so a foreign answer is translated
    rather than special-cased. Only entries carrying a release group identifier
    get this far, so the card can always be clicked through.
    """
    return {
        "id": entry["release_group_mbid"],
        "title": entry.get("title") or "",
        "first-release-date": entry.get("date") or "",
        "primary-type": entry.get("primary_type") or "Album",
        "secondary-types": [],
        "artist-credit": [
            {
                "name": entry.get("artist") or "",
                "artist": {"id": entry.get("artist_mbid") or "", "name": entry.get("artist") or ""},
            }
        ],
    }


@router.get("/new-releases", response_model=SearchResponse)
async def new_releases(
    session: SessionDep,
    user: CurrentUser,
    months: int = Query(default=3, ge=1, le=24),
    primary_type: str = Query(default="album"),
    limit: int = Query(default=40, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> SearchResponse:
    """Records recently out, from MusicBrainz and from ListenBrainz.

    MusicBrainz answers a date range: everything catalogued in the window,
    whether anyone listens to it or not. ListenBrainz keeps a fresh-releases
    list of its own, which is shorter and closer to what is actually played, so
    the two are merged with its entries first.
    """
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

    # Only on the first page: paging through a merged list would repeat entries.
    fresh: list[dict[str, Any]] = []
    listenbrainz = settings_service.load(session, "listenbrainz")
    if offset == 0 and listenbrainz.enabled and listenbrainz.recommendations:
        known = {(group.get("id") or "").lower() for group in groups}
        for entry in await ListenBrainzClient(listenbrainz).fresh_releases(
            days=min(months * 31, 90), limit=limit
        ):
            if entry["release_group_mbid"].lower() in known:
                continue
            if primary_type and (entry.get("primary_type") or "").lower() != primary_type.lower():
                continue
            fresh.append(_group_from_service(entry))

    merged = fresh + groups
    return SearchResponse(
        count=(payload or {}).get("count") or len(merged),
        offset=offset,
        items=await catalog.hydrate_and_build(session, client, merged[:limit]),
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
    """Albums carrying a genre, ordered by how well known they are for it.

    MusicBrainz lists what carries the tag but knows nothing of popularity, so
    everything comes back in an order nobody would call useful. Last.fm ranks
    the same tag by how often it is applied, and that ranking is used to reorder
    the MusicBrainz list — by name, never by identifier, because a Last.fm album
    identifier is not reliably a release group and would break the album page.
    """
    client = clients.musicbrainz(session)
    try:
        payload = await client.search_release_groups_by_tag(
            tag, limit=limit, offset=offset, primary_type=primary_type
        )
    except ServiceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message) from exc

    groups = (payload or {}).get("release-groups") or []

    lastfm = settings_service.load(session, "lastfm")
    if lastfm.enabled and lastfm.recommendations:
        ranking = {
            fuzzy_key(row["artist"], row["album"]): position
            for position, row in enumerate(
                await LastfmClient(lastfm).top_albums_for_tag(tag, limit=200)
            )
        }
        if ranking:
            def rank(group: dict[str, Any]) -> int:
                key = fuzzy_key(catalog.artist_credit_name(group.get("artist-credit")), group.get("title"))
                # Unknown to Last.fm: kept, but after everything it ranked.
                return ranking.get(key, len(ranking) + 1)

            groups.sort(key=rank)

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


@router.get("/for-you", response_model=RecommendationResponse)
async def for_you(session: SessionDep, user: CurrentUser) -> RecommendationResponse:
    """Everything computed for this listener, read straight from the table.

    Nothing is computed here: a run takes dozens of calls across two services
    and MusicBrainz. The page says when it last ran and offers to run it again.
    """
    rows = (
        session.execute(
            select(Recommendation)
            .where(Recommendation.user_id == user.id, Recommendation.ignored.is_(False))
            .order_by(Recommendation.score.desc(), Recommendation.id.asc())
        )
        .scalars()
        .all()
    )
    run = session.get(RecommendationRun, user.id)

    def albums(section: str) -> list[SuggestedAlbum]:
        return [
            SuggestedAlbum(
                **row.payload, id=row.id, seed_name=row.seed_name, sources=row.sources or []
            )
            for row in rows
            if row.section == section and row.kind == RecommendationKind.ALBUM
        ]

    listenbrainz = settings_service.load(session, "listenbrainz")
    lastfm = settings_service.load(session, "lastfm")
    return RecommendationResponse(
        artists=[
            SuggestedArtist(
                **row.payload, id=row.id, seed_name=row.seed_name, sources=row.sources or []
            )
            for row in rows
            if row.kind == RecommendationKind.ARTIST
        ],
        items=albums(RecommendationSection.DISCOVER),
        rediscover=albums(RecommendationSection.REDISCOVER),
        fresh=albums(RecommendationSection.FRESH),
        sources=list(run.sources or []) if run else [],
        computed_at=run.finished_at if run else None,
        running=bool(run and run.finished_at is None),
        # Whether connecting an account would change anything at all.
        connected=bool(user.listenbrainz_user or user.lastfm_user),
        available=bool(listenbrainz.enabled or lastfm.enabled),
    )


@router.post("/for-you/refresh")
async def refresh_for_you(session: SessionDep, user: CurrentUser) -> dict[str, Any]:
    """Queue a rebuild of this listener's suggestions."""
    job = queue.enqueue(
        session, queue.RECOMMENDATIONS, {"user_id": user.id}, unique=False
    )
    return {"queued": True, "job_id": job.id if job else None}


@router.post("/for-you/hide/{recommendation_id}")
async def hide_recommendation(
    recommendation_id: int, session: SessionDep, user: CurrentUser
) -> dict[str, bool]:
    """Hide one suggestion, and keep it hidden through later runs."""
    row = session.get(Recommendation, recommendation_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="Unknown recommendation")
    row.ignored = True
    session.commit()
    return {"hidden": True}
