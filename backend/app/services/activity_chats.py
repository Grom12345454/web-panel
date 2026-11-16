"""Telegram rooms for event participation and reusable activity groups."""
import html
import logging
from datetime import datetime
from hashlib import sha256

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from database import (db, ActivityChat, ActivityChatRemoval, SharedActivityChat,
                      Student, EventQuota, DayParticipation, EventDay, TelegramChatCandidate,
                      DirectionChat, EventQuotaChat, QuotaDirection, BotDeliveryJob, UserRole,
                      MessengerIdentity, EventLeader)
from config import settings
from services.staff_access import allowed
from services.applications import can_user_manage_direction
from database.helpers import get_quota_direction_ids
from web_app import login_required

logger = logging.getLogger(__name__)
activity_chat_bp = Blueprint('activity_chats', __name__)
AUDIENCES = {'event': 'Мероприятия', 'all': 'Все события'}


def find_target(kind, activity_id):
    if kind == 'event':
        return db.session.get(EventQuota, activity_id)
    return None


def is_live(kind, target):
    return bool(target and kind == 'event' and not target.is_closed and target.is_published)


def eligible(student, kind, target):
    """Eligibility for a new invitation triggered by an active registration."""
    if not student or not is_live(kind, target):
        return False
    if kind != 'event':
        return False
    return db.session.query(DayParticipation.id).join(EventDay, EventDay.id == DayParticipation.day_id).filter(
        EventDay.quota_id == target.id, DayParticipation.student_id == student.id,
        DayParticipation.status.in_(['registered', 'attended'])).first() is not None


def telegram_ids(student):
    """Only platform-confirmed Telegram identities; no guessed @username IDs."""
    if not student:
        return set()
    ids = {int(student.tg_id)} if student.tg_id and int(student.tg_id) > 0 else set()
    for link in MessengerIdentity.query.filter_by(student_id=student.id, platform='telegram').all():
        if str(link.external_user_id).isdigit() and int(link.external_user_id) > 0:
            ids.add(int(link.external_user_id))
    return ids


def by_telegram_id(telegram_id):
    student = Student.query.filter_by(tg_id=telegram_id).first()
    if student:
        return student
    link = MessengerIdentity.query.filter_by(platform='telegram', external_user_id=str(telegram_id)).first()
    return db.session.get(Student, link.student_id) if link else None


def student_has_audience(student, audience):
    """Past confirmed participation continues to qualify for a PERMANENT group.

    Uses saved registration records, not an open-event flag: closing an event
    must not remove a member from a long-lived discussion group.
    """
    if student is None:
        return False
    if audience in ('event', 'all'):
        event = db.session.query(DayParticipation.id).join(
            EventDay, EventDay.id == DayParticipation.day_id).join(
            EventQuota, EventQuota.id == EventDay.quota_id).filter(
            DayParticipation.student_id == student.id,
            DayParticipation.status.in_(['registered', 'attended'])).first()
        if event:
            return True
    return False


def _event_direction_ids(quota_id):
    direction_ids = {int(value) for value in get_quota_direction_ids(quota_id) if value is not None}
    direction_ids.update(int(value) for (value,) in EventQuotaChat.query.with_entities(
        EventQuotaChat.direction_id
    ).filter(EventQuotaChat.quota_id == quota_id, EventQuotaChat.direction_id.is_not(None)).all())
    return direction_ids


def may_write(user, kind, target):
    if not user or not user.is_active or target is None:
        return False
    if user.role == UserRole.SUPER_ADMIN.value:
        return kind == 'event'
    if kind != 'event':
        return False
    if user.role == UserRole.STAFF.value:
        home_id = getattr(user, 'assigned_direction_id', None)
        return bool(home_id and _event_direction_ids(target.id) == {int(home_id)} and
                    allowed(user, int(home_id), 'events', 'manage'))
    appointed = EventLeader.query.filter_by(quota_id=target.id).first()
    if appointed:
        linked_student_id = getattr(user, 'student_id', None)
        if linked_student_id is None and getattr(user, 'tg_id', None):
            profile = Student.query.filter_by(tg_id=user.tg_id).first()
            linked_student_id = profile.id if profile else None
        if linked_student_id == appointed.student_id:
            return True
    for direction_id in get_quota_direction_ids(target.id):
        if allowed(user, direction_id, 'events', 'manage'):
            return True
        if user.role == UserRole.LEADER.value and can_user_manage_direction(user.id, direction_id, None):
            return True
    return False


