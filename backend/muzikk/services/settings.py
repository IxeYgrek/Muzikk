"""Runtime configuration.

Every setting the administrator can change lives here. Sections are stored as
one JSON row each, validated by a Pydantic model that also carries the default
values, so a new setting is available immediately after an upgrade without a
migration. Secrets are encrypted at rest and masked when read back by the API.
"""

from __future__ import annotations

import threading
from typing import Any, ClassVar

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..models import AppSetting
from ..security import MASK, decrypt_secret, encrypt_secret


class Section(BaseModel):
    """Base class for a settings section."""

    secret_fields: ClassVar[tuple[str, ...]] = ()


class GeneralSettings(Section):
    # Flipped once the first-run wizard has been completed; while false the
    # unauthenticated setup endpoints stay open.
    setup_completed: bool = False
    # "jellyfin" or "local". Written once by the wizard, never afterwards.
    # Installs predating the local mode have no value stored and were built on
    # Jellyfin, which is why that is the default.
    mode: str = "jellyfin"
    default_language: str = "en"
    require_approval: bool = True
    admins_bypass_approval: bool = True
    default_weekly_quota: int = 0
    retry_failed_after_hours: int = 12
    max_retry_attempts: int = 8
    library_scan_interval_minutes: int = 360
    watchlist_check_interval_hours: int = 12
    keep_events_days: int = 60


class JellyfinSettings(Section):
    secret_fields: ClassVar[tuple[str, ...]] = ("api_key",)

    url: str = ""
    api_key: str = ""
    music_library_ids: list[str] = Field(default_factory=list)
    trigger_scan_on_import: bool = True
    allow_all_users: bool = True
    allowed_user_ids: list[str] = Field(default_factory=list)


class MusicBrainzSettings(Section):
    url: str = "http://musicbrainz:5000"
    use_public_fallback: bool = True
    public_url: str = "https://musicbrainz.org"
    rate_limit_per_second: float = 10.0
    public_rate_limit_per_second: float = 1.0
    contact: str = "muzikk@localhost"


class CoverArtSettings(Section):
    url: str = "https://coverartarchive.org"
    embed_in_files: bool = True
    save_folder_cover: bool = True
    save_folder_jpg: bool = True
    preferred_size: int = 1200


class SlskdSettings(Section):
    secret_fields: ClassVar[tuple[str, ...]] = ("api_key",)

    enabled: bool = True
    url: str = "http://slskd:5030"
    api_key: str = ""
    url_base: str = ""
    downloads_dir: str = "/downloads/slskd"
    # slskd treats this value as milliseconds despite what its docs say.
    search_timeout_ms: int = 15000
    response_limit: int = 250
    min_peer_upload_speed: int = 0
    max_peer_queue_length: int = 1000
    wait_timeout_minutes: int = 60
    stall_timeout_minutes: int = 12
    remove_completed: bool = True


class ProwlarrSettings(Section):
    secret_fields: ClassVar[tuple[str, ...]] = ("api_key",)

    enabled: bool = True
    url: str = "http://prowlarr:9696"
    api_key: str = ""
    # 3000 Audio, 3010 MP3, 3040 Lossless.
    categories: list[int] = Field(default_factory=lambda: [3000, 3010, 3040])
    result_limit: int = 100
    use_music_search: bool = True
    inspect_torrent_files: bool = True


class QbittorrentSettings(Section):
    secret_fields: ClassVar[tuple[str, ...]] = ("password",)

    enabled: bool = True
    url: str = "http://qbittorrent:8080"
    username: str = ""
    password: str = ""
    category: str = "muzikk"
    save_path: str = "/downloads/torrents"
    wait_timeout_minutes: int = 300
    stall_timeout_minutes: int = 45
    keep_seeding: bool = True
    add_paused: bool = False


class QualitySettings(Section):
    # Ordered from best to worst; the first match wins.
    lossless_formats: list[str] = Field(
        default_factory=lambda: ["flac", "alac", "wv", "ape", "aiff", "wav"]
    )
    allow_lossy_fallback: bool = False
    lossy_formats: list[str] = Field(default_factory=lambda: ["mp3", "m4a", "ogg", "opus"])
    min_lossy_bitrate: int = 320
    prefer_24bit: bool = True
    min_score: float = 78.0
    track_count_tolerance: int = 0
    min_seeders: int = 2
    min_size_per_track_mb: float = 4.0
    max_size_per_track_mb: float = 400.0
    verify_audio_integrity: bool = True
    reject_incomplete_albums: bool = True
    # Refuse a release whose path names no artist resembling the one asked for.
    # It costs the odd folder named after the album alone, and it spares taking
    # someone else's record of the same name for the right one.
    require_artist_match: bool = True


