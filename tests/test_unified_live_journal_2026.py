"""Static regressions for shared journal and Student App live sync."""
from pathlib import Path
import ast
import re

from jinja2 import Environment, FileSystemLoader

ROOT=Path(__file__).resolve().parents[1]


def test_sidebar_has_one_journal_and_no_monitor_link():
    base=(ROOT/'frontend/templates/shared/base.html').read_text('utf-8')
    assert 'Действия сотрудников' in base and "url_for('admin.admin_audit_log')" in base
    assert "url_for('admin.bot_activity')" in base
    assert 'galaxy-sidebar-monitor' not in base
    assert 'Центр событий' not in base
    assert 'Журнал действий</span>' not in base
    assert 'Журнал ботов <small' not in base


def test_tabs_switch_between_legacy_urls_with_admin_auth_intact():
    tabs=(ROOT/'frontend/templates/activity/_journal_tabs.html').read_text('utf-8')
    for endpoint in ("url_for('admin.admin_audit_log')", "url_for('admin.bot_journal')"):
        assert endpoint in tabs
    audit=(ROOT/'frontend/templates/activity/audit_log.html').read_text('utf-8')
    bot_page=(ROOT/'frontend/templates/activity/bot_journal.html').read_text('utf-8')
    assert 'activity/_journal_tabs.html' not in audit
    assert 'activity/_admin_monitor_tabs.html' in bot_page and 'activity/_journal_tabs.html' not in bot_page
    routes=(ROOT / 'backend/app/web_app.py').read_text('utf-8')
    assert '@super_admin_required\ndef admin_audit_log' in routes
    bot=(ROOT/'backend/app/services/bot_journal_routes.py').read_text('utf-8')
    assert '@super_admin_required\n    def bot_journal' in bot
    env=Environment(loader=FileSystemLoader(ROOT / 'frontend/templates'))
    for f in (ROOT / 'frontend/templates').rglob('*.html'):
        env.get_template(f.relative_to(ROOT / 'frontend/templates').as_posix())


def test_more_detailed_audit_filters_and_csv():
    source=(ROOT / 'backend/app/web_app.py').read_text('utf-8')
    ast.parse(source)
    assert "if level == 'slow':" in source
    assert "if method:" in source and 'if actor:' in source
    assert 'HTTP-метод' in source and 'Длительность мс' in source
    assert 'STAFF_AUDIT_ROLES' in source and 'HttpAuditLog.actor_user_id.isnot(None)' in source
    audit=(ROOT/'frontend/templates/activity/audit_log.html').read_text('utf-8')
    for field in ('name="actor"', 'name="method"', 'data-copy-request-id', 'audit-record-number'):
        assert field in audit


def test_live_sync_is_light_and_defers_when_busy():
    server=(ROOT / 'backend/app/web_app.py').read_text('utf-8')
    student=(ROOT/'frontend/assets/scripts/student/student_app.js').read_text('utf-8')
    assert '/student-app/api/sync-state' in server
    assert '_resolve_student_identity()' in server
    assert 'hashlib.sha256' in server
    assert 'STUDENT_SYNC_INTERVAL=5000' in student
    assert "api('/student-app/api/sync-state')" in student
    assert 'signal.revision===studentSyncRevision' in student
    assert 'studentAppDirty' in student and 'eventModalId!==null' in student
    assert 'document.addEventListener(\'visibilitychange\'' in student
    assert 'preserveStudentView()' in student
    bundle=(ROOT/'static/js/student-app.bundle.js').read_text('utf-8')
    assert 'STUDENT_SYNC_INTERVAL=5000' in bundle


def test_bundles_include_ultra_motion_and_reduced_motion():
    for name in ('staff/ultra-console-2026.css','staff/unified-logs-2026.css','student/ultra-student-2026.css'):
        assert name in (ROOT/'scripts/build_assets.py').read_text('utf-8')
    for name in ('site.bundle.css','student-app.bundle.css'):
        contents=(ROOT/'static/css'/name).read_text('utf-8')
        assert 'prefers-reduced-motion:reduce' in contents
