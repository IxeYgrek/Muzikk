# Muzikk — website

The showcase site for Muzikk: one landing page, a documentation page and a
download page. Plain PHP, HTML5, CSS3 and vanilla JavaScript — no build step, no
package manager, no framework.

## Running it

Any PHP 8.0 or later will do.

```bash
cd Website
php -S localhost:8000
```

Then open <http://localhost:8000>.

On a real server, point the document root at this folder. Nothing outside it
needs to be reachable, and `includes/` and `lang/` only ever hold PHP that is
included, never served.

## Layout

```
Website/
├── index.php              landing page: hero, presentation, features, slideshow
├── documentation.php      installation and configuration guide
├── download.php           repository link and quick start
├── includes/
│   ├── bootstrap.php      configuration accessor, URL helpers, loads the rest
│   ├── config.php         everything an operator may want to change
│   ├── i18n.php           language negotiation and the t() helper
│   ├── icons.php          inline SVG icons and the Muzikk mark
│   ├── layout.php         head, header, footer, shared render helpers
│   └── screenshots.php    reads the slideshow folder
├── lang/
│   └── en/
│       ├── common.php     navigation, footer, shared strings
│       ├── home.php       hero, presentation, feature categories, captions
│       ├── docs.php       the whole documentation, as structured blocks
│       └── download.php   download page
└── assets/
    ├── css/               base.css (tokens), components.css, pages.css
    ├── js/site.js         navigation, reveals, copy buttons, slideshow
    └── img/               logo, favicon, social card, screenshots/
```

## Configuration

Everything lives in `includes/config.php`.

| Key | What it does |
| --- | --- |
| `app_name`, `app_version` | Shown in the wordmark, the title and the footer |
| `site_url` | Absolute base URL for canonical and Open Graph tags; derived from the request when empty |
| `github_url` | Source repository. Empty keeps the download page in a "coming soon" state |
| `docker_hub_url` | Docker Hub page for the published image |
| `docker_image` | Image name used in `docker pull`, without a tag |
| `languages` | Languages the site ships with |
| `default_language` | Used when the browser asks for something unavailable |
| `screenshots_dir` | Folder scanned by the slideshow |

## Adding a language

1. Copy `lang/en` to `lang/<code>`, for instance `lang/fr`.
2. Translate the four files. Keys are never translated, only values. Missing
   keys fall back to the default language, so a partial translation is fine.
3. Add the entry in `includes/config.php`:

```php
'languages' => [
    'en' => ['label' => 'English', 'html_lang' => 'en'],
    'fr' => ['label' => 'Français', 'html_lang' => 'fr'],
],
```

The selector appears in the header on its own as soon as there is a second
language, and stays completely hidden while there is only one. A visitor's
choice is kept in a cookie; without one, `Accept-Language` decides.

Strings are authored in this repository and may contain inline markup such as
`<strong>` or `<code>`, so they are printed as-is. Anything coming from the
request goes through `e()` instead.

## Adding a screenshot

Copy the image into `Images/Screenshot` at the project root (next to
`Website/`). The slideshow reads that folder first. Two fallbacks exist if
it is empty: `Website/Images/Screenshot`, then `Website/assets/img/screenshots`.

Number the files (`01-home.png`, `02-search.png`) to control the order. A
caption can be added in `lang/en/home.php` under `home.shots.captions.<slug>`.
While every folder is empty, the section shows a short note instead of a
blank frame.

## Editing the documentation

`lang/en/docs.php` holds the documentation as a list of sections, each with a
list of blocks. The table of contents, the anchors and the footer links are
generated from it, so adding a section is a single array entry.

Block types: `p`, `h3`, `list` (with `ordered`), `code` (with `lang`), `table`
(with `head` and `rows`), `note`, `warning`, `faq`.

## Notes

- `assets/img/social-card.svg` is used for `og:image`. Most social platforms
  only render raster images, so export it to PNG at 1200×630 and point the tag
  at that file before sharing links widely.
- The fonts come from Google Fonts, exactly as the application does. Self-host
  them if the site has to work without outbound network access.
