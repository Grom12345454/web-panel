"""VK community Long Poll and MAX Bot API adapters.

Network operations are intentionally outside database transactions. VK uses a
community access token, MAX uses a bot token (Authorization header, API v2).
"""
import logging
import json
import re
import secrets
import time
from functools import lru_cache
import requests
from config import settings
from services.bot_journal import record_bot_event, command_category

logger = logging.getLogger(__name__)
MAX_API = 'https://platform-api2.max.ru'
VK_API = 'https://api.vk.com/method/'


@lru_cache(maxsize=2)
def _cached_vk_session(token, api_version):
    try:
        import vk_api
    except ImportError as exc:
        raise RuntimeError('Установите зависимости: pip install -r requirements.txt (vk-api)') from exc
    # Reuse SDK session and its request lock/rate limiter across broadcasts.
    return vk_api.VkApi(token=token, api_version=api_version)


def _vk_session():
    """Official community token, wrapped by the maintained vk_api Python SDK."""
    if not settings.VK_BOT_TOKEN:
        raise RuntimeError('VK_BOT_TOKEN не указан')
    return _cached_vk_session(settings.VK_BOT_TOKEN, settings.VK_API_VERSION)


def vk_request(method, **params):
    """Use SDK error handling/rate limiting, including for VK messages and chat discovery."""
    return _vk_session().method(method, params)


def _public_url(value):
    from urllib.parse import urlsplit
    from ipaddress import ip_address
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname or ''
        if parsed.scheme != 'https' or not hostname or parsed.username or parsed.password:
            return None
        if hostname.lower() in {'localhost', '127.0.0.1', '0.0.0.0', '::1'}:
            return None
        try:
            if not ip_address(hostname).is_global:
                return None
        except ValueError:
            pass
        return value
    except ValueError:
        return None


def vk_app_url():
    """VK Mini Apps deep link provides VK-signed parameters to Student App."""
    if settings.VK_MINI_APP_ID.isdigit():
        return 'https://vk.com/app' + settings.VK_MINI_APP_ID
    return _public_url(settings.WEBAPP_URL)


def max_app_url():
    """MAX native launch must be configured with URL in MAX partner panel."""
    if re.fullmatch(r'[A-Za-z0-9_]{3,64}', settings.MAX_BOT_USERNAME or ''):
        return 'https://max.ru/' + settings.MAX_BOT_USERNAME + '?startapp'
    return _public_url(settings.WEBAPP_URL)


def _vk_buttons(rows, *, include_app=False):
    """Build a persistent VK community keyboard below the composer.

    Use only text actions in the docked keyboard. The app route replies with a
    normal URL message; this avoids VK error 911 on keyboard formats that mix
    default reply keyboards with link-only button actions.
    """
    buttons = []
    for row in rows:
        current = []
        for button in row:
            current.append({'action': {'type': 'text', 'label': button.label[:40],
                       'payload': json.dumps({'ui': button.key}, ensure_ascii=False)}})
        if current:
            buttons.append(current)
    if include_app and not any(b.key == 'menu_app' for r in rows for b in r):
        buttons.append([{'action': {'type': 'text', 'label': '🌐 Личный кабинет',
                                    'payload': json.dumps({'ui': 'menu_app'}, ensure_ascii=False)}}])
    return json.dumps({'inline': False, 'one_time': False, 'buttons': buttons},
                      ensure_ascii=False) if buttons else None


def _max_buttons(rows, *, include_app=False):
    """Build a persistent MAX reply keyboard (shown by the composer, not in the bubble)."""
    buttons = []
    for row in rows:
        current = []
        for button in row:
            # Reply keyboards send a message as the user; the visible label is
            # also resolved server-side when the client omits the opaque payload.
            current.append({'type': 'message', 'text': button.label[:40],
                            'payload': 'ui:' + button.key})
        if current:
            buttons.append(current)
    if include_app and not any(b.key == 'menu_app' for r in rows for b in r):
        buttons.append([{'type': 'message', 'text': '🌐 Личный кабинет',
                         'payload': 'ui:menu_app'}])
    return [{'type': 'reply_keyboard', 'buttons': buttons}] if buttons else []


