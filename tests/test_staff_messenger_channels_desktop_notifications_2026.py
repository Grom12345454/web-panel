"""Static regression checks for channel ACLs and the desktop messenger PWA."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_channel_acl_is_separate_from_group_membership_and_read_access():
    model = read("backend/app/database/system.py")
    service = read("backend/app/services/staff_messenger.py")
    assert "class StaffChatChannelPermission" in model
    assert "uq_staff_chat_channel_permission" in model
    assert 'kind == "channel"' in service
    assert "def _channel_can_post" in service
    assert "def _can_write_conversation" in service
    assert "writer_ids.issubset(set(participant_ids))" in service
    assert "can_post=target.id in writer_ids" in service
    assert "current_user.role != UserRole.SUPER_ADMIN.value" in service


def test_main_channel_and_global_observer_visibility_are_preserved():
    service = read("backend/app/services/staff_messenger.py")
    assert 'conversation_key="staff-general"' in service
    assert 'conversation.kind == "general"' in service
    assert "UserRole.SUPER_ADMIN.value, UserRole.OBSERVER.value" in service
    assert 'conversation.kind == "general":' in service
    assert 'global_users = User.query.filter(User.is_active.is_(True), User.role.in_(CHAT_ROLES)).all()' in service


def test_native_desktop_notifications_use_electron_bridge_without_web_push():
    service = read("backend/app/services/staff_messenger.py")
    script = read("static/js/staff-messenger.js")
    template = read("frontend/templates/messenger/staff_messenger.html")
    assert "def notification_feed" in service
    assert "desktopBridge.showNotification" in script
    assert "desktopBridge.enableNotifications" in script
    assert "/staff-messenger/api/notifications?after=" in script
    assert "data-enable-notifications" in template
    assert "navigator.serviceWorker.register" not in script
    assert "Notification.requestPermission" not in script

def test_staff_route_allowlist_contains_all_desktop_and_notification_routes():
    source = read("backend/app/web_app.py")
    for endpoint in (
        "staff_messenger.notification_feed", "staff_messenger.create_conversation",
        "staff_messenger.poll_messages", "staff_messenger.send_message",
    ):
        assert endpoint in source


def test_notification_subscriptions_are_account_bound_and_not_publicly_readable():
    model = read("backend/app/database/system.py")
    service = read("backend/app/services/staff_messenger.py")
    block = model.split("class StaffChatPushSubscription", 1)[1].split("\nclass ", 1)[0]
    assert "user_id = db.Column(db.Integer, nullable=False, index=True)" in block
    assert "endpoint = db.Column(db.Text, nullable=False, unique=True)" in block
    assert "@login_required" in service.split("def save_push_subscription", 1)[0][-160:]
    assert 'endpoint.startswith("https://")' in service


def test_channel_readers_are_allowed_to_view_but_not_to_post():
    import ast
    from types import SimpleNamespace

    source = read("backend/app/services/staff_messenger.py")
    tree = ast.parse(source)
    wanted = {"_channel_can_post", "_can_write_conversation", "_conversation_access"}
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    permissions = {}

    class Abort403(Exception):
        pass

    class PermissionQuery:
        def filter_by(self, **kwargs):
            return SimpleNamespace(first=lambda: permissions.get((kwargs["conversation_id"], kwargs["user_id"])))

    def check_account(user, write=False):
        if not getattr(user, "is_active", True) or user.role not in {"staff", "super_admin", "observer"}:
            raise Abort403()
        if write and user.role == "observer":
            raise Abort403()

    participant_ids = set()
    def get_participant(conversation_id, user_id):
        return SimpleNamespace() if (conversation_id, user_id) in participant_ids else None

    namespace = {
        "UserRole": SimpleNamespace(SUPER_ADMIN=SimpleNamespace(value="super_admin"),
                                     OBSERVER=SimpleNamespace(value="observer")),
        "StaffChatChannelPermission": SimpleNamespace(query=PermissionQuery()),
        "_check_account": check_account,
        "_get_participant": get_participant,
        "Abort403": Abort403,
    }
    exec(compile(ast.Module(body=functions, type_ignores=[]), "staff_messenger_acl.py", "exec"), namespace)

    channel = SimpleNamespace(id=44, kind="channel", is_archived=False)
    reader = SimpleNamespace(id=7, role="staff", is_active=True)
    writer = SimpleNamespace(id=8, role="staff", is_active=True)
    participant_ids.update({(44, 7), (44, 8)})
    permissions[(44, 7)] = SimpleNamespace(can_post=False)
    permissions[(44, 8)] = SimpleNamespace(can_post=True)

    assert namespace["_conversation_access"](reader, channel) is True
    assert namespace["_conversation_access"](reader, channel, write=True) is False
    assert namespace["_conversation_access"](writer, channel, write=True) is True
    non_member = SimpleNamespace(id=9, role="staff", is_active=True)
    assert namespace["_conversation_access"](non_member, channel) is False
    admin = SimpleNamespace(id=1, role="super_admin", is_active=True)
    assert namespace["_conversation_access"](admin, channel, write=True) is True
    observer = SimpleNamespace(id=2, role="observer", is_active=True)
    assert namespace["_conversation_access"](observer, channel) is True
    try:
        namespace["_conversation_access"](observer, channel, write=True)
    except Abort403:
        pass
    else:
        raise AssertionError("observer must remain read-only")


def test_all_direction_employees_can_create_channels_and_assign_writers():
    service = read("backend/app/services/staff_messenger.py")
    template = read("frontend/templates/messenger/staff_messenger.html")
    assert "can_manage_channels" in service
    assert 'getattr(current_user, "staff_rank", "employee")' in service
    assert 'can_create_channel=(current_user.role == UserRole.SUPER_ADMIN.value or' in service
    assert 'if kind == "channel" and not can_manage_channels:' in service
    assert 'name="channel_writers"' in template
    assert "writer_ids.issubset(set(participant_ids))" in service
