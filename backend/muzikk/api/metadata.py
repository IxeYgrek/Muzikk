"""Metadata administration: find the gaps, then fill them from MusicBrainz.

The screen behind these endpoints plays the role Picard plays for a local
collection, with one difference: the album is compared with the Jellyfin index
as well, so the folders the media server silently ignored show up too.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import String, distinct, func, or_, select
from sqlalchemy.orm import Session

from ..jobs import queue
from ..models import Job, JobState, LibraryAlbum, MetadataAlbum, MetadataIssue, MetadataState
from ..schemas import (
    ArtworkSyncReport,
    JellyfinCoverReport,
    JellyfinMetadataReport,
    MetadataAlbumDetail,
    MetadataAlbumOut,
    MetadataApplyOut,
    MetadataListResponse,
    MetadataMatchRequest,
    MetadataPlanOut,
    MetadataProposalOut,
    MetadataScanReport,
    MetadataSummary,
)
from ..services import acoustid, catalog, coverfiles, jellyfincovers, jellyfinmeta, metadata
from ..services import settings as settings_service
from ..services.base import ServiceError
from ..services.jellyfin import JellyfinClient
from .deps import AdminUser, SessionDep

router = APIRouter(prefix="/metadata", tags=["metadata"])

MBID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)


def _to_out(row: MetadataAlbum) -> MetadataAlbumOut:
    payload = MetadataAlbumOut.model_validate(row)
    # Folders with no identifier at all still have their own artwork on disk.
    payload.cover_url = catalog.cover_url(
        row.match_release_group_mbid or row.release_group_mbid,
        row.match_release_mbid or row.release_mbid,
        row.jellyfin_id,
    ) or (f"/api/images/folder/{row.id}" if row.has_cover else None)
    return payload


def _load(session: Session, album_id: int) -> MetadataAlbum:
    row = session.get(MetadataAlbum, album_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown album")
    return row


def _job_running(session: Session, kind: str = queue.METADATA_SCAN) -> bool:
    return (
        session.execute(
            select(func.count())
            .select_from(Job)
            .where(Job.kind == kind)
            .where(Job.state.in_((JobState.QUEUED, JobState.RUNNING)))
        ).scalar()
        or 0
    ) > 0


def _last_job_error(session: Session, kind: str = queue.METADATA_SCAN) -> str:
    """Why the most recent run of that job stopped, if it did stop badly.

    The worker only writes the failure into the job row, so without this the
    screen would show an empty list and no explanation at all.
    """
    job = (
        session.execute(
            select(Job)
            .where(Job.kind == kind)
            .where(Job.state.in_((JobState.DONE, JobState.FAILED)))
            .order_by(Job.id.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    if job is None or job.state != JobState.FAILED:
        return ""
    return job.error or "the analysis failed without leaving a message"


@router.get("/summary", response_model=MetadataSummary)
async def summary(session: SessionDep, admin: AdminUser) -> MetadataSummary:
    naming = settings_service.load(session, "naming")
    config = settings_service.load(session, "metadata")

    totals = {
        state: session.execute(
            select(func.count()).select_from(MetadataAlbum).where(MetadataAlbum.state == state)
        ).scalar()
        or 0
        for state in (MetadataState.OPEN, MetadataState.RESOLVED, MetadataState.IGNORED)
    }

    # SQLite stores the JSON array as text, which is enough to count members.
    issues: dict[str, int] = {}
    for kind in MetadataIssue.ALL:
        issues[kind] = (
            session.execute(
                select(func.count())
                .select_from(MetadataAlbum)
                .where(MetadataAlbum.state == MetadataState.OPEN)
                .where(func.cast(MetadataAlbum.issues, String).like(f'%"{kind}"%'))
            ).scalar()
            or 0
        )

    last_scan = session.execute(select(func.max(MetadataAlbum.scanned_at))).scalar()
    # Shown next to the analysed count: a large gap means folders were skipped.
    library_albums = (
        session.execute(select(func.count()).select_from(LibraryAlbum)).scalar() or 0
    )
    stored = metadata.read_scan_report(session)
    artwork_report = coverfiles.read_report(session)
    jellyfin_report = jellyfincovers.read_report(session)
    metadata_report = jellyfinmeta.read_report(session)

    return MetadataSummary(
        total=sum(totals.values()),
        open=totals[MetadataState.OPEN],
        resolved=totals[MetadataState.RESOLVED],
        ignored=totals[MetadataState.IGNORED],
        issues=issues,
        last_scan_at=last_scan,
        library_dir=naming.music_dir,
        library_readable=Path(naming.music_dir).is_dir(),
        fingerprinting_available=acoustid.available(),
        acoustid_configured=bool(config.acoustid_enabled and config.acoustid_api_key),
        scan_running=_job_running(session),
        last_error=_last_job_error(session),
        library_albums=library_albums,
        last_scan=MetadataScanReport.model_validate(stored) if stored else None,
        artwork_running=_job_running(session, queue.ARTWORK_SYNC),
        artwork_error=_last_job_error(session, queue.ARTWORK_SYNC),
        last_artwork_sync=(
            ArtworkSyncReport.model_validate(artwork_report) if artwork_report else None
        ),
        jellyfin_covers_running=_job_running(session, queue.JELLYFIN_COVERS),
        jellyfin_covers_error=_last_job_error(session, queue.JELLYFIN_COVERS),
        last_jellyfin_covers=(
            JellyfinCoverReport.model_validate(jellyfin_report) if jellyfin_report else None
        ),
        jellyfin_meta_running=_job_running(session, queue.JELLYFIN_METADATA),
        jellyfin_meta_error=_last_job_error(session, queue.JELLYFIN_METADATA),
        last_jellyfin_meta=(
            JellyfinMetadataReport.model_validate(metadata_report) if metadata_report else None
        ),
    )


@router.post("/scan")
async def start_scan(session: SessionDep, admin: AdminUser) -> dict[str, object]:
    """Queue a full analysis; it runs in the background worker."""
    if _job_running(session):
        return {"queued": False, "message": "an analysis is already running"}
    queue.enqueue(session, queue.METADATA_SCAN, priority=3)
    return {"queued": True}


@router.post("/artwork-sync")
async def start_artwork_sync(session: SessionDep, admin: AdminUser) -> dict[str, object]:
    """Queue the pass that gives every album folder both cover.jpg and folder.jpg."""
    if _job_running(session, queue.ARTWORK_SYNC):
        return {"queued": False, "message": "the artwork pass is already running"}
    queue.enqueue(session, queue.ARTWORK_SYNC, priority=3)
    return {"queued": True}


@router.post("/jellyfin-covers")
async def start_jellyfin_covers(session: SessionDep, admin: AdminUser) -> dict[str, object]:
    """Queue the pass that gives Jellyfin the album covers it is missing."""
    if _job_running(session, queue.JELLYFIN_COVERS):
        return {"queued": False, "message": "the cover repair is already running"}
    queue.enqueue(session, queue.JELLYFIN_COVERS, priority=3)
    return {"queued": True}


@router.post("/jellyfin-metadata")
async def start_jellyfin_metadata(session: SessionDep, admin: AdminUser) -> dict[str, object]:
    """Queue the pass that makes Jellyfin agree with the tags on disk."""
    if _job_running(session, queue.JELLYFIN_METADATA):
        return {"queued": False, "message": "the metadata alignment is already running"}
    queue.enqueue(session, queue.JELLYFIN_METADATA, priority=3)
    return {"queued": True}


@router.get("/albums", response_model=MetadataListResponse)
async def list_albums(
    session: SessionDep,
    admin: AdminUser,
    issue: str | None = Query(default=None),
    state: str = Query(default=MetadataState.OPEN),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> MetadataListResponse:
    conditions = []
    if state != "any":
        conditions.append(MetadataAlbum.state == state)
    if issue:
        if issue not in MetadataIssue.ALL:
            raise HTTPException(status_code=400, detail=f"Unknown issue: {issue}")
        conditions.append(func.cast(MetadataAlbum.issues, String).like(f'%"{issue}"%'))
    if q:
        pattern = f"%{q.strip()}%"
        conditions.append(
            or_(
                MetadataAlbum.album_title.ilike(pattern),
                MetadataAlbum.album_artist.ilike(pattern),
                MetadataAlbum.path.ilike(pattern),
            )
        )

    statement = select(MetadataAlbum)
    count_statement = select(func.count()).select_from(MetadataAlbum)
    for condition in conditions:
        statement = statement.where(condition)
        count_statement = count_statement.where(condition)

    total = session.execute(count_statement).scalar() or 0
    rows = (
        session.execute(
            statement.order_by(
                MetadataAlbum.album_artist.asc(), MetadataAlbum.album_title.asc()
            )
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )
    return MetadataListResponse(
        count=total, offset=offset, items=[_to_out(row) for row in rows]
    )


@router.get("/artists")
async def list_artists(session: SessionDep, admin: AdminUser) -> list[str]:
    """Album artists having at least one open issue, for the filter box."""
    rows = session.execute(
        select(distinct(MetadataAlbum.album_artist))
        .where(MetadataAlbum.state == MetadataState.OPEN)
        .order_by(MetadataAlbum.album_artist.asc())
    ).scalars()
    return [name for name in rows if name]


@router.get("/albums/{album_id}", response_model=MetadataAlbumDetail)
async def album_detail(album_id: int, session: SessionDep, admin: AdminUser) -> MetadataAlbumDetail:
    row = _load(session, album_id)
    payload = MetadataAlbumDetail.model_validate(row)
    payload.cover_url = _to_out(row).cover_url
    return payload


@router.post("/albums/{album_id}/search", response_model=list[MetadataProposalOut])
async def search_candidates(
    album_id: int,
    session: SessionDep,
    admin: AdminUser,
    q: str | None = Query(default=None, max_length=300),
) -> list[MetadataProposalOut]:
    """Ask MusicBrainz what this folder could be."""
    row = _load(session, album_id)
    if q:
        # A free text override lets an administrator fix a badly named folder.
        row = MetadataAlbum(
            path=row.path,
            album_artist="",
            album_title=q.strip(),
            track_count=row.track_count,
        )
    try:
        proposals = await metadata.propose_from_text(session, row)
    except metadata.MetadataError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ServiceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message) from exc
    return [_proposal_out(item) for item in proposals]


@router.post("/albums/{album_id}/fingerprint", response_model=list[MetadataProposalOut])
async def fingerprint_album(
    album_id: int, session: SessionDep, admin: AdminUser
) -> list[MetadataProposalOut]:
    """Identify the album by its audio, the way Picard does."""
    row = _load(session, album_id)
    if not acoustid.available():
        raise HTTPException(
            status_code=400,
            detail="fpcalc is missing from this image: rebuild it to enable fingerprinting",
        )
    try:
        proposals = await metadata.propose_from_acoustid(session, row)
    except metadata.MetadataError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [_proposal_out(item) for item in proposals]


def _proposal_out(proposal: metadata.Proposal) -> MetadataProposalOut:
    payload = MetadataProposalOut(
        release_group_mbid=proposal.release_group_mbid,
        release_mbid=proposal.release_mbid,
        artist=proposal.artist,
        title=proposal.title,
        year=proposal.year,
        track_count=proposal.track_count,
        score=proposal.score,
        source=proposal.source,
        details=proposal.details,
    )
    payload.cover_url = catalog.cover_url(
        proposal.release_group_mbid, proposal.release_mbid or None
    )
    return payload


def read_reference(text: str) -> tuple[str, str, bool]:
    """Read a pasted MusicBrainz URL or identifier.

    Returns the release group, the release, and whether the reading is a guess:
    a bare identifier looks the same whichever entity it names, so the caller
    has to try both rather than assume, as an earlier version did.
    """
    found = MBID_RE.search(text or "")
    if not found:
        raise ValueError("No MusicBrainz identifier found in this text")
    mbid = found.group(0)
    if "/release-group/" in text:
        return mbid, "", False
    if "/release/" in text:
        return "", mbid, False
    return mbid, "", True


@router.post("/albums/{album_id}/match", response_model=MetadataAlbumDetail)
async def choose_match(
    album_id: int, payload: MetadataMatchRequest, session: SessionDep, admin: AdminUser
) -> MetadataAlbumDetail:
    """Attach a MusicBrainz release to the folder, without writing anything."""
    row = _load(session, album_id)

    group_mbid = payload.release_group_mbid.strip()
    release_mbid = payload.release_mbid.strip()
    ambiguous = False

    if payload.reference and not (group_mbid or release_mbid):
        try:
            group_mbid, release_mbid, ambiguous = read_reference(payload.reference)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not (group_mbid or release_mbid):
        raise HTTPException(status_code=400, detail="A release or release group is required")

    async def resolve(group: str, release: str) -> metadata.Proposal:
        return await metadata.resolve_release(
            session, row, release_group_mbid=group, release_mbid=release
        )

    try:
        try:
            proposal = await resolve(group_mbid, release_mbid)
        except (metadata.MetadataError, ServiceError):
            if not ambiguous:
                raise
            proposal = await resolve("", group_mbid)
    except metadata.MetadataError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ServiceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message) from exc

    metadata.store_proposal(session, row, proposal)
    return await album_detail(album_id, session, admin)


@router.get("/albums/{album_id}/plan", response_model=MetadataPlanOut)
async def preview_changes(album_id: int, session: SessionDep, admin: AdminUser) -> MetadataPlanOut:
    """Simulation: exactly what would be written, tag by tag."""
    row = _load(session, album_id)
    try:
        plan = await metadata.build_plan(session, row)
    except metadata.MetadataError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ServiceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message) from exc

    return MetadataPlanOut(
        release_mbid=plan.release_mbid,
        release_group_mbid=plan.release_group_mbid,
        artist=plan.artist,
        album=plan.album,
        year=plan.year,
        track_count=plan.track_count,
        files=[
            {
                "name": change.name,
                "path": change.path,
                "before": change.before,
                "after": change.after,
                "changed": change.changed,
                "repeated": change.repeated,
            }
            for change in plan.files
        ],
        warnings=plan.warnings,
        unmatched=plan.unmatched,
        cover_source=plan.cover_source,
    )


@router.post("/albums/{album_id}/apply", response_model=MetadataApplyOut)
async def apply_changes(album_id: int, session: SessionDep, admin: AdminUser) -> MetadataApplyOut:
    """Write the tags and the cover into the files."""
    row = _load(session, album_id)
    try:
        result = await metadata.apply_plan(session, row)
    except metadata.MetadataError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ServiceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message) from exc

    if not result.written:
        raise HTTPException(
            status_code=400,
            detail="; ".join(result.warnings) or "no file could be written",
        )

    # Jellyfin will not read the corrected files on its own: its default refresh
    # only fills in what is missing. The alignment pass is queued for this album
    # alone, without the uniqueness guard, so correcting ten albums in a row
    # queues ten passes rather than losing nine of them.
    if row.jellyfin_id:
        queue.enqueue(
            session,
            queue.JELLYFIN_METADATA,
            {"album_id": row.id},
            priority=2,
            unique=False,
        )

    return MetadataApplyOut(
        written=result.written,
        cover_written=result.cover_written,
        warnings=result.warnings,
    )


@router.post("/albums/{album_id}/state", response_model=MetadataAlbumOut)
async def set_state(
    album_id: int,
    session: SessionDep,
    admin: AdminUser,
    state: str = Query(pattern="^(open|ignored|resolved)$"),
    note: str = Query(default="", max_length=500),
) -> MetadataAlbumOut:
    row = _load(session, album_id)
    row.state = state
    row.note = note
    row.resolved_at = None if state == MetadataState.OPEN else row.resolved_at
    session.commit()
    return _to_out(row)


@router.post("/jellyfin-refresh")
async def refresh_jellyfin(session: SessionDep, admin: AdminUser) -> dict[str, bool]:
    """Ask Jellyfin to rescan, then refresh Muzikk's own index.

    The usual follow-up once the tags of an unindexed folder were repaired.
    """
    client = JellyfinClient(settings_service.load(session, "jellyfin"))
    if not client.configured or not client.api_key:
        raise HTTPException(status_code=400, detail="Jellyfin is not configured")
    try:
        await client.refresh_library()
    except ServiceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message) from exc
    queue.enqueue(session, queue.LIBRARY_SYNC)
    return {"ok": True}
