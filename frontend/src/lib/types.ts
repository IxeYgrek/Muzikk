export type Ownership = {
  status: 'owned' | 'probable' | null
  upgradable: boolean
  jellyfin_id: string | null
  formats: string[]
  path: string | null
}

export type AlbumCard = {
  release_group_mbid: string
  title: string
  artist: string
  artist_mbid: string | null
  year: number | null
  primary_type: string | null
  secondary_types: string[]
  cover_url: string | null
  ownership: Ownership
  request_status: string | null
  request_id: number | null
}

export type SearchResponse = {
  count: number
  offset: number
  items: AlbumCard[]
}

/** What a suggestion carries on top of the card itself. */
export type Suggested = {
  id: number
  /** The artist it was derived from: the reason shown on the card. */
  seed_name: string
  sources: string[]
}

export type SuggestedAlbum = AlbumCard & Suggested
export type SuggestedArtist = Artist & Suggested

export type RecommendationResponse = {
  /** Missing from the library, so these can be requested. */
  items: SuggestedAlbum[]
  artists: SuggestedArtist[]
  /** Already owned: played rather than downloaded. */
  rediscover: SuggestedAlbum[]
  /** Just out, by artists this listener plays. */
  fresh: SuggestedAlbum[]
  /** 'listenbrainz', 'lastfm', or 'library' when no account is connected. */
  sources: string[]
  computed_at: string | null
  running: boolean
  connected: boolean
  available: boolean
}

export type ListeningAccounts = {
  listenbrainz_enabled: boolean
  listenbrainz_user: string | null
  listenbrainz_connected: boolean
  lastfm_enabled: boolean
  lastfm_user: string | null
  lastfm_connected: boolean
  /** False until an administrator has registered a Last.fm application. */
  lastfm_can_authorize: boolean
}

export type LastfmAuthStart = {
  token: string
  url: string
}

export type Track = {
  position: number
  disc: number
  title: string
  length_ms: number | null
  recording_mbid: string | null
  artist: string | null
}

export type ReleaseSummary = {
  release_mbid: string
  title: string
  date: string | null
  country: string | null
  status: string | null
  formats: string[]
  track_count: number
  disc_count: number
  label: string | null
  is_recommended: boolean
}

export type AlbumDetail = AlbumCard & {
  genres: string[]
  selected_release: ReleaseSummary | null
  releases: ReleaseSummary[]
  tracks: Track[]
}

export type Artist = {
  mbid: string
  name: string
  disambiguation: string | null
  country: string | null
  type: string | null
  genres: string[]
  watched: boolean
  in_library: boolean
}

export type ArtistDetail = {
  artist: Artist
  release_groups: AlbumCard[]
  count: number
}

export type Label = {
  mbid: string
  name: string
  disambiguation: string | null
  country: string | null
  type: string | null
  label_code: string | null
  area: string | null
  genres: string[]
}

export type LabelDetail = {
  label: Label
  release_groups: AlbumCard[]
  count: number
  offset: number
}

/** Which backend owns the accounts and the library on this installation. */
export type Mode = 'jellyfin' | 'local'

export type User = {
  id: number
  /** Set in Jellyfin mode only; `username` takes its place in local mode. */
  jellyfin_user_id: string | null
  username: string | null
  name: string
  is_admin: boolean
  is_enabled: boolean
  can_request: boolean
  /** Ask for one track rather than the album holding it. Off by default. */
  can_request_track: boolean
  can_upgrade: boolean
  can_import: boolean
  auto_approve: boolean | null
  weekly_quota: number
  language: string | null
  last_login_at: string | null
}

export type Session = {
  token: string
  expires_at: string
  user: User
  auto_approve: boolean
}

export type LibraryAlbum = {
  id: number
  jellyfin_id: string
  name: string
  album_artist: string
  year: number | null
  formats: string[]
  is_lossless: boolean
  track_count: number
  genres: string[]
  label: string | null
  release_group_mbid: string | null
  release_mbid: string | null
  image_tag: string | null
  path: string | null
}

export type LibraryTrack = {
  jellyfin_id: string
  title: string
  artist: string
  track: number | null
  disc: number | null
  duration: number | null
  container: string
}

