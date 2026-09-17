<?php
/**
 * The shell every page is wrapped in: head, header, footer, and the small
 * render helpers shared by more than one page.
 */

declare(strict_types=1);

/** Main navigation, in display order. */
function nav_items(): array
{
    return [
        ['label' => t('common.nav.overview'), 'href' => url('index.php'), 'page' => 'index.php'],
        ['label' => t('common.nav.features'), 'href' => url('index.php') . '#features', 'page' => null],
        ['label' => t('common.nav.docs'), 'href' => url('documentation.php'), 'page' => 'documentation.php'],
    ];
    // Download is not listed here: it is the call to action on the right of the
    // header, and having it twice only made the bar look padded out.
}

/**
 * Opens the document and prints the header.
 *
 * @param array{title?: string, description?: string, class?: string} $options
 */
function page_start(array $options = []): void
{
    $name = (string) config('app_name');
    $title = $options['title'] ?? null;
    $fullTitle = $title === null ? $name . ' — ' . t('common.tagline') : $title . ' — ' . $name;
    $description = $options['description'] ?? t('common.description');
    $bodyClass = $options['class'] ?? '';
    $repository = repository_url();
    ?>
<!DOCTYPE html>
<html lang="<?= e(html_lang()) ?>">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title><?= e($fullTitle) ?></title>
    <meta name="description" content="<?= e($description) ?>">
    <meta name="theme-color" content="#0b0a12">
    <meta name="color-scheme" content="dark">
    <link rel="canonical" href="<?= e(canonical_url()) ?>">
    <link rel="icon" type="image/svg+xml" href="<?= e(asset('assets/img/favicon.svg')) ?>">
    <meta property="og:type" content="website">
    <meta property="og:site_name" content="<?= e($name) ?>">
    <meta property="og:title" content="<?= e($fullTitle) ?>">
    <meta property="og:description" content="<?= e($description) ?>">
    <meta property="og:url" content="<?= e(canonical_url()) ?>">
    <meta property="og:image" content="<?= e(asset('assets/img/social-card.svg')) ?>">
    <meta name="twitter:card" content="summary_large_image">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600&display=swap">
    <link rel="stylesheet" href="<?= e(asset('assets/css/base.css')) ?>">
    <link rel="stylesheet" href="<?= e(asset('assets/css/components.css')) ?>">
    <link rel="stylesheet" href="<?= e(asset('assets/css/pages.css')) ?>">
</head>
<body<?= $bodyClass !== '' ? ' class="' . e($bodyClass) . '"' : '' ?>>
<a class="skip-link" href="#main"><?= t('common.skipToContent') ?></a>
<div class="page-glow" aria-hidden="true"></div>

<header class="site-header" id="site-header">
    <div class="shell site-header__inner">
        <a class="brand" href="<?= e(url('index.php')) ?>">
            <?= logo_mark('brand__mark') ?>
            <span class="brand__text gradient-text"><?= e($name) ?></span>
        </a>

        <button class="nav-toggle" type="button" aria-expanded="false" aria-controls="site-nav"
                data-nav-toggle aria-label="<?= e(t('common.nav.menu')) ?>">
            <?= icon('menu', 'nav-toggle__open') ?>
            <?= icon('close', 'nav-toggle__close') ?>
        </button>

        <nav class="site-nav" id="site-nav" aria-label="<?= e(t('common.nav.primary')) ?>">
            <ul class="site-nav__list">
                <?php foreach (nav_items() as $item): ?>
                    <li>
                        <a class="site-nav__link<?= $item['page'] === current_page() ? ' is-current' : '' ?>"
                           href="<?= e($item['href']) ?>"
                            <?= $item['page'] === current_page() ? ' aria-current="page"' : '' ?>>
                            <?= e($item['label']) ?>
                        </a>
                    </li>
                <?php endforeach; ?>
            </ul>

            <div class="site-nav__actions">
                <?= language_selector() ?>
                <?php if ($repository !== null): ?>
                    <a class="btn btn--secondary btn--sm" href="<?= e($repository) ?>" rel="noopener noreferrer" target="_blank">
                        <?= icon('github') ?><span><?= t('common.github') ?></span>
                    </a>
                <?php endif; ?>
                <a class="btn btn--primary btn--sm" href="<?= e(url('download.php')) ?>"
                    <?= current_page() === 'download.php' ? ' aria-current="page"' : '' ?>>
                    <?= icon('download') ?><span><?= t('common.nav.download') ?></span>
                </a>
            </div>
        </nav>
    </div>
</header>

<main id="main">
    <?php
}

