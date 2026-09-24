<?php
/**
 * The download page.
 */

declare(strict_types=1);

return [
    'title' => 'Download',
    'eyebrow' => 'Get Muzikk',
    'lead' => 'One compose file, three volumes, and either a Jellyfin API key or a local administrator '
        . 'account. Building from source is optional.',

    'image' => [
        'soonBadge' => 'Coming soon',
        'soonTitle' => 'The image is not on Docker Hub yet',
        'soonText' => 'The published image will appear here as soon as it has been pushed.',
        'readyTitle' => 'Pull the image',
        'readyText' => 'The image already contains the API, the interface and the worker. '
            . 'Point compose at it, or pull it on its own.',
        'readyButton' => 'Open Docker Hub',
    ],

    'repo' => [
        'soonBadge' => 'Coming soon',
        'soonTitle' => 'The repository is not public yet',
        'soonText' => 'The source will be published on GitHub, and this page will link straight to it.',
        'soonButton' => 'GitHub — coming soon',
        'readyTitle' => 'Get the source code',
        'readyText' => 'Clone the repository if you want to read the code, change it, or build the image yourself.',
        'readyButton' => 'Open the repository',
        'docsButton' => 'Installation guide',
    ],

    'version' => [
        'label' => 'Current version',
        'license' => 'Self-hosted, no telemetry, no account outside your own server.',
    ],

    'quickstart' => [
        'title' => 'Quick start',
        'lead' => 'The published image is all you need. Cloning the repository is only for building it yourself.',
        'steps' => [
            [
                'title' => 'Share a Docker network',
                'text' => 'Muzikk reaches Jellyfin, MusicBrainz, slskd, Prowlarr and qBittorrent by container '
                    . 'name, so it belongs on the same network as them. Create one if you have none yet, using '
                    . 'whatever name suits your stack.',
                'code' => 'docker network create media',
            ],
            [
                'title' => 'Write a compose file',
                'text' => 'One file, four values to adjust: the host port, your music folder, your download '
                    . 'folder, and the user that owns your files. The installation guide has it ready to copy.',
                'code' => "mkdir muzikk && cd muzikk\n\$EDITOR compose.yaml",
            ],
            [
                'title' => 'Start it',
                'text' => 'Compose pulls the image from Docker Hub and starts a single container.',
                'code' => 'docker compose up -d',
            ],
            [
                'title' => 'Finish in the browser',
                'text' => 'Open Muzikk on the port you published. The wizard asks, once and for good, whether '
                    . 'Jellyfin or Muzikk itself owns the accounts and the library. With Jellyfin, give the URL '
                    . 'and an API key, then sign in with a Jellyfin administrator. Locally, create the first '
                    . 'administrator and point at the mounted music folder.',
                'code' => null,
            ],
        ],
    ],

    'requirements' => [
        'title' => 'What you need around it',
        'lead' => 'Jellyfin is optional: skip it and Muzikk keeps the accounts and the library itself. '
            . 'Beyond that, one download provider is enough to get going.',
        'items' => [
            [
                'icon' => 'shield',
                'name' => 'Jellyfin',
                'text' => 'Accounts, permissions, the music library and the rescan — when you choose that mode.',
                'url' => 'https://jellyfin.org',
            ],
            [
                'icon' => 'search',
                'name' => 'MusicBrainz',
                'text' => 'The catalogue. A self-hosted instance with Solr is recommended; the public '
                    . 'server can stand in.',
                'url' => 'https://musicbrainz.org',
            ],
            [
                'icon' => 'waveform',
                'name' => 'slskd',
                'text' => 'Soulseek downloading. One of the two provider families.',
                'url' => 'https://github.com/slskd/slskd',
            ],
            [
                'icon' => 'layers',
                'name' => 'Prowlarr + qBittorrent',
                'text' => 'Torrent search and downloading. The other provider family.',
                'url' => 'https://prowlarr.com',
            ],
        ],
    ],
];
