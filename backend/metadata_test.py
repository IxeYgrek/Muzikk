"""Checks the library analysis: folder grouping, tag reading, issue detection."""

from __future__ import annotations

import asyncio
import io
import os
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault("MUZIKK_CONFIG_DIR", tempfile.mkdtemp(prefix="muzikk-metadata-"))

from mutagen.flac import FLAC, Picture  # noqa: E402
from mutagen.id3 import APIC, ID3, TALB, TCON, TDRC, TIT2, TPE1, TPE2, TRCK, TXXX  # noqa: E402
from PIL import Image  # noqa: E402
from sqlalchemy import select  # noqa: E402

from muzikk.api.metadata import read_reference  # noqa: E402
from muzikk.db import SessionLocal, init_db  # noqa: E402
from muzikk.models import LibraryAlbum, MetadataAlbum, MetadataIssue  # noqa: E402
from muzikk.services import jellyfinmeta, metadata, tags  # noqa: E402

failures: list[str] = []


def check(label: str, condition: bool, extra: object = "") -> None:
    print(f"{'PASS' if condition else 'FAIL'}  {label}" + (f" :: {extra}" if extra else ""))
    if not condition:
        failures.append(label)


def make_image(size: int = 320) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (size, size), "purple").save(buffer, format="JPEG")
    return buffer.getvalue()


# MPEG-1 layer 3, 128 kbps, 44.1 kHz frames, repeated so mutagen can sync.
MP3_FRAME = b"\xff\xfb\x90\x00" + b"\x00" * 413


def write_mp3(path: Path, **fields: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(MP3_FRAME * 12)
    frames = ID3()
    if fields.get("title"):
        frames.add(TIT2(encoding=3, text=str(fields["title"])))
    if fields.get("artist"):
        frames.add(TPE1(encoding=3, text=str(fields["artist"])))
    if fields.get("albumartist"):
        frames.add(TPE2(encoding=3, text=str(fields["albumartist"])))
    if fields.get("album"):
        frames.add(TALB(encoding=3, text=str(fields["album"])))
    if fields.get("date"):
        frames.add(TDRC(encoding=3, text=str(fields["date"])))
    if fields.get("genre"):
        frames.add(TCON(encoding=3, text=str(fields["genre"])))
    if fields.get("track"):
        frames.add(TRCK(encoding=3, text=str(fields["track"])))
    if fields.get("release_mbid"):
        frames.add(
            TXXX(encoding=3, desc="MusicBrainz Album Id", text=str(fields["release_mbid"]))
        )
    if fields.get("release_group_mbid"):
        frames.add(
            TXXX(
                encoding=3,
                desc="MusicBrainz Release Group Id",
                text=str(fields["release_group_mbid"]),
            )
        )
    if fields.get("picture"):
        frames.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=make_image()))
    frames.save(str(path))


# A header-only FLAC: enough for mutagen to open the file and hold real tags.
def _flac_header() -> bytes:
    bits = (44100 << 44) | (1 << 41) | (15 << 36) | 44100
    info = struct.pack(">HH", 4096, 4096) + b"\x00" * 6 + struct.pack(">Q", bits) + b"\x00" * 16
    return b"fLaC" + b"\x80\x00\x00\x22" + info


def write_flac(path: Path, *, picture: bool = False, **fields: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_flac_header())
    audio = FLAC(str(path))
    audio.add_tags()
    for key, value in fields.items():
        if value:
            audio[key] = [str(value)]
    if picture:
        art = Picture()
        art.type = 3
        art.mime = "image/jpeg"
        art.data = make_image()
        audio.add_picture(art)
    audio.save()


root = Path(tempfile.mkdtemp(prefix="muzikk-library-"))

# A fully tagged album, nothing to report.
clean = root / "Daft Punk" / "Discovery (2001)"
for index, title in enumerate(["One More Time", "Aerodynamic", "Digital Love"], start=1):
    write_mp3(
        clean / f"{index:02} {title}.mp3",
        title=title,
        artist="Daft Punk",
        albumartist="Daft Punk",
        album="Discovery",
        date="2001-03-12",
        genre="Electronic",
        track=f"{index}/3",
        release_mbid="1c205925-2cfe-3d3f-8c9d-1eeb0d2bd8a3",
        release_group_mbid="0b0e4477-8b2f-3a2f-9a4f-4e2f4d0e2b9a",
        picture=index == 1,
    )

# No MusicBrainz identifier, no cover, no year: the typical Soulseek folder.
raw = root / "Outkast" / "Stankonia"
for index, title in enumerate(["Gasoline Dreams", "So Fresh, So Clean"], start=1):
    write_mp3(
        raw / f"{index:02} {title}.mp3",
        title=title,
        artist="Outkast",
        album="Stankonia",
        track=str(index),
    )

