/**
 * Site behaviour: navigation, reveals, copy buttons, the screenshot slideshow
 * and the documentation table of contents. No dependencies, and every piece
 * degrades to something usable when scripting is off.
 */

(function () {
    'use strict';

    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    /* ------------------------------------------------------------- header */

    const header = document.getElementById('site-header');
    if (header) {
        const updateHeader = () => {
            header.classList.toggle('is-stuck', window.scrollY > 8);
        };
        updateHeader();
        window.addEventListener('scroll', updateHeader, { passive: true });
    }

    const navToggle = document.querySelector('[data-nav-toggle]');
    const nav = document.getElementById('site-nav');
    if (navToggle && nav) {
        navToggle.addEventListener('click', () => {
            const open = navToggle.getAttribute('aria-expanded') === 'true';
            navToggle.setAttribute('aria-expanded', String(!open));
            nav.classList.toggle('is-open', !open);
        });

        // Following a link inside the panel should close it.
        nav.addEventListener('click', (event) => {
            if (event.target.closest('a')) {
                navToggle.setAttribute('aria-expanded', 'false');
                nav.classList.remove('is-open');
            }
        });
    }

    const langSelect = document.querySelector('[data-lang-select]');
    if (langSelect) {
        langSelect.addEventListener('change', () => {
            langSelect.form.submit();
        });
    }

    /* ------------------------------------------------------------ reveals */

    const revealables = document.querySelectorAll('.reveal');
    if (revealables.length > 0) {
        if (reducedMotion || !('IntersectionObserver' in window)) {
            revealables.forEach((node) => node.classList.add('is-visible'));
        } else {
            const observer = new IntersectionObserver(
                (entries) => {
                    entries.forEach((entry) => {
                        if (entry.isIntersecting) {
                            entry.target.classList.add('is-visible');
                            observer.unobserve(entry.target);
                        }
                    });
                },
                { rootMargin: '0px 0px -10% 0px', threshold: 0.08 },
            );
            revealables.forEach((node) => observer.observe(node));
        }
    }

    /* ------------------------------------------------------- copy buttons */

    document.querySelectorAll('[data-copy]').forEach((button) => {
        const block = button.closest('.code-block');
        const source = block && block.querySelector('code');
        if (!source) {
            return;
        }

        const idleLabel = button.dataset.labelIdle || 'Copy';
        const doneLabel = button.dataset.labelDone || 'Copied';
        const text = button.querySelector('span');
        let timer = null;

        button.addEventListener('click', async () => {
            try {
                await navigator.clipboard.writeText(source.innerText);
            } catch (error) {
                // Clipboard access can be refused outside a secure context; a
                // selection is still better than nothing.
                const range = document.createRange();
                range.selectNodeContents(source);
                const selection = window.getSelection();
                selection.removeAllRanges();
                selection.addRange(range);
                return;
            }

            button.classList.add('is-done');
            if (text) {
                text.textContent = doneLabel;
            }
            clearTimeout(timer);
            timer = window.setTimeout(() => {
                button.classList.remove('is-done');
                if (text) {
                    text.textContent = idleLabel;
                }
            }, 1800);
        });
    });

    /* ---------------------------------------------------------- slideshow */

    document.querySelectorAll('[data-slideshow]').forEach((root) => {
        const slides = Array.from(root.querySelectorAll('[data-slide]'));
        if (slides.length === 0) {
            return;
        }

        const dots = Array.from(root.querySelectorAll('[data-dot]'));
        const caption = root.querySelector('[data-caption-text]');
        const counter = root.querySelector('[data-counter]');
        const toggle = root.querySelector('[data-toggle]');
        const counterTemplate = counter ? counter.dataset.template || '{current} / {total}' : null;
        const delay = Number(root.dataset.interval || 6000);

        let index = slides.findIndex((slide) => slide.classList.contains('is-active'));
        if (index < 0) {
            index = 0;
        }
        let timer = null;
        let playing = false;

        const show = (next) => {
            index = (next + slides.length) % slides.length;
            slides.forEach((slide, position) => {
                const active = position === index;
                slide.classList.toggle('is-active', active);
                slide.setAttribute('aria-hidden', String(!active));
            });
            dots.forEach((dot, position) => {
                const active = position === index;
                dot.classList.toggle('is-active', active);
                dot.setAttribute('aria-selected', String(active));
                dot.tabIndex = active ? 0 : -1;
            });
            if (caption) {
                caption.textContent = slides[index].dataset.slideCaption || '';
            }
            if (counter && counterTemplate) {
                counter.textContent = counterTemplate
                    .replace('{current}', String(index + 1))
                    .replace('{total}', String(slides.length));
            }
        };

        const stop = () => {
            playing = false;
            clearInterval(timer);
            timer = null;
            if (toggle) {
                toggle.dataset.playing = 'false';
            }
        };

        const start = () => {
            if (slides.length < 2 || reducedMotion) {
                return;
            }
            clearInterval(timer);
            playing = true;
            timer = window.setInterval(() => show(index + 1), delay);
            if (toggle) {
                toggle.dataset.playing = 'true';
            }
        };

        root.querySelectorAll('[data-prev]').forEach((button) =>
            button.addEventListener('click', () => {
                show(index - 1);
                stop();
            }),
        );
        root.querySelectorAll('[data-next]').forEach((button) =>
            button.addEventListener('click', () => {
                show(index + 1);
                stop();
            }),
        );
        dots.forEach((dot, position) =>
            dot.addEventListener('click', () => {
                show(position);
                stop();
            }),
        );

        if (toggle) {
            toggle.addEventListener('click', () => (playing ? stop() : start()));
        }

        // Arrow keys work once the slideshow has focus, not before, so they do
        // not steal the page scroll.
        root.addEventListener('keydown', (event) => {
            if (event.key === 'ArrowLeft') {
                event.preventDefault();
                show(index - 1);
                stop();
            } else if (event.key === 'ArrowRight') {
                event.preventDefault();
                show(index + 1);
                stop();
            }
        });

        // Autoplay pauses while the visitor is looking closely, and while the
        // tab is in the background.
        root.addEventListener('mouseenter', () => playing && stop());
        root.addEventListener('focusin', () => playing && stop());
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                stop();
            }
        });

        // Swipe, tracked on the stage only.
        const stage = root.querySelector('[data-stage]') || root;
        let startX = null;
        stage.addEventListener(
            'touchstart',
            (event) => {
                startX = event.touches[0].clientX;
            },
            { passive: true },
        );
        stage.addEventListener(
            'touchend',
            (event) => {
                if (startX === null) {
                    return;
                }
                const travelled = event.changedTouches[0].clientX - startX;
                if (Math.abs(travelled) > 45) {
                    show(travelled < 0 ? index + 1 : index - 1);
                    stop();
                }
                startX = null;
            },
            { passive: true },
        );

        show(index);

        // Only start once the slideshow is actually on screen.
        if ('IntersectionObserver' in window) {
            const visibility = new IntersectionObserver(
                (entries) => {
                    entries.forEach((entry) => {
                        if (entry.isIntersecting) {
                            start();
                        } else {
                            stop();
                        }
                    });
                },
                { threshold: 0.35 },
            );
            visibility.observe(root);
        } else {
            start();
        }
    });

    /* --------------------------------------------- documentation contents */

    const tocLinks = Array.from(document.querySelectorAll('[data-toc-link]'));
    if (tocLinks.length > 0 && 'IntersectionObserver' in window) {
        const sections = tocLinks
            .map((link) => document.querySelector(link.getAttribute('href')))
            .filter(Boolean);

        const highlight = (id) => {
            tocLinks.forEach((link) => {
                link.classList.toggle('is-active', link.getAttribute('href') === '#' + id);
            });
        };

        const observer = new IntersectionObserver(
            (entries) => {
                // The topmost visible section wins, which keeps the highlight
                // steady while scrolling through a long one.
                const visible = entries
                    .filter((entry) => entry.isIntersecting)
                    .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
                if (visible.length > 0) {
                    highlight(visible[0].target.id);
                }
            },
            { rootMargin: '-25% 0px -60% 0px', threshold: 0 },
        );
        sections.forEach((section) => observer.observe(section));
    }
})();
