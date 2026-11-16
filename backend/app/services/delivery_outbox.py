"""Durable publication for lesson/event announcements to approved TG/VK/MAX chats.

The event/lesson is committed BEFORE any network call. Jobs survive restarts,
failed sends can be retried, and the UI never mistakes a queued message for a
successfully delivered message. All recipient IDs and message bodies are server-only.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
from html import unescape
import logging
import re
import uuid

from sqlalchemy import update, select

from config import settings
from database import db, DirectionChat, MessengerChat, BotDeliveryJob

logger = logging.getLogger(__name__)
PLATFORM_TOKENS = {
    'telegram': lambda: settings.BOT_TOKEN,
    'vk': lambda: settings.VK_BOT_TOKEN,
    'max': lambda: settings.MAX_BOT_TOKEN,
}


def plain_message(text):
    """Remove Telegram formatting before sending as VK/MAX plain text."""
    return unescape(re.sub(r'<[^>]*>', '', text or ''))


def chat_targets(direction_ids):
    """Return only ACTIVE, administrator-connected direction chats, deduplicated."""
    ids = sorted({int(did) for did in direction_ids if did is not None})
    if not ids:
        return []
    result, seen = [], set()
    # Check *all* live bindings, not only requested departments. A message for
    # department A must never be sent to a mixed chat also linked to B unless
    # this publication deliberately includes both A and B.
    all_tg = DirectionChat.query.filter(DirectionChat.is_active.is_(True)).order_by(DirectionChat.id.asc()).all()
    all_social = MessengerChat.query.filter(
        MessengerChat.is_active.is_(True), MessengerChat.platform.in_(['vk', 'max'])
    ).order_by(MessengerChat.id.asc()).all()
    scopes = {}
    for chat in all_tg:
        scopes.setdefault(('telegram',str(chat.chat_id or '').strip()),set()).add(chat.direction_id)
    for chat in all_social:
        scopes.setdefault((chat.platform,str(chat.chat_id or '').strip()),set()).add(chat.direction_id)
    requested = set(ids)
    tg = [c for c in all_tg if c.direction_id in requested]
    social = [c for c in all_social if c.direction_id in requested]
    for platform, rows in [('telegram', tg), ('social', social)]:
        for chat in rows:
            kind = platform if platform == 'telegram' else chat.platform
            cid = str(chat.chat_id or '').strip()
            key = kind, cid
            if cid and key not in seen and scopes.get(key, set()).issubset(requested):
                seen.add(key)
                result.append(key)
    return result


def enqueue_calendar_announcement(direction_ids, message, *, batch_key=None,
                                  source_type=None, source_id=None, explicit_targets=None):
    """Persist one job per live chat before attempting any delivery.

    A missing token is reported, not presented as a delivered message.
    A stable batch key allows a scheduler retry without duplicate broadcasts.
    """
    batch_key = batch_key or f'manual:{uuid.uuid4().hex}'
    if explicit_targets is None:
        eligible = chat_targets(direction_ids)
    else:
        # Explicit event assignment is authoritative: never fan an event out to
        # every chat bound to its directions. It is safe to send to several
        # selected chats, including chats from different supported platforms.
        eligible = []
        seen = set()
        for platform, recipient in explicit_targets:
            platform = str(platform or '').strip().lower()
            recipient = str(recipient or '').strip()
            if platform in PLATFORM_TOKENS and recipient and (platform, recipient) not in seen:
                seen.add((platform, recipient))
                eligible.append((platform, recipient))
    # Respect the 4000-4096 character transport limits, including HTML entities.
    # If escaped Telegram HTML grows too large, use safe plain text instead of
    # cutting through an HTML tag and causing a provider rejection.
    telegram_body = message if len(message) <= 3900 else plain_message(message)[:3900]
    social_body = plain_message(message)[:3900]
    skipped = {name: 0 for name in PLATFORM_TOKENS}
    blocked = {name: 0 for name in PLATFORM_TOKENS}
    rows = []
    for platform, recipient in eligible:
        token_present = bool(PLATFORM_TOKENS[platform]())
        if not token_present:
            blocked[platform] += 1
        key = sha256(f'{batch_key}:{platform}:{recipient}'.encode()).hexdigest()
        rows.append(dict(
            delivery_key=key, source_type=source_type if source_type in ('event', 'lesson') else None,
            source_id=int(source_id) if source_id is not None else None,
            platform=platform, recipient_id=recipient,
            is_chat=True, message=telegram_body if platform == 'telegram' else social_body,
            status='pending' if token_present else 'blocked', attempts=0,
            next_attempt_at=datetime.utcnow(),
            created_at=datetime.utcnow(),
        ))
    if rows:
        # ON CONFLICT DO NOTHING makes repeated scheduled checks idempotent.
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        with db.engines['system'].begin() as connection:
            connection.execute(sqlite_insert(BotDeliveryJob.__table__).values(rows).on_conflict_do_nothing(index_elements=['delivery_key']))
    queued = len(rows) - sum(blocked.values())
    logger.info('calendar publication source=%s:%s batch=%s targets=%d ready=%d blocked=%s',
                source_type or 'manual', source_id or 0, batch_key[:24], len(eligible), queued, blocked)
    return {'queued': queued, 'blocked': blocked, 'available': len(eligible),
            'missing_token': blocked, 'no_chats': len(eligible) == 0}


def process_delivery_jobs(limit=20, *, sender=None):
    """Worker entry point, called under Flask app context. Returns processed count."""
    if sender is None:
        from services.telegram import send_tg
        from services.messenger_transports import send_message
        def sender(platform, recipient, body, is_chat):
            if platform == 'telegram':
                return send_tg(recipient, body)
            return send_message(platform, recipient, body, is_chat=is_chat)

    from services.bot_journal import record_bot_event
    now = datetime.utcnow()
    # Blocked jobs survive the absence of a token, and resume automatically
    # once that bot is configured (without exhausting retry attempts).
    with db.engines['system'].begin() as connection:
        for platform, token in PLATFORM_TOKENS.items():
            if token():
                connection.execute(update(BotDeliveryJob.__table__).where(
                    BotDeliveryJob.status == 'blocked', BotDeliveryJob.platform == platform,
                ).values(status='pending', next_attempt_at=now))
    # Recover jobs from a worker that crashed mid-send. A retry may duplicate a
    # message if a provider accepted it just before the process died.
    with db.engines['system'].begin() as connection:
        connection.execute(update(BotDeliveryJob.__table__).where(
            BotDeliveryJob.status == 'sending', BotDeliveryJob.locked_until < now,
        ).values(status='retry', next_attempt_at=now))
        ids = connection.execute(select(BotDeliveryJob.id).where(
            BotDeliveryJob.status.in_(['pending', 'retry']),
            BotDeliveryJob.next_attempt_at <= now,
        ).order_by(BotDeliveryJob.id).limit(max(1, min(int(limit), 100)))).scalars().all()
    processed = 0
    for job_id in ids:
        with db.engines['system'].begin() as connection:
            claim = connection.execute(update(BotDeliveryJob.__table__).where(
                BotDeliveryJob.id == job_id,
                BotDeliveryJob.status.in_(['pending', 'retry']),
                BotDeliveryJob.next_attempt_at <= datetime.utcnow(),
            ).values(status='sending', locked_until=datetime.utcnow() + timedelta(minutes=2),
                     last_attempt_at=datetime.utcnow(),
                     attempts=BotDeliveryJob.attempts + 1))
            if not claim.rowcount:
                continue
            job = connection.execute(select(BotDeliveryJob.__table__).where(
                BotDeliveryJob.id == job_id)).mappings().first()
        try:
            successful = bool(sender(job['platform'], job['recipient_id'], job['message'], bool(job['is_chat'])))
            error_code = '' if successful else 'provider_rejected'
        except Exception as exc:
            successful = False
            error_code = type(exc).__name__[:80]  # Never store API payloads or tokens.
            logger.warning('Delivery job #%s failed (%s)', job_id, type(exc).__name__)
        attempts = int(job['attempts'])
        if successful:
            values = {'status': 'delivered', 'delivered_at': datetime.utcnow(), 'last_error': None, 'locked_until': None}
        elif attempts >= 6:
            values = {'status': 'failed', 'last_error': error_code, 'locked_until': None}
        else:
            values = {'status': 'retry', 'last_error': error_code, 'locked_until': None,
                      'next_attempt_at': datetime.utcnow() + timedelta(seconds=min(60 * 2 ** (attempts - 1), 1800))}
        with db.engines['system'].begin() as connection:
            connection.execute(update(BotDeliveryJob.__table__).where(
                BotDeliveryJob.id == job_id, BotDeliveryJob.status == 'sending',
            ).values(**values))
        # Extra delivery-specific audit metadata is safe: no body or recipient ID.
        source = f"{job['source_type'] or 'announcement'} #{job['source_id'] or 0}"
        record_bot_event(
            job['platform'], 'outgoing', 'calendar_delivery',
            'success' if successful else 'error',
            summary=f"{source}; job #{job_id}; attempt {attempts}/6; {values['status']} ({error_code or 'ok'})"[:150],
        )
        logger.info('calendar delivery source=%s:%s platform=%s job=%s status=%s attempt=%s/6 reason=%s',
                    job['source_type'], job['source_id'], job['platform'], job_id,
                    values['status'], attempts, error_code or '-')
        processed += 1
    return processed
