"""Regressions for event/lesson synchronization and protected diagnostics."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from datetime import date
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]


def _pure_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_normalized_calendar_contains_both_and_is_chronological():
    m = _pure_module('test_student_calendar_pure', 'backend/app/services/student_calendar.py')
    output = m.combine_calendar_items(
        [{'id': 6, 'title': 'Занятие', 'date': '25.10.2026', 'time': '09:30',
          'end_time': '11:00', 'direction_name': 'Медиа', 'room': '104'}],
        [{'id': 8, 'title': 'Фестиваль', 'time': '16:00', 'location': 'Зал',
          'days': [{'id': 12, 'date': '2026-10-25', 'registered': True}]}]
    )
    assert [item['kind'] for item in output] == ['lesson', 'event']
    assert output[0]['date'] == '2026-10-25'
    assert output[1]['event_id'] == 8
    assert output[1]['registered'] is True
    assert len(m.combine_calendar_items([], [])) == 0


def test_role_labels_replace_boolean_in_student_roster():
    source = (ROOT/'frontend/templates/students/list.html').read_text()
    assert '{{ role }}' in source and 'leadership-position-badge' in source
    assert 'badge-approved">Да' not in source
    # Independently execute just the pure helper, without database dependencies.
    import ast
    import types
    module=ast.parse((ROOT/'backend/app/services/student_roles.py').read_text())
    function=next(x for x in module.body if isinstance(x,ast.FunctionDef))
    scope={'role_label':lambda title:title,
           'role_scope':lambda title,education=None:None}
    exec(compile(ast.Module(body=[function],type_ignores=[]), '<roles>', 'exec'),scope)
    rows=[SimpleNamespace(student_id=3,position_name='Глава направления',education_type='institute',
            direction=SimpleNamespace(name='Медиа'))]
    assert scope['student_leadership_labels'](rows)[3] == ['Глава направления · Медиа']


def test_bot_journal_includes_delivery_attempts_and_token_status():
    template = (ROOT/'frontend/templates/activity/bot_journal.html').read_text()
    for expected in ('delivery_items','delivery_platform','delivery_status','job.attempts',
                     'job.source_type','job.last_error','delivery_counts.blocked'):
        assert expected in template
    model=(ROOT/'backend/app/database/system.py').read_text()
    assert 'last_attempt_at' in model and 'source_type' in model
    worker=(ROOT/'backend/app/services/delivery_outbox.py').read_text()
    assert "'blocked'" in worker and 'calendar_delivery' in worker


def test_removed_visible_brand_and_manual_effects_toggle():
    base=(ROOT/'frontend/templates/shared/base.html').read_text()
    student=(ROOT/'frontend/assets/scripts/student/student_app.js').read_text()
    for item in ('GALAXY CONTROL', 'data-toggle-galaxy-effects','Институт космонавтики'):
        assert item not in base
    for item in ('data-action="toggle-effects"','galaxy-reduce-effects','Уменьшить эффекты'):
        assert item not in student
    assert 'shared/orbital-experience-v3.css' in (ROOT/'scripts/build_assets.py').read_text()


def test_calendar_backend_fetches_whole_day_and_delivers_common_feed():
    web=(ROOT / 'backend/app/web_app.py').read_text()
    assert 'datetime.combine(datetime.now().date(), datetime.min.time())' in web
    assert '"calendar": calendar_items' in web
    assert "source_type='event', source_id=quota.id" in web
    assert "source_type='lesson', source_id=lesson.id" in web
    assert "BotDeliveryJob.status == 'blocked'" in (ROOT/'backend/app/services/delivery_outbox.py').read_text()


def test_all_templates_parse():
    env=Environment(loader=FileSystemLoader(str(ROOT / 'frontend/templates')))
    for file in (ROOT / 'frontend/templates').rglob('*.html'):
        env.get_template(file.relative_to(ROOT / 'frontend/templates').as_posix())
