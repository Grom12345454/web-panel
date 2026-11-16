from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding='utf-8')


def test_adaptive_performance_budget_is_loaded_before_visual_motion_layers():
    build = read('scripts/build_assets.py')
    js = read('frontend/assets/scripts/shared/performance-budget-2026.js')
    css = read('frontend/assets/styles/shared/performance-budget-2026.css')
    assert build.count("'shared/performance-budget-2026.js'") == 2
    assert build.count("'shared/performance-budget-2026.css'") == 2
    for bundle in ('SITE_JS', 'STUDENT_JS'):
        start = build.index(f'{bundle} = [')
        end = build.index(']', start)
        manifest = build[start:end]
        assert 'shared/immersive-3d-2026.js' not in manifest
    assert 'navigator.hardwareConcurrency' in js
    assert 'navigator.deviceMemory' in js
    assert 'connection.saveData' in js
    assert 'prefers-reduced-motion' in js
    assert 'perf-page-hidden' in css
    assert 'perf-economy' in css


def test_student_sync_is_throttled_and_suspended_when_hidden():
    js = read('frontend/assets/scripts/student/student_app.js')
    assert 'const STUDENT_SYNC_INTERVAL=5000' in js
    assert 'function scheduleStudentSync' in js
    assert "document.visibilityState==='hidden'" in js
    assert 'window.setInterval(syncStudentApp, 8000)' not in js


def test_website_theme_polling_is_throttled_and_suspended_when_hidden():
    js = read('frontend/assets/scripts/portal/theme-live-sync.js')
    assert 'const POLL_INTERVAL = 30000' in js
    assert 'function schedulePoll' in js
    assert "document.visibilityState === 'hidden'" in js
    assert 'window.setInterval(poll, 8000)' not in js


def test_no_webgl_renderer_remains_in_either_bundle():
    build = read('scripts/build_assets.py')
    assert 'immersive-3d-2026.js' not in build
    assert not (ROOT / 'frontend/assets/scripts/shared/immersive-3d-2026.js').exists()
    for bundle in ('static/js/site.bundle.js', 'static/js/student-app.bundle.js'):
        assert 'data-immersive-model' not in read(bundle)


def test_low_power_css_reduces_blur_without_removing_smoke_colours():
    css = read('frontend/assets/styles/shared/performance-budget-2026.css')
    assert 'body.perf-economy .holiday-smoke' in css
    assert 'mix-blend-mode: normal' in css
    assert 'body.perf-touch .holiday-smoke' in css
    assert 'backdrop-filter: none !important' in css
