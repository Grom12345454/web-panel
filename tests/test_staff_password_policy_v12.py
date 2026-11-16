"""Security and UI regressions for the v12 staff access/password work."""
from pathlib import Path

from services.password_policy import validate_new_password

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_password_policy_accepts_strong_unique_password():
    assert validate_new_password("Orbit!North2026", "staff.user@example.org") is None


def test_password_policy_rejects_weak_or_account_related_passwords():
    assert "12 символов" in validate_new_password("Short!1", "staff")
    assert "заглавную" in validate_new_password("longpassword!123", "staff")
    assert "логин" in validate_new_password("Staff.User!2026", "staff.user")
    assert "отличаться" in validate_new_password(
        "Orbit!North2026", "staff.user", "stored-hash",
        verify=lambda candidate, encoded: candidate == "Orbit!North2026",
    )


def test_forced_password_change_is_a_standalone_page_and_describes_policy():
    template = read("frontend/templates/auth/change_password.html")
    assert "<!doctype html>" in template.lower()
    assert "{% extends" not in template
    assert 'name="new_password"' in template
    assert 'name="confirm_password"' in template
    assert 'name="csrf_token"' in template
    assert "Не менее 12 символов" in template
    assert 'role="dialog"' not in template
    assert "aria-modal" not in template
    assert "position:fixed" not in template
    assert "document.body.appendChild" not in template
    assert "keydown" not in template


def test_password_reset_can_target_one_or_all_active_panel_accounts():
    routes = read("backend/app/services/staff_routes.py")
    account_page = read("frontend/templates/staff/accounts.html")
    assert "@staff_bp.post('/accounts/password-reset')" in routes
    assert "scope == 'all'" in routes
    assert "target.must_change_password = True" in routes
    assert 'name="user_id"' in account_page
    assert 'name="scope" value="all"' in account_page


def test_staff_reports_are_read_only_and_student_app_syncs_theme_without_reload():
    app = read("backend/app/web_app.py")
    student_app = read("frontend/assets/scripts/student/student_app.js")
    assert "path == '/most-active-students') and request.method not in {'GET', 'HEAD', 'OPTIONS'}" in app
    assert '"theme_vars": STUDENT_APP_SEASONS[season_key]["css_vars"]' in app
    assert "document.body.dataset.season=signal.season" in student_app
    assert "Math.max(30000, STUDENT_SYNC_INTERVAL)" in student_app
    assert "window.location.reload" not in student_app
    login_css = read("frontend/assets/styles/shared/login-awwwards-2026.css")
    assert "animation:premium-rise" not in login_css


def test_frontend_backend_boundaries_have_documented_entry_points():
    assert (ROOT / "backend/wsgi.py").is_file()
    assert "app = create_app()" in read("backend/wsgi.py")
    assert "frontend/assets/scripts/" in read("frontend/README.md")

def test_password_rotation_uses_the_shared_session_guard_and_rebuilds_session():
    app = read("backend/app/web_app.py")
    route_start = app.index('@auth_bp.route("/change-password", methods=["GET", "POST"])')
    route_end = app.index('@auth_bp.route("/logout"', route_start)
    route = app[route_start:route_end]
    assert "@login_required" in route
    assert "def change_password(current_user):" in route
    assert "user.must_change_password = False" in route
    assert "db.session.commit()" in route
    assert "db.session.refresh(user)" not in route
    assert 'session.clear()' in route
    assert 'session["auth_version"] = next_auth_version' in route
    assert 'session["_csrf_token"] = secrets.token_urlsafe(32)' in route
    assert 'return redirect(url_for("admin.dashboard"), code=303)' in route
