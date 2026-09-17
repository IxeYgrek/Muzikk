<?php
/**
 * Translation loading and language negotiation.
 *
 * A language is a folder under lang/. Each file inside returns an array and is
 * namespaced after its own name, so lang/en/home.php returning
 * ['hero' => ['title' => 'x']] is read as t('home.hero.title').
 *
 * Strings are authored in this repository, so they may hold inline markup and
 * are echoed as-is. Anything coming from the request is escaped with e().
 */

declare(strict_types=1);

const LANG_COOKIE = 'muzikk_site_lang';

/** Languages declared in the configuration, in declaration order. */
function languages(): array
{
    return config('languages');
}

/** True when the language selector is worth showing at all. */
function is_multilingual(): bool
{
    return count(languages()) > 1;
}

/**
 * Language used for this request: an explicit choice wins, then the visitor's
 * previous choice, then what the browser asks for, then the default.
 */
function current_language(): string
{
    static $language = null;
    if ($language !== null) {
        return $language;
    }

    $available = languages();
    $requested = isset($_GET['lang']) && is_string($_GET['lang']) ? $_GET['lang'] : null;

    if ($requested !== null && isset($available[$requested])) {
        $language = $requested;
        // 180 days, and scoped to the site so a subfolder install stays tidy.
        setcookie(LANG_COOKIE, $language, [
            'expires' => time() + 15552000,
            'path' => base_path() === '' ? '/' : base_path(),
            'samesite' => 'Lax',
        ]);
        return $language;
    }

    $stored = $_COOKIE[LANG_COOKIE] ?? null;
    if (is_string($stored) && isset($available[$stored])) {
        return $language = $stored;
    }

    $language = negotiate_language(array_keys($available)) ?? config('default_language');
    return $language;
}

/** Best match between Accept-Language and what the site offers. */
function negotiate_language(array $available): ?string
{
    $header = $_SERVER['HTTP_ACCEPT_LANGUAGE'] ?? '';
    if ($header === '') {
        return null;
    }

    $ranked = [];
    foreach (explode(',', $header) as $chunk) {
        $parts = explode(';q=', trim($chunk));
        $tag = strtolower(trim($parts[0]));
        if ($tag === '') {
            continue;
        }
        $quality = isset($parts[1]) ? (float) $parts[1] : 1.0;
        // "fr-CA" should still match a plain "fr" catalogue.
        $ranked[$tag] = max($ranked[$tag] ?? 0.0, $quality);
        $primary = explode('-', $tag)[0];
        $ranked[$primary] = max($ranked[$primary] ?? 0.0, $quality - 0.001);
    }
    arsort($ranked);

    foreach (array_keys($ranked) as $tag) {
        if (in_array($tag, $available, true)) {
            return $tag;
        }
    }
    return null;
}

/** The html lang attribute for the current language. */
function html_lang(): string
{
    $language = current_language();
    return languages()[$language]['html_lang'] ?? $language;
}

/** Every string of the current language, falling back to the default one. */
function strings(): array
{
    static $cache = [];
    $language = current_language();
    if (isset($cache[$language])) {
        return $cache[$language];
    }

    $loaded = load_language($language);
    $fallback = config('default_language');
    if ($language !== $fallback) {
        // A partial translation shows translated strings and keeps the rest in
        // the default language rather than showing raw keys.
        $loaded = array_replace_recursive(load_language($fallback), $loaded);
    }

    return $cache[$language] = $loaded;
}

/** Reads every file of one language folder into a single namespaced array. */
function load_language(string $language): array
{
    $folder = dirname(__DIR__) . '/lang/' . $language;
    if (!is_dir($folder)) {
        return [];
    }

    $strings = [];
    foreach (glob($folder . '/*.php') ?: [] as $file) {
        $namespace = basename($file, '.php');
        $content = require $file;
        if (is_array($content)) {
            $strings[$namespace] = $content;
        }
    }
    return $strings;
}

/**
 * Looks a key up by dot notation. A missing key returns the key itself, which
 * is loud enough to spot on the page without breaking it.
 *
 * @return string|array<mixed>
 */
function lookup(string $key)
{
    $value = strings();
    foreach (explode('.', $key) as $segment) {
        if (!is_array($value) || !array_key_exists($segment, $value)) {
            return $key;
        }
        $value = $value[$segment];
    }
    return $value;
}

/**
 * A translated string, with {placeholder} substitution.
 */
function t(string $key, array $values = []): string
{
    $value = lookup($key);
    if (!is_string($value)) {
        return $key;
    }
    foreach ($values as $name => $replacement) {
        $value = str_replace('{' . $name . '}', (string) $replacement, $value);
    }
    return $value;
}

/**
 * A translated list or structure.
 */
function tl(string $key): array
{
    $value = lookup($key);
    return is_array($value) ? $value : [];
}

/** Escapes anything that did not come from a language file. */
function e(?string $value): string
{
    return htmlspecialchars($value ?? '', ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}
