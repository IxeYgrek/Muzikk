<?php
/**
 * The landing page: hero, presentation, feature categories, slideshow.
 */

declare(strict_types=1);

return [
    'hero' => [
        'eyebrow' => 'Self-hosted music request manager',
        'lead' => 'Muzikk sits between your MusicBrainz catalogue and your Jellyfin (or local) library. '
            . 'Ask for an album, and it finds it on Soulseek or BitTorrent, checks it, tags it, '
            . 'files it under your own naming scheme and, when Jellyfin is in use, tells it to look again.',
        'ctaDocs' => 'Installation guide',
        'ctaDownload' => 'Get Muzikk',
        'badges' => [
            'One container',
            'SQLite only',
            'Lossless first',
            'Jellyfin or local',
        ],
        'credit' => 'This project (website and application) was entirely coded with Claude Opus',
    ],

    'intro' => [
        'eyebrow' => 'What it is',
        'title' => 'A request manager for music, inspired by DroppedNeedle (formerly MusicSeerr) and Seerr',
        'paragraphs' => [
            'Your users search a real catalogue rather than a scraped index, see at a glance what the '
                . 'library already holds, and request whole albums. Muzikk queries each source in the order '
                . 'you chose, scores every candidate it gets back, and only downloads one it can defend.',
            'What arrives is verified, tagged from MusicBrainz, given its artwork and filed in your library.',
        ],
        'highlights' => [
            [
                'icon' => 'headphones',
                'title' => 'Complete musical toolkit',
                'text' => 'Browse your Jellyfin or local library, search for new music with MusicBrainz, '
                    . 'and download using Soulseek and BitTorrent (with Prowlarr support).',
            ],
            [
                'icon' => 'tag',
                'title' => 'Metadata manager',
                'text' => 'Inspired by MusicBrainz Picard, manage metadata directly from the Muzikk '
                    . 'interface.',
            ],
            [
                'icon' => 'waveform',
                'title' => 'Lossless by default',
                'text' => 'Accepted formats are ranked, a lossy fallback is opt-in, and an album you '
                    . 'already own in MP3 can be upgraded on request.',
            ],
        ],
    ],

    'features' => [
        'eyebrow' => 'Features',
        'title' => 'Everything Muzikk does',
        'lead' => 'Grouped the way the application itself is: find the music, play it, fetch it, '
            . 'repair its tags, and keep the whole thing configurable.',
        'categories' => [
            [
                'id' => 'catalogue',
                'icon' => 'search',
                'title' => 'MusicBrainz catalogue search',
                'lead' => 'An album is identified before it is ever downloaded, which is what makes '
                    . 'everything downstream reliable.',
                'items' => [
                    'Runs against your own <strong>self-hosted MusicBrainz server</strong> first, with '
                        . 'musicbrainz.org kept as an automatic fallback when it is unreachable.',
                    'Search by <strong>album</strong>, by <strong>track</strong>, by <strong>artist</strong> '
                        . 'or by <strong>label</strong> — a label page unfolds its entire catalogue, ready to request.',
                    'Cover art from the <strong>MusicBrainz Cover Art Archive</strong>, cached on disk and '
                        . 'resized once, with the release falling back to its release group.',
                    '<strong>AcoustID</strong> support: an audio fingerprint identifies a folder whose tags '
                        . 'say nothing at all.',
                    'Albums you already own are flagged in the results — a solid tick on a MusicBrainz '
                        . 'identifier match, a lighter one on a fuzzy match, and an amber badge when the copy '
                        . 'you hold is not lossless.',
                    'A specific MusicBrainz release can be forced from the album page when the default '
                        . 'edition has the wrong track count.',
                ],
            ],
            [
                'id' => 'jellyfin',
                'icon' => 'disc',
                'title' => 'Jellyfin or a local library',
                'lead' => 'On first launch you choose once: Jellyfin owns the accounts and the library, '
                    . 'or Muzikk handles both on its own. The choice cannot be undone.',
                'items' => [
                    '<strong>With Jellyfin</strong>, sign in with your Jellyfin account. Administrators '
                        . 'there are administrators here, and access can be limited to a chosen list of '
                        . 'Jellyfin users.',
                    '<strong>Local only</strong>, create accounts in Muzikk itself. An administrator is '
                        . 'set up in the wizard, then creates the others. The library is scanned from the '
                        . 'folder you mount — no Jellyfin server required.',
                    '<strong>Playback directly inside the application</strong>, with a queue, shuffle and '
                        . 'repeat. Click a track on an album page and it starts there. Files are read '
                        . 'straight from the music folder; formats the browser cannot play are transcoded '
                        . 'with ffmpeg. In Jellyfin mode the stream can also be relayed so the browser '
                        . 'never receives a Jellyfin token.',
                    '<strong>Jellyfin playlist management</strong> when that mode is chosen: listen, create, '
                        . 'delete, add a single track or a whole album in disc and track order, and remove '
                        . 'a track. Playlists are hidden in local mode.',
                    '<strong>Thirty second previews</strong> from Deezer, then iTunes, for a track you do not '
                        . 'own yet — relayed by the API, so the browser contacts neither service.',
                ],
            ],
            [
                'id' => 'downloads',
                'icon' => 'download',
                'title' => 'Integrated downloading',
                'lead' => 'Providers are queried in the order you set. The first one with a candidate '
                    . 'above the score threshold wins; the others are never touched.',
                'items' => [
                    '<strong>Soulseek</strong> through slskd, with per-peer filters on speed and queue length.',
                    '<strong>Torrents</strong> through Prowlarr and qBittorrent, each indexer carrying its own '
                        . 'priority, public or private classification and seeder floor.',
                    '<strong>Upgrade option</strong>: replace an album you own in MP3 — or any other lossy '
                        . 'format — with a FLAC copy, as a permission granted per user.',
                    'Requests cover a whole album, with optional administrator approval and weekly '
                        . 'quotas per account. <strong>One track at a time</strong> is possible too, as '
                        . 'a permission granted per user and off by default — the file is still filed '
                        . 'inside the album it belongs to.',
                    'Every candidate is scored on artist and title similarity, track count, track titles, '
                        . 'detected format, size per track and seeders or peer speed. Below the threshold, '
                        . 'Muzikk moves on.',
                    'After download: integrity check with <code>flac -t</code> or <code>ffmpeg</code>, full '
                        . 'MusicBrainz tagging, embedded artwork and <code>cover.jpg</code>, filing under your '
                        . 'naming template, a hardlink so seeding continues, then a Jellyfin rescan when '
                        . 'that mode is in use.',
                    '<strong>Artist watchlist and wishlist</strong> list what is missing without ever '
                        . 'downloading it by themselves — new releases only, or a whole discography, per artist.',
                    '<strong>Local import</strong>: drop an album folder from the home page and Muzikk '
                        . 'identifies it, writes the tags, lays down the artwork and files it like any other '
                        . 'import — refusing to overwrite a lossless copy you already have.',
                ],
            ],
            [
                'id' => 'recommendations',
                'icon' => 'sparkles',
                'title' => 'Music recommendations',
                'lead' => 'Connect ListenBrainz or Last.fm and Muzikk suggests albums from what you '
                    . 'actually listen to, rather than from a genre you picked once.',
                'items' => [
                    'A <strong>For you</strong> tab reads your listening history and asks both services '
                        . 'which artists sit closest to the ones you play. Every card says why it is '
                        . 'there — <em>close to Röyksopp</em> — so a suggestion never reads as a random '
                        . 'one, and anything you are not interested in is hidden for good.',
                    'Three shelves, because they call for three different gestures: '
                        . '<strong>artists and albums to discover</strong>, which you request; what has '
                        . '<strong>just come out</strong> from the artists you play; and '
                        . '<strong>albums you already own</strong>, which you simply play again.',
                    'The other tabs benefit too: a genre is ordered by what Last.fm says it is best '
                        . 'known for, and new releases include the fresh-releases list ListenBrainz '
                        . 'keeps, rather than everything a catalogue happened to register that month.',
                    '<strong>Scrobbling</strong> works the other way round: what you play in Muzikk is '
                        . 'sent to ListenBrainz and to Last.fm, so the history that feeds the suggestions '
                        . 'keeps growing on its own.',
                    'Both are optional and personal: each listener connects their own account from their '
                        . 'own page, and nothing leaves the server for anyone who connects neither.',
                ],
            ],
            [
                'id' => 'metadata',
                'icon' => 'tag',
                'title' => 'Full metadata management',
                'lead' => 'A Picard-style workshop that runs on your own server: it reads the music folder '
                    . 'itself, tells you what is wrong, and writes nothing you have not simulated first.',
                'groups' => [
                    [
                        'title' => 'Library analysis',
                        'items' => [
                            'Walks the library folder straight from disk — including what Jellyfin skipped, '
                                . 'when Jellyfin is in use — groups files per album folder and folds multi-disc '
                                . 'sets back together.',
                            'Flags seven anomalies: no MusicBrainz tag, uncertain match, no artwork, '
                                . 'incomplete tags, doubled tags, duplicate album, missing from Jellyfin '
                                . '(Jellyfin mode).',
                            'Filter by anomaly, search by album, artist or path, and follow each album '
                                . 'through three states: to fix, fixed, ignored.',
                        ],
                    ],
                    [
                        'title' => 'Identification',
                        'items' => [
                            'Search MusicBrainz for the album, every candidate carrying a relevance score.',
                            'Paste a MusicBrainz <strong>MBID or URL</strong> — Muzikk tries it as a release '
                                . 'group, then as a release.',
                            '<strong>AcoustID audio fingerprint</strong> over a configurable number of '
                                . 'sampled tracks, with the results voted across them.',
                            'A stored match writes nothing on its own: it only unlocks the simulation.',
                        ],
                    ],
                    [
                        'title' => 'Reading and writing tags',
                        'items' => [
                            '<strong>Simulate first</strong>: every field, before and after, file by file, '
                                . 'with a count of what would change.',
                            'A full Picard-style tag set is written: titles, artists, album artist, date and '
                                . 'original date, track and disc numbers with their totals, up to eight genres, '
                                . 'label, catalogue number, barcode, ISRC, media, release country, status and '
                                . 'type, sort names, compilation flag and every MusicBrainz identifier.',
                            'Artwork from the Cover Art Archive, embedded in the files and written as '
                                . '<code>cover.jpg</code> and <code>folder.jpg</code> — each one a separate toggle.',
                        ],
                    ],
                    [
                        'title' => 'Jellyfin reconciliation (Jellyfin mode)',
                        'items' => [
                            '<strong>Repair the Jellyfin covers</strong>: ask Jellyfin to look again, then '
                                . 'upload the image directly for the albums still showing empty — from the '
                                . 'folder, then the tags, then the Cover Art Archive.',
                            '<strong>Align Jellyfin on the tags</strong>: compare album title, artist and '
                                . 'year plus every track title and number, then write them back through the '
                                . 'API. It also runs by itself after each tag write.',
                            '<strong>Reindex Jellyfin</strong> so the folders it had ignored are finally '
                                . 'picked up.',
                        ],
                    ],
                ],
            ],
            [
                'id' => 'administration',
                'icon' => 'sliders',
                'title' => 'Administration',
                'lead' => 'One section at a time, saved on its own. Each integration has a Test connection '
                    . 'button that uses what is on screen, even unsaved, and every secret is encrypted at rest.',
                'groups' => [
                    [
                        'title' => 'General behaviour',
                        'items' => [
                            'Default language and default weekly quota for new accounts.',
                            'Administrator approval required, and whether administrators bypass it.',
                            'Delay before a new attempt, and the maximum number of attempts per request.',
                            'Library index interval, followed artists check interval, log retention in days.',
                        ],
                    ],
                    [
                        'title' => 'Integrations, each with a connection test',
                        'items' => [
                            '<strong>Jellyfin</strong> — URL, API key, the music libraries to watch, a scan '
                                . 'triggered after import, and an optional allow-list of Jellyfin user ids.',
                            '<strong>MusicBrainz</strong> — local instance URL, public fallback and its URL, '
                                . 'one rate limit for each, and the contact sent in the User-Agent.',
                            '<strong>ListenBrainz</strong> and <strong>Last.fm</strong> — turned on here, then '
                                . 'connected by each listener on their own page, for suggestions and scrobbling.',
                            '<strong>Cover Art Archive</strong> — URL, preferred size, embedding in files, '
                                . '<code>cover.jpg</code> and <code>folder.jpg</code>.',
                            '<strong>slskd</strong> — URL, API key, URL prefix, the download folder as Muzikk '
                                . 'sees it, search duration, response limit, minimum peer speed, maximum peer '
                                . 'queue length, transfer and stall timeouts, and removal of finished transfers.',
                            '<strong>Prowlarr</strong> — URL, API key, Torznab categories, result limit, the '
                                . 'dedicated music search, and fetching the <code>.torrent</code> to check its '
                                . 'file list before adding it.',
                            '<strong>Indexers</strong> — synchronised from Prowlarr, then enabled, prioritised, '
                                . 'classified public or private and given their own seeder floor, one by one.',
                            '<strong>qBittorrent</strong> — URL, credentials, category, download folder, '
                                . 'transfer and stall timeouts, keep seeding after import, add torrents paused.',
                            '<strong>AcoustID</strong> — fingerprinting on or off, API key, and how many '
                                . 'tracks each fingerprint samples.',
                        ],
                    ],
                    [
                        'title' => 'Quality rules',
                        'items' => [
                            'Accepted lossless formats, in order of preference.',
                            'Optional lossy fallback, its accepted formats and a minimum bitrate.',
                            'A preference for 24 bit, and the minimum score a candidate must reach.',
                            'Tolerated track count difference, minimum seeders, minimum and maximum size '
                                . 'per track.',
                            'Audio integrity verification, rejection of incomplete albums, and a rule '
                                . 'requiring the artist to appear in the candidate path.',
                        ],
                    ],
                    [
                        'title' => 'Naming and filing',
                        'items' => [
                            'The naming template, with a live preview on three examples — a plain album, a '
                                . 'multi-disc set and a compilation.',
                            'Library folder, replacement character for unsafe ones, maximum component '
                                . 'length, and the name used for compilations.',
                            'Whether an upgrade deletes the old copy, and whether that deletion needs '
                                . 'validating first.',
                        ],
                    ],
                    [
                        'title' => 'Player and providers',
                        'items' => [
                            'Playback on or off, reading files directly from the music folder, thirty '
                                . 'second previews, a maximum relay bitrate, and play reporting to Jellyfin '
                                . 'when that mode is in use. Plays are scrobbled to ListenBrainz and Last.fm '
                                . 'for whoever connected them.',
                            'Provider order: reorder Soulseek, public trackers and private trackers as a '
                                . 'ranked list.',
                        ],
                    ],
                    [
                        'title' => 'Users and permissions',
                        'items' => [
                            'In Jellyfin mode, import accounts in one click; administrator status always '
                                . 'follows Jellyfin. In local mode, administrators create and rename accounts '
                                . 'and reset passwords from this page.',
                            'Per account: <strong>account active</strong>, <strong>request albums</strong>, '
                                . '<strong>request single tracks</strong>, <strong>upgrade to lossless</strong>, '
                                . '<strong>import a folder</strong>.',
                            '<strong>Automatic approval</strong> as a three-way choice — follow the global '
                                . 'setting, always, or never.',
                            'A <strong>weekly quota</strong> per account, zero meaning unlimited, with '
                                . 'administrators exempt.',
                            'Last sign-in shown next to each account.',
                        ],
                    ],
                    [
                        'title' => 'System and maintenance',
                        'items' => [
                            'Version, configuration directory, library folder, worker count, and which '
                                . 'services are actually configured.',
                            'Run any task by hand: index the library, import users, sync indexers, check '
                                . 'followed artists, check the wishlist, retry failures, prune logs.',
                            'Clear the cover cache, which is also purged on its own when the artwork URL '
                                . 'changes.',
                            'Watch the last forty background jobs with their state, their request and their '
                                . 'error message.',
                        ],
                    ],
                ],
            ],
        ],
    ],

    'shots' => [
        'eyebrow' => 'Screenshots',
        'title' => 'A look at the interface',
        'lead' => 'Dark by design, built for a browser you keep open next to your music.',
        'prev' => 'Previous screenshot',
        'next' => 'Next screenshot',
        'goTo' => 'Go to screenshot {index}',
        'counter' => '{current} / {total}',
        'toggle' => 'Pause or resume the slideshow',
        'emptyTitle' => 'No screenshot yet',
        'emptyHint' => 'Drop image files into <code>{folder}</code> at the project root and they appear '
            . 'here, ordered by file name. Numbering them — <code>01-home.png</code>, '
            . '<code>02-search.png</code> — is the easiest way to control that order.',
        // A caption per screenshot, keyed by the file name without its leading
        // number and extension. Anything missing falls back to the file name.
        'captions' => [
            'home' => 'The home page: one search field for albums, artists, tracks and labels.',
            'search' => 'Search results, with an ownership badge and a play button on every release.',
            'album' => 'An album page: editions, tracklist, playback and the request button.',
            'requests' => 'Requests, with the full log of every candidate that was evaluated.',
            'library' => 'The library, from Jellyfin or scanned from disk.',
            'metadata' => 'The metadata workshop: anomalies found, identification, simulated write.',
            'admin' => 'Administration: fifteen sections, each with its own connection test.',
            'player' => 'The player, with its queue, shuffle and repeat.',
			'upgrade' => 'Replace your mp3 in lossless equivalent.',
			'playlist' => 'Manage your Jellyfin playlists (Jellyfin mode).',
        ],
    ],

    'cta' => [
        'title' => 'Ready to run it?',
        'lead' => 'A compose file, three volumes, and either a Jellyfin API key or a local administrator '
            . 'account. The installation guide is short on purpose; the user guide covers everything after that.',
        'docs' => 'Installation guide',
        'guide' => 'User guide',
        'download' => 'Go to downloads',
    ],
];
