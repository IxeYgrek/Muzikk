<?php
/**
 * The download page.
 */

declare(strict_types=1);

return [
    'title' => 'Download',
    'eyebrow' => 'Get Muzikk',
    'lead' => 'Pull the image from Docker Hub, or clone the source and build it yourself. '
        . 'One compose file, three volumes, and a Jellyfin API key.',

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
        'docsButton' => 'Read the documentation',
    ],

    'version' => [
        'label' => 'Current version',
        'license' => 'Self-hosted, no telemetry, no account outside your own Jellyfin.',
    ],

    'quickstart' => [
        'title' => 'Quick start',
        'lead' => 'The published image is enough. Clone the repository only if you want the compose file and the documentation next to it.',
        'steps' => [
            [
                'title' => 'Create the shared network',
                'text' => 'Muzikk reaches Jellyfin, slskd, Prowlarr and qBittorrent by container name, so '
                    . 'they all need to sit on one external network.',
                'code' => 'docker network create mediastack',
            ],
            [
                'title' => 'Clone and configure',
                'text' => 'Set <code>PUID</code> and <code>PGID</code> to the owner of your music library, '
                    . 'then give the host paths for the library and the downloads.',
                'code' => <<<'CODE'
git clone https://github.com/IxeYgrek/Muzikk.git muzikk
cd muzikk
cp .env.example .env
$EDITOR .env
CODE,
            ],
            [
                'title' => 'Pull and start',
                'text' => 'Compose pulls <code>ixeygrek/muzikk</code> from Docker Hub. Add '
                    . '<code>--build</code> only if you want to build from the source you just cloned.',
                'code' => "docker compose pull\ndocker compose up -d",
            ],
            [
                'title' => 'Finish in the browser',
                'text' => 'Open <code>http://your-host:8383</code>, give the setup wizard your Jellyfin URL '
                    . 'and API key, pick the music libraries, then sign in with a Jellyfin administrator '
                    . 'account.',
                'code' => null,
            ],
        ],
    ],

    'requirements' => [
        'title' => 'What you need around it',
        'lead' => 'Jellyfin is required. Beyond that, one download provider is enough to get going.',
        'items' => [
            [
                'icon' => 'shield',
                'name' => 'Jellyfin',
                'text' => 'Accounts, permissions, the music library and the rescan. Required.',
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
