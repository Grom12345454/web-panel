from pathlib import Path
import ast
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding='utf-8')


def test_monitoring_has_staff_platform_bot_and_registered_student_tabs():
    tabs = read('frontend/templates/activity/_admin_monitor_tabs.html')
    for text in ('Сотрудники', 'Сводка по ботам'):
        assert text in tabs
    assert "url_for('admin.user_activity_log')" in tabs
    assert "url_for('admin.messenger_monitoring')" in tabs
    assert "url_for('admin.bot_journal')" not in tabs
    assert "url_for('admin.bot_activity')" not in tabs


def test_bot_journal_uses_a_filterable_data_table_not_event_cards():
    template = read('frontend/templates/activity/bot_journal.html')
    assert 'bot-monitor-table' in template
    for col in ('Когда (UTC)', 'Платформа', 'Что произошло', 'Тип события', 'Аккаунт', 'Результат'):
        assert col in template
    assert 'journal-event"' not in template
    assert 'data-journal-check' in template


def test_bot_activity_is_scoped_to_registered_student_ids_without_cross_bind_join():
    source = read('backend/app/web_app.py')
    tree = ast.parse(source)
    funcs = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for name in ('bot_activity', 'bot_activity_live_summary', 'bot_activity_live', '_render_bot_activity_table', 'dashboard'):
        assert name in funcs
    for name in ('bot_activity', 'bot_activity_live_summary', 'bot_activity_live', '_render_bot_activity_table'):
        body = ast.get_source_segment(source, funcs[name])
        assert 'council_registered.is_(True)' in body
        assert 'StudentActivity.student_id.in_(registered_student_ids)' in body or name in ('bot_activity', 'bot_activity_live_summary')
    assert "StudentActivity.action.like(r'bot\\_%'" in ast.get_source_segment(source, funcs['dashboard'])
    assert 'StudentActivity.query.join(Student' not in source


def test_registered_only_dashboard_metrics_and_refined_masthead_are_present():
    dashboard = read('frontend/templates/dashboard/overview.html')
    css = read('frontend/assets/styles/staff/admin-monitoring-v65.css')
    assert 'Активность зарегистрированных студентов в ботах' in dashboard
    assert 'Новых зарегистрированных профилей' in dashboard
    assert 'mission-hero-20 .galaxy-hero-visual.galaxy-energy-scene' in css
    assert 'bottom: -28px' in css
    assert 'repeat(4, minmax(0, 1fr))' in css


def test_v65_css_is_in_site_bundle_manifest_and_all_templates_parse():
    manifest = read('scripts/build_assets.py')
    assert "'staff/admin-monitoring-v65.css'" in manifest
    env = Environment()
    for path in (ROOT / 'frontend/templates').rglob('*.html'):
        env.parse(path.read_text(encoding='utf-8'))