def may_write_room(user, room, events=None):
    if not room.active or room.audience not in AUDIENCES or not user or not user.is_active:
        return False
    if user.role == UserRole.SUPER_ADMIN.value:
        # The main administrator manages institution-wide and event rooms.
        return True
    if user.role == UserRole.STAFF.value:
        # SharedActivityChat has no direction owner. A department employee must
        # use the dedicated DirectionChat composer, never a cross-area shared room.
        return False
    # Mixed rooms are institute-wide: only the superadministrator can post.
    if room.audience == 'all':
        return False
    if room.audience == 'event':
        rows = events if events is not None else EventQuota.query.all()
        if user.role == UserRole.STAFF.value:
            from services.staff_access import allowed
            try:
                home_id = int(user.assigned_direction_id) if user.assigned_direction_id else None
            except (TypeError, ValueError):
                return False
            return bool(home_id and allowed(user, home_id, 'chats', 'manage') and
                        any(_event_direction_ids(event.id) == {home_id} for event in rows))
        return any(may_write(user, 'event', e) for e in rows)
    return False


def _is_dedicated_event_group(chat_id):
    """Only dedicated Telegram groups may receive event-close removals/invites."""
    chat_id = str(chat_id or '').strip()
    if not chat_id:
        return False
    if DirectionChat.query.filter_by(chat_id=chat_id).first():
        return False
    if SharedActivityChat.query.filter_by(chat_id=chat_id).first():
        return False
    return True


def prepare_event_chat_invites(quota_id):
    """Create join-request links for dedicated Telegram groups assigned to one event.

    Returns (created_count, failure_count). No general direction/permanent chat is
    converted into an event-only group and no invite link is logged.
    """
    from services.telegram import telegram_api
    rows = EventQuotaChat.query.filter_by(quota_id=quota_id, platform='telegram').all()
    created = failures = 0
    for row in rows:
        if not _is_dedicated_event_group(row.chat_id):
            continue
        if row.invite_link:
            continue
        if not settings.BOT_TOKEN:
            failures += 1
            continue
        response = telegram_api('createChatInviteLink', {
            'chat_id': row.chat_id,
            'name': f'Мероприятие #{quota_id}'[:32],
            'creates_join_request': True,
        }, attempts=1)
        invite_link = ((response or {}).get('result') or {}).get('invite_link')
        if invite_link:
            row.invite_link = invite_link
            created += 1
        else:
            failures += 1
    if created:
        db.session.commit()
    return created, failures


def _queue_event_chat_invites(quota, student):
    """Queue a personal invitation to the dedicated chats assigned to this event."""
    if not quota or not student or not settings.BOT_TOKEN:
        return 0
    rows = []
    now = datetime.utcnow()
    for target in EventQuotaChat.query.filter_by(quota_id=quota.id, platform='telegram').all():
        if not target.invite_link or not _is_dedicated_event_group(target.chat_id):
            continue
        title = target.title or f'Мероприятие «{quota.event_title}»'
        body = (f'🎟️ <b>Чат мероприятия: {html.escape(title)}</b>\n\n'
                f'<b>{html.escape(quota.event_title)}</b>\n'
                'Вы записаны на мероприятие. Подайте заявку на вступление в чат по ссылке ниже:\n'
                f'<a href="{html.escape(target.invite_link, quote=True)}">Вступить в чат мероприятия</a>')
        for tg_id in telegram_ids(student):
            key = sha256(
                f'event-chat-invite:{quota.id}:{target.chat_id}:{student.id}:{tg_id}:'
                f'{sha256(target.invite_link.encode()).hexdigest()[:12]}'.encode()
            ).hexdigest()
            rows.append(dict(
                delivery_key=key, platform='telegram', recipient_id=str(tg_id), is_chat=False,
                message=body[:3800], status='pending', attempts=0,
                next_attempt_at=now, created_at=now,
            ))
    if rows:
        with db.engines['system'].begin() as conn:
            conn.execute(sqlite_insert(BotDeliveryJob.__table__).values(rows).on_conflict_do_nothing(
                index_elements=['delivery_key']))
    return len(rows)


