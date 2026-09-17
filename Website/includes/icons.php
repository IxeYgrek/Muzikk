<?php
/**
 * Inline SVG icons, drawn on the same 24x24 grid and with the same stroke as
 * the Lucide set the application itself uses.
 */

declare(strict_types=1);

/** Path data of every icon, keyed by name. */
function icon_paths(): array
{
    return [
        'search' => '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
        'disc' => '<circle cx="12" cy="12" r="10"/><path d="M6 12c0-1.7.7-3.2 1.8-4.2"/><circle cx="12" cy="12" r="2"/><path d="M18 12c0 1.7-.7 3.2-1.8 4.2"/>',
        'download' => '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/><path d="M12 15V3"/>',
        'tag' => '<path d="M12.586 2.586A2 2 0 0 0 11.172 2H4a2 2 0 0 0-2 2v7.172a2 2 0 0 0 .586 1.414l8.704 8.704a2.426 2.426 0 0 0 3.42 0l6.58-6.58a2.426 2.426 0 0 0 0-3.42z"/><circle cx="7.5" cy="7.5" r=".5" fill="currentColor"/>',
        'sliders' => '<path d="M21 4h-7"/><path d="M10 4H3"/><path d="M21 12h-9"/><path d="M8 12H3"/><path d="M21 20h-5"/><path d="M12 20H3"/><path d="M14 2v4"/><path d="M8 10v4"/><path d="M16 18v4"/>',
        'play' => '<path d="M6 3l14 9-14 9z"/>',
        'pause' => '<rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/>',
        'book' => '<path d="M12 7v14"/><path d="M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z"/>',
        'github' => '<path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 2-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.403 5.403 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4"/><path d="M9 18c-4.51 2-5-2-7-2"/>',
        'chevron-left' => '<path d="m15 18-6-6 6-6"/>',
        'chevron-right' => '<path d="m9 18 6-6-6-6"/>',
        'chevron-down' => '<path d="m6 9 6 6 6-6"/>',
        'check' => '<path d="M20 6 9 17l-5-5"/>',
        'arrow-right' => '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
        'terminal' => '<path d="m4 17 6-6-6-6"/><path d="M12 19h8"/>',
        'copy' => '<rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
        'server' => '<rect width="20" height="8" x="2" y="2" rx="2"/><rect width="20" height="8" x="2" y="14" rx="2"/><path d="M6 6h.01"/><path d="M6 18h.01"/>',
        'shield' => '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>',
        'menu' => '<path d="M4 6h16"/><path d="M4 12h16"/><path d="M4 18h16"/>',
        'close' => '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
        'waveform' => '<path d="M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2"/>',
        'layers' => '<path d="M12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83z"/><path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/><path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/>',
        'users' => '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
        'box' => '<path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/>',
        'list-music' => '<path d="M21 15V6"/><path d="M18.5 18a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5"/><path d="M12 12H3"/><path d="M16 6H3"/><path d="M12 18H3"/>',
        'headphones' => '<path d="M3 14h3a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-7a9 9 0 0 1 18 0v7a2 2 0 0 1-2 2h-1a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2h3"/>',
        'sparkles' => '<path d="M9.94 14.06 8.5 18l-1.44-3.94L3 12.5l4.06-1.44L8.5 7l1.44 4.06L14 12.5z"/><path d="M18 5.5 18.8 8 21 8.8 18.8 9.6 18 12l-.8-2.4L15 8.8 17.2 8z"/><path d="M17.5 15.5 18 17l1.5.5L18 18l-.5 1.5L17 18l-1.5-.5L17 17z"/>',
        'globe' => '<circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/>',
        'folder' => '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
        'alert' => '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
        'image' => '<rect width="18" height="18" x="3" y="3" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.09-3.09a2 2 0 0 0-2.82 0L6 21"/>',
        'docker' => '<path d="M4.5 10h3v3h-3z"/><path d="M8 10h3v3H8z"/><path d="M11.5 10h3v3h-3z"/><path d="M8 6.5h3V9.5H8z"/><path d="M11.5 6.5h3V9.5h-3z"/><path d="M4.2 14.2c-.4 1.6.2 2.8 1.6 3.4 2.1.9 5.8.7 8.2-.4 1.8-.8 2.9-2.1 3.3-3.8.6 0 2.4.1 3.2-1.3.4-.7.3-1.6-.1-2.1-.6-.7-1.6-.6-1.6-.6s.2-1.1-.5-1.8c-.6-.6-1.5-.5-1.9-.3"/><path d="M3 13.5h15"/>',
    ];
}

/**
 * Renders one icon. Decorative by default; pass a label to expose it.
 */
function icon(string $name, string $class = '', ?string $label = null): string
{
    $paths = icon_paths()[$name] ?? null;
    if ($paths === null) {
        return '';
    }

    $attributes = $label === null
        ? ' aria-hidden="true" focusable="false"'
        : ' role="img" aria-label="' . e($label) . '"';

    return '<svg class="icon' . ($class !== '' ? ' ' . e($class) : '') . '" viewBox="0 0 24 24"'
        . ' fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"'
        . ' stroke-linejoin="round"' . $attributes . '>' . $paths . '</svg>';
}

/**
 * The Muzikk mark: five equaliser bars whose tops trace an M, exactly as the
 * application draws it.
 */
function logo_mark(string $class = ''): string
{
    $id = 'muzikk-mark-' . substr(md5($class . random_int(0, PHP_INT_MAX)), 0, 8);
    return '<svg class="logo-mark' . ($class !== '' ? ' ' . e($class) : '') . '"'
        . ' viewBox="0 0 64 64" aria-hidden="true" focusable="false">'
        . '<defs><linearGradient id="' . $id . '" x1="0" y1="0" x2="1" y2="1">'
        . '<stop offset="0%" stop-color="#8B5CF6"/>'
        . '<stop offset="55%" stop-color="#7C3AED"/>'
        . '<stop offset="100%" stop-color="#DB2777"/>'
        . '</linearGradient></defs>'
        . '<g fill="url(#' . $id . ')">'
        . '<rect x="5" y="10" width="8" height="46" rx="4"/>'
        . '<rect x="17" y="22" width="8" height="34" rx="4"/>'
        . '<rect x="29" y="34" width="8" height="22" rx="4"/>'
        . '<rect x="41" y="22" width="8" height="34" rx="4"/>'
        . '<rect x="53" y="10" width="8" height="46" rx="4"/>'
        . '</g></svg>';
}
