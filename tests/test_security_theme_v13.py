from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding='utf-8')


def test_global_security_headers_and_csp_are_present():
    source = read('backend/app/web_app.py')
    for header in ('X-Content-Type-Options', 'Referrer-Policy', 'Permissions-Policy',
                   'X-Permitted-Cross-Domain-Policies', 'Cross-Origin-Opener-Policy',
                   'Cross-Origin-Resource-Policy', 'Content-Security-Policy'):
        assert header in source
    assert 'not settings.LOCAL_DEMO and settings.DEBUG' in source


def test_public_rate_limits_apply_only_to_student_app_and_bot_webhook():
    source = read('backend/app/security.py')
    assert 'default_limits=[]' in source
    assert 'APP_STUDENT_API_RATE_LIMIT' in source
    assert 'APP_STUDENT_API_READ_RATE_LIMIT' in source
    assert 'APP_STUDENT_API_WRITE_RATE_LIMIT' in source
    assert 'APP_BOT_WEBHOOK_RATE_LIMIT' in source
    assert 'path.startswith("/student-app/api/")' in source
    assert '"/hooks/max"' in source
    assert 'swallow_errors=True' in source
    assert '"auth.login"' in source and '"auth.verify_otp"' in source
    assert 'RATELIMIT_STORAGE_URI' in source


def test_host_allowlist_is_scoped_to_student_app_and_bot_webhook():
    source = read('backend/app/web_app.py')
    assert 'app.config["TRUSTED_HOSTS"]' not in source
    assert "path == '/student-app' or path.startswith('/student-app/api/')" in source
    assert "path == '/hooks/max'" in source
    assert 'if external_endpoint and settings.APP_TRUSTED_HOSTS:' in source


def test_otp_delivery_failure_does_not_consume_retry_cooldown():
    source = read('backend/app/web_app.py')
    login_source = source[source.index('@auth_bp.route("/login"'):source.index("@auth_bp.route('/verify'")]
    assert "attempts=2, timeout=5" in login_source
    assert login_source.index("if not delivery:") < login_source.index("_otp_issued[user.id] = requests_recent + [time.time()]")
    assert "redirect(url_for('auth.verify_otp'), code=303)" in login_source


def test_theme_palette_drives_site_and_student_app():
    base = read('frontend/templates/shared/base.html')
    student = read('backend/app/web_app.py')
    css = read('frontend/assets/styles/shared/unified-space-2026.css')
    assert '--office-accent:{{ active_visual_theme_config.palette[0]' in base
    assert '"theme_vars": STUDENT_APP_SEASONS[season_key]["css_vars"]' in student
    assert 'var(--office-accent' in css


def test_security_audit_and_backend_frontend_boundaries_are_documented():
    assert (ROOT / 'backend/wsgi.py').is_file()
    assert (ROOT / 'frontend/README.md').is_file()
    assert (ROOT / 'requirements-security.txt').is_file()
    assert 'pip-audit' in read('SECURITY_HARDENING_V13.md')
