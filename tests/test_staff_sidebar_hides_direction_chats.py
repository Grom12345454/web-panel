"""Direction-chat navigation is hidden for every staff account subtype."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_staff_sidebar_has_no_direction_chat_item_for_either_employee_scope():
    source = (ROOT / "frontend/templates/shared/base.html").read_text(encoding="utf-8")
    staff_branch = source.split("{% if session.user_role == 'staff' %}", 1)[1].split(
        "{% else %}\n            <nav class=\"sidebar-nav\" data-sidebar-nav aria-label=\"Главная навигация\">", 1
    )[0]

    # Both the all-directions employee and the single-direction employee use
    # UserRole.STAFF and therefore share this branch of the sidebar template.
    assert "Чаты направления" not in staff_branch
    assert "url_for('activity_chats.index')" not in staff_branch
    assert "staff_nav_access.activity_chats" not in staff_branch


def test_chat_capability_is_not_removed_from_server_route_policy():
    source = (ROOT / "backend/app/web_app.py").read_text(encoding="utf-8")
    guard = source.split("if actor.role == UserRole.STAFF.value:", 1)[1].split(
        "# Apply external-facing host checks", 1
    )[0]
    assert "'activity_chats.index'" in guard