# The same album a second time, in another folder. The artist is spelled
# differently on purpose: the duplicate must still be seen.
duplicate = root / "Outkast" / "Stankonia (2000) [FLAC]"
write_mp3(duplicate / "01 Gasoline Dreams.mp3", title="Gasoline Dreams", album="Stankonia",
          artist="OutKast", track="1")
write_mp3(duplicate / "02 So Fresh So Clean.mp3", title="So Fresh So Clean", album="Stankonia",
          artist="OutKast", track="2")

# A multi disc album: one album, not two.
boxset = root / "Pink Floyd" / "The Wall (1979)"
for disc in (1, 2):
    for index in (1, 2):
        write_mp3(
            boxset / f"CD{disc}" / f"{index:02} track.mp3",
            title=f"Track {disc}-{index}",
            album="The Wall",
            albumartist="Pink Floyd",
            date="1979",
            track=str(index),
        )

# A single loose track must not be reported as an album.
(root / "Various").mkdir(parents=True, exist_ok=True)
write_mp3(root / "Various" / "random.mp3", title="Random", album="Nothing")

# ------------------------------------------------------------- tag reading

read = tags.read_file(clean / "01 One More Time.mp3")
check("mp3 title read", read.title == "One More Time", read.title)
check("album artist read", read.albumartist == "Daft Punk", read.albumartist)
check("track number parsed from 1/3", read.track == 1, read.track)
check("year derived from the date", read.year == 2001, read.year)
check(
    "release group identifier read from TXXX",
    read.release_group_mbid == "0b0e4477-8b2f-3a2f-9a4f-4e2f4d0e2b9a",
    read.release_group_mbid,
)
check("musicbrainz presence detected", read.has_musicbrainz)
check("embedded picture detected", read.has_picture)

bare = tags.read_file(raw / "01 Gasoline Dreams.mp3")
check("untagged album has no identifier", not bare.has_musicbrainz)
check("no picture on the untagged file", not bare.has_picture)
check("missing date reads as unknown", bare.year is None, bare.year)

# ---------------------------------------------------------- folder grouping

folders = {str(item.path): item for item in metadata.collect_folders(root, min_tracks=2)}
check("clean album found", str(clean) in folders)
check("multi disc album grouped as one", str(boxset) in folders, sorted(folders))
check(
    "both discs attached to the album",
    len(folders.get(str(boxset)).files) == 4 if str(boxset) in folders else False,
)
check("disc subfolder not listed on its own", str(boxset / "CD1") not in folders)
check("loose single track ignored", str(root / "Various") not in folders)

# ------------------------------------------------------------ issue detection

init_db()
session = SessionLocal()
session.query(LibraryAlbum).delete()
session.add(
    LibraryAlbum(
        jellyfin_id="jf-discovery",
        name="Discovery",
        album_artist="Daft Punk",
        # Jellyfin sees the library under its own mount point.
        path="/media/jellyfin/Music/Daft Punk/Discovery (2001)",
        fuzzy_key="daft punk|discovery",
        release_group_mbid="0b0e4477-8b2f-3a2f-9a4f-4e2f4d0e2b9a",
    )
)
session.add(
    LibraryAlbum(
        jellyfin_id="jf-stankonia",
        name="Stankonia",
        album_artist="Outkast",
        path="/media/jellyfin/Music/Outkast/Stankonia",
        fuzzy_key="outkast|stankonia",
        release_group_mbid=None,
        release_mbid=None,
    )
)
session.commit()

locator = metadata.LibraryLocator(session)
matched = locator.find(clean, "daft punk|discovery")
check(
    "album matched across different mount points",
    matched is not None and matched.jellyfin_id == "jf-discovery",
    matched,
)
check(
    "unknown folder matches nothing",
    locator.find(root / "Nobody" / "Nothing", "nobody|nothing") is None,
)

walk = metadata.WalkReport()
findings = {item.path: item for item in metadata._scan_disk(
    root, min_tracks=2, max_albums=500, locator=locator, report=walk
)}
check("walk counted the audio files", walk.audio_files > 0, walk)

clean_finding = findings[str(clean)]
check("tagged album reports no problem", clean_finding.issues == [], clean_finding.issues)
check("tagged album linked to jellyfin", clean_finding.jellyfin_id == "jf-discovery")