def _queue_invites(room, students):
    if not room.active or not room.invite_link:
        return 0
    rows = []
    now = datetime.utcnow()
    for student in students:
        if not student:
            continue
        body = (f'💬 <b>Постоянный чат: {html.escape(room.title)}</b>\n'
                f'{AUDIENCES.get(room.audience, "Обсуждения")}\n\n'
                'Чат используется для событий и связанных с ними активностей. '
                'Подайте заявку на вступление по ссылке:\n'
                f'{html.escape(room.invite_link)}')
        for tg_id in telegram_ids(student):
            rows.append(dict(delivery_key=sha256(
                f'shared-chat-invite:{room.id}:{sha256(room.invite_link.encode()).hexdigest()[:12]}:{student.id}:{tg_id}'.encode()).hexdigest(),
                platform='telegram', recipient_id=str(tg_id), is_chat=False,
                message=body[:3800], status='pending' if settings.BOT_TOKEN else 'blocked',
                attempts=0, next_attempt_at=now, created_at=now))
    if rows:
        with db.engines['system'].begin() as conn:
            conn.execute(sqlite_insert(BotDeliveryJob.__table__).values(rows).on_conflict_do_nothing(
                index_elements=['delivery_key']))
    return len(rows)


def invite_existing_participants(room):
    """Newly added/reconnected rooms also invite everyone already enrolled.

    Enrollment data live in separate DB binds; collect IDs in each database
    separately, then load Students in manageable chunks.
    """
    ids = set()
    if room.audience in ('event', 'all'):
        ids.update(sid for (sid,) in db.session.query(DayParticipation.student_id).join(
            EventDay, EventDay.id == DayParticipation.day_id).join(
            EventQuota, EventQuota.id == EventDay.quota_id).filter(
            DayParticipation.status.in_(['registered', 'attended'])).distinct().all())
    ids.discard(None)
    sorted_ids = sorted(ids)
    count = 0
    for start in range(0, len(sorted_ids), 150):
        batch = Student.query.filter(Student.id.in_(sorted_ids[start:start + 150])).all()
        count += _queue_invites(room, batch)
    return count


def queue_student_invite(kind, activity_id, student):
    """Invite a registered student to this event's assigned chats and reusable rooms."""
    quota = find_target(kind, activity_id)
    if kind != 'event' or not eligible(student, kind, quota):
        return 0
    count = _queue_event_chat_invites(quota, student)
    rooms = SharedActivityChat.query.filter_by(active=True).filter(
        SharedActivityChat.audience.in_((kind, 'all'))).all()
    return count + sum(_queue_invites(room, [student]) for room in rooms)


