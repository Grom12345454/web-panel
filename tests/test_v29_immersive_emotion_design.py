from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding='utf-8')


def test_shared_immersive_design_is_last_layer_for_site_and_student_app():
    build = read('scripts/build_assets.py')
    assert build.count("'shared/immersive-emotion-v29.css'") == 2
    site = read('static/css/site.bundle.css')
    student = read('static/css/student-app.bundle.css')
    assert site.rfind('V29 — Aurora / deep-space design language') > site.rfind('===== BEGIN frontend/assets/styles/portal/orders-archive.css =====')
    assert student.rfind('V29 — Aurora / deep-space design language') > student.rfind('Student App theme system v28')


def test_design_depth_and_theme_palette_are_shared_across_both_surfaces():
    css = read('frontend/assets/styles/shared/immersive-emotion-v29.css')
    assert 'body.uc-body[data-theme]' in css
    assert 'body.student-app-body[data-season]' in css
    assert '--v29-accent' in css
    assert '.cosmos-field__nebula' in css
    assert '.command-hero' in css
    assert '.sidebar' in css
    assert '.mission-bottom-nav' in css
    assert 'v29-theme-resonance' in css
    assert 'data-theme="constitution_day"' in css
    assert 'data-season="constitution_day"' in css


def test_visual_motion_is_accessible_and_mobile_avoids_hover_lifts():
    css = read('frontend/assets/styles/shared/immersive-emotion-v29.css')
    assert '@media (prefers-reduced-motion:reduce)' in css
    assert '@media (hover:hover) and (pointer:fine)' in css
    assert '@media (max-width:760px), (pointer:coarse)' in css
    assert 'transform: none;' in css
