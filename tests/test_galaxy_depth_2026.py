"""Regression checks: strong 3D is on by default with no visible switch."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def source(path):
    return (ROOT / path).read_text('utf-8')


def test_no_motion_button_in_staff_or_student_html():
    for template in ('frontend/templates/shared/base.html', 'frontend/templates/student/student_app.html'):
        html = source(template)
        assert 'data-pro-mode-toggle' not in html
        assert '3D-эффекты' not in html
    for bundle in ('static/js/site.bundle.js', 'static/js/student-app.bundle.js'):
        assert 'student-council:pro-motion' not in source(bundle)
        assert 'data-pro-mode-toggle' not in source(bundle)


def test_visual_layers_built_in_both_apps_and_mobile_accessible():
    css = source('frontend/assets/styles/shared/galaxy-depth-2026.css')
    site = source('static/css/site.bundle.css')
    student = source('static/css/student-app.bundle.css')
    for selector in ('.mission-hero-20', '.mission-kpi', '.command-hero', '.command-world', '.command-metric'):
        assert selector in css
    assert css in site and css in student
    assert '@media(prefers-reduced-motion:reduce)' in css
    assert '@media(max-width:760px)' in css
    assert 'data-pro-mode-toggle' not in source('frontend/assets/scripts/portal/pro-workspace.js')


def test_javascript_syntax_and_single_telegram_router_dispatcher():
    for script in ('static/js/site.bundle.js', 'static/js/student-app.bundle.js'):
        subprocess.run(['node', '--check', str(ROOT / script)], check=True, capture_output=True)
    bot = source('backend/app/bot.py')
    assert 'def get_dispatcher():' in bot
    assert 'if _dispatcher is not None:' in bot
    assert 'dp = get_dispatcher()' in bot
    assert 'await bot.session.close()' in bot
    assert 'raise\n    finally:' in bot
