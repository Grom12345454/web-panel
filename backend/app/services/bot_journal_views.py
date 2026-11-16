"""Read-only query helpers used by the super-admin bot journal screens."""
from datetime import datetime, timedelta
from sqlalchemy import or_
from database import BotJournalEvent
from services.bot_journal import PLATFORMS, KINDS, STATUSES


def validated_filters(args):
    result = {
        'platform': (args.get('platform') or '').strip(),
        'kind': (args.get('kind') or '').strip(),
        'status': (args.get('status') or '').strip(),
        'start': (args.get('start') or '').strip()[:10],
        'end': (args.get('end') or '').strip()[:10],
        'q': (args.get('q') or '').strip()[:80],
    }
    for key, options in [('platform', PLATFORMS), ('kind', KINDS), ('status', STATUSES)]:
        if result[key] not in options:
            result[key] = ''
    for key in ('start', 'end'):
        try:
            result[key + '_date'] = datetime.strptime(result[key], '%Y-%m-%d') if result[key] else None
        except ValueError:
            result[key] = ''
            result[key + '_date'] = None
    return result


def filtered_events(filters):
    query = BotJournalEvent.query
    for key in ('platform', 'kind', 'status'):
        if filters[key]:
            query = query.filter(getattr(BotJournalEvent, key) == filters[key])
    if filters['start_date']:
        query = query.filter(BotJournalEvent.created_at >= filters['start_date'])
    if filters['end_date']:
        query = query.filter(BotJournalEvent.created_at < filters['end_date'] + timedelta(days=1))
    if filters['q']:
        # Users can search actions, safe summaries and pseudonymous account keys.
        pattern = '%' + filters['q'].replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        query = query.filter(or_(
            BotJournalEvent.action.ilike(pattern, escape='\\'),
            BotJournalEvent.summary.ilike(pattern, escape='\\'),
            BotJournalEvent.actor_alias.ilike(pattern, escape='\\'),
        ))
    return query


PLATFORM_NAMES = {'telegram': 'Telegram', 'vk': 'ВКонтакте', 'max': 'MAX'}
KIND_NAMES = {'incoming': 'Входящее', 'outgoing': 'Отправка', 'chat': 'Чат', 'system': 'Система'}
STATUS_NAMES = {'success': 'Успешно', 'error': 'Ошибка', 'ignored': 'Пропущено'}
ACTION_NAMES = {
    'text_message': 'Сообщение', 'other_command': 'Команда',
    'button': 'Нажатие кнопки', 'chat_detected': 'Чат обнаружен',
    'calendar_delivery': 'Доставка объявления календаря',
    'calendar_no_chats': 'Нет подключённых чатов для публикации',
    'calendar_token_missing': 'Ожидание токена мессенджера',
    'message_sent': 'Сообщение отправлено', 'message_failed': 'Ошибка отправки',
    'webhook': 'Webhook', 'polling_error': 'Сбой соединения',
}
