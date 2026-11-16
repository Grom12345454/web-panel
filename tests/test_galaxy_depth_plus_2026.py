"""Static integration checks for the Galaxy Depth Plus theme rollout."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(relative):
    return (ROOT / relative).read_text(encoding='utf-8')


def test_theme_toggle_is_not_present():
    for relative in ('frontend/templates/shared/base.html', 'frontend/templates/student/student_app.html',
                     'static/js/site.bundle.js', 'static/js/student-app.bundle.js'):
        text = read(relative).lower()
        for forbidden in ('3d-эффекты', '3d эффекты', 'data-motion-toggle', 'depth-toggle'):
            assert forbidden not in text, (relative, forbidden)


def test_theme_studio_keeps_theme_cards_without_the_removed_preview_panel():
    html = read('frontend/templates/system/student_app_design.html')
    for selector in ('theme-cover-satellite', 'theme-cover-stars', 'name="season"', 'csrf_token', 'theme-card-content'):
        assert selector in html
    assert 'theme-live-preview' not in html
    assert 'theme-preview-panel' not in html
    assert 'march_8' in read('backend/app/web_app.py')
    assert 'applySelection' in read('frontend/assets/scripts/portal/student-app-theme-designer.js')


def test_styles_in_both_products_and_reduced_motion():
    source = read('frontend/assets/styles/shared/galaxy-depth-plus-2026.css')
    for selector in ('body.uc-body', 'body.student-app-body', '.theme-card',
                     '.theme-preview-panel', '.galaxy-depth-moon', '.command-depth-moon',
                     'prefers-reduced-motion:reduce', 'pointer-events:none'):
        assert selector in source
    for bundle in ('static/css/site.bundle.css', 'static/css/student-app.bundle.css'):
        content = read(bundle)
        assert content.count('BEGIN frontend/assets/styles/shared/galaxy-depth-plus-2026.css') == 1
        assert 'theme-cover-satellite' in content


def test_script_only_wired_on_staff_and_skips_non_designer_pages():
    script = read('frontend/assets/scripts/shared/galaxy-depth-plus.js')
    assert "if (!studio) return;" in script
    assert "prefers-reduced-motion: reduce" in script
    assert 'localStorage' not in script
    assert 'navigator.sendBeacon' not in script
    assert read('static/js/site.bundle.js').count('BEGIN frontend/assets/scripts/shared/galaxy-depth-plus.js') == 1
    assert 'galaxy-depth-plus.js' not in read('static/js/student-app.bundle.js')
