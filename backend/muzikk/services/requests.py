"""Request lifecycle: creation, approval, retry and cancellation."""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..jobs import queue
from ..models import Request, RequestEvent, RequestKind, RequestStatus, User, utcnow
from ..pipeline import importer
from . import clients
from . import settings as settings_service
from . import users as users_service
from .catalog import artist_credit_mbid, artist_credit_name, year_of
from .library_index import OwnershipIndex
from .musicbrainz import MusicBrainzClient

logger = logging.getLogger(__name__)


class RequestError(RuntimeError):
    def __init__(self, message: str, *, code: str = "invalid") -> None:
        super().__init__(message)
        self.code = code


def _log(session: Session, request_id: int, stage: str, message: str, level: str = "info") -> None:
    session.add(
        RequestEvent(request_id=request_id, stage=stage, message=message, level=level)
    )
    session.commit()


def weekly_usage(session: Session, user: User) -> int:
    since = utcnow() - timedelta(days=7)
    return (
        session.execute(
            select(func.count())
            .select_from(Request)
            .where(Request.user_id == user.id)
            .where(Request.created_at >= since)
            .where(Request.status != RequestStatus.REJECTED)
        ).scalar()
        or 0
    )


async def _resolve_metadata(
    client: MusicBrainzClient, release_group_mbid: str
) -> dict[str, object]:
    group = await client.get_release_group(release_group_mbid)
    credits = group.get("artist-credit")
    return {
        "artist_name": artist_credit_name(credits) or "Unknown Artist",
        "artist_mbid": artist_credit_mbid(credits),
        "album_title": group.get("title") or "Unknown Album",
        "primary_type": group.get("primary-type"),
        "year": year_of(group.get("first-release-date")),
    }


async def _resolve_track(
    client: MusicBrainzClient, recording_mbid: str
) -> dict[str, object]:
    """The album a recording belongs to, and the title to look for.

    A track request is filed inside its album, so the release group has to be
    resolved here rather than trusted from the caller: a recording appears on
    several releases and only one of them is the record being completed.
    """
    recording = await client.get_recording(recording_mbid)
    title = recording.get("title") or ""
    credits = recording.get("artist-credit")

    group_mbid = ""
    release_mbid = None
    for release in recording.get("releases") or []:
        group = release.get("release-group") or {}
        if group.get("id"):
            group_mbid = group["id"]
            release_mbid = release.get("id")
            break

    return {
        "recording_mbid": recording_mbid,
        "track_title": title,
        "artist_name": artist_credit_name(credits) or "Unknown Artist",
        "artist_mbid": artist_credit_mbid(credits),
        "release_group_mbid": group_mbid,
        "release_mbid": release_mbid,
    }


async def create_request(
    session: Session,
    user: User,
    release_group_mbid: str,
    *,
    release_mbid: str | None = None,
    is_upgrade: bool = False,
    recording_mbid: str | None = None,
) -> Request:
    """Create a request for a whole album, or for one track of one."""
    wants_track = bool(recording_mbid)

    if is_upgrade:
        if not user.can_upgrade and not user.is_admin:
            raise RequestError(
                "This account is not allowed to request upgrades", code="forbidden"
            )
    elif wants_track:
        if not user.can_request_track and not user.is_admin:
            raise RequestError(
                "This account is not allowed to request single tracks", code="forbidden"
            )
    elif not user.can_request and not user.is_admin:
        raise RequestError("This account is not allowed to request albums", code="forbidden")

    client = clients.musicbrainz(session)
    track: dict[str, object] = {}
    if wants_track:
        track = await _resolve_track(client, str(recording_mbid))
        # The album the recording belongs to wins over anything the caller sent:
        # it is where the file will be filed.
        release_group_mbid = str(track["release_group_mbid"] or release_group_mbid)
        release_mbid = release_mbid or (track["release_mbid"] or None)  # type: ignore[assignment]
        if not release_group_mbid:
            raise RequestError("MusicBrainz lists no album for this track")

    # Matched on the same thing that was asked for: a track request and an album
    # request on the same record are two different jobs, and merging them would
    # silently answer one with the other.
    query = (
        select(Request)
        .where(Request.release_group_mbid == release_group_mbid)
        .where(Request.status.notin_((RequestStatus.REJECTED, RequestStatus.CANCELLED)))
        .order_by(Request.id.desc())
    )
    if wants_track:
        query = query.where(Request.recording_mbid == recording_mbid)
    else:
        query = query.where(Request.kind == RequestKind.ALBUM)

    existing = session.execute(query).scalars().first()
    if existing is not None:
        if existing.status == RequestStatus.IMPORTED and is_upgrade:
            pass  # an upgrade of an already imported album is a new request
        elif existing.status == RequestStatus.FAILED:
            return retry_request(session, existing)
        else:
            return existing

    if user.weekly_quota and not user.is_admin:
        used = weekly_usage(session, user)
        if used >= user.weekly_quota:
            raise RequestError(
                f"Weekly quota reached ({used}/{user.weekly_quota})", code="quota_exceeded"
            )

    metadata = await _resolve_metadata(client, release_group_mbid)

    replaces_path = None
    if is_upgrade:
        match = OwnershipIndex(session).lookup(
            release_group_mbid=release_group_mbid,
            release_mbids=[release_mbid] if release_mbid else None,
            artist=str(metadata["artist_name"]),
            album=str(metadata["album_title"]),
        )
        if match is not None:
            replaces_path = match.path

    auto_approve = users_service.effective_auto_approve(session, user)
    request = Request(
        user_id=user.id,
        release_group_mbid=release_group_mbid,
        release_mbid=release_mbid,
        artist_name=str(metadata["artist_name"]),
        artist_mbid=metadata["artist_mbid"] or None,
        album_title=str(metadata["album_title"]),
        primary_type=metadata["primary_type"],
        year=metadata["year"],
        is_upgrade=is_upgrade,
        replaces_path=replaces_path,
        kind=RequestKind.TRACK if wants_track else RequestKind.ALBUM,
        recording_mbid=str(track["recording_mbid"]) if wants_track else None,
        track_title=str(track["track_title"]) if wants_track else None,
        status=RequestStatus.APPROVED if auto_approve else RequestStatus.PENDING,
        approved_by_id=user.id if auto_approve else None,
        approved_at=utcnow() if auto_approve else None,
    )
    session.add(request)
    session.commit()
    session.refresh(request)

    what = f'track "{request.track_title}"' if wants_track else "album"
    _log(
        session,
        request.id,
        "created",
        f"{what} requested by {user.name}"
        + ("" if auto_approve else ", waiting for approval"),
    )
    if auto_approve:
        queue.enqueue(
            session, queue.PROCESS_REQUEST, {"request_id": request.id}, request_id=request.id
        )
    return request


