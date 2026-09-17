<div align="center">

# Muzikk

**A music request and download manager, in the spirit of Overseerr.**

MusicBrainz catalogue, Jellyfin authentication and library, acquisition through
Soulseek (slskd) and BitTorrent (Prowlarr + qBittorrent), automatic lossless
import and tagging.

</div>

---

## Contents

- [What Muzikk does](#what-muzikk-does)
- [Requirements](#requirements)
- [Installation](#installation)
- [First start](#first-start)
- [Configuring the services](#configuring-the-services)
- [Naming template](#naming-template)
- [How acquisition works](#how-acquisition-works)
- [Environment variables](#environment-variables)
- [Development](#development)
- [Troubleshooting](#troubleshooting)

---

## What Muzikk does

- **Search** MusicBrainz (local instance first, `musicbrainz.org` as a fallback)
  by album, artist, track or label: a label page lists its whole catalogue,
  ready to request.
- **Flags albums you already own** in the Jellyfin library: a solid green tick
  when the MBID matches, a lighter one on a fuzzy match, an amber "upgradeable"
  badge when the copy you hold is not lossless.
- **Whole-album requests** — never track by track — with optional administrator
  approval and weekly quotas per user.
- **Automatic acquisition**: providers are queried in the configured order
  (slskd, public trackers, private trackers by default). Each candidate is
  scored; below the threshold, Muzikk moves on.
- **Full import**: integrity check (`flac -t` / `ffmpeg`), exhaustive MusicBrainz
  tagging, embedded artwork and `cover.jpg`, filing in the library under a
  configurable naming template, a hardlink so seeding continues, then a Jellyfin
  rescan.
- **Artist watchlist and wishlist**: the *Watchlist* tab lists what is missing
  for followed artists — new releases only, or their whole missing discography,
  per artist. Nothing is ever downloaded without a click.
- **Track search**: a song title is enough to find the album that contains it,
  in the library and in MusicBrainz alike.
- **Playback inside Muzikk**: albums you already own play through the API rather
  than a direct Jellyfin link, with a queue, shuffle and repeat.
- **Jellyfin playlists**: those of the signed-in account can be browsed, played
  and edited from Muzikk — add a track or a whole album, remove a track, create
  or delete a list.
- **Thirty-second previews** to hear a track you do not own before requesting
  it, from Deezer then iTunes, relayed by the API.
- **Local import**: a drop zone under the home search, reserved for accounts
  that have the right, to drop an album folder or pick one from the file
  picker. Muzikk proposes MusicBrainz candidates (or accepts an MBID, or a
  manual form), writes the tags, lays down `cover.jpg` and `folder.jpg`, then
  files the tracks under the naming template. An existing copy is replaced only
  if the new one is better (lossy → lossless), after confirmation.
- **Metadata workshop** (administrators): walks the music folder for albums
  without a MusicBrainz tag, without artwork, with incomplete tags, duplicates,
  or invisible to Jellyfin; identification via the local MusicBrainz server, a
  pasted MBID or an AcoustID fingerprint; a before/after simulation, then the
  write of tags and artwork. Two extra buttons: one pairs artwork on disk so
  every album folder holds both `cover.jpg` and `folder.jpg`, the other sends
  Jellyfin the covers of albums it still shows empty.
- **Live activity** over SSE, with the full log of each request: which
  provider, which score, why a candidate was rejected.

Everything runs in **one container**: FastAPI serves the API and the React SPA,
an internal asyncio worker drains a job queue stored in SQLite. No Redis, no
Postgres.

## Requirements

| Service | Role | Required |
| --- | --- | --- |
| Jellyfin | Authentication, user list, music library, rescan | Yes |
| MusicBrainz | Catalogue (search, releases, tracks) | Recommended (public fallback otherwise) |
| slskd | Soulseek downloading | At least one provider |
| Prowlarr + qBittorrent | Torrent search and downloading | At least one provider |

A shared external Docker network — named `mediastack` in the shipped
`docker-compose.yml` — lets Muzikk reach those containers by name.

> **Volume paths must be identical from one container to the next.** If
> qBittorrent writes to `/downloads/torrents`, Muzikk has to see that same
> folder at that same path, otherwise hardlinks silently become copies (and
> files still being seeded get duplicated).

## Installation

```bash
git clone https://github.com/IxeYgrek/Muzikk.git muzikk
cd muzikk
cp .env.example .env
$EDITOR .env          # PUID/PGID, MUSIC_LIBRARY, DOWNLOADS_ROOT
docker compose pull
docker compose up -d
```

The published image is `ixeygrek/muzikk` on [Docker Hub](https://hub.docker.com/r/ixeygrek/muzikk).
Add `--build` to `docker compose up` only if you want to build from the source.

The interface is then available at `http://<host>:8383`.

The network must exist first:

```bash
docker network create mediastack   # if it does not exist yet
```

### Volumes

| Volume | Contents |
| --- | --- |
| `/config` | SQLite database, encryption key, JWT key, cover cache, logs |
| `MUSIC_LIBRARY_CONTAINER` (`/music`) | The Jellyfin library, and where imports are filed |
| `DOWNLOADS_CONTAINER` (`/downloads`) | The download root shared with slskd and qBittorrent |

The **host** paths come from `MUSIC_LIBRARY` and `DOWNLOADS_ROOT`, the paths
**inside the container** from `MUSIC_LIBRARY_CONTAINER` and
`DOWNLOADS_CONTAINER`. Those last two exist because the other containers do
not necessarily see the disks in the same place: give Muzikk the path Jellyfin
uses for the library, and the one slskd and qBittorrent use for downloads.
Mounting the same host disk twice on two different paths is fine — hardlinks
keep working, since it is still one filesystem.

## First start

Muzikk authenticates through Jellyfin: nobody can sign in until Jellyfin is
configured. A setup wizard is therefore open on the first launch, and closed
for good afterwards.

1. **Jellyfin** — the URL, for instance `http://jellyfin:8096`, and an API key
   created in Jellyfin under *Dashboard → Advanced → API keys*.
2. **Library** — tick the music libraries to watch, and give the destination
   folder for imports (`/music` by default).
3. Jellyfin users are imported. Sign in with a **Jellyfin administrator**
   account: it becomes a Muzikk administrator.

Indexing the library starts in the background. Depending on its size, expect a
few minutes before the "already owned" badges show up.

## Configuring the services

Everything is set in **Administration**, one section at a time. Each service
has a *Test connection* button that uses the values currently on screen,
including unsaved ones. Secrets are encrypted at rest (Fernet, key generated
in `/config`) and come back masked: leave a masked field alone to keep its
current value.

### Jellyfin

| Setting | Detail |
| --- | --- |
| URL / API key | As in the wizard above |
| Watched libraries | Restricts indexing to the music libraries you pick |
| Trigger a scan after import | Calls `POST /Library/Refresh` once an album is filed |
| Allow every Jellyfin user | Turn it off and only the listed user ids may sign in |

Jellyfin administrators (`Policy.IsAdministrator`) are Muzikk administrators.

### MusicBrainz

Point `url` at your local instance (`http://musicbrainz:5000`). Full-text
search needs **Solr**; without it only identifier lookups work, and Muzikk
falls back to `musicbrainz.org` if the fallback is enabled.

Rate limits are honoured separately for the local instance (10 requests per
second by default) and for the public server (1 per second, as MusicBrainz
requires).

The home page searches by album, artist, track or **label**. MusicBrainz
attaches labels to releases rather than to albums, so Muzikk walks a label's
releases and folds them back into albums. A record pressed five times shows
up once, and the five pressings still help recognise what you already own.
The counter on the label page is therefore a number of releases, larger than
the number of tiles.

### Cover art

Cover Art Archive, with a disk cache in `/config/cache`. You choose the size,
whether it is embedded in the files, and whether a `cover.jpg` and a
`folder.jpg` are written next to the tracks. Both names exist because players
disagree: Jellyfin and Kodi read either, Plex only looks at `cover.jpg`,
others only at `folder.jpg`. Writing both costs a few kilobytes and settles
the question.

For a catalogue album, Muzikk tries the release artwork then the release
group. For an album you already own, it tries in turn the Jellyfin image, a
`cover.jpg`, `folder.jpg` or `front.jpg` in the album folder, the artwork
**embedded in the tags** of the first track, and finally the Cover Art
Archive. Anything found is cached and resized.

When no source has an image — common for mashups, bootlegs and obscure
compilations — the tile shows a default disc rather than an empty frame. That
is true everywhere: album grids, track results, MusicBrainz proposals on the
Metadata page, and the player.

The *Clear the cover cache* button in the System section forces a fresh
lookup, which is handy after adding missing artwork to your library. The
cache is purged automatically when you change the service URL.

### slskd

| Setting | Detail |
| --- | --- |
| URL | `http://slskd:5030` |
| API key | From `slskd.yml`, under `web.authentication.api_keys` |
| URL prefix | Only needed when slskd runs behind a subpath |
| Download folder | The path **as Muzikk sees it**, `/downloads/slskd` by default |
| Search duration | In milliseconds — slskd reads this value as milliseconds despite its own documentation |
| Minimum peer speed / maximum queue | Filters out peers that are too slow or too busy |

Make sure the slskd API key allows the Muzikk container address in its
`cidr`.

The **download folder** is the single most often mistyped setting. slskd and
Muzikk each see the disk through their own mounts, and it is the Muzikk-side
path that belongs here. If slskd writes to
`/media/wdred/downloads/complete/soulseek` in its own container, mount the
same volume in Muzikk and enter the matching path. The slskd connection test
checks that Muzikk can read that folder and refuses to pass otherwise: a
transfer that succeeds but whose files cannot be found was downloaded for
nothing.

### Prowlarr

| Setting | Detail |
| --- | --- |
| URL | `http://prowlarr:9696` |
| API key | *Settings → General → API Key* |
| Categories | `3000` (Audio), `3010` (MP3), `3040` (Lossless) by default |
| Dedicated music search | Uses `type=music` where the indexer supports it |
| Check the `.torrent` before adding it | **Leave this on** — it is what avoids most false positives |

Once saved, go to **Indexers** and run the sync. Each indexer can then be
enabled, prioritised, classified public or private, and given a seeder
threshold of its own.

### qBittorrent

| Setting | Detail |
| --- | --- |
| URL | `http://qbittorrent:8080`, adjust if `WEBUI_PORT` differs |
| Username / password | Leave empty when authentication is disabled for the local network |
| Category | `muzikk`, created automatically |
| Download folder | The **same** path in both containers |
| Keep seeding after import | Recommended for private trackers |

Authentication changed with qBittorrent 5.2: a successful login returns an
empty `204` instead of a `200` containing `Ok.`, a wrong password returns
`401` instead of a `200` containing `Fails.`, and the session cookie was
renamed. Muzikk handles both generations. To read a failure:

- **HTTP 401** — credentials refused on qBittorrent 5.2 and later. On earlier
  versions this code usually means the `Host` header was rejected, which is
  common when reaching qBittorrent by container name: untick *Enable Host
  header validation* in *Tools → Options → Web UI*.
- **`Fails.`** — credentials refused on qBittorrent 5.1 and earlier.
- **HTTP 403** — after a few failures qBittorrent temporarily bans the
  address. Restart the container to lift it.

The alternative that avoids all of this is to tick *Bypass authentication for
clients in whitelisted IP subnets* with your Docker subnet, and leave the
username empty in Muzikk.

### Quality

Accepted lossless formats from best to worst, an optional compressed
fallback, size thresholds per track, a seeder count, a tolerance on the track
count and a **minimum score** for acceptance — 78 by default. Lower it if too
many albums fail, raise it if bad ones get through.

*Require the artist in the candidate path* rejects a release whose path names
no artist resembling the one requested. The artist is only worth 20 points
out of 100, so without this rule a namesake's album — same title, same track
count, same format — clears the threshold and can be imported instead of the
right one. The price is that a folder named after the album alone, without
its artist, is refused too: untick the rule if your sources are organised
that way.

### Provider order

Reorder the `slskd`, `public trackers` and `private trackers` groups. The
first one to offer a candidate above the threshold wins.

### Metadata

This section drives the metadata workshop, which administrators reach from
the *Metadata* entry in the menu. The analysis walks the library folder,
groups files per album and reports seven anomalies: no MusicBrainz tag, a
match that is only probable, missing artwork, incomplete tags, doubled tags,
a duplicate, and a folder Jellyfin cannot see.

| Setting | Effect |
| --- | --- |
| Nightly analysis and its hour | Re-runs the analysis every night at the given hour |
| Minimum files per album | Below it, a folder counts as loose tracks rather than an album |
| Confidence score | The score above which a proposal is presented as reliable |
| Embedded artwork / `cover.jpg` / `folder.jpg` | What gets written when you fix an album |
| AcoustID | Audio fingerprinting; needs a free API key |

The *Paste an MBID or a MusicBrainz URL* field accepts both forms. A URL
says what it points at; a bare identifier is ambiguous, so Muzikk tries it
as a release group then as a release before giving up. Search results do not
show a track count: a release group has none, the count appears once the
edition is chosen.

Nothing is written without confirmation: each album is simulated first, field
by field, before and after. Once the tags are fixed, the *Reindex Jellyfin*
button makes the server rediscover the folders it had ignored.

### Local import

The drop zone under the home search only appears if the account has the
*Import a folder* right, granted per user in *Administration → Users*.
Administrators already present when the feature landed received it; an
account created later stays without it until you turn it on.

The browser sends the files to the container (a Windows path is not readable
there). After identification — a MusicBrainz list, a pasted MBID, or tags
typed by hand — the tracks are renamed like any Muzikk import
(`Artist/Album (year)/01 Title.ext`), tagged, and the folder receives
`cover.jpg` and `folder.jpg`. If the album is already owned in lossless, the
import is refused; if it only exists as lossy and the dropped folder is
lossless, Muzikk offers to replace the old copy.

The *Doubled tags* anomaly is handled like the others, through the filter of
the same name. Some encoders append a value instead of replacing it: the
field then holds the same thing twice, which Picard shows as `Dushi; Dushi`
and players display glued together, `DushiDushi`. A field is flagged only
when it carries a single value, written several times, case ignored. As soon
as the values differ, nothing is flagged even if one of them comes back: a
medley names its parts one by one and may credit the same artist on the
first and the last, a multi-artist track keeps one identifier per performer.
Those are legitimate multi-value tags, and flagging them used to surface
healthy albums.

Tags in the repair window are shown the way Picard shows them, value by
value: a block for the album tags, the track list below, and each track
expands to every tag read in its file. A value written twice appears as-is,
in amber, separated by a semicolon — that is the only honest display,
keeping the first value would hide the problem. The simulation shows it too:
a field whose text is already correct still counts as a change, because the
rewrite clears the tags before recreating them and therefore removes the
doubling. Repair stays album by album, with the usual simulation then
confirmation. Those albums usually already carry their MusicBrainz
identifier in their tags, so no search is needed; without one, identify the
album in the window first.

*Pair up the artwork files* does not touch tags and downloads nothing: it
walks every album folder so it holds both file names players expect. If
`cover` and `folder` are already there, it skips. If only one exists, it
copies it under the other name, keeping the extension: `folder.png` yields
`cover.png`. If neither exists, the artwork embedded in the track tags is
extracted, converted to JPEG at the configured size, then written as
`cover.jpg` and `folder.jpg`. A folder with no artwork at all, neither file
nor tag, is counted separately rather than filled at random. The pass has no
side effect: running it again changes nothing. Unlike the analysis, a single
track is enough for a folder to be processed.

*Repair the Jellyfin covers* attacks the inverse problem: albums Jellyfin
shows without a cover while one sits on disk. Muzikk first asks Jellyfin to
look again, album by album, which is enough when the file was added after
the last scan. For those that stay empty, it uploads the image itself via
`POST /Items/{id}/Images/Primary`, exactly what *Edit images* in the UI
does: that path bypasses image providers and therefore works even when the
embedded-cover extractor is broken. The image comes from the folder, then
the tags, then the Cover Art Archive. The refresh never asks to replace
existing images: on a music library that option deletes `cover.jpg` files
from folders
([jellyfin#12629](https://github.com/jellyfin/jellyfin/issues/12629)).

Two implementation details are worth knowing. The upload body must be the
image **encoded as base64** with an explicit MIME type — a binary body or a
`Content-Type: image/*` returns `400 Incorrect ContentType` — and Muzikk
falls back to a binary upload if a future version changes its mind. Jellyfin
also queues the refresh and answers immediately, so Muzikk waits for the
queue to drain (20 s plus 0.4 s per album, 7 minutes at most) before
checking what is still missing.

*Align Jellyfin on the tags* fixes the most confusing symptom: tags corrected
on disk that Jellyfin keeps showing wrong. Jellyfin reads a file's tags the
first time it sees it, then trusts its own database; its default refresh
only fills what is missing, so an album named after a doubled tag keeps that
name forever. A library that writes NFO files makes it worse: the bad name
left in `album.nfo` is read before the tags.

The pass therefore compares both sides — album title, artist and year, plus
every track title and number — then proceeds as for covers: first a full
refresh (`metadataRefreshMode=FullRefresh` and `replaceAllMetadata=true`,
the only mode that rereads the files), and for what resists a direct write
via `POST /Items/{id}`, i.e. what *Edit metadata* in the UI posts: no
provider consulted, no NFO reread. The write is a read-then-send of the
whole item, because that call applies every field in the body and would
therefore wipe any field you omit. Images are never touched, for the reason
above.

The refresh is tried first on eight albums, and only extended to the rest if
it fixed at least one. On a server that ignores it — which happens as soon
as something else overwrites the tags — insisting would cost a long wait
for nothing, and worse: a refresh that finishes after our write undoes it.
The report then says so plainly, *file reread ignored by Jellyfin*, and the
pass writes directly.

Albums whose Jellyfin value is written twice go to the front of the queue,
ahead of those whose year merely diverges. Without that, a library walked
alphabetically spends its whole quota on the first letters and leaves the
defect under the letter T waiting for the next pass.

The mismatch is looked up twice on purpose. The last analysis is a cheap
filter — it already holds what each folder declares, so spotting suspects
reads no file — then the files themselves are reread and have the last
word: an analysis older than the last correction would otherwise push stale
values into Jellyfin. At most 400 albums are processed per pass, so a badly
skewed library does not become a storm of calls; a pass that leaves albums
behind enqueues the next one on its own, up to eight times, enough to align
the whole library without clicking again. The chain is bounded on purpose:
a value Jellyfin would refuse to keep cannot loop forever.

The pass is also enqueued on its own after every tag write, for that album
only: that is what removes the need to think about it after a correction.
That pass does not replace the report at the top of the page, which remains
the last full one.

The analysis runs in the worker: it continues if you change tabs or close
the page, and even survives a container restart, which requeues it.

Each analysis leaves a report at the top of the page: album folders found,
folders kept, then the fate of the others — fewer tracks than the minimum,
unreadable folder, unreadable tags. The *Albums analysed* counter also
recalls how many albums Jellyfin knows, and `/config/logs/muzikk.log` names
every skipped folder.

Each format is read according to its container: ID3 for MP3, WAV and AIFF,
iTunes atoms for MP4, Vorbis comments for FLAC, Ogg and Opus, and WM
attributes for WMA. Genre is reported when missing but is not enough to
declare an album incomplete, otherwise almost a whole library would be
flagged.

A folder whose tags resist is never lost: it is listed from its folder
name, marked *no identifier* and *incomplete tags*, and its sheet shows the
error. The report also names the first offending folders with their
message, enough to diagnose without opening a terminal.

If the analysis finds nothing at all, the page shows the exact reason
returned by the worker (empty folder, volume not mounted, insufficient
rights, track minimum too high): the path analysed is the one from
*Naming → Library folder*, which must point at the real library and not
only at the import destination.

Audio fingerprinting depends on `fpcalc`, provided by the image's
`libchromaprint-tools` package. If your image was built before that feature
existed, rebuild it.

### Player

Enables playback inside Muzikk. Click a track on an album page, or a result
in the *Tracks* tab, to start on that track; the queue stays reachable from
the player.

By default Muzikk reads the file straight from the library folder, resolving
the path even when Jellyfin sees it under a different mount point. It is
faster and depends on no Jellyfin playback policy. Untick *Read files from
the music folder* if the library is only visible to Jellyfin: the stream is
then relayed by the API, and the browser never receives a token. Exotic
formats (APE, DSF, WavPack) always go through Jellyfin, which transcodes
them.

The maximum bitrate, in bits per second, applies to that relay; `0` streams
the original file. Plays can be reported to Jellyfin under the listener's
account, which assumes they have signed in to Muzikk since playback was
enabled, so that their token has been stored.

### Playlists

The *Playlists* tab shows those of the signed-in Jellyfin account. A list
plays from Muzikk, track by track or as a whole, and can be edited: *Add to
a playlist* appears on an album page — it adds the whole album, in disc and
track order — and on every already-owned result in the *Tracks* tab. The
detail of a list lets you remove a track, and delete the list if Jellyfin
allows the listener to do so.

Everything goes through the listener's token, never the server API key: a
list belongs to an account, and the key would file them all under whoever
holds it. A list created from Muzikk is therefore an ordinary Jellyfin
playlist, visible in every client. The message *No Jellyfin session for this
account* simply means the token was not stored: sign out and back in to
Muzikk.

### Hearing a track you do not own

On the page of an album missing from the library, clicking a track plays a
thirty-second preview; the same on unowned results in the *Tracks* tab, via
the headphone button on the cover. The player then shows the *30 s preview*
chip, and the play is not reported to Jellyfin: there is no library track
behind it.

The preview comes from Deezer, whose public search needs no key and returns
an MP3, and from iTunes as a fallback. Each response is compared to the
requested artist and title: a karaoke version or a tribute band that match
the title perfectly are dropped on the artist. When neither service offers
something convincing, Muzikk says so rather than playing something else.

The audio is relayed by the API, like the library: the browser contacts
neither Deezer nor Apple, and the cover shown remains the one Muzikk already
displayed. Untick *Offer thirty second extracts* in the player settings so
the server no longer talks to those two services at all.

## Naming template

The default template reproduces the usual Picard script:

```
{albumartist}/{album} ({year})/{disc_prefix}{track:02} {artist_prefix}{title}
```

which gives `Daft Punk/Discovery (2001)/03 Digital Love.flac`.

| Variable | Value |
| --- | --- |
| `{albumartist}` `{artist}` | Album artist / track artist |
| `{album}` `{title}` | Album title / track title |
| `{year}` `{date}` | Year, full release date |
| `{track}` `{disc}` `{totaldiscs}` | Numbers; `{track:02}` pads to two digits |
| `{disc_prefix}` | Empty on a single disc, `1-` otherwise, `01-` beyond nine discs |
| `{artist_prefix}` | Empty, except on a multi-artist album where it becomes `Artist - ` |
| `{ext}` | File extension, appended automatically when absent |

The preview updates as you type, on three representative examples: a plain
album, a multi-disc box set and a compilation.

> Soulseek downloads are hardlinked then tagged in place. Torrents are
> **copied** before tagging: rewriting the tags of a file still being seeded
> would corrupt it in the tracker's eyes.

## How acquisition works

```
request → (approval) → search → candidate chosen → download
        → verification → tagging → import → Jellyfin rescan
```

Before searching anything, Muzikk inspects the slskd download folder: if the
album already sits there complete, it is imported directly, without going
back to the network. That candidate folder is scored exactly like a remote
one — format, track count, titles, size per track — so a partial download or
a different album cannot be picked up by mistake. This is what avoids
re-downloading an album whose import failed for a configuration reason.

Then, for each provider, in the configured order:

1. Search from the artist, the normalised title, the year and the track
   count. Up to four wordings are tried, each dropping something the peer
   may not have written: the release type first — Soulseek only answers when
   **every** word appears in the path, so searching "Pharaoh EP" never finds
   a folder named "Eekoz - Pharaoh" — then edition mentions. The bare title,
   without the artist, goes last: it is the only wording that returns
   hundreds of unrelated folders, and asking it early used to fill the
   candidate list before the wordings that name the artist had their turn.
2. Score each candidate: artist and title similarity with `rapidfuzz`, after
   stripping accents, punctuation and mentions like "deluxe" or "remaster";
   track count match; track title coverage; detected format; consistency of
   the size per track; seeders or peer speed.
3. For torrents the `.torrent` is fetched and **its file list is read
   before** it is handed to qBittorrent. For slskd, results are grouped per
   remote folder, and a folder holding a single audio file is discarded —
   an isolated track named after the album is not the album. Unless
   MusicBrainz says the release has one track, in which case one file is
   enough; otherwise the release was thrown away before it was even scored.
4. The best candidate above the threshold is queued; otherwise Muzikk moves
   to the next provider. If they all fail, the request is marked failed and
   retried later on its own.

Each request keeps every candidate it evaluated, with its score and the
reason it was rejected, readable from the **Requests** page.

Three bulk actions sit at the top of that page, each acting on the whole
matching list rather than the rows on screen: clear imported requests, clear
failed ones, cancel the active ones. A cancel does not stop the transfer at
that instant: the pipeline notices at its next progress check and then
abandons the download in progress.

### Approving an upgrade before the old version is deleted

An upgrade almost always lands in the very folder it improves, since the
naming scheme yields the same artist, album and year. The old MP3s and the
new FLACs end up side by side in one folder, which is exactly what makes
deleting that folder unsafe.

So at the end of an upgrade import, Muzikk records both versions file by
file — format, resolution, bitrate, duration, size — and puts the request in
the **To approve** state without deleting anything. The requester or an
administrator opens it, compares the two columns, then chooses:

- **Approve** deletes the old audio files only, keeping the folder artwork
  and the tracks that were just written. If the new folder is elsewhere, the
  old one goes entirely.
- **Reject** does the opposite: the freshly imported files are removed and
  the old version stays. Only the folder artwork, rewritten on import,
  cannot be restored.

The record of the old files is taken **before** the new ones are placed,
otherwise a file of the same name and extension would be overwritten along
with the proof of what it was. A file replaced that way is never offered
for deletion: it already holds the new version.

The setting *Ask for a validation before deleting the old copy* (Naming
section) turns this step off and makes the deletion immediate again, now
also covering the old files of a shared folder, which it did not before.
And *Delete the old copy after an upgrade*, if turned off, still keeps
everything without asking.

### Following an artist without downloading anything

Following an artist triggers no download. The periodic check compares their
MusicBrainz discography to the library and records what is missing; the
**Watchlist** tab shows it, and every album waits for a click. That is
deliberate: auto-downloading the new releases of a few dozen followed
artists fills the disk with records nobody asked for.

Each followed artist has its own scope, set on its row:

- **New releases** shows only the last 400 days.
- **Discography** shows everything missing, regardless of year.

Albums, EPs and singles count in both cases, a chip on the cover reminding
you what it is when it is not an album. Compilations, live albums, remixes
and other secondary types are left out: you follow an artist for their
discography, not their reissues. Changing the scope reruns a check, since
the list depends on it.

The list can be filtered by artist, or to new releases only. The crossed-out
eye on a cover sets the album aside: it moves to *Ignored* and only comes
back if you restore it, even after a new check. An album disappears on its
own once the library contains it.

The **wishlist** remains a hand-kept list, fed by the *Add to wishlist*
button on an album page. It no longer retries anything on its own: *Check*
simply clears the entries the library now holds, and each row keeps its own
request button.

## Environment variables

Only infrastructure and paths go through the environment; everything else is
configured in the interface.

| Variable | Default | Role |
| --- | --- | --- |
| `PUID` / `PGID` | `1000` | Owner of the files Muzikk writes; must match the library |
| `UMASK` | `002` | Mask applied to imported files |
| `TZ` | `Europe/Paris` | Container time zone |
| `MUZIKK_PORT` | `8383` | HTTP port |
| `MUZIKK_CONFIG_DIR` | `/config` | Database, keys, cache, logs |
| `MUZIKK_STATIC_DIR` | `/app/static` | The compiled interface |
| `MUZIKK_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` |
| `MUZIKK_WORKER_CONCURRENCY` | `2` | Jobs handled in parallel, 1 to 8 |
| `MUZIKK_SESSION_HOURS` | `336` | How long a session stays valid |

In the compose file, `MUSIC_LIBRARY` and `DOWNLOADS_ROOT` are the **host**
paths, `MUSIC_LIBRARY_CONTAINER` and `DOWNLOADS_CONTAINER` the matching paths
**inside the container**.

## Development

Backend:

```bash
python -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
MUZIKK_CONFIG_DIR=./config .venv/bin/uvicorn muzikk.main:app --reload --app-dir backend --port 8383
```

Frontend:

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173, /api is proxied to port 8383
```

Quick checks, without Node or Docker:

```bash
.venv/bin/python -m ruff check backend        # lint
.venv/bin/python backend/smoke_test.py        # startup, routes and auth guards
.venv/bin/python backend/pipeline_test.py     # naming, matching, file/track pairing
.venv/bin/python backend/artwork_test.py      # artwork resolution
.venv/bin/python backend/metadata_test.py     # library analysis and tag reading
.venv/bin/python backend/local_import_test.py # local folder import
.venv/bin/python backend/playback_test.py     # file lookup and Range requests
.venv/bin/python frontend/check_frontend.py   # imports and translation keys
```

An Alembic migration is generated with:

```bash
cd backend && alembic revision --autogenerate -m "description"
```

Migrations are applied automatically at startup. On an empty database the
schema is created and then stamped at the latest revision.

## Troubleshooting

**"Search returns nothing"** — the local MusicBrainz instance most likely has
no Solr. The connection test says so explicitly. Enable the public fallback
in the meantime.

**"No candidate is ever accepted"** — open the request: every candidate
evaluated shows its score and the reason it was rejected. The usual causes
are a different track count — the wrong MusicBrainz edition was picked, so
force another one from the album page — a score that is just too low, so
lower the threshold in *Quality*, or not enough seeders.

**"The same album is downloaded over and over"** — the request log then
contains `the downloaded files could not be located on disk`. slskd did
fetch the album, but Muzikk cannot find the files and treats the candidate
as a failure. Fix the **download folder** in the slskd section (see above)
and retry the request: the files already there are imported without being
downloaded again. Muzikk now stops the request immediately in this case
rather than trying the next candidates, and schedules no automatic retry
until the configuration is corrected.

**"Files are copied instead of hardlinked"** — the `/downloads` and `/music`
paths must be on the **same filesystem** and mounted at the same location in
every container. A separate network mount forces a copy.

**"Jellyfin does not see the new albums"** — check `PUID`/`PGID` and
`UMASK`: Jellyfin has to be able to read the files. The automatic rescan can
also be turned off in the Jellyfin settings. If a folder stays invisible
despite a rescan, it appears in *Metadata* under "Missing from Jellyfin" —
almost always an album without an `album` or `albumartist` tag, which the
media server cannot classify. Fix the tags from that page, then reindex.
Matching tries the exact path, then the last two path segments, then the
MusicBrainz identifier — so Jellyfin can rename an album without losing it
— and the name as a last resort.

**"Playback does not start"** — the player now shows the exact reason
returned by the server next to "Cannot play". The *Player* section must be
enabled and, if direct access is off, Jellyfin has to be reachable from the
container. An account that signed in before playback was enabled has no
stored token yet, so the play falls back to the server API key and is not
credited; signing out and back in is enough.

**"I cannot sign in"** — Muzikk stores no password, so the failure comes
from Jellyfin. Check that the user is active in Muzikk under
*Administration → Users*, and that the Jellyfin API key is still valid.

Detailed logs live in `/config/logs/muzikk.log` and in
`docker compose logs -f muzikk`. Both receive the same thing; an earlier
version let Alembic take over the logging configuration at startup, which
stopped writing the file right after the migrations.
