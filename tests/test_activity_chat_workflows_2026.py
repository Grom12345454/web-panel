"""Regression checks for long-lived, shared Telegram rooms (not per-event groups).

Bot API integration still requires real Telegram admin permissions and a test chat.
"""
import ast
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def text(path):
    return (ROOT / path).read_text(encoding='utf-8')


def get_func(name):
    source = ast.parse(text('backend/app/services/activity_chats.py'))
    node = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == name)
    env = {}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), 'subset', 'exec'), env)
    return env[name]


def test_chat_rooms_are_permanent_and_no_event_id_is_required():
    model = text('backend/app/database/activity_chats.py')
    service = text('backend/app/services/activity_chats.py')
    shared = model.split('class SharedActivityChat')[1]
    assert 'activity_id' not in shared
    assert 'chat_id = db.Column(db.String(100), unique=True' in shared
    assert 'audience = db.Column(' in shared
    assert "@activity_chat_bp.post('/activity-chats/add')" in service
    assert "candidate.chat_type not in {'group', 'supergroup'}" in service
    assert "'creates_join_request': True" in service
    assert "telegram_api('getChat'" in service


def test_eligibility_for_new_invites_and_historical_membership():
    service = text('backend/app/services/activity_chats.py')
    func = get_func('is_live')
    assert func('science', SimpleNamespace(is_open=True))
    assert not func('science', SimpleNamespace(is_open=False))
    assert func('event', SimpleNamespace(is_closed=False, is_published=True))
    assert not func('event', SimpleNamespace(is_closed=True, is_published=True))
    assert 'def student_has_audience' in service
    assert 'if audience in (\'science\', \'all\'):' in service
    assert 'if audience in (\'event\', \'all\'):' in service
    assert 'not is_live(kind, target)' in service
    assert 'student_has_audience(student, room.audience)' in text('backend/app/handlers/telegram_discovery.py')
    assert 'decline_chat_join_request' in text('backend/app/handlers/telegram_discovery.py')


def test_invitation_dedupe_by_room_link_and_user_and_deliver_to_existing_members():
    service = text('backend/app/services/activity_chats.py')
    assert '@activity_chat_bp.get(\'/student-app/api/activity-chats\')' in service
    assert '_student_from_init_request(allow_science=True)' in service
    assert "f'shared-chat-invite:{room.id}:" in service
    assert "platform='telegram', recipient_id=str(tg_id), is_chat=False" in service
    assert 'MessengerIdentity.query.filter_by(student_id=student.id' in service
    assert "SharedActivityChat.audience.in_((kind, 'all'))" in service
    assert 'invite_existing_participants(room)' in service
    assert "sqlite_insert(BotDeliveryJob.__table__)" in service


def test_only_admin_manages_rooms_and_superadmin_writes_to_mixed_rooms():
    service = text('backend/app/services/activity_chats.py')
    template = text('frontend/templates/activity/chats.html')
    assert 'if room.audience == \'all\':' in service
    assert 'if current_user.role != UserRole.SUPER_ADMIN.value:' in service
    assert 'not may_write_room(current_user, room)' in service
    assert 'html.escape(body)' in service
    assert 'name="csrf_token"' in template
    assert "url_for('activity_chats.post_message'" in template
    assert "url_for('activity_chats.add_room')" in template
    assert 'Добавленные чаты' in template
    assert 'name="target_id"' not in template


def test_closing_activity_does_not_delete_room_or_ban_participants():
    service = text('backend/app/services/activity_chats.py')
    assert get_func('close_activity_chat')('event', 123) == 0
    assert get_func('close_activity_chat')('science', 44) == 0
    assert "telegram_api('banChatMember'" in service  # legacy removals only
    assert "permanent_ids = [r.chat_id for r in SharedActivityChat.query.all()]" in service
    assert "telegram_api('revokeChatInviteLink'" in service  # admin disable only
    assert "ActivityChatRemoval.status: 'cancelled'" in text('backend/app/database/helpers.py')
    assert "close_activity_chat('event', qid)" in text('backend/app/web_app.py')  # safe no-op
    assert "close_activity_chat('science', reading_id)" in text('backend/app/services/science_routes.py')


def test_student_app_telegram_bot_and_science_author_cabinet_use_shared_chats():
    client = text('frontend/assets/scripts/student/student_app.js')
    bot = text('backend/app/handlers/science.py')
    assert 'loadActivityChatInvites' in client
    assert '/student-app/api/activity-chats' in client
    assert 'safeTelegramLink(c.url)' in client
    assert 'activity_chats_menu' in text('backend/app/handlers/menu.py')
    assert "Command('my_chats')" in text('backend/app/handlers/telegram_discovery.py')
    assert 'SharedActivityChat' in bot
    assert 'external_chats=external_chats' in text('backend/app/services/science_routes.py')


def test_unrelated_archives_expiry_and_refresh_remain_in_place():
    assert 'NOTIFICATION_TTL = timedelta(minutes=90)' in text('backend/app/services/site_notifications.py')
    assert 'delete_expired_notifications' in text('run.py')
    assert "autoRefresh='off'" in text('frontend/assets/scripts/portal/site-sync.js')
    assert "@orders_bp.post('/upload')" in text('backend/app/services/orders.py')
    assert '@admin_bp.route("/system/clear-science"' in text('backend/app/web_app.py')


def test_science_author_can_access_status_and_coauthor_confirmation():
    bot = text('backend/app/handlers/science.py')
    assert "Command('science_cabinet')" in bot
    assert "callback_data='science_cabinet'" in bot
    assert 'show_science_cabinet' in bot
    assert 'sci:cabinet:(yes|no)' in bot
    assert 'ScienceAuthor.student_id == student.id' in bot
    assert 'confirm_author(callback.from_user.id' in bot
