"""All role panels share the same visual primitives without changing access rules."""
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]


def test_role_panel_parity_layer_is_last_in_the_canonical_css_bundle():
    manifest = (ROOT / "scripts/build_assets.py").read_text(encoding="utf-8")
    css = (ROOT / "frontend/assets/styles/shared/role-panel-parity-2026.css").read_text(encoding="utf-8")
    assert "'shared/role-panel-parity-2026.css'" in manifest
    assert manifest.index("'shared/role-panel-parity-2026.css'") > manifest.index("'shared/unified-dashboard-foundation-2026.css'")
    assert "body.uc-body:not(.is-auth-page)" in css
    for primitive in (".card", ".table-wrap", ".section-title", "textarea", ".btn"):
        assert primitive in css


def test_staff_leader_archive_and_observer_keep_the_same_dashboard_template():
    source = (ROOT / "backend/app/web_app.py").read_text(encoding="utf-8")
    start = source.index("def dashboard(current_user):")
    end = source.index("BOT_MONITOR_ACTION_LABELS", start)
    dashboard = source[start:end]
    assert 'dashboard_mode="full"' in dashboard
    assert 'if role == UserRole.STAFF.value:' in dashboard
    assert 'UserRole.OBSERVER.value' in dashboard
    assert 'UserRole.LEADER.value' in dashboard
    assert '"dashboard/overview.html"' in dashboard


def test_all_templates_still_compile_after_cross_role_visual_layer():
    env = Environment(loader=FileSystemLoader(str(ROOT / "frontend/templates")))
    for path in (ROOT / "frontend/templates").rglob("*.html"):
        env.get_template(path.relative_to(ROOT / "frontend/templates").as_posix())


def test_readonly_role_and_direction_scope_rules_are_not_replaced_by_visual_styles():
    observer_css = (ROOT / "frontend/assets/styles/shared/observer-readonly-v46.css").read_text(encoding="utf-8")
    staff_routes = (ROOT / "backend/app/services/staff_routes.py").read_text(encoding="utf-8")
    assert "body.role-observer form[method=\"post\" i]" in observer_css
    assert "permitted = set().union(*(direction_ids(current_user, section, 'view') for section in SECTIONS))" in staff_routes
    assert "allowed(current_user, selected, sec)" in staff_routes
