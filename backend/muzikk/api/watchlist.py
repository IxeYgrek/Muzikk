"""Followed artists, the albums they are missing, and the wishlist."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..jobs import queue
from ..models import User, WatchedArtist, WatchedRelease, WishlistItem
from ..schemas import (
    WatchCreate,
    WatchedArtistOut,
    WatchedReleaseOut,
    WatchUpdate,
    WishlistCreate,
    WishlistItemOut,
)
from ..services import catalog
from .deps import CurrentUser, SessionDep

router = APIRouter(tags=["watchlist"])


def _watch_out(row: WatchedArtist, missing: int) -> WatchedArtistOut:
    payload = WatchedArtistOut.model_validate(row)
    payload.missing = missing
    return payload


def _missing_count(session: Session, watch_id: int) -> int:
    return (
        session.execute(
            select(func.count())
            .select_from(WatchedRelease)
            .where(WatchedRelease.watch_id == watch_id)
            .where(WatchedRelease.ignored.is_(False))
        ).scalar()
        or 0
    )


def _own_watch(session: Session, watch_id: int, user: User) -> WatchedArtist:
    row = session.get(WatchedArtist, watch_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Not followed")
    if row.user_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="This follow belongs to another user")
    return row


@router.get("/watchlist", response_model=list[WatchedArtistOut])
async def list_watched(session: SessionDep, user: CurrentUser) -> list[WatchedArtistOut]:
    rows = (
        session.execute(
            select(WatchedArtist)
            .where(WatchedArtist.user_id == user.id)
            .order_by(WatchedArtist.artist_name.asc())
        )
        .scalars()
        .all()
    )
    counts = dict(
        session.execute(
            select(WatchedRelease.watch_id, func.count())
            .where(WatchedRelease.watch_id.in_([row.id for row in rows] or [0]))
            .where(WatchedRelease.ignored.is_(False))
            .group_by(WatchedRelease.watch_id)
        ).all()
    )
    return [_watch_out(row, counts.get(row.id, 0)) for row in rows]


@router.post("/watchlist", response_model=WatchedArtistOut, status_code=status.HTTP_201_CREATED)
async def follow_artist(
    payload: WatchCreate, session: SessionDep, user: CurrentUser
) -> WatchedArtistOut:
    existing = session.execute(
        select(WatchedArtist)
        .where(WatchedArtist.user_id == user.id)
        .where(WatchedArtist.artist_mbid == payload.artist_mbid)
    ).scalar_one_or_none()
    if existing is not None:
        return _watch_out(existing, _missing_count(session, existing.id))

    row = WatchedArtist(
        user_id=user.id,
        artist_mbid=payload.artist_mbid,
        artist_name=payload.artist_name,
        scope=payload.scope,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    queue.enqueue(session, queue.WATCHLIST_CHECK)
    return _watch_out(row, 0)


@router.patch("/watchlist/{watch_id}", response_model=WatchedArtistOut)
async def update_watch(
    watch_id: int, payload: WatchUpdate, session: SessionDep, user: CurrentUser
) -> WatchedArtistOut:
    row = _own_watch(session, watch_id, user)
    if row.scope != payload.scope:
        row.scope = payload.scope
        session.commit()
        # The list of missing albums depends on the scope, so it has to be
        # drawn again before the tab can be trusted.
        queue.enqueue(session, queue.WATCHLIST_CHECK)
    return _watch_out(row, _missing_count(session, row.id))


@router.delete("/watchlist/{watch_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unfollow_artist(watch_id: int, session: SessionDep, user: CurrentUser) -> None:
    row = _own_watch(session, watch_id, user)
    session.delete(row)
    session.commit()


@router.post("/watchlist/check")
async def check_now(session: SessionDep, user: CurrentUser) -> dict[str, bool]:
    queue.enqueue(session, queue.WATCHLIST_CHECK)
    return {"queued": True}


@router.get("/watchlist/releases", response_model=list[WatchedReleaseOut])
async def list_watched_releases(
    session: SessionDep,
    user: CurrentUser,
    artist_mbid: str | None = Query(default=None),
    only_new: bool = Query(default=False),
    ignored: bool = Query(default=False),
) -> list[WatchedReleaseOut]:
    """The albums the followed artists are missing, newest first.

    Ownership and request status are read live rather than from the rows: an
    album requested a minute ago has to show it, without waiting for the next
    check to come round.
    """
    statement = (
        select(WatchedRelease, WatchedArtist)
        .join(WatchedArtist, WatchedArtist.id == WatchedRelease.watch_id)
        .where(WatchedArtist.user_id == user.id)
        .where(WatchedRelease.ignored.is_(ignored))
        .order_by(WatchedRelease.first_release_date.desc(), WatchedRelease.title.asc())
    )
    if artist_mbid:
        statement = statement.where(WatchedArtist.artist_mbid == artist_mbid)
    if only_new:
        statement = statement.where(WatchedRelease.is_new.is_(True))

    pairs = session.execute(statement).all()
    cards = {
        card.release_group_mbid: card
        for card in catalog.build_cards(session, [dict(row.payload or {}) for row, _ in pairs])
    }

    result: list[WatchedReleaseOut] = []
    for row, watch in pairs:
        card = cards.get(row.release_group_mbid)
        if card is None:
            continue
        result.append(
            WatchedReleaseOut(
                id=row.id,
                watch_id=row.watch_id,
                artist_mbid=watch.artist_mbid,
                artist_name=watch.artist_name,
                is_new=row.is_new,
                ignored=row.ignored,
                first_release_date=row.first_release_date,
                album=card,
            )
        )
    return result


@router.patch("/watchlist/releases/{release_id}", status_code=status.HTTP_204_NO_CONTENT)
async def set_release_ignored(
    release_id: int, session: SessionDep, user: CurrentUser, ignored: bool = Query(default=True)
) -> None:
    row = session.get(WatchedRelease, release_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown album")
    watch = session.get(WatchedArtist, row.watch_id)
    if watch is None or (watch.user_id != user.id and not user.is_admin):
        raise HTTPException(status_code=403, detail="This follow belongs to another user")
    row.ignored = ignored
    session.commit()


@router.get("/wishlist", response_model=list[WishlistItemOut])
async def list_wishlist(session: SessionDep, user: CurrentUser) -> list[WishlistItemOut]:
    statement = select(WishlistItem).order_by(WishlistItem.created_at.desc())
    if not user.is_admin:
        statement = statement.where(WishlistItem.user_id == user.id)
    rows = session.execute(statement).scalars().all()
    return [WishlistItemOut.model_validate(row) for row in rows]


@router.post("/wishlist", response_model=WishlistItemOut, status_code=status.HTTP_201_CREATED)
async def add_to_wishlist(
    payload: WishlistCreate, session: SessionDep, user: CurrentUser
) -> WishlistItemOut:
    existing = session.execute(
        select(WishlistItem)
        .where(WishlistItem.user_id == user.id)
        .where(WishlistItem.release_group_mbid == payload.release_group_mbid)
    ).scalar_one_or_none()
    if existing is not None:
        existing.is_active = True
        session.commit()
        return WishlistItemOut.model_validate(existing)

    row = WishlistItem(
        user_id=user.id,
        release_group_mbid=payload.release_group_mbid,
        artist_name=payload.artist_name,
        album_title=payload.album_title,
        artist_mbid=payload.artist_mbid,
        year=payload.year,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return WishlistItemOut.model_validate(row)


@router.delete("/wishlist/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_from_wishlist(item_id: int, session: SessionDep, user: CurrentUser) -> None:
    row = session.get(WishlistItem, item_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Not in the wishlist")
    if row.user_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="This entry belongs to another user")
    session.delete(row)
    session.commit()


@router.post("/wishlist/refresh")
async def refresh_wishlist(session: SessionDep, user: CurrentUser) -> dict[str, bool]:
    """Close the entries the library ended up holding. Nothing is downloaded."""
    queue.enqueue(session, queue.WISHLIST_RETRY)
    return {"queued": True}
