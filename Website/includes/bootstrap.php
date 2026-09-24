<?php
/**
 * Loaded first by every page: configuration, helpers, translations, icons.
 */

declare(strict_types=1);

/** One configuration value. */
function config(string $key)
{
    static $values = null;
    if ($values === null) {
        $values = require __DIR__ . '/config.php';
    }
    return $values[$key] ?? null;
}

/**
 * Folder the site is served from, without a trailing slash. Works both at a
 * domain root and inside a subfolder, so no absolute URL has to be configured.
 */
function base_path(): string
{
    static $path = null;
    if ($path !== null) {
        return $path;
    }
    $script = $_SERVER['SCRIPT_NAME'] ?? '';
    $folder = rtrim(str_replace('\\', '/', dirname($script)), '/');
    return $path = ($folder === '/' || $folder === '.') ? '' : $folder;
}

/** A link to one of the site pages, keeping the chosen language. */
function url(string $page = '', array $query = []): string
{
    $link = base_path() . '/' . ltrim($page, '/');
    if ($query !== []) {
        $link .= '?' . http_build_query($query);
    }
    return $link;
}

/** A link to a static asset, cache-busted by its own modification time. */
function asset(string $path): string
{
    $relative = ltrim($path, '/');
    $file = dirname(__DIR__) . '/' . $relative;
    $link = base_path() . '/' . $relative;
    if (is_file($file)) {
        $link .= '?v=' . filemtime($file);
    }
    return $link;
}

/** Absolute URL of the current page, for canonical and Open Graph tags. */
function canonical_url(): string
{
    $configured = rtrim((string) config('site_url'), '/');
    if ($configured !== '') {
        return $configured . current_page_path();
    }
    $https = ($_SERVER['HTTPS'] ?? '') !== '' && ($_SERVER['HTTPS'] ?? '') !== 'off';
    $scheme = $https ? 'https' : 'http';
    $host = $_SERVER['HTTP_HOST'] ?? 'localhost';
    return $scheme . '://' . $host . current_page_path();
}

/** Path of the page being served, without its query string. */
function current_page_path(): string
{
    $path = explode('?', $_SERVER['REQUEST_URI'] ?? '/')[0];
    return $path === '' ? '/' : $path;
}

/** File name of the page being served, used to light up the navigation. */
function current_page(): string
{
    return basename($_SERVER['SCRIPT_NAME'] ?? 'index.php');
}

/** The project repository, or null while it is not published yet. */
function repository_url(): ?string
{
    $url = trim((string) config('github_url'));
    return $url === '' ? null : $url;
}

/** The Docker Hub page, or null while the image is not published yet. */
function docker_hub_url(): ?string
{
    $url = trim((string) config('docker_hub_url'));
    return $url === '' ? null : $url;
}

/** The Discord support server, or null while it is not published yet. */
function discord_url(): ?string
{
    $url = trim((string) config('discord_url'));
    return $url === '' ? null : $url;
}

/** Image name on Docker Hub, without a tag. */
function docker_image(): string
{
    $image = trim((string) config('docker_image'));
    return $image === '' ? 'ixeygrek/muzikk' : $image;
}

require __DIR__ . '/i18n.php';
require __DIR__ . '/icons.php';
require __DIR__ . '/screenshots.php';
require __DIR__ . '/layout.php';
require __DIR__ . '/docpage.php';
