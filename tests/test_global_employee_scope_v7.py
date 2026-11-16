"""Regression coverage for the simplified staff-account model (v7)."""
import ast
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


class _DirectionQuery:
    def __init__(self, rows):
        self.rows = rows

    def get(self, direction_id):
        return next((row for row in self.rows if row.id == direction_id), None)

    def filter_by(self, **kwargs):
        rows = self.rows
        for key, value in kwargs.items():
            rows = [row for row in rows if getattr(row, key) == value]
        return _DirectionQuery(rows)

    def all(self):
        return list(self.rows)


class _GrantQuery:
    def __init__(self, grants):
        self.grants = grants
        self.filters = {}

    def filter_by(self, **kwargs):
        self.filters.update(kwargs)
        return self

    def first(self):
        value = self.grants.get((self.filters['user_id'], self.filters['direction_id'], self.filters['section']))
        return SimpleNamespace(access=value) if value else None


def _load_access_helpers(grants):
    source = (ROOT / 'backend/app/services/staff_access.py').read_text('utf-8')
    tree = ast.parse(source)
    names = {'_active_direction', '_grant_access', 'allowed', 'direction_ids'}
    body = [node for node in tree.body if
            (isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id in {'SECTIONS', 'EMPLOYEE_READ_ONLY_SECTIONS', 'DEFAULT_EMPLOYEE_GRANTS'}
                for target in node.targets
            )) or (isinstance(node, ast.FunctionDef) and node.name in names)]

    directions = [
        SimpleNamespace(id=1, is_archived=False),
        SimpleNamespace(id=2, is_archived=False),
        SimpleNamespace(id=3, is_archived=False),
        SimpleNamespace(id=4, is_archived=True),
    ]

    class Direction:
        query = _DirectionQuery(directions)

    class StaffGrant:
        query = _GrantQuery(grants)

    namespace = {
        'Direction': Direction,
        'StaffGrant': StaffGrant,
        'UserRole': SimpleNamespace(SUPER_ADMIN=SimpleNamespace(value='super_admin'), OBSERVER=SimpleNamespace(value='observer'), STAFF=SimpleNamespace(value='staff')),
    }
    exec(compile(ast.Module(body=body, type_ignores=[]), 'staff_access.py', 'exec'), namespace)
    return namespace


def test_global_employee_is_scoped_by_explicit_grants_per_direction():
    helpers = _load_access_helpers({
        (10, 1, 'students'): 'manage',
        (10, 1, 'report_archive'): 'view',
        (10, 1, 'orders'): 'view',
        (10, 1, 'chats'): 'none',
        (10, 2, 'students'): 'view',
        (10, 2, 'statistics'): 'view',
        (10, 2, 'chats'): 'view',
    })
    global_employee = SimpleNamespace(
        id=10, role='staff', staff_rank='employee_all', assigned_direction_id=None, is_active=True,
    )
    assert helpers['allowed'](global_employee, 1, 'students', 'manage') is True
    assert helpers['allowed'](global_employee, 2, 'students', 'view') is True
    assert helpers['allowed'](global_employee, 2, 'students', 'manage') is False
    assert helpers['allowed'](global_employee, 3, 'students', 'manage') is True  # newly created direction inherits defaults
    assert helpers['direction_ids'](global_employee, 'students', 'view') == {1, 2, 3}
    assert helpers['direction_ids'](global_employee, 'statistics', 'manage') == {1, 3}
    assert helpers['allowed'](global_employee, 1, 'chats', 'view') is False  # saved 'none' overrides default
    assert helpers['allowed'](global_employee, 1, 'report_archive', 'manage') is False
    assert helpers['allowed'](global_employee, 1, 'orders', 'manage') is False


def test_direction_employee_cannot_use_grants_for_another_direction_and_observer_is_read_only():
    helpers = _load_access_helpers({
        (11, 1, 'students'): 'manage',
        (11, 2, 'students'): 'manage',  # deliberately invalid extra row must not widen scope
    })
    scoped_employee = SimpleNamespace(
        id=11, role='staff', staff_rank='employee', assigned_direction_id=1, is_active=True,
    )
    assert helpers['allowed'](scoped_employee, 1, 'students', 'manage') is True
    assert helpers['allowed'](scoped_employee, 2, 'students', 'manage') is False
    assert helpers['direction_ids'](scoped_employee, 'students', 'view') == {1}

    observer = SimpleNamespace(id=12, role='observer', staff_rank='observer', assigned_direction_id=None, is_active=True)
    assert helpers['direction_ids'](observer, 'students', 'view') == {1, 2, 3}
    assert helpers['direction_ids'](observer, 'students', 'manage') == set()


def test_superadmin_panel_is_the_only_account_provisioning_path_and_observer_is_not_bootstrapped():
    routes = (ROOT / 'backend/app/services/staff_routes.py').read_text('utf-8')
    helpers = (ROOT / 'backend/app/database/helpers.py').read_text('utf-8')
    env_example = (ROOT / '.env.example').read_text('utf-8')
    assert "def accounts(current_user):\n    _admin()" in routes
    assert "def _admin():" in routes and 'UserRole.SUPER_ADMIN.value' in routes
    assert "rank in {'observer', 'employee_all'}" in routes
    assert 'singleton_query' not in routes
    assert "'employee_all':" in routes and "'employee':" in routes and "'observer':" in routes
    panel_bootstrap = helpers[helpers.index('panel_users = ['):helpers.index('# Explicit administrator bot binding')]
    assert "settings.ADMIN_USERNAME" in panel_bootstrap
    assert 'OBSERVER_PASSWORD' not in helpers
    assert 'OBSERVER_USERNAME' not in env_example and 'OBSERVER_PASSWORD' not in env_example
