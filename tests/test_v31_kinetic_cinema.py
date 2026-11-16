from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding='utf-8')


def test_kinetic_cinema_is_last_layer_on_site_and_student_app():
    build = read('scripts/build_assets.py')
    assert build.count("'shared/kinetic-cinema-v31.css'") == 2
    assert build.count("'shared/kinetic-cinema-v31.js'") == 2
    for bundle in ('static/css/site.bundle.css', 'static/css/student-app.bundle.css'):
        content = read(bundle)
        assert content.rfind('V31 — Kinetic cinema layer') > content.rfind('V29 — Aurora / deep-space')
        assert content.rfind('V32: render the current dashboard') > content.rfind('V31 — Kinetic cinema layer') if bundle == 'static/css/site.bundle.css' else True
    assert int(read('PROJECT_VERSION').strip().split('.')[0]) >= 31


def test_interactive_depth_is_theme_aware_and_accessible():
    css = read('frontend/assets/styles/shared/kinetic-cinema-v31.css')
    js = read('frontend/assets/scripts/shared/kinetic-cinema-v31.js')
    for needle in ('body.uc-body[data-theme]', 'body.student-app-body[data-season]',
                   '.v31-light-halo', '.v31-depth-hover', 'prefers-reduced-motion: reduce',
                   'pointer: coarse', 'forced-colors: active'):
        assert needle in css
    for needle in ('requestAnimationFrame', 'getBoundingClientRect', 'pointermove',
                   'prefers-reduced-motion: reduce', 'pagehide', 'removeProperty'):
        assert needle in js
    assert 'localStorage' not in js
    assert 'navigator.sendBeacon' not in js


def test_built_javascript_is_valid_and_monitoring_styles_remain_present():
    for script in ('static/js/site.bundle.js', 'static/js/student-app.bundle.js'):
        subprocess.run(['node', '--check', str(ROOT / script)], check=True, capture_output=True)
    site = read('static/css/site.bundle.css')
    assert 'monitoring-layout-v30.css' in site
    assert 'grid-template-columns: repeat(3, minmax(0, 1fr)) !important' in site
