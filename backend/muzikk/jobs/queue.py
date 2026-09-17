"""Persistent work queue.

A SQLite table is enough here: the queue is small, the worker runs in the same
process, and surviving a restart matters more than throughput.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from ..models import Job, JobState, utcnow

logger = logging.getLogger(__name__)

PROCESS_REQUEST = "process_request"
RESUME_DOWNLOAD = "resume_download"
LIBRARY_SYNC = "library_sync"
USERS_SYNC = "users_sync"
INDEXERS_SYNC = "indexers_sync"
WATCHLIST_CHECK = "watchlist_check"
WISHLIST_RETRY = "wishlist_retry"
RETRY_FAILED = "retry_failed"
PRUNE_EVENTS = "prune_events"
METADATA_SCAN = "metadata_scan"
ARTWORK_SYNC = "artwork_sync"
JELLYFIN_COVERS = "jellyfin_covers"
JELLYFIN_METADATA = "jellyfin_metadata"


def enqueue(
    session: Session,
    kind: str,
    payload: dict[str, Any] | None = None,
    *,
    run_after: datetime | None = None,
    priority: int = 0,
    request_id: int | None = None,
    unique: bool = True,
) -> Job | None:
    """Add a job, skipping duplicates that are still waiting or already running."""
    per_request = kind in (PROCESS_REQUEST, RESUME_DOWNLOAD)
    if unique and per_request and request_id is not None:
        # One acquisition at a time: a second process_request on the same
        # album would start Soulseek while the torrent is still importing.
        existing = session.execute(
            select(Job).where(
                and_(
                    Job.request_id == request_id,
                    Job.kind.in_((PROCESS_REQUEST, RESUME_DOWNLOAD)),
                    Job.state.in_((JobState.QUEUED, JobState.RUNNING)),
                )
            )
        ).scalars().first()
        if existing is not None:
            return existing
    elif unique and not per_request:
        existing = session.execute(
            select(Job).where(and_(Job.kind == kind, Job.state == JobState.QUEUED))
        ).scalars().first()
        if existing is not None:
            return existing

    job = Job(
        kind=kind,
        payload=payload or {},
        priority=priority,
        request_id=request_id,
        run_after=run_after or utcnow(),
    )
    session.add(job)
    session.commit()
    return job


def claim_next(session: Session) -> Job | None:
    """Take the next runnable job and mark it as running."""
    job = (
        session.execute(
            select(Job)
            .where(Job.state == JobState.QUEUED)
            .where(Job.run_after <= utcnow())
            .order_by(Job.priority.desc(), Job.id.asc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    if job is None:
        return None
    job.state = JobState.RUNNING
    job.started_at = utcnow()
    job.attempts += 1
    session.commit()
    return job


def finish(session: Session, job_id: int, *, error: str | None = None) -> None:
    job = session.get(Job, job_id)
    if job is None:
        return
    job.state = JobState.FAILED if error else JobState.DONE
    job.error = error
    job.finished_at = utcnow()
    session.commit()


def requeue_running(session: Session) -> int:
    """After a restart, put jobs that were running back in the queue."""
    jobs = session.execute(select(Job).where(Job.state == JobState.RUNNING)).scalars().all()
    for job in jobs:
        job.state = JobState.QUEUED
        job.started_at = None
    session.commit()
    return len(jobs)


def prune(session: Session, *, keep: int = 500) -> int:
    """Drop the oldest finished jobs."""
    finished = (
        session.execute(
            select(Job)
            .where(Job.state.in_((JobState.DONE, JobState.FAILED)))
            .order_by(Job.id.desc())
            .offset(keep)
        )
        .scalars()
        .all()
    )
    for job in finished:
        session.delete(job)
    session.commit()
    return len(finished)
