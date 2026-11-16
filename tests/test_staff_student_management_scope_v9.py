"""Student management for all-direction and single-direction employees (v9)."""
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_both_employee_ranks_use_the_same_grant_scoped_workspace():
    source = read("backend/app/services/staff_routes.py")
    body = source[source.index("def workspace(current_user):"):source.index("@staff_bp.post('/applications/")]
    assert "direction_ids(current_user, section, 'view')" in body
    assert "sections = {sec:allowed(current_user, selected, sec) for sec in SECTIONS}" in body
    assert "sections['students'] or sections['applications']" in body
    assert "if current_user.role == UserRole.STAFF.value and getattr(current_user, 'staff_rank', 'employee') == 'employee_all'" in body
    # No separate early-return page for single-direction employees remains.
    assert "home_direction =" not in body
    assert "!= 'employee_all'" not in body


def test_only_the_main_administrator_can_create_student_profiles():
    source = read("backend/app/services/staff_routes.py")
    route = source[source.index("def create_student(current_user, direction_id):"):source.index("@staff_bp.post('/students/<int:student_id>/<int:direction_id>/profile')")]
    assert "abort(403)" in route
    guard = read("backend/app/web_app.py").split("if actor.role == UserRole.STAFF.value:", 1)[1].split("# Apply external-facing host checks", 1)[0]
    assert "'staff.create_student'" not in guard
    assert "{% if is_chief_admin %}" in read("frontend/templates/staff/students.html")


def test_student_creation_form_and_legacy_endpoint_are_admin_only():
    template = read("frontend/templates/staff/students.html")
    source = read("backend/app/web_app.py")
    route = source[source.index('@admin_bp.route("/students/add"'):source.index('@admin_bp.route("/students/<int:sid>"')]
    assert "{% if is_chief_admin %}" in template
    assert "@super_admin_required" in route
    staff_route = read("backend/app/services/staff_routes.py")
    create = staff_route[staff_route.index("def create_student(current_user, direction_id):"):staff_route.index("@staff_bp.post('/students/<int:student_id>/<int:direction_id>/profile')")]
    assert "current_user.role != UserRole.SUPER_ADMIN.value" in create
    assert "abort(403)" in create


def test_profile_edit_cannot_change_a_student_shared_with_an_unpermitted_direction():
    source = read("backend/app/services/staff_routes.py")
    route = source[source.index("def update_student_profile(current_user, student_id, direction_id):"):source.index("@staff_bp.post('/notifications')")]
    assert "allowed(current_user, direction_id, 'students', 'manage')" in route
    assert "direction_id not in linked_direction_ids" in route
    assert "manageable_ids = set(direction_ids(current_user, 'students', 'manage'))" in route
    assert "linked_direction_ids.issubset(manageable_ids)" in route
    assert "student.full_name = full_name" in route
    assert "student.phone = phone or None" in route


def test_student_detail_filters_direction_names_for_staff():
    source = read("backend/app/web_app.py")
    route = source[source.index("def student_detail(sid, current_user):"):source.index('@admin_bp.route("/students/<int:sid>/edit"')]
    assert "direction_ids(current_user, 'students', 'view')" in route
    assert "student_directions.c.direction_id.in_(permitted or {-1})" in route
    assert "visible_directions=visible_directions" in route
    template = read("frontend/templates/students/view.html")
    assert "for direction in visible_directions" in template
    assert "for direction in student.directions" not in template


def test_employee_routes_are_explicitly_allowed_and_default_deny_is_preserved():
    source = read("backend/app/web_app.py")
    guard = source.split("if actor.role == UserRole.STAFF.value:", 1)[1].split("# Apply external-facing host checks", 1)[0]
    for endpoint in ("'staff.students'", "'staff.update_student_profile'", "'admin.student_detail'", "'admin.dashboard'"):
        assert endpoint in guard
    assert "if not (is_staff_module_action or is_staff_account_action or is_staff_static):" in guard
    assert "'admin.delete_student'" not in guard


def test_staff_workspace_offers_create_view_and_edit_student_actions():
    template = read("frontend/templates/staff/students.html")
    home = read("frontend/templates/staff/workspace.html")
    assert "Студенты" in template
    assert "{% if is_chief_admin %}" in template
    assert "url_for('staff.create_student'" in template
    assert "url_for('staff.update_student_profile'" in template
    assert "url_for('admin.delete_student'" not in template
    assert 'id="applications"' not in home


def test_staff_sidebar_shows_student_workspace_only_when_student_view_is_granted():
    base = read("frontend/templates/shared/base.html")
    staff_branch = base.split("{% if session.user_role == 'staff' %}", 1)[1].split("{% else %}\n            <nav class=\"sidebar-nav\" data-sidebar-nav aria-label=\"Главная навигация\">", 1)[0]
    assert "{% if staff_nav_access.students %}" in staff_branch
    assert "Студенты" in staff_branch
    context = read("backend/app/web_app.py")
    assert "staff_nav_access[section] = bool(staff_direction_ids(nav_user, section, 'view'))" in context


def test_all_templates_compile():
    env = Environment(loader=FileSystemLoader(str(ROOT / "frontend/templates")))
    for path in (ROOT / "frontend/templates").rglob("*.html"):
        env.get_template(path.relative_to(ROOT / "frontend/templates").as_posix())
