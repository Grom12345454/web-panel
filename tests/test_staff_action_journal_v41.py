"""v41 regressions: employee-only audit journal, bots stay in their own area."""
from pathlib import Path
import ast
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]


def test_staff_journal_query_filters_out_student_and_bot_rows():
    src = (ROOT / "backend/app/web_app.py").read_text("utf-8")
    tree = ast.parse(src)
    base = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_staff_audit_base_query")
    text = ast.get_source_segment(src, base)
    assert "HttpAuditLog.actor_user_id.isnot(None)" in text
    assert "HttpAuditLog.actor_role.in_(STAFF_AUDIT_ROLES)" in text
    assert "StudentActivity" not in text and "BotJournalEvent" not in text


def test_registered_staff_activity_filters_and_exports_share_the_same_query():
    src = (ROOT / "backend/app/web_app.py").read_text("utf-8")
    assert "query, filters = _registered_user_activity_query(request.args)" in src
    assert "query.order_by(HttpAuditLog.created_at.desc(), HttpAuditLog.id.desc())" in src
    assert "HttpAuditLog.method.in_(('POST', 'PUT', 'PATCH', 'DELETE'))" in src
    assert "HttpAuditLog.status_code >= 400" in src
    assert "HttpAuditLog.duration_ms >= 1500" in src


def test_staff_mutations_failures_and_slow_requests_are_logged_without_get_noise():
    src = (ROOT / "backend/app/web_app.py").read_text("utf-8")
    assert "is_staff_write_request" in src
    assert 'request.method in {"POST", "PUT", "PATCH", "DELETE"}' in src
    assert 'or status_code >= 400 or elapsed_ms >= 1500' in src
    assert 'should_persist' in src
    assert 'or is_staff_action_request' not in src
    assert '"/api/visual-theme"' in src and '"/notifications/api/unread"' in src
    assert '"/audit-log/check"' in src


def test_staff_log_template_has_only_registered_web_accounts():
    audit = (ROOT / "frontend/templates/activity/user_activity.html").read_text("utf-8")
    assert "Действия сотрудников" in audit or "Журнал действий сотрудников" in audit
    assert 'name="role"' in audit and 'name="actor"' in audit
    assert 'name="method"' in audit and 'name="level"' in audit
    assert "StudentActivity" not in audit
    assert "BotJournalEvent" not in audit


def test_super_admin_navigation_hides_monitoring_but_templates_still_compile():
    base = (ROOT / "frontend/templates/shared/base.html").read_text("utf-8")
    assert "nav-monitoring-group" not in base
    assert "url_for('admin.user_activity_log')" not in base
    assert "url_for('admin.messenger_monitoring')" not in base
    env = Environment(loader=FileSystemLoader(ROOT / "frontend/templates"))
    for path in (ROOT / "frontend/templates").rglob("*.html"):
        env.get_template(path.relative_to(ROOT / "frontend/templates").as_posix())