raw_finding = findings[str(raw)]
check("missing identifier reported", MetadataIssue.MISSING_MBID in raw_finding.issues)
check("missing cover reported", MetadataIssue.MISSING_COVER in raw_finding.issues)
check("incomplete tags reported", MetadataIssue.INCOMPLETE_TAGS in raw_finding.issues)
check(
    "missing fields listed",
    set(raw_finding.details.get("missing_tags", [])) >= {"albumartist", "date", "genre"},
    raw_finding.details,
)
check(
    "album known to jellyfin without an identifier is only probable",
    MetadataIssue.PROBABLE_MATCH in raw_finding.issues,
    raw_finding.issues,
)
check(
    "album known to jellyfin is not reported as missing from it",
    MetadataIssue.NOT_IN_JELLYFIN not in raw_finding.issues,
)

boxset_finding = findings[str(boxset)]
check(
    "folder absent from jellyfin reported",
    MetadataIssue.NOT_IN_JELLYFIN in boxset_finding.issues,
    boxset_finding.issues,
)
check("album artist read from the tags", boxset_finding.album_artist == "Pink Floyd")
check("year read from the tags", boxset_finding.year == 1979, boxset_finding.year)

check(
    "duplicate folders reported on both sides",
    MetadataIssue.DUPLICATE in findings[str(raw)].issues
    and MetadataIssue.DUPLICATE in findings[str(duplicate)].issues,
)
check(
    "duplicate points at the other folder",
    findings[str(duplicate)].details.get("duplicate_of") == [str(raw)],
    findings[str(duplicate)].details,
)
check(
    "distinct albums are not duplicates",
    MetadataIssue.DUPLICATE not in clean_finding.issues,
)

# ---------------------------------------------------------- artist guessing

untagged = root / "Radiohead" / "OK Computer (1997)"
write_mp3(untagged / "01 airbag.mp3")
write_mp3(untagged / "02 paranoid android.mp3")
guessed = metadata._examine(
    metadata.FolderInfo(path=untagged, files=sorted(untagged.glob("*.mp3"))), locator
)
check("artist guessed from the folder tree", guessed.album_artist == "Radiohead", guessed.album_artist)
check("album guessed from the folder name", guessed.album_title == "OK Computer", guessed.album_title)
check("year guessed from the folder name", guessed.year == 1997, guessed.year)

# --------------------------------------------------------------- padded tags

check("padded value trimmed", metadata.common_value([" Discovery "]) == "Discovery")
check("padded and clean values merged", metadata.common_value([" Homework", "Homework"]) == "Homework")
check("most frequent value wins", metadata.common_value(["A", "B ", "B"]) == "B")
check("only blanks give nothing", metadata.common_value(["", "  ", None]) == "")  # type: ignore[list-item]

padded = root / "Air" / "Moon Safari"
write_mp3(padded / "01 la femme d argent.mp3", title="La femme d'argent", album="Moon Safari ",
          albumartist=" Air", artist="Air ", track="1/10", date="1998", genre="Electronic")
write_mp3(padded / "02 sexy boy.mp3", title="Sexy Boy", album="Moon Safari",
          albumartist="Air", artist="Air", track="2/10", date="1998", genre="Electronic")
spaced = metadata._examine(
    metadata.FolderInfo(path=padded, files=sorted(padded.glob("*.mp3"))), locator
)
check("album with padded tags analysed", spaced.album_title == "Moon Safari", spaced.album_title)
check("padded album artist analysed", spaced.album_artist == "Air", spaced.album_artist)

# -------------------------------------------------------- a Picard-tagged FLAC
#
# Regression: the reader used to pick its format by asking the tag block for an
# iTunes key, which makes a Vorbis comment raise, so every FLAC in a library
# looked untagged.

flac_album = root / "113" / "113 degres"
for index, title in enumerate(["La grenade", "Marginal", "36 quai des Orfevres"], start=1):
    write_flac(
        flac_album / f"{index:02} {title}.flac",
        picture=index == 1,
        title=title,
        artist="113",
        albumartist="113",
        album="113 degres",
        date="2005-11-14",
        genre="Hip-Hop",
        tracknumber=str(index),
        musicbrainz_albumid="d066f071-2037-3d3f-8c9d-1eeb0d2bd8a3",
        musicbrainz_releasegroupid="a12a9d52-93c5-3333-4444-555566667777",
    )

flac_tags = tags.read_file(next(flac_album.glob("*.flac")))
check("flac album read", flac_tags.album == "113 degres", flac_tags.album)
check("flac album artist read", flac_tags.albumartist == "113", flac_tags.albumartist)
check("flac track number read", flac_tags.track == 1, flac_tags.track)
check("flac identifier read", flac_tags.release_mbid.startswith("d066f071"), flac_tags.release_mbid)
check("flac picture seen", flac_tags.has_picture is True, flac_tags.has_picture)

