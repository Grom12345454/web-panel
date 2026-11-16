"""Only the chief administrator binds chats; employees can only send messages."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = (ROOT / 'backend/app/web_app.py').read_text(encoding='utf-8')
DETAIL = (ROOT / 'frontend/templates/directions/detail.html').read_text(encoding='utf-8')
TREE = ast.parse(WEB)


def function(name):
    return next(node for node in TREE.body
                if isinstance(node, ast.FunctionDef) and node.name == name)


def test_only_superadmin_can_manage_or_bind_direction_chats():
    helper = ast.get_source_segment(WEB, function('_can_manage_direction_chats'))
    assert 'UserRole.SUPER_ADMIN.value' in helper
    assert 'UserRole.STAFF.value' not in helper
    assert 'staff_allowed' not in helper

    require = ast.get_source_segment(WEB, function('_require_direction_chat_management'))
    assert '_can_manage_direction_chats(user)' in require
    assert 'abort(403)' in require


def test_staff_chat_binding_routes_are_denied_before_route_handlers():
    guard = ast.get_source_segment(WEB, function('_employee_direction_scope_guard'))
    for endpoint in (
        'directions.connect_chat_candidate', 'directions.connect_social_chat',
        'directions.remove_social_chat', 'directions.add_chat',
        'directions.chat_audience', 'directions.delete_chat', 'directions.test_chat',
    ):
        assert endpoint in guard
    assert 'if endpoint in staff_chat_configuration_endpoints:' in guard
    assert 'abort(403)' in guard
    # Sending is a different action and remains grant-controlled.
    assert "'directions.chat_message': 'chats'" in guard


def test_employees_only_see_send_composer_not_discovered_or_bound_chat_ids():
    direction_detail = ast.get_source_segment(WEB, function('direction_detail'))
    assert 'can_view_direction_chats = current_user.role in {' in direction_detail
    assert 'UserRole.STAFF.value' not in direction_detail.split('can_view_direction_chats =', 1)[1].split('# All roles', 1)[0]
    assert "current_user.role == UserRole.STAFF.value and staff_allowed(current_user, did, 'chats', 'manage')" in direction_detail

    # Chat configuration and discovered candidates are guarded by the
    # superadmin-only flag. Staff still get the sender when granted chat access.
    assert '{% if can_view_direction_chats or can_manage_direction_chats %}' in DETAIL
    assert '{% if can_send_direction_chat %}' in DETAIL
    assert 'Обнаруженные Telegram-чаты' in DETAIL
    assert "url_for('directions.connect_chat_candidate'" in DETAIL
    assert "url_for('directions.add_chat'" in DETAIL


def test_every_chat_configuration_route_uses_the_superadmin_only_guard():
    for name in ('connect_chat_candidate', 'connect_social_chat', 'remove_social_chat',
                 'add_chat', 'chat_audience', 'delete_chat', 'test_chat'):
        source = ast.get_source_segment(WEB, function(name))
        assert '_require_direction_chat_management(current_user, did)' in source, name


def test_staff_message_route_only_targets_preassigned_chats_for_its_direction():
    source = ast.get_source_segment(WEB, function('chat_message'))
    assert "staff_allowed(current_user, did, 'chats', 'manage')" in source
    assert 'telegram_targets_for_directions([did])' in source
    assert "MessengerChat.query.filter_by(direction_id=did, is_active=True)" in source
    assert 'request.form.get("chat_id")' not in source
