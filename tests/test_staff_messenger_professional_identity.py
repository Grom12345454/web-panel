"""Regression coverage for Telegram-like professional employee identity in chats."""
from pathlib import Path
import ast
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_message_payload_uses_employee_full_name_and_position():
    source = read("backend/app/services/staff_messenger.py")
    tree = ast.parse(source)
    fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_message_payload")
    code = ast.get_source_segment(source, fn)
    assert '"sender": sender_profile["full_name"]' in code
    assert '"sender_position": sender_profile["position"]' in code
    assert '"sender_initials": sender_profile["initials"]' in code


def test_group_conversation_preview_includes_last_sender_identity():
    source = read("backend/app/services/staff_messenger.py")
    assert "last_sender_profile = _user_profile(last_sender)" in source
    assert '"last_sender": (last_sender_profile or {}).get("full_name", "")' in source
    assert '"last_sender_position": (last_sender_profile or {}).get("position", "")' in source


def test_server_and_live_messages_render_name_and_position_separately():
    template = read("frontend/templates/messenger/staff_messenger.html")
    script = read("static/js/staff-messenger.js")
    assert 'class="messenger-message-author"' in template
    assert 'class="messenger-message-position"' in template
    assert 'class="messenger-message-position"' in script
    assert "item.last_sender" in template
    assert "item.peer.position" in template


def test_identity_template_parses_and_responsive_style_exists():
    template = read("frontend/templates/messenger/staff_messenger.html")
    assert Environment().parse(template) is not None
    css = read("static/css/staff-messenger.css")
    assert "Professional messenger identity system" in css
    assert ".messenger-member-chip" in css
    assert "@media(max-width:680px)" in css


def test_topbar_uses_professional_identity_instead_of_login():
    template = read("frontend/templates/messenger/staff_messenger.html")
    assert "current_profile.full_name" in template
    assert "current_profile.position" in template
    assert "session.get('user_login'" not in template
