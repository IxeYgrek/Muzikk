"""Destination paths.

The default template reproduces the MusicBrainz Picard script used as the
reference layout:

    Artist/Album (year)/01 Title.flac

``disc_prefix`` and ``artist_prefix`` are computed rather than expressed with
conditionals in the template, so the template itself stays readable.
"""

from __future__ import annotations

import re
import string
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from ..services.settings import NamingSettings

UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
TRAILING_JUNK = re.compile(r"[ .]+$")
MULTI_SPACE = re.compile(r"\s{2,}")

RESERVED_WINDOWS_NAMES = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


@dataclass(slots=True)
class TrackContext:
    """Everything a template can reference for a single track."""

    albumartist: str = ""
    album: str = ""
    title: str = ""
    artist: str = ""
    track: int = 0
    totaltracks: int = 0
    disc: int = 1
    totaldiscs: int = 1
    year: str = ""
    date: str = ""
    genre: str = ""
    label: str = ""
    catalognumber: str = ""
    media: str = ""
    releasetype: str = ""
    extension: str = "flac"
    is_multiartist: bool = False
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def disc_prefix(self) -> str:
        if self.totaldiscs <= 1:
            return ""
        width = 2 if self.totaldiscs > 9 else 1
        return f"{self.disc:0{width}d}-"

    @property
    def artist_prefix(self) -> str:
        if not self.is_multiartist or not self.artist:
            return ""
        if self.artist.strip().lower() == self.albumartist.strip().lower():
            return ""
        return f"{self.artist} - "

    def as_mapping(self) -> dict[str, object]:
        mapping: dict[str, object] = {
            "albumartist": self.albumartist,
            "album": self.album,
            "title": self.title,
            "artist": self.artist,
            "track": self.track,
            "tracknumber": self.track,
            "totaltracks": self.totaltracks,
            "disc": self.disc,
            "discnumber": self.disc,
            "totaldiscs": self.totaldiscs,
            "year": self.year,
            "date": self.date,
            "genre": self.genre,
            "label": self.label,
            "catalognumber": self.catalognumber,
            "media": self.media,
            "releasetype": self.releasetype,
            "disc_prefix": self.disc_prefix,
            "artist_prefix": self.artist_prefix,
        }
        mapping.update(self.extra)
        return mapping


class _Formatter(string.Formatter):
    """Formatter that tolerates unknown fields instead of raising."""

    def get_value(self, key, args, kwargs):  # type: ignore[override]
        if isinstance(key, str):
            return kwargs.get(key, "")
        return super().get_value(key, args, kwargs)

    def format_field(self, value, format_spec):  # type: ignore[override]
        if format_spec and isinstance(value, str):
            # "{track:02}" with a missing value must not blow up.
            if not value.strip():
                return ""
            if value.strip().isdigit():
                value = int(value)
        if format_spec and value in (None, ""):
            return ""
        return super().format_field(value, format_spec)


_formatter = _Formatter()


def sanitize_component(value: str, settings: NamingSettings) -> str:
    """Make a single path component safe on Linux, Windows and SMB shares."""
    text = UNSAFE_CHARS.sub(settings.replace_unsafe_with, str(value or ""))
    text = MULTI_SPACE.sub(" ", text).strip()
    text = TRAILING_JUNK.sub("", text)
    if text.lower() in RESERVED_WINDOWS_NAMES:
        text = f"{text}_"
    limit = max(20, settings.max_component_length)
    if len(text) > limit:
        text = text[:limit].strip()
        text = TRAILING_JUNK.sub("", text)
    return text or "Unknown"


class TemplateError(ValueError):
    pass


def render_relative_path(context: TrackContext, settings: NamingSettings) -> PurePosixPath:
    """Render the template into a relative path, extension included."""
    template = (settings.album_template or "").strip()
    if not template:
        raise TemplateError("the naming template is empty")

    mapping = context.as_mapping()
    try:
        rendered = _formatter.vformat(template, (), mapping)
    except (KeyError, IndexError, ValueError) as exc:
        raise TemplateError(f"invalid naming template: {exc}") from exc

    rendered = rendered.replace("\\", "/")
    components = [part for part in rendered.split("/") if part.strip()]
    if not components:
        raise TemplateError("the naming template produced an empty path")

    safe = [sanitize_component(part, settings) for part in components]
    extension = (context.extension or "flac").lower().lstrip(".")
    safe[-1] = f"{safe[-1]}.{extension}"
    return PurePosixPath(*safe)


def validate_template(template: str) -> None:
    """Reject unknown variables.

    Rendering itself stays tolerant so a template edited badly never breaks an
    import in progress; the administrator is warned here instead, in the preview.
    """
    known = set(TrackContext().as_mapping())
    unknown = sorted(
        {
            name.split(".")[0].split("[")[0]
            for _, name, _, _ in _formatter.parse(template)
            if name
        }
        - known
    )
    if unknown:
        raise TemplateError(f"unknown variable(s): {', '.join('{' + name + '}' for name in unknown)}")


def preview(settings: NamingSettings, template: str | None = None) -> list[str]:
    """Three representative examples shown next to the template field."""
    overrides = {**settings.model_dump(), "album_template": template or settings.album_template}
    effective = NamingSettings(**overrides)
    validate_template(effective.album_template)

    samples = [
        TrackContext(
            albumartist="Daft Punk",
            album="Discovery",
            title="Digital Love",
            artist="Daft Punk",
            track=3,
            totaltracks=14,
            disc=1,
            totaldiscs=1,
            year="2001",
            date="2001-03-12",
            extension="flac",
        ),
        TrackContext(
            albumartist="Pink Floyd",
            album="The Wall",
            title="Comfortably Numb",
            artist="Pink Floyd",
            track=6,
            totaltracks=13,
            disc=2,
            totaldiscs=2,
            year="1979",
            date="1979-11-30",
            extension="flac",
        ),
        TrackContext(
            albumartist=effective.various_artists_name,
            album="Trainspotting",
            title="Born Slippy",
            artist="Underworld",
            track=9,
            totaltracks=14,
            disc=1,
            totaldiscs=1,
            year="1996",
            date="1996-07-08",
            extension="flac",
            is_multiartist=True,
        ),
    ]
    return [str(render_relative_path(sample, effective)) for sample in samples]
