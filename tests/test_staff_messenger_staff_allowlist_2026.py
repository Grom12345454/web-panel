"""Regression coverage for staff messenger endpoint admission."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_staff_allowlist_admits_the_complete_messenger_workspace():
    source = (ROOT / "backend/app/web_app.py").read_text(encoding="utf-8")
    required = {
        "staff_messenger.communications": {"GET", "HEAD", "OPTIONS"},
        "staff_messenger.index": {"GET", "HEAD", "OPTIONS"},
        "staff_messenger.create_conversation": {"POST"},
        "staff_messenger.poll_messages": {"GET", "HEAD", "OPTIONS"},
        "staff_messenger.mark_read": {"POST"},
        "staff_messenger.update_typing": {"POST"},
        "staff_messenger.send_message": {"POST"},
        "staff_messenger.delete_message": {"POST"},
        "staff_messenger.toggle_reaction": {"POST"},
        "staff_messenger.search_messages": {"GET", "HEAD", "OPTIONS"},
        "staff_messenger.download_attachment": {"GET", "HEAD", "OPTIONS"},
    }
    for endpoint, methods in required.items():
        method_literal = "{" + ", ".join(repr(method) for method in sorted(methods)) + "}"
        assert endpoint in source
        assert method_literal in source


def test_staff_messenger_remains_protected_by_route_level_acl():
    source = (ROOT / "backend/app/services/staff_messenger.py").read_text(encoding="utf-8")
    assert "_check_account(current_user, write=True)" in source
    assert "_conversation_access(current_user, conversation, write=True)" in source
    assert "current_user.role == UserRole.SUPER_ADMIN.value" in source
    assert "if write and user.role == UserRole.OBSERVER.value" in source