def close_activity_chat(kind, activity_id, *, commit=True):
    """Revoke invitations and queue removal only from dedicated event Telegram groups.

    Shared/direction-wide groups are never cleaned when one event closes. Reused
    groups are also protected while any other assigned event remains open.
    """
    if kind != 'event':
        return 0
    targets = EventQuotaChat.query.filter_by(quota_id=activity_id, platform='telegram').all()
    if not targets:
        return 0
    rows_by_chat = {}
    for row in targets:
        chat_id = str(row.chat_id or '').strip()
        if chat_id:
            rows_by_chat.setdefault(chat_id, []).append(row)

    removable_chat_ids = set()
    from services.telegram import telegram_api
    for chat_id, target_rows in rows_by_chat.items():
        if not _is_dedicated_event_group(chat_id):
            continue
        other_assignments = EventQuotaChat.query.filter(
            EventQuotaChat.platform == 'telegram', EventQuotaChat.chat_id == chat_id,
            EventQuotaChat.quota_id != activity_id,
        ).all()
        other_quota_ids = {row.quota_id for row in other_assignments if row.quota_id is not None}
        active_elsewhere = bool(other_quota_ids and EventQuota.query.filter(
            EventQuota.id.in_(other_quota_ids), EventQuota.is_closed.is_(False)
        ).first())
        if active_elsewhere:
            continue
        removable_chat_ids.add(chat_id)
        if settings.BOT_TOKEN:
            for target in target_rows:
                if target.invite_link:
                    # Stop new join requests after closing the event.
                    telegram_api('revokeChatInviteLink', {
                        'chat_id': chat_id, 'invite_link': target.invite_link,
                    }, attempts=1)

    if not removable_chat_ids:
        return 0
    participant_ids = {sid for (sid,) in db.session.query(DayParticipation.student_id).join(
        EventDay, EventDay.id == DayParticipation.day_id).filter(
        EventDay.quota_id == activity_id,
        DayParticipation.status.in_(['registered', 'attended', 'absent'])).distinct().all() if sid}
    if not participant_ids:
        return 0
    students = Student.query.filter(Student.id.in_(participant_ids)).all()
    pending = {(str(row.chat_id), int(row.telegram_user_id)) for row in
               ActivityChatRemoval.query.filter(ActivityChatRemoval.status.in_(['pending', 'retry'])).all()}
    added = 0
    for student in students:
        for tg_id in telegram_ids(student):
            for chat_id in removable_chat_ids:
                key = (chat_id, tg_id)
                if key in pending:
                    continue
                db.session.add(ActivityChatRemoval(chat_id=chat_id, telegram_user_id=tg_id,
                                                   status='pending', attempts=0))
                pending.add(key)
                added += 1
    if added and commit:
        db.session.commit()
    return added


def process_chat_removals(limit=20):
    """Only drain historical removals for rooms NOT converted to permanent use."""
    from services.telegram import telegram_api
    if not settings.BOT_TOKEN:
        return 0
    # Direction chats are shared community groups too. Protect them as well as
    # explicitly permanent activity rooms from any stale legacy removal job.
    permanent_ids = {str(r.chat_id) for r in SharedActivityChat.query.all()}
    permanent_ids.update(str(r.chat_id) for r in DirectionChat.query.all())
    if permanent_ids:
        cancelled = ActivityChatRemoval.query.filter(
            ActivityChatRemoval.chat_id.in_(permanent_ids),
            ActivityChatRemoval.status.in_(['pending', 'retry']),
        ).update({ActivityChatRemoval.status: 'cancelled', ActivityChatRemoval.last_error: 'shared_chat_protected'},
                 synchronize_session=False)
        if cancelled:
            db.session.commit()
    query = ActivityChatRemoval.query.filter(ActivityChatRemoval.status.in_(['pending', 'retry']))
    if permanent_ids:
        query = query.filter(~ActivityChatRemoval.chat_id.in_(permanent_ids))
    rows = query.filter(ActivityChatRemoval.attempts < 6).order_by(ActivityChatRemoval.id).limit(limit).all()
    for item in rows:
        item.attempts += 1
        ok = telegram_api('banChatMember', {'chat_id': item.chat_id, 'user_id': item.telegram_user_id}, attempts=1)
        if ok:
            unbanned = telegram_api('unbanChatMember', {
                'chat_id': item.chat_id, 'user_id': item.telegram_user_id, 'only_if_banned': True}, attempts=1)
            item.status = 'done' if unbanned else 'retry'
            item.last_error = None if unbanned else 'unban_failed'
        else:
            item.status = 'retry' if item.attempts < 6 else 'failed'
            item.last_error = 'missing_rights_or_provider_error'
        db.session.commit()
    return len(rows)


def _make_invite(chat_id, audience):
    from services.telegram import telegram_api
    invite = telegram_api('createChatInviteLink', {
        'chat_id': chat_id, 'name': f'Постоянный чат: {audience}'[:32],
        'creates_join_request': True}, attempts=1)
    return (invite or {}).get('result', {}).get('invite_link')