# Jellyfin sometimes names an album its own way; the identifier still ties the
# two together.
session.add(
    LibraryAlbum(
        jellyfin_id="jf-127",
        name="113 degres, but named otherwise by Jellyfin",
        album_artist="113",
        fuzzy_key="113|113 degres named otherwise",
        path="/media/jellyfin/Music/113/Album",
        release_mbid="d066f071-2037-3d3f-8c9d-1eeb0d2bd8a3",
    )
)
session.commit()
mbid_locator = metadata.LibraryLocator(session)

flac_finding = metadata._examine(
    metadata.FolderInfo(path=flac_album, files=sorted(flac_album.glob("*.flac"))), mbid_locator
)
check("tagged flac album reports no problem", flac_finding.issues == [], flac_finding.issues)
check(
    "tagged flac album tied to jellyfin by identifier",
    flac_finding.jellyfin_id == "jf-127",
    flac_finding.jellyfin_id,
)

# Genre is reported but does not make an album incomplete on its own.
no_genre = root / "Yuksek" / "Away From the Sea"
for index, title in enumerate(["Break Ya", "Tonight"], start=1):
    write_flac(
        no_genre / f"{index:02} {title}.flac",
        picture=True,
        title=title,
        artist="Yuksek",
        albumartist="Yuksek",
        album="Away From the Sea",
        date="2011-05-30",
        tracknumber=str(index),
        musicbrainz_albumid="11112222-3333-4444-5555-666677778888",
    )
genreless = metadata._examine(
    metadata.FolderInfo(path=no_genre, files=sorted(no_genre.glob("*.flac"))), mbid_locator
)
check(
    "missing genre alone does not flag the album",
    MetadataIssue.INCOMPLETE_TAGS not in genreless.issues,
    genreless.issues,
)
check(
    "missing genre still reported",
    genreless.details.get("missing_tags") == ["genre"],
    genreless.details,
)
by_mbid = mbid_locator.find(
    Path("/somewhere/else"),
    "somebody|else",
    release_mbid="D066F071-2037-3D3F-8C9D-1EEB0D2BD8A3",
)
check(
    "album matched by its identifier despite a different name",
    by_mbid is not None and by_mbid.jellyfin_id == "jf-127",
    by_mbid,
)
check(
    "unknown identifier still matches nothing",
    mbid_locator.find(Path("/somewhere/else"), "somebody|else", release_mbid="0" * 36) is None,
)

# ------------------------------------------------- a broken album stays listed

broken_walk = metadata.WalkReport()
original_examine = metadata._examine
try:
    metadata._examine = lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("boom"))
    salvaged = metadata._scan_disk(
        root, min_tracks=2, max_albums=50, locator=locator, report=broken_walk
    )
finally:
    metadata._examine = original_examine

check("broken folders still listed", len(salvaged) == broken_walk.failed, len(salvaged))
check("failures counted", broken_walk.failed > 0, broken_walk.failed)
check("failure sample kept", bool(broken_walk.failures), broken_walk.failures)
check(
    "failure sample carries the error",
    broken_walk.failures[0]["error"].startswith("ValueError: boom"),
    broken_walk.failures[0],
)
check(
    "salvaged album named after its folder",
    all(item.album_title for item in salvaged),
    [item.album_title for item in salvaged],
)
check(
    "salvaged album carries the reason",
    all("scan_error" in item.details for item in salvaged),
    salvaged[0].details,
)

# ------------------------------------------------ unreadable tags cost one file

damaged = root / "Damaged" / "Album"
damaged.mkdir(parents=True)
(damaged / "01.mp3").write_bytes(b"not an mp3 at all")
tags_of_junk = tags.read_album(sorted(damaged.glob("*.mp3")))
check("junk file reported unreadable", tags_of_junk[0].readable is False, tags_of_junk[0])

# ------------------------------------------------------ tags written twice
#
# A tagger that appends instead of replacing leaves the same value twice in one
# frame, which players then show glued together: "DushiDushi".

