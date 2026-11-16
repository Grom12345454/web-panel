"""Observer role gets all operational read scopes, never management rights."""
import ast
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


class _DirectionQuery:
    rows = [SimpleNamespace(id=1, is_archived=False),
            SimpleNamespace(id=2, is_archived=False),
            SimpleNamespace(id=3, is_archived=True)]

    @classmethod
    def all(cls):
        return list(cls.rows)

    @classmethod
    def get(cls, direction_id):
        return next((row for row in cls.rows if row.id == direction_id), None)

    @classmethod
    def filter_by(cls, **kwargs):
        active_only = kwargs.get("is_archived") is False
        return SimpleNamespace(all=lambda: [row for row in cls.rows
                                            if not active_only or not row.is_archived])


class _Direction:
    query = _DirectionQuery


_ROLES = SimpleNamespace(
    SUPER_ADMIN=SimpleNamespace(value="super_admin"),
    STAFF=SimpleNamespace(value="staff"),
    LEADER=SimpleNamespace(value="leader"),
    OBSERVER=SimpleNamespace(value="observer"),
)


def _load_access_functions():
    tree = ast.parse((ROOT / "backend/app/services/staff_access.py").read_text(encoding="utf-8"))
    wanted = {"_active_direction", "allowed", "direction_ids"}
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    namespace = {"UserRole": _ROLES, "Direction": _Direction,
                 "SECTIONS": ("students", "applications", "events", "lessons", "notifications")}
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])),
                 "staff_access_policy", "exec"), namespace)
    return namespace["allowed"], namespace["direction_ids"]


def test_observer_can_view_every_operational_section_in_every_active_direction():
    allowed, _ = _load_access_functions()
    observer = SimpleNamespace(role="observer", is_active=True, grants=[],
                               staff_rank=None, assigned_direction_id=None)
    for section in ("students", "applications", "events", "lessons", "notifications"):
        assert allowed(observer, 1, section, "view") is True
        assert allowed(observer, 2, section, "view") is True
        assert allowed(observer, 3, section, "view") is False  # archived direction


def test_observer_never_receives_manage_access_or_unknown_sections():
    allowed, _ = _load_access_functions()
    observer = SimpleNamespace(role="observer", is_active=True, grants=[],
                               staff_rank=None, assigned_direction_id=None)
    for section in ("students", "applications", "events", "lessons", "notifications"):
        assert allowed(observer, 1, section, "manage") is False
    assert allowed(observer, 1, "system_maintenance", "view") is False
    assert allowed(observer, None, "events", "view") is False
    observer.is_active = False
    assert allowed(observer, 1, "events", "view") is False


def test_observer_view_scope_is_global_but_manage_scope_is_empty():
    _, direction_ids = _load_access_functions()
    observer = SimpleNamespace(role="observer", is_active=True, grants=[],
                               staff_rank=None, assigned_direction_id=None)
    assert direction_ids(observer, "students", "view") == {1, 2}
    assert direction_ids(observer, "events", "manage") == set()
    assert direction_ids(observer, "system_maintenance", "view") == set()


def test_observer_routes_keep_documents_readable_but_not_uploadable():
    orders = (ROOT / "backend/app/services/orders.py").read_text(encoding="utf-8")
    assert "UserRole.OBSERVER.value" in orders[orders.index("def archive("):orders.index("def upload_order(")]
    assert "def may_view_order" in orders
    assert "may_view_order(current_user, item.target_kind, target)" in orders
    assert "may_upload(current_user, kind, target)" in orders[orders.index("def upload_order("):orders.index("def retry_order(")]


def test_observer_can_open_chat_directory_without_write_controls():
    chats = (ROOT / "backend/app/services/activity_chats.py").read_text(encoding="utf-8")
    template = (ROOT / "frontend/templates/activity/chats.html").read_text(encoding="utf-8")
    route = chats[chats.index("def index(current_user):"):chats.index("@activity_chat_bp.post('/activity-chats/add')")]
    assert "UserRole.OBSERVER.value" in route
    assert "if is_observer:" in route and "if room.active" in route
    assert "{% if not is_observer %}<form method=\"post\"" in template


def test_all_observer_data_mutations_are_blocked_at_request_guard():
    app = (ROOT / "backend/app/web_app.py").read_text(encoding="utf-8")
    guard = app[app.index("def login_required(f):"):app.index("def super_admin_required(f):")]
    assert "user.role == UserRole.OBSERVER.value" in guard
    assert "request.method not in {\"GET\", \"HEAD\", \"OPTIONS\"}" in guard
    assert "OBSERVER_SAFE_POST_ENDPOINTS" in guard
    assert '"auth.logout", "auth.change_password"' in app


def test_observer_controls_are_hidden_but_notification_receipts_remain_available():
    css = (ROOT / "frontend/assets/styles/shared/observer-readonly-v46.css").read_text(encoding="utf-8")
    assert 'form[method="post" i]' in css
    assert ':not([data-notification-read])' in css
    assert 'body.role-observer [data-calendar-create-event]' in css
    base = (ROOT / "frontend/templates/shared/base.html").read_text(encoding="utf-8")
    assert 'session.user_role == \'observer\'' in base
    assert "Режим просмотра" in base


def test_observer_gets_a_separate_read_only_student_profile_and_questionnaire_navigation():
    app = (ROOT / "backend/app/web_app.py").read_text(encoding="utf-8")
    route = app[app.index('@admin_bp.route("/students/<int:sid>", methods=["GET"]'):app.index('@admin_bp.route("/students/<int:sid>/edit"')]
    assert 'endpoint="student_detail"' in route
    assert 'render_template("students/view.html"' in route
    view = (ROOT / "frontend/templates/students/view.html").read_text(encoding="utf-8")
    assert "Профиль студента" in view and "Направления" in view
    assert '<form' not in view.lower() and 'method="post"' not in view.lower()
    list_template = (ROOT / "frontend/templates/students/list.html").read_text(encoding="utf-8")
    assert "admin.student_detail" in list_template and "Просмотреть" in list_template
    css = (ROOT / "frontend/assets/styles/shared/observer-readonly-v46.css").read_text(encoding="utf-8")
    assert 'a[href*="/questions"]' not in css  # questionnaire contents remain readable
