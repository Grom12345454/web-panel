from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding='utf-8')


def test_theme_palette_is_visible_without_separate_theme_labels():
    base = read('frontend/templates/shared/base.html')
    student = read('frontend/templates/student/student_app.html')
    css = read('frontend/assets/styles/shared/holiday-visual-v40.css')
    assert 'active-theme-indicator' not in base
    assert 'active_visual_theme_config.label' not in base
    assert 'student-active-theme' not in student
    assert 'student_app_theme.label' not in student
    css_bundle = read('static/css/site.bundle.css')
    student_bundle = read('static/css/student-app.bundle.css')
    assert '.active-theme-indicator' not in css_bundle
    assert '.student-active-theme' not in student_bundle
    assert 'body.uc-body[data-theme]' in css
    assert 'body.student-app-body[data-season]' in css


def test_student_app_has_no_ship_model_or_floating_holiday_stickers():
    student = read('frontend/templates/student/student_app.html')
    base = read('frontend/templates/shared/base.html')
    css = read('frontend/assets/styles/student/holiday-motion-2026.css')
    assert 'immersive-3d-canvas' not in student
    assert 'campus-ship.glb' not in student
    assert 'student-orbit-scene' in student  # CSS-only atmosphere, no model canvas
    assert 'student-festive-glyph' not in student
    assert 'student-festival-badge' not in css
    assert 'festive-spark--' not in base


def test_pointer_following_script_is_not_bundled():
    build = read('scripts/build_assets.py')
    site_js = read('static/js/site.bundle.js')
    student_js = read('static/js/student-app.bundle.js')
    css = read('frontend/assets/styles/shared/holiday-visual-v40.css')
    assert 'shared/kinetic-cinema-v31.js' not in build
    assert "document.addEventListener('pointermove'" not in site_js
    assert "document.addEventListener('pointermove'" not in student_js
    assert '.v31-light-halo, .v31-light-halo--active { display: none !important; }' in css
