"""Metadata writing.

The tag set mirrors what MusicBrainz Picard writes, including every MBID, so
Jellyfin identifies the album straight away and Muzikk can later recognise it
as owned.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field
from pathlib import Path

from mutagen import File as MutagenFile
from mutagen.flac import FLAC, Picture
from mutagen.id3 import (
    APIC,
    ID3,
    TALB,
    TCMP,
    TCON,
    TDRC,
    TIT2,
    TPE1,
    TPE2,
    TPOS,
    TPUB,
    TRCK,
    TSO2,
    TSOP,
    TSRC,
    TXXX,
    UFID,
    ID3NoHeaderError,
)
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis

logger = logging.getLogger(__name__)

MB_UFID_OWNER = "http://musicbrainz.org"


class TaggingError(RuntimeError):
    pass


@dataclass(slots=True)
class TrackMetadata:
    title: str = ""
    artist: str = ""
    artists: list[str] = field(default_factory=list)
    album: str = ""
    albumartist: str = ""
    artist_sort: str = ""
    albumartist_sort: str = ""
    date: str = ""
    original_date: str = ""
    track: int = 0
    total_tracks: int = 0
    disc: int = 1
    total_discs: int = 1
    genres: list[str] = field(default_factory=list)
    label: str = ""
    catalog_number: str = ""
    media: str = ""
    release_country: str = ""
    release_status: str = ""
    release_type: str = ""
    barcode: str = ""
    isrc: str = ""
    is_compilation: bool = False
    release_mbid: str = ""
    release_group_mbid: str = ""
    recording_mbid: str = ""
    release_track_mbid: str = ""
    artist_mbid: str = ""
    albumartist_mbid: str = ""

    @property
    def year(self) -> str:
        return self.date[:4] if len(self.date) >= 4 else ""


def _vorbis_tags(meta: TrackMetadata) -> dict[str, list[str]]:
    tags: dict[str, list[str]] = {
        "TITLE": [meta.title],
        "ARTIST": [meta.artist],
        "ALBUM": [meta.album],
        "ALBUMARTIST": [meta.albumartist],
        "TRACKNUMBER": [str(meta.track)],
        "TRACKTOTAL": [str(meta.total_tracks)],
        "TOTALTRACKS": [str(meta.total_tracks)],
        "DISCNUMBER": [str(meta.disc)],
        "DISCTOTAL": [str(meta.total_discs)],
        "TOTALDISCS": [str(meta.total_discs)],
    }
    optional = {
        "DATE": meta.date,
        "ORIGINALDATE": meta.original_date,
        "ORIGINALYEAR": meta.original_date[:4] if meta.original_date else "",
        "LABEL": meta.label,
        "CATALOGNUMBER": meta.catalog_number,
        "MEDIA": meta.media,
        "RELEASECOUNTRY": meta.release_country,
        "RELEASESTATUS": meta.release_status,
        "RELEASETYPE": meta.release_type,
        "BARCODE": meta.barcode,
        "ISRC": meta.isrc,
        "ARTISTSORT": meta.artist_sort,
        "ALBUMARTISTSORT": meta.albumartist_sort,
        "MUSICBRAINZ_ALBUMID": meta.release_mbid,
        "MUSICBRAINZ_RELEASEGROUPID": meta.release_group_mbid,
        "MUSICBRAINZ_TRACKID": meta.recording_mbid,
        "MUSICBRAINZ_RELEASETRACKID": meta.release_track_mbid,
        "MUSICBRAINZ_ARTISTID": meta.artist_mbid,
        "MUSICBRAINZ_ALBUMARTISTID": meta.albumartist_mbid,
    }
    for key, value in optional.items():
        if value:
            tags[key] = [value]
    if meta.genres:
        tags["GENRE"] = list(meta.genres)
    if meta.artists:
        tags["ARTISTS"] = list(meta.artists)
    if meta.is_compilation:
        tags["COMPILATION"] = ["1"]
    return {key: values for key, values in tags.items() if any(values)}


def _build_picture(cover: bytes, mime: str = "image/jpeg") -> Picture:
    picture = Picture()
    picture.data = cover
    picture.type = 3  # front cover
    picture.mime = mime
    picture.desc = "Cover"
    return picture


def _tag_flac(path: Path, meta: TrackMetadata, cover: bytes | None) -> None:
    audio = FLAC(str(path))
    audio.delete()
    for key, values in _vorbis_tags(meta).items():
        audio[key] = values
    if cover:
        audio.clear_pictures()
        audio.add_picture(_build_picture(cover))
    audio.save()


def _tag_vorbis(path: Path, meta: TrackMetadata, cover: bytes | None, opus: bool) -> None:
    audio = OggOpus(str(path)) if opus else OggVorbis(str(path))
    for key in list(audio.keys()):
        del audio[key]
    for key, values in _vorbis_tags(meta).items():
        audio[key] = values
    if cover:
        encoded = base64.b64encode(_build_picture(cover).write()).decode("ascii")
        audio["METADATA_BLOCK_PICTURE"] = [encoded]
    audio.save()


def _tag_id3(path: Path, meta: TrackMetadata, cover: bytes | None) -> None:
    try:
        tags = ID3(str(path))
        tags.delete()
    except ID3NoHeaderError:
        tags = ID3()

    tags.add(TIT2(encoding=3, text=meta.title))
    tags.add(TPE1(encoding=3, text=meta.artist))
    tags.add(TPE2(encoding=3, text=meta.albumartist))
    tags.add(TALB(encoding=3, text=meta.album))
    tags.add(TRCK(encoding=3, text=f"{meta.track}/{meta.total_tracks or meta.track}"))
    tags.add(TPOS(encoding=3, text=f"{meta.disc}/{meta.total_discs or meta.disc}"))
    if meta.date:
        tags.add(TDRC(encoding=3, text=meta.date))
    if meta.genres:
        tags.add(TCON(encoding=3, text=meta.genres))
    if meta.label:
        tags.add(TPUB(encoding=3, text=meta.label))
    if meta.isrc:
        tags.add(TSRC(encoding=3, text=meta.isrc))
    if meta.artist_sort:
        tags.add(TSOP(encoding=3, text=meta.artist_sort))
    if meta.albumartist_sort:
        tags.add(TSO2(encoding=3, text=meta.albumartist_sort))
    if meta.is_compilation:
        tags.add(TCMP(encoding=3, text="1"))

    txxx = {
        "MusicBrainz Album Id": meta.release_mbid,
        "MusicBrainz Release Group Id": meta.release_group_mbid,
        "MusicBrainz Release Track Id": meta.release_track_mbid,
        "MusicBrainz Artist Id": meta.artist_mbid,
        "MusicBrainz Album Artist Id": meta.albumartist_mbid,
        "MusicBrainz Album Status": meta.release_status,
        "MusicBrainz Album Type": meta.release_type,
        "MusicBrainz Album Release Country": meta.release_country,
        "CATALOGNUMBER": meta.catalog_number,
        "MEDIA": meta.media,
        "BARCODE": meta.barcode,
    }
    for description, value in txxx.items():
        if value:
            tags.add(TXXX(encoding=3, desc=description, text=value))

    if meta.recording_mbid:
        tags.add(UFID(owner=MB_UFID_OWNER, data=meta.recording_mbid.encode("ascii")))
    if cover:
        tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover))

    tags.save(str(path), v2_version=3)


def _tag_mp4(path: Path, meta: TrackMetadata, cover: bytes | None) -> None:
    audio = MP4(str(path))
    audio.delete()
    audio["\xa9nam"] = [meta.title]
    audio["\xa9ART"] = [meta.artist]
    audio["aART"] = [meta.albumartist]
    audio["\xa9alb"] = [meta.album]
    if meta.date:
        audio["\xa9day"] = [meta.date]
    if meta.genres:
        audio["\xa9gen"] = list(meta.genres)
    audio["trkn"] = [(meta.track, meta.total_tracks or meta.track)]
    audio["disk"] = [(meta.disc, meta.total_discs or meta.disc)]
    if meta.is_compilation:
        audio["cpil"] = True

    freeform = {
        "MusicBrainz Album Id": meta.release_mbid,
        "MusicBrainz Release Group Id": meta.release_group_mbid,
        "MusicBrainz Track Id": meta.recording_mbid,
        "MusicBrainz Release Track Id": meta.release_track_mbid,
        "MusicBrainz Artist Id": meta.artist_mbid,
        "MusicBrainz Album Artist Id": meta.albumartist_mbid,
        "LABEL": meta.label,
        "CATALOGNUMBER": meta.catalog_number,
        "MEDIA": meta.media,
    }
    for name, value in freeform.items():
        if value:
            audio[f"----:com.apple.iTunes:{name}"] = [value.encode("utf-8")]

    if cover:
        audio["covr"] = [MP4Cover(cover, imageformat=MP4Cover.FORMAT_JPEG)]
    audio.save()


def write_tags(path: Path, meta: TrackMetadata, cover: bytes | None = None) -> str:
    """Tag a single file and return the format that was handled."""
    extension = path.suffix.lower().lstrip(".")
    try:
        if extension == "flac":
            _tag_flac(path, meta, cover)
            return "flac"
        if extension in ("ogg", "oga"):
            _tag_vorbis(path, meta, cover, opus=False)
            return "vorbis"
        if extension == "opus":
            _tag_vorbis(path, meta, cover, opus=True)
            return "opus"
        if extension == "mp3":
            _tag_id3(path, meta, cover)
            return "id3"
        if extension in ("m4a", "mp4", "alac", "aac"):
            _tag_mp4(path, meta, cover)
            return "mp4"

        # Anything else: let mutagen decide, tag what it can.
        audio = MutagenFile(str(path))
        if audio is None:
            raise TaggingError(f"unsupported audio format: {extension or 'unknown'}")
        if hasattr(audio, "tags") and audio.tags is None:
            audio.add_tags()
        for key, values in _vorbis_tags(meta).items():
            try:
                audio[key] = values
            except (KeyError, TypeError, ValueError):
                continue
        audio.save()
        return extension or "generic"
    except TaggingError:
        raise
    except Exception as exc:  # noqa: BLE001 - mutagen raises many unrelated types
        raise TaggingError(f"{path.name}: {exc}") from exc


def read_audio_info(path: Path) -> dict[str, object]:
    """Length, bitrate and bit depth of a file, for reporting."""
    try:
        audio = MutagenFile(str(path))
    except Exception:  # noqa: BLE001
        return {}
    if audio is None or not getattr(audio, "info", None):
        return {}
    info = audio.info
    return {
        "length": getattr(info, "length", None),
        "bitrate": getattr(info, "bitrate", None),
        "sample_rate": getattr(info, "sample_rate", None),
        "bit_depth": getattr(info, "bits_per_sample", None),
        "channels": getattr(info, "channels", None),
    }
