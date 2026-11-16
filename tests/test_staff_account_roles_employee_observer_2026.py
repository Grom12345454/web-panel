"""The panel provisions repeatable global employees, scoped employees, and observers."""
import ast
import sqlite3
from pathlib import Path
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]


def test_staff_account_editor_exposes_three_account_modes_and_is_admin_only():
    routes = (ROOT / 'backend/app/services/staff_routes.py').read_text('utf-8')
    template = (ROOT / 'frontend/templates/staff/accounts.html').read_text('utf-8')
    assert "ACCOUNT_RANKS = {'employee_all': 'Сотрудник — все направления', 'employee': 'Сотрудник одного направления', 'observer': 'Наблюдатель'}" in routes
    assert 'if rank not in ACCOUNT_RANKS:' in routes
    assert "rank in {'observer', 'employee_all'}" in routes
    assert 'singleton_query' not in routes
    assert 'already created' not in routes
    assert "def accounts(current_user):\n    _admin()" in routes
    assert "if rank == 'employee_all':" in routes
    assert "User.role.in_([UserRole.STAFF.value, UserRole.OBSERVER.value])" in routes
    assert "UserRole.ADMIN.value if rank == 'admin'" not in routes
    assert "'head': 'Руководитель направления'" not in routes
    assert 'Сотрудники и наблюдатели' in template
    assert "{% for value,label in ranks.items() %}" in template
    Environment().parse(template)


def test_staff_access_no_longer_treats_job_title_as_permission():
    access = (ROOT / 'backend/app/services/staff_access.py').read_text('utf-8')
    assert "rank == 'employee_all'" in access
    assert 'default employee profile in every' in access
    assert "if user.staff_rank == 'head'" not in access
    assert "if user.staff_rank == 'head'" not in (ROOT / 'backend/app/services/broadcast_policy.py').read_text('utf-8')


def test_role_migration_downgrades_old_archive_admin_safely_and_removes_legacy_ranks(tmp_path):
    source = (ROOT / 'backend/app/database/helpers.py').read_text('utf-8')
    tree = ast.parse(source)
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'migrate_staff_account_roles')
    path = tmp_path / 'people.sqlite'
    with sqlite3.connect(path) as conn:
        conn.execute('''CREATE TABLE users (
            id INTEGER PRIMARY KEY, email TEXT, role TEXT, staff_rank TEXT,
            assigned_direction_id INTEGER, auth_version INTEGER)''')
        conn.execute('CREATE TABLE staff_grants (id INTEGER PRIMARY KEY, user_id INTEGER, direction_id INTEGER, section TEXT, access TEXT)')
        conn.executemany('INSERT INTO users VALUES (?, ?, ?, ?, ?, ?)', [
            (1, 'root', 'super_admin', 'employee', None, 4),
            (2, 'archive', 'admin', 'admin', 55, 7),
            (3, 'head', 'staff', 'head', 12, 3),
            (4, 'deputy', 'staff', 'deputy', 12, 1),
            (5, 'employee', 'staff', 'employee', 12, 9),
            (6, 'observer', 'observer', 'observer', None, 2),
            (7, 'employee_all', 'staff', 'employee_all', None, 6),
        ])
        conn.executemany('INSERT INTO staff_grants VALUES (?, ?, ?, ?, ?)', [
            (1, 2, 55, 'events', 'manage'),
            (2, 3, 12, 'students', 'view'),
            (3, 4, 12, 'lessons', 'manage'),
        ])
        conn.commit()

    namespace = {
        'sqlite3': sqlite3,
        '_sqlite_table_exists': lambda db, table: sqlite3.connect(db).execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone() is not None,
        '_columns': lambda conn, table: [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')],
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'helpers.py', 'exec'), namespace)
    namespace['migrate_staff_account_roles'](path)

    with sqlite3.connect(path) as conn:
        rows = {row[0]: row[1:] for row in conn.execute(
            'SELECT id, role, staff_rank, assigned_direction_id, auth_version FROM users')}
        grants = conn.execute('SELECT user_id, direction_id, section, access FROM staff_grants ORDER BY id').fetchall()
    assert rows[1] == ('super_admin', 'employee', None, 4)
    assert rows[2] == ('staff', 'employee', None, 8)
    assert rows[3] == ('staff', 'employee', 12, 4)
    assert rows[4] == ('staff', 'employee', 12, 2)
    assert rows[5] == ('staff', 'employee', 12, 9)
    assert rows[6] == ('observer', 'observer', None, 2)
    assert rows[7] == ('staff', 'employee_all', None, 6)
    assert grants == [(3, 12, 'students', 'view'), (4, 12, 'lessons', 'manage')]

    # Migration is safe to run on every startup; no second permission reset occurs.
    namespace['migrate_staff_account_roles'](path)
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT auth_version FROM users WHERE id=3').fetchone()[0] == 4


def test_only_employee_and_observer_accounts_are_authorized_for_password_rotation_and_deletion():
    routes = (ROOT / 'backend/app/services/staff_routes.py').read_text('utf-8')
    password_reset = routes[routes.index('def request_password_rotation'):routes.index("@staff_bp.post('/accounts/<int:user_id>/delete')")]
    delete = routes[routes.index('def delete_account'):routes.index("@staff_bp.get('/workspace')")]
    assert 'User.role.in_([UserRole.STAFF.value, UserRole.OBSERVER.value])' in password_reset
    assert 'target.role not in {UserRole.STAFF.value, UserRole.OBSERVER.value}' in password_reset
    assert 'account.role not in {UserRole.STAFF.value, UserRole.OBSERVER.value}' in delete
