"""Privacy-conscious operational journal shared by TG, VK and MAX.

This log stores event metadata only: no message bodies, link codes, passwords,
access tokens, raw external user IDs or platform webhook payloads. Writes use an
independent short-lived transaction on the system DB, so a failure to write a
journal row never rolls back a student's registration or breaks a bot response.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import hmac
import logging
import re

from flask import has_app_context
from contextlib import nullcontext
from config import settings
from database import db, BotJournalEvent

logger = logging.getLogger(__name__)
_journal_app = None

def bind_journal_app(app):
    """Allow background broadcast threads to journal without a request context."""
    global _journal_app
    _journal_app = app

PLATFORMS = ('telegram', 'vk', 'max')
KINDS = ('incoming', 'outgoing', 'chat', 'system')
STATUSES = ('success', 'error', 'ignored')

# Never record raw free-form text. Record a command keyword only when approved.
SAFE_COMMANDS = frozenset({
    '/start', '/help', '/menu', '/profile', '/accounts', '/directions', '/events',
    '/applications', '/status', '/chatid', '/chat_id', '/leadership', '/cancel',
    '/code', '/link', '/register', '/connectvk', '/connectmax', '/connecttelegram',
})


def command_category(text):
    """Return only an allowlisted command name, never parameters (e.g. link codes)."""
    candidate = (text or '').strip().split(maxsplit=1)
    command = candidate[0].lower().split('@', 1)[0] if candidate else ''
    if command in SAFE_COMMANDS:
        return command
    if command.startswith('/'):
        return 'other_command'
    return 'text_message'


def actor_alias(platform, external_id):
    """Stable pseudonym for support diagnostics, not a reversible messenger ID."""
    if external_id is None:
        return None
    source = f'{platform}:{external_id}'.encode('utf-8')
    return hmac.new(settings.SECRET_KEY.encode('utf-8'), source, hashlib.sha256).hexdigest()[:12]


def safe_action(value):
    """Restrict action names to a small safe set of ASCII event identifiers."""
    value = str(value or 'event')[:72]
    return value if re.fullmatch(r'[A-Za-z0-9_./:-]{1,72}', value) else 'event'


def record_bot_event(platform, kind, action, status='success', *, actor_id=None,
                     summary=None, duration_ms=None):
    """Fail-open event recording; never requires committing the caller's session."""
    if platform not in PLATFORMS or kind not in KINDS or status not in STATUSES:
        raise ValueError('Unknown bot journal values')
    if not has_app_context() and _journal_app is None:
        return False
    try:
        context = nullcontext() if has_app_context() else _journal_app.app_context()
        with context:
            return _write_event(platform, kind, action, status, actor_id, summary, duration_ms)
    except Exception:
        logger.warning('Bot journal write unavailable (%s/%s)', platform, kind, exc_info=False)
        return False


SAFE_SUMMARIES = frozenset({
    'Нажатие кнопки', 'Команда обнаружения чата',
    'Команда или сообщение (без текста)', 'Изменилось членство бота в чате',
    'Отправка сообщения через Telegram', 'Отправка в чат', 'Ответ пользователю',
    'Сбой доставки в чат', 'Сбой доставки ответа',
    'Беседа обнаружена; требуется подключение администратором',
    'Входящее действие VK (без текста)', 'Ошибка обработки команды',
    'VK Long Poll запущен', 'Переподключение VK Long Poll',
    'Входящее действие MAX (без текста)', 'MAX polling запущен',
    'Сбой MAX polling', 'Telegram polling запущен',
    'Telegram polling остановлен', 'Отправка из веб-панели',
})


def safe_summary(value):
    """Allow only fixed operational labels and reduced delivery metadata.

    Free-form text is never stored in the transport journal: provider responses,
    exception messages and user-entered content can contain credentials or PII.
    """
    candidate = str(value or '').strip()[:150]
    if candidate in SAFE_SUMMARIES:
        return candidate
    if re.fullmatch(r'Мероприятие #\d+: нет выбранных чатов для отправки', candidate):
        return 'Мероприятие: нет выбранных чатов для отправки'
    if re.fullmatch(r'Мероприятие #\d+: ожидают токен \d+ чатов', candidate):
        return 'Ожидание токена мессенджера'
    delivery_match = re.fullmatch(
        r'(?:event|lesson|announcement) #\d+; job #\d+; attempt (\d+)/6; '
        r'(pending|retry|failed|delivered) \(([a-z_]{1,80}|ok)\)', candidate
    )
    if delivery_match:
        attempt, state, _code = delivery_match.groups()
        return f'Доставка: {state}; попытка {attempt}/6'
    return 'Событие интеграции'


def _write_event(platform, kind, action, status, actor_id, summary, duration_ms):
    label = safe_summary(summary)
    values = dict(platform=platform, kind=kind, action=safe_action(action),
                  status=status, actor_alias=actor_alias(platform, actor_id),
                  summary=label, duration_ms=(min(max(int(duration_ms), 0), 600000)
                                              if duration_ms is not None else None))
    with db.engines['system'].begin() as connection:
        connection.execute(BotJournalEvent.__table__.insert().values(**values))
    return True

def prune_bot_journal(*, days=90):
    """Optional explicit maintenance operation, not run on every request."""
    days = min(max(int(days), 7), 3650)
    cutoff = datetime.utcnow() - timedelta(days=days)
    with db.engines['system'].begin() as connection:
        result = connection.execute(BotJournalEvent.__table__.delete().where(
            BotJournalEvent.created_at < cutoff))
    return result.rowcount
