"""Only a chief administrator may assign event-specific messenger chats."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB_SOURCE = (ROOT / "backend/app/web_app.py").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "frontend/templates/events/form.html").read_text(encoding="utf-8")
TREE = ast.parse(WEB_SOURCE)
CREATE_QUOTA = next(
    node for node in TREE.body
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "create_quota"
)
CREATE_SOURCE = ast.get_source_segment(WEB_SOURCE, CREATE_QUOTA)


def test_event_chat_options_are_only_loaded_for_super_admin():
    assert 'can_assign_event_chats = current_user.role == UserRole.SUPER_ADMIN.value' in CREATE_SOURCE
    assert '_event_chat_picker_options() if can_assign_event_chats else []' in CREATE_SOURCE


def test_non_admin_submitted_chat_ids_are_ignored_server_side():
    assert 'if can_assign_event_chats:' in CREATE_SOURCE
    assert "request.form.getlist('event_chat_targets')" in CREATE_SOURCE
    assert 'else:\n        selected_targets = []' in CREATE_SOURCE
    assert 'Ignored forged event_chat_targets submitted by non-super-admin' in CREATE_SOURCE
    assert 'set_quota_chat_targets(q.id, selected_targets)' in CREATE_SOURCE


def test_template_hides_picker_from_other_roles_and_explains_owner():
    assert '{% if can_assign_event_chats %}' in TEMPLATE
    assert 'Только главный администратор назначает чаты мероприятия.' in TEMPLATE
    assert 'Назначение чатов мероприятия' in TEMPLATE
