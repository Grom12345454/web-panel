from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding='utf-8')


def test_dashboard_hero_has_balanced_visual_container_before_dashboard_sections():
    html = read('frontend/templates/dashboard/overview.html')
    assert '</svg>\n    </div>\n  </section>\n\n  <section class="galaxy-stats' in html
    assert '</svg>\n    </div>\n    </div>\n  </section>' not in html


def test_constitution_day_is_a_selectable_theme_with_full_app_tokens():
    app = read('backend/app/web_app.py')
    template = read('frontend/templates/system/student_app_design.html')
    assert '"constitution_day": {"label": "День Конституции России"' in app
    assert '"constitution_day": {"season-accent"' in app
    assert 'themes.items()' in template
    assert 'theme.group == group_id' in template


def test_initial_and_live_website_theme_use_both_theme_attributes():
    base = read('frontend/templates/shared/base.html')
    sync = read('frontend/assets/scripts/portal/theme-live-sync.js')
    assert 'data-theme="{{ active_visual_theme' in base
    assert 'data-season="{{ active_visual_theme' in base
    assert 'body.dataset.theme = data.theme' in sync
    assert 'body.dataset.season = data.theme' in sync
    assert 'const POLL_INTERVAL = 5000' in sync
    assert 'schedulePoll(0)' in sync
    assert 'window.setInterval(poll, 8000)' not in sync
    assert 'schedulePoll(0);' in sync
    assert 'function schedulePoll' in sync


def test_constitution_day_has_distinct_motion_and_palette_for_both_clients():
    motion = read('frontend/assets/styles/shared/theme-change-motion-2026.css')
    spectrum = read('frontend/assets/styles/shared/theme-spectrum-v23.css')
    student_css = read('frontend/assets/styles/student/student_app.css')
    site_bundle = read('static/css/site.bundle.css')
    student_bundle = read('static/css/student-app.bundle.css')
    assert 'data-season="constitution_day"' in motion
    assert 'data-theme="constitution_day"' in spectrum
    assert 'data-season="constitution_day"' in student_css
    assert 'constitution_day' in site_bundle and 'constitution_day' in student_bundle
    assert 'rf-site-stripe' in site_bundle and 'rf-flag-ribbon' in student_bundle
