<?php
/**
 * The user guide: everything that happens once Muzikk is installed. The
 * installation itself lives in docs.php.
 *
 * Same block format as the installation page: p, h3, list, code, table, note,
 * warning, faq.
 */

declare(strict_types=1);

return [
    'eyebrow' => 'User guide',
    'title' => 'Using Muzikk',
    'lead' => 'Connecting your services, asking for an album, getting suggestions, and the handful of '
        . 'settings that decide what gets accepted and where it lands.',

    // Used by the footer, which links a few sections directly.
    'nav' => [
        'guide' => 'User guide',
        'services' => 'Connecting the services',
        'requests' => 'Requesting an album',
        'troubleshooting' => 'Troubleshooting',
    ],

    'sections' => [
        [
            'id' => 'modes',
            'title' => 'Jellyfin mode or local mode',
            'blocks' => [
                ['type' => 'p', 'text' => 'The mode chosen during installation decides where accounts and the '
                    . 'library come from, and it cannot be changed afterwards.'],
                ['type' => 'table', 'head' => ['', 'With Jellyfin', 'Local only'], 'rows' => [
                    ['Accounts', 'Imported from Jellyfin, which also decides who is an administrator', 'Created in Muzikk by an administrator'],
                    ['Library', 'Read from Jellyfin', 'Scanned from the mounted folder'],
                    ['Playlists', 'Full management from Muzikk', 'Unavailable: they live in Jellyfin'],
                    ['Playback', 'Files read directly, or relayed by Jellyfin', 'Files read directly, ffmpeg for exotic formats'],
                ]],
                ['type' => 'p', 'text' => 'Everything else behaves identically: the same catalogue search, the same '
                    . 'download pipeline, the same metadata workshop.'],
            ],
        ],
        [
            'id' => 'services',
            'title' => 'Connecting the services',
            'blocks' => [
                ['type' => 'p', 'text' => 'Everything is set in <strong>Administration</strong>, one section at a '
                    . 'time. Each service has a <em>Test connection</em> button that uses what is currently on '
                    . 'screen, including values you have not saved. Secrets come back masked: leave a masked field '
                    . 'alone to keep it.'],
                ['type' => 'note', 'text' => 'The addresses below are examples using each image\'s default port. Use '
                    . 'your own container names and ports, and the <strong>internal</strong> port of each service '
                    . 'rather than the one published on your host.'],

                ['type' => 'h3', 'text' => 'Jellyfin'],
                ['type' => 'table', 'head' => ['Setting', 'Detail'], 'rows' => [
                    ['URL', 'For instance <code>http://jellyfin:8096</code>'],
                    ['API key', '<em>Dashboard → Advanced → API keys</em>'],
                    ['Watched libraries', 'Restricts indexing to the music libraries you pick'],
                    ['Trigger a scan after import', 'Makes Jellyfin pick up a freshly imported album'],
                    ['Allow every Jellyfin user', 'Turn it off and only the listed user ids may sign in'],
                ]],
                ['type' => 'p', 'text' => 'Jellyfin administrators are Muzikk administrators, refreshed at every '
                    . 'sign-in and every user sync. Unused in local mode.'],

                ['type' => 'h3', 'text' => 'MusicBrainz'],
                ['type' => 'p', 'text' => 'This is the catalogue every search runs against. A self-hosted instance '
                    . 'needs <strong>Solr</strong> for text search; without it only identifier lookups work. '
                    . 'Leave the public fallback enabled and musicbrainz.org takes over when your instance cannot '
                    . 'answer. Rate limits are honoured separately for each, as the public server requires.'],
                ['type' => 'p', 'text' => 'A self-hosted instance can serve the API while the album pages still open '
                    . 'on musicbrainz.org: the browse URL is a setting of its own, so an instance without a web '
                    . 'interface is perfectly usable.'],

                ['type' => 'h3', 'text' => 'ListenBrainz and Last.fm, for recommendations'],
                ['type' => 'p', 'text' => 'Both are optional, and both are turned on here but connected '
                    . 'by each listener on their own <em>My account</em> page. That split is not an '
                    . 'oversight: an account on either service is personal, and two listeners on one '
                    . 'Muzikk have two different tastes and two different histories.'],
                ['type' => 'table', 'head' => ['Service', 'What the administrator sets', 'What the listener sets'], 'rows' => [
                    [
                        'ListenBrainz',
                        'Turn it on. The default URLs suit the public instance; change them only for a self-hosted one',
                        'Their username, and a user token if they want their plays submitted',
                    ],
                    [
                        'Last.fm',
                        'An API key and shared secret, registered once at <code>last.fm/api/account/create</code>',
                        'One click to approve Muzikk, which grants scrobbling',
                    ],
                ]],
                ['type' => 'note', 'text' => 'The Last.fm key identifies <strong>Muzikk itself</strong>, not a '
                    . 'person, which is why it cannot ship with the image: a secret published in a public '
                    . 'repository gets abused and then suspended for everyone. ListenBrainz needs no such '
                    . 'key at all — reading a public listening history is open, and writing only needs the '
                    . 'listener\'s own token.'],
                ['type' => 'p', 'text' => 'Once connected, the <em>For you</em> tab of the Discover page asks '
                    . 'both services which artists sit closest to the ones you listen to. It then lays the '
                    . 'answer out on three shelves, because each one calls for a different gesture: artists '
                    . 'and albums to <strong>discover</strong>, which you request; what has <strong>just come '
                    . 'out</strong> from the artists you play; and albums you <strong>already own</strong>, '
                    . 'which you simply play again. Every card names the artist it was derived from, and can '
                    . 'be hidden for good.'],
                ['type' => 'note', 'text' => 'Those suggestions are computed in the background, not while the '
                    . 'page loads: one pass means dozens of calls across both services and MusicBrainz. It '
                    . 'runs twice a day, and the page has a button to ask for it sooner. With nothing '
                    . 'connected the tab falls back on the artists you own most, which works but knows '
                    . 'nothing of what you actually play.'],
                ['type' => 'p', 'text' => 'The rest of the Discover page uses them where they know something '
                    . 'MusicBrainz does not. <em>By genre</em> stays a MusicBrainz list — it is the only '
                    . 'catalogue whose album pages can be opened by identifier — but Last.fm reorders it by '
                    . 'how often each album is actually tagged with that genre, which is a notion MusicBrainz '
                    . 'has no data for. <em>New releases</em> keeps its date range query and puts the '
                    . 'ListenBrainz fresh-releases list in front of it.'],

                ['type' => 'h3', 'text' => 'slskd, for Soulseek'],
                ['type' => 'table', 'head' => ['Setting', 'Detail'], 'rows' => [
                    ['URL', 'For instance <code>http://slskd:5030</code>'],
                    ['API key', 'From <code>slskd.yml</code>, under <code>web.authentication.api_keys</code>'],
                    ['Download folder', 'The path <strong>as Muzikk sees it</strong>'],
                    ['Minimum peer speed / maximum queue', 'Filters out peers too slow or too busy'],
                ]],
                ['type' => 'warning' , 'text' => 'The <strong>download folder</strong> is the most often mistyped '
                    . 'setting on this page. slskd and Muzikk each see the disk through their own mounts, and it is '
                    . 'the Muzikk-side path that belongs here. The connection test refuses to pass until Muzikk can '
                    . 'read it: a transfer that completes but whose files cannot be found was downloaded for '
                    . 'nothing. Make sure the slskd API key also allows the Muzikk container address in its '
                    . '<code>cidr</code>.'],

                ['type' => 'h3', 'text' => 'Prowlarr and qBittorrent, for torrents'],
                ['type' => 'table', 'head' => ['Setting', 'Detail'], 'rows' => [
                    ['Prowlarr URL / API key', 'For instance <code>http://prowlarr:9696</code>, key under <em>Settings → General</em>'],
                    ['Categories', '<code>3000</code> Audio, <code>3010</code> MP3, <code>3040</code> Lossless by default'],
                    ['Check the <code>.torrent</code> before adding it', '<strong>Leave this on</strong> — it avoids most false positives'],
                    ['qBittorrent URL', 'For instance <code>http://qbittorrent:8080</code>'],
                    ['Download folder', 'The <strong>same</strong> path in both containers'],
                    ['Keep seeding after import', 'Recommended for private trackers'],
                ]],
                ['type' => 'p', 'text' => 'Once Prowlarr is saved, open <strong>Indexers</strong> and run the sync. '
                    . 'Each indexer can then be enabled, prioritised, classified public or private, and given a '
                    . 'seeder threshold of its own.'],
                ['type' => 'p', 'text' => 'If qBittorrent refuses the login, the quickest fix is to tick <em>Bypass '
                    . 'authentication for clients in whitelisted IP subnets</em> with your Docker subnet and leave '
                    . 'the username empty in Muzikk. An <code>HTTP 401</code> on older versions usually means the '
                    . '<code>Host</code> header was rejected instead: untick <em>Enable Host header validation</em> '
                    . 'in <em>Tools → Options → Web UI</em>. An <code>HTTP 403</code> is a temporary ban after a few '
                    . 'failed attempts, lifted by restarting the container.'],
            ],
        ],
        [
            'id' => 'requests',
            'title' => 'Requesting an album',
            'blocks' => [
                ['type' => 'p', 'text' => 'Search, open an album, press the button. What happens next:'],
                ['type' => 'code', 'lang' => 'text', 'body' => <<<'CODE'
request → (approval) → search → candidate chosen → download
        → verification → tagging → filing → library index
CODE],
                ['type' => 'p', 'text' => 'Before reaching the network, Muzikk looks in the slskd download folder: an '
                    . 'album already sitting there complete is imported straight away. That folder is scored exactly '
                    . 'like a remote one, so a half-finished download cannot be mistaken for the album.'],
                ['type' => 'p', 'text' => 'Each provider is then queried in the order you set, and the first '
                    . 'candidate above the score threshold wins — the others are never touched. Every candidate '
                    . 'evaluated is kept with its score and the reason it was rejected, readable from the '
                    . '<strong>Requests</strong> page. That page is also where you clear imported or failed '
                    . 'requests, retry every failure at once, or cancel what is running.'],
                ['type' => 'h3', 'text' => 'Asking for one track'],
                ['type' => 'p', 'text' => 'A request normally covers the whole album. An account granted '
                    . '<em>Request single tracks</em> — off by default — also gets a download button on '
                    . 'each line of a tracklist. The file is still tagged and filed inside the album it '
                    . 'belongs to, so it can later be completed rather than sitting in the library as an '
                    . 'orphan; the album simply appears incomplete until then.'],
                ['type' => 'note', 'text' => 'Soulseek only, because it is the one place files are shared '
                    . 'individually. A track is matched on its own title, its artist and its '
                    . '<strong>length</strong> — a remix or a live take shares the title and rarely the '
                    . 'duration, which is what keeps another version out. The album rules are untouched: '
                    . 'a lone file is still never accepted as a record.'],

                ['type' => 'h3', 'text' => 'Upgrading an album you already own'],
                ['type' => 'p', 'text' => 'An upgrade replaces a lossy copy with a lossless one, and lands in the '
                    . 'very folder it improves. Rather than deleting anything, Muzikk records both versions file by '
                    . 'file and puts the request in the <strong>To approve</strong> state. You compare the two '
                    . 'columns, play either side, then approve — which removes the old audio files only — or reject, '
                    . 'which removes what was just imported. A setting in the Naming section makes the deletion '
                    . 'immediate instead.'],
                ['type' => 'h3', 'text' => 'Following an artist'],
                ['type' => 'p', 'text' => 'Following an artist downloads nothing. The periodic check compares their '
                    . 'discography to your library and lists what is missing in the <strong>Watchlist</strong> tab, '
                    . 'where every album waits for a click. Each artist has its own scope: new releases only, or the '
                    . 'whole discography. Compilations, live albums and remixes are left out either way.'],
            ],
        ],
        [
            'id' => 'quality',
            'title' => 'Deciding what is accepted',
            'blocks' => [
                ['type' => 'p', 'text' => 'The <strong>Quality</strong> section holds the accepted lossless formats '
                    . 'in order of preference, an optional lossy fallback, size thresholds per track, a seeder '
                    . 'count, and the <strong>minimum score</strong> a candidate must reach — 78 by default. Lower '
                    . 'it if too many albums fail, raise it if bad ones get through.'],
                ['type' => 'p', 'text' => 'A candidate is scored on artist and title similarity, track count, how '
                    . 'many track titles match, the detected format, the size per track, and seeders or peer speed. '
                    . 'Names are compared after stripping accents, punctuation and mentions like "deluxe" or '
                    . '"remaster".'],
                ['type' => 'p', 'text' => '<em>Require the artist in the candidate path</em> rejects a release whose '
                    . 'path names nobody resembling the artist asked for. The artist alone is only worth 20 points, '
                    . 'so without this rule a namesake\'s album — same title, same track count, same format — can '
                    . 'clear the threshold. The price is that a folder named after the album alone is refused too: '
                    . 'untick it if your sources are organised that way.'],
                ['type' => 'p', 'text' => 'In <strong>Provider order</strong>, reorder Soulseek, public trackers and '
                    . 'private trackers as a ranked list.'],
            ],
        ],
        [
            'id' => 'naming',
            'title' => 'How files are named',
            'blocks' => [
                ['type' => 'p', 'text' => 'The default template reproduces the usual Picard script:'],
                ['type' => 'code', 'lang' => 'text', 'body' => '{albumartist}/{album} ({year})/{disc_prefix}{track:02} {artist_prefix}{title}'],
                ['type' => 'p', 'text' => 'which gives <code>Daft Punk/Discovery (2001)/03 Digital Love.flac</code>. '
                    . 'The preview updates as you type, on three examples: a plain album, a multi-disc box set and a '
                    . 'compilation.'],
                ['type' => 'table', 'head' => ['Variable', 'Value'], 'rows' => [
                    ['<code>{albumartist}</code> <code>{artist}</code>', 'Album artist / track artist'],
                    ['<code>{album}</code> <code>{title}</code>', 'Album title / track title'],
                    ['<code>{year}</code> <code>{date}</code>', 'Year, full release date'],
                    ['<code>{track}</code> <code>{disc}</code> <code>{totaldiscs}</code>', 'Numbers; <code>{track:02}</code> pads to two digits'],
                    ['<code>{disc_prefix}</code>', 'Empty on a single disc, <code>1-</code> otherwise'],
                    ['<code>{artist_prefix}</code>', 'Empty, except on a multi-artist album where it becomes <code>Artist - </code>'],
                ]],
                ['type' => 'note', 'text' => 'Soulseek downloads are hardlinked then tagged in place. Torrents are '
                    . '<strong>copied</strong> before tagging: rewriting the tags of a file still being seeded would '
                    . 'corrupt it in the tracker\'s eyes.'],
            ],
        ],
        [
            'id' => 'metadata',
            'title' => 'The metadata workshop',
            'blocks' => [
                ['type' => 'p', 'text' => 'Administrators reach it from <em>Metadata</em> in the menu. It walks the '
                    . 'library folder itself, groups files per album and reports what is wrong: no MusicBrainz tag, '
                    . 'a match that is only probable, missing artwork, incomplete tags, doubled tags, a duplicate, '
                    . 'and — in Jellyfin mode — a folder Jellyfin cannot see.'],
                ['type' => 'p', 'text' => 'An album is identified by searching MusicBrainz, by pasting an MBID or '
                    . 'URL, or by <strong>audio fingerprint</strong> through AcoustID, which needs a free API key. '
                    . 'Nothing is written without a simulation first: every field, before and after, file by file. '
                    . 'Once the tags are fixed, <em>Reindex Jellyfin</em> makes the server rediscover folders it had '
                    . 'ignored.'],
                ['type' => 'p', 'text' => 'Artwork comes from the Cover Art Archive and is cached. You choose the '
                    . 'size, whether it is embedded in the files, and whether <code>cover.jpg</code> and '
                    . '<code>folder.jpg</code> are written next to the tracks. Both names exist because players '
                    . 'disagree: Jellyfin and Kodi read either, Plex only looks at <code>cover.jpg</code>. Writing '
                    . 'both costs a few kilobytes and settles the question.'],
                ['type' => 'p', 'text' => 'A nightly pass can re-run the analysis on its own, at an hour you pick.'],
            ],
        ],
        [
            'id' => 'playback',
            'title' => 'Listening in Muzikk',
            'blocks' => [
                ['type' => 'p', 'text' => 'Playback has to be enabled in the <strong>Player</strong> section. Files '
                    . 'are read straight from the music folder, which is faster and depends on no media server '
                    . 'policy. In Jellyfin mode you can untick that and have the stream relayed by the API instead, '
                    . 'so the browser never receives a Jellyfin token; the maximum bitrate applies to that relay, '
                    . 'and <code>0</code> streams the original file. Formats a browser cannot decode — APE, DSF, '
                    . 'WavPack — are transcoded on the fly.'],
                ['type' => 'p', 'text' => 'The queue supports shuffle and repeat, and a track you do not own yet can '
                    . 'be previewed for thirty seconds, relayed by the API so your browser contacts no outside '
                    . 'service. In Jellyfin mode, plays can be reported under the listener\'s own account.'],
                ['type' => 'p', 'text' => 'A play is also scrobbled to ListenBrainz and Last.fm for whoever '
                    . 'connected them, in either mode, since those accounts belong to the listener rather than '
                    . 'to the library. A listen is only submitted once the track has genuinely played: at '
                    . 'least thirty seconds long, and past either half its length or four minutes.'],
                ['type' => 'p', 'text' => 'Playlists are Jellyfin playlists, editable from Muzikk: create, rename, '
                    . 'add a track or a whole album, remove, delete. A track already in a playlist is not added '
                    . 'twice. They can also be exported to a JSON backup and imported back, and an administrator may '
                    . 'import into another Jellyfin account.'],
            ],
        ],
        [
            'id' => 'users',
            'title' => 'Users and permissions',
            'blocks' => [
                ['type' => 'p', 'text' => 'Each account is granted, independently: <em>account active</em>, '
                    . '<em>request albums</em>, <em>request single tracks</em>, <em>upgrade to lossless</em> '
                    . 'and <em>import a folder</em>. '
                    . '<em>Automatic approval</em> is a three-way choice — follow the global setting, always, or '
                    . 'never — and the weekly quota is a number, zero meaning unlimited. Administrators bypass both '
                    . 'permissions and quotas.'],
                ['type' => 'note', 'text' => 'In Jellyfin mode, administrator status is deliberately not editable '
                    . 'here: it is read from Jellyfin at every sign-in, so any change would be overwritten. In local '
                    . 'mode, administrators are managed in Muzikk itself.'],
            ],
        ],
        [
            'id' => 'troubleshooting',
            'title' => 'Troubleshooting',
            'blocks' => [
                ['type' => 'faq', 'items' => [
                    [
                        'q' => 'Search returns nothing',
                        'a' => 'A self-hosted MusicBrainz instance without Solr cannot do text search, and the '
                            . 'connection test says so explicitly. Enable the public fallback in the meantime.',
                    ],
                    [
                        'q' => 'No candidate is ever accepted',
                        'a' => 'Open the request: every candidate shows its score and why it was rejected. The usual '
                            . 'causes are a track count that does not match — the wrong MusicBrainz edition was '
                            . 'picked, so choose another one from the album page — a score just below the threshold, '
                            . 'or not enough seeders.',
                    ],
                    [
                        'q' => 'The same album is downloaded over and over',
                        'a' => 'The request log then says <em>the downloaded files could not be located on disk</em>. '
                            . 'The transfer worked but Muzikk cannot find the files. Fix the <strong>download '
                            . 'folder</strong> in the slskd section and retry: what is already downloaded is '
                            . 'imported without being fetched again.',
                    ],
                    [
                        'q' => 'Files are copied instead of hardlinked',
                        'a' => 'The downloads and the library must be on the <strong>same filesystem</strong>, '
                            . 'mounted at the same path in every container. A separate network mount forces a copy.',
                    ],
                    [
                        'q' => 'Jellyfin does not see the new albums',
                        'a' => 'Check <code>PUID</code>, <code>PGID</code> and <code>UMASK</code> first: Jellyfin has '
                            . 'to be able to read the files. A folder that stays invisible despite a rescan appears '
                            . 'in <em>Metadata</em> under "Missing from Jellyfin" — almost always an album with no '
                            . '<code>album</code> or <code>albumartist</code> tag, which a media server cannot '
                            . 'classify. Fix the tags there, then reindex.',
                    ],
                    [
                        'q' => 'Playback does not start',
                        'a' => 'The player prints the exact reason next to "Cannot play". The <em>Player</em> section '
                            . 'must be enabled. In Jellyfin mode with direct reads off, Jellyfin has to be reachable '
                            . 'from the container, and an account that signed in before playback was enabled has no '
                            . 'stored token yet: signing out and back in is enough.',
                    ],
                    [
                        'q' => 'I cannot sign in',
                        'a' => 'In Jellyfin mode Muzikk stores no password, so the refusal comes from Jellyfin: check '
                            . 'the account is active under <em>Administration → Users</em> and that the API key is '
                            . 'still valid. In local mode an administrator can reset the password from that same '
                            . 'page.',
                    ],
                ]],
                ['type' => 'p', 'text' => 'Logs are in <code>/config/logs/muzikk.log</code> and in '
                    . '<code>docker compose logs -f muzikk</code>. Anything about getting the container running is '
                    . 'in the <a href="documentation.php">installation guide</a>.'],
            ],
        ],
    ],
];