@activity_chat_bp.get('/activity-chats/')
@login_required
def index(current_user):
    if current_user.role not in {UserRole.SUPER_ADMIN.value, UserRole.STAFF.value, UserRole.LEADER.value, UserRole.OBSERVER.value}:
        abort(403)
    if current_user.role == UserRole.STAFF.value:
        # Shared activity rooms are institution-wide and remain admin-only.
        # Employees are routed to a direction-specific chat workspace they own.
        from services.staff_access import direction_ids as staff_direction_ids
        permitted = sorted(staff_direction_ids(current_user, 'chats', 'view'))
        requested = request.args.get('direction', type=int)
        direction_id = requested if requested in permitted else None
        if requested is not None and direction_id is None:
            abort(403)
        if direction_id is None:
            home_id = getattr(current_user, 'assigned_direction_id', None)
            direction_id = home_id if home_id in permitted else (permitted[0] if permitted else None)
        if not direction_id:
            abort(403)
        from flask import redirect
        return redirect(url_for('directions.direction_detail', did=int(direction_id)) + '#direction-chats')
    is_admin = current_user.role == UserRole.SUPER_ADMIN.value
    is_observer = current_user.role == UserRole.OBSERVER.value
    events_query = EventQuota.query.order_by(EventQuota.id.desc())
    if current_user.role == UserRole.STAFF.value:
        home_id = getattr(current_user, 'assigned_direction_id', None)
        from services.staff_access import allowed as staff_allowed
        if not home_id or not staff_allowed(current_user, home_id, 'chats', 'manage'):
            events_query = events_query.filter(db.false())
        else:
            scoped_quota_ids = [row.quota_id for row in QuotaDirection.query.filter_by(direction_id=home_id).all()]
            events_query = events_query.filter(EventQuota.id.in_(scoped_quota_ids))
    events = events_query.limit(100).all()
    if current_user.role == UserRole.STAFF.value and current_user.assigned_direction_id:
        home_id = int(current_user.assigned_direction_id)
        events = [event for event in events if _event_direction_ids(event.id) == {home_id}]
    rooms = SharedActivityChat.query.order_by(SharedActivityChat.active.desc(), SharedActivityChat.id.desc()).all()
    if is_observer:
        # Global observer can inspect active chat configuration but cannot post,
        # invite, add, enable, disable, or otherwise manage any room.
        rooms = [room for room in rooms if room.active]
    elif not is_admin:
        rooms = [room for room in rooms if may_write_room(current_user, room, events)]
    can_manage_shared_rooms = is_admin
    candidates = TelegramChatCandidate.query.order_by(TelegramChatCandidate.id.desc()).limit(150).all() if can_manage_shared_rooms else []
    return render_template('activity/chats.html', rooms=rooms, candidates=candidates,
                           is_admin=can_manage_shared_rooms, is_observer=is_observer, audiences=AUDIENCES)


@activity_chat_bp.post('/activity-chats/add')
@login_required
def add_room(current_user):
    if current_user.role != UserRole.SUPER_ADMIN.value:
        abort(403)
    audience = (request.form.get('audience') or '').strip()
    candidate_id = request.form.get('candidate_id', type=int)
    candidate = db.session.get(TelegramChatCandidate, candidate_id) if candidate_id else None
    if audience not in AUDIENCES or not candidate or candidate.chat_type not in {'group', 'supergroup'}:
        abort(400)
    if (SharedActivityChat.query.filter_by(chat_id=candidate.chat_id).first() or
        DirectionChat.query.filter_by(chat_id=candidate.chat_id).first() or
        EventQuotaChat.query.filter_by(chat_id=candidate.chat_id).first()):
        flash('Чат уже добавлен или используется как чат направления. Выберите другую группу.', 'warning')
        return redirect(url_for('activity_chats.index'))
    from services.telegram import telegram_api
    actual = telegram_api('getChat', {'chat_id': candidate.chat_id}, attempts=1)
    if not actual or str((actual.get('result') or {}).get('id')) != str(candidate.chat_id):
        flash('Не удалось проверить Telegram-группу. Проверьте доступ бота.', 'danger')
        return redirect(url_for('activity_chats.index'))
    invite = _make_invite(candidate.chat_id, audience)
    if not invite:
        flash('Бот не смог создать ссылку с заявкой на вступление. Выдайте права на приглашение.', 'danger')
        return redirect(url_for('activity_chats.index'))
    title = ' '.join((request.form.get('title') or candidate.title or 'Чат Telegram').split())[:255]
    room = SharedActivityChat(chat_id=candidate.chat_id, title=title,
                              audience=audience, invite_link=invite, active=True)
    db.session.add(room)
    db.session.commit()
    try:
        invite_existing_participants(room)
    except Exception:
        logger.exception('Failed to enqueue existing participants for permanent room %s', room.id)
        flash('Чат добавлен, но очередь приглашений не создана полностью. Ссылки доступны в кабинетах.', 'warning')
        return redirect(url_for('activity_chats.index'))
    flash('Постоянный чат добавлен. Приглашения поставлены в очередь для уже записанных студентов.', 'success')
    return redirect(url_for('activity_chats.index'))


