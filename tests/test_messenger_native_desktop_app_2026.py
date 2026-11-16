import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "desktop-app"


def test_standalone_electron_package_is_defined_and_pinned():
    package = json.loads((DESKTOP / "package.json").read_text(encoding="utf-8"))
    assert package["main"] == "main.cjs"
    assert package["scripts"]["build:win"] == "electron-builder --win nsis --x64"
    assert package["devDependencies"]["electron"] == "45.3.1"
    assert package["devDependencies"]["electron-builder"] == "26.18.1"


def test_electron_window_is_sandboxed_and_restricted_to_messenger_routes():
    source = (DESKTOP / "main.cjs").read_text(encoding="utf-8")
    assert "contextIsolation: true" in source
    assert "nodeIntegration: false" in source
    assert "sandbox: true" in source
    assert "function isAllowedAppUrl" in source
    assert "p === '/messenger'" in source
    assert "p === '/auth'" in source
    assert "event.preventDefault()" in source


def test_native_client_uses_native_windows_notification_bridge_and_tray():
    main = (DESKTOP / "main.cjs").read_text(encoding="utf-8")
    preload = (DESKTOP / "preload.cjs").read_text(encoding="utf-8")
    frontend = (ROOT / "static/js/staff-messenger.js").read_text(encoding="utf-8")
    assert "new Notification({" in main
    assert "new Tray(" in main
    assert "desktop:show-notification" in main
    assert "notificationCursor" in main
    assert "notifications-cursor-save" in main
    assert "showNotification" in preload
    assert "saveNotificationCursor" in preload
    assert "window.studsovetDesktop" in frontend
    assert "data-native-desktop" in (ROOT / "frontend/templates/messenger/staff_messenger.html").read_text(encoding="utf-8")


def test_run_bat_launches_electron_source_not_browser_app_mode():
    launcher = (ROOT / "RUN_MESSENGER_DESKTOP.bat").read_text(encoding="utf-8")
    assert "npm start" in launcher
    assert "msedge.exe --app" not in launcher
    assert "chrome.exe --app" not in launcher
