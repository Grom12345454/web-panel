from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_login_template_contains_only_single_auth_panel():
    template = (ROOT / "frontend/templates/auth/login.html").read_text(encoding="utf-8")
    assert 'class="premium-login premium-login--single"' in template
    assert 'РАБОЧЕЕ ПРОСТРАНСТВО' in template
    assert 'С возвращением' in template
    assert 'name="username"' in template
    assert 'name="password"' in template
    assert 'name="csrf_token"' in template
    assert 'id="password-visibility"' in template
    assert "premium-story" not in template
    assert "premium-visual" not in template


def test_login_route_skips_global_decorative_scenes_and_duplicate_flash():
    base = (ROOT / "frontend/templates/shared/base.html").read_text(encoding="utf-8")
    condition = "{% if request.endpoint not in ['auth.login', 'auth.verify_otp'] %}"
    assert base.count(condition) >= 2
    assert "request.endpoint in ['auth.login', 'auth.verify_otp']" in base
    assert 'is-login-page is-auth-page' in base


def test_single_panel_styles_are_bundled_last():
    build = (ROOT / "scripts/build_assets.py").read_text(encoding="utf-8")
    assert "'shared/login-single-panel-v36.css'" in build
    bundle = (ROOT / "static/css/site.bundle.css").read_text(encoding="utf-8")
    assert "v36 — single dark authentication panel" in bundle
    assert bundle.rfind("v36 — single dark authentication panel") > bundle.rfind("V34 — stable login panel")


def test_login_panel_uses_dark_responsive_surface():
    css = (ROOT / "frontend/assets/styles/shared/login-single-panel-v36.css").read_text(encoding="utf-8")
    assert "#050d15" in css
    assert "100dvh" in css
    assert "env(safe-area-inset-top" in css
    assert "@media (max-width: 420px)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css


def test_otp_template_uses_the_same_dark_single_panel():
    template = (ROOT / "frontend/templates/auth/verify.html").read_text(encoding="utf-8")
    assert 'class="premium-login premium-login--single"' in template
    assert 'РАБОЧЕЕ ПРОСТРАНСТВО' in template
    assert 'name="code"' in template
    assert 'name="csrf_token"' in template
    assert 'id="otp-seconds"' in template
    assert "url_for('auth.login')" in template


def test_auth_routes_do_not_emit_global_space_model_or_flash_stack():
    base = (ROOT / "frontend/templates/shared/base.html").read_text(encoding="utf-8")
    assert "request.endpoint not in ['auth.login', 'auth.verify_otp']" in base
    assert "is-login-page is-auth-page" in base
    assert base.count("request.endpoint not in ['auth.login', 'auth.verify_otp']") >= 2


def test_otp_countdown_disables_new_panel_submit_button():
    js = (ROOT / "static/js/otp.js").read_text(encoding="utf-8")
    assert ".premium-auth--single .premium-submit[type=\"submit\"]" in js
