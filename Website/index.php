<?php
/**
 * The showcase page: title and logo, a short presentation, every feature
 * grouped by category, then the screenshot slideshow.
 */

declare(strict_types=1);

require __DIR__ . '/includes/bootstrap.php';

$categories = tl('home.features.categories');
$shots = screenshots();

page_start(['class' => 'page-home']);
?>

<section class="hero">
    <div class="shell hero__inner">
        <p class="eyebrow"><?= t('home.hero.eyebrow') ?></p>

        <div class="hero__mark">
            <?= logo_mark() ?>
        </div>

        <h1 class="hero__title gradient-text"><?= e((string) config('app_name')) ?></h1>
        <p class="hero__tagline"><?= t('common.tagline') ?></p>
        <p class="hero__lead"><?= t('home.hero.lead') ?></p>

        <div class="hero__actions">
            <a class="btn btn--primary btn--lg" href="<?= e(url('documentation.php')) ?>">
                <?= icon('book') ?><span><?= t('home.hero.ctaDocs') ?></span>
            </a>
            <a class="btn btn--secondary btn--lg" href="<?= e(url('download.php')) ?>">
                <?= icon('download') ?><span><?= t('home.hero.ctaDownload') ?></span>
            </a>
        </div>

        <ul class="hero__badges">
            <?php foreach (tl('home.hero.badges') as $badge): ?>
                <li class="chip"><?= icon('check') ?><?= $badge ?></li>
            <?php endforeach; ?>
        </ul>
    </div>
</section>

<section class="section section--tight" id="about">
    <div class="shell">
        <div class="intro__grid reveal">
            <div class="intro__text">
                <?= section_heading(t('home.intro.eyebrow'), t('home.intro.title')) ?>
                <div class="prose">
                    <?php foreach (tl('home.intro.paragraphs') as $paragraph): ?>
                        <p><?= $paragraph ?></p>
                    <?php endforeach; ?>
                </div>
            </div>

            <ul class="intro__highlights">
                <?php foreach (tl('home.intro.highlights') as $highlight): ?>
                    <li class="intro__card glass">
                        <span class="icon-badge"><?= icon($highlight['icon']) ?></span>
                        <div>
                            <h3><?= $highlight['title'] ?></h3>
                            <p><?= $highlight['text'] ?></p>
                        </div>
                    </li>
                <?php endforeach; ?>
            </ul>
        </div>
    </div>
</section>

<section class="section" id="features">
    <div class="shell">
        <?= section_heading(
            t('home.features.eyebrow'),
            t('home.features.title'),
            t('home.features.lead')
        ) ?>

        <div class="features">
            <?php foreach ($categories as $position => $category): ?>
                <?php
                $hasGroups = isset($category['groups']);
                $items = $category['items'] ?? [];
                // A long flat list reads better in two columns on a wide screen.
                $split = !$hasGroups && count($items) > 6;
                ?>
                <article class="feature glass reveal" id="feature-<?= e($category['id']) ?>">
                    <header class="feature__head">
                        <span class="icon-badge icon-badge--lg"><?= icon($category['icon']) ?></span>
                        <p class="feature__index"><?= sprintf('%02d', $position + 1) ?></p>
                        <h3 class="feature__title"><?= $category['title'] ?></h3>
                        <p class="feature__lead"><?= $category['lead'] ?></p>
                    </header>

                    <div class="feature__body<?= $split ? ' feature__body--split' : '' ?>">
                        <?php if ($hasGroups): ?>
                            <div class="feature__groups">
                                <?php foreach ($category['groups'] as $group): ?>
                                    <section>
                                        <h4 class="feature__group-title"><?= $group['title'] ?></h4>
                                        <ul class="tick-list">
                                            <?php foreach ($group['items'] as $item): ?>
                                                <li><?= icon('check') ?><span><?= $item ?></span></li>
                                            <?php endforeach; ?>
                                        </ul>
                                    </section>
                                <?php endforeach; ?>
                            </div>
                        <?php else: ?>
                            <ul class="tick-list">
                                <?php foreach ($items as $item): ?>
                                    <li><?= icon('check') ?><span><?= $item ?></span></li>
                                <?php endforeach; ?>
                            </ul>
                        <?php endif; ?>
                    </div>
                </article>
            <?php endforeach; ?>
        </div>
    </div>
</section>

