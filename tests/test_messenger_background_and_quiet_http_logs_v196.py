from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_main_window_close_hides_to_tray_until_explicit_quit():
    source = (ROOT / "desktop-app/main.cjs").read_text(encoding="utf-8")
    close_handler = source[source.index("mainWindow.on('close'"):source.index("mainWindow.on('closed'")]
    assert "if (!quitting)" in close_handler
    assert "event.preventDefault()" in close_handler
    assert "mainWindow.hide()" in close_handler
    assert "function quitApplication()" in source
    assert "if (tray) { tray.destroy(); tray = null; }" in source


def test_successful_werkzeug_access_logs_are_suppressed_but_app_logs_remain_info():
    for name in ("run.py", "main.py"):
        source = (ROOT / name).read_text(encoding="utf-8")
        assert "logging.basicConfig(level=logging.INFO" in source
        assert 'logging.getLogger("werkzeug").setLevel(logging.WARNING)' in source


def test_desktop_theme_poll_is_at_most_once_per_15_seconds():
    source = (ROOT / "static/js/staff-messenger.js").read_text(encoding="utf-8")
    assert "const DESKTOP_THEME_POLL_INTERVAL = 15000" in source
    assert "scheduleDesktopThemePoll(250)" not in source
