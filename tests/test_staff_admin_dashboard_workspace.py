"""Staff workspace is a clean home page, separate from the two scoped people pages."""
from pathlib import Path
from types import SimpleNamespace
from jinja2 import Environment, ChoiceLoader, DictLoader, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]


def test_staff_workspace_uses_the_shared_admin_shell():
    template = (ROOT / 'frontend/templates/staff/workspace.html').read_text('utf-8')
    base = (ROOT / 'frontend/templates/shared/base.html').read_text('utf-8')
    builder = (ROOT / 'scripts/build_assets.py').read_text('utf-8')
    assert 'galaxy-dashboard staff-dashboard' in template
    assert "['admin.dashboard', 'staff.workspace']" in base
    assert "staff/role-workspace-dashboard-2026.css" in builder


def test_employee_home_moves_student_workflow_to_the_sidebar_destination():
    home = (ROOT / 'frontend/templates/staff/workspace.html').read_text('utf-8')
    students = (ROOT / 'frontend/templates/staff/students.html').read_text('utf-8')
    base = (ROOT / 'frontend/templates/shared/base.html').read_text('utf-8')
    for removed_panel in ('id=\"applications\"', 'id=\"notifications\"', 'id=\"lessons\"', 'id=\"events\"'):
        assert removed_panel not in home
    assert "url_for('staff.students')" in base
    assert "{% if is_chief_admin %}" in students
    assert "staff.update_student_profile" in students
    assert "admin.student_detail" in students
    assert "may_manage('students')" in students



def test_direction_employee_and_global_employee_share_scoped_workspace_route():
    source = (ROOT / 'backend/app/services/staff_routes.py').read_text('utf-8')
    start = source.index('def workspace(current_user):')
    end = source.index("@staff_bp.post('/applications/", start)
    body = source[start:end]
    assert "if current_user.role not in {UserRole.STAFF.value, UserRole.SUPER_ADMIN.value}" in body
    assert "direction_ids(current_user, section, 'view')" in body
    assert "sections = {sec:allowed(current_user, selected, sec) for sec in SECTIONS}" in body
    assert "sections['students'] or sections['applications']" in body
    assert "is_global_employee=(current_user.role == UserRole.STAFF.value" in body


def test_employee_workspace_opens_the_shared_role_scoped_admin_dashboard():
    route = (ROOT / 'backend/app/services/staff_routes.py').read_text('utf-8')
    dashboard = (ROOT / 'backend/app/web_app.py').read_text('utf-8')
    base = (ROOT / 'frontend/templates/shared/base.html').read_text('utf-8')
    start = route.index('def workspace(current_user):')
    end = route.index("@staff_bp.get('/students')", start)
    body = route[start:end]
    assert "if current_user.role == UserRole.STAFF.value:" in body
    assert "return redirect(url_for('admin.dashboard'))" in body
    assert 'url_for("staff.students")' in dashboard
    assert "url_for('staff.workspace')" not in base.split("{% if session.user_role == 'staff' %}", 1)[1].split("{% else %}\n            <nav class=\"sidebar-nav\"", 1)[0]