def send_vk(peer_id, message, *, with_app=False, pairing_actions=None, keyboard_rows=None):
    # VK random_id stays identical across retries so a successful first request
    # cannot create a duplicate message when the response was lost in transit.
    payload = {'peer_id': int(peer_id), 'message': message[:4000],
               'random_id': secrets.randbelow(2**31)}
    if keyboard_rows is not None:
        markup = _vk_buttons(keyboard_rows, include_app=with_app)
        if markup:
            payload['keyboard'] = markup
    elif with_app:
        payload['keyboard'] = json.dumps({'inline': False, 'one_time': False, 'buttons': [[{'action': {
            'type': 'text', 'label': '🌐 Личный кабинет',
            'payload': json.dumps({'ui': 'menu_app'}, ensure_ascii=False)}}]]}, ensure_ascii=False)
    if pairing_actions and pairing_actions.get('owner_prompt'):
        request_id = int(pairing_actions['request_id'])
        payload['keyboard'] = json.dumps({'inline': False, 'one_time': False, 'buttons': [[
            {'action': {'type': 'text', 'label': f'✅ Подтвердить #{request_id}',
                        'payload': json.dumps({'pair': 'approve', 'request_id': request_id})}, 'color': 'positive'},
            {'action': {'type': 'text', 'label': f'❌ Отклонить #{request_id}',
                        'payload': json.dumps({'pair': 'deny', 'request_id': request_id})}, 'color': 'negative'},
        ]]}, ensure_ascii=False)
    for attempt in range(2):
        try:
            return vk_request('messages.send', **payload)
        except requests.exceptions.RequestException:
            if attempt:
                raise
            time.sleep(0.4)

