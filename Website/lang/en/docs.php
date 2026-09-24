<?php
/**
 * The installation page: getting the container running, and nothing else.
 * Everything about using Muzikk afterwards lives in guide.php.
 *
 * Each section becomes an entry in the table of contents on its own. A block is
 * one of: p, h3, list, code, table, note, warning.
 */

declare(strict_types=1);

return [
    'eyebrow' => 'Installation',
    'title' => 'Install Muzikk',
    'lead' => 'One container, one compose file. The only part worth reading twice is the paths: '
        . 'that is where almost every problem actually comes from.',
    'tocTitle' => 'On this page',
    'copy' => 'Copy',
    'copied' => 'Copied',

    // Used by the footer and by the download page, which link a few sections.
    'nav' => [
        'requirements' => 'Requirements',
        'install' => 'Installation',
        'paths' => 'Paths and permissions',
        'firstRun' => 'First start',
    ],

    'sections' => [
        [
            'id' => 'requirements',
            'title' => 'What you need',
            'blocks' => [
                ['type' => 'p', 'text' => 'Docker with the Compose plugin, a folder holding your music, and '
                    . 'somewhere to put downloads. Muzikk itself is a <strong>single container</strong>: the API, '
                    . 'the interface and the background worker all run inside it, on an SQLite database. There is '
                    . 'no Redis and no Postgres to provision.'],
                ['type' => 'p', 'text' => 'Everything else is optional and can be added later, from the interface:'],
                ['type' => 'table', 'head' => ['Service', 'What it brings', 'Needed?'], 'rows' => [
                    ['Jellyfin', 'Accounts and the music library', 'Optional — Muzikk can own both itself'],
                    ['MusicBrainz', 'The catalogue searched when you look for an album', 'Optional — musicbrainz.org is used otherwise'],
                    ['slskd', 'Downloading from Soulseek', 'One provider is enough'],
                    ['Prowlarr + qBittorrent', 'Downloading from torrents', 'One provider is enough'],
                ]],
                ['type' => 'note', 'text' => '<strong>Put Muzikk on the same Docker network as those services.</strong> '
                    . 'Containers on one network reach each other by name, so Muzikk can be pointed at '
                    . '<code>http://jellyfin:8096</code> or <code>http://musicbrainz:5000</code> and keep working '
                    . 'when host addresses change. Without it you are back to host IPs and published ports, which '
                    . 'is where "connection refused" comes from.'],
            ],
        ],
        [
            'id' => 'install',
            'title' => 'Install with Docker Compose',
            'blocks' => [
                ['type' => 'p', 'text' => 'Create a folder, drop this <code>compose.yaml</code> in it, adjust the '
                    . 'four values marked below, and start it. Nothing to clone and nothing to build.'],
                ['type' => 'code', 'lang' => 'yaml', 'body' => <<<'CODE'
services:
  muzikk:
    image: ixeygrek/muzikk:latest
    container_name: muzikk
    restart: unless-stopped
    environment:
      # Owner of the files Muzikk writes. Must match your music library,
      # otherwise your media server cannot read what was imported.
      PUID: 1000
      PGID: 1000
      UMASK: 002
      TZ: Europe/Paris
    ports:
      # Left side: any free port on your host. Right side: always 8383.
      - "8383:8383"
    volumes:
      # Database, keys, cover cache and logs. Keep it.
      - ./config:/config
      # Your music library. Left: the host path. Right: how Muzikk sees it.
      - /path/to/your/music:/music
      # Your download folder, shared with slskd and/or qBittorrent.
      - /path/to/your/downloads:/downloads
    networks:
      - media

networks:
  # The network your other containers already use. Adjust the name.
  media:
    external: true
CODE],
                ['type' => 'code', 'lang' => 'bash', 'body' => <<<'CODE'
docker compose up -d
CODE],
                ['type' => 'p', 'text' => 'Muzikk is then on <code>http://your-host:PORT</code>, where '
                    . '<code>PORT</code> is the left side of the mapping you chose above.'],
                ['type' => 'note', 'text' => 'Inside the container Muzikk always listens on <strong>8383</strong>. '
                    . 'Only the left side of <code>"8383:8383"</code> is yours to change — <code>"9000:8383"</code> '
                    . 'serves it on port 9000, and running a second instance means a second left-hand port, never a '
                    . 'second right-hand one.'],
                ['type' => 'h3', 'text' => 'If you have no Docker network yet'],
                ['type' => 'p', 'text' => 'Create one, then attach your other containers to it as well:'],
                ['type' => 'code', 'lang' => 'bash', 'body' => 'docker network create media'],
                ['type' => 'p', 'text' => 'If a service runs directly on the host rather than in Docker, add '
                    . '<code>extra_hosts: ["host.docker.internal:host-gateway"]</code> to the compose file and '
                    . 'address it as <code>http://host.docker.internal:PORT</code>.'],
            ],
        ],
        [
            'id' => 'paths',
            'title' => 'Paths and permissions',
            'blocks' => [
                ['type' => 'table', 'head' => ['Mounted on', 'Holds'], 'rows' => [
                    ['<code>/config</code>', 'SQLite database, encryption key, cover cache, logs'],
                    ['<code>/music</code>', 'Your library, and where imported albums are filed'],
                    ['<code>/downloads</code>', 'The download folder shared with slskd and qBittorrent'],
                ]],
                ['type' => 'warning', 'text' => '<strong>Mount your downloads on the same path every container '
                    . 'uses.</strong> Muzikk reads the locations slskd and qBittorrent report, so if qBittorrent '
                    . 'writes to <code>/downloads/torrents</code>, Muzikk has to see that folder at that exact '
                    . 'path. Keep it on the same filesystem as the library too, otherwise imports are copied '
                    . 'instead of hardlinked and everything still seeding gets duplicated.'],
                ['type' => 'p', 'text' => 'The same goes for the library when Jellyfin is in the stack: give Muzikk '
                    . 'the path Jellyfin itself reports for its albums. Mounting one host disk twice on two '
                    . 'different paths is fine — hardlinks keep working, since it is still one filesystem.'],
                ['type' => 'p', 'text' => '<code>PUID</code> and <code>PGID</code> must match the owner of your '
                    . 'music files. Get them with <code>id</code> on the host. When they are wrong, imports land '
                    . 'with the wrong owner and your media server quietly ignores them.'],
            ],
        ],
        [
            'id' => 'first-run',
            'title' => 'First start',
            'blocks' => [
                ['type' => 'p', 'text' => 'Open the interface. A wizard runs once and then closes for good. Its '
                    . 'first question cannot be revisited: who owns the accounts and the library.'],
                ['type' => 'list', 'items' => [
                    '<strong>With Jellyfin</strong> — its URL and an API key created under <em>Dashboard → '
                        . 'Advanced → API keys</em>. Pick the music libraries to watch, then sign in with a '
                        . 'Jellyfin <strong>administrator</strong> account: it becomes a Muzikk administrator.',
                    '<strong>Local only</strong> — no media server involved. Create the first administrator and '
                        . 'point Muzikk at the library folder as the container sees it, normally '
                        . '<code>/music</code>. Playlists are unavailable in this mode, since they live in '
                        . 'Jellyfin.',
                ]],
                ['type' => 'p', 'text' => 'Indexing then starts in the background. On a large library, expect a few '
                    . 'minutes before the "already owned" badges appear.'],
                ['type' => 'p', 'text' => 'Everything else — download providers, quality rules, file naming — is '
                    . 'configured from <strong>Administration</strong> afterwards, and covered in the '
                    . '<a href="guide.php">user guide</a>.'],
            ],
        ],
        [
            'id' => 'environment',
            'title' => 'Environment variables',
            'blocks' => [
                ['type' => 'p', 'text' => 'Only infrastructure goes through the environment. Everything else is set '
                    . 'in the interface, where it can be tested before being saved.'],
                ['type' => 'table', 'head' => ['Variable', 'Default', 'Role'], 'rows' => [
                    ['<code>PUID</code> / <code>PGID</code>', '<code>1000</code>', 'Owner of the files Muzikk writes'],
                    ['<code>UMASK</code>', '<code>002</code>', 'Mask applied to imported files'],
                    ['<code>TZ</code>', '<code>Europe/Paris</code>', 'Container time zone'],
                    ['<code>MUZIKK_LOG_LEVEL</code>', '<code>INFO</code>', '<code>DEBUG</code>, <code>INFO</code> or <code>WARNING</code>'],
                    ['<code>MUZIKK_WORKER_CONCURRENCY</code>', '<code>2</code>', 'Jobs handled in parallel, 1 to 8'],
                    ['<code>MUZIKK_SESSION_HOURS</code>', '<code>336</code>', 'How long a session stays valid'],
                    ['<code>MUZIKK_CONFIG_DIR</code>', '<code>/config</code>', 'Only if you mount the config elsewhere'],
                ]],
            ],
        ],
        [
            'id' => 'update',
            'title' => 'Updating and backing up',
            'blocks' => [
                ['type' => 'code', 'lang' => 'bash', 'body' => "docker compose pull\ndocker compose up -d"],
                ['type' => 'p', 'text' => 'Database migrations run on their own at startup. To pin a version rather '
                    . 'than follow <code>latest</code>, replace the tag: <code>ixeygrek/muzikk:0.2.0</code>.'],
                ['type' => 'p', 'text' => 'Your whole installation is the <code>/config</code> folder. Copy it while '
                    . 'the container is stopped and you have a complete backup.'],
            ],
        ],
        [
            'id' => 'build',
            'title' => 'Building the image yourself',
            'blocks' => [
                ['type' => 'p', 'text' => 'Only useful if you want to change the code. The published image is the '
                    . 'normal way in.'],
                ['type' => 'code', 'lang' => 'bash', 'body' => <<<'CODE'
git clone https://github.com/IxeYgrek/Muzikk.git muzikk
cd muzikk
cp .env.example .env
$EDITOR .env
docker compose up -d --build
CODE],
                ['type' => 'p', 'text' => 'The compose file in the repository reads its paths and ports from '
                    . '<code>.env</code>, which is why that route needs one and the compose file above does not.'],
            ],
        ],
        [
            'id' => 'install-help',
            'title' => 'It does not start',
            'blocks' => [
                ['type' => 'faq', 'items' => [
                    [
                        'q' => 'The page does not load at all',
                        'a' => 'Check the container is up and healthy with <code>docker compose ps</code>, then read '
                            . '<code>docker compose logs -f muzikk</code>. A container stuck restarting is almost '
                            . 'always a volume it cannot write to, or a host port already taken by something else.',
                    ],
                    [
                        'q' => 'Muzikk cannot reach Jellyfin, slskd or Prowlarr',
                        'a' => 'They have to share a Docker network for container names to resolve. Verify with '
                            . '<code>docker network inspect &lt;network&gt;</code> that every container is listed. '
                            . 'Inside a network you use the <strong>internal</strong> port of the service, not the '
                            . 'one published on the host.',
                    ],
                    [
                        'q' => 'The library stays empty',
                        'a' => 'The mount is likely wrong. <code>docker compose exec muzikk ls /music</code> shows '
                            . 'what Muzikk actually sees. In Jellyfin mode, also check the wizard selected the right '
                            . 'music libraries.',
                    ],
                    [
                        'q' => 'Imported files are ignored by my media server',
                        'a' => 'A permissions problem: <code>PUID</code>, <code>PGID</code> and <code>UMASK</code> '
                            . 'must let it read what Muzikk wrote. Compare with <code>ls -l</code> on an album that '
                            . 'does work.',
                    ],
                ]],
                ['type' => 'p', 'text' => 'Logs are in <code>/config/logs/muzikk.log</code> and in '
                    . '<code>docker compose logs -f muzikk</code> — both receive the same thing. Anything about '
                    . 'using Muzikk rather than installing it is in the <a href="guide.php">user guide</a>.'],
            ],
        ],
    ],
];
