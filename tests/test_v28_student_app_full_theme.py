from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding='utf-8')


def test_student_app_theme_spectrum_is_last_in_built_cascade():
    build = read('scripts/build_assets.py')
    assert "'student/student-app-theme-spectrum-2026.css'" in build
    bundle = read('static/css/student-app.bundle.css')
    assert 'Student App theme system v28' in bundle
    assert bundle.rfind('Student App theme system v28') > bundle.rfind('===== BEGIN frontend/assets/styles/student/ship-student-2026.css =====')


def test_student_app_theme_updates_full_interface_and_honors_tricolor_holidays():
    css = read('frontend/assets/styles/student/student-app-theme-spectrum-2026.css')
    assert '.command-hero' in css
    assert '.command-metric' in css
    assert '.student-announcement' in css
    assert '.nav button.active' in css
    assert 'data-season="constitution_day"' in css
    assert 'data-season="flag_day"' in css
    assert 'sa-russian-ribbon' in css
    assert 'prefers-reduced-motion:reduce' in css


def test_student_app_live_sync_updates_vars_even_when_theme_key_stays_same():
    js = read('frontend/assets/scripts/student/student_app.js')
    assert "api('/student-app/api/sync-state')" in js
    assert "document.body.dataset.theme=signal.season" in js
    assert 'document.body.style.getPropertyValue(`--${name}`).trim()!==value.trim()' in js
    assert 'const STUDENT_SYNC_INTERVAL=30000' in js
    assert 'scheduleStudentSync(0)' in js
    assert 'document.visibilityState===\'hidden\'' in js
    assert 'window.setInterval(syncStudentApp, 8000)' not in js


def test_built_student_app_bundle_contains_same_theme_sync_and_visual_layer():
    js = read('static/js/student-app.bundle.js')
    css = read('static/css/student-app.bundle.css')
    assert 'visualThemeChanged' in js
    assert 'Student App theme system v28' in css
