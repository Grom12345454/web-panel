"""Single-direction employee panel and direction chat modal authorization."""
import ast
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def _top_functions(path, names):
    tree = ast.parse((ROOT / path).read_text(encoding='utf-8'))
    return [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]


class _DirectionQuery:
    def __init__(self, directions):
        self.directions = directions
        self.active_only = False

    def get(self, direction_id):
        return self.directions.get(int(direction_id))

    def filter_by(self, **kwargs):
        query = _DirectionQuery(self.directions)
        query.active_only = kwargs.get('is_archived') is False
        return query

    def all(self):
        rows = list(self.directions.values())
        return [row for row in rows if not row.is_archived] if self.active_only else rows


def _policy():
    directions = {
        12: SimpleNamespace(id=12, is_archived=False),
        99: SimpleNamespace(id=99, is_archived=False),
        100: SimpleNamespace(id=100, is_archived=True),
    }
    grant_rows = []
    class GrantQuery:
        def filter_by(self, **kwargs):
            return SimpleNamespace(first=lambda: next((grant for grant in grant_rows
                if all(getattr(grant, key, None) == value for key, value in kwargs.items())), None))
    namespace = {
        'UserRole': SimpleNamespace(
            SUPER_ADMIN=SimpleNamespace(value='super_admin'),
            STAFF=SimpleNamespace(value='staff'),
            OBSERVER=SimpleNamespace(value='observer'),
        ),
        'Direction': SimpleNamespace(query=_DirectionQuery(directions)),
        'StaffGrant': SimpleNamespace(query=GrantQuery()),
        '_grant_rows': grant_rows,
        'SECTIONS': ('students', 'applications', 'events', 'lessons', 'notifications'),
    }
    access_tree = ast.parse((ROOT / 'backend/app/services/staff_access.py').read_text(encoding='utf-8'))
    constant = next(node for node in access_tree.body if isinstance(node, ast.Assign) and
                    any(isinstance(target, ast.Name) and target.id == 'EMPLOYEE_READ_ONLY_SECTIONS'
                        for target in node.targets))
    nodes = [constant] + _top_functions('backend/app/services/staff_access.py', {'_active_direction', '_grant_access', 'allowed', 'direction_ids'})
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'staff_access.py', 'exec'), namespace)
    return namespace


def test_superadmin_is_global_even_when_a_preferred_direction_is_set():
    policy = _policy()
    admin = SimpleNamespace(role='super_admin', is_active=True, assigned_direction_id=12, grants=[])
    assert policy['allowed'](admin, 12, 'students', 'manage') is True
    assert policy['allowed'](admin, 99, 'notifications', 'manage') is True
    assert policy['allowed'](admin, 100, 'students', 'view') is False
    assert policy['direction_ids'](admin, 'students', 'manage') == {12, 99}


def test_employee_cannot_access_foreign_direction_even_if_foreign_grant_remains():
    policy = _policy()
    grants = [
        SimpleNamespace(user_id=7, direction_id=12, section='students', access='manage'),
        SimpleNamespace(user_id=7, direction_id=99, section='students', access='manage'),
        SimpleNamespace(user_id=7, direction_id=12, section='notifications', access='view'),
    ]
    policy['_grant_rows'].extend(grants)
    employee = SimpleNamespace(id=7, role='staff', is_active=True, staff_rank='employee',
                                assigned_direction_id=12, grants=grants)
    assert policy['allowed'](employee, 12, 'students', 'manage') is True
    assert policy['allowed'](employee, 99, 'students', 'view') is False
    assert policy['allowed'](employee, 12, 'notifications', 'manage') is False
    assert policy['direction_ids'](employee, 'students', 'view') == {12}
    assert policy['direction_ids'](employee, 'notifications', 'manage') == set()


def test_observer_is_global_read_only_and_inactive_users_have_no_access():
    policy = _policy()
    observer = SimpleNamespace(role='observer', is_active=True, assigned_direction_id=None, grants=[])
    assert policy['allowed'](observer, 99, 'students', 'view') is True
    assert policy['allowed'](observer, 99, 'students', 'manage') is False
    assert policy['direction_ids'](observer, 'students', 'view') == {12, 99}
    observer.is_active = False
    assert policy['allowed'](observer, 12, 'students', 'view') is False
    assert policy['direction_ids'](observer, 'students', 'view') == set()


