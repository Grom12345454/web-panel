"""Access policy for uploading official reports/orders (v20)."""
import ast
from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_policy(allowed_result=True):
    source = ast.parse((ROOT / "backend/app/services/orders.py").read_text("utf8"))
    names = {"_event_direction_ids", "_staff_is_head", "may_upload"}
    selected = [node for node in source.body
                if isinstance(node, ast.FunctionDef) and node.name in names]
    roles = SimpleNamespace(SUPER_ADMIN=SimpleNamespace(value="super_admin"),
                            STAFF=SimpleNamespace(value="staff"),
                            LEADER=SimpleNamespace(value="leader"))
    class FakeColumn:
        def __eq__(self, _other): return True
        def is_not(self, _other): return True

    class FakeQuery:
        def with_entities(self, *_args): return self
        def filter(self, *_args): return self
        def all(self): return []

    event_chat = SimpleNamespace(
        query=FakeQuery(), quota_id=FakeColumn(), direction_id=FakeColumn()
    )
    namespace = {
        "UserRole": roles,
        "EventQuotaChat": event_chat,
        "get_quota_direction_ids": lambda _quota_id: [7],
        "can_user_manage_direction": lambda user_id, direction_id, education: bool(user_can_lead.get(user_id, False)),
    }
    staff_access = ModuleType("services.staff_access")
    staff_access.allowed = lambda user, direction_id, section, level: (
        allowed_result and section == "events" and level == "manage"
        and bool(getattr(user, "can_manage_events", False))
    )
    # The dynamic import in _staff_is_head must resolve to the isolated policy stub.
    module = ModuleType("services")
    module.__path__ = []
    user_can_lead.clear()
    exec(compile(ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[])),
                 "orders_policy_test", "exec"), namespace)
    policy = namespace["may_upload"]
    def invoke(*args, **kwargs):
        with patch.dict(sys.modules, {"services": module, "services.staff_access": staff_access}):
            return policy(*args, **kwargs)
    return invoke


user_can_lead = {}


def test_only_superadmin_or_authorized_leader_can_upload_and_employees_are_view_only():
    may_upload = load_policy()
    target = SimpleNamespace(id=33)
    # Main administrator has site-wide authority, regardless of the optional
    # default direction saved for navigation.
    assert may_upload(SimpleNamespace(role="super_admin", is_active=True, assigned_direction_id=7), "event", target)
    assert may_upload(SimpleNamespace(role="super_admin", is_active=True, assigned_direction_id=8), "event", target)
    assert may_upload(SimpleNamespace(role="super_admin", is_active=True, assigned_direction_id=None), "event", target)
    staff_manager = SimpleNamespace(id=4, role="staff", is_active=True, assigned_direction_id=7, can_manage_events=True)
    staff_view_only = SimpleNamespace(id=5, role="staff", is_active=True, assigned_direction_id=7, can_manage_events=False)
    # Orders are read/download-only even when an employee may manage events.
    assert not may_upload(staff_manager, "event", target)
    assert not may_upload(staff_view_only, "event", target)
    user_can_lead[6] = True
    leader = SimpleNamespace(id=6, role="leader", is_active=True)
    assert may_upload(leader, "event", target)


def test_students_observers_and_inactive_accounts_cannot_upload_even_if_event_leader():
    may_upload = load_policy()
    target = SimpleNamespace(id=33)
    # A student being appointed as EventLeader is not a staff-panel permission.
    for role in ("student", "observer", "user", None):
        user = SimpleNamespace(id=9, role=role, is_active=True, student_id=99, tg_id="123")
        assert not may_upload(user, "event", target)
    inactive_staff = SimpleNamespace(id=10, role="staff", is_active=False, can_manage_events=True)
    assert not may_upload(inactive_staff, "event", target)