<section class="section shots-section" id="screenshots">
    <div class="shell">
        <?= section_heading(
            t('home.shots.eyebrow'),
            t('home.shots.title'),
            t('home.shots.lead')
        ) ?>

        <?php if ($shots === []): ?>
            <div class="shots__empty reveal">
                <span class="icon-badge icon-badge--lg"><?= icon('image') ?></span>
                <h3><?= t('home.shots.emptyTitle') ?></h3>
                <p><?= t('home.shots.emptyHint', ['folder' => e(screenshots_hint_folder())]) ?></p>
            </div>
        <?php else: ?>
            <div class="shots reveal" data-slideshow data-interval="6000" tabindex="-1">
                <div class="shots__frame">
                    <div class="shots__stage" data-stage>
                        <?php foreach ($shots as $position => $shot): ?>
                            <figure class="shots__slide<?= $position === 0 ? ' is-active' : '' ?>"
                                    data-slide
                                    data-slide-caption="<?= e($shot['caption']) ?>"
                                    aria-hidden="<?= $position === 0 ? 'false' : 'true' ?>">
                                <img src="<?= e($shot['src']) ?>"
                                     alt="<?= e($shot['caption']) ?>"
                                     <?= $shot['width'] !== null ? 'width="' . $shot['width'] . '"' : '' ?>
                                     <?= $shot['height'] !== null ? 'height="' . $shot['height'] . '"' : '' ?>
                                     loading="<?= $position === 0 ? 'eager' : 'lazy' ?>"
                                     decoding="async">
                            </figure>
                        <?php endforeach; ?>
                    </div>

                    <?php if (count($shots) > 1): ?>
                        <button class="shots__arrow shots__arrow--prev" type="button" data-prev
                                aria-label="<?= e(t('home.shots.prev')) ?>">
                            <?= icon('chevron-left') ?>
                        </button>
                        <button class="shots__arrow shots__arrow--next" type="button" data-next
                                aria-label="<?= e(t('home.shots.next')) ?>">
                            <?= icon('chevron-right') ?>
                        </button>
                    <?php endif; ?>

                    <figcaption class="shots__caption">
                        <span data-caption-text><?= e($shots[0]['caption']) ?></span>
                        <?php if (count($shots) > 1): ?>
                            <span class="shots__counter" data-counter
                                  data-template="<?= e(t('home.shots.counter')) ?>">
                                <?= t('home.shots.counter', ['current' => 1, 'total' => count($shots)]) ?>
                            </span>
                        <?php endif; ?>
                    </figcaption>
                </div>

                <?php if (count($shots) > 1): ?>
                    <div class="shots__controls">
                        <div class="shots__dots" role="tablist" aria-label="<?= e(t('home.shots.eyebrow')) ?>">
                            <?php foreach ($shots as $position => $shot): ?>
                                <button class="shots__dot<?= $position === 0 ? ' is-active' : '' ?>"
                                        type="button" role="tab" data-dot
                                        aria-selected="<?= $position === 0 ? 'true' : 'false' ?>"
                                        tabindex="<?= $position === 0 ? '0' : '-1' ?>"
                                        aria-label="<?= e(t('home.shots.goTo', ['index' => $position + 1])) ?>"></button>
                            <?php endforeach; ?>
                        </div>
                        <button class="shots__toggle" type="button" data-toggle data-playing="false"
                                aria-label="<?= e(t('home.shots.toggle')) ?>"
                                title="<?= e(t('home.shots.toggle')) ?>">
                            <span class="shots__toggle-pause"><?= icon('pause') ?></span>
                            <span class="shots__toggle-play"><?= icon('play') ?></span>
                        </button>
                    </div>
                <?php endif; ?>
            </div>
        <?php endif; ?>
    </div>
</section>

<section class="section">
    <div class="shell">
        <div class="cta glass reveal">
            <h2><?= t('home.cta.title') ?></h2>
            <p><?= t('home.cta.lead') ?></p>
            <div class="cta__actions">
                <a class="btn btn--primary btn--lg" href="<?= e(url('documentation.php')) ?>">
                    <?= icon('book') ?><span><?= t('home.cta.docs') ?></span>
                </a>
                <a class="btn btn--secondary btn--lg" href="<?= e(url('download.php')) ?>">
                    <?= icon('download') ?><span><?= t('home.cta.download') ?></span>
                </a>
            </div>
        </div>
    </div>
</section>

<?php page_end(); ?>