@activity_chat_bp.post('/activity-chats/<int:chat_id>/deactivate')
@login_required
def deactivate_room(current_user, chat_id):
    if current_user.role != UserRole.SUPER_ADMIN.value:
        abort(403)
    room = db.get_or_404(SharedActivityChat, chat_id)
    if room.audience not in AUDIENCES:
        abort(404)
    if room.active:
        room.active = False
        db.session.commit()
        # Never ban existing members. Invalidate only the application-generated link.
        if room.invite_link:
            from services.telegram import telegram_api
            if not telegram_api('revokeChatInviteLink', {
                'chat_id': room.chat_id, 'invite_link': room.invite_link}, attempts=1):
                flash('Чат отключён в панели, но Telegram не подтвердил отзыв ссылки.', 'warning')
                return redirect(url_for('activity_chats.index'))
    flash('Чат отключён от новых приглашений. Существующие участники не удалены.', 'success')
    return redirect(url_for('activity_chats.index'))


@activity_chat_bp.post('/activity-chats/<int:chat_id>/activate')
@login_required
def activate_room(current_user, chat_id):
    if current_user.role != UserRole.SUPER_ADMIN.value:
        abort(403)
    room = db.get_or_404(SharedActivityChat, chat_id)
    if room.audience not in AUDIENCES:
        abort(404)
    if not room.active:
        link = _make_invite(room.chat_id, room.audience)
        if not link:
            flash('Не удалось получить новую ссылку. Проверьте права Telegram-бота.', 'danger')
            return redirect(url_for('activity_chats.index'))
        room.invite_link = link
        room.active = True
        db.session.commit()
        try:
            invite_existing_participants(room)
        except Exception:
            logger.exception('Failed to enqueue participant links for reactivated room %s', room.id)
            flash('Чат включён, но автоматическая очередь приглашений недоступна.', 'warning')
            return redirect(url_for('activity_chats.index'))
    flash('Постоянный чат снова подключён.', 'success')
    return redirect(url_for('activity_chats.index'))


@activity_chat_bp.post('/activity-chats/<int:chat_id>/message')
@login_required
def post_message(current_user, chat_id):
    room = db.get_or_404(SharedActivityChat, chat_id)
    if not may_write_room(current_user, room):
        abort(403)
    body = ' '.join((request.form.get('body') or '').split())
    if not 1 <= len(body) <= 1800:
        flash('Сообщение должно содержать от 1 до 1800 символов.', 'warning')
        return redirect(url_for('activity_chats.index'))
    from services.telegram import send_tg
    sender = current_user.full_name or current_user.email
    ok = send_tg(room.chat_id, '<b>' + html.escape(sender) + '</b>\n' + html.escape(body))
    flash('Сообщение отправлено в общий чат.' if ok else 'Telegram не подтвердил доставку. Проверьте права бота.',
          'success' if ok else 'danger')
    return redirect(url_for('activity_chats.index'))


