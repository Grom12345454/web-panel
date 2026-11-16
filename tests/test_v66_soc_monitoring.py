from pathlib import Path
import ast
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]
def read(path): return (ROOT / path).read_text(encoding="utf-8")
def funcs(path):
    source = read(path); tree = ast.parse(source)
    return source, {n.name:n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
def body(path, name):
    source, nodes = funcs(path); return ast.get_source_segment(source, nodes[name])

def test_monitoring_has_only_staff_actions_and_bot_summary_tabs():
    tabs = read("frontend/templates/activity/_admin_monitor_tabs.html")
    assert "Сотрудники" in tabs and "Действия сотрудников" in tabs and "Сводка по ботам" in tabs
    assert "Расследование" not in tabs and "Инциденты" not in tabs
    assert "url_for('admin.user_activity_log')" in tabs
    assert "url_for('admin.messenger_monitoring')" in tabs

def test_employee_view_is_a_plain_action_ledger_without_case_statuses():
    template = read("frontend/templates/activity/user_activity.html")
    for field in ("Когда (UTC)", "Сотрудник / аккаунт", "Что сделал", "Раздел", "Экспорт CSV"):
        assert field in template
    for token in ("Новый", "Расследуется", "Ложное срабатывание", "Очередь инцидентов", "Ответственный аналитик"):
        assert token not in template
    assert "row.path" not in template and "row.request_id" not in template
    assert "Запрос</th>" not in template and "Результат</th>" not in template
    assert "row.subcategory_label" in template

def test_employee_actions_are_only_from_authenticated_web_accounts():
    source, nodes = funcs("backend/app/web_app.py")
    base = ast.get_source_segment(source, nodes["_registered_user_activity_base_query"])
    assert "HttpAuditLog.actor_user_id.isnot(None)" in base
    assert "HttpAuditLog.actor_role.in_(REGISTERED_WEB_ACCOUNT_ROLES)" in base
    assert "~HttpAuditLog.path.like('/student-app%')" in base
    route = body("backend/app/web_app.py", "user_activity_log")
    assert "_registered_user_activity_query(request.args)" in route
    node = funcs("backend/app/web_app.py")[1]["user_activity_log"]
    assert "super_admin_required" in [ast.unparse(d) for d in node.decorator_list]

def test_legacy_audit_log_url_redirects_to_employee_action_ledger():
    route = body("backend/app/web_app.py", "admin_audit_log")
    assert "redirect(url_for('admin.user_activity_log'" in route
    assert "_refresh_staff_incident_cases" not in route

def test_bot_summary_uses_one_grouped_business_action_ledger():
    route = body("backend/app/web_app.py", "messenger_monitoring")
    assert "_collect_registered_bot_activities(request.args)" in route
    assert "bot_events" not in route and "BotJournalEvent" not in route
    assert "_collect_registered_bot_activities(request.args)" in route
    template = read("frontend/templates/system/messenger_monitoring.html")
    for token in ("Операции участников через ботов", "Регистрация", "Заявления", "Квоты и мероприятия", "Отказы и отмены", "activity.events", "event_group_label"):
        assert token in template
    assert "Нажатия кнопок и отдельные входящие сообщения не считаются самостоятельными операциями" in template
    assert "bot_events" not in template and "actor_alias" not in template

def test_legacy_bot_event_export_redirects_to_business_action_export():
    source, nodes = funcs("backend/app/web_app.py")
    node = nodes["messenger_monitoring_bot_events_export"]
    code = ast.get_source_segment(source, node)
    assert "super_admin_required" in [ast.unparse(d) for d in node.decorator_list]
    assert "messenger_monitoring_student_events_export" in code
    assert "bot_q" in code and "bot_platform" in code

def test_bot_business_action_filters_replace_transport_event_filters():
    template = read("frontend/templates/system/messenger_monitoring.html")
    for key in ("q", "event_type", "platform", "start", "end"):
        assert f'name="{key}"' in template
    for key in ("bot_q", "bot_platform", "bot_kind", "bot_status"):
        assert f'name="{key}"' not in template

def test_registered_student_activity_keeps_registered_profile_predicate():
    source, nodes = funcs("backend/app/web_app.py")
    for name in ("_registered_student_id_chunks", "_registered_bot_activity_summary", "_collect_registered_bot_activities"):
        code = ast.get_source_segment(source, nodes[name])
        assert "Student.council_registered.is_(True)" in code or "_registered_student_id_chunks" in code

def test_all_templates_compile():
    env = Environment(loader=FileSystemLoader(str(ROOT / "frontend/templates")))
    for path in (ROOT / "frontend/templates").rglob("*.html"):
        env.get_template(path.relative_to(ROOT / "frontend/templates").as_posix())