def max_request(method, endpoint, *, params=None, payload=None, timeout=15):
    if not settings.MAX_BOT_TOKEN:
        raise RuntimeError('MAX_BOT_TOKEN не указан')
    response = requests.request(
        method, MAX_API + endpoint,
        headers={'Authorization': settings.MAX_BOT_TOKEN, 'Content-Type': 'application/json'},
        params=params, json=payload, timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    if data.get('success') is False:
        raise RuntimeError('MAX API returned success=false')
    return data


def _max_sdk_send(target, message, *, is_chat=False):
    """Send plain messages via the MAX Python SDK (async) from sync workers.

    Reply keyboards use the raw API path below because the SDK's convenience
    sender does not expose the complete native attachment structure.
    """
    import asyncio
    try:
        from maxapi import Bot
    except ImportError as exc:
        raise RuntimeError('Установите зависимости: pip install -r requirements.txt (maxapi)') from exc

    async def deliver():
        bot = Bot(settings.MAX_BOT_TOKEN)
        try:
            opts = {'chat_id' if is_chat else 'user_id': int(target)}
            return await bot.send_message(text=message[:4000], **opts)
        finally:
            # maxapi versions differ in how they expose a transport session.
            # Close it when provided by the installed version.
            session = getattr(bot, 'session', None)
            closer = getattr(session, 'close', None)
            if closer is not None:
                result = closer()
                if asyncio.iscoroutine(result):
                    await result

    # Calls are dispatched from Flask/worker threads; never nest event loops.
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(deliver())
    # This path is called by existing async Telegram handlers; do not drop
    # the message or attempt a nested asyncio.run() in that same thread.
    return max_request('POST', '/messages',
                       params={'chat_id' if is_chat else 'user_id': int(target)},
                       payload={'text': message[:4000]})


def send_max(target, message, *, is_chat=False, with_app=False, pairing_actions=None, keyboard_rows=None):
    if not settings.MAX_BOT_TOKEN:
        raise RuntimeError('MAX_BOT_TOKEN не указан')
    key = 'chat_id' if is_chat else 'user_id'
    payload = {'text': message[:4000]}
    if keyboard_rows is not None:
        payload['attachments'] = _max_buttons(keyboard_rows, include_app=with_app)
    elif with_app:
        from services.bot_ui import Action
        payload['attachments'] = _max_buttons(((Action('🌐 Личный кабинет','menu_app'),),),
                                                include_app=False)
    if pairing_actions and pairing_actions.get('owner_prompt'):
        request_id = int(pairing_actions['request_id'])
        payload['attachments'] = [{'type': 'reply_keyboard', 'buttons': [[
            {'type': 'message', 'text': f'✅ Подтвердить #{request_id}',
             'payload': f'pair:approve:{request_id}'},
            {'type': 'message', 'text': f'❌ Отклонить #{request_id}',
             'payload': f'pair:deny:{request_id}'},
        ]]}]
    if not payload.get('attachments'):
        return _max_sdk_send(target, message, is_chat=is_chat)
    # MAX SDK does not accept arbitrary reply-keyboard attachments. Preserve
    # identical actions by sending typed JSON straight to the documented API.
    return max_request('POST', '/messages', params={key: int(target)}, payload=payload)


def send_message(platform, user_id, message, *, is_chat=False, with_app=False,
                 pairing_actions=None, keyboard_rows=None):
    """Send without recording the message body or its sensitive parameters."""
    began = time.monotonic()
    try:
        if platform == 'vk':
            success = send_vk(user_id, message, with_app=with_app,
                              pairing_actions=pairing_actions, keyboard_rows=keyboard_rows) is not None
        elif platform == 'max':
            success = bool(send_max(user_id, message, is_chat=is_chat, with_app=with_app,
                                    pairing_actions=pairing_actions, keyboard_rows=keyboard_rows))
        else:
            raise ValueError('Unknown messenger')
        record_bot_event(platform, 'outgoing', 'message_sent' if success else 'message_failed',
                         'success' if success else 'error', actor_id=user_id,
                         summary='Отправка в чат' if is_chat else 'Ответ пользователю',
                         duration_ms=(time.monotonic() - began) * 1000)
        return success
    except Exception as exc:
        # Do not save exceptions or API payloads: they can contain tokens/IDs.
        api_code = getattr(exc, 'code', None) or getattr(exc, 'error_code', None)
        if platform == 'vk' and api_code == 911:
            logger.warning('VK keyboard rejected (keyboard_invalid, api_code=911)')
        elif platform == 'vk' and isinstance(api_code, int):
            logger.warning('Messenger send failed (vk, %s, api_code=%s)',
                           type(exc).__name__, api_code)
        else:
            logger.warning('Messenger send failed (%s, %s)', platform, type(exc).__name__)
        if platform in {'vk', 'max'}:
            record_bot_event(platform, 'outgoing', 'message_failed', 'error',
                             actor_id=user_id, summary='Сбой доставки в чат' if is_chat else 'Сбой доставки ответа',
                             duration_ms=(time.monotonic() - began) * 1000)
        return False


def _deliver_private(platform, user_id, text, *, username=None, action=None):
    """Render equivalent structured screens for VK and MAX from the same service."""
    from services.multi_messenger import handle_private_text, handle_private_action, bot_screen
    if action is None:
        response = handle_private_text(platform, str(user_id), text, username=username)
        command = (text or '').strip().lower().split(' ', 1)[0]
    else:
        response = handle_private_action(platform, str(user_id), action, username=username)
        from services.bot_ui import action_to_command
        command = action_to_command(action) or {
            'account_vk':'/connectvk', 'account_max':'/connectmax',
            'account_telegram':'/connecttelegram',
        }.get(action, '/start')
    screen = bot_screen(platform, str(user_id), command, action=command)
    return response, screen

def discover_chat(platform, chat_id, title):
    """Record chat from authenticated bot updates; never activate it automatically."""
    from datetime import datetime
    from database import db, MessengerChatCandidate
    raw = str(chat_id)
    row = MessengerChatCandidate.query.filter_by(platform=platform, chat_id=raw).first()
    if row is None:
        row = MessengerChatCandidate(platform=platform, chat_id=raw, title=(title or raw)[:255])
        db.session.add(row)
    else:
        row.title = (title or raw)[:255]
        row.last_seen_at = datetime.utcnow()
    db.session.commit()
    record_bot_event(platform, 'chat', 'chat_detected', summary='Беседа обнаружена; требуется подключение администратором')


def _action_from_button_text(platform, text, user_id):
    """Resolve visible bottom-keyboard labels on any platform when payload is absent."""
    import unicodedata
    from services.bot_ui import (HOME_ROWS, WELCOME_ROWS, BACK_ROWS, CANCEL_ROWS,
                                 EDUCATION_ROWS, rows_for_screen)

    def norm(value):
        return ' '.join(unicodedata.normalize('NFKC', str(value or '')).casefold().split())

    target = norm(text)
    if not target:
        return None
    candidate_rows = [HOME_ROWS, WELCOME_ROWS, BACK_ROWS, CANCEL_ROWS, EDUCATION_ROWS]
    for screen_name in ('status', 'profile', 'leadership', 'inbox', 'app'):
        candidate_rows.append(rows_for_screen(screen_name))
    try:
        from services.multi_messenger import student_for, linked_account_status, pending_link_requests, _get_flow
        from services.applications import available_application_directions
        student = student_for(platform, user_id)
        if student and student.council_registered:
            directions = available_application_directions(student)
            candidate_rows.append(rows_for_screen(
                'directions', directions=[(d.id, d.icon, d.name) for d in directions]))
            from services.shared_event_actions import visible_events, event_for_student
            events = visible_events(student)
            candidate_rows.append(rows_for_screen('events', events=[(q.id, q.event_title) for q in events]))
            for item in events[:20]:
                quota = event_for_student(student, item.id)
                if quota:
                    from database import EventQuotaDecline
                    declined = bool(EventQuotaDecline.query.filter_by(
                        quota_id=quota.id, student_id=student.id).first())
                    days = [d.date.strftime('%Y-%m-%d') for d in quota.days
                            if d.date.date() >= __import__('datetime').datetime.utcnow().date()
                            and d.available_places() > 0]
                    candidate_rows.append(rows_for_screen('event', event=(quota.id, days, declined)))
            status = linked_account_status(student)
            candidate_rows.append(rows_for_screen(
                'accounts', pending=[r['id'] for r in pending_link_requests(student)],
                linked=[name for name, value in status.items() if value['connected']],
                current_platform=platform))
        flow = _get_flow(platform, user_id)
        if flow and flow.get('kind') == 'unlink_confirm':
            candidate_rows.append(rows_for_screen(
                'unlink_confirm', target_platform=flow.get('target_platform')))
        elif flow and flow.get('kind') == 'registration' and flow.get('field') == 'education_type':
            candidate_rows.append(rows_for_screen('education'))
        elif flow:
            candidate_rows.append(rows_for_screen('question'))
    except Exception:
        logger.debug('Could not resolve dynamic messenger keyboard label', exc_info=True)

    for rows in candidate_rows:
        for row in rows:
            for button in row:
                # Keep label normalization consistent with VK API's 40-char limit.
                if norm(button.label[:(40 if platform in {'vk', 'max'} else 64)]) == target:
                    return button.key
    # Pair-review buttons use an explicit request number and are validated by
    # review_link_request against the authenticated account owner.
    import re
    match = re.fullmatch(r'[✅✔]??\s*Подтвердить\s*#(\d+)', str(text).strip(), re.I)
    if match:
        return 'pair:approve:' + match.group(1)
    match = re.fullmatch(r'[❌✖]??\s*Отклонить\s*#(\d+)', str(text).strip(), re.I)
    if match:
        return 'pair:deny:' + match.group(1)
    return None


def _vk_action_from_text(text, user_id):
    """Backward-compatible VK-specific resolver."""
    return _action_from_button_text('vk', text, user_id)


def handle_vk_event(event, app):
    """VK message payloads are UX shortcuts, never proof of a privileged action.

    VK does not send Telegram-style /start as the only onboarding signal. When a
    user first presses the community's "Начать" button, Long Poll emits
    ``message_allow``. Treat it as the VK equivalent of Telegram /start and
    MAX ``bot_started`` so a new dialog never looks empty.
    """
    event_type = event.get('type')
    if event_type == 'message_allow':
        obj = event.get('object') or {}
        user_id = obj.get('user_id') or obj.get('user', {}).get('id')
        if not user_id or int(user_id) <= 0:
            return
        try:
            with app.app_context():
                response, screen = _deliver_private('vk', user_id, '/start')
            if response:
                send_message('vk', user_id, response, keyboard_rows=screen['rows'],
                             with_app=screen['app'])
                record_bot_event('vk', 'incoming', 'bot_started', 'success', actor_id=user_id,
                                 summary='Пользователю показано стартовое меню VK')
        except Exception:
            logger.exception('VK welcome delivery failed')
            record_bot_event('vk', 'incoming', 'bot_started', 'error', actor_id=user_id,
                             summary='Не удалось показать стартовое меню VK')
            with app.app_context():
                from database import db
                db.session.rollback()
        return
    if event_type == 'message_deny':
        obj = event.get('object') or {}
        user_id = obj.get('user_id')
        if user_id:
            record_bot_event('vk', 'incoming', 'message_denied', 'warning', actor_id=user_id,
                             summary='Пользователь запретил сообщения сообщества')
        return
    if event_type != 'message_new':
        return
    message = (event.get('object') or {}).get('message') or {}
    user_id, peer_id = message.get('from_id'), message.get('peer_id')
    if not user_id or not peer_id or int(user_id) <= 0 or message.get('out'):
        return
    text = (message.get('text') or '').strip()
    if int(peer_id) == int(user_id):
        record_bot_event('vk', 'incoming', 'button' if message.get('payload') else command_category(text),
                         actor_id=user_id, summary='Входящее действие VK (без текста)')
    if int(peer_id) != int(user_id):
        if text.lower() in {'/chatid', '/chat_id'}:
            with app.app_context():
                discover_chat('vk', peer_id, 'Беседа VK · ' + str(peer_id))
            send_message('vk', peer_id, f'Беседа VK обнаружена (ID {peer_id}). Подключить её к направлению может только главный администратор.', is_chat=True)
        return
    try:
        action = None
        payload = message.get('payload')
        if payload:
            try:
                parsed = payload if isinstance(payload, dict) else json.loads(payload)
                if isinstance(parsed, dict):
                    if isinstance(parsed.get('ui'), str):
                        action = parsed['ui']
                    elif parsed.get('pair') in {'approve', 'deny'} and str(parsed.get('request_id', '')).isdigit():
                        action = 'pair:' + parsed['pair'] + ':' + str(parsed['request_id'])
            except (ValueError, TypeError, AttributeError):
                pass
        if action is None and text:
            with app.app_context():
                action = _action_from_button_text('vk', text, user_id)
        with app.app_context():
            response, screen = _deliver_private('vk', user_id, text, action=action)
            command = (text or '').strip().lower().split(' ', 1)[0]
            if action == 'menu_app' or command in {'/app', '/student_app'}:
                app_url = vk_app_url()
                if response and app_url:
                    response += '\n' + app_url
        if response:
            send_message('vk', peer_id, response, keyboard_rows=screen['rows'],
                         with_app=screen['app'])
    except Exception:
        logger.exception('VK incoming command failed')
        record_bot_event('vk', 'incoming', 'processing_error', 'error', actor_id=user_id, summary='Ошибка обработки команды')
        with app.app_context():
            from database import db
            db.session.rollback()

def run_vk_polling(app, stop_event=None):
    """Run VK community Long Poll with bounded exponential reconnect backoff."""
    if not settings.VK_GROUP_ID or not settings.VK_BOT_TOKEN:
        logger.info('VK bot not started: set VK_GROUP_ID and VK_BOT_TOKEN')
        return
    try:
        from vk_api.bot_longpoll import VkBotLongPoll
    except ImportError:
        logger.exception('VK SDK is unavailable; install requirements.txt')
        return
    record_bot_event('vk', 'system', 'bot_started', summary='VK Long Poll запущен')
    reconnect_delay = 5
    while stop_event is None or not stop_event.is_set():
        try:
            session = _vk_session()
            longpoll = VkBotLongPoll(session, int(settings.VK_GROUP_ID), wait=10)
            logger.info('VK Long Poll connected; group_id=%s', settings.VK_GROUP_ID)
            while stop_event is None or not stop_event.is_set():
                events = longpoll.check()
                reconnect_delay = 5
                for event in events:
                    handle_vk_event(event.raw, app)
        except Exception as exc:
            # VK API error code 5 means the access token is invalid/revoked.
            if getattr(exc, 'code', None) == 5:
                from services.runtime_supervisor import PermanentWorkerExit
                record_bot_event('vk', 'system', 'invalid_credentials', 'error', summary='VK отключён: токен отклонён API')
                raise PermanentWorkerExit('VK rejected VK_BOT_TOKEN; update .env and restart')
            if isinstance(exc, requests.exceptions.RequestException):
                logger.warning('VK Long Poll network interruption (%s); reconnect in %ss',
                               type(exc).__name__, reconnect_delay)
            else:
                logger.exception('VK Long Poll failed; reconnect in %ss', reconnect_delay)
            record_bot_event('vk', 'system', 'polling_error', 'error', summary='Переподключение VK Long Poll')
            # Drop the cached SDK session after transport failures; a fresh
            # connection/session is used on the next attempt.
            if isinstance(exc, requests.exceptions.RequestException):
                _cached_vk_session.cache_clear()
            delay = reconnect_delay
            reconnect_delay = min(reconnect_delay * 2, 60)
            if stop_event is not None:
                if stop_event.wait(delay):
                    break
            else:
                time.sleep(delay)


def handle_max_event(update, app):
    """MAX text and callback buttons share the same application command handler."""
    kind = update.get('update_type')
    message = update.get('message') or {}
    # Callback message.sender can be the BOT: the clicking user is update.user.
    sender = ((update.get('user') or {}) if kind in {'message_callback','bot_started'} else (message.get('sender') or update.get('user') or {}))
    user_id = sender.get('user_id')
    if not user_id or sender.get('is_bot'):
        return
    action = None
    callback_id = None
    if kind == 'bot_started':
        text = '/start'
        target = user_id
    elif kind == 'message_callback':
        callback = update.get('callback') or {}
        callback_id = callback.get('callback_id')
        payload = str(callback.get('payload') or '')
        target = user_id  # Always respond privately to the authenticated sender.
        if payload.startswith('ui:'):
            action = payload[3:]
        elif re.fullmatch(r'pair:(approve|deny):[0-9]+', payload):
            action = payload
        else:
            return
        text = ''
    elif kind == 'message_created':
        text = ((message.get('body') or {}).get('text') or '').strip()
        recipient = message.get('recipient') or {}
        chat_type = str(recipient.get('chat_type', '')).lower()
        is_chat = chat_type not in {'dialog', 'private', 'user'}
        target = recipient.get('chat_id') if is_chat else user_id
        if is_chat:
            if text.lower() in {'/chatid', '/chat_id'} and target is not None:
                with app.app_context():
                    discover_chat('max', target, 'Чат MAX · ' + str(target))
                send_message('max', target, 'Чат MAX обнаружен (ID ' + str(target) + '). Подключить его к направлению может только главный администратор.', is_chat=True)
            return
        if text:
            action = _action_from_button_text('max', text, user_id)
    else:
        return
    if not text and action is None:
        return
    record_bot_event('max', 'incoming', 'button' if action else command_category(text),
                     actor_id=user_id, summary='Входящее действие MAX (без текста)')
    try:
        with app.app_context():
            response, screen = _deliver_private('max', str(user_id), text, username=sender.get('username'), action=action)
            command = (text or '').strip().lower().split(' ', 1)[0]
            if action == 'menu_app' or command in {'/app', '/student_app'}:
                app_url = max_app_url()
                if response and app_url:
                    response += '\n' + app_url
        if callback_id:
            # Acknowledge the click; content is delivered with the same keyboard as VK.
            try:
                max_request('POST', '/answers', params={'callback_id':callback_id},
                            payload={'notification':'Раздел открыт'})
            except (requests.RequestException, RuntimeError, ValueError):
                logger.warning('MAX callback acknowledgement failed')
        if response:
            send_message('max', target, response, keyboard_rows=screen['rows'],
                         with_app=screen['app'])
    except Exception:
        logger.exception('MAX incoming command failed')
        record_bot_event('max', 'incoming', 'processing_error', 'error', actor_id=user_id, summary='Ошибка обработки команды')
        with app.app_context():
            from database import db
            db.session.rollback()

def run_max_dev_polling(app, stop_event=None):
    """Development only; MAX officially requires webhook in production."""
    marker = None
    record_bot_event('max', 'system', 'bot_started', summary='MAX polling запущен')
    while stop_event is None or not stop_event.is_set():
        try:
            params = {'timeout': 30, 'limit': 100}
            if marker is not None:
                params['marker'] = marker
            data = max_request('GET', '/updates', params=params, timeout=40)
            for event in data.get('updates', []):
                handle_max_event(event, app)
            marker = data.get('marker', marker)
        except requests.HTTPError as exc:
            if getattr(exc.response, 'status_code', None) in {401, 403}:
                from services.runtime_supervisor import PermanentWorkerExit
                record_bot_event('max', 'system', 'invalid_credentials', 'error', summary='MAX отключён: токен отклонён API')
                raise PermanentWorkerExit('MAX rejected MAX_BOT_TOKEN; update .env and restart')
            logger.exception('MAX dev polling failed')
            record_bot_event('max', 'system', 'polling_error', 'error', summary='Сбой MAX polling')
            time.sleep(5)
        except Exception:
            logger.exception('MAX dev polling failed')
            record_bot_event('max', 'system', 'polling_error', 'error', summary='Сбой MAX polling')
            time.sleep(5)
