"""Staff modules are open only through direction-scoped handlers."""
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]


def test_staff_sidebar_exposes_requested_work_modules_and_analytics():
    source = (ROOT / 'frontend/templates/shared/base.html').read_text(encoding='utf-8')
    staff_branch = source.split("{% if session.user_role == 'staff' %}", 1)[1].split(
        "{% else %}\n            <nav class=\"sidebar-nav\" data-sidebar-nav aria-label=\"Главная навигация\">", 1
    )[0]
    for expected in (
        "url_for('admin.calendar')", "url_for('admin.notifications')",
        "url_for('admin.report_archive')", "url_for('orders.archive')",
        "url_for('stats.overview_statistics')",
        "url_for('admin.most_active_students')", "Заблокированные",
        "Руководство студсовета", "Направления",
    ):
        assert expected in staff_branch
    for forbidden in (
        'staff.accounts', 'admin.system_maintenance', 'admin.user_activity_log',
        "url_for('activity_chats.index')", 'Чаты направления',
        'staff_nav_access.activity_chats',
    ):
        assert forbidden not in staff_branch


def test_staff_endpoint_allowlist_includes_only_scoped_modules_and_actions():
    source = (ROOT / 'backend/app/web_app.py').read_text(encoding='utf-8')
    guard = source.split("if actor.role == UserRole.STAFF.value:", 1)[1].split(
        '# Apply external-facing host checks', 1
    )[0]
    for endpoint in (
        "'admin.calendar'", "'admin.notifications'", "'admin.notifications_publish'",
        "'admin.report_archive'", "'orders.archive'", "'orders.download_order'",
        "'activity_chats.index'", "'directions.direction_detail'",
        "'directions.connect_chat_candidate'", "'directions.connect_social_chat'",
        "'directions.remove_social_chat'", "'directions.add_chat'",
        "'directions.chat_audience'", "'directions.delete_chat'", "'directions.test_chat'",
        "'lessons.create_lesson'", "'quotas.create_quota'", "'stats.overview_statistics'",
        "'admin.most_active_students'",
    ):
        assert endpoint in guard
    assert "'activity_chats.post_message'" not in guard
    assert 'request.endpoint or' in guard
    assert 'staff_endpoint_methods.get(endpoint, set())' in guard
    assert "path.startswith('/orders/')" not in guard
    assert "path.startswith('/activity-chats/')" not in guard


def test_staff_navigation_is_conditioned_on_direction_permissions():
    source = (ROOT / 'backend/app/web_app.py').read_text(encoding='utf-8')
    block = source.split("if nav_user and nav_user.is_active and nav_user.role == UserRole.STAFF.value:", 1)[1].split(
        "elif nav_user and nav_user.is_active and nav_user.role == UserRole.SUPER_ADMIN.value:", 1
    )[0]
    assert "staff_direction_ids(nav_user, section, 'view')" in block
    assert "for section in ('students', 'applications', 'events', 'lessons', 'notifications'):" in block
    assert "staff_nav_access['report_archive'] = bool(staff_direction_ids(nav_user, 'report_archive', 'view'))" in block


def test_all_templates_compile():
    env = Environment(loader=FileSystemLoader(str(ROOT / 'frontend/templates')))
    for path in (ROOT / 'frontend/templates').rglob('*.html'):
        env.get_template(path.relative_to(ROOT / 'frontend/templates').as_posix())


def test_staff_calendar_controls_use_direction_scoped_manage_permission():
    source = (ROOT / 'backend/app/web_app.py').read_text(encoding='utf-8')
    calendar = source.split('def calendar(current_user):', 1)[1].split('@admin_bp.route("/student-app/design"', 1)[0]
    assert "event_manage_ids = set(staff_direction_ids(current_user, 'events', 'manage'))" in calendar
    assert 'can_manage_events = bool(event_manage_ids)' in calendar
    assert 'event_scope is not None and (not visible or set(visible) != set(dids))' in calendar