def test_account_provisioning_defaults_new_employee_grants_only_for_home_direction():
    routes = (ROOT / 'backend/app/services/staff_routes.py').read_text(encoding='utf-8')
    template = (ROOT / 'frontend/templates/staff/accounts.html').read_text(encoding='utf-8')
    form = routes[routes.index('def _form_account('):routes.index('@staff_bp.route(\'/accounts\'')]
    assert "if rank == 'employee'" in form
    assert "field = f'grant_{home_direction_id}_{section}'" in form
    assert "DEFAULT_EMPLOYEE_GRANTS.get(section, 'none') if is_new_account else 'none'" in form
    assert 'card.hidden=observer||!matches' in template
    assert 'el.disabled=observer||!matches' in template
    assert "home_direction_id').addEventListener('change'" in template


def test_staff_chat_modal_and_post_route_require_chat_management_permission():
    web = (ROOT / 'backend/app/web_app.py').read_text(encoding='utf-8')
    tree = ast.parse(web)
    chat = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'chat_message')
    chat_source = ast.get_source_segment(web, chat)
    assert "staff_allowed(current_user, did, 'chats', 'manage')" in chat_source
    assert 'telegram_targets_for_directions([did])' in chat_source
    assert 'queue_social_chat_announcement([did]' in chat_source
    assert 'request.form.get("chat_id")' not in chat_source
    detail = (ROOT / 'frontend/templates/directions/detail.html').read_text(encoding='utf-8')
    assert 'data-open-direction-broadcast' in detail
    assert 'id="direction-broadcast-dialog"' in detail
    assert "url_for('directions.chat_message', did=direction.id)" in detail
    assert "{% if can_send_direction_chat %}" in detail


def test_staff_direction_routes_and_template_are_scoped_to_assigned_direction():
    web = (ROOT / 'backend/app/web_app.py').read_text(encoding='utf-8')
    guard = web[web.index('def _employee_direction_scope_guard'):web.index('stats_bp = Blueprint')]
    assert "user.role != UserRole.STAFF.value" in guard
    assert "int(user.assigned_direction_id) != int(direction_id)" in guard
    assert "'directions.chat_message': 'chats'" in guard
    detail = (ROOT / 'frontend/templates/directions/detail.html').read_text(encoding='utf-8')
    assert '{% if can_send_direction_chat %}' in detail


def test_dashboard_employee_branch_is_explicitly_single_direction_and_admin_global():
    web = (ROOT / 'backend/app/web_app.py').read_text(encoding='utf-8')
    tree = ast.parse(web)
    dashboard = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'dashboard')
    source = ast.get_source_segment(web, dashboard)
    admin_branch = source[source.index('if role == UserRole.SUPER_ADMIN.value:'):source.index('elif role == UserRole.STAFF.value:')]
    staff_start = source.index('elif role == UserRole.STAFF.value:')
    observer_start = source.index('elif role == UserRole.OBSERVER.value:', staff_start)
    staff_branch = source[staff_start:observer_start]
    assert 'ПОЛНЫЙ ДОСТУП' in admin_branch
    assert 'По всему сайту' in admin_branch
    assert 'ОДНО НАЗНАЧЕННОЕ НАПРАВЛЕНИЕ' in staff_branch
    assert 'только этим направлением' in staff_branch


def test_calendar_and_creation_routes_enforce_employee_grants_without_restricting_admin():
    web = (ROOT / 'backend/app/web_app.py').read_text(encoding='utf-8')
    calendar = web[web.index('@admin_bp.route("/calendar")'):web.index('@admin_bp.route("/student-app/design"') ]
    create_quota = web[web.index('def create_quota(current_user):'):web.index('def publish_due_quotas():')]
    assert "staff_direction_ids(current_user, 'events', 'view')" in calendar
    assert "staff_direction_ids(current_user, 'lessons', 'view')" in calendar
    assert "staff_allowed(current_user, lesson.direction_id, 'lessons', 'manage')" in calendar
    assert "staff_direction_ids(current_user, 'events', 'manage')" in create_quota
    assert "can_assign_event_chats = current_user.role == UserRole.SUPER_ADMIN.value" in create_quota


def test_main_admin_can_manage_shared_direction_and_event_chat_configuration():
    chat = (ROOT / 'backend/app/services/activity_chats.py').read_text(encoding='utf-8')
    assert 'can_manage_shared_rooms = is_admin' in chat
    assert "if current_user.role != UserRole.SUPER_ADMIN.value:" in chat
    assert 'not getattr(current_user, \'assigned_direction_id\'' not in chat
