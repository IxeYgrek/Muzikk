"""Reading the tags already written in the library files.

The counterpart of ``pipeline.tagger``, which writes them. Each container keeps
its metadata in its own way, so the mapping is explicit per format rather than
delegated to mutagen's "easy" wrappers, whose key set varies across versions
and silently drops the release group identifier we care most about.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from mutagen import File as MutagenFile
from mutagen.asf import ASFTags
from mutagen.mp4 import MP4Tags

logger = logging.getLogger(__name__)

# Vorbis comments, used by FLAC, Ogg Vorbis and Opus.
VORBIS_FIELDS = {
    "title": "title",
    "artist": "artist",
    "album": "album",
    "albumartist": "albumartist",
    "date": "date",
    "genre": "genre",
    "track": "tracknumber",
    "disc": "discnumber",
    "release_mbid": "musicbrainz_albumid",
    "release_group_mbid": "musicbrainz_releasegroupid",
    "recording_mbid": "musicbrainz_trackid",
    "artist_mbid": "musicbrainz_artistid",
}

ID3_FRAMES = {
    "title": "TIT2",
    "artist": "TPE1",
    "album": "TALB",
    "albumartist": "TPE2",
    "date": "TDRC",
    "genre": "TCON",
    "track": "TRCK",
    "disc": "TPOS",
}

# ID3 keeps the MusicBrainz identifiers in TXXX frames, keyed by description.
ID3_TXXX = {
    "release_mbid": "MusicBrainz Album Id",
    "release_group_mbid": "MusicBrainz Release Group Id",
    "artist_mbid": "MusicBrainz Artist Id",
}

MP4_FIELDS = {
    "title": "\xa9nam",
    "artist": "\xa9ART",
    "album": "\xa9alb",
    "albumartist": "aART",
    "date": "\xa9day",
    "genre": "\xa9gen",
}

MP4_FREEFORM = {
    "release_mbid": "----:com.apple.iTunes:MusicBrainz Album Id",
    "release_group_mbid": "----:com.apple.iTunes:MusicBrainz Release Group Id",
    "recording_mbid": "----:com.apple.iTunes:MusicBrainz Track Id",
    "artist_mbid": "----:com.apple.iTunes:MusicBrainz Artist Id",
}

# Windows Media, still found in older libraries.
ASF_FIELDS = {
    "title": "Title",
    "artist": "Author",
    "album": "WM/AlbumTitle",
    "albumartist": "WM/AlbumArtist",
    "date": "WM/Year",
    "genre": "WM/Genre",
    "track": "WM/TrackNumber",
    "disc": "WM/PartOfSet",
    "release_mbid": "MusicBrainz/Album Id",
    "release_group_mbid": "MusicBrainz/Release Group Id",
    "recording_mbid": "MusicBrainz/Track Id",
    "artist_mbid": "MusicBrainz/Artist Id",
}


@dataclass(slots=True)
class FileTags:
    """What a single audio file currently declares about itself."""

    path: str
    name: str
    extension: str = ""
    title: str = ""
    artist: str = ""
    album: str = ""
    albumartist: str = ""
    date: str = ""
    genres: list[str] = field(default_factory=list)
    track: int | None = None
    disc: int | None = None
    release_mbid: str = ""
    release_group_mbid: str = ""
    recording_mbid: str = ""
    artist_mbid: str = ""
    has_picture: bool = False
    duration: float | None = None
    bitrate: int | None = None
    bit_depth: int | None = None
    sample_rate: int | None = None
    readable: bool = True
    # Fields holding the same value twice, as left behind by a tagger that
    # appended instead of replacing. Kept out of as_dict: this describes the
    # file, it is not one of its values.
    repeated: dict[str, list[str]] = field(default_factory=dict)

    @property
    def year(self) -> int | None:
        head = self.date[:4]
        return int(head) if head.isdigit() else None

    @property
    def has_musicbrainz(self) -> bool:
        return bool(self.release_mbid or self.release_group_mbid)

    def as_dict(self) -> dict[str, object]:
        """Flat view used by the before/after comparison in the interface."""
        return {
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "albumartist": self.albumartist,
            "date": self.date,
            "genres": self.genres,
            "track": self.track,
            "disc": self.disc,
            "release_mbid": self.release_mbid,
            "release_group_mbid": self.release_group_mbid,
            "recording_mbid": self.recording_mbid,
        }


def _text(value: object) -> str:
    """First usable string out of whatever mutagen returned."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return _text(value[0]) if value else ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace").strip()
    return str(value).strip()