def approve_request(session: Session, request: Request, admin: User) -> Request:
    if request.status != RequestStatus.PENDING:
        raise RequestError("This request is not awaiting approval")
    request.status = RequestStatus.APPROVED
    request.approved_by_id = admin.id
    request.approved_at = utcnow()
    request.error = None
    session.commit()
    _log(session, request.id, "approved", f"approved by {admin.name}")
    queue.enqueue(
        session, queue.PROCESS_REQUEST, {"request_id": request.id}, request_id=request.id
    )
    return request


def reject_request(session: Session, request: Request, admin: User, reason: str = "") -> Request:
    if request.status not in (RequestStatus.PENDING, RequestStatus.FAILED):
        raise RequestError("Only a pending or failed request can be rejected")
    request.status = RequestStatus.REJECTED
    request.error = reason or None
    request.completed_at = utcnow()
    session.commit()
    _log(
        session,
        request.id,
        "rejected",
        f"rejected by {admin.name}" + (f": {reason}" if reason else ""),
        level="warning",
    )
    return request


def cancel_request(session: Session, request: Request) -> Request:
    request.status = RequestStatus.CANCELLED
    request.completed_at = utcnow()
    request.retry_after = None
    session.commit()
    _log(session, request.id, "cancelled", "cancelled", level="warning")
    return request


def resolve_upgrade(session: Session, request: Request, *, accept: bool) -> list[str]:
    """Carry out the decision taken on an upgrade.

    Accepting deletes the copy the new release supersedes; refusing deletes the
    files we just added instead, so the library is left exactly as it was.
    """
    if request.status != RequestStatus.AWAITING_VALIDATION or not request.upgrade_review:
        raise RequestError("This request is not waiting for a validation")

    review = dict(request.upgrade_review)
    music_dir = Path(settings_service.load(session, "naming").music_dir)
    if accept:
        removed = importer.commit_upgrade(review, music_dir)
        request.status = RequestStatus.IMPORTED
        request.error = None
        message = f"upgrade validated, {len(removed)} file(s) of the previous copy deleted"
        level = "info"
    else:
        removed = importer.revert_upgrade(review, music_dir)
        request.status = RequestStatus.REJECTED
        request.error = "upgrade refused, the previous copy was kept"
        message = f"upgrade refused, {len(removed)} newly imported file(s) deleted"
        level = "warning"

    review["resolved"] = "accepted" if accept else "refused"
    review["removed"] = removed
    request.upgrade_review = review
    request.completed_at = utcnow()
    session.commit()
    _log(session, request.id, "import", message, level=level)
    return removed


def retry_request(session: Session, request: Request) -> Request:
    request.status = RequestStatus.APPROVED
    request.error = None
    request.retry_after = None
    request.progress = 0.0
    request.exhausted_providers = []
    session.commit()
    _log(session, request.id, "retry", "new attempt queued")
    queue.enqueue(
        session, queue.PROCESS_REQUEST, {"request_id": request.id}, request_id=request.id
    )
    return request