export type LibraryAlbumDetail = {
  album: LibraryAlbum
  tracks: LibraryTrack[]
  tracks_error: string | null
}

export type LibraryResponse = {
  count: number
  offset: number
  items: LibraryAlbum[]
}

export type RequestStatus =
  | 'pending'
  | 'approved'
  | 'searching'
  | 'matched'
  | 'downloading'
  | 'verifying'
  | 'tagging'
  | 'importing'
  | 'awaiting_validation'
  | 'imported'
  | 'failed'
  | 'rejected'
  | 'cancelled'

export type AlbumRequest = {
  id: number
  user_id: number
  user_name: string | null
  release_group_mbid: string
  release_mbid: string | null
  artist_name: string
  album_title: string
  artist_mbid: string | null
  primary_type: string | null
  year: number | null
  track_count: number | null
  status: RequestStatus
  is_upgrade: boolean
  progress: number
  provider_key: string | null
  provider_label: string | null
  error: string | null
  destination_path: string | null
  attempts: number
  retry_after: string | null
  created_at: string
  updated_at: string
  completed_at: string | null
  cover_url: string | null
}

export type RequestEvent = {
  id: number
  created_at: string
  level: string
  stage: string
  message: string
  data: Record<string, unknown> | null
}

export type DownloadAttempt = {
  id: number
  provider_key: string
  provider_label: string
  candidate_title: string
  score: number
  decision: string
  reason: string
  details: Record<string, unknown> | null
  created_at: string
}

export type Download = {
  id: number
  client: string
  external_id: string
  username: string | null
  state: string
  progress: number
  size: number
  downloaded: number
  speed: number
  eta: number | null
  content_path: string | null
}

export type UpgradeFile = {
  path: string
  name: string
  format: string
  title: string
  track: number | null
  duration: number | null
  bitrate: number | null
  bit_depth: number | null
  sample_rate: number | null
  size: number
}

export type UpgradeReview = {
  old_path: string
  new_path: string | null
  same_folder: boolean
  old_files: UpgradeFile[]
  new_files: UpgradeFile[]
  remove: string[]
  new_dirs: string[]
  resolved?: 'accepted' | 'refused'
  removed?: string[]
}

export type RequestDetail = AlbumRequest & {
  events: RequestEvent[]
  attempts_log: DownloadAttempt[]
  downloads: Download[]
  upgrade_review: UpgradeReview | null
}

export type RequestListResponse = {
  count: number
  offset: number
  items: AlbumRequest[]
}

export type ActivityItem = {
  id: number
  artist: string
  album: string
  status: RequestStatus
  progress: number
  provider: string | null
  cover_url: string | null
  error: string | null
  speed: number
  eta: number | null
  size: number
  downloaded: number
  client: string | null
}

export type ActivitySnapshot = {
  items: ActivityItem[]
  counts: { pending: number; active: number; failed: number }
}

export type Stats = {
  users: number
  library_albums: number
  library_lossless: number
  requests_total: number
  requests_pending: number
  requests_active: number
  requests_to_validate: number
  requests_failed: number
  requests_imported: number
  watched_artists: number
  watchlist_missing: number
  wishlist_items: number
}

export type WatchScope = 'new' | 'missing'

export type WatchedArtist = {
  id: number
  artist_mbid: string
  artist_name: string
  scope: WatchScope
  last_checked_at: string | null
  created_at: string
  missing: number
}

export type WatchedRelease = {
  id: number
  watch_id: number
  artist_mbid: string
  artist_name: string
  is_new: boolean
  ignored: boolean
  first_release_date: string | null
  album: AlbumCard
}

export type WishlistItem = {
  id: number
  release_group_mbid: string
  artist_name: string
  album_title: string
  artist_mbid: string | null
  year: number | null
  is_active: boolean
  attempts: number
  last_attempt_at: string | null
  created_at: string
}

export type Indexer = {
  id: number
  prowlarr_id: number
  name: string
  protocol: string
  privacy: string
  enabled: boolean
  priority: number
  min_seeders: number
  supports_music_search: boolean
}

export type TestResult = {
  ok: boolean
  message: string
  details: Record<string, unknown>
}

export type MetadataIssueKind =
  | 'missing_mbid'
  | 'probable_match'
  | 'missing_cover'
  | 'not_in_jellyfin'
  | 'duplicate'
  | 'incomplete_tags'
  | 'duplicate_tags'

