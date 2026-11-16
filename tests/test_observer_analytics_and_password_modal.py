from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def read(path):
    return (ROOT / path).read_text(encoding="utf-8")

def test_observer_sees_analytics_navigation():
    nav = read("frontend/templates/shared/base.html")
    assert "{% if session.user_role in ['super_admin', 'observer'] %}" in nav
    assert "Статистика" in nav and "Активные студенты" in nav

def test_observer_analytics_access_is_read_only():
    source = read("backend/app/web_app.py")
    decorator = source[source.index("def analytics_view_required"):source.index("def archive_year_admin_required")]
    assert "UserRole.SUPER_ADMIN.value, UserRole.OBSERVER.value" in decorator
    assert 'request.method not in {"GET", "HEAD", "OPTIONS"}' in decorator
    for name in ("overview_statistics", "direction_statistics", "most_active_students"):
        assert f"@analytics_view_required\ndef {name}" in source

def test_password_change_page_is_not_a_tab_blocking_modal():
    template = read("frontend/templates/auth/change_password.html")
    assert "<!doctype html>" in template.lower()
    assert "document.body.appendChild" not in template
    assert "password-rotation-backdrop" not in template
    assert "password-rotation-open" not in template
    assert 'aria-modal="true"' not in template
    assert "Keep keyboard focus inside" not in template
    assert "action=\"{{ url_for('auth.change_password') }}\"" in template
