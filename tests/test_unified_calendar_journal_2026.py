"""Regressions for one student calendar and two separately managed journals.

No Flask, bot tokens, or live database is needed for this module.
"""
from datetime import datetime
from pathlib import Path
import ast
import importlib.util
import json
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def load_pure_helper():
    spec = importlib.util.spec_from_file_location('student_calendar_2026', ROOT / 'backend/app/services/student_calendar.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_lessons_and_published_events_in_one_persisted_feed():
    combine = load_pure_helper().combine_calendar_items
    rows = combine(
        [{'id': 11, 'title': 'Практика', 'date': '26.10.2026', 'time': '14:00',
          'direction_id': 2, 'direction_name': 'Медиа'}],
        [{'id': 24, 'title': 'Форум', 'time': '18:00', 'days': [{'id': 9, 'date': '2026-10-26'}]}]
    )
    assert len(rows) == 2
    assert {row['kind'] for row in rows} == {'event', 'lesson'}
    assert all(row['date'] == '2026-10-26' for row in rows)
    assert combine([{'id': 11, 'title': 'Практика', 'date': '26.10.2026'}] * 2, []) == combine([{'id': 11, 'title': 'Практика', 'date': '26.10.2026'}], [])


def test_calendar_does_not_depend_on_chat_delivery_or_publication_jobs():
    web = (ROOT / 'backend/app/web_app.py').read_text('utf-8')
    me = web[web.index('def student_app_me('):web.index('def _local_demo_cookie_serializer')]
    assert 'student_lessons' in me and 'calendar_event_payloads' in me
    assert 'combine_calendar_items(student_lessons, calendar_event_payloads)' in me
    assert 'timedelta(days=62)' in me  # includes dates from the selected/current month
    assert 'BotDeliveryJob' not in me  # chat publishing must not gate lesson visibility
    assert 'calendar_floor' in me and 'quota.is_published' not in me  # quotas are filtered before building calendar


def test_staff_menu_and_deprecated_list_urls_use_one_calendar():
    web = (ROOT / 'backend/app/web_app.py').read_text('utf-8')
    legacy_lesson = web[web.index('def list_lessons('):web.index('@lessons_bp.route("/create"')]
    legacy_quota = web[web.index('def quotas_list('):web.index('@quotas_bp.route("/participants/')] 
    assert 'url_for("admin.calendar"' in legacy_lesson
    assert 'url_for("admin.calendar"' in legacy_quota
    nav = (ROOT / 'frontend/templates/shared/base.html').read_text('utf-8')
    assert '<span>Календарь</span>' in nav
    assert "url_for('admin.calendar')" in nav


def test_student_navigation_and_timeline_unified():
    js = (ROOT / 'frontend/assets/scripts/student/student_app.js').read_text('utf-8')
    header = js[js.index('function shell(){'):js.index('function missionHighlights(){')]
    assert "['calendar','Календарь']" in header
    assert "['events','Мероприятия']" not in header
    assert "case'open-lesson'" in js
    assert 'data-action="download-lesson"' in js
    assert 'data-action="open-event"' in js
    assert "case'calendar-type'" in js
    build = (ROOT / 'scripts/build_assets.py').read_text('utf-8')
    assert 'student/unified-calendar-2026.css' in build
    assert (ROOT / 'frontend/assets/styles/student/unified-calendar-2026.css').read_text('utf-8') in (ROOT / 'static/css/student-app.bundle.css').read_text('utf-8')


def test_journal_clearance_server_permissions_and_confirmation():
    tree = ast.parse((ROOT / 'backend/app/web_app.py').read_text('utf-8'))
    functions = {fn.name:fn for fn in tree.body if isinstance(fn, ast.FunctionDef)}
    for name in ('clear_logs','clear_bot_journal'):
        fn = functions[name]
        assert any(isinstance(dec, ast.Name) and dec.id == 'super_admin_required' for dec in fn.decorator_list)
        source = ast.get_source_segment((ROOT / 'backend/app/web_app.py').read_text('utf-8'), fn)
        assert 'confirmation' in source and 'db.engines["system"].begin()' in source
        assert 'BotDeliveryJob.__table__.delete()' not in source
    all_log_src = ast.get_source_segment((ROOT / 'backend/app/web_app.py').read_text('utf-8'), functions['clear_logs'])
    assert 'StudentActivity.__table__.delete()' in all_log_src
    assert 'HttpAuditLog.__table__.delete()' in all_log_src
    assert 'BotJournalEvent.__table__.delete()' in all_log_src
    assert 'ОЧИСТИТЬ' in all_log_src
    bot_log_src = ast.get_source_segment((ROOT / 'backend/app/web_app.py').read_text('utf-8'), functions['clear_bot_journal'])
    assert 'БОТЫ' in bot_log_src
    assert 'StudentActivity.__table__.delete()' not in bot_log_src
    assert 'HttpAuditLog.__table__.delete()' not in bot_log_src


def test_log_templates_and_navigation_only_superadmin():
    base = (ROOT / 'frontend/templates/shared/base.html').read_text('utf-8')
    assert "session.user_role == 'super_admin'" in base
    # The monitoring menu is intentionally hidden; privileged server-side
    # journal and audit routes remain available to security/diagnostic code.
    assert 'nav-monitoring-group' not in base
    assert "url_for('admin.admin_audit_log')" not in base
    assert "url_for('admin.bot_journal')" not in base
    assert 'Центр событий' not in base
    journal = (ROOT / 'frontend/templates/activity/bot_journal.html').read_text('utf-8')
    audit = (ROOT / 'frontend/templates/activity/user_activity.html').read_text('utf-8')
    system = (ROOT / 'frontend/templates/system/maintenance.html').read_text('utf-8')
    assert "url_for('admin.clear_bot_journal')" in journal
    assert "url_for('admin.clear_logs')" not in system
    assert "Журналы и диагностика" not in system
    assert "Создать резервную копию сейчас" in system
    assert "Автоматическая защита баз данных" in system
    assert 'rows' in audit and 'Журнал действий' in audit
    assert 'ОЧИСТИТЬ' not in system and 'БОТЫ' in journal


def test_calendar_js_shows_both_items_without_other_datasets():
    if not shutil.which('node'):
        return
    source = (ROOT / 'frontend/assets/scripts/student/student_app.js').read_text('utf-8')
    renderer = source[source.index('function studentTimelineItems('):source.index('function saveLessonCalendar(')]
    script = """const esc=x=>String(x||'');
const state={calendar:[
 {kind:'lesson',id:18,date:'2026-10-27',title:'Учебное занятие',time:'09:00'},
 {kind:'event',id:12,event_id:4,date:'2026-10-27',title:'Фестиваль',time:'12:00'}
],lessons:[],events:[]};
const schedulePeriod='month';const calendarCursor=new Date(2026,9,1);
const calendarChosen='2026-10-27';const calendarKind='all';
""" + renderer + "\nconst result=schedule(); if(!result.includes('Учебное занятие')||!result.includes('Фестиваль')||!result.includes('mission-list-feed'))throw new Error('Missing calendar entries');"
    check = subprocess.run(['node', '-e', script], text=True, capture_output=True)
    assert check.returncode == 0, check.stderr


def test_log_clear_hides_old_delivery_receipts_without_losing_pending_jobs():
    web = (ROOT / 'backend/app/web_app.py').read_text('utf-8')
    journal = (ROOT / 'backend/app/services/bot_journal_routes.py').read_text('utf-8')
    assert '_mark_bot_history_cleared(connection)' in web
    assert 'BotDeliveryJob.__table__.delete()' not in web[web.index('def clear_logs('):web.index('@admin_bp.route("/system/clear-statistics"')]
    assert 'bot_delivery_history_visible_since' in journal
    assert "'pending', 'retry', 'sending', 'blocked', 'failed'" in journal
    assert 'BotDeliveryJob.created_at >= cutoff' in journal
