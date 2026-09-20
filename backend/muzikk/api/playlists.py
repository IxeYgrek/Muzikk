"""Jellyfin playlists, seen and edited as the signed in listener.

Everything here runs under the token Muzikk stored when the user signed in,
never under the server API key: a playlist belongs to an account, and the key
would file them all under whichever account owns it.

Playlists live in Jellyfin, so an installation without one has none. Every
route below refuses in local mode and the interface hides the section.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import LibraryAlbum, User
from ..schemas import PlaylistAdd, PlaylistChange, PlaylistCreate, PlaylistOut, PlaylistTrack
from ..services import catalog, clients
from ..services import mode as mode_service
from ..services import users as users_service
from ..services.base import ServiceError
from ..services.jellyfin import JellyfinClient
from .deps import CurrentUser, SessionDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/playlists", tags=["playlists"])


def _client(session: Session) -> JellyfinClient:
    if mode_service.is_local(session):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This installation has no Jellyfin, and therefore no playlists",
        )
    client = clients.jellyfin(session)
    if not client.configured:
        raise HTTPException(status_code=400, detail="Jellyfin is not configured")
    return client


def _token(user: User) -> str:
    token = users_service.jellyfin_token(user)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No Jellyfin session for this account: sign out and sign in again",
        )
    return token


def _fail(exc: ServiceError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message)


def _albums_by_jellyfin_id(session: Session, ids: set[str]) -> dict[str, LibraryAlbum]:
    if not ids:
        return {}
    rows = (
        session.execute(select(LibraryAlbum).where(LibraryAlbum.jellyfin_id.in_(ids)))
        .scalars()
        .all()
    )
    return {row.jellyfin_id: row for row in rows}


async def _resolve_tracks(
    client: JellyfinClient, payload: PlaylistAdd | PlaylistCreate
) -> list[str]:
    """The tracks to add, an album standing for its own in track order."""
    ids = [item for item in payload.track_ids if item]
    if payload.album_id:
        items = await client.get_album_tracks(payload.album_id)
        items.sort(
            key=lambda item: (
                item.get("ParentIndexNumber") or 1,
                item.get("IndexNumber") or 999,
                item.get("Name") or "",
            )
        )
        ids.extend(item["Id"] for item in items if item.get("Id"))
    # Keep the order, drop the repeats.
    return list(dict.fromkeys(ids))


@router.get("", response_model=list[PlaylistOut])
async def list_playlists(session: SessionDep, user: CurrentUser) -> list[PlaylistOut]:
    client = _client(session)
    try:
        items = await client.get_playlists(token=_token(user), user_id=user.jellyfin_user_id)
    except ServiceError as exc:
        raise _fail(exc) from exc

    return [
        PlaylistOut(
            id=item.get("Id") or "",
            name=item.get("Name") or "",
            track_count=int(item.get("ChildCount") or 0),
            can_delete=bool(item.get("CanDelete")),
            cover_url=catalog.cover_url(None, None, item.get("Id")),
        )
        for item in items
        if item.get("Id")
    ]


@router.get("/{playlist_id}", response_model=list[PlaylistTrack])
async def playlist_tracks(
    playlist_id: str, session: SessionDep, user: CurrentUser
) -> list[PlaylistTrack]:
    client = _client(session)
    try:
        items = await client.get_playlist_items(
            playlist_id, token=_token(user), user_id=user.jellyfin_user_id
        )
    except ServiceError as exc:
        raise _fail(exc) from exc

    albums = _albums_by_jellyfin_id(
        session, {item.get("AlbumId") for item in items if item.get("AlbumId")}
    )
    tracks: list[PlaylistTrack] = []
    for item in items:
        if not item.get("Id"):
            continue
        album = albums.get(item.get("AlbumId") or "")
        ticks = item.get("RunTimeTicks") or 0
        artists = item.get("Artists") or []
        tracks.append(
            PlaylistTrack(
                jellyfin_id=item["Id"],
                playlist_item_id=item.get("PlaylistItemId") or "",
                title=item.get("Name") or "",
                artist=(artists[0] if artists else "") or item.get("AlbumArtist") or "",
                album=item.get("Album") or (album.name if album else ""),
                album_id=item.get("AlbumId"),
                track=item.get("IndexNumber"),
                disc=item.get("ParentIndexNumber"),
                duration=round(ticks / 10_000_000, 3) if ticks else None,
                container=(item.get("Container") or "").lower(),
                cover_url=catalog.cover_url(
                    album.release_group_mbid if album else None,
                    album.release_mbid if album else None,
                    item.get("AlbumId"),
                ),
                stream_url=f"/api/play/track/{item['Id']}",
            )
        )
    return tracks


@router.post("", response_model=PlaylistChange, status_code=status.HTTP_201_CREATED)
async def create_playlist(
    payload: PlaylistCreate, session: SessionDep, user: CurrentUser
) -> PlaylistChange:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="A playlist needs a name")

    client = _client(session)
    token = _token(user)
    try:
        ids = await _resolve_tracks(client, payload)
        playlist_id = await client.create_playlist(
            name, token=token, user_id=user.jellyfin_user_id, item_ids=ids
        )
    except ServiceError as exc:
        raise _fail(exc) from exc

    return PlaylistChange(playlist_id=playlist_id, name=name, added=len(ids))


@router.post("/{playlist_id}/items", response_model=PlaylistChange)
async def add_items(
    playlist_id: str, payload: PlaylistAdd, session: SessionDep, user: CurrentUser
) -> PlaylistChange:
    client = _client(session)
    token = _token(user)
    try:
        ids = await _resolve_tracks(client, payload)
        if not ids:
            raise HTTPException(status_code=400, detail="Nothing to add")
        await client.add_to_playlist(
            playlist_id, ids, token=token, user_id=user.jellyfin_user_id
        )
    except ServiceError as exc:
        raise _fail(exc) from exc

    return PlaylistChange(playlist_id=playlist_id, name="", added=len(ids))


@router.delete("/{playlist_id}/items", status_code=status.HTTP_204_NO_CONTENT)
async def remove_items(
    playlist_id: str, entry_ids: str, session: SessionDep, user: CurrentUser
) -> None:
    entries = [item for item in entry_ids.split(",") if item]
    if not entries:
        raise HTTPException(status_code=400, detail="Nothing to remove")
    client = _client(session)
    try:
        await client.remove_from_playlist(playlist_id, entries, token=_token(user))
    except ServiceError as exc:
        raise _fail(exc) from exc


@router.delete("/{playlist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_playlist(playlist_id: str, session: SessionDep, user: CurrentUser) -> None:
    client = _client(session)
    try:
        await client.delete_playlist(playlist_id, token=_token(user))
    except ServiceError as exc:
        raise _fail(exc) from exc