def _number(value: object) -> int | None:
    """Track and disc numbers come as "3", "3/12" or (3, 12)."""
    if isinstance(value, (list, tuple)) and value and isinstance(value[0], (list, tuple)):
        value = value[0]
    if isinstance(value, (list, tuple)) and value and isinstance(value[0], int):
        return int(value[0]) or None
    head = _text(value).split("/")[0].strip()
    return int(head) if head.isdigit() else None


def _genres(value: object) -> list[str]:
    if value is None:
        return []
    items = value if isinstance(value, (list, tuple)) else [value]
    result: list[str] = []
    for item in items:
        for piece in _text(item).replace(";", "/").split("/"):
            cleaned = piece.strip()
            if cleaned and cleaned not in result:
                result.append(cleaned)
    return result


def _lookup(tags, key: str):
    """Read one key without trusting the container's opinion of it.

    Vorbis comment dictionaries raise a bare ``ValueError`` on any key they
    consider invalid, and APEv2 has its own ideas, so every lookup is guarded.
    """
    try:
        return tags.get(key)
    except (AttributeError, KeyError, TypeError, ValueError):
        return None


def _all_values(raw: object) -> list[str]:
    """Every string a tag holds, in order and with nothing collapsed.

    The readers below keep the first value, which is the right answer for
    reading an album but hides the anomaly ``_repeats`` looks for.
    """
    if raw is None:
        return []
    raw = getattr(raw, "text", raw)  # an ID3 frame keeps its values there
    items = raw if isinstance(raw, (list, tuple)) else [raw]
    values: list[str] = []
    for item in items:
        # MP4 stores track and disc as a pair, which reads as "3/12".
        cleaned = "/".join(str(part) for part in item) if isinstance(item, tuple) else _text(item)
        if cleaned:
            values.append(cleaned)
    return values


def _repeats(tags, fields: dict[str, str]) -> dict[str, list[str]]:
    """Tags holding one single value, written several times.

    That is the shape a tagger writing twice into the same field leaves behind,
    and what players then show as "Dushi; Dushi".

    Nothing is reported as soon as the values differ, even when one of them
    comes back: a medley credits three artists and may well name the same one
    on the first and the last part, and a track with several performers keeps
    one identifier per performer. Both are legitimate multi valued tags, and
    flagging them was reporting healthy albums.
    """
    found: dict[str, list[str]] = {}
    for attribute, key in fields.items():
        values = _all_values(_lookup(tags, key))
        if len(values) < 2:
            continue
        if len({value.casefold() for value in values}) == 1:
            # The field maps name one tag "genre", the dataclass holds
            # "genres": the callers compare against ``as_dict``, so they get
            # the name used there.
            found["genres" if attribute == "genre" else attribute] = values
    return found


def _read_vorbis(tags, into: FileTags) -> None:
    for attribute, key in VORBIS_FIELDS.items():
        raw = _lookup(tags, key)
        if raw is None:
            continue
        if attribute == "genre":
            into.genres = _genres(raw)
        elif attribute in ("track", "disc"):
            setattr(into, attribute, _number(raw))
        else:
            setattr(into, attribute, _text(raw))
    into.has_picture = bool(_lookup(tags, "metadata_block_picture"))


def _read_id3(tags, into: FileTags) -> None:
    for attribute, frame in ID3_FRAMES.items():
        raw = tags.get(frame)
        if raw is None:
            continue
        text = getattr(raw, "text", raw)
        if attribute == "genre":
            into.genres = _genres(text)
        elif attribute in ("track", "disc"):
            setattr(into, attribute, _number(text))
        else:
            setattr(into, attribute, _text(text))

    descriptions = {
        (frame.desc or "").lower(): _text(frame.text) for frame in tags.getall("TXXX")
    }
    for attribute, description in ID3_TXXX.items():
        value = descriptions.get(description.lower())
        if value:
            setattr(into, attribute, value)

    for frame in tags.getall("UFID"):
        if (frame.owner or "").startswith("http://musicbrainz.org"):
            into.recording_mbid = _text(frame.data)
    into.has_picture = bool(tags.getall("APIC"))


