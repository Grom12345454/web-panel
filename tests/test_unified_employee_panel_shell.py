"""The employee shell exposes direction-scoped work modules, not global admin controls."""
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]


def test_staff_sidebar_contains_workspace_people_and_direction_work_destinations():
    base = (ROOT / 'frontend/templates/shared/base.html').read_text(encoding='utf-8')
    staff_branch = base.split("{% if session.user_role == 'staff' %}", 1)[1].split("{% else %}\n            <nav class=\"sidebar-nav\" data-sidebar-nav aria-label=\"Главная навигация\">", 1)[0]
    assert 'class="sidebar-nav" data-sidebar-nav' in staff_branch
    assert staff_branch.index('Рабочий стол') < staff_branch.index('Работа совета') < staff_branch.index('Студенты и участники') < staff_branch.index('Аналитика')
    assert "url_for('admin.dashboard')" in staff_branch
    assert "url_for('admin.dashboard') }}" in base
    assert 'nav-section-work' in staff_branch
    assert 'nav-section-people' in staff_branch
    assert "url_for('staff.workspace')" not in staff_branch
    assert "url_for('admin.blocked_students')" in staff_branch
    assert "url_for('admin.leadership_public')" in staff_branch
    for allowed_link in (
        "url_for('admin.calendar')", "url_for('admin.notifications')",
        "url_for('admin.report_archive')", "url_for('orders.archive')",
        "url_for('stats.overview_statistics')",
        "url_for('admin.most_active_students')",
    ):
        assert allowed_link in staff_branch
    assert "url_for('directions.directions_list')" in staff_branch
    assert "url_for('activity_chats.index')" not in staff_branch
    assert 'Чаты направления' not in staff_branch


def test_employee_route_allowlist_is_default_deny_and_allows_scoped_work_modules():
    source = (ROOT / 'backend/app/web_app.py').read_text(encoding='utf-8')
    guard = source.split("if actor.role == UserRole.STAFF.value:", 1)[1].split("# Apply external-facing host checks", 1)[0]
    for allowed_endpoint in (
        "'admin.dashboard'", "'staff.workspace'", "'staff.students'", "'staff.update_student_profile'", "'admin.student_detail'", "'directions.directions_list'", "'staff.application_decision'", "'staff.create_lesson'",
        "'staff.create_event'", "'directions.chat_message'",
        "'admin.blocked_students'", "'admin.leadership_public'",
        "'admin.notifications'", "'admin.calendar'", "'admin.report_archive'",
        "'orders.archive'", "'activity_chats.index'", "'stats.overview_statistics'",
        "'admin.most_active_students'",
    ):
        assert allowed_endpoint in guard
    assert "if not (is_staff_module_action or is_staff_account_action or is_staff_static):" in guard
    for forbidden_prefix in (
        "path.startswith('/staff/')", "path.startswith('/notifications/')",
        "path.startswith('/directions/')", "path.startswith('/orders/')",
        "path.startswith('/activity-chats/')", "path.startswith('/stats/')",
    ):
        assert forbidden_prefix not in guard


def test_visual_theme_poll_is_explicitly_allowed_for_staff():
    source = (ROOT / 'backend/app/web_app.py').read_text(encoding='utf-8')
    guard = source.split("if actor.role == UserRole.STAFF.value:", 1)[1].split("# Apply external-facing host checks", 1)[0]
    assert "'admin.visual_theme_state'" in guard
    assert "'admin.notifications_unread'" in guard


def test_employee_home_links_to_separate_students_module_and_keeps_scope_picker():
    source = (ROOT / 'frontend/templates/staff/workspace.html').read_text(encoding='utf-8')
    students = (ROOT / 'frontend/templates/staff/students.html').read_text(encoding='utf-8')
    sidebar = (ROOT / 'frontend/templates/shared/base.html').read_text(encoding='utf-8')
    assert 'selected_direction.name' in source
    assert 'id="applications"' not in source
    assert "url_for('staff.students')" in sidebar
    assert "{% if is_chief_admin %}" in students
    assert "url_for('staff.create_student'" in students
    assert "url_for('staff.update_student_profile'" in students
    assert "url_for('admin.student_detail'" in students


def test_all_templates_compile_after_navigation_change():
    env = Environment(loader=FileSystemLoader(str(ROOT / 'frontend/templates')))
    for path in (ROOT / 'frontend/templates').rglob('*.html'):
        env.get_template(path.relative_to(ROOT / 'frontend/templates').as_posix())


def test_sidebar_has_student_notifications_and_one_filtered_calendar_entry():
    base = (ROOT / 'frontend/templates/shared/base.html').read_text(encoding='utf-8')
    calendar = (ROOT / 'frontend/templates/calendar/index.html').read_text(encoding='utf-8')
    script = (ROOT / 'frontend/assets/scripts/portal/calendar.js').read_text(encoding='utf-8')
    assert "url_for('staff.students')" in base
    assert "url_for('admin.notifications')" in base
    assert 'href="{{ url_for(\'admin.calendar\') }}"' in base
    assert "url_for('admin.calendar', kind='lesson')" not in base
    assert "url_for('admin.calendar', kind='event')" not in base
    assert 'id="calendar-type-filter"' in calendar
    assert 'data-initial-kind=' in calendar
    assert "root.dataset.initialKind" in script
    assert 'Уведомления' in base


def test_employee_legacy_site_notification_route_is_not_allowed():
    source = (ROOT / 'backend/app/web_app.py').read_text(encoding='utf-8')
    guard = source.split("if actor.role == UserRole.STAFF.value:", 1)[1].split("# Apply external-facing host checks", 1)[0]
    assert "'staff.publish_notice'" not in guard
    route_source = (ROOT / 'backend/app/services/staff_routes.py').read_text(encoding='utf-8')
    legacy = route_source.split("def publish_notice(current_user):", 1)[1]
    assert "abort(403)" in legacy
