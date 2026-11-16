from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_employee_broadcast_rejects_site_and_staff_inbox_channels():
    source = (ROOT / "backend/app/web_app.py").read_text(encoding="utf-8")
    block = source[source.index("def notifications_publish(current_user):"):source.index("def messenger_chat_create(current_user):")]
    assert "if 'site' in channels or 'staff_dm' in channels" in block
    assert "raise PermissionError" in block

def test_employee_notification_composer_hides_site_and_staff_delivery():
    template = (ROOT / "frontend/templates/system/notifications.html").read_text(encoding="utf-8")
    assert "{% if is_superadmin %}<label class=\"alerts-channel-option\"><input type=\"checkbox\" name=\"channels\" value=\"site\"" in template
    assert "{% if is_superadmin %}<label class=\"alerts-channel-option\"><input type=\"checkbox\" name=\"channels\" value=\"staff_dm\"" in template
    assert "Публикация на сайте недоступна" in template

def test_chat_discovery_and_binding_are_superadmin_only():
    source = (ROOT / "backend/app/web_app.py").read_text(encoding="utf-8")
    block = source[source.index("def _can_manage_direction_chats"):source.index("def _require_direction_chat_management")]
    assert "user.role == UserRole.SUPER_ADMIN.value" in block
    assert "Only the chief administrator" in block