def _read_mp4(tags, into: FileTags) -> None:
    for attribute, key in MP4_FIELDS.items():
        raw = _lookup(tags, key)
        if raw is None:
            continue
        if attribute == "genre":
            into.genres = _genres(raw)
        else:
            setattr(into, attribute, _text(raw))
    into.track = _number(_lookup(tags, "trkn"))
    into.disc = _number(_lookup(tags, "disk"))
    for attribute, key in MP4_FREEFORM.items():
        raw = _lookup(tags, key)
        if raw:
            setattr(into, attribute, _text(raw))
    into.has_picture = bool(_lookup(tags, "covr"))


def _read_asf(tags, into: FileTags) -> None:
    for attribute, key in ASF_FIELDS.items():
        raw = _lookup(tags, key)
        if not raw:
            continue
        if attribute == "genre":
            into.genres = _genres(raw)
        elif attribute in ("track", "disc"):
            setattr(into, attribute, _number(raw))
        else:
            setattr(into, attribute, _text(raw))
    into.has_picture = bool(_lookup(tags, "WM/Picture"))


def _reader_for(tags):
    """Pick the reader and its field map from the tag container itself.

    Probing for a key instead, as a first version did, is a trap: asking a
    Vorbis comment block for an iTunes atom raises a bare ``ValueError``, so
    every FLAC file in a library ended up looking untagged.
    """
    if hasattr(tags, "getall"):  # ID3, including the one WAV and AIFF carry
        return _read_id3, ID3_FRAMES
    if isinstance(tags, MP4Tags):
        return _read_mp4, MP4_FIELDS
    if isinstance(tags, ASFTags):
        return _read_asf, ASF_FIELDS
    return _read_vorbis, VORBIS_FIELDS  # Vorbis comments and APEv2


def read_file(path: Path) -> FileTags:
    """Tags and audio properties of one file, whatever its container."""
    result = FileTags(
        path=str(path), name=path.name, extension=path.suffix.lower().lstrip(".")
    )
    try:
        audio = MutagenFile(str(path))
    except Exception as exc:  # noqa: BLE001 - damaged files must not stop a scan
        logger.debug("Unreadable audio file %s: %s", path, exc)
        result.readable = False
        return result
    if audio is None:
        result.readable = False
        return result

    # Some containers compute these on access and raise on a truncated stream.
    try:
        info = getattr(audio, "info", None)
        if info is not None:
            result.duration = getattr(info, "length", None)
            result.bitrate = getattr(info, "bitrate", None)
            result.sample_rate = getattr(info, "sample_rate", None)
            result.bit_depth = getattr(info, "bits_per_sample", None)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Unreadable audio properties in %s: %s", path, exc)

    tags = getattr(audio, "tags", None)
    if tags is None:
        return result

    # A malformed frame must cost this one file, never the whole album: the
    # per-format readers walk raw tag data and a single odd value in a library
    # of thousands of files would otherwise stop the analysis.
    reader, fields = _reader_for(tags)
    try:
        reader(tags, result)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Unreadable tags in %s: %s: %s", path, type(exc).__name__, exc)

    try:
        result.repeated = _repeats(tags, fields)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not look for repeated tags in %s: %s", path, exc)

    # FLAC keeps its artwork outside the comment block.
    if not result.has_picture and getattr(audio, "pictures", None):
        try:
            result.has_picture = bool(audio.pictures)
        except Exception:  # noqa: BLE001
            result.has_picture = False
    return result


def read_album(files: list[Path], *, limit: int = 60) -> list[FileTags]:
    """Tags of an album folder, ordered by track number then file name."""
    read = [read_file(path) for path in files[:limit]]
    try:
        read.sort(key=lambda item: (item.disc or 1, item.track or 999, item.name.lower()))
    except TypeError:
        # A tag holding something unexpected must not cost the ordering.
        read.sort(key=lambda item: item.name.lower())
    return read
