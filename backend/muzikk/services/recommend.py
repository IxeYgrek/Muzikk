"""Personal recommendations, built from listening data rather than from tags.

Muzikk keeps no listening history of its own: a play is forwarded to Jellyfin
and to the services the listener connected, and nothing is stored here. So the
taste has to come from outside, which is exactly what ListenBrainz and Last.fm
hold. When neither is connected the library stands in: the artists with the most
albums are a decent, if blunt, description of what somebody likes.

From those seeds, both services are asked for similar artists. The two answers
are merged by MusicBrainz identifier, which is the only key the rest of Muzikk
can act on: an artist name without an MBID is dropped rather than guessed at.
Their albums are then filtered against the library so that only what is missing
is proposed.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..matching.normalize import fuzzy_key
from ..models import LibraryArtist, User, WatchedArtist
from ..schemas import AlbumCard, ArtistOut
from . import catalog, clients
from . import settings as settings_service
from .base import ServiceError
from .lastfm import LastfmClient
from .listenbrainz import ListenBrainzClient

logger = logging.getLogger(__name__)

# How many seeds to expand. Each one costs a similar-artists call, then one
# discography browse per artist kept, so this is the knob that decides how long
# the page takes to build.
MAX_SEEDS = 6
MAX_SIMILAR_PER_SEED = 12
MAX_ARTISTS_EXPANDED = 10
MAX_ALBUMS = 60


@dataclass(slots=True)
class Seed:
    artist_mbid: str
    name: str = ""


@dataclass(slots=True)
class Suggestion:
    artist_mbid: str
    name: str
    score: float = 0.0
    sources: set[str] = field(default_factory=set)


def _library_seeds(session: Session, limit: int) -> list[Seed]:
    """The best-represented artists of the library, as a fallback taste."""
    rows = (
        session.execute(
            select(LibraryArtist)
            .where(LibraryArtist.mbid.is_not(None))
            .order_by(LibraryArtist.album_count.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return [Seed(artist_mbid=row.mbid or "", name=row.name) for row in rows if row.mbid]


async def seeds_for(session: Session, user: User, *, limit: int = MAX_SEEDS) -> tuple[list[Seed], list[str]]:
    """Artists to expand from, and which services they were read from."""
    seeds: dict[str, Seed] = {}
    sources: list[str] = []

    listenbrainz = settings_service.load(session, "listenbrainz")
    if listenbrainz.enabled and listenbrainz.recommendations and user.listenbrainz_user:
        client = ListenBrainzClient(listenbrainz)
        for row in await client.top_artists(user.listenbrainz_user, count=limit * 2):
            mbid = (row.get("artist_mbid") or "").strip()
            if mbid and mbid not in seeds:
                seeds[mbid] = Seed(artist_mbid=mbid, name=row.get("artist_name") or "")
        if seeds:
            sources.append("listenbrainz")

    lastfm = settings_service.load(session, "lastfm")
    if lastfm.enabled and lastfm.recommendations and user.lastfm_user:
        client = LastfmClient(lastfm)
        added = False
        for row in await client.top_artists(user.lastfm_user, limit=limit * 2):
            mbid = (row.get("mbid") or "").strip()
            if mbid and mbid not in seeds:
                seeds[mbid] = Seed(artist_mbid=mbid, name=row.get("name") or "")
                added = True
        if added:
            sources.append("lastfm")

    if not seeds:
        for seed in _library_seeds(session, limit):
            seeds[seed.artist_mbid] = seed
        if seeds:
            sources.append("library")

    return list(seeds.values())[:limit], sources


async def similar_to(session: Session, seeds: list[Seed]) -> list[Suggestion]:
    """Merge what both services consider close to these artists."""
    listenbrainz = settings_service.load(session, "listenbrainz")
    lastfm = settings_service.load(session, "lastfm")

    lb_client = ListenBrainzClient(listenbrainz) if listenbrainz.enabled and listenbrainz.recommendations else None
    fm_client = LastfmClient(lastfm) if lastfm.enabled and lastfm.recommendations else None
    if lb_client is None and fm_client is None:
        return []

    calls: list[asyncio.Future[list[dict]]] = []
    origins: list[str] = []
    for seed in seeds:
        if lb_client is not None:
            calls.append(
                asyncio.ensure_future(
                    lb_client.similar_artists(seed.artist_mbid, limit=MAX_SIMILAR_PER_SEED)
                )
            )
            origins.append("listenbrainz")
        if fm_client is not None:
            calls.append(
                asyncio.ensure_future(
                    fm_client.similar_artists(
                        mbid=seed.artist_mbid, name=seed.name, limit=MAX_SIMILAR_PER_SEED
                    )
                )
            )
            origins.append("lastfm")

    answers = await asyncio.gather(*calls, return_exceptions=True)

    known = {seed.artist_mbid.lower() for seed in seeds}
    merged: dict[str, Suggestion] = {}
    for origin, answer in zip(origins, answers, strict=True):
        if isinstance(answer, BaseException):
            logger.debug("Similar artists lookup failed on %s: %s", origin, answer)
            continue
        # Each service scores on its own scale, so ranking is by how many
        # services agree first, and by raw score only to break a tie.
        highest = max((float(row.get("score") or 0.0) for row in answer), default=0.0) or 1.0
        for row in answer:
            mbid = (row.get("artist_mbid") or "").strip()
            if not mbid or mbid.lower() in known:
                continue
            entry = merged.get(mbid)
            if entry is None:
                entry = Suggestion(artist_mbid=mbid, name=row.get("name") or "")
                merged[mbid] = entry
            entry.sources.add(origin)
            entry.score += float(row.get("score") or 0.0) / highest

    ranked = sorted(merged.values(), key=lambda item: (-len(item.sources), -item.score))
    return ranked


def _as_artist_cards(
    session: Session, user: User, suggestions: list[Suggestion], *, limit: int
) -> list[ArtistOut]:
    """Turn suggested artists into cards, flagging the ones already known.

    An artist the library already holds is still worth showing: it says the
    suggestion is on the right track, and the badge keeps it honest.
    """
    watched = {
        row.artist_mbid
        for row in session.execute(
            select(WatchedArtist).where(WatchedArtist.user_id == user.id)
        ).scalars()
    }
    library = session.execute(select(LibraryArtist.mbid, LibraryArtist.fuzzy_key)).all()
    library_mbids = {row.mbid for row in library if row.mbid}
    library_keys = {row.fuzzy_key for row in library if row.fuzzy_key}

    cards: list[ArtistOut] = []
    for suggestion in suggestions[:limit]:
        if not suggestion.name:
            continue
        cards.append(
            ArtistOut(
                mbid=suggestion.artist_mbid,
                name=suggestion.name,
                # Both services agreeing is the only signal worth showing here.
                disambiguation=(
                    " · ".join(sorted(suggestion.sources)) if len(suggestion.sources) > 1 else None
                ),
                watched=suggestion.artist_mbid in watched,
                in_library=suggestion.artist_mbid in library_mbids
                or fuzzy_key(suggestion.name, None) in library_keys,
            )
        )
    return cards


async def recommendations_for(
    session: Session, user: User, *, limit: int = MAX_ALBUMS, artist_limit: int = 12
) -> tuple[list[AlbumCard], list[ArtistOut], list[str], list[str]]:
    """Albums and artists worth discovering, and where they came from.

    Both are drawn from one pass: the similar-artist lookup is the expensive
    part, so the artists it returns are shown as suggestions of their own rather
    than thrown away once their albums have been listed.
    """
    seeds, sources = await seeds_for(session, user)
    if not seeds:
        return [], [], sources, []

    suggestions = await similar_to(session, seeds)
    if not suggestions:
        return [], [], sources, []

    client = clients.musicbrainz(session)
    groups: list[dict] = []
    expanded: list[str] = []

    for suggestion in suggestions[:MAX_ARTISTS_EXPANDED]:
        try:
            payload = await client.browse_artist_release_groups(suggestion.artist_mbid, limit=50)
        except ServiceError:
            continue
        found = False
        for group in (payload or {}).get("release-groups") or []:
            if (group.get("primary-type") or "").lower() != "album":
                continue
            if group.get("secondary-types"):
                continue
            groups.append(group)
            found = True
        if found and suggestion.name:
            expanded.append(suggestion.name)

    cards = catalog.build_cards(session, groups)
    # An album already owned, or already being fetched, is not a discovery.
    missing = [card for card in cards if not card.ownership.status and not card.request_status]
    missing.sort(key=lambda card: card.year or 0, reverse=True)

    artists = _as_artist_cards(session, user, suggestions, limit=artist_limit)
    return missing[:limit], artists, sources, expanded
