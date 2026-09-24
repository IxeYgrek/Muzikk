"""Personal recommendations, built from listening data rather than from tags.

Muzikk keeps no listening history of its own: a play is forwarded to Jellyfin
and to the services the listener connected, and nothing is stored here. So the
taste comes from outside, which is exactly what ListenBrainz and Last.fm hold.
When neither is connected the library stands in: the artists with the most
albums are a decent, if blunt, description of what somebody likes.

Three shelves come out of one pass, because they call for three different
actions. What the listener already owns is worth playing again. What they do
not own is worth requesting. What has just come out is worth knowing about.
Every suggestion keeps the artist it was derived from, so a card can say why it
is there — a suggestion without a reason reads as a random one.

Building all this takes dozens of calls, so nothing here runs while a page is
loading: a job writes the rows, and the page reads them.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..matching.normalize import fuzzy_key
from ..models import (
    LibraryAlbum,
    LibraryArtist,
    Recommendation,
    RecommendationKind,
    RecommendationRun,
    RecommendationSection,
    User,
    WatchedArtist,
    utcnow,
)
from ..schemas import AlbumCard, ArtistOut, Ownership
from . import catalog, clients
from . import settings as settings_service
from .base import ServiceError
from .lastfm import LastfmClient
from .listenbrainz import ListenBrainzClient

logger = logging.getLogger(__name__)

# Seeds to expand. Each one costs a similar-artists call per service, so this is
# the knob that decides how long a run takes.
MAX_SEEDS = 14
MAX_SIMILAR_PER_SEED = 15
# Artists kept as suggestions of their own, and how many of them get their
# discography looked at for album suggestions.
MAX_ARTISTS = 24
MAX_ARTISTS_EXPANDED = 16
MAX_ALBUMS = 80
MAX_FRESH = 40
MAX_REDISCOVER = 40


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
    # The artist this was derived from. Shown on the card as the reason.
    seed_name: str = ""
    seed_mbid: str = ""


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


async def seeds_for(
    session: Session, user: User, *, limit: int = MAX_SEEDS
) -> tuple[list[Seed], list[str]]:
    """Artists to expand from, and which services they were read from.

    Read over the whole history and over the last quarter: the first says what
    somebody likes, the second what they are playing now, and a taste built on
    one alone is either stale or too thin to be worth anything.
    """
    seeds: dict[str, Seed] = {}
    sources: list[str] = []

    listenbrainz = settings_service.load(session, "listenbrainz")
    if listenbrainz.enabled and listenbrainz.recommendations and user.listenbrainz_user:
        client = ListenBrainzClient(listenbrainz)
        answers = await asyncio.gather(
            client.top_artists(user.listenbrainz_user, count=limit, range_="all_time"),
            client.top_artists(user.listenbrainz_user, count=limit, range_="quarter"),
            client.top_release_groups(user.listenbrainz_user, count=limit, range_="all_time"),
            return_exceptions=True,
        )
        before = len(seeds)
        for answer in answers:
            if isinstance(answer, BaseException):
                continue
            for row in answer:
                # An album row names its artist the same way an artist row does.
                mbid = (row.get("artist_mbid") or (row.get("artist_mbids") or [""])[0] or "").strip()
                if mbid and mbid not in seeds:
                    seeds[mbid] = Seed(
                        artist_mbid=mbid, name=row.get("artist_name") or row.get("artist") or ""
                    )
        if len(seeds) > before:
            sources.append("listenbrainz")

    lastfm = settings_service.load(session, "lastfm")
    if lastfm.enabled and lastfm.recommendations and user.lastfm_user:
        client = LastfmClient(lastfm)
        before = len(seeds)
        for row in await client.top_artists(user.lastfm_user, limit=limit, period="overall"):
            mbid = (row.get("mbid") or "").strip()
            if mbid and mbid not in seeds:
                seeds[mbid] = Seed(artist_mbid=mbid, name=row.get("name") or "")
        if len(seeds) > before:
            sources.append("lastfm")

    if not seeds:
        for seed in _library_seeds(session, limit):
            seeds[seed.artist_mbid] = seed
        if seeds:
            sources.append("library")

    return list(seeds.values())[:limit], sources


async def similar_to(session: Session, seeds: list[Seed]) -> list[Suggestion]:
    """Merge what both services consider close to these artists.

    Each service scores on its own scale, so a raw sum would let whichever one
    uses the larger numbers decide alone. Scores are normalised per answer, and
    ranking is by how many services agree first.
    """
    listenbrainz = settings_service.load(session, "listenbrainz")
    lastfm = settings_service.load(session, "lastfm")

    lb_client = (
        ListenBrainzClient(listenbrainz)
        if listenbrainz.enabled and listenbrainz.recommendations
        else None
    )
    fm_client = (
        LastfmClient(lastfm) if lastfm.enabled and lastfm.recommendations else None
    )
    if lb_client is None and fm_client is None:
        return []

    calls: list[asyncio.Future[list[dict]]] = []
    origins: list[tuple[str, Seed]] = []
    for seed in seeds:
        if lb_client is not None:
            calls.append(
                asyncio.ensure_future(
                    lb_client.similar_artists(seed.artist_mbid, limit=MAX_SIMILAR_PER_SEED)
                )
            )
            origins.append(("listenbrainz", seed))
        if fm_client is not None:
            calls.append(
                asyncio.ensure_future(
                    fm_client.similar_artists(
                        mbid=seed.artist_mbid, name=seed.name, limit=MAX_SIMILAR_PER_SEED
                    )
                )
            )
            origins.append(("lastfm", seed))

    answers = await asyncio.gather(*calls, return_exceptions=True)

    known = {seed.artist_mbid.lower() for seed in seeds}
    merged: dict[str, Suggestion] = {}
    for (origin, seed), answer in zip(origins, answers, strict=True):
        if isinstance(answer, BaseException):
            logger.debug("Similar artists lookup failed on %s: %s", origin, answer)
            continue
        highest = max((float(row.get("score") or 0.0) for row in answer), default=0.0) or 1.0
        for row in answer:
            mbid = (row.get("artist_mbid") or "").strip()
            if not mbid or mbid.lower() in known:
                continue
            entry = merged.get(mbid)
            if entry is None:
                entry = Suggestion(
                    artist_mbid=mbid,
                    name=row.get("name") or "",
                    seed_name=seed.name,
                    seed_mbid=seed.artist_mbid,
                )
                merged[mbid] = entry
            entry.sources.add(origin)
            entry.score += float(row.get("score") or 0.0) / highest

    return sorted(merged.values(), key=lambda item: (-len(item.sources), -item.score))


# ------------------------------------------------------------------ building


def _owned_groups(session: Session) -> set[str]:
    rows = session.execute(
        select(LibraryAlbum.release_group_mbid).where(LibraryAlbum.release_group_mbid.is_not(None))
    ).scalars()
    return {(value or "").lower() for value in rows if value}


def _owned_artists(session: Session) -> tuple[set[str], set[str]]:
    rows = session.execute(select(LibraryArtist.mbid, LibraryArtist.fuzzy_key)).all()
    return (
        {(row.mbid or "").lower() for row in rows if row.mbid},
        {row.fuzzy_key for row in rows if row.fuzzy_key},
    )


def _row(
    user: User,
    *,
    kind: str,
    section: str,
    card: AlbumCard | ArtistOut,
    seed_name: str = "",
    seed_mbid: str = "",
    sources: set[str] | None = None,
    score: float = 0.0,
) -> Recommendation:
    payload = card.model_dump()
    if isinstance(card, AlbumCard):
        return Recommendation(
            user_id=user.id,
            kind=kind,
            section=section,
            release_group_mbid=card.release_group_mbid,
            artist_mbid=card.artist_mbid,
            title=card.title[:500],
            artist_name=card.artist[:500],
            seed_name=seed_name[:500],
            seed_mbid=seed_mbid or None,
            sources=sorted(sources or ()),
            score=score,
            payload=payload,
        )
    return Recommendation(
        user_id=user.id,
        kind=kind,
        section=section,
        artist_mbid=card.mbid,
        title=card.name[:500],
        artist_name=card.name[:500],
        seed_name=seed_name[:500],
        seed_mbid=seed_mbid or None,
        sources=sorted(sources or ()),
        score=score,
        payload=payload,
    )


async def _discover_rows(
    session: Session, user: User, suggestions: list[Suggestion]
) -> tuple[list[Recommendation], int, int]:
    """Artists and albums the library does not hold, each with its reason."""
    owned_mbids, owned_keys = _owned_artists(session)
    watched = {
        row.artist_mbid
        for row in session.execute(
            select(WatchedArtist).where(WatchedArtist.user_id == user.id)
        ).scalars()
    }

    rows: list[Recommendation] = []
    artists = 0
    for suggestion in suggestions:
        if artists >= MAX_ARTISTS:
            break
        if not suggestion.name:
            continue
        # Somebody already in the library is not a discovery.
        if (
            suggestion.artist_mbid.lower() in owned_mbids
            or fuzzy_key(suggestion.name, None) in owned_keys
        ):
            continue
        rows.append(
            _row(
                user,
                kind=RecommendationKind.ARTIST,
                section=RecommendationSection.DISCOVER,
                card=ArtistOut(
                    mbid=suggestion.artist_mbid,
                    name=suggestion.name,
                    watched=suggestion.artist_mbid in watched,
                ),
                seed_name=suggestion.seed_name,
                seed_mbid=suggestion.seed_mbid,
                sources=suggestion.sources,
                score=suggestion.score,
            )
        )
        artists += 1

    # Albums: the records people actually play, not a whole discography.
    listenbrainz = settings_service.load(session, "listenbrainz")
    lb_client = ListenBrainzClient(listenbrainz) if listenbrainz.enabled else None
    client = clients.musicbrainz(session)

    groups: list[dict] = []
    reasons: dict[str, Suggestion] = {}
    for suggestion in suggestions[:MAX_ARTISTS_EXPANDED]:
        best: list[dict] = []
        if lb_client is not None:
            best = await lb_client.top_release_groups_for_artist(suggestion.artist_mbid, limit=4)
        if best:
            for entry in best:
                reasons[entry["release_group_mbid"].lower()] = suggestion
                groups.append(
                    {
                        "id": entry["release_group_mbid"],
                        "title": entry["title"],
                        "first-release-date": entry.get("date") or "",
                        "primary-type": "Album",
                        "secondary-types": [],
                        "artist-credit": [
                            {"name": entry.get("artist") or suggestion.name}
                        ],
                    }
                )
            continue
        # Nothing popular known: fall back on the catalogue.
        try:
            payload = await client.browse_artist_release_groups(suggestion.artist_mbid, limit=30)
        except ServiceError:
            continue
        for group in (payload or {}).get("release-groups") or []:
            if (group.get("primary-type") or "").lower() != "album" or group.get("secondary-types"):
                continue
            reasons[(group.get("id") or "").lower()] = suggestion
            groups.append(group)

    cards = catalog.build_cards(session, groups)
    albums = 0
    for card in cards:
        if albums >= MAX_ALBUMS:
            break
        if card.ownership.status or card.request_status:
            continue
        suggestion = reasons.get(card.release_group_mbid.lower())
        rows.append(
            _row(
                user,
                kind=RecommendationKind.ALBUM,
                section=RecommendationSection.DISCOVER,
                card=card,
                seed_name=suggestion.seed_name if suggestion else "",
                seed_mbid=suggestion.seed_mbid if suggestion else "",
                sources=suggestion.sources if suggestion else None,
                score=suggestion.score if suggestion else 0.0,
            )
        )
        albums += 1

    return rows, artists, albums


async def _rediscover_rows(session: Session, user: User) -> list[Recommendation]:
    """Albums the listener owns and has been playing elsewhere, or is nudged to.

    Nothing here is downloaded: these are records already on the shelf, which is
    why they get a play button and not a request one.
    """
    listenbrainz = settings_service.load(session, "listenbrainz")
    lastfm = settings_service.load(session, "lastfm")

    wanted: dict[str, str] = {}
    if listenbrainz.enabled and listenbrainz.recommendations and user.listenbrainz_user:
        client = ListenBrainzClient(listenbrainz)
        for row in await client.top_release_groups(
            user.listenbrainz_user, count=60, range_="all_time"
        ):
            mbid = (row.get("release_group_mbid") or "").strip().lower()
            if mbid:
                wanted[mbid] = row.get("artist_name") or ""
        for track in await client.recommended_playlist_tracks(user.listenbrainz_user):
            # Playlists name a release, the library is indexed by release group,
            # so these only land here when the album is recognised below.
            if track.get("familiar") and track.get("title"):
                wanted.setdefault(track["release_mbid"].lower(), track.get("artist") or "")

    if lastfm.enabled and lastfm.recommendations and user.lastfm_user:
        client = LastfmClient(lastfm)
        for row in await client.top_albums(user.lastfm_user, limit=60, period="overall"):
            mbid = (row.get("mbid") or "").strip().lower()
            if mbid:
                wanted.setdefault(mbid, ((row.get("artist") or {}).get("name") or ""))

    if not wanted:
        return []

    owned = (
        session.execute(
            select(LibraryAlbum).where(
                LibraryAlbum.release_group_mbid.is_not(None)
            )
        )
        .scalars()
        .all()
    )
    rows: list[Recommendation] = []
    for album in owned:
        if len(rows) >= MAX_REDISCOVER:
            break
        group = (album.release_group_mbid or "").lower()
        release = (album.release_mbid or "").lower()
        if group not in wanted and release not in wanted:
            continue
        card = AlbumCard(
            release_group_mbid=album.release_group_mbid or "",
            title=album.name,
            artist=album.album_artist,
            artist_mbid=album.artist_mbid,
            year=album.year,
            primary_type="Album",
            secondary_types=[],
            cover_url=catalog.cover_url(
                album.release_group_mbid, album.release_mbid, album.jellyfin_id
            ),
            # Owned by definition: these rows come out of the library index.
            ownership=Ownership(
                status="owned",
                upgradable=not album.is_lossless,
                jellyfin_id=album.jellyfin_id,
                formats=list(album.formats or []),
                path=album.path,
            ),
            request_status=None,
            request_id=None,
        )
        rows.append(
            _row(
                user,
                kind=RecommendationKind.ALBUM,
                section=RecommendationSection.REDISCOVER,
                card=card,
            )
        )
    return rows


async def _fresh_rows(session: Session, user: User) -> list[Recommendation]:
    """Records just out by artists this listener actually plays."""
    listenbrainz = settings_service.load(session, "listenbrainz")
    if not (
        listenbrainz.enabled and listenbrainz.recommendations and user.listenbrainz_user
    ):
        return []

    client = ListenBrainzClient(listenbrainz)
    entries = await client.personal_fresh_releases(user.listenbrainz_user, days=60)
    if not entries:
        return []

    groups = [
        {
            "id": entry["release_group_mbid"],
            "title": entry["title"],
            "first-release-date": entry.get("date") or "",
            "primary-type": entry.get("primary_type") or "Album",
            "secondary-types": [],
            "artist-credit": [
                {
                    "name": entry.get("artist") or "",
                    "artist": {"id": entry.get("artist_mbid") or ""},
                }
            ],
        }
        for entry in entries
    ]

    rows: list[Recommendation] = []
    for card in catalog.build_cards(session, groups):
        if len(rows) >= MAX_FRESH:
            break
        if card.ownership.status or card.request_status:
            continue
        rows.append(
            _row(
                user,
                kind=RecommendationKind.ALBUM,
                section=RecommendationSection.FRESH,
                card=card,
                sources={"listenbrainz"},
            )
        )
    return rows


async def refresh_for(session: Session, user: User) -> dict[str, object]:
    """Recompute every shelf for one listener and store the result.

    Rows are replaced wholesale rather than merged: a taste moves, and a
    suggestion nobody asked to keep has no reason to outlive the run that made
    it. The ones the listener hid are the exception.
    """
    run = session.get(RecommendationRun, user.id) or RecommendationRun(user_id=user.id)
    run.started_at = utcnow()
    run.finished_at = None
    run.error = None
    session.add(run)
    session.commit()

    hidden = {
        (row.kind, row.release_group_mbid or row.artist_mbid)
        for row in session.execute(
            select(Recommendation).where(
                Recommendation.user_id == user.id, Recommendation.ignored.is_(True)
            )
        ).scalars()
    }

    try:
        seeds, sources = await seeds_for(session, user)
        suggestions = await similar_to(session, seeds) if seeds else []
        discover, artists, albums = (
            await _discover_rows(session, user, suggestions) if suggestions else ([], 0, 0)
        )
        rediscover = await _rediscover_rows(session, user)
        fresh = await _fresh_rows(session, user)
    except Exception as exc:  # noqa: BLE001 - a failed run must not kill the worker
        logger.exception("Recommendation run failed for user %s", user.id)
        run.error = str(exc)[:500]
        run.finished_at = utcnow()
        session.commit()
        raise

    session.execute(delete(Recommendation).where(Recommendation.user_id == user.id))
    kept = 0
    for row in discover + rediscover + fresh:
        if (row.kind, row.release_group_mbid or row.artist_mbid) in hidden:
            row.ignored = True
            kept += 1
        session.add(row)

    report = {
        "seeds": len(seeds),
        "similar": len(suggestions),
        "artists": artists,
        "albums": albums,
        "rediscover": len(rediscover),
        "fresh": len(fresh),
        "hidden_kept": kept,
    }
    run.sources = sources
    run.finished_at = utcnow()
    run.report = report
    session.commit()
    logger.info("Recommendations for user %s: %s", user.id, report)
    return report


async def refresh_all(session: Session) -> dict[str, object]:
    """Recompute for every listener who connected a service.

    Accounts that connected nothing are left alone: their suggestions would be
    read off the library, which the Discover page can do on its own without
    anybody's data leaving the server on a schedule.
    """
    listeners = (
        session.execute(
            select(User).where(
                User.is_enabled.is_(True),
                (User.listenbrainz_user.is_not(None)) | (User.lastfm_user.is_not(None)),
            )
        )
        .scalars()
        .all()
    )
    done = 0
    failed = 0
    for listener in listeners:
        try:
            await refresh_for(session, listener)
            done += 1
        except Exception:  # noqa: BLE001 - one bad account must not stop the rest
            failed += 1
    return {"listeners": len(listeners), "refreshed": done, "failed": failed}
