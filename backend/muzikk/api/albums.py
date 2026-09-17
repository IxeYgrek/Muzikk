"""Album and artist browsing on top of MusicBrainz."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from ..matching.normalize import fuzzy_key
from ..models import LibraryArtist, WatchedArtist
from ..schemas import AlbumDetail, ArtistOut, LabelDetail, LabelOut, SearchResponse
from ..services import catalog, clients
from ..services.base import ServiceError
from .deps import CurrentUser, SessionDep

router = APIRouter(tags=["catalog"])


@router.get("/albums/search", response_model=SearchResponse)
async def search_albums(
    session: SessionDep,
    user: CurrentUser,
    q: str = Query(default="", max_length=300),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    primary_type: str | None = Query(default=None),
) -> SearchResponse:
    client = clients.musicbrainz(session)
    try:
        payload = await client.search_release_groups(
            q, limit=limit, offset=offset, primary_type=primary_type
        )
    except ServiceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message) from exc

    groups = (payload or {}).get("release-groups") or []
    return SearchResponse(
        count=(payload or {}).get("count") or len(groups),
        offset=offset,
        items=await catalog.hydrate_and_build(session, client, groups),
    )


@router.get("/albums/{release_group_mbid}", response_model=AlbumDetail)
async def album_detail(
    release_group_mbid: str,
    session: SessionDep,
    user: CurrentUser,
    release: str | None = Query(default=None, description="Force a specific release MBID"),
) -> AlbumDetail:
    client = clients.musicbrainz(session)
    try:
        return await catalog.get_album_detail(
            session, client, release_group_mbid, release_mbid=release
        )
    except ServiceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message) from exc


@router.get("/artists/search", response_model=list[ArtistOut])
async def search_artists(
    session: SessionDep,
    user: CurrentUser,
    q: str = Query(default="", max_length=300),
    limit: int = Query(default=20, ge=1, le=50),
) -> list[ArtistOut]:
    client = clients.musicbrainz(session)
    try:
        payload = await client.search_artists(q, limit=limit)
    except ServiceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message) from exc

    watched = {
        row.artist_mbid
        for row in session.execute(
            select(WatchedArtist).where(WatchedArtist.user_id == user.id)
        ).scalars()
    }
    library = session.execute(select(LibraryArtist.mbid, LibraryArtist.fuzzy_key)).all()
    library_mbids = {row.mbid for row in library if row.mbid}
    library_keys = {row.fuzzy_key for row in library if row.fuzzy_key}

    results: list[ArtistOut] = []
    for artist in (payload or {}).get("artists") or []:
        mbid = artist.get("id")
        if not mbid:
            continue
        name = artist.get("name") or ""
        results.append(
            ArtistOut(
                mbid=mbid,
                name=name,
                disambiguation=artist.get("disambiguation") or None,
                country=artist.get("country") or None,
                type=artist.get("type") or None,
                genres=[
                    item.get("name") for item in (artist.get("tags") or [])[:6] if item.get("name")
                ],
                watched=mbid in watched,
                in_library=mbid in library_mbids or fuzzy_key(name, None) in library_keys,
            )
        )
    return results


def _label_out(payload: dict[str, Any], mbid: str = "") -> LabelOut:
    area = payload.get("area") or {}
    tags = payload.get("genres") or payload.get("tags") or []
    return LabelOut(
        mbid=str(payload.get("id") or mbid),
        name=str(payload.get("name") or ""),
        disambiguation=payload.get("disambiguation") or None,
        country=payload.get("country") or None,
        type=payload.get("type") or None,
        # A label code identifies a publisher the way a barcode identifies a
        # product; it is often the only way to tell two same-named labels apart.
        label_code=str(payload["label-code"]) if payload.get("label-code") else None,
        area=(area.get("name") if isinstance(area, dict) else None) or None,
        genres=[item.get("name") for item in tags[:6] if item.get("name")],
    )


@router.get("/labels/search", response_model=list[LabelOut])
async def search_labels(
    session: SessionDep,
    user: CurrentUser,
    q: str = Query(default="", max_length=300),
    limit: int = Query(default=25, ge=1, le=50),
) -> list[LabelOut]:
    client = clients.musicbrainz(session)
    try:
        payload = await client.search_labels(q, limit=limit)
    except ServiceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message) from exc

    return [
        _label_out(label) for label in (payload or {}).get("labels") or [] if label.get("id")
    ]


@router.get("/labels/{label_mbid}", response_model=LabelDetail)
async def label_detail(
    label_mbid: str,
    session: SessionDep,
    user: CurrentUser,
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> LabelDetail:
    """The catalogue of a label, folded from editions back into albums."""
    client = clients.musicbrainz(session)
    try:
        label = await client.get_label(label_mbid)
        releases_payload = await client.browse_releases_for_label(
            label_mbid, limit=limit, offset=offset
        )
    except ServiceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message) from exc

    groups = catalog.groups_from_releases((releases_payload or {}).get("releases") or [])
    groups.sort(key=lambda item: item.get("first-release-date") or "", reverse=True)

    return LabelDetail(
        label=_label_out(label, label_mbid),
        release_groups=catalog.build_cards(session, groups),
        # Editions, not albums: the two differ and the page says so.
        count=(releases_payload or {}).get("release-count") or 0,
        offset=offset,
    )


@router.get("/artists/{artist_mbid}")
async def artist_detail(
    artist_mbid: str,
    session: SessionDep,
    user: CurrentUser,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    client = clients.musicbrainz(session)
    try:
        artist = await client.get_artist(artist_mbid)
        groups_payload = await client.browse_artist_release_groups(
            artist_mbid, limit=limit, offset=offset
        )
    except ServiceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message) from exc

    groups = (groups_payload or {}).get("release-groups") or []
    groups.sort(key=lambda item: item.get("first-release-date") or "", reverse=True)

    watched = session.execute(
        select(WatchedArtist)
        .where(WatchedArtist.user_id == user.id)
        .where(WatchedArtist.artist_mbid == artist_mbid)
    ).scalar_one_or_none()

    library_artist = session.execute(
        select(LibraryArtist).where(
            (LibraryArtist.mbid == artist_mbid)
            | (LibraryArtist.fuzzy_key == fuzzy_key(artist.get("name"), None))
        )
    ).scalars().first()

    return {
        "artist": ArtistOut(
            mbid=artist_mbid,
            name=artist.get("name") or "",
            disambiguation=artist.get("disambiguation") or None,
            country=artist.get("country") or None,
            type=artist.get("type") or None,
            genres=[
                item.get("name")
                for item in (artist.get("genres") or artist.get("tags") or [])[:8]
                if item.get("name")
            ],
            watched=watched is not None,
            in_library=library_artist is not None,
        ).model_dump(),
        "release_groups": [card.model_dump() for card in catalog.build_cards(session, groups)],
        "count": (groups_payload or {}).get("release-group-count") or len(groups),
    }
