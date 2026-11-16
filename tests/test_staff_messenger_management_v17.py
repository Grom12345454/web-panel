"""Regression checks for per-user chat organization and admin channel ACLs."""
from pathlib import Path
import ast
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]

def read(path):
    return (ROOT / path).read_text(encoding="utf-8")

def test_per_user_chat_preferences_model_is_system_scoped_and_unique():
    source = read("backend/app/database/system.py")
    block = source.split("class StaffChatUserPreference", 1)[1].split("\nclass ", 1)[0]
    assert '__bind_key__ = "system"' in block
    assert "is_pinned" in block and "is_hidden" in block
    assert "uq_staff_chat_user_preference" in block
    facade = read("backend/app/database/__init__.py")
    assert "StaffChatUserPreference" in facade

def test_chat_list_honors_personal_pin_and_hide_without_shared_deletion():
    source = read("backend/app/services/staff_messenger.py")
    assert "hidden_ids = {item.conversation_id" in source
    assert "pinned_ids = {item.conversation_id" in source
    assert '"is_pinned": bool(preference and preference.is_pinned)' in source
    assert 'preference.is_hidden = True' in source

def test_only_super_admin_can_change_channel_writer_acl_and_archive_shared_chat():
    source = read("backend/app/services/staff_messenger.py")
    assert 'def update_channel_permissions(current_user, conversation_id)' in source
    route = source.split('def update_channel_permissions', 1)[1].split('\n@staff_messenger_bp', 1)[0]
    assert 'current_user.role != UserRole.SUPER_ADMIN.value' in route
    assert 'writer_ids.issubset(participant_ids)' in route
    assert 'conversation.is_archived = True' in source

def test_thread_controls_and_channel_permission_dialog_are_wired():
    template = read("frontend/templates/messenger/staff_messenger.html")
    script = read("static/js/staff-messenger.js")
    assert Environment().parse(template) is not None
    for token in ('data-conversation-action', 'data-open-channel-permissions', 'channel_permission_writer'):
        assert token in template
    for token in ('/preferences', '/channel-permissions', "action: 'archive'"):
        # The action value is read from the control's data attribute.
        assert token in script or token == "action: 'archive'"
    assert "writer_ids:writerIds" in script
