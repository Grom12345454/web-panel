"""Regression checks for the contained dashboard and Student App welcome heroes.
These are static checks; visual sizing is also verified separately in Chromium.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source(path):
    return (ROOT / path).read_text(encoding='utf-8')


def test_hero_layout_override_is_last_in_both_bundles():
    build = source('scripts/build_assets.py')
    source_name = 'shared/hero-smooth-performance-2026.css'
    assert build.count(source_name) == 2
    for bundle in ('static/css/site.bundle.css', 'static/css/student-app.bundle.css'):
        text = source(bundle)
        assert text.count('BEGIN frontend/assets/styles/' + source_name) == 1
        assert text.rfind('BEGIN frontend/assets/styles/' + source_name) > text.rfind('BEGIN frontend/assets/styles/shared/cosmos-world-2026.css')


def test_both_heroes_keep_art_in_separate_grid_column():
    css = source('frontend/assets/styles/shared/hero-smooth-performance-2026.css')
    for selector in ('.mission-hero-20', '.command-hero', '.galaxy-hero-visual', '.command-world'):
        assert selector in css
    assert 'grid-template-columns:' in css
    assert 'position:relative !important;inset:auto !important' in css
    assert 'max-width:700px' in css
    assert 'prefers-reduced-motion:reduce' in css


def test_card_motion_no_longer_tracks_pointer():
    for name in (
        'frontend/assets/scripts/shared/cosmos-world-2026.js',
        'frontend/assets/scripts/portal/pro-workspace.js',
        'frontend/assets/scripts/student/pro-student-experience.js',
    ):
        js = source(name)
        assert "addEventListener('pointermove'" not in js
        assert 'getBoundingClientRect(' not in js
        assert 'requestAnimationFrame(' not in js
    assert "addEventListener('pointermove'" not in source('frontend/assets/scripts/portal/app.js')


def test_starfield_is_render_rate_limited():
    js = source('frontend/assets/scripts/portal/space.js')
    assert 'const frameInterval = economyMode ? 88 : 55' in js
    assert 'now - lastDrawAt < frameInterval' in js
    assert "addEventListener('pointermove'" not in js
    assert 'if (document.hidden) stop()' in js


def test_student_navigation_and_buttons_unchanged():
    js = source('frontend/assets/scripts/student/student_app.js')
    html = source('frontend/templates/dashboard/overview.html')
    assert 'Мои заявления' in js
    assert 'Привязанные аккаунты' in js
    assert 'Студенты и заявки' in html
    assert 'Открыть календарь' in html
