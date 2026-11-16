"""Main administrator is global; ordinary employees are single-direction scoped."""
import ast
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding='utf-8')


def test_all_supported_panel_roles_can_login_without_telegram_binding_or_bot_token():
    source = read('backend/app/web_app.py')
    login = source[source.index('def login('):source.index('def verify_otp(')]
    assert 'if not user.tg_id or int(user.tg_id) <= 0 or not settings.BOT_TOKEN:' in login
    for role in ('SUPER_ADMIN', 'STAFF', 'OBSERVER', 'LEADER'):
        assert f'UserRole.{role}.value' in login
    assert 'Для этой учётной записи требуется действующая Telegram-привязка.' not in login
    password_fallback = login.split('if not user.tg_id or int(user.tg_id) <= 0 or not settings.BOT_TOKEN:', 1)[1]
    assert "session['user_id'] = user.id" in password_fallback
    assert "return redirect(url_for('admin.dashboard'))" in password_fallback


def test_linked_accounts_keep_telegram_otp_as_an_additional_login_step():
    source = read('backend/app/web_app.py')
    login = source[source.index('def login('):source.index('def verify_otp(')]
    assert "'chat_id': int(user.tg_id)" in login
    assert "redirect(url_for('auth.verify_otp'), code=303)" in login


def test_superadmin_visibility_is_global_and_does_not_depend_on_home_direction():
    source = read('backend/app/web_app.py')
    helper = source[source.index('def _staff_visible_direction_ids'):source.index('def _quota_direction_scope_ids')]
    assert 'if user.role == UserRole.SUPER_ADMIN.value:' in helper
    assert 'return {direction.id for direction in Direction.query.all()}' in helper
    admin_branch = helper.split('if user.role == UserRole.SUPER_ADMIN.value:', 1)[1].split('from services.staff_access', 1)[0]
    assert 'return {direction.id for direction in Direction.query.all()}' in admin_branch


def test_dashboard_is_site_wide_for_superadmin_and_single_direction_for_employee():
    source = read('backend/app/web_app.py')
    routes = read('backend/app/services/staff_routes.py')
    assert 'scope_ids = _staff_visible_direction_ids(current_user)' in source
    tree = ast.parse(source)
    dashboard = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'dashboard')
    dashboard_source = ast.get_source_segment(source, dashboard)
    staff_start = dashboard_source.index('elif role == UserRole.STAFF.value:')
    observer_start = dashboard_source.index('elif role == UserRole.OBSERVER.value:', staff_start)
    staff_branch = dashboard_source[staff_start:observer_start]
    assert 'СОТРУДНИК · {home_name.upper()}' in staff_branch
    assert 'СОТРУДНИК · НАПРАВЛЕНИЕ НЕ НАЗНАЧЕНО' in staff_branch
    assert 'Все данные и действия ограничены этим направлением и выданными разрешениями.' in staff_branch
    workspace = routes[routes.index('def workspace('):routes.index("@staff_bp.post('/applications")]
    assert 'direction_ids(current_user, section, \'view\')' in workspace
    assert 'scoped_events' not in workspace


def test_employee_route_guards_never_narrow_superadmin():
    source = read('backend/app/web_app.py')
    quota_guard = source[source.index('def _employee_quota_scope_guard'):source.index('def _employee_direction_scope_guard')]
    direction_guard = source[source.index('def _employee_direction_scope_guard'):source.index('stats_bp = Blueprint')]
    assert "user.role != UserRole.STAFF.value" in quota_guard
    assert "user.role != UserRole.STAFF.value" in direction_guard
    assert "abort(403)" in quota_guard
    assert "abort(404)" in direction_guard
    assert "staff_direction_ids(user, 'events', level)" in quota_guard
    assert "staff_allowed(user, direction_id, section, 'manage')" in direction_guard
    assert "staff_allowed(user, direction_id, section, 'view')" in direction_guard


def test_main_admin_can_manage_all_directions_chats_and_official_documents():
    applications = read('backend/app/services/applications.py')
    chat = read('backend/app/services/activity_chats.py')
    orders = read('backend/app/services/orders.py')
    policy = read('backend/app/services/broadcast_policy.py')
    assert 'if user.role == UserRole.SUPER_ADMIN.value:' in applications
    assert 'return kind == \'event\'' in chat
    assert 'can_manage_shared_rooms = is_admin' in chat
    assert 'if user.role == UserRole.SUPER_ADMIN.value:' in orders
    assert 'return None' in policy[policy.index('def broadcast_direction_ids'):policy.index('def authorize_broadcast')]
    assert 'home_direction_id' not in policy[policy.index('def broadcast_direction_ids'):policy.index('def authorize_broadcast')].split('if user.role == UserRole.SUPER_ADMIN.value:', 1)[1].split('if user.role != UserRole.STAFF.value:', 1)[0]


def test_report_archive_is_global_for_superadmin_including_legacy_and_archived_reports():
    source = read('backend/app/web_app.py')
    section = source[source.index('def _report_archive_can_view'):source.index('def _report_archive_file')]
    assert "if role == UserRole.SUPER_ADMIN.value:" in section
    assert 'return True' in section.split("if role == UserRole.SUPER_ADMIN.value:", 1)[1].split('if role == UserRole.OBSERVER.value:', 1)[0]
    assert 'query = query' in source[source.index('def report_archive('):source.index('def report_archive_download(')]


def test_employee_provisioning_stores_permissions_only_for_one_assigned_direction():
    routes = read('backend/app/services/staff_routes.py')
    template = read('frontend/templates/staff/accounts.html')
    form = routes[routes.index('def _form_account('):routes.index('@staff_bp.route(\'/accounts\'')]
    assert "rank == 'employee'" in form
    assert 'Для сотрудника направления выберите одно действующее направление.' in form
    assert "for section in SECTIONS:" in form
    assert "field = f'grant_{direction_id}_{section}'" in form
    assert "target_direction_ids = [home_direction_id]" in form
    assert "rank == 'employee_all'" in form
    assert 'card.hidden=observer||!matches' in template
    assert "data-direction-id=\"{{direction.id}}\"" in template


def test_employee_chat_scope_is_checked_before_event_leader_shortcut():
    source = read('backend/app/services/activity_chats.py')
    body = source[source.index('def may_write('):source.index('def may_write_room(')]
    assert body.index("if user.role == UserRole.STAFF.value:") < body.index('appointed = EventLeader.query')
    assert "_event_direction_ids(target.id) == {int(home_id)}" in body
    assert "allowed(user, int(home_id), 'events', 'manage')" in body
