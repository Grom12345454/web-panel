"""Central department announcements: site feed + restart-safe Telegram/VK/MAX queue.

No client-supplied recipient IDs. A sender can publish only after the calling
route performs a server-side permission check. Messenger failures do not undo
a committed calendar entry or falsely report confirmed delivery.
"""
import html
import logging
from datetime import datetime
from hashlib import sha256
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from config import settings
from database import (db, User, UserRole, Direction, SiteNotification, BotDeliveryJob)
from services.system_broadcasts import recipients, social_recipients
from services.staff_access import allowed

logger = logging.getLogger(__name__)
ALL_CHANNELS = frozenset({'site','chats','dm','vk_chats','vk_dm','max_chats','max_dm','staff_dm'})
TOKEN = {'telegram': lambda: settings.BOT_TOKEN, 'vk': lambda: settings.VK_BOT_TOKEN,
         'max': lambda: settings.MAX_BOT_TOKEN}


def _staff_private_recipients(direction_ids, category):
    """Include verified staff Telegram accounts only within their staff scope.

    ``None`` means the administrator's global send. Ordinary system notices
    are mandatory; preferences control optional science/calendar updates only.
    """
    from services.broadcast_policy import broadcast_direction_ids
    result = set()
    for user in User.query.filter(User.role == UserRole.STAFF.value,
                                  User.is_active.is_(True), User.tg_id.isnot(None)).all():
        if category != 'system' and category not in (user.notifications or '').split(','):
            continue
        scope = broadcast_direction_ids(user)
        if direction_ids is None or (scope and set(direction_ids).intersection(scope)):
            result.add(str(user.tg_id))
    return result


def publish_direction_announcement(direction_ids, title, body, *, category='system',
                                   creator_user_id=None, channels=None, batch_key=None,
                                   link_path=None, source_type=None, source_id=None,
                                   education='', severity='info', audience='all', global_broadcast=False):
    """Persist alerts in Student App/employee panel, then queue deduplicated DMs/chats.

    Returns number of ready/blocked jobs, NOT confirmed successful deliveries.
    A caller-supplied stable batch key allows idempotent calendar publication.
    """
    if category not in {'science','events','lessons','applications','system','leadership'}:
        raise ValueError('Unknown notification category')
    channels = ALL_CHANNELS if channels is None else frozenset(channels)
    if not channels or channels - ALL_CHANNELS:
        raise ValueError('Unknown notification delivery channel')
    ids = sorted({int(did) for did in direction_ids if did is not None})
    if not ids and not global_broadcast:
        raise ValueError('Direction is required')
    known = {d.id for d in Direction.query.filter(Direction.id.in_(ids)).all()}
    if len(known) != len(ids):
        raise ValueError('Unknown direction')
    title, body = str(title).strip()[:180], str(body).strip()[:2000]
    if not title or not body:
        raise ValueError('Missing title or body')
    # Stable identifiers for event/lesson announcements; for manual notices use a
    # fresh random key so repeated deliberate announcements remain distinct.
    import secrets
    batch_key = batch_key or 'manual:' + secrets.token_hex(16)
    # Each direction gets a separate site notification so students only receive
    # messages in their ACTIVE directions, rather than a global unscoped notice.
    if 'site' in channels:
        for did in ([None] if global_broadcast else ids):
            pub_key = sha256(f'{batch_key}:site:{did}'.encode()).hexdigest()
            if SiteNotification.query.filter_by(publication_key=pub_key).first():
                continue
            db.session.add(SiteNotification(
                title=title, body=body, category=category, severity=severity,
                audience=audience, education_type=education or None, direction_id=did, creator_user_id=creator_user_id,
                publication_key=pub_key,
                link_path=link_path if link_path and link_path.startswith('/') and not link_path.startswith('//') else None))
        db.session.commit()
    selected = set(channels) - {'site','staff_dm'}
    targets = {}
    for did in ([None] if global_broadcast else ids):
        tg = recipients(education, did, selected)
        social = social_recipients(education, did, selected)
        for channel, values in {**tg, **social}.items():
            if channel in channels:
                platform = 'telegram' if channel in {'dm','chats'} else channel.split('_')[0]
                is_chat = channel.endswith('chats') or channel == 'chats'
                for value in values:
                    # A shared chat receiving posts about the same event through two
                    # departments is contacted only once per batch.
                    targets[(platform, str(value), is_chat)] = True
    if 'staff_dm' in channels:
        for tg_id in _staff_private_recipients(ids if not global_broadcast else None, category):
            targets[('telegram', tg_id, False)] = True
    plain = f'🔔 {title}\n\n{body}'[:3800]
    tg_html = '<b>🔔 ' + html.escape(title) + '</b>\n\n' + html.escape(body)
    if len(tg_html) > 3900:
        tg_html = html.escape(plain[:3000])
    now = datetime.utcnow()
    rows, blocked = [], 0
    for platform, recipient, is_chat in sorted(targets):
        enabled = bool(TOKEN[platform]())
        if not enabled:
            blocked += 1
        rows.append(dict(
            delivery_key=sha256(f'{batch_key}:{platform}:{recipient}:{int(is_chat)}'.encode()).hexdigest(),
            source_type=source_type if source_type in {'event','lesson'} else None,
            source_id=source_id if source_type in {'event','lesson'} else None,
            platform=platform, recipient_id=recipient, is_chat=is_chat,
            message=tg_html if platform == 'telegram' else plain,
            status='pending' if enabled else 'blocked', attempts=0,
            next_attempt_at=now, created_at=now))
    if rows:
        with db.engines['system'].begin() as connection:
            connection.execute(sqlite_insert(BotDeliveryJob.__table__).values(rows)
                               .on_conflict_do_nothing(index_elements=['delivery_key']))
    logger.info('department broadcast batch=%s scopes=%s queued=%s blocked=%s',
                batch_key[:30], len(ids), len(rows)-blocked, blocked)
    return {'queued': len(rows)-blocked, 'blocked': blocked, 'targets': len(rows),
            'site': 'site' in channels}
