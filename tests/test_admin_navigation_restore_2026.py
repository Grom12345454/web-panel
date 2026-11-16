"""The chief administrator retains the complete legacy administration navigation."""
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]


def test_only_employees_use_the_direction_scoped_staff_sidebar():
    source = (ROOT / "frontend/templates/shared/base.html").read_text(encoding="utf-8")
    assert "{% if session.user_role == 'staff' %}" in source
    assert "{% if session.user_role in ['staff', 'super_admin'] %}" not in source


def test_main_admin_retains_all_previous_admin_navigation_groups():
    source = (ROOT / "frontend/templates/shared/base.html").read_text(encoding="utf-8")
    legacy_admin_branch = source.split("{% else %}", 1)[1]
    for expected in (
        "admin.students_management",
        "admin.blocked_students",
        "admin.leadership_public",
        "stats.overview_statistics",
        "staff.accounts",
        "admin.event_reports",
        "admin.manage_leadership",
        "admin.student_app_design",
        "admin.system_runtime",
        "admin.system_maintenance",
        "admin.user_activity_log",
        "admin.messenger_monitoring",
    ):
        assert expected in legacy_admin_branch


def test_staff_navigation_does_not_expose_global_admin_controls():
    source = (ROOT / "frontend/templates/shared/base.html").read_text(encoding="utf-8")
    staff_branch = source.split("{% if session.user_role == 'staff' %}", 1)[1].split("{% else %}", 1)[0]
    # The employee branch contains no account-management or system-admin links.
    assert "staff.accounts" not in staff_branch
    assert "admin.system_maintenance" not in staff_branch
    assert "admin.user_activity_log" not in staff_branch


def test_all_templates_compile_after_restoring_admin_navigation():
    env = Environment(loader=FileSystemLoader(str(ROOT / "frontend/templates")))
    for path in (ROOT / "frontend/templates").rglob("*.html"):
        env.get_template(path.relative_to(ROOT / "frontend/templates").as_posix())
