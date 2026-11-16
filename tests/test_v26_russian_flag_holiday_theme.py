from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def read(path): return (ROOT / path).read_text(encoding='utf-8')
def test_bridge_uses_css_energy_visual_without_any_3d_model():
    bridge = read('frontend/templates/dashboard/overview.html')
    app = read('frontend/templates/student/student_app.html')
    assert 'hero-energy-core' in bridge
    assert 'student-aurora-cloud' in app
    assert '.glb' not in bridge + app
    assert 'data-immersive-model' not in bridge + app

def test_russian_holiday_palette_and_motion_in_student_app_bundle():
    css = read('static/css/student-app.bundle.css')
    for season in ('russia_day', 'flag_day', 'unity_day', 'constitution_day'):
        assert season in css
    assert '#3978ed' in css and '#e83e58' in css and 'rf-flag-ribbon' in css

def test_website_holiday_theme_and_reduced_motion():
    css = read('static/css/site.bundle.css')
    assert 'rf-site-stripe' in css
    assert 'prefers-reduced-motion:reduce' in css
