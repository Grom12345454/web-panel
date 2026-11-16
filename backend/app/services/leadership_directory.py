"""Single authoritative public leadership directory across Telegram, VK, MAX and web.

Only account IDs and public usernames confirmed by a platform are published.
Historical chair-per-direction rows are displayed as one chair appointment.
"""
import re
from database import MessengerIdentity, StudentLeadership
from services.permissions import role_label, role_scope, is_global_role_name

VISIBLE_POSITIONS = frozenset({
    'Председатель студсовета',
    'Заместитель председателя студсовета по колледжу',
    'Заместитель председателя студсовета по институту',
    'Глава направления', 'Заместитель главы направления',
})


def profile_links(person, identities):
    """Return only verified, public, safely clickable messenger profiles."""
    links, seen = [], set()

    def add(platform, label, handle, url, symbol):
        if platform not in seen:
            links.append({'platform': platform, 'label': label, 'handle': handle,
                          'symbol': symbol, 'url': url})
            seen.add(platform)

    username = (getattr(person, 'telegram_username', None) or '').strip().lstrip('@')
    if getattr(person, 'tg_id', None) and person.tg_id > 0 and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{4,31}', username):
        add('telegram', 'Telegram', '@' + username, 'https://t.me/' + username, '✈')
    for ident in identities:
        external_id = str(ident.external_user_id or '').strip()
        if ident.platform == 'vk' and re.fullmatch(r'[1-9][0-9]{0,18}', external_id):
            add('vk', 'ВКонтакте', 'ID ' + external_id, 'https://vk.com/id' + external_id, 'VK')
        if ident.platform == 'max':
            handle = (ident.public_username or '').strip().lstrip('@')
            if re.fullmatch(r'[A-Za-z0-9_]{3,64}', handle):
                add('max', 'MAX', '@' + handle, 'https://max.ru/' + handle, 'M')
    return links


def leadership_cards(direction_ids=None):
    """Build public directory cards, optionally restricted to direction leaders.

    ``direction_ids=None`` preserves the global public directory. An explicit
    set, including an empty set, is a strict direction-only scope for employees.
    Global chair/deputy roles are deliberately excluded from a direction scope.
    """
    query = StudentLeadership.query.order_by(StudentLeadership.id.asc())
    if direction_ids is None:
        rows = query.all()
    else:
        allowed_ids = {int(value) for value in direction_ids if value is not None}
        rows = query.filter(StudentLeadership.direction_id.in_(allowed_ids)).all() if allowed_ids else []
        rows = [row for row in rows if not is_global_role_name(row.position_name)]
    student_ids = {row.student_id for row in rows if row.student_id is not None}
    identities_by_student = {}
    if student_ids:
        for ident in MessengerIdentity.query.filter(MessengerIdentity.student_id.in_(student_ids)).all():
            identities_by_student.setdefault(ident.student_id, []).append(ident)
    result, seen, chair_shown = [], set(), False
    for row in rows:
        person = row.student
        if not person:
            continue
        role = role_label(row.position_name)
        if role not in VISIBLE_POSITIONS:
            continue
        scope = role_scope(row.position_name, row.education_type) or 'direction'
        if role == 'Председатель студсовета':
            if chair_shown:
                continue
            chair_shown = True
            key = ('chair',)
        else:
            key = (person.id, role, scope, row.direction_id if scope == 'direction' else None)
        if key in seen:
            continue
        seen.add(key)
        responsibility = ('Все направления' if role == 'Председатель студсовета' else
            'Колледж · все направления' if scope == 'college' else
            'Институт · все направления' if scope == 'institute' else
            row.direction.name if row.direction else 'Направление не указано')
        result.append({
            'student_id': person.id,
            'full_name': person.full_name,
            'group': person.group or '',
            'position': role,
            'scope': scope,
            'direction_name': responsibility,
            'links': profile_links(person, identities_by_student.get(person.id, [])),
        })
    # A deterministic hierarchy across ALL frontends: one chair, two deputy
    # cohorts, then direction heads/deputies. Legacy row order is not authority.
    priority = {'Председатель студсовета': 0,
                'Заместитель председателя студсовета по колледжу': 1,
                'Заместитель председателя студсовета по институту': 2,
                'Глава направления': 3, 'Заместитель главы направления': 4}
    return sorted(result, key=lambda card: (priority.get(card['position'], 9),
                    card['direction_name'].casefold(), card['full_name'].casefold()))


def leadership_plain_text():
    cards = leadership_cards()
    if not cards:
        return '🏛 Руководство студсовета\n\nРуководство пока не назначено.'
    lines = ['✦ Руководство студсовета', 'Подтверждённые публичные контакты руководителей:']
    for card in cards:
        lines.append('\n' + card['position'] + '\n' + card['full_name'] +
                     '\nОтветственность: ' + card['direction_name'])
        for link in card['links']:
            lines.append('↗ ' + link['label'] + ' · ' + link['handle'] + ': ' + link['url'])
    return '\n'.join(lines)
