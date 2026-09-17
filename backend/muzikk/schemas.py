"""Pydantic payloads exposed by the HTTP API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------- auth


class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(ORMModel):
    id: int
    jellyfin_user_id: str
    name: str
    is_admin: bool
    is_enabled: bool
    can_request: bool
    can_upgrade: bool
    can_import: bool
    auto_approve: bool | None
    weekly_quota: int
    language: str | None
    last_login_at: datetime | None


class SessionOut(BaseModel):
    token: str
    expires_at: datetime
    user: UserOut
    auto_approve: bool


class UserUpdate(BaseModel):
    is_enabled: bool | None = None
    can_request: bool | None = None
    can_upgrade: bool | None = None
    can_import: bool | None = None
    auto_approve: bool | None = None
    weekly_quota: int | None = None
    is_admin: bool | None = None


# ------------------------------------------------------------------ browsing


class Ownership(BaseModel):
    status: str | None = None
    upgradable: bool = False
    jellyfin_id: str | None = None
    formats: list[str] = Field(default_factory=list)
    path: str | None = None


class AlbumCard(BaseModel):
    release_group_mbid: str
    title: str
    artist: str
    artist_mbid: str | None = None
    year: int | None = None
    primary_type: str | None = None
    secondary_types: list[str] = Field(default_factory=list)
    cover_url: str | None = None
    ownership: Ownership = Field(default_factory=Ownership)
    request_status: str | None = None
    request_id: int | None = None


class SearchResponse(BaseModel):
    count: int
    offset: int
    items: list[AlbumCard]


class TrackOut(BaseModel):
    position: int
    disc: int
    title: str
    length_ms: int | None = None
    recording_mbid: str | None = None
    artist: str | None = None


class ReleaseSummary(BaseModel):
    release_mbid: str
    title: str
    date: str | None = None
    country: str | None = None
    status: str | None = None
    formats: list[str] = Field(default_factory=list)
    track_count: int = 0
    disc_count: int = 1
    label: str | None = None
    is_recommended: bool = False


class AlbumDetail(BaseModel):
    release_group_mbid: str
    title: str
    artist: str
    artist_mbid: str | None = None
    year: int | None = None
    primary_type: str | None = None
    secondary_types: list[str] = Field(default_factory=list)
    genres: list[str] = Field(default_factory=list)
    cover_url: str | None = None
    ownership: Ownership = Field(default_factory=Ownership)
    request_status: str | None = None
    request_id: int | None = None
    selected_release: ReleaseSummary | None = None
    releases: list[ReleaseSummary] = Field(default_factory=list)
    tracks: list[TrackOut] = Field(default_factory=list)


class ArtistOut(BaseModel):
    mbid: str
    name: str
    disambiguation: str | None = None
    country: str | None = None
    type: str | None = None
    genres: list[str] = Field(default_factory=list)
    watched: bool = False
    in_library: bool = False


class LabelOut(BaseModel):
    mbid: str
    name: str
    disambiguation: str | None = None
    country: str | None = None
    type: str | None = None
    label_code: str | None = None
    area: str | None = None
    genres: list[str] = Field(default_factory=list)


class LabelDetail(BaseModel):
    label: LabelOut
    release_groups: list[AlbumCard] = Field(default_factory=list)
    count: int = 0
    offset: int = 0


class LibraryAlbumOut(ORMModel):
    id: int
    jellyfin_id: str
    name: str
    album_artist: str
    year: int | None
    formats: list[str]
    is_lossless: bool
    track_count: int
    genres: list[str]
    release_group_mbid: str | None
    release_mbid: str | None
    image_tag: str | None
    path: str | None


class LibraryResponse(BaseModel):
    count: int
    offset: int
    items: list[LibraryAlbumOut]


class LibraryTrack(BaseModel):
    """One track of a library album, as Jellyfin describes it."""

    jellyfin_id: str
    title: str
    artist: str = ""
    track: int | None = None
    disc: int | None = None
    duration: float | None = None
    container: str = ""


class LibraryAlbumDetail(BaseModel):
    """An album of the library, with no MusicBrainz identity required."""

    album: LibraryAlbumOut
    tracks: list[LibraryTrack]
    # Why the tracklist is empty, when it is.
    tracks_error: str | None = None


# ------------------------------------------------------------------ requests


class RequestCreate(BaseModel):
    release_group_mbid: str
    release_mbid: str | None = None
    is_upgrade: bool = False


class RequestEventOut(ORMModel):
    id: int
    created_at: datetime
    level: str
    stage: str
    message: str
    data: dict[str, Any] | None


class DownloadAttemptOut(ORMModel):
    id: int
    provider_key: str
    provider_label: str
    candidate_title: str
    score: float
    decision: str
    reason: str
    details: dict[str, Any] | None
    created_at: datetime


class DownloadOut(ORMModel):
    id: int
    client: str
    external_id: str
    username: str | None
    state: str
    progress: float
    size: int
    downloaded: int
    speed: int
    eta: int | None
    content_path: str | None


class RequestOut(ORMModel):
    id: int
    user_id: int
    user_name: str | None = None
    release_group_mbid: str
    release_mbid: str | None
    artist_name: str
    album_title: str
    artist_mbid: str | None
    primary_type: str | None
    year: int | None
    track_count: int | None
    status: str
    is_upgrade: bool
    progress: float
    provider_key: str | None
    provider_label: str | None
    error: str | None
    destination_path: str | None
    attempts: int
    retry_after: datetime | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    cover_url: str | None = None


class RequestDetail(RequestOut):
    events: list[RequestEventOut] = Field(default_factory=list)
    attempts_log: list[DownloadAttemptOut] = Field(default_factory=list)
    downloads: list[DownloadOut] = Field(default_factory=list)
    # Only on the detail: the file by file comparison of an upgrade is far too
    # heavy to repeat for every row of the list.
    upgrade_review: dict[str, Any] | None = None


class RequestListResponse(BaseModel):
    count: int
    offset: int
    items: list[RequestOut]


# ------------------------------------------------------------------- extras


class WatchedArtistOut(ORMModel):
    id: int
    artist_mbid: str
    artist_name: str
    scope: str
    last_checked_at: datetime | None
    created_at: datetime
    # Albums of this artist the library is missing, the ignored ones aside.
    missing: int = 0


class WatchCreate(BaseModel):
    artist_mbid: str
    artist_name: str
    scope: Literal["new", "missing"] = "new"


class WatchUpdate(BaseModel):
    scope: Literal["new", "missing"]


class WatchedReleaseOut(BaseModel):
    """A missing album of a followed artist, ready to be drawn as a card."""

    id: int
    watch_id: int
    artist_mbid: str
    artist_name: str
    is_new: bool
    ignored: bool
    first_release_date: str | None
    album: AlbumCard


class WishlistItemOut(ORMModel):
    id: int
    release_group_mbid: str
    artist_name: str
    album_title: str
    artist_mbid: str | None
    year: int | None
    is_active: bool
    attempts: int
    last_attempt_at: datetime | None
    created_at: datetime


class WishlistCreate(BaseModel):
    release_group_mbid: str
    artist_name: str
    album_title: str
    artist_mbid: str | None = None
    year: int | None = None


# -------------------------------------------------------------------- admin


class IndexerOut(ORMModel):
    id: int
    prowlarr_id: int
    name: str
    protocol: str
    privacy: str
    enabled: bool
    priority: int
    min_seeders: int
    supports_music_search: bool


class IndexerUpdate(BaseModel):
    enabled: bool | None = None
    priority: int | None = None
    min_seeders: int | None = None
    privacy: str | None = None


class SettingsPayload(BaseModel):
    model_config = ConfigDict(extra="allow")


class TestResult(BaseModel):
    ok: bool
    message: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class NamingPreviewRequest(BaseModel):
    template: str | None = None


class NamingPreviewOut(BaseModel):
    template: str
    examples: list[str]
    error: str | None = None


class StatsOut(BaseModel):
    users: int
    library_albums: int
    library_lossless: int
    requests_total: int
    requests_pending: int
    requests_active: int
    requests_to_validate: int = 0
    requests_failed: int
    requests_imported: int
    watched_artists: int
    watchlist_missing: int = 0
    wishlist_items: int


class HealthOut(BaseModel):
    status: str
    version: str
    setup_required: bool
    services: dict[str, bool]


# ------------------------------------------------------------------ metadata


class MetadataAlbumOut(ORMModel):
    id: int
    path: str
    jellyfin_id: str | None
    album_artist: str
    album_title: str
    year: int | None
    track_count: int
    formats: list[str]
    issues: list[str]
    state: str
    has_cover: bool
    release_mbid: str | None
    release_group_mbid: str | None
    details: dict[str, Any] = Field(default_factory=dict)
    match_release_group_mbid: str | None
    match_release_mbid: str | None
    match_artist: str
    match_title: str
    match_year: int | None
    match_track_count: int | None
    match_score: float
    match_source: str
    note: str
    scanned_at: datetime | None
    resolved_at: datetime | None
    cover_url: str | None = None


class MetadataAlbumDetail(MetadataAlbumOut):
    tracks: list[dict[str, Any]] = Field(default_factory=list)
    match_details: dict[str, Any] | None = None


class MetadataListResponse(BaseModel):
    count: int
    offset: int
    items: list[MetadataAlbumOut]


class MetadataScanFailure(BaseModel):
    path: str = ""
    error: str = ""


class MetadataScanReport(BaseModel):
    """What the last walk of the library saw, folder by folder."""

    root: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None
    min_tracks: int = 0
    directories: int = 0
    audio_files: int = 0
    # Album folders found on disk, then how many of them made it to the table.
    folders: int = 0
    analysed: int = 0
    below_min_tracks: int = 0
    unreadable: int = 0
    failed: int = 0
    failures: list[MetadataScanFailure] = Field(default_factory=list)


class ArtworkSyncReport(BaseModel):
    """What the cover.jpg / folder.jpg pass did to the library."""

    root: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None
    folders: int = 0
    # Folders that already had both names, then the three ways of fixing one.
    already: int = 0
    copied: int = 0
    extracted: int = 0
    without_art: int = 0
    failed: int = 0
    failures: list[MetadataScanFailure] = Field(default_factory=list)


class JellyfinCoverReport(BaseModel):
    """What the pass filling in the Jellyfin covers found and changed."""

    started_at: datetime | None = None
    finished_at: datetime | None = None
    albums: int = 0
    without_cover: int = 0
    refreshed: int = 0
    # Albums Jellyfin picked up on its own once asked, then those we had to push.
    fixed_by_refresh: int = 0
    uploaded: int = 0
    no_source: int = 0
    failed: int = 0
    failures: list[MetadataScanFailure] = Field(default_factory=list)


class JellyfinMetadataReport(BaseModel):
    """What the pass aligning Jellyfin on the disk tags found and changed."""

    started_at: datetime | None = None
    finished_at: datetime | None = None
    albums: int = 0
    compared: int = 0
    stale: int = 0
    refreshed: int = 0
    # Albums Jellyfin corrected on its own once asked, then those we wrote into.
    fixed_by_refresh: int = 0
    albums_written: int = 0
    tracks_written: int = 0
    unreadable: int = 0
    left: int = 0
    # Whether asking the server to reread the files proved pointless.
    refresh_ignored: bool = False
    failed: int = 0
    failures: list[MetadataScanFailure] = Field(default_factory=list)
    # The albums found out of step, with the fields at fault.
    samples: list[MetadataScanFailure] = Field(default_factory=list)


class MetadataSummary(BaseModel):
    total: int
    open: int
    ignored: int
    resolved: int
    issues: dict[str, int]
    last_scan_at: datetime | None = None
    library_dir: str
    library_readable: bool
    fingerprinting_available: bool
    acoustid_configured: bool
    scan_running: bool = False
    last_error: str = ""
    library_albums: int = 0
    last_scan: MetadataScanReport | None = None
    artwork_running: bool = False
    artwork_error: str = ""
    last_artwork_sync: ArtworkSyncReport | None = None
    jellyfin_covers_running: bool = False
    jellyfin_covers_error: str = ""
    last_jellyfin_covers: JellyfinCoverReport | None = None
    jellyfin_meta_running: bool = False
    jellyfin_meta_error: str = ""
    last_jellyfin_meta: JellyfinMetadataReport | None = None


class MetadataProposalOut(BaseModel):
    release_group_mbid: str
    release_mbid: str = ""
    artist: str = ""
    title: str = ""
    year: int | None = None
    track_count: int = 0
    score: float = 0.0
    source: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    cover_url: str | None = None


class MetadataMatchRequest(BaseModel):
    release_group_mbid: str = ""
    release_mbid: str = ""
    # A MusicBrainz URL pasted by an administrator is accepted as is.
    reference: str = ""


class MetadataFileChange(BaseModel):
    name: str
    path: str
    before: dict[str, Any]
    after: dict[str, Any]
    changed: list[str]
    repeated: dict[str, list[str]] = Field(default_factory=dict)


class MetadataPlanOut(BaseModel):
    release_mbid: str
    release_group_mbid: str
    artist: str
    album: str
    year: int | None = None
    track_count: int
    files: list[MetadataFileChange]
    warnings: list[str] = Field(default_factory=list)
    unmatched: list[str] = Field(default_factory=list)
    cover_source: str = ""


class MetadataApplyOut(BaseModel):
    written: int
    cover_written: bool
    warnings: list[str] = Field(default_factory=list)


# -------------------------------------------------------------------- player


class PlayableTrack(BaseModel):
    # Empty on a thirty second extract: there is no library item behind it.
    jellyfin_id: str = ""
    title: str
    artist: str = ""
    album: str = ""
    album_id: str | None = None
    track: int | None = None
    disc: int | None = None
    duration: float | None = None
    container: str = ""
    cover_url: str | None = None
    # Which service the extract comes from, when this is one.
    preview: str | None = None
    stream_url: str


class TrackSearchResult(BaseModel):
    """A track found either in the library or in MusicBrainz."""

    title: str
    artist: str = ""
    album: str = ""
    year: int | None = None
    duration: float | None = None
    owned: bool = False
    # Present for a library track, so it can be played straight away.
    jellyfin_id: str | None = None
    album_jellyfin_id: str | None = None
    # Present for a MusicBrainz recording, so its album can be requested.
    release_group_mbid: str | None = None
    recording_mbid: str | None = None
    cover_url: str | None = None


class TrackSearchResponse(BaseModel):
    count: int
    items: list[TrackSearchResult]


# ----------------------------------------------------------------- playlists


class PlaylistOut(BaseModel):
    id: str
    name: str
    track_count: int = 0
    can_delete: bool = False
    cover_url: str | None = None


class PlaylistTrack(PlayableTrack):
    # The same track can sit twice in a playlist, so removing one takes the
    # identifier of the entry rather than the identifier of the track.
    playlist_item_id: str = ""


class PlaylistCreate(BaseModel):
    name: str
    album_id: str | None = None
    track_ids: list[str] = Field(default_factory=list)


class PlaylistAdd(BaseModel):
    album_id: str | None = None
    track_ids: list[str] = Field(default_factory=list)


class PlaylistChange(BaseModel):
    playlist_id: str
    name: str
    added: int = 0


# -------------------------------------------------------------- local import


class LocalImportTrackOut(BaseModel):
    name: str
    relative: str
    title: str = ""
    artist: str = ""
    album: str = ""
    track: int | None = None
    disc: int | None = None
    extension: str = ""


class LocalImportOwnershipOut(BaseModel):
    status: str | None = None
    upgradable: bool = False
    blocked: bool = False
    reason: str = ""
    path: str | None = None
    is_lossless: bool = False
    formats: list[str] = Field(default_factory=list)
    jellyfin_id: str | None = None


class LocalImportSessionOut(BaseModel):
    id: str
    status: str
    artist: str = ""
    album: str = ""
    year: str = ""
    track_count: int = 0
    is_lossless: bool = False
    has_cover: bool = False
    cover_url: str | None = None
    mode: str = ""
    release_mbid: str = ""
    release_group_mbid: str = ""
    tracks: list[LocalImportTrackOut] = Field(default_factory=list)
    proposals: list[MetadataProposalOut] = Field(default_factory=list)
    ownership: LocalImportOwnershipOut | None = None
    warnings: list[str] = Field(default_factory=list)
    destination: str | None = None
    files: list[str] = Field(default_factory=list)


class LocalImportSearchRequest(BaseModel):
    query: str = ""


class LocalImportMatchRequest(BaseModel):
    release_group_mbid: str = ""
    release_mbid: str = ""
    reference: str = ""


class LocalImportManualRequest(BaseModel):
    artist: str
    album: str
    year: str = ""


class LocalImportCommitRequest(BaseModel):
    confirm_upgrade: bool = False
