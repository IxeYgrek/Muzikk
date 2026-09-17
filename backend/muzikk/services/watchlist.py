"""Artist following and wishlist upkeep.

Following an artist is a reading habit, not an order: nothing here creates a
request. The check writes down what the library is missing, the Follow tab
shows it, and each album waits for someone to press the button.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Request,
    RequestStatus,
    WatchedArtist,
    WatchedRelease,
    WatchScope,
    WishlistItem,
    utcnow,
)
from . import clients
from . import requests as requests_service
from .library_index import OwnershipIndex

logger = logging.getLogger(__name__)

# A release group is considered "new" while it is this recent.
NEW_RELEASE_WINDOW_DAYS = 400
# What counts as a release worth telling a follower about. A single is in:
# nothing downloads by itself any more, so leaving it out only hid records
# somebody might want.
WANTED_TYPES = ("album", "ep", "single")
# Enough for a long career; browsing further would cost a page per artist.
BROWSE_LIMIT = 100


def trim_group(group: dict[str, Any]) -> dict[str, Any]:
    """Keep just enough of a release group to draw its card later."""
    return {
        "id": group.get("id"),
        "title": group.get("title") or "",
        "first-release-date": group.get("first-release-date") or "",
        "primary-type": group.get("primary-type"),
        "secondary-types": list(group.get("secondary-types") or []),
        "artist-credit": group.get("artist-credit") or [],
    }


def _wanted(
    groups: list[dict[str, Any]], watch: WatchedArtist, cutoff: str
) -> list[tuple[dict[str, Any], bool]]:
    """The albums this follow is about, each with whether it is a new release.

    Albums, EPs and singles all count. Compilations, live albums and the rest
    of the secondary types are left out: a follower wants the discography, not
    every repackaging of it.
    """
    only_new = watch.scope != WatchScope.MISSING
    kept: list[tuple[dict[str, Any], bool]] = []

    for group in groups:
        if not group.get("id") or group.get("secondary-types"):
            continue
        primary = (group.get("primary-type") or "").lower()
        if primary and primary not in WANTED_TYPES:
            continue
        date = group.get("first-release-date") or ""
        is_new = bool(date) and date >= cutoff
        if only_new and not is_new:
            continue
        kept.append((group, is_new))
    return kept


async def check_watched_artists(session: Session) -> dict[str, int]:
    """Refresh what the followed artists are missing from the library."""
    watches = list(session.execute(select(WatchedArtist)).scalars())
    if not watches:
        return {"artists": 0, "missing": 0, "added": 0}

    client = clients.musicbrainz(session)
    index = OwnershipIndex(session)
    cutoff = (utcnow() - timedelta(days=NEW_RELEASE_WINDOW_DAYS)).strftime("%Y-%m-%d")
    missing = 0
    added = 0

    for watch in watches:
        try:
            payload = await client.browse_artist_release_groups(
                watch.artist_mbid, limit=BROWSE_LIMIT
            )
        except Exception as exc:  # noqa: BLE001 - one artist must not break the run
            logger.warning("Watchlist check failed for %s: %s", watch.artist_name, exc)
            continue

        known = {
            row.release_group_mbid: row
            for row in session.execute(
                select(WatchedRelease).where(WatchedRelease.watch_id == watch.id)
            ).scalars()
        }
        now = utcnow()
        seen: set[str] = set()

        for group, is_new in _wanted((payload or {}).get("release-groups") or [], watch, cutoff):
            mbid = group["id"]
            title = group.get("title") or ""
            if index.lookup(release_group_mbid=mbid, artist=watch.artist_name, album=title):
                continue

            seen.add(mbid)
            missing += 1
            row = known.get(mbid)
            if row is None:
                session.add(
                    WatchedRelease(
                        watch_id=watch.id,
                        release_group_mbid=mbid,
                        title=title,
                        primary_type=group.get("primary-type"),
                        first_release_date=group.get("first-release-date") or None,
                        is_new=is_new,
                        payload=trim_group(group),
                        last_seen_at=now,
                    )
                )
                added += 1
                continue

            row.title = title
            row.primary_type = group.get("primary-type")
            row.first_release_date = group.get("first-release-date") or None
            row.is_new = is_new
            row.payload = trim_group(group)
            row.last_seen_at = now

        # What the library now holds, or what the chosen scope no longer covers,
        # has no reason to stay on the list.
        for mbid, row in known.items():
            if mbid not in seen:
                session.delete(row)

        watch.last_checked_at = now
        session.commit()

    return {"artists": len(watches), "missing": missing, "added": added}


async def refresh_wishlist(session: Session) -> dict[str, int]:
    """Close the wishlist entries the library ended up holding.

    Nothing is requested here. An entry leaves the list when the album shows up
    in the library, or when a request for it finished importing.
    """
    items = list(
        session.execute(select(WishlistItem).where(WishlistItem.is_active.is_(True))).scalars()
    )
    fulfilled = 0
    index = OwnershipIndex(session)

    for item in items:
        owned = index.lookup(
            release_group_mbid=item.release_group_mbid,
            artist=item.artist_name,
            album=item.album_title,
        )
        if owned is None:
            imported = session.execute(
                select(Request.id)
                .where(Request.release_group_mbid == item.release_group_mbid)
                .where(Request.status == RequestStatus.IMPORTED)
            ).first()
            if imported is None:
                continue

        item.is_active = False
        fulfilled += 1

    session.commit()
    return {"items": len(items), "fulfilled": fulfilled}


async def retry_failed_requests(session: Session) -> dict[str, int]:
    """Requeue failed requests whose retry delay has elapsed."""
    rows = list(
        session.execute(
            select(Request)
            .where(Request.status == RequestStatus.FAILED)
            .where(Request.retry_after.is_not(None))
            .where(Request.retry_after <= utcnow())
        ).scalars()
    )
    for request in rows:
        requests_service.retry_request(session, request)
    return {"requeued": len(rows)}
