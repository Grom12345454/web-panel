"""The staff messenger is desktop-only; the website exposes no chat page."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_messenger_template_is_a_standalone_desktop_document():
    template = read("frontend/templates/messenger/staff_messenger.html")
    assert "extends 'shared/base.html'" not in template
    assert "messenger-workspace-topbar" in template
    assert 'aria-label="Боковая панель чатов"' in template
    assert 'data-chat-filter="all"' in template
    assert 'data-chat-filter="direct"' in template
    assert 'data-chat-filter="group"' in template
    assert 'data-chat-filter="general"' in template
    assert 'css/messenger-workspace.css' in template
    assert 'data-native-desktop="{{ \'1\' if native_desktop else \'0\' }}"' in template
    assert "Веб-версия мессенджера в отдельном окне" not in template
    assert "data-install-desktop" not in template
    assert "manifest" not in template
    assert template.rstrip().endswith("</html>")


def test_website_navigation_does_not_expose_messenger():
    base = read("frontend/templates/shared/base.html")
    assert "staff_messenger.index" not in base
    assert "staff_messenger.communications" not in base
    assert "Внутренний чат" not in base
    assert "Центр коммуникаций" not in base
    assert "registration.unregister()" in base
    assert "/messenger/service-worker.js" in base
    assert not (ROOT / "frontend/templates/messenger/communications.html").exists()


def test_messenger_page_is_gated_to_desktop_shell_and_session_is_ephemeral():
    service = read("backend/app/services/staff_messenger.py")
    desktop = read("desktop-app/main.cjs")
    assert '@staff_messenger_bp.get("/messenger")' in service
    assert '@staff_messenger_bp.get("/staff-messenger")' in service
    assert 'request.headers.get("X-StudSovet-Desktop") != "1"' in service
    assert "abort(404)" in service
    assert "const DESKTOP_PARTITION = 'temp:studsovet-messenger'" in desktop
    assert "X-StudSovet-Desktop" in desktop
    assert "partition: DESKTOP_PARTITION" in desktop
    assert "app.on('window-all-closed', () => app.quit())" in desktop


def test_browser_pwa_assets_and_web_install_entrypoints_are_removed():
    assert not (ROOT / "static/messenger-sw.js").exists()
    assert not (ROOT / "static/messenger-icon-192.png").exists()
    assert not (ROOT / "static/messenger-icon-512.png").exists()
    service = read("backend/app/services/staff_messenger.py")
    script = read("static/js/staff-messenger.js")
    assert "def desktop_manifest" not in service
    assert "def desktop_service_worker" not in service
    assert "navigator.serviceWorker.register" not in script
    assert "beforeinstallprompt" not in script
