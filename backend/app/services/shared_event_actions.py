"""Cross-platform event actions for authenticated student accounts.

Telegram continues to use its existing rich cards; VK and MAX call this
shared DB-backed service and expose the same event-date and refusal actions.
"""
from datetime import datetime
from database import (db, EventQuota, EventDay, DayParticipation, EventQuotaDecline,
                      DirectionStatus, student_directions, record_activity)


def visible_events(student):
    active = {row.direction_id for row in db.session.execute(
        student_directions.select().where(
            (student_directions.c.student_id == student.id) &
            (student_directions.c.status == DirectionStatus.ACTIVE.value)
        )).fetchall()}
    if not active:
        return []
    return [quota for quota in EventQuota.query.filter_by(is_closed=False, is_published=True)
            .order_by(EventQuota.id.desc()).limit(100).all()
            if any(direction.id in active for direction in quota.directions)]


def event_for_student(student, quota_id):
    return next((q for q in visible_events(student) if q.id == int(quota_id)), None)


def event_detail(student, quota_id):
    """Render the bot event card using the same key fields as the event panel."""
    quota = event_for_student(student, quota_id)
    if quota is None:
        return 'Мероприятие недоступно для вашего профиля.'
    decline = EventQuotaDecline.query.filter_by(quota_id=quota.id, student_id=student.id).first()
    lines = [f'🎟 {quota.event_title}', f'📍 Место: {quota.location or "Место уточняется"}']
    if quota.time_range:
        lines.append('🕒 Время: ' + quota.time_range)
    lines.append(f'👥 Мест: {quota.total_places}')
    dates = [f'📅 {day.date:%d.%m.%Y %H:%M}' for day in quota.days]
    if dates:
        lines.append('\nДаты мероприятия:\n' + '\n'.join(dates))
    lines.append('\n📝 Описание:\n' + (quota.event_description.strip()[:900] if quota.event_description else 'Без описания'))
    if quota.dress_code:
        lines.append('👔 Дресс-код: ' + quota.dress_code)
    if quota.functionality:
        lines.append('ℹ️ Дополнительно: ' + quota.functionality.strip()[:500])
    if decline:
        lines.append('\n⛔ Оформлен отказ от мероприятия. Действие «Вернуться» его отменит.')
    else:
        lines.append('\nВаша запись:')
        for day in quota.days:
            joined = DayParticipation.query.filter_by(student_id=student.id, day_id=day.id).first()
            joined = joined and joined.status != 'cancelled'
            lines.append(f'• {day.date:%d.%m.%Y} — ' + ('вы записаны' if joined else f'свободно мест: {day.available_places()}'))
    return '\n'.join(lines)


def join_event(student, quota_id, date_text, platform='vk'):
    try:
        date = datetime.strptime(date_text, '%Y-%m-%d').date()
    except ValueError:
        return 'Укажите дату в формате ГГГГ-ММ-ДД.'
    quota = event_for_student(student, quota_id)
    if quota is None:
        return 'Мероприятие недоступно: требуется активное участие в направлении.'
    if EventQuotaDecline.query.filter_by(quota_id=quota.id, student_id=student.id).first():
        return 'Сначала отмените отказ от мероприятия.'
    day = next((item for item in quota.days if item.date.date() == date), None)
    if day is None or day.date.date() < datetime.utcnow().date():
        return 'Эта дата недоступна для записи.'
    current = DayParticipation.query.filter_by(student_id=student.id, day_id=day.id).first()
    if current and current.status != 'cancelled':
        return 'Вы уже записаны на этот день.'
    if day.available_places() <= 0:
        return 'Свободных мест на эту дату нет.'
    if current:
        current.status = 'registered'
    else:
        db.session.add(DayParticipation(student_id=student.id, day_id=day.id, status='registered'))
    record_activity('bot_event_registered', f'Запись на мероприятие через {platform}',
                    student_id=student.id, quota_id=quota.id)
    db.session.commit()
    try:
        from services.activity_chats import queue_student_invite
        queue_student_invite('event', quota.id, student)
    except Exception:
        import logging
        logging.getLogger(__name__).exception('Could not queue event chat invitation')
    return f'✅ Запись подтверждена: {quota.event_title}, {day.date:%d.%m.%Y}.'


def decline_event(student, quota_id, reason, platform='vk'):
    quota = event_for_student(student, quota_id)
    if not quota:
        return 'Мероприятие недоступно.'
    reason = (reason or '').strip()
    if not 5 <= len(reason) <= 2000:
        return 'Укажите причину отказа от 5 до 2000 символов.'
    existing = EventQuotaDecline.query.filter_by(quota_id=quota.id, student_id=student.id).first()
    if existing:
        return 'Отказ от этого мероприятия уже сохранён.'
    db.session.add(EventQuotaDecline(quota_id=quota.id, student_id=student.id, reason=reason))
    for day in quota.days:
        participation = DayParticipation.query.filter_by(student_id=student.id, day_id=day.id).first()
        if participation and participation.status != 'cancelled':
            participation.status = 'cancelled'
    record_activity('bot_quota_declined', f'Отказ от мероприятия через {platform}',
                    student_id=student.id, quota_id=quota.id)
    db.session.commit()
    return '✅ Отказ сохранён. Организаторы смогут увидеть указанную причину.'


def return_to_event(student, quota_id, platform='vk'):
    quota = event_for_student(student, quota_id)
    if not quota:
        return 'Мероприятие недоступно.'
    existing = EventQuotaDecline.query.filter_by(quota_id=quota.id, student_id=student.id).first()
    if not existing:
        return 'Отказ от участия уже отсутствует.'
    db.session.delete(existing)
    record_activity('bot_quota_decline_reversed', f'Возврат к мероприятию через {platform}',
                    student_id=student.id, quota_id=quota.id)
    db.session.commit()
    return '✅ Отказ отменён. Вы можете выбрать доступную дату.'
