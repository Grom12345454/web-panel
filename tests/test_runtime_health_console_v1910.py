"""Regression checks for the v1.9.10 system health console presentation."""
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_console_has_a_single_anchor_for_each_major_section():
    template = (ROOT / "frontend/templates/system/runtime.html").read_text("utf-8")
    for anchor in (
        "runtime-databases", "runtime-process", "runtime-integrations", "runtime-http",
        "runtime-queue", "runtime-workers", "runtime-recovery",
    ):
        assert template.count(f'id="{anchor}"') == 1
        assert f'href="#{anchor}"' in template


def test_runtime_console_keeps_live_data_hooks_and_refresh_action():
    template = (ROOT / "frontend/templates/system/runtime.html").read_text("utf-8")
    for hook in (
        "data-runtime-url", "data-runtime-refresh", "data-runtime-health-banner",
        "data-runtime-health-label", "data-runtime-db-healthy", "data-runtime-workers-running",
        "data-db-bind", "data-worker", "data-integration", "data-queue-row",
    ):
        assert hook in template
    assert "url_for('admin.system_maintenance')" in template
    assert "url_for('admin.system_runtime_status')" in template


def test_runtime_console_redesign_is_in_the_canonical_bundle_and_manifest():
    css_source = "frontend/assets/styles/staff/runtime-health-console-v199.css"
    css = (ROOT / css_source).read_text("utf-8")
    bundle = (ROOT / "static/css/site.bundle.css").read_text("utf-8")
    manifest = (ROOT / "frontend/asset-manifest.json").read_text("utf-8")
    build_script = (ROOT / "scripts/build_assets.py").read_text("utf-8")
    assert ".runtime-console-nav" in css and "prefers-reduced-motion" in css
    assert "runtime-health-console-v199.css" in bundle
    assert css_source.split("frontend/assets/styles/")[-1] in manifest
    assert "runtime-health-console-v199.css" in build_script


def test_runtime_template_compiles_with_jinja():
    env = Environment(loader=FileSystemLoader(str(ROOT / "frontend/templates")))
    env.get_template("system/runtime.html")


def test_runtime_status_icon_tracks_latest_health_state():
    source = (ROOT / "static/js/runtime-status.js").read_text("utf-8")
    assert "const mark = banner.querySelector('.pro-runtime-health-mark')" in source
    assert "state === 'ok' ? '✓'" in source
