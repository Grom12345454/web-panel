"""Regressions for task-first admin journal workspace (no live DB required)."""
from pathlib import Path
import ast
from jinja2 import Environment, FileSystemLoader

ROOT=Path(__file__).resolve().parents[1]


def test_staff_and_bot_business_action_screens_are_separate_in_navigation():
    sidebar=(ROOT/'frontend/templates/shared/base.html').read_text('utf-8')
    tabs=(ROOT/'frontend/templates/activity/_admin_monitor_tabs.html').read_text('utf-8')
    assert "url_for('admin.user_activity_log')" in tabs
    assert "url_for('admin.messenger_monitoring')" in tabs
    assert 'Сотрудники' in tabs and 'Сводка по ботам' in tabs
    assert 'Действия сотрудников' in (ROOT/'frontend/templates/activity/user_activity.html').read_text('utf-8')
    assert "url_for('admin.user_activity_log')" in sidebar


def test_staff_journal_is_role_filtered_and_server_side_paginated():
    routes=(ROOT / 'backend/app/web_app.py').read_text('utf-8')
    ast.parse(routes)
    functions = {
        node.name: node for node in ast.parse(routes).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    def function_source(name):
        node = functions[name]
        return "\n".join(routes.splitlines()[node.lineno - 1:node.end_lineno])

    query_block = function_source('_staff_audit_base_query') + function_source('_filtered_audit_queries')
    staff_check = function_source('admin_audit_check')
    legacy_export = function_source('admin_audit_export')
    user_activity = function_source('user_activity_log') + function_source('user_activity_export')
    scoped = query_block + staff_check + legacy_export + user_activity
    assert 'HttpAuditLog.actor_user_id.isnot(None)' in query_block
    assert 'HttpAuditLog.actor_role.in_(STAFF_AUDIT_ROLES)' in query_block
    assert 'HttpAuditLog.actor_role == role' in query_block
    assert 'offset((page - 1) * page_size)' in user_activity
    assert "latest_staff_id = _staff_audit_base_query()" in staff_check
    assert "return redirect(url_for('admin.user_activity_export'" in legacy_export
    assert 'StudentActivity.query' not in scoped
    assert 'BotJournalEvent' not in scoped
    assert "response.headers['Cache-Control'] = 'no-store'" in staff_check
    assert 'HttpAuditLog.__table__.insert().values(**audit_values)' in routes

def test_employee_and_bot_journals_exclude_technical_columns_and_raw_input_events():
    staff=(ROOT/'frontend/templates/activity/user_activity.html').read_text('utf-8')
    bot=(ROOT/'frontend/templates/system/messenger_monitoring.html').read_text('utf-8')
    assert 'Журнал действий сотрудников' in staff
    assert 'Запрос</th>' not in staff and 'Результат</th>' not in staff
    assert 'row.subcategory_label' in staff
    for area in ('Администрирование', 'Аналитика', 'Студенты и участники', 'Работа совета', 'Рабочий стол'):
        assert area in (ROOT/'backend/app/web_app.py').read_text('utf-8')
    assert 'GROUPED BOT BUSINESS ACTIONS' in bot
    assert 'activity.events' in bot
    assert 'Нажатия кнопок и отдельные входящие сообщения не считаются самостоятельными операциями' in bot
    assert 'bot_events' not in bot and 'actor_alias' not in bot
    env=Environment(loader=FileSystemLoader(ROOT / 'frontend/templates'))
    for file in (ROOT / 'frontend/templates').rglob('*.html'):
        env.get_template(file.relative_to(ROOT / 'frontend/templates').as_posix())


def test_ux_live_badge_is_non_disruptive_and_assets_bundled():
    js=(ROOT/'frontend/assets/scripts/portal/journal-ux.js').read_text('utf-8')
    css=(ROOT/'frontend/assets/styles/staff/professional-logs-2026.css').read_text('utf-8')
    bot=(ROOT/'backend/app/services/bot_journal_routes.py').read_text('utf-8')
    builder=(ROOT/'scripts/build_assets.py').read_text('utf-8')
    assert 'window.setInterval(check, 45000)' in js
    assert 'if (document.hidden || inFlight || !checkUrl) return' in js
    assert 'notice.hidden = false' in js
    assert 'window.location.reload()' not in js
    assert "localStorage.setItem(key, compact ? '1' : '0')" in js
    assert 'prefers-reduced-motion:reduce' in css
    assert 'staff/professional-logs-2026.css' in builder
    assert 'focus=focus' in bot and "focus = ('events'" in bot
    assert 'pro-log-workspace' in (ROOT/'static/css/site.bundle.css').read_text('utf-8')