class NamingSettings(Section):
    album_template: str = (
        "{albumartist}/{album} ({year})/{disc_prefix}{track:02} {artist_prefix}{title}"
    )
    replace_unsafe_with: str = "_"
    max_component_length: int = 120
    various_artists_name: str = "Various Artists"
    music_dir: str = "/music"
    use_hardlinks: bool = True
    overwrite_on_upgrade: bool = True
    # An upgrade usually lands in the very folder it improves, so the old files
    # and the new ones sit side by side until someone says the new release is
    # really the album. Turn this off to delete the old copy right away.
    confirm_upgrade_replace: bool = True


class ProvidersSettings(Section):
    # Provider groups, queried in this order.
    order: list[str] = Field(
        default_factory=lambda: ["slskd", "torrent_public", "torrent_private"]
    )


class MetadataSettings(Section):
    """Library analysis and metadata repair."""

    secret_fields: ClassVar[tuple[str, ...]] = ("acoustid_api_key",)

    nightly_scan: bool = True
    scan_hour: int = 3
    # Folders holding fewer files than this are treated as loose tracks.
    min_tracks_per_album: int = 2
    max_albums_per_scan: int = 20000
    # Above this score a proposal is presented as reliable; nothing is ever
    # written without an explicit confirmation.
    confident_score: float = 90.0
    embed_cover: bool = True
    write_folder_cover: bool = True
    write_folder_jpg: bool = True
    acoustid_enabled: bool = False
    acoustid_api_key: str = ""
    # Fingerprinting is slow, so only a sample of the album is submitted.
    acoustid_sample_tracks: int = 3


class PlayerSettings(Section):
    enabled: bool = True
    # Jellyfin transcodes on the fly when the browser cannot decode the file.
    max_bitrate: int = 0
    report_playback: bool = True
    # Local mode only: without Jellyfin, an APE or a WavPack file has to be
    # re-encoded here or it simply will not play. Turn it off to keep the CPU
    # free and let those tracks be reported as unplayable instead.
    transcode: bool = True
    transcode_format: str = "mp3"
    # Read the file from the library folder instead of asking Jellyfin to send
    # it back. Faster, and immune to Jellyfin playback policies.
    direct_file_access: bool = True
    # Thirty second extracts, from Deezer then iTunes, for the tracks the
    # library does not hold. Turn it off to keep Muzikk from reaching out to
    # either service.
    previews: bool = True


SECTION_MODELS: dict[str, type[Section]] = {
    "general": GeneralSettings,
    "jellyfin": JellyfinSettings,
    "musicbrainz": MusicBrainzSettings,
    "coverart": CoverArtSettings,
    "slskd": SlskdSettings,
    "prowlarr": ProwlarrSettings,
    "qbittorrent": QbittorrentSettings,
    "quality": QualitySettings,
    "naming": NamingSettings,
    "providers": ProvidersSettings,
    "metadata": MetadataSettings,
    "player": PlayerSettings,
}

_cache: dict[str, Section] = {}
_lock = threading.Lock()


def invalidate_cache(section: str | None = None) -> None:
    with _lock:
        if section is None:
            _cache.clear()
        else:
            _cache.pop(section, None)


def _model_for(section: str) -> type[Section]:
    try:
        return SECTION_MODELS[section]
    except KeyError:
        raise KeyError(f"Unknown settings section: {section}") from None


def load(session: Session, section: str) -> Any:
    """Return a section with decrypted secrets, using cached values when possible."""
    with _lock:
        cached = _cache.get(section)
    if cached is not None:
        return cached

    model = _model_for(section)
    row = session.get(AppSetting, section)
    raw: dict[str, Any] = dict(row.data or {}) if row else {}
    for field in model.secret_fields:
        if raw.get(field):
            raw[field] = decrypt_secret(raw[field]) or ""
    instance = model.model_validate(raw)
    with _lock:
        _cache[section] = instance
    return instance


def load_all(session: Session) -> dict[str, Section]:
    return {name: load(session, name) for name in SECTION_MODELS}


def save(session: Session, section: str, updates: dict[str, Any]) -> Any:
    """Merge ``updates`` into a section and persist it.

    A secret submitted as the mask placeholder keeps its previous value, which
    lets the frontend send back the whole form without leaking secrets.
    """
    model = _model_for(section)
    current = load(session, section)
    merged = current.model_dump()

    for key, value in updates.items():
        if key not in merged:
            continue
        if key in model.secret_fields and isinstance(value, str) and value.strip() == MASK:
            continue
        merged[key] = value

    instance = model.model_validate(merged)
    payload = instance.model_dump()
    for field in model.secret_fields:
        if payload.get(field):
            payload[field] = encrypt_secret(payload[field])

    row = session.get(AppSetting, section)
    if row is None:
        row = AppSetting(section=section, data=payload)
        session.add(row)
    else:
        row.data = payload
    session.commit()
    invalidate_cache(section)
    return load(session, section)


def to_public(section: str, instance: Section) -> dict[str, Any]:
    """Serialize a section for the admin API, masking configured secrets."""
    model = _model_for(section)
    data = instance.model_dump()
    for field in model.secret_fields:
        data[field] = MASK if data.get(field) else ""
    return data