/** Closes the document and prints the footer. */
function page_end(): void
{
    $name = (string) config('app_name');
    $repository = repository_url();
    ?>
</main>

<footer class="site-footer">
    <div class="shell site-footer__inner">
        <div class="site-footer__brand">
            <a class="brand" href="<?= e(url('index.php')) ?>">
                <?= logo_mark('brand__mark') ?>
                <span class="brand__text gradient-text"><?= e($name) ?></span>
            </a>
            <p class="site-footer__tagline"><?= t('common.tagline') ?></p>
            <p class="site-footer__note"><?= t('common.footer.selfHosted') ?></p>
        </div>

        <nav class="site-footer__links" aria-label="<?= e(t('common.footer.linksLabel')) ?>">
            <div>
                <h2 class="site-footer__heading"><?= t('common.footer.project') ?></h2>
                <ul>
                    <li><a href="<?= e(url('index.php')) ?>#features"><?= t('common.nav.features') ?></a></li>
                    <li><a href="<?= e(url('index.php')) ?>#screenshots"><?= t('common.nav.screenshots') ?></a></li>
                    <li><a href="<?= e(url('download.php')) ?>"><?= t('common.nav.download') ?></a></li>
                </ul>
            </div>
            <div>
                <h2 class="site-footer__heading"><?= t('common.footer.docs') ?></h2>
                <ul>
                    <li><a href="<?= e(url('documentation.php')) ?>#requirements"><?= t('docs.nav.requirements') ?></a></li>
                    <li><a href="<?= e(url('documentation.php')) ?>#install"><?= t('docs.nav.install') ?></a></li>
                    <li><a href="<?= e(url('documentation.php')) ?>#services"><?= t('docs.nav.services') ?></a></li>
                    <li><a href="<?= e(url('documentation.php')) ?>#troubleshooting"><?= t('docs.nav.troubleshooting') ?></a></li>
                </ul>
            </div>
            <div>
                <h2 class="site-footer__heading"><?= t('common.footer.builtOn') ?></h2>
                <ul>
                    <li><a href="https://musicbrainz.org" rel="noopener noreferrer" target="_blank">MusicBrainz</a></li>
                    <li><a href="https://jellyfin.org" rel="noopener noreferrer" target="_blank">Jellyfin</a></li>
                    <li><a href="https://github.com/slskd/slskd" rel="noopener noreferrer" target="_blank">slskd</a></li>
                    <li><a href="https://prowlarr.com" rel="noopener noreferrer" target="_blank">Prowlarr</a></li>
                    <li><a href="https://www.qbittorrent.org" rel="noopener noreferrer" target="_blank">qBittorrent</a></li>
                </ul>
            </div>
        </nav>
    </div>

    <div class="shell site-footer__bottom">
        <p><?= t('common.footer.version', ['version' => e((string) config('app_version'))]) ?></p>
        <div class="site-footer__bottom-links">
            <?php if (docker_hub_url() !== null): ?>
                <a href="<?= e(docker_hub_url()) ?>" rel="noopener noreferrer" target="_blank">
                    <?= icon('docker') ?><span><?= t('common.dockerHub') ?></span>
                </a>
            <?php endif; ?>
            <?php if ($repository !== null): ?>
                <a href="<?= e($repository) ?>" rel="noopener noreferrer" target="_blank">
                    <?= icon('github') ?><span><?= t('common.github') ?></span>
                </a>
            <?php endif; ?>
        </div>
        <?php if ($repository === null && docker_hub_url() === null): ?>
            <p class="site-footer__soon"><?= t('common.footer.repoSoon') ?></p>
        <?php endif; ?>
    </div>
</footer>

<script src="<?= e(asset('assets/js/site.js')) ?>" defer></script>
</body>
</html>
    <?php
}

/**
 * The language selector, which stays out of the way entirely while the site
 * speaks a single language.
 */
function language_selector(): string
{
    if (!is_multilingual()) {
        return '';
    }

    $current = current_language();
    $html = '<form class="lang-select" method="get" action="' . e(current_page_path()) . '">'
        . '<label class="lang-select__label" for="lang-select">' . icon('globe')
        . '<span class="sr-only">' . t('common.language') . '</span></label>'
        . '<select class="lang-select__input" id="lang-select" name="lang" data-lang-select>';
    foreach (languages() as $code => $language) {
        $html .= '<option value="' . e($code) . '"' . ($code === $current ? ' selected' : '') . '>'
            . e($language['label']) . '</option>';
    }
    $html .= '</select><noscript><button class="btn btn--secondary btn--sm" type="submit">'
        . t('common.apply') . '</button></noscript></form>';

    return $html;
}

/** A code sample with its language label and a copy button. */
function code_block(string $body, string $language = 'text'): string
{
    $idle = t('docs.copy');
    $done = t('docs.copied');

    return '<div class="code-block">'
        . '<div class="code-block__bar">'
        . '<span class="code-block__lang">' . icon('terminal') . e($language) . '</span>'
        . '<button class="code-block__copy" type="button" data-copy'
        . ' data-label-idle="' . e($idle) . '" data-label-done="' . e($done) . '">'
        . icon('copy') . '<span>' . e($idle) . '</span></button>'
        . '</div>'
        . '<pre><code>' . e($body) . '</code></pre>'
        . '</div>';
}

/** Section heading shared by the landing sections. */
function section_heading(string $eyebrow, string $title, string $lead = ''): string
{
    $html = '<header class="section-heading">'
        . '<p class="eyebrow">' . $eyebrow . '</p>'
        . '<h2 class="section-heading__title">' . $title . '</h2>';
    if ($lead !== '') {
        $html .= '<p class="section-heading__lead">' . $lead . '</p>';
    }
    return $html . '</header>';
}
