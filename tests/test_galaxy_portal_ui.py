"""Static regression checks independent of optional Flask runtime packages."""
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]


def test_student_app_has_single_cabinet_and_account_area():
    js = (ROOT / 'frontend/assets/scripts/student/student_app.js').read_text(encoding='utf-8')
    assert "['home','Мой кабинет']" in js
    assert "['profile','Профиль']" not in js
    assert "['accounts','Аккаунты']" not in js
    assert 'id="my-profile"' in js
    assert 'id="my-connected-accounts"' in js
    assert 'accountSettings(true)' in js
    assert 'missionHighlights()' in js
    assert 'data-action="account-review"' in js
    assert 'data-action="account-generate"' in js


def test_galaxy_portal_role_scoped_admin_controls():
    html = (ROOT / 'frontend/templates/dashboard/overview.html').read_text(encoding='utf-8')
    dashboard = (ROOT / 'frontend/templates/dashboard/overview.html').read_text(encoding='utf-8')
    hero = (ROOT / 'frontend/templates/dashboard/_dashboard_hero.html').read_text(encoding='utf-8')
    backend = (ROOT / 'backend/app/web_app.py').read_text(encoding='utf-8')
    assert 'dashboard_show_analytics' in dashboard
    assert 'dashboard_show_directions' in dashboard
    assert 'galaxy-students' not in html
    assert 'galaxy-hero' in hero
    assert 'hero-energy-orbit' in hero
    assert 'admin.leadership_public' in backend


def test_registry_has_mobile_labels_and_working_actions():
    html = (ROOT / 'frontend/templates/students/list.html').read_text(encoding='utf-8')
    for label in ('Студент','Группа','Телефон','Руководитель','Направления','Посещения','Отказы','Статус','Действия'):
        assert f'data-label="{label}"' in html
    assert "url_for('admin.edit_student', sid=student.id)" in html
    assert "url_for('admin.delete_student', sid=student.id)" in html
    assert 'name="csrf_token"' in html


def test_new_layers_bundled_and_templates_parse():
    build = (ROOT / 'scripts/build_assets.py').read_text(encoding='utf-8')
    assert 'galaxy-student-final.css' in build
    assert 'galaxy-portal-experience.css' in build
    for path in ROOT.glob('frontend/templates/**/*.html'):
        Environment(loader=FileSystemLoader(ROOT / 'frontend/templates')).parse(path.read_text(encoding='utf-8'))
