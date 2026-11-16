"""Out-of-band notice of a pending account claim. Never grants access.

Notifications are best effort: the request remains pending in Student App even if
messenger delivery is blocked or a platform is temporarily offline.
"""
import logging
import requests
from config import settings
from database import MessengerIdentity
from services.messenger_transports import send_message

log = logging.getLogger(__name__)


def telegram_notice(user_id, text, *, request_id=None):
    if not settings.BOT_TOKEN or not user_id or int(user_id) <= 0:
        return False
    payload = {'chat_id': int(user_id), 'text': text}
    if request_id is not None:
        payload['reply_markup'] = {'inline_keyboard': [[
            {'text': '✅ Подтвердить', 'callback_data': f'pair:approve:{request_id}'},
            {'text': '❌ Отклонить', 'callback_data': f'pair:deny:{request_id}'},
        ]]}
    try:
        response = requests.post('https://api.telegram.org/bot' + settings.BOT_TOKEN + '/sendMessage',
                                 json=payload, timeout=8)
        return response.ok and response.json().get('ok', False)
    except (requests.RequestException, ValueError):
        log.warning('Could not notify Telegram account about pairing')
        return False


def notify_link_request(student, request_id, platform, handle):
    """Alert ONLY existing trusted identities, never the unlinked claiming sender."""
    label = {'telegram': 'Telegram', 'vk': 'ВКонтакте', 'max': 'MAX'}[platform]
    text = (f'🔐 Запрос на подключение {label}\nАккаунт: {handle}\n'
            'Вы запрашивали привязку этого аккаунта?\n'
            f'✅ /pairapprove {request_id} — подтвердить\n'
            f'❌ /pairdeny {request_id} — отклонить\n'
            'Если запрос не ваш, нажмите «Отклонить».\n'
            'Без вашего согласия аккаунт не получит доступ. Запрос действует 10 минут.')
    if student.tg_id and student.tg_id > 0:
        telegram_notice(student.tg_id, text, request_id=request_id)
    for item in MessengerIdentity.query.filter_by(student_id=student.id).all():
        send_message(item.platform, item.external_user_id, text,
                     pairing_actions={'request_id': request_id, 'owner_prompt': True})


def notify_link_result(platform, user_id, accepted):
    text = ('✅ Владелец подтвердил подключение. Теперь можно войти через этот бот.' if accepted else
            '❌ Владелец профиля отклонил подключение. Доступ не предоставлен.')
    if platform == 'telegram':
        telegram_notice(user_id, text)
    else:
        send_message(platform, user_id, text)