doubled_album = root / "Crookers" / "Dr Gonzo"
for index, song in enumerate(["Dushi", "Wake App"], start=1):
    track_path = doubled_album / f"{index:02} {song}.mp3"
    track_path.parent.mkdir(parents=True, exist_ok=True)
    track_path.write_bytes(MP3_FRAME * 12)
    doubled_frames = ID3()
    doubled_frames.add(TIT2(encoding=3, text=[song, song]))
    doubled_frames.add(TPE1(encoding=3, text=["Crookers", "Crookers"]))
    doubled_frames.add(TPE2(encoding=3, text=["Crookers", "Crookers"]))
    doubled_frames.add(TALB(encoding=3, text=["Dr Gonzo", "Dr Gonzo"]))
    doubled_frames.add(TDRC(encoding=3, text=["2011-10-25", "2011-10-25"]))
    doubled_frames.add(TCON(encoding=3, text=["Electronic", "Electronic"]))
    doubled_frames.add(TRCK(encoding=3, text=[str(index), str(index)]))
    doubled_frames.add(
        TXXX(encoding=3, desc="MusicBrainz Album Id", text="ff711332-b409-44dd-ad1d-f7714f8906db")
    )
    doubled_frames.save(str(track_path))

doubled_tags = tags.read_file(doubled_album / "01 Dushi.mp3")
check("doubled title still read once", doubled_tags.title == "Dushi", doubled_tags.title)
check(
    "doubled title reported",
    doubled_tags.repeated.get("title") == ["Dushi", "Dushi"],
    doubled_tags.repeated,
)
check(
    "doubled album, artist, date and number reported",
    {"album", "artist", "albumartist", "date", "track", "genres"} <= set(doubled_tags.repeated),
    sorted(doubled_tags.repeated),
)

doubled_finding = metadata._examine(
    metadata.FolderInfo(path=doubled_album, files=sorted(doubled_album.glob("*.mp3"))),
    mbid_locator,
)
check(
    "album with doubled tags flagged",
    MetadataIssue.DUPLICATE_TAGS in doubled_finding.issues,
    doubled_finding.issues,
)
doubled_details = doubled_finding.details.get("duplicated_tags", {})
check(
    "every affected file counted",
    doubled_details.get("file_count") == 2,
    doubled_details.get("file_count"),
)
check(
    "affected fields named",
    "album" in doubled_details.get("fields", []) and "title" in doubled_details.get("fields", []),
    doubled_details.get("fields"),
)
check(
    "read values kept for the screen",
    doubled_details.get("files", [{}])[0].get("tags", {}).get("title") == ["Dushi", "Dushi"],
    doubled_details.get("files"),
)
check(
    "doubled values also carried by the track rows",
    doubled_finding.tracks[0]["repeated"].get("album") == ["Dr Gonzo", "Dr Gonzo"],
    doubled_finding.tracks[0].get("repeated"),
)

# Two different artists on one track is ordinary, not an anomaly.
featuring = root / "Crookers" / "Featuring"
featuring.mkdir(parents=True, exist_ok=True)
featured_path = featuring / "01 Knobbers.mp3"
featured_path.write_bytes(MP3_FRAME * 12)
featured_frames = ID3()
featured_frames.add(TIT2(encoding=3, text="Knobbers"))
featured_frames.add(TPE1(encoding=3, text=["Crookers", "Carli"]))
featured_frames.add(TCON(encoding=3, text=["Electronic", "House"]))
featured_frames.save(str(featured_path))
check(
    "several different values are left alone",
    tags.read_file(featured_path).repeated == {},
    tags.read_file(featured_path).repeated,
)

# A medley names one part per value and may well credit the same artist on the
# first and the last one. False positive found on a real library: three values,
# two of them equal, and the album was reported as doubled.
medley = root / "Stupeflip" / "Stup Virus"
medley.mkdir(parents=True, exist_ok=True)
medley_path = medley / "19 Pleure pas Stupeflip.mp3"
medley_path.write_bytes(MP3_FRAME * 12)
medley_frames = ID3()
medley_frames.add(
    TIT2(encoding=3, text=["Pleure pas Stupeflip", "Tales from the Crou", "Fan 2 Stup"])
)
medley_frames.add(TPE1(encoding=3, text=["Stupeflip", "Stupeflip feat. Cadillac", "Stupeflip"]))
medley_frames.add(
    TXXX(
        encoding=3,
        desc="MusicBrainz Artist Id",
        text=["b1f0f2d9-1111-2222-3333-444455556666", "c2a1b3c4-7777-8888-9999-aaaabbbbcccc"],
    )
)
medley_frames.save(str(medley_path))
check(
    "a repeated value among different ones is left alone",
    tags.read_file(medley_path).repeated == {},
    tags.read_file(medley_path).repeated,
)
check(
    "a healthy album reports nothing doubled",
    MetadataIssue.DUPLICATE_TAGS not in flac_finding.issues,
    flac_finding.issues,
)

# ------------------------------------------------------- pasted references

