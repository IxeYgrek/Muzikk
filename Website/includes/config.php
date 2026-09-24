<?php
/**
 * Every setting an operator may want to change lives here.
 */

declare(strict_types=1);

return [
    'app_name' => 'Muzikk',
    'app_version' => '0.2.0',

    // Absolute base URL used for canonical and Open Graph tags. Left empty, it
    // is derived from the incoming request.
    'site_url' => '',

    'github_url' => 'https://github.com/IxeYgrek/Muzikk',
    'docker_hub_url' => 'https://hub.docker.com/r/ixeygrek/muzikk',
    'docker_image' => 'ixeygrek/muzikk',
    'discord_url' => 'https://discord.gg/rKE8hGXwY2',

    // Languages the site ships with, keyed by their folder name under lang/.
    // Adding an entry is all it takes: the selector appears by itself as soon
    // as a second language exists, and stays hidden while there is only one.
    'languages' => [
        'en' => ['label' => 'English', 'html_lang' => 'en'],
    ],
    'default_language' => 'en',

    // Folders scanned for the slideshow, in priority order. Relative paths are
    // resolved from the Website/ folder. The first directory that actually
    // contains an image is the one shown. Drop captures in Images/Screenshot
    // at the project root and they appear without being copied into the site.
    'screenshots_dirs' => [
        '../Images/Screenshot',
        'Images/Screenshot',
        'assets/img/screenshots',
    ],
    'screenshots_dir' => '../Images/Screenshot',
];
