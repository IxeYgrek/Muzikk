"""SQLAlchemy models.

Statuses and kinds are plain strings rather than SQL enums: SQLite cannot alter
enum types, and using strings keeps future migrations trivial.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class RequestStatus:
    """States of the acquisition state machine."""

    PENDING = "pending"          # waiting for admin approval
    APPROVED = "approved"        # queued, waiting for a worker
    SEARCHING = "searching"      # querying providers
    MATCHED = "matched"          # a candidate was accepted
    DOWNLOADING = "downloading"
    VERIFYING = "verifying"
    TAGGING = "tagging"
    IMPORTING = "importing"
    # An upgrade whose files are in place, waiting for someone to confirm the
    # new copy is really the album before the old one is deleted.
    AWAITING_VALIDATION = "awaiting_validation"
    IMPORTED = "imported"
    FAILED = "failed"
    REJECTED = "rejected"        # refused by an admin
    CANCELLED = "cancelled"

    ACTIVE = (SEARCHING, MATCHED, DOWNLOADING, VERIFYING, TAGGING, IMPORTING)
    TERMINAL = (IMPORTED, REJECTED, CANCELLED)


class JobState:
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class MetadataIssue:
    """Anomalies the library analysis can report on an album folder."""

    MISSING_MBID = "missing_mbid"          # no MusicBrainz identifier in the tags
    PROBABLE_MATCH = "probable_match"      # owned, but only recognised by resemblance
    MISSING_COVER = "missing_cover"        # neither cover file nor embedded picture
    NOT_IN_JELLYFIN = "not_in_jellyfin"    # on disk, absent from the Jellyfin index
    DUPLICATE = "duplicate"                # same album sitting in several folders
    INCOMPLETE_TAGS = "incomplete_tags"    # album artist, year, genre or numbering missing
    DUPLICATE_TAGS = "duplicate_tags"      # the same value written twice in one tag

    ALL = (
        MISSING_MBID,
        PROBABLE_MATCH,
        MISSING_COVER,
        NOT_IN_JELLYFIN,
        DUPLICATE,
        INCOMPLETE_TAGS,
        DUPLICATE_TAGS,
    )


class MetadataState:
    OPEN = "open"
    RESOLVED = "resolved"
    IGNORED = "ignored"


class AppSetting(Base):
    __tablename__ = "app_setting"

    section: Mapped[str] = mapped_column(String(64), primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class User(Base):
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Exactly one of the two is set, depending on the mode the install was
    # built in: an account comes either from Jellyfin or from Muzikk itself.
    jellyfin_user_id: Mapped[str | None] = mapped_column(
        String(64), unique=True, index=True, nullable=True
    )
    username: Mapped[str | None] = mapped_column(
        String(64), unique=True, index=True, nullable=True
    )
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    can_request: Mapped[bool] = mapped_column(Boolean, default=True)
    # Replace an owned lossy album with a lossless download (MP3 to FLAC).
    can_upgrade: Mapped[bool] = mapped_column(Boolean, default=False)
    # Drop an album folder onto the home page and tag it into the library.
    can_import: Mapped[bool] = mapped_column(Boolean, default=False)
    # None means "inherit the global requirement" set in the general settings.
    auto_approve: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    # 0 means unlimited.
    weekly_quota: Mapped[int] = mapped_column(Integer, default=0)
    language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    primary_image_tag: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Jellyfin session token, encrypted at rest, so playback runs as this user.
    jellyfin_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    requests: Mapped[list[Request]] = relationship(
        back_populates="user", cascade="all, delete-orphan", foreign_keys="Request.user_id"
    )


class Request(Base):
    __tablename__ = "request"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)

    release_group_mbid: Mapped[str] = mapped_column(String(64), index=True)
    release_mbid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    artist_mbid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    artist_name: Mapped[str] = mapped_column(String(500))
    album_title: Mapped[str] = mapped_column(String(500))
    primary_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    track_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[str] = mapped_column(String(32), default=RequestStatus.PENDING, index=True)
    is_upgrade: Mapped[bool] = mapped_column(Boolean, default=False)
    replaces_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Both sides of an upgrade, written at import time: what the old folder
    # held, what the new one holds, and which files the confirmation deletes.
    upgrade_review: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)

    attempts: Mapped[int] = mapped_column(Integer, default=0)
    retry_after: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    provider_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    destination_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Providers already tried during the current run, to avoid loops.
    exhausted_providers: Mapped[list[str]] = mapped_column(JSON, default=list)

    approved_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped[User] = relationship(back_populates="requests", foreign_keys=[user_id])
    events: Mapped[list[RequestEvent]] = relationship(
        back_populates="request", cascade="all, delete-orphan", order_by="RequestEvent.id"
    )
    attempts_log: Mapped[list[DownloadAttempt]] = relationship(
        back_populates="request", cascade="all, delete-orphan", order_by="DownloadAttempt.id"
    )
    downloads: Mapped[list[Download]] = relationship(
        back_populates="request", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_request_status_created", "status", "created_at"),
    )


class RequestEvent(Base):
    __tablename__ = "request_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("request.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    level: Mapped[str] = mapped_column(String(16), default="info")
    stage: Mapped[str] = mapped_column(String(32), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    request: Mapped[Request] = relationship(back_populates="events")


class DownloadAttempt(Base):
    __tablename__ = "download_attempt"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("request.id", ondelete="CASCADE"), index=True)
    provider_key: Mapped[str] = mapped_column(String(64))
    provider_label: Mapped[str] = mapped_column(String(255), default="")
    candidate_title: Mapped[str] = mapped_column(Text, default="")
    score: Mapped[float] = mapped_column(Float, default=0.0)
    decision: Mapped[str] = mapped_column(String(16), default="rejected")
    reason: Mapped[str] = mapped_column(Text, default="")
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    request: Mapped[Request] = relationship(back_populates="attempts_log")


class Download(Base):
    __tablename__ = "download"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("request.id", ondelete="CASCADE"), index=True)
    client: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(String(255), default="")
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    state: Mapped[str] = mapped_column(String(32), default="queued")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    size: Mapped[int] = mapped_column(Integer, default=0)
    downloaded: Mapped[int] = mapped_column(Integer, default=0)
    speed: Mapped[int] = mapped_column(Integer, default=0)
    eta: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    request: Mapped[Request] = relationship(back_populates="downloads")


class LibraryAlbum(Base):
    __tablename__ = "library_album"

    id: Mapped[int] = mapped_column(primary_key=True)
    # The album identifier the whole application passes around: a Jellyfin
    # GUID in Jellyfin mode, a "local:" key derived from the folder path in
    # local mode. Nothing downstream ever reads it, only compares it, which is
    # what lets both modes share every table and every route below this line.
    jellyfin_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(500))
    album_artist: Mapped[str] = mapped_column(String(500), default="")
    album_artist_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    release_mbid: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    release_group_mbid: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    artist_mbid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fuzzy_key: Mapped[str] = mapped_column(String(600), default="", index=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    path: Mapped[str | None] = mapped_column(Text, nullable=True)
    track_count: Mapped[int] = mapped_column(Integer, default=0)
    formats: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_lossless: Mapped[bool] = mapped_column(Boolean, default=False)
    bit_depth: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sample_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    genres: Mapped[list[str]] = mapped_column(JSON, default=list)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    date_created: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    image_tag: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class LibraryArtist(Base):
    __tablename__ = "library_artist"

    id: Mapped[int] = mapped_column(primary_key=True)
    jellyfin_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(500))
    mbid: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    fuzzy_key: Mapped[str] = mapped_column(String(600), default="", index=True)
    album_count: Mapped[int] = mapped_column(Integer, default=0)
    image_tag: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class LibraryTrack(Base):
    """One audio file of the library, as the local scanner read it.

    Filled by the local mode only. In Jellyfin mode the tracklist of an album
    is asked to Jellyfin, which knows its own library better than a folder
    listing ever could, so the table simply stays empty.
    """

    __tablename__ = "library_track"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    album_item_id: Mapped[str] = mapped_column(String(64), index=True)
    path: Mapped[str] = mapped_column(String(1000), unique=True, index=True)

    title: Mapped[str] = mapped_column(String(500), default="")
    artist: Mapped[str] = mapped_column(String(500), default="")
    album: Mapped[str] = mapped_column(String(500), default="")
    track: Mapped[int | None] = mapped_column(Integer, nullable=True)
    disc: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    container: Mapped[str] = mapped_column(String(16), default="")
    is_lossless: Mapped[bool] = mapped_column(Boolean, default=False)
    recording_mbid: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Size and modification time let a rescan skip every file that did not
    # move, which is what turns a full walk into a few seconds.
    size: Mapped[int] = mapped_column(Integer, default=0)
    mtime: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (Index("ix_library_track_album_order", "album_item_id", "disc", "track"),)


class MetadataAlbum(Base):
    """One album folder on disk, with whatever the analysis found wrong with it.

    Keyed by path rather than by Jellyfin identifier on purpose: the folders
    Jellyfin failed to index are precisely the ones worth reporting.
    """

    __tablename__ = "metadata_album"

    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(String(1000), unique=True, index=True)
    jellyfin_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    album_artist: Mapped[str] = mapped_column(String(500), default="")
    album_title: Mapped[str] = mapped_column(String(500), default="")
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    track_count: Mapped[int] = mapped_column(Integer, default=0)
    formats: Mapped[list[str]] = mapped_column(JSON, default=list)
    fuzzy_key: Mapped[str] = mapped_column(String(600), default="", index=True)

    issues: Mapped[list[str]] = mapped_column(JSON, default=list)
    state: Mapped[str] = mapped_column(String(16), default=MetadataState.OPEN, index=True)
    has_cover: Mapped[bool] = mapped_column(Boolean, default=False)
    release_mbid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    release_group_mbid: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Snapshot of the per-file tags, so the before/after view needs no disk access.
    tracks: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    # Issue specific payload: missing tag names, sibling folders of a duplicate.
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    match_release_group_mbid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    match_release_mbid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    match_artist: Mapped[str] = mapped_column(String(500), default="")
    match_title: Mapped[str] = mapped_column(String(500), default="")
    match_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    match_track_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    match_score: Mapped[float] = mapped_column(Float, default=0.0)
    match_source: Mapped[str] = mapped_column(String(32), default="")
    match_details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    note: Mapped[str] = mapped_column(Text, default="")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    scanned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (Index("ix_metadata_state_artist", "state", "album_artist"),)


class WatchScope:
    """How much of a followed artist Muzikk is asked to keep an eye on."""

    NEW = "new"
    MISSING = "missing"
    ALL = (NEW, MISSING)


class WatchedArtist(Base):
    __tablename__ = "watched_artist"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    artist_mbid: Mapped[str] = mapped_column(String(64), index=True)
    artist_name: Mapped[str] = mapped_column(String(500))
    # Either the recent releases only, or everything the library does not hold.
    scope: Mapped[str] = mapped_column(String(16), default=WatchScope.NEW)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (UniqueConstraint("user_id", "artist_mbid", name="uq_watch_user_artist"),)


class WatchedRelease(Base):
    """An album of a followed artist that the library does not hold.

    Following an artist never downloads anything: the check writes these rows,
    the Follow tab shows them, and each one waits for a click.
    """

    __tablename__ = "watched_release"

    id: Mapped[int] = mapped_column(primary_key=True)
    watch_id: Mapped[int] = mapped_column(
        ForeignKey("watched_artist.id", ondelete="CASCADE"), index=True
    )
    release_group_mbid: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(500))
    primary_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_release_date: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Recent enough to count as a new release, whatever the chosen scope.
    is_new: Mapped[bool] = mapped_column(Boolean, default=False)
    # Hidden by the follower, and kept that way across checks.
    ignored: Mapped[bool] = mapped_column(Boolean, default=False)
    # The release group as MusicBrainz described it, so the card can be drawn
    # again without asking for it a second time.
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("watch_id", "release_group_mbid", name="uq_watched_release"),
    )


class WishlistItem(Base):
    __tablename__ = "wishlist_item"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    release_group_mbid: Mapped[str] = mapped_column(String(64), index=True)
    artist_name: Mapped[str] = mapped_column(String(500))
    album_title: Mapped[str] = mapped_column(String(500))
    artist_mbid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "release_group_mbid", name="uq_wishlist_user_release_group"),
    )


class Indexer(Base):
    """Local mirror of a Prowlarr indexer with Muzikk specific settings."""

    __tablename__ = "indexer"

    id: Mapped[int] = mapped_column(primary_key=True)
    prowlarr_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    protocol: Mapped[str] = mapped_column(String(32), default="torrent")
    privacy: Mapped[str] = mapped_column(String(32), default="public")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=50)
    min_seeders: Mapped[int] = mapped_column(Integer, default=1)
    supports_music_search: Mapped[bool] = mapped_column(Boolean, default=False)
    categories: Mapped[list[int]] = mapped_column(JSON, default=list)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Job(Base):
    __tablename__ = "job"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    state: Mapped[str] = mapped_column(String(16), default=JobState.QUEUED, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    request_id: Mapped[int | None] = mapped_column(
        ForeignKey("request.id", ondelete="CASCADE"), nullable=True, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    run_after: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (Index("ix_job_state_run_after", "state", "run_after"),)
