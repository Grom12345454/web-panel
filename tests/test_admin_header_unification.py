from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_ui_polish_has_one_canonical_source_and_legacy_alias_only():
    build = read("scripts/build_assets.py")
    canonical = read("frontend/assets/styles/portal/ui-polish.css")
    alias = read("frontend/assets/standalone/css/ui-polish-v9.css")
    assert "'ui-polish.css'" not in build.split("STANDALONE_CSS = [", 1)[1].split("]", 1)[0]
    assert not (ROOT / "frontend/assets/standalone/css/ui-polish.css").exists()
    assert '@import url("/static/css/ui-polish.css")' in alias
    for version in range(5, 9):
        assert f"'ui-polish-v{version}.css'" not in build
        assert not (ROOT / f"static/css/ui-polish-v{version}.css").exists()
    assert "Consolidated from ui-polish-v5.css" in canonical
    assert "Consolidated from ui-polish-v9.css" in canonical


def test_admin_header_fix_is_last_in_site_bundle_and_version_independent():
    manifest = json.loads(read("frontend/asset-manifest.json"))
    site_files = manifest["bundles"]["site_css"]["files"]
    assert site_files[-1] == "portal/admin-header-fix.css"
    header = read("frontend/assets/styles/portal/admin-header-fix.css")
    assert 'body.uc-body .app-shell > .main > .topbar' in header
    assert 'body.uc-body .topbar-inner' in header
    assert 'body.uc-body .top-title-accent' in header
    assert 'data-ui-version="11"' not in header
    bundle = read("static/css/site.bundle.css")
    assert "Unified administration header" in bundle


def test_admin_header_title_is_centered_large_and_theme_reactive():
    header = read("frontend/assets/styles/portal/admin-header-fix.css")
    assert "grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr)" in header
    assert "grid-column: 2" in header
    assert "font-size: clamp(20px, 1.48vw, 28px)" in header
    assert "admin-header-smoke-drift" in header
    assert "admin-header-title-shimmer" in header
    assert "var(--office-accent-rgb" in header
    assert "var(--office-secondary-rgb" in header
    assert "prefers-reduced-motion: reduce" in header
