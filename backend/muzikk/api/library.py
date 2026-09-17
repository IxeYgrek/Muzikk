"""The Jellyfin music library, served from the local index."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import String, func, or_, select

from ..matching.normalize import normalize_artist, normalize_title
from ..models import LibraryAlbum, LibraryArtist
from ..schemas import LibraryAlbumDetail, LibraryAlbumOut, LibraryResponse, LibraryTrack
from ..services import clients, library_index
from ..services.base import ServiceError
from .deps import AdminUser, CurrentUser, SessionDep

router = APIRouter(prefix="/library", tags=["library"])

SORT_COLUMNS = {
    "recent": LibraryAlbum.date_created.desc(),
    "artist": LibraryAlbum.album_artist.asc(),
    "album": LibraryAlbum.name.asc(),
    "year": LibraryAlbum.year.desc(),
}


@router.get("/albums", response_model=LibraryResponse)
async def list_albums(
    session: SessionDep,
    user: CurrentUser,
    q: str | None = Query(default=None, max_length=200),
    artist: str | None = Query(default=None, max_length=300),
    genre: str | None = Query(default=None, max_length=100),
    year: int | None = Query(default=None, ge=1900, le=2100),
    quality: str | None = Query(default=None, pattern="^(lossless|lossy)$"),
    sort: str = Query(default="recent"),
    limit: int = Query(default=60, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> LibraryResponse:
    statement = select(LibraryAlbum)
    filters = []

    if q:
        pattern = f"%{q.strip()}%"
        filters.append(or_(LibraryAlbum.name.ilike(pattern), LibraryAlbum.album_artist.ilike(pattern)))
    if artist:
        filters.append(LibraryAlbum.album_artist.ilike(f"%{artist.strip()}%"))
    if year:
        filters.append(LibraryAlbum.year == year)
    if quality == "lossless":
        filters.append(LibraryAlbum.is_lossless.is_(True))
    elif quality == "lossy":
        filters.append(LibraryAlbum.is_lossless.is_(False))
    if genre:
        # The genre list is stored as a JSON array; SQLite keeps it as text.
        filters.append(
            func.lower(func.cast(LibraryAlbum.genres, String)).like(f'%"{genre.strip().lower()}"%')
        )

    for condition in filters:
        statement = statement.where(condition)

    count_statement = select(func.count()).select_from(LibraryAlbum)
    for condition in filters:
        count_statement = count_statement.where(condition)
    total = session.execute(count_statement).scalar() or 0

    statement = statement.order_by(SORT_COLUMNS.get(sort, SORT_COLUMNS["recent"]))
    rows = session.execute(statement.limit(limit).offset(offset)).scalars().all()

    return LibraryResponse(
        count=total,
        offset=offset,
        items=[LibraryAlbumOut.model_validate(row) for row in rows],
    )


@router.get("/albums/{jellyfin_id}", response_model=LibraryAlbumDetail)
async def album_detail(
    jellyfin_id: str, session: SessionDep, user: CurrentUser
) -> LibraryAlbumDetail:
    """One album of the library, tracklist included.

    Most albums carry a MusicBrainz release group and are read on the catalogue
    page instead. This one answers for the others: a folder Jellyfin gathered
    without any tag still deserves a page of its own.
    """
    row = (
        session.execute(select(LibraryAlbum).where(LibraryAlbum.jellyfin_id == jellyfin_id))
        .scalars()
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown album")

    tracks: list[LibraryTrack] = []
    failure: str | None = None
    client = clients.jellyfin(session)
    if not client.configured:
        failure = "Jellyfin is not configured"
    else:
        try:
            items = await client.get_album_tracks(jellyfin_id)
        except ServiceError as exc:
            failure = exc.message
        else:
            for item in items:
                if not item.get("Id"):
                    continue
                ticks = item.get("RunTimeTicks") or 0
                artists = item.get("Artists") or []
                tracks.append(
                    LibraryTrack(
                        jellyfin_id=item["Id"],
                        title=item.get("Name") or "",
                        artist=(artists[0] if artists else "") or item.get("AlbumArtist") or "",
                        track=item.get("IndexNumber"),
                        disc=item.get("ParentIndexNumber"),
                        duration=round(ticks / 10_000_000, 3) if ticks else None,
                        container=(item.get("Container") or "").lower(),
                    )
                )
            tracks.sort(key=lambda item: (item.disc or 1, item.track or 999, item.title))

    return LibraryAlbumDetail(
        album=LibraryAlbumOut.model_validate(row), tracks=tracks, tracks_error=failure
    )


@router.get("/artists")
async def list_artists(
    session: SessionDep,
    user: CurrentUser,
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[dict[str, object]]:
    statement = select(LibraryArtist).order_by(LibraryArtist.name.asc())
    if q:
        statement = statement.where(LibraryArtist.name.ilike(f"%{q.strip()}%"))
    rows = session.execute(statement.limit(limit)).scalars().all()
    return [
        {
            "id": row.id,
            "jellyfin_id": row.jellyfin_id,
            "name": row.name,
            "mbid": row.mbid,
            "album_count": row.album_count,
        }
        for row in rows
    ]


@router.get("/genres")
async def list_genres(session: SessionDep, user: CurrentUser) -> list[str]:
    counter: dict[str, int] = {}
    for genres in session.execute(select(LibraryAlbum.genres)).scalars():
        for genre in genres or []:
            key = genre.strip()
            if key:
                counter[key] = counter.get(key, 0) + 1
    return [name for name, _ in sorted(counter.items(), key=lambda item: (-item[1], item[0]))][:80]


@router.get("/years")
async def list_years(session: SessionDep, user: CurrentUser) -> list[int]:
    rows = session.execute(
        select(LibraryAlbum.year).where(LibraryAlbum.year.is_not(None)).distinct()
    ).scalars()
    return sorted({int(year) for year in rows if year}, reverse=True)


@router.get("/stats")
async def library_stats(session: SessionDep, user: CurrentUser) -> dict[str, int]:
    total = session.execute(select(func.count()).select_from(LibraryAlbum)).scalar() or 0
    lossless = (
        session.execute(
            select(func.count()).select_from(LibraryAlbum).where(LibraryAlbum.is_lossless.is_(True))
        ).scalar()
        or 0
    )
    tracks = session.execute(select(func.sum(LibraryAlbum.track_count))).scalar() or 0
    artists = session.execute(select(func.count()).select_from(LibraryArtist)).scalar() or 0
    return {
        "albums": total,
        "lossless_albums": lossless,
        "lossy_albums": total - lossless,
        "tracks": int(tracks),
        "artists": artists,
    }


@router.post("/sync")
async def sync(session: SessionDep, admin: AdminUser) -> dict[str, int]:
    try:
        return await library_index.sync_library(session)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/lookup")
async def lookup(
    session: SessionDep,
    user: CurrentUser,
    artist: str = Query(default=""),
    album: str = Query(default=""),
    release_group_mbid: str | None = Query(default=None),
) -> dict[str, object]:
    """Ownership probe used by the frontend for a single album."""
    index = library_index.OwnershipIndex(session)
    match = index.lookup(
        release_group_mbid=release_group_mbid,
        artist=normalize_artist(artist) and artist,
        album=normalize_title(album) and album,
    )
    if match is None:
        return {"status": None, "upgradable": False}
    return {
        "status": match.status,
        "upgradable": match.upgradable,
        "jellyfin_id": match.jellyfin_id,
        "formats": match.formats,
        "path": match.path,
    }
