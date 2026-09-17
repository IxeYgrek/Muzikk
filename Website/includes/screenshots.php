<?php
/**
 * The slideshow reads its own folders, so adding a capture is a file copy and
 * nothing else. Order comes from the file names, which is why numbering them
 * (01-home.png, 02-search.png) is worth the trouble.
 *
 * Folders are tried in the order given by config('screenshots_dirs'). The first
 * one that actually holds an image wins, so a drop into Images/Screenshot at
 * the project root is picked up without moving files into the site tree.
 *
 * A caption can be written in the language files under
 * home.shots.captions.<slug>, where the slug is the file name stripped of its
 * leading number and its extension. Without one, the name itself is tidied up
 * and used, so a screenshot is never left without a label.
 */

declare(strict_types=1);

const SCREENSHOT_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp', 'avif', 'gif'];

/**
 * Folders scanned for screenshots, as absolute paths, in priority order.
 *
 * @return list<string>
 */
function screenshot_folders(): array
{
    $site = dirname(__DIR__);
    $configured = config('screenshots_dirs');
    if (!is_array($configured) || $configured === []) {
        $single = trim((string) config('screenshots_dir'), '/\\');
        $configured = $single === '' ? [] : [$single];
    }

    $folders = [];
    foreach ($configured as $relative) {
        if (!is_string($relative) || $relative === '') {
            continue;
        }
        $path = $relative;
        if (!preg_match('#^[A-Za-z]:[\\\\/]#', $path) && !str_starts_with($path, '/')) {
            $path = $site . '/' . str_replace('\\', '/', $relative);
        }
        $resolved = realpath($path);
        if ($resolved !== false && is_dir($resolved)) {
            $folders[] = $resolved;
        }
    }

    return array_values(array_unique($folders));
}

/**
 * @return list<array{src: string, slug: string, caption: string, width: int|null, height: int|null}>
 */
function screenshots(): array
{
    static $found = null;
    if ($found !== null) {
        return $found;
    }

    foreach (screenshot_folders() as $folder) {
        $shots = screenshots_in($folder);
        if ($shots !== []) {
            return $found = $shots;
        }
    }

    return $found = [];
}

/**
 * @return list<array{src: string, slug: string, caption: string, width: int|null, height: int|null}>
 */
function screenshots_in(string $folder): array
{
    $files = [];
    foreach (scandir($folder) ?: [] as $entry) {
        if ($entry === '.' || $entry === '..') {
            continue;
        }
        $extension = strtolower(pathinfo($entry, PATHINFO_EXTENSION));
        if (in_array($extension, SCREENSHOT_EXTENSIONS, true) && is_file($folder . DIRECTORY_SEPARATOR . $entry)) {
            $files[] = $entry;
        }
    }
    // Natural order so 2 comes before 10 even when someone forgets the zero.
    natcasesort($files);

    $shots = [];
    foreach ($files as $file) {
        $slug = screenshot_slug($file);
        $absolute = $folder . DIRECTORY_SEPARATOR . $file;
        $size = @getimagesize($absolute);
        $shots[] = [
            'src' => screenshot_src($folder, $file),
            'slug' => $slug,
            'caption' => screenshot_caption($slug),
            'width' => is_array($size) ? (int) $size[0] : null,
            'height' => is_array($size) ? (int) $size[1] : null,
        ];
    }

    return $shots;
}

/**
 * A public URL for one capture. Files sitting under the site root are served
 * as regular assets; anything else goes through screenshot.php so a folder
 * next to Website/ stays reachable without being copied.
 */
function screenshot_src(string $folder, string $file): string
{
    $site = realpath(dirname(__DIR__));
    $inside = $site !== false && str_starts_with($folder, $site . DIRECTORY_SEPARATOR);
    if ($inside) {
        $relative = ltrim(str_replace('\\', '/', substr($folder, strlen($site))) . '/' . $file, '/');
        return asset($relative);
    }

    $query = ['f' => $file];
    $absolute = $folder . DIRECTORY_SEPARATOR . $file;
    if (is_file($absolute)) {
        $query['v'] = (string) filemtime($absolute);
    }
    return url('screenshot.php', $query);
}

/** Absolute path of one named capture, or null if it is not one of ours. */
function screenshot_file(string $name): ?string
{
    $base = basename($name);
    if ($base !== $name || $base === '' || $base === '.' || $base === '..') {
        return null;
    }
    $extension = strtolower(pathinfo($base, PATHINFO_EXTENSION));
    if (!in_array($extension, SCREENSHOT_EXTENSIONS, true)) {
        return null;
    }

    foreach (screenshot_folders() as $folder) {
        $candidate = $folder . DIRECTORY_SEPARATOR . $base;
        $resolved = realpath($candidate);
        if ($resolved !== false && is_file($resolved) && str_starts_with($resolved, $folder . DIRECTORY_SEPARATOR)) {
            return $resolved;
        }
    }

    return null;
}

/** Folder shown in the empty-state hint: the first configured path. */
function screenshots_hint_folder(): string
{
    $dirs = config('screenshots_dirs');
    if (is_array($dirs) && isset($dirs[0]) && is_string($dirs[0]) && $dirs[0] !== '') {
        return $dirs[0];
    }
    return (string) config('screenshots_dir');
}

/** "03_metadata-page.png" becomes "metadata-page". */
function screenshot_slug(string $file): string
{
    $name = pathinfo($file, PATHINFO_FILENAME);
    return (string) preg_replace('/^\d+\s*[-_.]?\s*/', '', $name);
}

/** A translated caption when one exists, a readable file name otherwise. */
function screenshot_caption(string $slug): string
{
    foreach ([$slug, strtolower($slug)] as $candidate) {
        $key = 'home.shots.captions.' . $candidate;
        $caption = t($key);
        if ($caption !== $key) {
            return $caption;
        }
    }
    $words = trim((string) preg_replace('/[-_]+/', ' ', $slug));
    return $words === '' ? '' : ucfirst($words);
}
