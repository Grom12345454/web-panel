from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_palette_smoke_is_bundled_for_site_and_student_app():
    source = read("frontend/assets/styles/shared/theme-smoke-v59.css")
    site = read("static/css/site.bundle.css")
    student = read("static/css/student-app.bundle.css")
    for content in (source, site, student):
        assert "--theme-smoke-primary" in content
        assert "--theme-smoke-secondary" in content
        assert "holiday-smoke--white" in content
        assert "holiday-smoke--blue" in content
        assert "holiday-smoke--red" in content
        assert "data-season=\"russia_day\"" in content
        assert "data-theme=\"russia_day\"" in content
    assert "BEGIN frontend/assets/styles/shared/theme-smoke-v59.css" in site
    assert "BEGIN frontend/assets/styles/shared/theme-smoke-v59.css" in student


def test_auth_panel_uses_theme_atmosphere_and_stays_server_authenticated():
    base = read("frontend/templates/shared/base.html")
    auth_css = read("frontend/assets/styles/shared/auth-panel-v59.css")
    site = read("static/css/site.bundle.css")
    login = read("frontend/templates/auth/login.html")
    for content in (auth_css, site):
        assert ".auth-atmosphere" in content
        assert "--auth-accent-rgb" in content
        assert "prefers-reduced-motion: reduce" in content
    assert "class=\"auth-atmosphere\"" in base
    assert "csrf_token()" in login
    assert "name=\"username\"" in login and "name=\"password\"" in login
    assert "auth-panel-v59.css" in read("scripts/build_assets.py")


def test_login_security_enhancement_has_accessible_visibility_and_single_submit():
    js = read("frontend/assets/standalone/js/login-security.js")
    published = read("static/js/login-security.js")
    for content in (js, published):
        assert "aria-pressed" in content
        assert "Скрыть пароль" in content
        assert "aria-busy" in content
        assert "dataset.submitting" in content
