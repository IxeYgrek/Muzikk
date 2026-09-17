"""Turns MusicBrainz payloads into the shapes the frontend consumes."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..matching.release_picker import ReleaseInfo, pick_release
from ..models import Request, RequestStatus
from ..schemas import AlbumCard, AlbumDetail, Ownership, ReleaseSummary, TrackOut
from .library_index import OwnershipIndex
from .musicbrainz import MusicBrainzClient

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = (
    RequestStatus.PENDING,
    RequestStatus.APPROVED,
    *RequestStatus.ACTIVE,
    RequestStatus.AWAITING_VALIDATION,
    RequestStatus.FAILED,
    RequestStatus.IMPORTED,
)


def artist_credit_name(credits: Iterable[dict[str, Any]] | None) -> str:
    if not credits:
        return ""
    parts: list[str] = []
    for credit in credits:
        name = credit.get("name") or (credit.get("artist") or {}).get("name") or ""
        parts.append(name)
        join = credit.get("joinphrase") or ""
        if join:
            parts.append(join)
    return "".join(parts).strip()


def artist_credit_mbid(credits: Iterable[dict[str, Any]] | None) -> str | None:
    for credit in credits or []:
        artist = credit.get("artist") or {}
        if artist.get("id"):
            return artist["id"]
    return None


def year_of(date: str | None) -> int | None:
    if date and len(date) >= 4 and date[:4].isdigit():
        return int(date[:4])
    return None


def cover_url(
    release_group_mbid: str | None,
    release_mbid: str | None = None,
    jellyfin_id: str | None = None,
) -> str | None:
    """Build a cover URL carrying its own fallbacks.

    An album we already own goes straight to Jellyfin: that is the picture the
    listener already sees on the album page, and Cover Art Archive often has
    nothing yet for a release that just landed. Everyone else gets the edition
    first, then the release group.
    """
    if jellyfin_id:
        return f"/api/images/jellyfin/{jellyfin_id}"
    if release_mbid:
        path = f"/api/images/cover/release/{release_mbid}"
        extra = {"group": release_group_mbid}
    elif release_group_mbid:
        path = f"/api/images/cover/release-group/{release_group_mbid}"
        extra = {}
    else:
        return None

    query = "&".join(f"{key}={value}" for key, value in extra.items() if value)
    return f"{path}?{query}" if query else path


def request_status_map(session: Session, release_group_mbids: Iterable[str]) -> dict[str, Request]:
    mbids = [mbid for mbid in release_group_mbids if mbid]
    if not mbids:
        return {}
    rows = (
        session.execute(
            select(Request)
            .where(Request.release_group_mbid.in_(mbids))
            .where(Request.status.in_(ACTIVE_STATUSES))
            .order_by(Request.id.desc())
        )
        .scalars()
        .all()
    )
    result: dict[str, Request] = {}
    for row in rows:
        # Rows are ordered newest first; keep the most relevant one.
        current = result.get(row.release_group_mbid)
        if current is None:
            result[row.release_group_mbid] = row
            continue
        if current.status == RequestStatus.IMPORTED and row.status != RequestStatus.IMPORTED:
            result[row.release_group_mbid] = row
    return result


def _ownership_payload(match) -> Ownership:
    if match is None:
        return Ownership()
    return Ownership(
        status=match.status,
        upgradable=match.upgradable,
        jellyfin_id=match.jellyfin_id,
        formats=match.formats,
        path=match.path,
    )


def groups_from_releases(releases: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fold a list of editions back into the albums they belong to.

    Browsing by label, or by anything else attached to editions rather than to
    albums, returns the same album once per pressing. Each group keeps every
    edition seen, which also sharpens the ownership lookup, and borrows the
    artist credit of its first edition since the embedded group carries none.
    """
    grouped: dict[str, dict[str, Any]] = {}
    for release in releases:
        group = release.get("release-group") or {}
        mbid = group.get("id")
        if not mbid:
            continue

        known = grouped.get(mbid)
        if known is None:
            known = {
                **group,
                "artist-credit": group.get("artist-credit")
                or release.get("artist-credit")
                or [],
                "releases": [],
            }
            grouped[mbid] = known
        if release.get("id"):
            known["releases"].append({"id": release["id"]})

    return list(grouped.values())


def attach_releases(groups: list[dict[str, Any]], releases: list[dict[str, Any]]) -> None:
    """Hang edition identifiers on each group, so a card can ask CAA for one."""
    by_group: dict[str, list[dict[str, Any]]] = {}
    for release in releases:
        group = release.get("release-group")
        group_id = group.get("id") if isinstance(group, dict) else group
        if not group_id or not release.get("id"):
            continue
        by_group.setdefault(group_id, []).append({"id": release["id"]})

    for group in groups:
        extra = by_group.get(group.get("id") or "")
        if not extra:
            continue
        known = {item.get("id") for item in (group.get("releases") or [])}
        group.setdefault("releases", [])
        group["releases"].extend(item for item in extra if item["id"] not in known)


async def hydrate_and_build(session: Session, client: Any, groups: list[dict[str, Any]]) -> list[AlbumCard]:
    """Cards with an edition on them, so the search grid matches the album page."""
    try:
        releases = await client.releases_for_groups([group.get("id") for group in groups])
    except Exception:  # noqa: BLE001 - a cover miss must not blank the search
        releases = []
    attach_releases(groups, releases)
    return build_cards(session, groups)


