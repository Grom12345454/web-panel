"""Regression checks for direction cards and Administration navigation.

These isolated checks do not require Flask or configured messenger tokens.
"""
import ast
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]


def groups():
    tree = ast.parse((ROOT / 'backend/app/services/science_routes.py').read_text(encoding='utf8'))
    target = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                  and node.name == 'group_readings_by_science_direction')
    scope = {}
    exec(compile(ast.Module(body=[target], type_ignores=[]), 'science_groups', 'exec'), scope)
    return scope['group_readings_by_science_direction']


def row(number, names):
    return SimpleNamespace(id=number, title=f'Чтение {number}', science_directions=names,
                           description='Описание', held_at=datetime.utcnow() + timedelta(days=20),
                           deadline=None, is_open=True)


def env():
    result = Environment(loader=FileSystemLoader(str(ROOT / 'frontend/templates')), autoescape=True)
    result.globals.update(url_for=lambda endpoint, **kw: '/' + endpoint.replace('.', '/') +
                          ('/' + str(kw['reading_id']) if 'reading_id' in kw else ''),
                          csrf_token=lambda: 'test-token', asset_version=lambda _: 'test',
                          get_flashed_messages=lambda **_: [],
                          session={'user_id': 1, 'user_role': 'super_admin', 'user_login': 'admin'},
                          request=SimpleNamespace(endpoint='science.index'))
    return result


def test_one_science_direction_per_card_and_no_duplicate_reading_ids():
    g = groups()([row(10, ['Физика', 'Информатика']), row(20, ['физика', 'Математика']),
                  row(30, ['Математика', 'Математика'])])
    assert [group['name'] for group in g] == ['Информатика', 'Математика', 'Физика']
    assert [[r.id for r in group['readings']] for group in g] == [[10], [20, 30], [10, 20]]


def test_public_catalogue_displays_exactly_one_heading_per_direction():
    readings = [row(1, ['История', 'Химия']), row(2, ['Химия'])]
    direction_cards = groups()(readings)
    html = env().get_template('science/public.html').render(readings=readings,
               direction_cards=direction_cards, science_directions=[g['name'] for g in direction_cards])
    assert html.count('class="card direction-card"') == 2
    assert html.count('class="direction-heading"') == 2
    assert html.count('data-reading-id="1"') == 2  # one reading belongs to two groups
    assert html.count('data-reading-id="2"') == 1
    assert 'Направления: История · Химия' not in html


def test_admin_science_displays_one_card_per_group():
    readings = [row(1, ['История', 'Химия']), row(2, ['Химия'])]
    html = env().get_template('science/index.html').render(readings=readings,
               direction_cards=groups()(readings), submissions=[],
               science_directions=['История', 'Химия'], may_create=False,
               can_manage=lambda _: False)
    assert html.count('science-reading-card science-direction-card') == 2
    assert html.count('<h3>История</h3>') == 1
    assert html.count('<h3>Химия</h3>') == 1


def test_staff_link_is_nested_in_admin_section_not_loose_sidebar_item():
    src = (ROOT / 'frontend/templates/shared/base.html').read_text('utf8')
    admin_group = src.index('id="nav-section-system"')
    staff_link = src.index("url_for('staff.accounts')")
    nav_end = src.index('class="sidebar-nav-end"')
    assert admin_group < staff_link < nav_end
    assert src.count("url_for('staff.accounts')") == 1
    assert "ep == 'staff.accounts'" in src
    assert src.rfind("{% if session.user_role == 'super_admin' %}", 0, admin_group) < staff_link


def test_student_app_uses_grouped_directions_and_preserves_reading_ids():
    src = (ROOT / 'frontend/assets/scripts/student/student_app.js').read_text('utf8')
    assert 'const groups=new Map()' in src
    assert 'seen.has(key)' in src
    assert 'student-science-direction-card' in src
    assert 'name="reading_id" value="${Number(r.id)}"' in src
    assert '.join(\' · \')' not in src[src.index('async function loadScience()'):src.index('async function scienceApply(')]
