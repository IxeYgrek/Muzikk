<?php
/**
 * Renderer shared by the installation page and the user guide.
 *
 * Both are the same thing structurally: a list of sections, each holding a list
 * of blocks, read from one language namespace. The table of contents and the
 * anchors come from that list, so adding a section is a single array entry.
 */

declare(strict_types=1);

/** One documentation block, whatever its type. */
function doc_block(array $block): string
{
    switch ($block['type']) {
        case 'p':
            return '<p>' . $block['text'] . '</p>';

        case 'h3':
            return '<h3>' . $block['text'] . '</h3>';

        case 'list':
            $ordered = !empty($block['ordered']);
            $html = '<' . ($ordered ? 'ol' : 'ul') . ' class="doc-list'
                . ($ordered ? ' doc-list--ordered' : '') . '">';
            foreach ($block['items'] as $item) {
                $html .= '<li>' . $item . '</li>';
            }
            return $html . '</' . ($ordered ? 'ol' : 'ul') . '>';

        case 'code':
            return code_block($block['body'], $block['lang'] ?? 'text');

        case 'table':
            $html = '<div class="table-wrap"><table class="doc-table"><thead><tr>';
            foreach ($block['head'] as $heading) {
                $html .= '<th scope="col">' . $heading . '</th>';
            }
            $html .= '</tr></thead><tbody>';
            foreach ($block['rows'] as $row) {
                $html .= '<tr>';
                foreach ($row as $cell) {
                    $html .= '<td>' . $cell . '</td>';
                }
                $html .= '</tr>';
            }
            return $html . '</tbody></table></div>';

        case 'note':
            return '<aside class="callout callout--note">' . icon('sparkles')
                . '<div>' . $block['text'] . '</div></aside>';

        case 'warning':
            return '<aside class="callout callout--warning">' . icon('alert')
                . '<div>' . $block['text'] . '</div></aside>';

        case 'faq':
            $html = '<div class="faq">';
            foreach ($block['items'] as $item) {
                $html .= '<details class="faq__item"><summary class="faq__question">'
                    . '<span>' . $item['q'] . '</span>' . icon('chevron-down') . '</summary>'
                    . '<div class="faq__answer">' . $item['a'] . '</div></details>';
            }
            return $html . '</div>';
    }

    return '';
}

/**
 * Renders a whole documentation page from one language namespace, which holds
 * `title`, `lead`, `eyebrow` and `sections`.
 */
function doc_page(string $namespace): void
{
    $sections = tl($namespace . '.sections');

    page_start([
        'title' => t($namespace . '.title'),
        'description' => t($namespace . '.lead'),
        'class' => 'page-docs',
    ]);
    ?>

<section class="doc-hero">
    <div class="shell doc-hero__inner">
        <p class="eyebrow"><?= t($namespace . '.eyebrow') ?></p>
        <h1><?= t($namespace . '.title') ?></h1>
        <p class="lead"><?= t($namespace . '.lead') ?></p>
    </div>
</section>

<div class="shell doc-layout">
    <aside class="doc-toc">
        <nav class="doc-toc__inner glass-soft" aria-label="<?= e(t('docs.tocTitle')) ?>">
            <p class="doc-toc__title"><?= t('docs.tocTitle') ?></p>
            <ul class="doc-toc__list">
                <?php foreach ($sections as $section): ?>
                    <li>
                        <a class="doc-toc__link" data-toc-link href="#<?= e($section['id']) ?>">
                            <?= $section['title'] ?>
                        </a>
                    </li>
                <?php endforeach; ?>
            </ul>
        </nav>
    </aside>

    <div class="doc-body">
        <?php foreach ($sections as $section): ?>
            <section class="doc-section" id="<?= e($section['id']) ?>">
                <h2 class="doc-section__title">
                    <span><?= $section['title'] ?></span>
                    <a class="doc-section__anchor" href="#<?= e($section['id']) ?>"
                       aria-label="<?= e($section['title']) ?>">#</a>
                </h2>
                <?php foreach ($section['blocks'] as $block): ?>
                    <?= doc_block($block) ?>
                <?php endforeach; ?>
            </section>
        <?php endforeach; ?>
    </div>
</div>

    <?php
    page_end();
}
