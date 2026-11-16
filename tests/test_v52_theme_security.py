from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_v56_tricolour_smoke_replaces_flag_graphic_and_motion_is_bundled():
    css = read("static/css/student-app.bundle.css")
    assert ".holiday-flag" not in css
    assert "rgba(255,255,255,.64)" in css
    assert "rgba(0,57,166,.72)" in css
    assert "rgba(213,43,30,.62)" in css
    assert "holiday-smoke-drift" in css
    assert "data-season] .holiday-smoke" in css
    assert "holiday-particle { display: none !important; }" in css
    assert "theme-atmosphere-breathe" in css


def test_admin_starfield_is_scoped_and_orders_archive_is_excluded():
    base = read("frontend/templates/shared/base.html")
    css = read("static/css/site.bundle.css")
    script = read("static/js/site.bundle.js")
    student = read("frontend/templates/student/student_app.html")
    assert "data-admin-entry-sky" in base
    assert "data-student-entry-sky" in student
    assert "student-app-entry-sky-v52" in script
    assert "role-super_admin" in script
    assert "admin-entry-sky-reveal" in css
    assert "not([data-page^=\"orders-\"])" in css
    assert "not (request.endpoint or '').startswith('orders.')" in base


def test_student_app_and_admin_effects_do_not_restyle_orders_archive():
    base = read("frontend/templates/shared/base.html")
    css = read("frontend/assets/styles/shared/holiday-atmosphere-v52.css")
    archive = read("frontend/templates/orders/archive.html")
    assert "portal-theme-atmosphere" in base
    assert "orders." in base
    assert "data-page^=\"orders-\"" in css
    assert "holiday-atmosphere-v52" not in archive


def test_telegram_initdata_is_size_limited_and_duplicate_fields_are_rejected():
    source = read("backend/app/web_app.py")
    validator = source[source.index("def validate_telegram_init_data"):source.index("def _student_overall_status")]
    assert "len(init_data) > 8192" in validator
    assert "max_num_fields=64" in validator
    assert "len(names) != len(set(names))" in validator
    assert "hmac.compare_digest" in validator


def test_admin_sessions_and_frame_policy_are_hardened():
    source = read("backend/app/web_app.py")
    assert 'SESSION_REFRESH_EACH_REQUEST"] = False' in source
    assert 'PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)' not in source
    assert "session['_auth_issued_at']" not in source
    assert 'X-Frame-Options", "DENY"' in source
    assert "frame-ancestors 'none'" in source
    assert "APP_ADMIN_TRUSTED_HOSTS" not in source
    assert 'cap_override=300' in source
    assert '"max-bot-webhook"' in source


def test_rate_limits_cover_student_app_write_bot_webhook_and_admin_auth_routes():
    source = read("backend/app/security.py")
    for value in (
        "APP_STUDENT_API_READ_RATE_LIMIT",
        "APP_STUDENT_API_WRITE_RATE_LIMIT",
        "APP_BOT_WEBHOOK_RATE_LIMIT",
        "APP_ADMIN_LOGIN_RATE_LIMIT",
        "APP_ADMIN_OTP_RATE_LIMIT",
        '"auth.login"',
        '"auth.verify_otp"',
        'default_limits=[]',
    ):
        assert value in source
