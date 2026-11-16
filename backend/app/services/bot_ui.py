"""Shared messenger UI contract.

Transport adapters convert these rows to native Telegram, VK and MAX buttons.
All actions remain server-validated; button payloads are never authority.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Action:
    label: str
    key: str


WELCOME_ROWS = (
    (Action('✅ У меня уже есть аккаунт', 'onboarding_existing'),),
    (Action('✨ Создать новый аккаунт', 'onboarding_new'),),
)
HOME_ROWS = (
    (Action('📝 Подать заявление', 'menu_apply'), Action('📌 Мои заявления', 'menu_status')),
    (Action('🎟 Мероприятия', 'menu_events'), Action('👤 Мой профиль', 'menu_profile')),
    (Action('🌐 Личный кабинет', 'menu_app'), Action('🔐 Привязанные аккаунты', 'menu_accounts')),
    (Action('🏛 Руководство студсовета', 'menu_leadership'), Action('📥 Заявки руководителю', 'menu_inbox')),
    (Action('💬 Мои чаты', 'menu_chats'), Action('❔ Помощь', 'menu_help')),
)
BACK_ROWS = ((Action('‹ В главное меню', 'menu_home'),),)
CANCEL_ROWS = ((Action('✕ Отменить', 'flow_cancel'),),)
EDUCATION_ROWS = (
    (Action('🏫 Колледж', 'education_college'),),
    (Action('🎓 Институт', 'education_institute'),),
    (Action('✕ Отменить', 'flow_cancel'),),
)

# Keys are identical on all platforms; clients may render different native components.
COMMANDS = {
    'onboarding_existing': '/link',
    'onboarding_new': '/register',
    'menu_home': '/start',
    'menu_apply': '/directions',
    'menu_status': '/status',
    'menu_events': '/events',
    'menu_profile': '/me',
    'menu_accounts': '/accounts',
    'menu_leadership': '/leadership',
    'menu_inbox': '/inbox',
    'menu_chats': '/my_chats',
    'menu_help': '/help',
    'menu_app': '/app',
    'education_college': '1',
    'education_institute': '2',
    'flow_cancel': '/cancel',
}


def action_to_command(key):
    if key in COMMANDS:
        return COMMANDS[key]
    if key.startswith('account_unlink_') and key.rsplit('_', 1)[-1] in {'vk', 'max'}:
        return '/unlink ' + key.rsplit('_', 1)[-1]
    if key.startswith('unlink_confirm_') and key.rsplit('_', 1)[-1] in {'vk', 'max'}:
        return '/unlink_confirm ' + key.rsplit('_', 1)[-1]
    if key.startswith('event_detail_') and key[13:].isdigit():
        return '/event ' + key[13:]
    if key.startswith('event_return_') and key[13:].isdigit():
        return '/return ' + key[13:]
    if key.startswith('event_decline_') and key[14:].isdigit():
        return '/decline ' + key[14:]
    if key.startswith('event_join_'):
        bits = key.split('_')
        if len(bits) == 4 and bits[2].isdigit() and len(bits[3]) == 10:
            return '/join ' + bits[2] + ' ' + bits[3]
    if key.startswith('direction_') and key[10:].isdigit():
        return '/apply ' + key[10:]
    if key.startswith('pair:'):
        parts = key.split(':')
        if len(parts) == 3 and parts[1] in ('approve', 'deny') and parts[2].isdigit():
            return ('/pairapprove ' if parts[1] == 'approve' else '/pairdeny ') + parts[2]
    return None


def rows_for_screen(screen, *, directions=(), pending=(), linked=(), events=(), event=None, current_platform=None, target_platform=None):
    """Presentation-only navigation; privacy checks happen before screen data is built."""
    if screen == 'welcome':
        return WELCOME_ROWS
    if screen == 'home':
        return HOME_ROWS
    if screen == 'education':
        return EDUCATION_ROWS
    if screen in ('link', 'registration', 'question', 'account_handle'):
        return CANCEL_ROWS
    if screen == 'unlink_confirm':
        if target_platform not in {'vk', 'max'}:
            return BACK_ROWS
        label = 'ВКонтакте' if target_platform == 'vk' else 'MAX'
        return ((Action('Да, отключить ' + label, 'unlink_confirm_' + target_platform),),) + CANCEL_ROWS
    if screen == 'directions':
        rows = tuple((Action((icon or '✦') + ' ' + name[:55], 'direction_' + str(item_id)),)
                     for item_id, icon, name in directions[:8])
        return rows + BACK_ROWS
    if screen == 'events':
        return tuple((Action('🎟 ' + title[:50], 'event_detail_' + str(qid)),)
                     for qid, title in events[:8]) + BACK_ROWS
    if screen == 'event':
        if not event:
            return BACK_ROWS
        qid, days, declined = event
        if declined:
            return ((Action('↩ Вернуться к мероприятию', 'event_return_' + str(qid)),),) + BACK_ROWS
        return (tuple((Action('📅 ' + date + ' · Записаться', 'event_join_' + str(qid) + '_' + date),)
                      for date in days[:8]) +
                ((Action('✕ Отказаться от мероприятия', 'event_decline_' + str(qid)),),) + BACK_ROWS)
    if screen == 'accounts':
        rows = []
        for platform, label in (('telegram', 'Telegram'), ('vk', 'ВКонтакте'), ('max', 'MAX')):
            if platform == current_platform:
                continue
            if platform in linked:
                if platform in {'vk', 'max'}:
                    rows.append((Action('↪ Отключить ' + label, 'account_unlink_' + platform),))
            else:
                rows.append((Action('➕ Подключить ' + label, 'account_' + platform),))
        rows.extend((Action('✅ Подтвердить #' + str(item_id), 'pair:approve:' + str(item_id)),
                     Action('❌ Отклонить #' + str(item_id), 'pair:deny:' + str(item_id)))
                    for item_id in pending[:3])
        return tuple(rows) + BACK_ROWS
    if screen == 'status':
        return ((Action('📝 Подать заявление', 'menu_apply'),),
                (Action('🎟 Мероприятия', 'menu_events'),),) + BACK_ROWS
    if screen == 'profile':
        return ((Action('🔐 Привязанные аккаунты', 'menu_accounts'),),
                (Action('📌 Мои заявления', 'menu_status'),),) + BACK_ROWS
    if screen in {'leadership', 'inbox', 'app'}:
        return BACK_ROWS
    return BACK_ROWS


def welcome_text():
    return (
        '✦ СТУДЕНЧЕСКИЙ СОВЕТ\n'
        '━━━━━━━━━━━━━━━━━━━━\n\n'
        'Рады видеть вас! Это единый помощник студенческого совета.\n\n'
        'Здесь можно подать заявление, следить за его рассмотрением, записываться на мероприятия и управлять профилем.\n\n'
        'Если у вас уже есть аккаунт, подключите его. Если нет — создайте новый профиль.\n\nВыберите подходящий вариант в меню внизу.'
    )


def home_text(full_name):
    return (
        '✦ СТУДЕНЧЕСКИЙ СОВЕТ\n'
        '━━━━━━━━━━━━━━━━━━━━\n\n'
        f'Здравствуйте, {full_name}! 👋\n\n'
        'Ваш профиль доступен в Telegram, ВКонтакте и MAX.\n'
        'Заявления, статусы и мероприятия синхронизируются между подключёнными аккаунтами.\n\n'
        'Выберите нужный раздел с помощью кнопок внизу чата.'
    )