check(
    "release-group url read as a group",
    read_reference("https://musicbrainz.org/release-group/8ab0da4b-880e-4349-9755-66d9a14664a7")
    == ("8ab0da4b-880e-4349-9755-66d9a14664a7", "", False),
)
check(
    "release url read as a release",
    read_reference("https://musicbrainz.org/release/8ab0da4b-880e-4349-9755-66d9a14664a7")
    == ("", "8ab0da4b-880e-4349-9755-66d9a14664a7", False),
)
check(
    "bare identifier left ambiguous",
    read_reference("  8ab0da4b-880e-4349-9755-66d9a14664a7 ")
    == ("8ab0da4b-880e-4349-9755-66d9a14664a7", "", True),
)
try:
    read_reference("not an identifier")
    check("text without an identifier refused", False)
except ValueError:
    check("text without an identifier refused", True)

# -------------------------------------------------------------- scoring

row = MetadataAlbum(
    path=str(raw), album_artist="Outkast", album_title="Stankonia", track_count=24
)
exact = metadata._score_candidate(row, "OutKast", "Stankonia", 24)
wrong_count = metadata._score_candidate(row, "OutKast", "Stankonia", 12)
other = metadata._score_candidate(row, "Nirvana", "Nevermind", 13)
check("exact match scores high", exact >= 95, exact)
check("wrong track count penalised", wrong_count < exact, f"{wrong_count} < {exact}")
check("unrelated album scores low", other < 40, other)

# ------------------------------------------------------- before / after plan

release = {
    "id": "1c205925-2cfe-3d3f-8c9d-1eeb0d2bd8a3",
    "title": "Stankonia",
    "date": "2000-10-31",
    "status": "Official",
    "country": "US",
    "release-group": {
        "id": "0000aaaa-1111-2222-3333-444455556666",
        "title": "Stankonia",
        "primary-type": "Album",
        "first-release-date": "2000-10-31",
    },
    "artist-credit": [
        {
            "name": "OutKast",
            "artist": {"id": "ee1a1c6a-2f10-4d1e-a1c6-1e0e1f2a3b4c", "sort-name": "OutKast"},
        }
    ],
    "media": [
        {
            "position": 1,
            "format": "CD",
            "track-count": 2,
            "tracks": [
                {
                    "id": "track-1",
                    "position": 1,
                    "title": "Gasoline Dreams",
                    "recording": {"id": "rec-1", "title": "Gasoline Dreams"},
                },
                {
                    "id": "track-2",
                    "position": 2,
                    "title": "So Fresh, So Clean",
                    "recording": {"id": "rec-2", "title": "So Fresh, So Clean"},
                },
            ],
        }
    ],
}

plan = metadata._build_plan(row, release, "0000aaaa-1111-2222-3333-444455556666")
check("plan covers every file", len(plan.files) == 2, len(plan.files))
check("plan reports the album artist", plan.artist == "OutKast", plan.artist)
first = plan.files[0]
check("identifier listed as a change", "release_group_mbid" in first.changed, first.changed)
check(
    "identifier filled in the target tags",
    first.after["release_group_mbid"] == "0000aaaa-1111-2222-3333-444455556666",
)
check("existing title left untouched", "title" not in first.changed, first.changed)
check("date added by the plan", "date" in first.changed and first.after["date"] == "2000-10-31")
check("no file left unmatched", plan.unmatched == [], plan.unmatched)

# A value written twice has to show up as a change even though its text already
# matches: the rewrite deletes the tags first, so the repeat disappears.
doubled_row = MetadataAlbum(
    path=str(doubled_album),
    album_artist="Crookers",
    album_title="Dr Gonzo",
    track_count=2,
    release_mbid="ff711332-b409-44dd-ad1d-f7714f8906db",
)
doubled_release = {
    "id": "ff711332-b409-44dd-ad1d-f7714f8906db",
    "title": "Dr Gonzo",
    "date": "2011-10-25",
    "release-group": {"id": "aaaabbbb-cccc-dddd-eeee-ffff00001111", "title": "Dr Gonzo"},
    "artist-credit": [
        {"name": "Crookers", "artist": {"id": "20cf9a2a-7418-42e1-9b36-312cd9c2088f"}}
    ],
    "media": [
        {
            "position": 1,
            "format": "CD",
            "track-count": 2,
            "tracks": [
                {
                    "id": "dg-1",
                    "position": 1,
                    "title": "Dushi",
                    "recording": {"id": "dg-rec-1", "title": "Dushi"},
                },
                {
                    "id": "dg-2",
                    "position": 2,
                    "title": "Wake App",
                    "recording": {"id": "dg-rec-2", "title": "Wake App"},
                },
            ],
        }
    ],
}
doubled_plan = metadata._build_plan(
    doubled_row, doubled_release, "aaaabbbb-cccc-dddd-eeee-ffff00001111"
)
doubled_file = doubled_plan.files[0]
check(
    "same title written twice still counts as a change",
    doubled_file.before["title"] == "Dushi"
    and doubled_file.after["title"] == "Dushi"
    and "title" in doubled_file.changed,
    doubled_file.changed,
)
check(
    "plan carries the values read twice",
    doubled_file.repeated.get("album") == ["Dr Gonzo", "Dr Gonzo"],
    doubled_file.repeated,
)
check(
    "a healthy file carries nothing doubled",
    first.repeated == {},
    first.repeated,
)

