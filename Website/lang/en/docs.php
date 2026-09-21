<?php
/**
 * The documentation page.
 *
 * Each section becomes an entry in the table of contents on its own. A block is
 * one of: p, h3, list, code, table, note, warning.
 */

declare(strict_types=1);

return [
    'title' => 'Documentation',
    'lead' => 'Installing Muzikk, pointing it at your services, and getting the paths right — which is '
        . 'where almost every problem actually comes from.',
    'tocTitle' => 'On this page',
    'copy' => 'Copy',
    'copied' => 'Copied',

    // Used by the footer, which links to a few sections directly.
    'nav' => [
        'requirements' => 'Requirements',
        'install' => 'Installation',
        'services' => 'Configuring the services',
        'troubleshooting' => 'Troubleshooting',
    ],

    'sections' => [
        [
            'id' => 'overview',
            'title' => 'How it is put together',
            'blocks' => [
                ['type' => 'p', 'text' => 'Everything runs in a <strong>single container</strong>. FastAPI serves '
                    . 'both the API and the compiled React interface, and an internal asyncio worker drains a job '
                    . 'queue stored in SQLite. There is no Redis and no Postgres to provision.'],
                ['type' => 'p', 'text' => 'On first launch you choose, once and for good, whether '
                    . '<strong>Jellyfin</strong> owns the accounts and the music library, or whether '
                    . '<strong>Muzikk</strong> handles both itself. In Jellyfin mode, authentication is '
                    . 'delegated to it and accounts are imported from it. In local mode, passwords live in '
                    . 'SQLite and the library is scanned from the folder you mount. Secrets you enter — '
                    . 'API keys, the qBittorrent password — are encrypted at rest with a Fernet key generated '
                    . 'in <code>/config</code>, and are returned masked by the API.'],
                ['type' => 'note', 'text' => 'The interface listens on port <code>8383</code> by default, so '
                    . 'once the container is up it answers on <code>http://your-host:8383</code>.'],
            ],
        ],
        [
            'id' => 'requirements',
            'title' => 'Requirements',
            'blocks' => [
                ['type' => 'table', 'head' => ['Service', 'Role', 'Required'], 'rows' => [
                    ['Jellyfin', 'Authentication, user list, music library, rescan — when that mode is chosen', 'Optional: skip it and run fully local'],
                    ['MusicBrainz', 'Catalogue: search, releases, tracklists', 'Recommended — the public server is used as a fallback'],
                    ['slskd', 'Soulseek downloading', 'At least one provider'],
                    ['Prowlarr + qBittorrent', 'Torrent search and downloading', 'At least one provider'],
                ]],
                ['type' => 'p', 'text' => 'A shared external Docker network — named <code>mediastack</code> in the '
                    . 'compose file that ships with the project — lets Muzikk reach those containers by name.'],
                ['type' => 'warning', 'text' => '<strong>Volume paths must be identical from one container to the '
                    . 'next.</strong> If qBittorrent writes to <code>/downloads/torrents</code>, Muzikk has to see '
                    . 'that same folder at that same path, otherwise hardlinks silently become copies and files '
                    . 'still being seeded get duplicated.'],
            ],
        ],
        [
            'id' => 'install',
            'title' => 'Installation',
            'blocks' => [
                ['type' => 'code', 'lang' => 'bash', 'body' => <<<'CODE'
docker network create mediastack   # if it does not exist yet

git clone https://github.com/IxeYgrek/Muzikk.git muzikk
cd muzikk
cp .env.example .env
$EDITOR .env          # PUID/PGID, MUSIC_LIBRARY, DOWNLOADS_ROOT
docker compose pull
docker compose up -d
CODE],
                ['type' => 'p', 'text' => 'Compose pulls <code>ixeygrek/muzikk</code> from Docker Hub. Add '
                    . '<code>--build</code> to <code>docker compose up</code> only if you want to build from the '
                    . 'cloned source. The image is also available on its own: '
                    . '<code>docker pull ixeygrek/muzikk:0.1.0</code>.'],
                ['type' => 'p', 'text' => 'The interface is then available on <code>http://your-host:8383</code>.'],
                ['type' => 'h3', 'text' => 'Volumes'],
                ['type' => 'table', 'head' => ['Volume', 'Contents'], 'rows' => [
                    ['<code>/config</code>', 'SQLite database, encryption key, JWT key, cover cache, logs'],
                    ['<code>MUSIC_LIBRARY_CONTAINER</code> (<code>/music</code>)', 'The music library, and where imports are filed'],
                    ['<code>DOWNLOADS_CONTAINER</code> (<code>/downloads</code>)', 'The download root shared with slskd and qBittorrent'],
                ]],
                ['type' => 'p', 'text' => 'The <strong>host</strong> paths come from <code>MUSIC_LIBRARY</code> and '
                    . '<code>DOWNLOADS_ROOT</code>, the paths <strong>inside the container</strong> from '
                    . '<code>MUSIC_LIBRARY_CONTAINER</code> and <code>DOWNLOADS_CONTAINER</code>. Those last two '
                    . 'exist because the other containers do not necessarily see the disks in the same place: give '
                    . 'Muzikk the path your library uses — the one Jellyfin uses, if Jellyfin is in the stack — '
                    . 'and the one slskd and qBittorrent use for '
                    . 'downloads. Mounting the same host disk twice on two different paths is perfectly fine — '
                    . 'hardlinks keep working, since it is still one filesystem.'],
                ['type' => 'h3', 'text' => 'The compose file'],
                ['type' => 'code', 'lang' => 'yaml', 'body' => <<<'CODE'
services:
  muzikk:
    build:
      context: .
      dockerfile: Dockerfile
    image: muzikk:latest
    container_name: muzikk
    restart: unless-stopped
    environment:
      PUID: ${PUID:-1000}
      PGID: ${PGID:-1000}
      UMASK: ${UMASK:-002}
      TZ: ${TZ:-Europe/Paris}
      MUZIKK_PORT: 8383
      MUZIKK_LOG_LEVEL: ${MUZIKK_LOG_LEVEL:-INFO}
    ports:
      - "${MUZIKK_PORT:-8383}:8383"
    volumes:
      - ${MUZIKK_CONFIG:-./config}:/config
      - ${MUSIC_LIBRARY:?set MUSIC_LIBRARY in .env}:${MUSIC_LIBRARY_CONTAINER:-/music}
      - ${DOWNLOADS_ROOT:?set DOWNLOADS_ROOT in .env}:${DOWNLOADS_CONTAINER:-/downloads}
    extra_hosts:
      - "host.docker.internal:host-gateway"
    networks:
      - mediastack

networks:
  mediastack:
    external: true
CODE],
            ],
        ],
        [
            'id' => 'first-run',
            'title' => 'First start',
            'blocks' => [
                ['type' => 'p', 'text' => 'A setup wizard is open on the very first launch, and closed for good '
                    . 'afterwards. The first question cannot be revisited: how accounts and the library are managed.'],
                ['type' => 'list', 'ordered' => true, 'items' => [
                    '<strong>Mode</strong> — <em>With Jellyfin</em>, or <em>Local only</em>. This choice is '
                        . 'permanent for the installation.',
                    '<strong>With Jellyfin</strong> — the URL, for instance <code>http://jellyfin:8096</code>, and an '
                        . 'API key created in Jellyfin under <em>Dashboard → Advanced → API keys</em>. Tick the music '
                        . 'libraries to watch, and give the destination folder for imports, <code>/music</code> by '
                        . 'default. Jellyfin users are then imported. Sign in with a <strong>Jellyfin administrator</strong> '
                        . 'account: it becomes a Muzikk administrator.',
                    '<strong>Local only</strong> — create the first administrator (username and password), and give '
                        . 'the library folder as the container sees it, typically the volume mounted on '
                        . '<code>/music</code>. Sign in with that account afterwards. Playlists are not available in '
                        . 'this mode, because they live on Jellyfin.',
                ]],
                ['type' => 'p', 'text' => 'Indexing the library starts in the background. Depending on its size, '
                    . 'expect a few minutes before the "already owned" badges show up.'],
            ],
        ],
        [
            'id' => 'services',
            'title' => 'Configuring the services',
            'blocks' => [
                ['type' => 'p', 'text' => 'Everything is set in <strong>Administration</strong>, one section at a '
                    . 'time. Each service has a <em>Test connection</em> button that uses the values currently on '
                    . 'screen, including the ones you have not saved yet. Secrets come back masked: leave a masked '
                    . 'field alone to keep its current value.'],

                ['type' => 'h3', 'text' => 'Jellyfin'],
                ['type' => 'p', 'text' => 'These settings apply when the installation runs <strong>with Jellyfin</strong>. '
                    . 'They are unused in local mode.'],
                ['type' => 'table', 'head' => ['Setting', 'Detail'], 'rows' => [
                    ['URL / API key', 'As in the wizard above'],
                    ['Watched libraries', 'Restricts indexing to the music libraries you pick'],
                    ['Trigger a scan after import', 'Calls <code>POST /Library/Refresh</code> once an album is filed'],
                    ['Allow every Jellyfin user', 'Turn it off and only the listed user ids may sign in'],
                ]],
                ['type' => 'p', 'text' => 'In Jellyfin mode, Jellyfin administrators — <code>Policy.IsAdministrator</code> — are '
                    . 'Muzikk administrators, and that status is refreshed at each sign-in and each user sync.'],

                ['type' => 'h3', 'text' => 'MusicBrainz'],
                ['type' => 'p', 'text' => 'Point the URL at your local instance, for example '
                    . '<code>http://musicbrainz:5000</code>. Full-text search needs <strong>Solr</strong>; without '
                    . 'it only identifier lookups work, and Muzikk falls back to musicbrainz.org if the fallback is '
                    . 'enabled. Rate limits are honoured separately for the local instance (10 requests per second '
                    . 'by default) and for the public server (1 per second, as MusicBrainz requires).'],
                ['type' => 'p', 'text' => 'Label pages deserve a word: MusicBrainz attaches labels to releases '
                    . 'rather than to albums, so Muzikk walks a label\'s releases and folds them back into albums. '
                    . 'A record pressed five times shows up once, and the five pressings still help recognise what '
                    . 'you already own. The counter on the label page is therefore a number of releases, larger '
                    . 'than the number of tiles.'],

                ['type' => 'h3', 'text' => 'Cover art'],
                ['type' => 'p', 'text' => 'Artwork comes from the Cover Art Archive and is cached in '
                    . '<code>/config/cache</code>. You choose the size, whether it is embedded in the files, and '
                    . 'whether a <code>cover.jpg</code> and a <code>folder.jpg</code> are written next to the '
                    . 'tracks. Both names exist because players disagree: Jellyfin and Kodi read either, Plex only '
                    . 'looks at <code>cover.jpg</code>, others only at <code>folder.jpg</code>. Writing both costs '
                    . 'a few kilobytes and settles the question.'],
                ['type' => 'p', 'text' => 'For a catalogue album, Muzikk tries the release artwork then the release '
                    . 'group. For an album you already own, it tries in turn the Jellyfin image, a '
                    . '<code>cover.jpg</code>, <code>folder.jpg</code> or <code>front.jpg</code> in the album '
                    . 'folder, the artwork <strong>embedded in the tags</strong> of the first track, and finally '
                    . 'the Cover Art Archive. Anything found is cached and resized.'],
                ['type' => 'p', 'text' => 'The <em>Clear the cover cache</em> button in the System section forces a '
                    . 'fresh lookup, which is handy after adding missing artwork to your library. The cache is '
                    . 'purged automatically when you change the service URL.'],

                ['type' => 'h3', 'text' => 'slskd'],
                ['type' => 'table', 'head' => ['Setting', 'Detail'], 'rows' => [
                    ['URL', '<code>http://slskd:5030</code>'],
                    ['API key', 'From <code>slskd.yml</code>, under <code>web.authentication.api_keys</code>'],
                    ['URL prefix', 'Only needed when slskd runs behind a subpath'],
                    ['Download folder', 'The path <strong>as Muzikk sees it</strong>, <code>/downloads/slskd</code> by default'],
                    ['Search duration', 'In milliseconds — slskd reads this value as milliseconds despite its own documentation'],
                    ['Minimum peer speed / maximum queue', 'Filters out peers that are too slow or too busy'],
                ]],
                ['type' => 'p', 'text' => 'Make sure the slskd API key allows the Muzikk container address in its '
                    . '<code>cidr</code>.'],
                ['type' => 'warning', 'text' => 'The <strong>download folder</strong> is the single most often '
                    . 'mistyped setting. slskd and Muzikk each see the disk through their own mounts, and it is the '
                    . 'Muzikk-side path that belongs here. The connection test checks that Muzikk can read that '
                    . 'folder and refuses to pass otherwise: a transfer that succeeds but whose files cannot be '
                    . 'found was downloaded for nothing.'],

                ['type' => 'h3', 'text' => 'Prowlarr'],
                ['type' => 'table', 'head' => ['Setting', 'Detail'], 'rows' => [
                    ['URL', '<code>http://prowlarr:9696</code>'],
                    ['API key', '<em>Settings → General → API Key</em>'],
                    ['Categories', '<code>3000</code> (Audio), <code>3010</code> (MP3), <code>3040</code> (Lossless) by default'],
                    ['Dedicated music search', 'Uses <code>type=music</code> where the indexer supports it'],
                    ['Check the <code>.torrent</code> before adding it', '<strong>Leave this on</strong> — it is what avoids most false positives'],
                ]],
                ['type' => 'p', 'text' => 'Once saved, go to <strong>Indexers</strong> and run the sync. Each '
                    . 'indexer can then be enabled, prioritised, classified public or private, and given a seeder '
                    . 'threshold of its own.'],

                ['type' => 'h3', 'text' => 'qBittorrent'],
                ['type' => 'table', 'head' => ['Setting', 'Detail'], 'rows' => [
                    ['URL', '<code>http://qbittorrent:8080</code>, adjust if <code>WEBUI_PORT</code> differs'],
                    ['Username / password', 'Leave empty when authentication is disabled for the local network'],
                    ['Category', '<code>muzikk</code>, created automatically'],
                    ['Download folder', 'The <strong>same</strong> path in both containers'],
                    ['Keep seeding after import', 'Recommended for private trackers'],
                ]],
                ['type' => 'p', 'text' => 'Authentication changed with qBittorrent 5.2: a successful login returns '
                    . 'an empty <code>204</code> instead of a <code>200</code> containing <code>Ok.</code>, a wrong '
                    . 'password returns <code>401</code> instead of a <code>200</code> containing '
                    . '<code>Fails.</code>, and the session cookie was renamed. Muzikk handles both generations. To '
                    . 'read a failure:'],
                ['type' => 'list', 'items' => [
                    '<strong>HTTP 401</strong> — credentials refused on qBittorrent 5.2 and later. On earlier '
                        . 'versions this code usually means the <code>Host</code> header was rejected, which is '
                        . 'common when reaching qBittorrent by container name: untick <em>Enable Host header '
                        . 'validation</em> in <em>Tools → Options → Web UI</em>.',
                    '<strong><code>Fails.</code></strong> — credentials refused on qBittorrent 5.1 and earlier.',
                    '<strong>HTTP 403</strong> — after a few failures qBittorrent temporarily bans the address. '
                        . 'Restart the container to lift it.',
                ]],
                ['type' => 'p', 'text' => 'The alternative that avoids all of this is to tick <em>Bypass '
                    . 'authentication for clients in whitelisted IP subnets</em> with your Docker subnet, and leave '
                    . 'the username empty in Muzikk.'],

                ['type' => 'h3', 'text' => 'Quality'],
                ['type' => 'p', 'text' => 'Accepted lossless formats from best to worst, an optional compressed '
                    . 'fallback, size thresholds per track, a seeder count, a tolerance on the track count and a '
                    . '<strong>minimum score</strong> for acceptance — 78 by default. Lower it if too many albums '
                    . 'fail, raise it if bad ones get through.'],
                ['type' => 'p', 'text' => '<em>Require the artist in the candidate path</em> rejects a release whose '
                    . 'path names no artist resembling the one requested. The artist is only worth 20 points out of '
                    . '100, so without this rule a namesake\'s album — same title, same track count, same format — '
                    . 'clears the threshold and can be imported instead of the right one. The price is that a '
                    . 'folder named after the album alone, without its artist, is refused too: untick the rule if '
                    . 'your sources are organised that way.'],

                ['type' => 'h3', 'text' => 'Provider order'],
                ['type' => 'p', 'text' => 'Reorder the <code>slskd</code>, <code>public trackers</code> and '
                    . '<code>private trackers</code> groups. The first one to offer a candidate above the threshold '
                    . 'wins, and the others are never queried.'],

                ['type' => 'h3', 'text' => 'Metadata'],
                ['type' => 'p', 'text' => 'This section drives the metadata workshop, which administrators reach '
                    . 'from the <em>Metadata</em> entry in the menu. The analysis walks the library folder, groups '
                    . 'files per album and reports seven anomalies: no MusicBrainz tag, a match that is only '
                    . 'probable, missing artwork, incomplete tags, doubled tags, a duplicate, and — in Jellyfin '
                    . 'mode — a folder Jellyfin cannot see.'],
                ['type' => 'table', 'head' => ['Setting', 'Effect'], 'rows' => [
                    ['Nightly analysis and its hour', 'Re-runs the analysis every night at the given hour'],
                    ['Minimum files per album', 'Below it, a folder counts as loose tracks rather than an album'],
                    ['Confidence score', 'The score above which a proposal is presented as reliable'],
                    ['Embedded artwork / <code>cover.jpg</code> / <code>folder.jpg</code>', 'What gets written when you fix an album'],
                    ['AcoustID', 'Audio fingerprinting; needs a free API key'],
                ]],
                ['type' => 'p', 'text' => 'Nothing is written without confirmation: each album is simulated first, '
                    . 'field by field, before and after. In Jellyfin mode, once the tags are fixed, the '
                    . '<em>Reindex Jellyfin</em> button makes the server rediscover the folders it had ignored.'],
                ['type' => 'p', 'text' => 'Audio fingerprinting relies on <code>fpcalc</code>, provided by the '
                    . 'image\'s <code>libchromaprint-tools</code> package. If your image was built before that '
                    . 'feature existed, rebuild it.'],

                ['type' => 'h3', 'text' => 'Player'],
                ['type' => 'p', 'text' => 'By default Muzikk reads the file straight from the library folder. In '
                    . 'Jellyfin mode it still resolves the path when Jellyfin sees the library under a different '
                    . 'mount point. Direct reads are faster and depend on no Jellyfin playback policy. Untick '
                    . '<em>Read files from the music folder</em> if the library is only visible to Jellyfin: the '
                    . 'stream is then relayed by the API, and the browser never receives a token. Exotic formats '
                    . '— APE, DSF, WavPack — are transcoded with ffmpeg in local mode, and through Jellyfin when '
                    . 'that mode is chosen.'],
                ['type' => 'p', 'text' => 'The maximum bitrate, in bits per second, applies to that relay; '
                    . '<code>0</code> streams the original file. In Jellyfin mode, plays can be reported under the '
                    . 'listener\'s account, which assumes they have signed in to Muzikk since playback was enabled, '
                    . 'so that their token has been stored.'],

                ['type' => 'h3', 'text' => 'Users and permissions'],
                ['type' => 'p', 'text' => 'In Jellyfin mode, accounts come from Jellyfin. In local mode, they are '
                    . 'created in Muzikk by an administrator. For each one you grant, independently: '
                    . '<em>Account active</em>, <em>Request albums</em>, <em>Upgrade to lossless</em> and '
                    . '<em>Import a folder</em>. <em>Automatic approval</em> is a three-way choice — follow the '
                    . 'global setting, always, or never — and the weekly quota is a number, zero meaning '
                    . 'unlimited. Administrators bypass permissions and quotas.'],
                ['type' => 'note', 'text' => 'In Jellyfin mode, administrator status is not editable here on purpose: '
                    . 'it is read from Jellyfin at every sign-in and every user sync, so it would be overwritten '
                    . 'anyway. In local mode, administrators are managed in Muzikk itself.'],
            ],
        ],
        [
            'id' => 'naming',
            'title' => 'Naming template',
            'blocks' => [
                ['type' => 'p', 'text' => 'The default template reproduces the usual Picard script:'],
                ['type' => 'code', 'lang' => 'text', 'body' => '{albumartist}/{album} ({year})/{disc_prefix}{track:02} {artist_prefix}{title}'],
                ['type' => 'p', 'text' => 'which gives <code>Daft Punk/Discovery (2001)/03 Digital Love.flac</code>.'],
                ['type' => 'table', 'head' => ['Variable', 'Value'], 'rows' => [
                    ['<code>{albumartist}</code> <code>{artist}</code>', 'Album artist / track artist'],
                    ['<code>{album}</code> <code>{title}</code>', 'Album title / track title'],
                    ['<code>{year}</code> <code>{date}</code>', 'Year, full release date'],
                    ['<code>{track}</code> <code>{disc}</code> <code>{totaldiscs}</code>', 'Numbers; <code>{track:02}</code> pads to two digits'],
                    ['<code>{disc_prefix}</code>', 'Empty on a single disc, <code>1-</code> otherwise, <code>01-</code> beyond nine discs'],
                    ['<code>{artist_prefix}</code>', 'Empty, except on a multi-artist album where it becomes <code>Artist - </code>'],
                    ['<code>{ext}</code>', 'File extension, appended automatically when absent'],
                ]],
                ['type' => 'p', 'text' => 'The preview updates as you type, on three representative examples: a '
                    . 'plain album, a multi-disc box set and a compilation.'],
                ['type' => 'note', 'text' => 'Soulseek downloads are hardlinked then tagged in place. Torrents are '
                    . '<strong>copied</strong> before tagging: rewriting the tags of a file still being seeded would '
                    . 'corrupt it in the tracker\'s eyes.'],
            ],
        ],
        [
            'id' => 'acquisition',
            'title' => 'How acquisition works',
            'blocks' => [
                ['type' => 'code', 'lang' => 'text', 'body' => <<<'CODE'
request → (approval) → search → candidate chosen → download
        → verification → tagging → import → library index (and Jellyfin rescan when in that mode)
CODE],
                ['type' => 'p', 'text' => 'Before searching anything, Muzikk inspects the slskd download folder: if '
                    . 'the album already sits there complete, it is imported directly, without going back to the '
                    . 'network. That candidate folder is scored exactly like a remote one — format, track count, '
                    . 'titles, size per track — so a partial download or a different album cannot be picked up by '
                    . 'mistake. This is what avoids re-downloading an album whose import failed for a '
                    . 'configuration reason.'],
                ['type' => 'p', 'text' => 'Then, for each provider, in the configured order:'],
                ['type' => 'list', 'ordered' => true, 'items' => [
                    'Search from the artist, the normalised title, the year and the track count. Up to four '
                        . 'wordings are tried, each dropping something the peer may not have written: the release '
                        . 'type first — Soulseek only answers when <strong>every</strong> word appears in the path, '
                        . 'so searching "Pharaoh EP" never finds a folder named "Eekoz - Pharaoh" — then edition '
                        . 'mentions. The title is never asked without its artist: that wording is what used to '
                        . 'return hundreds of unrelated folders.',
                    'Score each candidate: artist and title similarity with <code>rapidfuzz</code>, after stripping '
                        . 'accents, punctuation and mentions like "deluxe" or "remaster"; track count match; track '
                        . 'title coverage; detected format; consistency of the size per track; seeders or peer speed.',
                    'For torrents the <code>.torrent</code> is fetched and <strong>its file list read before</strong> '
                        . 'it is handed to qBittorrent. For slskd, results are grouped per remote folder, and a '
                        . 'folder holding a single audio file is discarded — an isolated track named after the album '
                        . 'is not the album. Unless MusicBrainz says the release has one track, in which case one '
                        . 'file is enough.',
                    'The best candidate above the threshold is queued; otherwise Muzikk moves to the next provider. '
                        . 'If they all fail, the request is marked failed and retried later on its own.',
                ]],
                ['type' => 'p', 'text' => 'Each request keeps every candidate it evaluated, with its score and the '
                    . 'reason it was rejected, readable from the <strong>Requests</strong> page. Bulk actions at the '
                    . 'top of that page clear imported requests, clear failed ones, retry every failure at once, or '
                    . 'cancel the active ones — each acting on the whole matching list, not only the rows on screen.'],
                ['type' => 'h3', 'text' => 'Approving an upgrade before the old version is deleted'],
                ['type' => 'p', 'text' => 'An upgrade almost always lands in the very folder it improves, since the '
                    . 'naming scheme yields the same artist, album and year. The old MP3s and the new FLACs end up '
                    . 'side by side in one folder, which is exactly what makes deleting that folder unsafe.'],
                ['type' => 'p', 'text' => 'So at the end of an upgrade import, Muzikk records both versions file by '
                    . 'file — format, resolution, bitrate, duration, size — and puts the request in the <strong>To '
                    . 'approve</strong> state without deleting anything. The requester or an administrator opens it, '
                    . 'compares the two columns, plays either side, then chooses:'],
                ['type' => 'list', 'items' => [
                    '<strong>Approve</strong> deletes the old audio files only, keeping the folder artwork and the '
                        . 'tracks that were just written. If the new folder is elsewhere, the old one goes entirely.',
                    '<strong>Reject</strong> does the opposite: the freshly imported files are removed and the old '
                        . 'version stays. Only the folder artwork, rewritten on import, cannot be restored.',
                ]],
                ['type' => 'p', 'text' => 'The setting <em>Ask for a validation before deleting the old copy</em>, in '
                    . 'the Naming section, turns this step off and makes the deletion immediate again.'],
                ['type' => 'h3', 'text' => 'Following an artist without downloading anything'],
                ['type' => 'p', 'text' => 'Following an artist triggers no download. The periodic check compares '
                    . 'their MusicBrainz discography to the library and records what is missing; the '
                    . '<strong>Watchlist</strong> tab shows it, and every album waits for a click. Each followed '
                    . 'artist has its own scope: <em>New releases</em> shows only the last 400 days, '
                    . '<em>Discography</em> shows everything missing. Albums, EPs and singles count in both cases; '
                    . 'compilations, live albums and remixes are left out.'],
            ],
        ],
        [
            'id' => 'environment',
            'title' => 'Environment variables',
            'blocks' => [
                ['type' => 'p', 'text' => 'Only infrastructure and paths go through the environment; everything else '
                    . 'is configured in the interface.'],
                ['type' => 'table', 'head' => ['Variable', 'Default', 'Role'], 'rows' => [
                    ['<code>PUID</code> / <code>PGID</code>', '<code>1000</code>', 'Owner of the files Muzikk writes; must match the library'],
                    ['<code>UMASK</code>', '<code>002</code>', 'Mask applied to imported files'],
                    ['<code>TZ</code>', '<code>Europe/Paris</code>', 'Container time zone'],
                    ['<code>MUZIKK_PORT</code>', '<code>8383</code>', 'HTTP port'],
                    ['<code>MUZIKK_CONFIG_DIR</code>', '<code>/config</code>', 'Database, keys, cache, logs'],
                    ['<code>MUZIKK_STATIC_DIR</code>', '<code>/app/static</code>', 'The compiled interface'],
                    ['<code>MUZIKK_LOG_LEVEL</code>', '<code>INFO</code>', '<code>DEBUG</code>, <code>INFO</code>, <code>WARNING</code>'],
                    ['<code>MUZIKK_WORKER_CONCURRENCY</code>', '<code>2</code>', 'Jobs handled in parallel, 1 to 8'],
                    ['<code>MUZIKK_SESSION_HOURS</code>', '<code>336</code>', 'How long a session stays valid'],
                ]],
                ['type' => 'p', 'text' => 'In the compose file, <code>MUSIC_LIBRARY</code> and '
                    . '<code>DOWNLOADS_ROOT</code> are the <strong>host</strong> paths, '
                    . '<code>MUSIC_LIBRARY_CONTAINER</code> and <code>DOWNLOADS_CONTAINER</code> the matching paths '
                    . '<strong>inside the container</strong>.'],
            ],
        ],
        [
            'id' => 'development',
            'title' => 'Development',
            'blocks' => [
                ['type' => 'h3', 'text' => 'Backend'],
                ['type' => 'code', 'lang' => 'bash', 'body' => <<<'CODE'
python -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
MUZIKK_CONFIG_DIR=./config .venv/bin/uvicorn muzikk.main:app \
    --reload --app-dir backend --port 8383
CODE],
                ['type' => 'h3', 'text' => 'Frontend'],
                ['type' => 'code', 'lang' => 'bash', 'body' => <<<'CODE'
cd frontend
npm install
npm run dev          # http://localhost:5173, /api is proxied to port 8383
CODE],
                ['type' => 'h3', 'text' => 'Quick checks, without Node or Docker'],
                ['type' => 'code', 'lang' => 'bash', 'body' => <<<'CODE'
.venv/bin/python -m ruff check backend        # lint
.venv/bin/python backend/smoke_test.py        # startup, routes and auth guards
.venv/bin/python backend/pipeline_test.py     # naming, matching, file/track pairing
.venv/bin/python backend/artwork_test.py      # artwork resolution
.venv/bin/python backend/metadata_test.py     # library analysis and tag reading
.venv/bin/python backend/local_import_test.py # local folder import
.venv/bin/python backend/local_mode_test.py   # local accounts, wizard and disk scanner
.venv/bin/python backend/playback_test.py     # file lookup and Range requests
.venv/bin/python frontend/check_frontend.py   # imports and translation keys
CODE],
                ['type' => 'h3', 'text' => 'Migrations'],
                ['type' => 'code', 'lang' => 'bash', 'body' => 'cd backend && alembic revision --autogenerate -m "description"'],
                ['type' => 'p', 'text' => 'Migrations are applied automatically at startup. On an empty database the '
                    . 'schema is created and then stamped at the latest revision.'],
            ],
        ],
        [
            'id' => 'troubleshooting',
            'title' => 'Troubleshooting',
            'blocks' => [
                ['type' => 'faq', 'items' => [
                    [
                        'q' => 'Search returns nothing',
                        'a' => 'The local MusicBrainz instance most likely has no Solr. The connection test says so '
                            . 'explicitly. Enable the public fallback in the meantime.',
                    ],
                    [
                        'q' => 'No candidate is ever accepted',
                        'a' => 'Open the request: every candidate evaluated shows its score and the reason it was '
                            . 'rejected. The usual causes are a different track count — the wrong MusicBrainz edition '
                            . 'was picked, so force another one from the album page — a score that is just too low, '
                            . 'so lower the threshold in <em>Quality</em>, or not enough seeders.',
                    ],
                    [
                        'q' => 'The same album is downloaded over and over',
                        'a' => 'The request log then contains <em>the downloaded files could not be located on '
                            . 'disk</em>. slskd did fetch the album, but Muzikk cannot find the files and treats the '
                            . 'candidate as a failure. Fix the <strong>download folder</strong> in the slskd section '
                            . 'and retry the request: the files already there are imported without being downloaded '
                            . 'again. Muzikk now stops the request immediately in this case rather than trying the '
                            . 'next candidates, and schedules no automatic retry until the configuration is corrected.',
                    ],
                    [
                        'q' => 'Files are copied instead of hardlinked',
                        'a' => 'The <code>/downloads</code> and <code>/music</code> paths must be on the '
                            . '<strong>same filesystem</strong> and mounted at the same location in every container. '
                            . 'A separate network mount forces a copy.',
                    ],
                    [
                        'q' => 'Jellyfin does not see the new albums',
                        'a' => 'Check <code>PUID</code>, <code>PGID</code> and <code>UMASK</code>: Jellyfin has to be '
                            . 'able to read the files. The automatic rescan can also be turned off in the Jellyfin '
                            . 'settings. If a folder stays invisible despite a rescan, it appears in '
                            . '<em>Metadata</em> under "Missing from Jellyfin" — almost always an album without an '
                            . '<code>album</code> or <code>albumartist</code> tag, which the media server cannot '
                            . 'classify. Fix the tags from that page, then reindex.',
                    ],
                    [
                        'q' => 'Playback does not start',
                        'a' => 'The player shows the exact reason returned by the server next to "Cannot play". The '
                            . '<em>Player</em> section must be enabled. In Jellyfin mode, if direct access is off, '
                            . 'Jellyfin has to be reachable from the container. An account that signed in before '
                            . 'playback was enabled has no stored token yet, so the play falls back to the server API '
                            . 'key and is not credited; signing out and back in is enough. In local mode, files are '
                            . 'read from the mounted library folder, with ffmpeg for formats the browser cannot play.',
                    ],
                    [
                        'q' => 'I cannot sign in',
                        'a' => 'In Jellyfin mode, Muzikk stores no password, so the failure comes from Jellyfin. '
                            . 'Check that the user is active in Muzikk under <em>Administration → Users</em>, and '
                            . 'that the Jellyfin API key is still valid. In local mode, the password lives in Muzikk: '
                            . 'an administrator can reset it from that same page. If login fails right after setup '
                            . 'with an internal error, the first library scan may still be writing to SQLite — wait '
                            . 'a moment and try again.',
                    ],
                ]],
                ['type' => 'p', 'text' => 'Detailed logs live in <code>/config/logs/muzikk.log</code> and in '
                    . '<code>docker compose logs -f muzikk</code>. Both receive the same thing.'],
            ],
        ],
    ],
];
