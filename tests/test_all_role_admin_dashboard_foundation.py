"""All panel roles share the admin dashboard shell while server scopes remain role-specific."""
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_every_role_dashboard_uses_the_shared_admin_visual_components():
    overview = read("frontend/templates/dashboard/overview.html")
    base = read("frontend/templates/shared/base.html")
    route = read("backend/app/services/staff_routes.py")
    for partial in (
        "dashboard/_dashboard_hero.html",
        "dashboard/_dashboard_metrics.html",
        "dashboard/_dashboard_overview_panels.html",
    ):
        assert partial in overview
    assert "unified-role-dashboard" in overview
    assert "is-dashboard-page" in base
    workspace = route[route.index("def workspace(current_user):"):route.index("@staff_bp.get('/students')")]
    assert "if current_user.role == UserRole.STAFF.value:" in workspace
    assert "return redirect(url_for('admin.dashboard'))" in workspace


def test_legacy_archive_admin_role_is_removed_from_the_active_dashboard():
    source = read("backend/app/web_app.py")
    helper = read("backend/app/database/helpers.py")
    dashboard = source[source.index("def dashboard(current_user):"):source.index("def ", source.index("def dashboard(current_user):") + 10)]
    base = read("frontend/templates/shared/base.html")
    assert 'dashboard_mode="archive"' not in dashboard
    assert "session.user_role == 'admin'" not in base
    assert "migrate_staff_account_roles(settings.PEOPLE_DATABASE_PATH)" in helper
    assert "assigned_direction_id=NULL" in helper


def test_staff_and_leader_routes_cannot_expand_to_the_global_student_register():
    source = read("backend/app/web_app.py")
    students = source[source.index("def students_management(current_user):"):source.index("@admin_bp.route(\"/most-active-students\")")]
    directions = source[source.index("def directions_list(current_user):"):source.index("@directions_bp.route(\"/<int:did>/chat-message\"")]
    assert 'return redirect(url_for("staff.workspace"))' in students
    assert 'return redirect(url_for("directions.directions_list"))' in students
    assert "_lesson_access_scope(current_user)" in directions
    assert "Direction.id.in_(allowed_ids)" in directions


def test_observer_student_list_is_presented_without_mutating_actions():
    template = read("frontend/templates/students/list.html")
    assert "session.user_role != 'observer'" in template
    assert "session.user_role == 'observer'" in template
    assert "session.user_role == 'super_admin'" in template


def test_all_templates_compile_and_common_dashboard_css_is_in_the_build_manifest():
    templates = ROOT / "frontend/templates"
    env = Environment(loader=FileSystemLoader(str(templates)))
    for path in templates.rglob("*.html"):
        env.get_template(path.relative_to(templates).as_posix())
    build = read("scripts/build_assets.py")
    css = ROOT / "frontend/assets/styles/shared/unified-dashboard-foundation-2026.css"
    assert css.exists()
    assert "shared/unified-dashboard-foundation-2026.css" in build


def test_observer_direction_pages_render_read_only_without_mutation_controls():
    detail = read("frontend/templates/directions/detail.html")
    questions = read("frontend/templates/directions/questions.html")
    source = read("backend/app/web_app.py")
    direction_route = source[source.index("def direction_detail(did, current_user):"):source.index('@directions_bp.route("/<int:did>/questions"')]
    questions_route = source[source.index("def manage_questions(did, current_user):"):source.index('@directions_bp.route("/<int:did>/add_student"')]
    assert "can_manage_direction=can_manage_direction" in direction_route
    assert "{% if can_manage_direction %}" in detail
    assert "can_manage_questions=can_manage_questions" in questions_route
    assert "{% if can_manage_questions %}" in questions
    assert "if not can_manage_questions" in questions_route


def test_leader_question_management_is_limited_to_assigned_direction():
    source = read("backend/app/web_app.py")
    route = source[source.index("def manage_questions(did, current_user):"):source.index('@directions_bp.route("/<int:did>/add_student"')]
    assert "current_user.role == UserRole.LEADER.value" in route
    assert "can_user_manage_direction(current_user.id, did, None)" in route
    assert "abort(403)" in route


def test_leader_event_creation_filters_and_validates_direction_scope():
    source = read("backend/app/web_app.py")
    route = source[source.index("def create_quota(current_user):"):source.index("def publish_due_quotas():")]
    assert "allowed_direction_ids = _lesson_access_scope(current_user)" in route
    assert "Direction.id.in_(allowed_direction_ids)" in route
    assert "can_user_manage_direction(current_user.id, direction_id, None)" in route
    assert "set(valid_dids) != set(dids)" in route


def test_direction_overview_does_not_load_unassigned_student_picker_data():
    source = read("backend/app/web_app.py")
    route = source[source.index("def direction_detail(did, current_user):"):source.index('@directions_bp.route("/<int:did>/questions"')]
    assert "available_students" not in route
    assert "can_manage_direction" in route