/** Tags holding the same value twice, as reported by the analysis. */
export type DuplicatedTags = {
  fields: string[]
  files: { name: string; tags: Record<string, string[]> }[]
  file_count: number
}

export type MetadataAlbum = {
  id: number
  path: string
  jellyfin_id: string | null
  album_artist: string
  album_title: string
  year: number | null
  track_count: number
  formats: string[]
  issues: MetadataIssueKind[]
  state: 'open' | 'resolved' | 'ignored'
  has_cover: boolean
  release_mbid: string | null
  release_group_mbid: string | null
  details: {
    missing_tags?: string[]
    duplicate_of?: string[]
    unreadable_files?: string[]
    scan_error?: string
    duplicated_tags?: DuplicatedTags
  }
  match_release_group_mbid: string | null
  match_release_mbid: string | null
  match_artist: string
  match_title: string
  match_year: number | null
  match_track_count: number | null
  match_score: number
  match_source: string
  note: string
  scanned_at: string | null
  resolved_at: string | null
  cover_url: string | null
}

export type MetadataTrack = {
  name: string
  path: string
  title: string
  artist: string
  album: string
  albumartist: string
  track: number | null
  disc: number | null
  date: string
  genres: string[]
  release_mbid: string
  release_group_mbid: string
  recording_mbid: string
  extension: string
  has_picture: boolean
  readable: boolean
  duration: number | null
  /** Absent from albums analysed before the doubled-tag check existed. */
  repeated?: Record<string, string[]>
}

export type MetadataAlbumDetail = MetadataAlbum & {
  tracks: MetadataTrack[]
  match_details: Record<string, unknown> | null
}

export type MetadataListResponse = {
  count: number
  offset: number
  items: MetadataAlbum[]
}

export type MetadataSummary = {
  total: number
  open: number
  ignored: number
  resolved: number
  issues: Record<string, number>
  last_scan_at: string | null
  library_dir: string
  library_readable: boolean
  fingerprinting_available: boolean
  acoustid_configured: boolean
  scan_running: boolean
  last_error: string
  library_albums: number
  last_scan: MetadataScanReport | null
  artwork_running: boolean
  artwork_error: string
  last_artwork_sync: ArtworkSyncReport | null
  jellyfin_covers_running: boolean
  jellyfin_covers_error: string
  last_jellyfin_covers: JellyfinCoverReport | null
  jellyfin_meta_running: boolean
  jellyfin_meta_error: string
  last_jellyfin_meta: JellyfinMetadataReport | null
}

export type MetadataScanReport = {
  root: string
  started_at: string | null
  finished_at: string | null
  min_tracks: number
  directories: number
  audio_files: number
  folders: number
  analysed: number
  below_min_tracks: number
  unreadable: number
  failed: number
  failures: { path: string; error: string }[]
}

export type ArtworkSyncReport = {
  root: string
  started_at: string | null
  finished_at: string | null
  folders: number
  already: number
  copied: number
  extracted: number
  without_art: number
  failed: number
  failures: { path: string; error: string }[]
}

export type JellyfinCoverReport = {
  started_at: string | null
  finished_at: string | null
  albums: number
  without_cover: number
  refreshed: number
  fixed_by_refresh: number
  uploaded: number
  no_source: number
  failed: number
  failures: { path: string; error: string }[]
}

export type JellyfinMetadataReport = {
  started_at: string | null
  finished_at: string | null
  albums: number
  compared: number
  stale: number
  refreshed: number
  fixed_by_refresh: number
  albums_written: number
  tracks_written: number
  unreadable: number
  left: number
  refresh_ignored: boolean
  failed: number
  failures: { path: string; error: string }[]
  samples: { path: string; error: string }[]
}

export type MetadataProposal = {
  release_group_mbid: string
  release_mbid: string
  artist: string
  title: string
  year: number | null
  track_count: number
  score: number
  source: string
  details: Record<string, unknown>
  cover_url: string | null
}

export type MetadataFileChange = {
  name: string
  path: string
  before: Record<string, unknown>
  after: Record<string, unknown>
  changed: string[]
  /** Values the file holds twice, which `before` only carries once. */
  repeated: Record<string, string[]>
}

