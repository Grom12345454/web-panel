"""Regression coverage for v77 calendar performance and staff deletion rules."""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]


def _function(source: str, name: str) -> str:
    tree = ast.parse(source)
    node = next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    return ast.get_source_segment(source, node)


def test_calendar_bulk_loads_event_relations_and_reuses_lesson_scope():
    source = (ROOT / "backend/app/web_app.py").read_text("utf-8")
    route = source[source.index('@admin_bp.route("/calendar")'):source.index('@admin_bp.route("/student-app/design"', source.index('@admin_bp.route("/calendar")'))]
    assert "selectinload(EventQuota.days)" in route
    assert "QuotaDirection.quota_id.in_(quota_ids)" in route
    assert "EventQuotaChat.quota_id.in_(quota_ids)" in route
    assert "get_quota_direction_ids(quota.id)" not in route
    assert "EventQuotaChat.query.filter_by(quota_id=quota.id)" not in route
    assert "scope = (lesson_allowed_ids if current_user.role in {UserRole.OBSERVER.value, UserRole.STAFF.value}" in route
    assert "else _lesson_access_scope(current_user))" in route
    assert "staff_allowed(current_user, lesson.direction_id, 'lessons', 'manage')" in route
    assert "QuotaDirection.quota_id.in_(quota_ids)" in route


def test_staff_workspace_loads_student_profiles_in_bulk():
    source = (ROOT / "backend/app/services/staff_routes.py").read_text("utf-8")
    workspace = _function(source, "workspace")
    assert "student_directions.select()" in workspace
    assert "Student.id.in_(student_ids)" in workspace
    assert "students_by_id.get(item.student_id)" in workspace
    assert "Student.query.get(item.student_id)" not in workspace
    assert "selectinload(EventQuota.days)" in workspace


def test_event_delete_is_server_guarded_by_full_scope_status_and_date():
    source = (ROOT / "backend/app/services/staff_routes.py").read_text("utf-8")
    delete = _function(source, "delete_event")
    assert "allowed(current_user, direction_id, 'events', 'manage')" in delete
    assert "if not direction_ids_for_event" in delete
    assert "quota.is_closed or quota.closed_at" in delete
    assert "not event_days or any(day.date.date() < today for day in event_days)" in delete
    assert "today = datetime.now().date()" in delete
    assert "close_activity_chat('event', quota_id, commit=False)" in delete
    assert "DayParticipation.query" in delete and "EventDay.query" in delete
    assert "BotDeliveryJob.status: 'cancelled'" in delete
    assert "db.session.rollback()" in delete


def test_lesson_delete_is_server_guarded_and_cancels_queued_notices():
    source = (ROOT / "backend/app/services/staff_routes.py").read_text("utf-8")
    delete = _function(source, "delete_lesson")
    assert "allowed(current_user, direction_id, 'lessons', 'manage')" in delete
    assert "BotDeliveryJob.status: 'cancelled'" in delete
    assert "record_activity('lesson_deleted'" in delete
    assert "db.session.delete(lesson)" in delete


def test_staff_template_uses_post_csrf_and_confirms_destructive_actions():
    template = (ROOT / "frontend/templates/staff/workspace.html").read_text("utf-8")
    assert "staff.delete_lesson" in template
    assert "staff.delete_event" in template
    assert 'name="csrf_token"' in template
    assert 'data-confirm="Удалить мероприятие' in template
    assert 'data-confirm="Удалить занятие' in template
    assert "item.id in deletable_event_ids" in template


def test_activity_chat_close_can_join_event_deletion_transaction():
    source = (ROOT / "backend/app/services/activity_chats.py").read_text("utf-8")
    close = _function(source, "close_activity_chat")
    assert "def close_activity_chat(kind, activity_id, *, commit=True)" in close
    assert "if added and commit" in close
