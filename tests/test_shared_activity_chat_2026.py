"""Persistent-room regression tests; Bot API delivery needs live credentials."""
import ast
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def read(name):
    return (ROOT / name).read_text(encoding='utf-8')


def function(name):
    tree = ast.parse(read('backend/app/services/activity_chats.py'))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    ctx = {}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), '<test>', 'exec'), ctx)
    return ctx[name]


def test_no_activity_binding_and_permanent_room_list():
    model = read('backend/app/database/activity_chats.py')
    view = read('frontend/templates/activity/chats.html')
    service = read('backend/app/services/activity_chats.py')
    assert 'class SharedActivityChat' in model
    shared = model.split('class SharedActivityChat')[1]
    assert 'activity_id' not in shared and 'audience' in shared
    assert "@activity_chat_bp.post('/activity-chats/add')" in service
    assert "candidate.chat_type not in {'group', 'supergroup'}" in service
    assert "'creates_join_request': True" in service
    assert 'Добавленные чаты' in view and '{% for room in rooms %}' in view
    assert 'name="target_id"' not in view and 'name="audience"' in view
    assert "url_for('activity_chats.add_room')" in view


def test_closing_one_activity_never_closes_permanent_group():
    assert function('close_activity_chat')('science', 24) == 0
    assert function('close_activity_chat')('event', 55) == 0
    service = read('backend/app/services/activity_chats.py')
    assert 'room.active = False' in service  # admin-only disable operation
    assert "@activity_chat_bp.post('/activity-chats/<int:chat_id>/deactivate')" in service
    assert "@activity_chat_bp.post('/activity-chats/<int:chat_id>/activate')" in service
    assert "telegram_api('revokeChatInviteLink'" in service
    assert 'room.active = False' not in service.split('def close_activity_chat')[1].split('def process_chat_removals')[0]


def test_old_chat_links_migrate_and_removals_cancelled():
    migration = read('backend/app/database/helpers.py')
    assert 'for legacy_chat in ActivityChat.query.all()' in migration
    assert 'SharedActivityChat(chat_id=legacy_chat.chat_id' not in migration or 'db.session.add(SharedActivityChat' in migration
    assert "ActivityChatRemoval.status: 'cancelled'" in migration
    assert 'SharedActivityChat.query' in migration
    assert 'SharedActivityChat.query' in read('backend/app/handlers/telegram_discovery.py')
    assert 'student_has_audience(student, room.audience)' in read('backend/app/handlers/telegram_discovery.py')
    assert "permanent_ids = [r.chat_id for r in SharedActivityChat.query.all()]" in read('backend/app/services/activity_chats.py')


def test_registration_and_student_app_return_same_permanent_group():
    service = read('backend/app/services/activity_chats.py')
    assert "SharedActivityChat.audience.in_((kind, 'all'))" in service
    assert "invite_existing_participants(room)" in service
    assert "f'shared-chat-invite:{room.id}:" in service
    assert 'student_has_audience(student, room.audience)' in service
    assert "@activity_chat_bp.get('/student-app/api/activity-chats')" in service
    assert "_student_from_init_request(allow_science=True)" in service
    assert 'SharedActivityChat.query.filter_by(active=True)' in read('backend/app/handlers/menu.py')
    assert 'Доступно' not in read('frontend/templates/activity/chats.html') or 'постоянный' in read('frontend/templates/activity/chats.html')


def test_reading_status_and_permissions_still_checked():
    check = function('is_live')
    assert check('science', SimpleNamespace(is_open=True))
    assert not check('science', SimpleNamespace(is_open=False))
    assert check('event', SimpleNamespace(is_closed=False, is_published=True))
    assert not check('event', SimpleNamespace(is_closed=True, is_published=True))
    service = read('backend/app/services/activity_chats.py')
    assert "if room.audience == 'all':" in service
    assert 'science_allowed(user, \'manage\')' in service
    assert 'not may_write_room(current_user, room)' in service
    assert 'html.escape(body)' in service
    assert 'DirectionChat.query.filter_by(chat_id=candidate.chat_id)' in service
