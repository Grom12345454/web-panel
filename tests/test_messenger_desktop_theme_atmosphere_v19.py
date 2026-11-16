from pathlib import Path
from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]


def test_native_messenger_reuses_site_art_and_smoke_layers():
    template = (ROOT / "frontend/templates/messenger/staff_messenger.html").read_text(encoding="utf-8")
    styles = (ROOT / "static/css/messenger-workspace.css").read_text(encoding="utf-8")
    site_image = ROOT / "static/images/campus-space.webp"
    assert 'class="portal-theme-atmosphere messenger-theme-atmosphere"' in template
    assert all(f"holiday-smoke holiday-smoke--{name}" in template for name in ("white", "blue", "red"))
    assert site_image.is_file()
    assert 'url("../images/campus-space.webp")' in styles
    assert 'url("../favicon-watermark.png")' in styles
    assert "prefers-reduced-motion: reduce" in styles


def test_native_messenger_theme_sync_is_fast_and_does_not_reload():
    script = (ROOT / "static/js/staff-messenger.js").read_text(encoding="utf-8")
    assert "root.dataset.nativeDesktop === '1'" in script
    assert "fetch('/api/visual-theme'" in script
    assert "cache: 'no-store'" in script
    assert "const DESKTOP_THEME_POLL_INTERVAL = 15000" in script
    assert "scheduleDesktopThemePoll(DESKTOP_THEME_POLL_INTERVAL)" in script
    assert "applyLiveTheme({ ...palette, type: 'theme-save' })" in script


def test_desktop_shortcut_uses_exact_site_favicon_assets():
    site_ico = Image.open(ROOT / "static/favicon.ico").convert("RGBA")
    app_ico = Image.open(ROOT / "desktop-app/assets/messenger.ico").convert("RGBA")
    assert ImageChops.difference(site_ico, app_ico).getbbox() is None
    site_mark = Image.open(ROOT / "static/favicon-watermark.png").convert("RGBA")
    assert site_mark.size == (512, 512)
    assert (ROOT / "desktop-app/assets/messenger.png").is_file()
    assert (ROOT / "desktop-app/package.json").read_text(encoding="utf-8").find('"version": "1.9.6"') >= 0
