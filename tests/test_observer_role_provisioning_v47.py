"""The global observer must be assignable from the staff accounts UI."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_staff_account_role_selector_includes_global_observer():
    template = (ROOT / "frontend/templates/staff/accounts.html").read_text(encoding="utf-8")
    routes = (ROOT / "backend/app/services/staff_routes.py").read_text(encoding="utf-8")
    assert "ACCOUNT_RANKS = {'employee_all': 'Сотрудник — все направления', 'employee': 'Сотрудник одного направления', 'observer': 'Наблюдатель'}" in routes
    assert "ranks=ACCOUNT_RANKS" in routes
    assert "{% for value,label in ranks.items() %}" in template
    assert "'Наблюдатель' if user.role == 'observer'" in template


def test_selected_observer_role_is_persisted_as_global_read_only_role():
    routes = (ROOT / "backend/app/services/staff_routes.py").read_text(encoding="utf-8")
    assert "user.role = UserRole.OBSERVER.value if rank == 'observer' else UserRole.STAFF.value" in routes
    assert "if user.role != UserRole.OBSERVER.value:" in routes
    assert "if rank == 'employee_all':" in routes
    assert 'target_direction_ids' in routes
    assert "home_direction_id = None" in routes
    assert "StaffGrant.query.filter_by(user_id=user.id).delete" in routes


def test_existing_observers_can_be_listed_edited_and_removed_by_superadmin():
    routes = (ROOT / "backend/app/services/staff_routes.py").read_text(encoding="utf-8")
    assert "User.role.in_([UserRole.STAFF.value, UserRole.OBSERVER.value])" in routes
    assert "user.role not in {UserRole.STAFF.value, UserRole.OBSERVER.value}" in routes
    assert "'observer' if user.role == UserRole.OBSERVER.value else (user.staff_rank if user.staff_rank in {'employee', 'employee_all'} else 'employee')" in routes
    assert "account.role not in {UserRole.STAFF.value, UserRole.OBSERVER.value}" in routes


def test_observer_form_disables_direction_grants_and_explains_scope():
    template = (ROOT / "frontend/templates/staff/accounts.html").read_text(encoding="utf-8")
    assert 'id="staff-observer-note" hidden' in template
    assert "const observer=rank==='observer'" in template
    assert 'el.disabled=observer||!matches' in template
    assert "Управление запрещено" in template
