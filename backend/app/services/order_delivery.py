"""Persistent, individually scoped delivery of private order documents.

Only participating students are recipients. One queue row per (order, student)
prevents accidental repeated sends on page refresh or concurrent workers.
"""
from datetime import datetime, timedelta
import logging

import requests
from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from config import settings
from database import (db, AdministrativeOrder, OrderDeliveryJob, EventDay,
                      DayParticipation, Student)

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 5


def eligible_student_ids(kind, target_id):
    """Explicit participation, NOT all members of a student council direction."""
    if kind == 'event':
        rows = db.session.query(DayParticipation.student_id).join(
            EventDay, DayParticipation.day_id == EventDay.id).filter(
            EventDay.quota_id == target_id,
            DayParticipation.status.in_(['registered', 'attended']),
        ).distinct().all()
    else:
        return set()
    return {int(row[0]) for row in rows}


def queue_order_documents(order):
    """Idempotent publication. Telegram cannot DM a user until they start bot."""
    student_ids = eligible_student_ids(order.target_kind, order.target_id)
    if not student_ids:
        return {'recipients': 0, 'queued': 0, 'without_telegram': 0}
    students = Student.query.filter(Student.id.in_(student_ids)).all()
    now = datetime.utcnow()
    rows = [dict(order_id=order.id, student_id=s.id, platform='telegram',
                 recipient_id=str(s.tg_id), status='pending' if settings.BOT_TOKEN else 'blocked',
                 attempts=0, next_attempt_at=now, created_at=now)
            for s in students if s.tg_id is not None and int(s.tg_id) > 0]
    before = db.session.query(OrderDeliveryJob.id).filter_by(order_id=order.id).count()
    if rows:
        # A stable unique constraint prevents repeated queue entries on refresh.
        db.session.execute(sqlite_insert(OrderDeliveryJob.__table__).values(rows).on_conflict_do_nothing(
            index_elements=['order_id','student_id','platform']))
        db.session.commit()
    after = db.session.query(OrderDeliveryJob.id).filter_by(order_id=order.id).count()
    return {'recipients': len(student_ids), 'queued': max(0, after-before),
            'without_telegram': len(student_ids) - len(rows)}


def _send_telegram_document(order, recipient):
    if not settings.BOT_TOKEN:
        return False
    from services.orders import _order_root
    # Never use untrusted display names as a filesystem path.
    path = _order_root() / order.stored_name
    if not path.is_file() or path.parent != _order_root():
        return False
    caption = ('📜 Приказ по мероприятию\nДокумент: ' + order.original_name)[:900]
    try:
        with path.open('rb') as document:
            response = requests.post(
                'https://api.telegram.org/bot' + settings.BOT_TOKEN + '/sendDocument',
                data={'chat_id': recipient, 'caption': caption,
                      'disable_content_type_detection': 'true'},
                files={'document': (order.original_name, document, order.mime_type)},
                timeout=(7, 40),
            )
        return bool(response.status_code == 200 and response.json().get('ok'))
    except (requests.RequestException, ValueError, OSError) as exc:
        logger.warning('Order Telegram document failed: %s', type(exc).__name__)
        return False


def process_order_deliveries(limit=10, *, sender=None):
    """Outbox worker; the network call is outside DB transactions."""
    now = datetime.utcnow()
    if settings.BOT_TOKEN:
        db.session.execute(update(OrderDeliveryJob).where(
            OrderDeliveryJob.status == 'blocked', OrderDeliveryJob.platform == 'telegram'
        ).values(status='pending', next_attempt_at=now))
    db.session.execute(update(OrderDeliveryJob).where(
        OrderDeliveryJob.status == 'sending', OrderDeliveryJob.locked_until < now
    ).values(status='retry', next_attempt_at=now))
    db.session.commit()
    ids = db.session.execute(select(OrderDeliveryJob.id).where(
        OrderDeliveryJob.status.in_(['pending','retry']),
        OrderDeliveryJob.next_attempt_at <= datetime.utcnow()
    ).order_by(OrderDeliveryJob.id).limit(max(1,min(int(limit),25)))).scalars().all()
    count = 0
    for job_id in ids:
        claimed = db.session.execute(update(OrderDeliveryJob).where(
            OrderDeliveryJob.id == job_id,
            OrderDeliveryJob.status.in_(['pending','retry']),
            OrderDeliveryJob.next_attempt_at <= datetime.utcnow(),
        ).values(status='sending', attempts=OrderDeliveryJob.attempts+1,
                 locked_until=datetime.utcnow()+timedelta(minutes=3)))
        db.session.commit()
        if not claimed.rowcount:
            continue
        job = db.session.get(OrderDeliveryJob, job_id)
        order = db.session.get(AdministrativeOrder, job.order_id)
        # Do not send if the event/reading was cleared or the recipient has
        # since ceased to be an eligible participant.
        student = db.session.get(Student, job.student_id)
        if (not order or not student or str(student.tg_id) != job.recipient_id or
                job.student_id not in eligible_student_ids(order.target_kind, order.target_id)):
            job.status, job.last_error, job.locked_until = 'failed', 'recipient_ineligible', None
            db.session.commit()
            count += 1
            continue
        try:
            success = bool(sender(order, job.recipient_id) if sender else _send_telegram_document(order, job.recipient_id))
        except Exception as exc:
            logger.warning('Order delivery worker error (%s)', type(exc).__name__)
            success = False
        job = db.session.get(OrderDeliveryJob, job_id)
        if success:
            job.status, job.delivered_at, job.last_error = 'delivered', datetime.utcnow(), None
        elif job.attempts >= MAX_ATTEMPTS:
            job.status, job.last_error = 'failed', 'provider_rejected'
        else:
            job.status, job.last_error = 'retry', 'provider_rejected'
            job.next_attempt_at = datetime.utcnow() + timedelta(seconds=min(60 * 2**(job.attempts-1), 1800))
        job.locked_until = None
        db.session.commit()
        count += 1
    return count
