from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_http_csp_does_not_unconditionally_upgrade_local_http():
    source = read("backend/app/web_app.py")
    assert "if request.is_secure or settings.SESSION_COOKIE_SECURE:" in source
    assert 'csp += " upgrade-insecure-requests;"' in source
    csp_block = source[source.index("csp = ("):source.index("# Do not upgrade requests on the local/private HTTP server.")]
    assert "upgrade-insecure-requests" not in csp_block.split("if request.is_secure", 1)[0]


def test_theme_sync_does_not_poll_from_unauthenticated_login_or_otp_pages():
    source = read("frontend/assets/scripts/portal/theme-live-sync.js")
    base = read("frontend/templates/shared/base.html")
    assert "body.dataset.authenticated !== '1'" in source
    assert "data-authenticated=\"{{ '1' if session.get('user_id') else '0' }}\"" in base


def test_login_uses_zoom_stable_layout_source_and_built_bundle():
    builder = read("scripts/build_assets.py")
    source = read("frontend/assets/styles/shared/login-zoom-stability-v34.css")
    bundle = read("static/css/site.bundle.css")
    assert "shared/login-zoom-stability-v34.css" in builder
    assert "@media (min-width: 761px)" in source
    assert "@media (max-width: 760px)" in source
    assert bundle.rfind("V34 — stable login panel") > bundle.rfind("V33")
    assert "max-height: calc(100dvh - 24px)" in bundle


def test_favicon_root_is_served_and_optional_student_lookup_is_guarded():
    source = read("backend/app/web_app.py")
    staff = read("backend/app/services/staff_routes.py")
    assert '@app.get("/favicon.ico")' in source
    assert 'mimetype="image/vnd.microsoft.icon"' in source
    assert "suggested_student_id is not None" in staff
