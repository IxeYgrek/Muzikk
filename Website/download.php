<?php
/**
 * Download page: the published Docker image first, then the source repository.
 */

declare(strict_types=1);

require __DIR__ . '/includes/bootstrap.php';

$repository = repository_url();
$hub = docker_hub_url();
$image = docker_image();
$tag = (string) config('app_version');

page_start([
    'title' => t('download.title'),
    'description' => t('download.lead'),
    'class' => 'page-download',
]);
?>

<section class="dl-hero">
    <div class="shell dl-hero__inner">
        <p class="eyebrow"><?= t('download.eyebrow') ?></p>
        <h1><?= t('download.title') ?></h1>
        <p class="lead"><?= t('download.lead') ?></p>
    </div>
</section>

<section class="section section--tight">
    <div class="shell">
        <div class="dl-card glass reveal">
            <span class="dl-card__icon"><?= icon('docker') ?></span>
            <?php if ($hub === null): ?>
                <span class="chip chip--warning"><?= t('download.image.soonBadge') ?></span>
                <h2><?= t('download.image.soonTitle') ?></h2>
                <p><?= t('download.image.soonText') ?></p>
            <?php else: ?>
                <h2><?= t('download.image.readyTitle') ?></h2>
                <p><?= t('download.image.readyText') ?></p>
                <?= code_block('docker pull ' . $image . ':' . $tag, 'bash') ?>
                <div class="dl-card__actions">
                    <a class="btn btn--primary btn--lg" href="<?= e($hub) ?>"
                       rel="noopener noreferrer" target="_blank">
                        <?= icon('docker') ?><span><?= t('download.image.readyButton') ?></span>
                    </a>
                    <a class="btn btn--secondary btn--lg" href="<?= e(url('documentation.php')) ?>#install">
                        <?= icon('book') ?><span><?= t('download.repo.docsButton') ?></span>
                    </a>
                </div>
            <?php endif; ?>
            <div class="dl-card__meta">
                <span><?= t('download.version.label') ?> · <code><?= e($image) ?>:<?= e($tag) ?></code></span>
                <span><?= t('download.version.license') ?></span>
            </div>
        </div>
    </div>
</section>

<section class="section section--tight">
    <div class="shell">
        <div class="dl-card glass reveal">
            <span class="dl-card__icon"><?= icon('github') ?></span>
            <?php if ($repository === null): ?>
                <span class="chip chip--warning"><?= t('download.repo.soonBadge') ?></span>
                <h2><?= t('download.repo.soonTitle') ?></h2>
                <p><?= t('download.repo.soonText') ?></p>
                <div class="dl-card__actions">
                    <span class="btn btn--primary btn--lg" aria-disabled="true" role="link">
                        <?= icon('github') ?><span><?= t('download.repo.soonButton') ?></span>
                    </span>
                </div>
            <?php else: ?>
                <h2><?= t('download.repo.readyTitle') ?></h2>
                <p><?= t('download.repo.readyText') ?></p>
                <?= code_block('git clone ' . $repository . '.git muzikk', 'bash') ?>
                <div class="dl-card__actions">
                    <a class="btn btn--primary btn--lg" href="<?= e($repository) ?>"
                       rel="noopener noreferrer" target="_blank">
                        <?= icon('github') ?><span><?= t('download.repo.readyButton') ?></span>
                    </a>
                </div>
            <?php endif; ?>
        </div>
    </div>
</section>

<section class="section section--tight" id="quickstart">
    <div class="shell">
        <?= section_heading(
            t('common.nav.download'),
            t('download.quickstart.title'),
            t('download.quickstart.lead')
        ) ?>

        <div class="dl-steps">
            <?php foreach (tl('download.quickstart.steps') as $step): ?>
                <article class="dl-step glass reveal">
                    <header class="dl-step__head">
                        <span class="dl-step__number" aria-hidden="true"></span>
                        <h3><?= $step['title'] ?></h3>
                    </header>
                    <p><?= $step['text'] ?></p>
                    <?php if (!empty($step['code'])): ?>
                        <?= code_block($step['code'], 'bash') ?>
                    <?php endif; ?>
                </article>
            <?php endforeach; ?>
        </div>
    </div>
</section>

<section class="section section--tight" id="requirements">
    <div class="shell">
        <?= section_heading(
            t('docs.nav.requirements'),
            t('download.requirements.title'),
            t('download.requirements.lead')
        ) ?>

        <div class="dl-reqs">
            <?php foreach (tl('download.requirements.items') as $item): ?>
                <article class="dl-req glass reveal">
                    <span class="icon-badge"><?= icon($item['icon']) ?></span>
                    <div>
                        <h3><?= $item['name'] ?></h3>
                        <p><?= $item['text'] ?></p>
                        <a class="dl-req__link" href="<?= e($item['url']) ?>"
                           rel="noopener noreferrer" target="_blank">
                            <span><?= e(parse_url($item['url'], PHP_URL_HOST) ?? $item['url']) ?></span>
                            <?= icon('arrow-right') ?>
                        </a>
                    </div>
                </article>
            <?php endforeach; ?>
        </div>
    </div>
</section>

<?php page_end(); ?>