export type MetadataPlan = {
  release_mbid: string
  release_group_mbid: string
  artist: string
  album: string
  year: number | null
  track_count: number
  files: MetadataFileChange[]
  warnings: string[]
  unmatched: string[]
  cover_source: string
}

export type MetadataApplyResult = {
  written: number
  cover_written: boolean
  warnings: string[]
}

export type LocalImportTrack = {
  name: string
  relative: string
  title: string
  artist: string
  album: string
  track: number | null
  disc: number | null
  extension: string
}

export type LocalImportOwnership = {
  status: string | null
  upgradable: boolean
  blocked: boolean
  reason: string
  path: string | null
  is_lossless: boolean
  formats: string[]
  jellyfin_id: string | null
}

export type LocalImportSession = {
  id: string
  status: string
  artist: string
  album: string
  year: string
  track_count: number
  is_lossless: boolean
  has_cover: boolean
  cover_url: string | null
  mode: string
  release_mbid: string
  release_group_mbid: string
  tracks: LocalImportTrack[]
  proposals: MetadataProposal[]
  ownership: LocalImportOwnership | null
  warnings: string[]
  destination: string | null
  files: string[]
}

export type PlayableTrack = {
  /** Empty on a thirty second extract: no library item sits behind it. */
  jellyfin_id: string
  title: string
  artist: string
  album: string
  album_id: string | null
  /** Known when the album is indexed: lets the player reach the artist page. */
  artist_mbid?: string | null
  track: number | null
  disc: number | null
  duration: number | null
  container: string
  cover_url: string | null
  /** 'deezer' or 'itunes' when this entry is an extract. */
  preview?: string | null
  /** Re-encoded on the fly: the stream cannot be seeked into, only restarted. */
  transcoded?: boolean
  /** False when nothing on the server can decode this file for the browser. */
  playable?: boolean
  stream_url: string
}

export type TrackSearchResult = {
  title: string
  artist: string
  album: string
  year: number | null
  duration: number | null
  owned: boolean
  jellyfin_id: string | null
  album_jellyfin_id: string | null
  release_group_mbid: string | null
  recording_mbid: string | null
  cover_url: string | null
}

export type Playlist = {
  id: string
  name: string
  track_count: number
  can_delete: boolean
  cover_url: string | null
}

export type PlaylistTrack = PlayableTrack & {
  playlist_item_id: string
}

export type PlaylistChange = {
  playlist_id: string
  name: string
  added: number
  /** Tracks the playlist already held, left alone rather than doubled. */
  skipped: number
}

export type PlaylistBackupTrack = {
  jellyfin_id: string
  path: string
  title: string
  artist: string
  album: string
  recording_mbid: string | null
  release_mbid: string | null
}

export type PlaylistBackupEntry = {
  name: string
  owner: string
  tracks: PlaylistBackupTrack[]
}

export type PlaylistBackup = {
  version: number
  playlists: PlaylistBackupEntry[]
}

export type PlaylistImportMissing = {
  title: string
  artist: string
  album: string
  reason: string
}

export type PlaylistImportResult = {
  name: string
  playlist_id: string
  added: number
  missing: PlaylistImportMissing[]
}

export type PlaylistImportReport = {
  playlists: PlaylistImportResult[]
}

export type PlaylistAccount = {
  id: string
  name: string
}

export type TrackSearchResponse = {
  count: number
  items: TrackSearchResult[]
}

export type Health = {
  status: string
  version: string
  setup_required: boolean
  mode: Mode
  services: Record<string, boolean>
  musicbrainz_browse_url: string
}

export type SetupStatus = {
  setup_completed: boolean
  mode: Mode
  jellyfin_configured: boolean
  users: number
}

export type JellyfinLibrary = {
  id: string
  name: string
  locations: string[]
}

export type AllSettings = Record<string, Record<string, unknown>>

export type JobRow = {
  id: number
  kind: string
  state: string
  request_id: number | null
  attempts: number
  run_after: string
  started_at: string | null
  finished_at: string | null
  error: string | null
}

export type SystemInfo = {
  version: string
  mode: Mode
  config_dir: string
  music_dir: string
  worker_concurrency: number
  configured: Record<string, boolean>
  provider_order: string[]
}
