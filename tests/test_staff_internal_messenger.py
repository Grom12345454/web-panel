"""Static regression checks for the SQLite-backed in-app staff messenger."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_messenger_models_live_in_system_sqlite_bind_and_have_membership_state():
    source = read("backend/app/database/system.py")
    for model in (
        "StaffChatConversation", "StaffChatParticipant", "StaffChatMessage",
        "StaffChatReaction", "StaffChatAttachment", "StaffChatTyping",
    ):
        block = source.split(f"class {model}", 1)[1].split("\nclass ", 1)[0]
        assert '__bind_key__ = "system"' in block
    assert "last_read_message_id" in source
    assert "reply_to_id" in source
    assert "uq_staff_chat_reaction" in source
    assert "uq_staff_chat_typing" in source


def test_every_messenger_route_requires_login_and_mutations_recheck_membership():
    source = read("backend/app/services/staff_messenger.py")
    tree = ast.parse(source)
    route_names = {
        "index", "create_conversation", "poll_messages", "mark_read", "update_typing",
        "send_message", "toggle_reaction", "search_messages", "download_attachment",
    }
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in route_names:
            decorators = [ast.unparse(item) for item in node.decorator_list]
            found[node.name] = decorators
    assert route_names == set(found)
    assert all(any("login_required" in item for item in decorators) for decorators in found.values())
    assert "_conversation_access(current_user, conversation, write=True)" in source
    assert "_conversation_access(current_user, conversation)" in source
    assert "_check_account(user, write=write)" in source


def test_messenger_supports_required_workflows_and_secure_private_attachments():
    source = read("backend/app/services/staff_messenger.py")
    template = read("frontend/templates/messenger/staff_messenger.html")
    script = read("static/js/staff-messenger.js")
    for token in ("kind == \"general\"", "kind == \"direct\"", "kind == \"group\"",
                  "StaffChatReaction", "StaffChatTyping", "StaffChatAttachment", "reply_to_id",
                  "last_read_message_id", "ilike(", "_attachment_root()"):
        assert token in source
    for token in ("Общая переписка команды", "data-reply-id", "data-reaction", "messenger-attachments",
                  "messenger-search", "messenger-typing", "Прочитано", "Режим наблюдателя"):
        assert token in template
    for token in ("/messages?after=", "/typing", "/reactions", "/staff-messenger/search"):
        assert token in script
    assert "static_folder" not in source
    assert "staff_chat_attachments" in source
    assert "MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024" in source
    allowed_block = source.split("ALLOWED_EXTENSIONS = {", 1)[1].split("}", 1)[0]
    assert ".html" not in allowed_block and ".svg" not in allowed_block


def test_read_only_observer_and_navigation_are_wired_in_shared_site_shell():
    web = read("backend/app/web_app.py")
    base = read("frontend/templates/shared/base.html")
    source = read("backend/app/services/staff_messenger.py")
    assert '"staff_messenger.mark_read"' in web
    assert "app.register_blueprint(staff_messenger_bp)" in web
    assert "user.role == UserRole.OBSERVER.value" in source
    assert "Внутренний чат" not in base
    assert "staff_messenger.index" not in base


def test_existing_report_pages_remain_the_real_site_templates_and_runpy_entrypoint_is_kept():
    report_hub = read("frontend/templates/events/reports.html")
    report_direction = read("frontend/templates/events/direction_report.html")
    report_event = read("frontend/templates/events/event_report.html")
    report_archive = read("frontend/templates/events/report_archive.html")
    web = read("backend/app/web_app.py")
    run = read("run.py")
    for token in ("Создание отчётов", "Открыть HTML", "PDF с подписью", "Архив отчётов"):
        assert token in report_hub
    assert "Полная история действий направления" in report_direction
    assert "Посещаемость участников" in report_event and "Скачать подписанный PDF" in report_event
    assert "Доступные документы" in report_archive
    assert "def event_reports" in web and "def direction_report_html" in web and "def event_report_html" in web
    assert "def main()" in run and "if __name__ == \"__main__\":" in run
    assert "from web_app import create_app, notification_worker" in run
    start_bat = read("start.bat")
    assert "Starting Studsovet through run.py" in start_bat and "python.exe run.py" in start_bat