def build_cards(session: Session, release_groups: list[dict[str, Any]]) -> list[AlbumCard]:
    index = OwnershipIndex(session)
    requests = request_status_map(session, [group.get("id") for group in release_groups])
    cards: list[AlbumCard] = []

    for group in release_groups:
        mbid = group.get("id")
        if not mbid:
            continue
        credits = group.get("artist-credit")
        artist = artist_credit_name(credits)
        title = group.get("title") or ""
        release_mbids = [
            release.get("id") for release in (group.get("releases") or []) if release.get("id")
        ]
        match = index.lookup(
            release_group_mbid=mbid,
            release_mbids=release_mbids,
            artist=artist,
            album=title,
        )
        pending = requests.get(mbid)
        cards.append(
            AlbumCard(
                release_group_mbid=mbid,
                title=title,
                artist=artist,
                artist_mbid=artist_credit_mbid(credits),
                year=year_of(group.get("first-release-date")),
                primary_type=group.get("primary-type"),
                secondary_types=list(group.get("secondary-types") or []),
                cover_url=cover_url(
                    mbid,
                    release_mbids[0] if release_mbids else None,
                    match.jellyfin_id if match else None,
                ),
                ownership=_ownership_payload(match),
                request_status=pending.status if pending else None,
                request_id=pending.id if pending else None,
            )
        )
    return cards


def _release_summary(release: ReleaseInfo, *, recommended_mbid: str | None) -> ReleaseSummary:
    return ReleaseSummary(
        release_mbid=release.mbid,
        title=release.title,
        date=release.date,
        country=release.country,
        status=release.status,
        formats=release.formats,
        track_count=release.track_count,
        disc_count=release.disc_count,
        label=release.label,
        is_recommended=release.mbid == recommended_mbid,
    )


def _tracks_from_release(payload: dict[str, Any]) -> list[TrackOut]:
    tracks: list[TrackOut] = []
    for disc_index, medium in enumerate(payload.get("media") or [], start=1):
        disc_number = medium.get("position") or disc_index
        for track in medium.get("tracks") or []:
            recording = track.get("recording") or {}
            length = track.get("length") or recording.get("length")
            credits = track.get("artist-credit") or recording.get("artist-credit")
            tracks.append(
                TrackOut(
                    position=track.get("position") or len(tracks) + 1,
                    disc=disc_number,
                    title=track.get("title") or recording.get("title") or "",
                    length_ms=int(length) if length else None,
                    recording_mbid=recording.get("id"),
                    artist=artist_credit_name(credits) or None,
                )
            )
    return tracks


async def get_album_detail(
    session: Session,
    client: MusicBrainzClient,
    release_group_mbid: str,
    *,
    release_mbid: str | None = None,
) -> AlbumDetail:
    group = await client.get_release_group(release_group_mbid)
    browse = await client.browse_releases_for_group(release_group_mbid)
    releases_payload = (browse or {}).get("releases") or []

    recommended, ranked = pick_release(
        releases_payload, group_first_date=group.get("first-release-date")
    )
    chosen_mbid = release_mbid or (recommended.mbid if recommended else None)

    detail_payload: dict[str, Any] = {}
    tracks: list[TrackOut] = []
    if chosen_mbid:
        try:
            detail_payload = await client.get_release(chosen_mbid)
            tracks = _tracks_from_release(detail_payload)
        except Exception as exc:  # noqa: BLE001 - the page must still render
            logger.warning("Unable to load release %s: %s", chosen_mbid, exc)

    credits = group.get("artist-credit")
    artist = artist_credit_name(credits)
    title = group.get("title") or ""

    index = OwnershipIndex(session)
    match = index.lookup(
        release_group_mbid=release_group_mbid,
        release_mbids=[release.mbid for release in ranked],
        artist=artist,
        album=title,
    )
    pending = request_status_map(session, [release_group_mbid]).get(release_group_mbid)

    selected = next((release for release in ranked if release.mbid == chosen_mbid), None)
    genres = sorted(
        {
            (item.get("name") or "").strip()
            for item in (group.get("genres") or []) + (group.get("tags") or [])
            if item.get("name")
        }
    )

    return AlbumDetail(
        release_group_mbid=release_group_mbid,
        title=title,
        artist=artist,
        artist_mbid=artist_credit_mbid(credits),
        year=year_of(group.get("first-release-date")),
        primary_type=group.get("primary-type"),
        secondary_types=list(group.get("secondary-types") or []),
        genres=genres[:12],
        cover_url=cover_url(
            release_group_mbid, chosen_mbid, match.jellyfin_id if match else None
        ),
        ownership=_ownership_payload(match),
        request_status=pending.status if pending else None,
        request_id=pending.id if pending else None,
        selected_release=(
            _release_summary(selected, recommended_mbid=recommended.mbid if recommended else None)
            if selected
            else None
        ),
        releases=[
            _release_summary(release, recommended_mbid=recommended.mbid if recommended else None)
            for release in ranked
        ],
        tracks=tracks,
    )
