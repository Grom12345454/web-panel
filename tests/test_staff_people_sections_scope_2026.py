"""Employee people pages stay direction-scoped and the old workspace panels are removed."""
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]


def test_staff_sidebar_exposes_only_the_requested_people_pages():
    base = (ROOT / 'frontend/templates/shared/base.html').read_text(encoding='utf-8')
    staff = base.split("{% if session.user_role == 'staff' %}", 1)[1].split("{% else %}\n            <nav class=\"sidebar-nav\" data-sidebar-nav aria-label=\"Главная навигация\">", 1)[0]
    assert "url_for('admin.blocked_students')" in staff
    assert "url_for('admin.leadership_public')" in staff
    assert 'Заблокированные' in staff
    assert 'Руководство студсовета' in staff
    assert 'Студенты' in staff
    assert "staff_nav_access.students" in staff
    assert "'admin.leadership_public'" in base.split("{% if session.user_role == 'staff' %}", 1)[1]


def test_employee_workspace_removes_student_panel_and_uses_dedicated_sidebar_page():
    home = (ROOT / 'frontend/templates/staff/workspace.html').read_text(encoding='utf-8')
    students = (ROOT / 'frontend/templates/staff/students.html').read_text(encoding='utf-8')
    base = (ROOT / 'frontend/templates/shared/base.html').read_text(encoding='utf-8')
    assert 'id="applications"' not in home
    assert "url_for('staff.students')" in base
    assert "may_manage('students')" in students
    assert "{% if is_chief_admin %}" in students
    assert "url_for('staff.create_student'" in students
    assert "url_for('staff.update_student_profile'" in students


def test_blocked_students_route_filters_staff_to_assigned_direction():
    source = (ROOT / 'backend/app/web_app.py').read_text(encoding='utf-8')
    route = source.split('def blocked_students(current_user):', 1)[1].split('@admin_bp.route("/blocked-students/add"', 1)[0]
    assert "current_user.role == UserRole.STAFF.value" in route
    assert "scoped_direction_ids = set(staff_direction_ids(current_user, 'students', 'view'))" in route
    assert "ApplicationDecision.direction_id.in_(scoped_direction_ids)" in route


def test_leadership_directory_filters_employee_rows_and_cards_by_direction():
    source = (ROOT / 'backend/app/web_app.py').read_text(encoding='utf-8')
    route = source.split('def leadership_public(current_user):', 1)[1].split('def _lesson_message', 1)[0]
    assert 'StudentLeadership.direction_id.in_(direction_scope)' in route
    assert 'leadership_cards(direction_ids=direction_scope)' in route
    assert 'is_global_role_name' in route


def test_leadership_card_builder_has_explicit_direction_filter():
    source = (ROOT / 'backend/app/services/leadership_directory.py').read_text(encoding='utf-8')
    assert 'def leadership_cards(direction_ids=None):' in source
    assert 'StudentLeadership.direction_id.in_(allowed_ids)' in source
    assert 'not is_global_role_name(row.position_name)' in source


def test_templates_compile():
    env = Environment(loader=FileSystemLoader(str(ROOT / 'frontend/templates')))
    for path in (ROOT / 'frontend/templates').rglob('*.html'):
        env.get_template(path.relative_to(ROOT / 'frontend/templates').as_posix())