# --------------------------------------------- aligning Jellyfin on the tags

# Two albums whose files are clean. Jellyfin kept the doubled names of the
# first one, which is exactly what a refresh never corrects.
lotus = root / "Cristobal Tapia de Veer" / "The White Lotus"
for index, title in enumerate(["Aloha!", "Pineapple Suite"], start=1):
    write_mp3(
        lotus / f"{index:02} {title}.mp3",
        title=title,
        artist="Cristobal Tapia de Veer",
        albumartist="Cristobal Tapia de Veer",
        album="The White Lotus",
        date="2021-07-11",
        track=f"{index}/2",
    )
agreed = root / "Air" / "Moon Safari"
write_mp3(agreed / "01 La femme d'argent.mp3", title="La femme d'argent", artist="Air",
          albumartist="Air", album="Moon Safari", date="1998-01-16", track="1/1")


def stored_tracks(folder: Path) -> list[dict[str, object]]:
    """The track list an analysis leaves on the album row."""
    return [
        {"name": entry.name, "path": entry.path, "title": entry.title,
         "track": entry.track, "disc": entry.disc, "readable": True}
        for entry in tags.read_album(sorted(folder.glob("*.mp3")))
    ]


session.add(
    MetadataAlbum(
        path=str(lotus),
        jellyfin_id="jf-lotus",
        album_artist="Cristobal Tapia de Veer",
        album_title="The White Lotus",
        year=2021,
        track_count=2,
        tracks=stored_tracks(lotus),
    )
)
session.add(
    MetadataAlbum(
        path=str(agreed),
        jellyfin_id="jf-air",
        album_artist="Air",
        album_title="Moon Safari",
        year=1998,
        track_count=1,
        tracks=stored_tracks(agreed),
    )
)
session.commit()

created: list[object] = []


class FakeJellyfin:
    """A server holding the doubled names and refusing to read the files again."""

    configured = True
    api_key = "key"

    def __init__(self, _settings: object) -> None:
        created.append(self)
        self.refreshed: list[str] = []
        self.written: dict[str, dict[str, object]] = {}
        self.items: dict[str, dict[str, object]] = {
            "jf-lotus": {
                "Id": "jf-lotus",
                "Name": "The White LotusThe White Lotus",
                "AlbumArtists": [{"Name": "Cristobal Tapia de Veer"}],
                "ProductionYear": 2021,
                "Overview": "kept by the round trip",
                "Path": str(lotus),
            },
            "jf-air": {
                "Id": "jf-air",
                "Name": "Moon Safari",
                "AlbumArtists": [{"Name": "Air"}],
                "ProductionYear": 1998,
                "Path": str(agreed),
            },
            "jf-lotus-1": {"Id": "jf-lotus-1", "Name": "Aloha!Aloha!", "IndexNumber": 1,
                           "AlbumId": "jf-lotus", "Path": str(lotus / "01 Aloha!.mp3")},
            "jf-lotus-2": {"Id": "jf-lotus-2", "Name": "Pineapple Suite", "IndexNumber": 2,
                           "AlbumId": "jf-lotus", "Path": str(lotus / "02 Pineapple Suite.mp3")},
            "jf-air-1": {"Id": "jf-air-1", "Name": "La femme d'argent", "IndexNumber": 1,
                         "AlbumId": "jf-air", "Path": str(agreed / "01 La femme d'argent.mp3")},
        }

    def _of_type(self, album: bool) -> list[dict[str, object]]:
        return [
            dict(item)
            for item in self.items.values()
            if ("AlbumId" in item) is not album
        ]

    async def get_albums(self, _ids: object = None) -> list[dict[str, object]]:
        return self._of_type(album=True)

    async def get_audio_items(self, _ids: object = None) -> list[dict[str, object]]:
        return self._of_type(album=False)

    async def refresh_item_metadata(self, item_id: str) -> None:
        self.refreshed.append(item_id)

    async def get_album_tracks(self, album_id: str) -> list[dict[str, object]]:
        return [dict(item) for item in self.items.values() if item.get("AlbumId") == album_id]

    async def get_item_for_edit(self, item_id: str) -> dict[str, object]:
        return dict(self.items[item_id])

    async def update_item(self, item_id: str, payload: dict[str, object]) -> None:
        self.written[item_id] = payload
        self.items[item_id] = payload


jellyfinmeta.JellyfinClient = FakeJellyfin  # type: ignore[misc]
jellyfinmeta.SETTLE_BASE_SECONDS = 0.0
jellyfinmeta.SETTLE_PER_ALBUM_SECONDS = 0.0
jellyfinmeta.CALL_INTERVAL_SECONDS = 0.0

align = asyncio.run(jellyfinmeta.align_metadata(session))
fake = created[-1]

check("both albums compared", align["compared"] == 2, align["compared"])
check("only the doubled album is out of step", align["stale"] == 1, align["samples"])
check("the refresh is asked for first", fake.refreshed == ["jf-lotus"], fake.refreshed)
check("the album title is written back", fake.written["jf-lotus"]["Name"] == "The White Lotus",
      fake.written.get("jf-lotus"))
check("the round trip keeps the other fields",
      fake.written["jf-lotus"]["Overview"] == "kept by the round trip")
check("the doubled track is written back",
      fake.written["jf-lotus-1"]["Name"] == "Aloha!", fake.written.get("jf-lotus-1"))
check("a track Jellyfin got right is left alone", "jf-lotus-2" not in fake.written,
      sorted(fake.written))
check("an album Jellyfin got right is left alone", "jf-air" not in fake.written,
      sorted(fake.written))
check("the counts match what was written",
      align["albums_written"] == 1 and align["tracks_written"] == 1, align)


# A refresh that does work spares the direct write.
class ObedientJellyfin(FakeJellyfin):
    async def refresh_item_metadata(self, item_id: str) -> None:
        await super().refresh_item_metadata(item_id)
        self.items[item_id]["Name"] = "The White Lotus"
        self.items["jf-lotus-1"]["Name"] = "Aloha!"


jellyfinmeta.JellyfinClient = ObedientJellyfin  # type: ignore[misc]
obedient = asyncio.run(jellyfinmeta.align_metadata(session))
check("an obedient server needs no direct write",
      obedient["fixed_by_refresh"] == 1 and obedient["albums_written"] == 0, obedient)
check("nothing was written by hand", created[-1].written == {}, created[-1].written)

stored_report = jellyfinmeta.read_report(session)
check("the report is stored", stored_report.get("compared") == 2, stored_report)

# The pass queued right after a correction: one album, and the report of the
# library wide run left as it was.
lotus_row = session.execute(
    select(MetadataAlbum).where(MetadataAlbum.jellyfin_id == "jf-lotus")
).scalars().one()
jellyfinmeta.JellyfinClient = FakeJellyfin  # type: ignore[misc]
alone = asyncio.run(jellyfinmeta.align_metadata(session, album_id=lotus_row.id))
check("a single album pass looks at that album only", alone["compared"] == 1, alone)
check("it corrects it all the same",
      created[-1].written["jf-lotus"]["Name"] == "The White Lotus", created[-1].written)
check("it leaves the stored report alone",
      jellyfinmeta.read_report(session).get("compared") == 2)

check("a value written twice is recognised",
      jellyfinmeta._looks_doubled("Aloha!Aloha!", "Aloha!")
      and jellyfinmeta._looks_doubled("Dushi; Dushi", "Dushi"))
check("a different value is not a doubling",
      not jellyfinmeta._looks_doubled("Aloha", "Aloha!")
      and not jellyfinmeta._looks_doubled("Aloha!", "Aloha!"))


# A capped pass must spend its budget on the album showing its tags twice, not
# on a year that merely disagrees and that nobody would notice.
class YearOffJellyfin(FakeJellyfin):
    def __init__(self, _settings: object) -> None:
        super().__init__(_settings)
        self.items["jf-air"]["ProductionYear"] = 1996


jellyfinmeta.JellyfinClient = YearOffJellyfin  # type: ignore[misc]
jellyfinmeta.MAX_ALBUMS = 1
priority = asyncio.run(jellyfinmeta.align_metadata(session))
check("the doubled album is served before the rest",
      "jf-lotus" in created[-1].written and "jf-air" not in created[-1].written,
      sorted(created[-1].written))
check("the other one waits for the next pass", priority["left"] == 1, priority)

session.close()

print()
print("FAILURES:", failures if failures else "none")
sys.exit(1 if failures else 0)
