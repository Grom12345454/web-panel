import html
import json
import logging
from datetime import datetime, timedelta
import requests
from database import db, Student, User, Direction, DirectionQuestion, StudentLeadership, DirectionStatus, EducationType, UserRole, ApplicationDecision, student_directions, record_activity
from config import settings

logger=logging.getLogger(__name__)

def telegram_api(method,payload,attempts=3,timeout=10):
    if not settings.BOT_TOKEN: return None
    url=f"https://api.telegram.org/bot{settings.BOT_TOKEN}/{method}"
    for attempt in range(attempts):
        try:
            r=requests.post(url,json=payload,timeout=timeout); data=r.json()
            if data.get('ok'): return data
            if r.status_code==429 and attempt<attempts-1:
                import time; time.sleep(min(int((data.get('parameters') or {}).get('retry_after',1)),5)); continue
            return None
        except Exception as exc:
            logger.warning('Telegram %s network error (%s)',method,type(exc).__name__)
    return None

def education_label(value): return 'Колледж' if value=='college' else 'Институт' if value=='institute' else 'Все'

def leader_records_for(direction_id, education_type):
    rows=StudentLeadership.query.filter_by(direction_id=direction_id).all()
    return [r for r in rows if r.student and r.student.tg_id and r.student.tg_id>0 and r.education_type in {education_type,'all'}]

def leader_telegram_ids_for(direction_id, education_type):
    """Return Telegram IDs of the main direction leaders, without duplicates.

    A leader can be represented either by a StudentLeadership assignment or by a
    website account with role=leader and an assigned direction. This keeps the
    website, Mini App and Telegram bot on the same notification path.
    """
    ids=[]

    # Include only people authorized to decide on this applicant's cohort.
    from services.permissions import can_manage_direction
    for record in leader_records_for(direction_id, education_type):
        if not can_manage_direction(record.student.tg_id, direction_id, education_type):
            continue
        try:
            tg_id=int(record.student.tg_id)
        except (TypeError, ValueError):
            continue
        if tg_id > 0 and tg_id not in ids:
            ids.append(tg_id)

    try:
        from services.permissions import has_global_council_access
        for student in Student.query.all():
            if student.tg_id and student.tg_id > 0 and has_global_council_access(student_id=student.id, education_type=education_type):
                if int(student.tg_id) not in ids:
                    ids.append(int(student.tg_id))
    except Exception:
        logger.exception("Unable to resolve global council leaders")

    # Also notify a website LEADER account assigned to this direction.
    try:
        users=User.query.filter_by(
            role=UserRole.LEADER.value,
            assigned_direction_id=direction_id,
        ).all()
    except Exception:
        users=[]

    for user in users:
        if not user.tg_id:
            continue
        # A leader account may be scoped to a specific education contour.
        scope=getattr(user,'assigned_education_type','all') or 'all'
        if scope not in {education_type,'all'}:
            continue
        try:
            tg_id=int(user.tg_id)
        except (TypeError, ValueError):
            continue
        if tg_id > 0 and tg_id not in ids:
            ids.append(tg_id)

    return ids

def notify_leaders_about_application(student, direction):
    """Send a real Telegram bot notification to the leader of the direction."""
    if not student or not direction: return 0
    leader_ids=leader_telegram_ids_for(direction.id,student.education_type)
    sent=0
    markup={'inline_keyboard':[[
        {'text':'✅ Принять и активировать','callback_data':f'app:approve:{student.id}:{direction.id}'},
        {'text':'❌ Отклонить','callback_data':f'app:reject:{student.id}:{direction.id}'},
    ]]}
    link = get_application(student.id, direction.id)
    extra = {}
    try:
        extra = json.loads((link.extra_data if link else None) or "{}")
    except (TypeError, ValueError):
        extra = {}
    answers = extra.get("answers") or []
    qa_text = ""
    base_text = (f"📥 <b>Новая заявка в направление</b>\n\n"
                 f"👤 <b>Студент:</b> {html.escape(student.full_name)}\n"
                 f"🎓 <b>Контур:</b> {education_label(student.education_type)}\n"
                 f"👥 <b>Группа:</b> {html.escape(student.group or '—')}\n"
                 f"📞 <b>Телефон:</b> {html.escape(student.phone or '—')}\n"
                 f"📌 <b>Направление:</b> {html.escape((direction.icon or '✦')+' '+direction.name)}\n")
    if answers:
        qa_text = "\n🧾 <b>Дополнительные вопросы</b>"
        omitted = False
        for item in answers:
            question = html.escape(str(item.get("question") or "Вопрос"))
            answer = html.escape(str(item.get("answer") or "—"))
            entry = f"\n<b>Вопрос:</b> {question}\n<b>Ответ студента:</b> {answer}"
            if len(base_text) + len(qa_text) + len(entry) + 100 > 3900:
                omitted = True
                break
            qa_text += entry
        if omitted:
            qa_text += "\n\n<i>Остальные ответы смотрите в Student App.</i>"
    text = base_text + qa_text + "\n\nВыберите действие ниже:"
    for tg_id in leader_ids:
        if telegram_api('sendMessage',{'chat_id':tg_id,'text':text,'parse_mode':'HTML','reply_markup':markup}):
            sent+=1
    if leader_ids and sent == 0:
        logger.warning('Application notification could not be delivered for direction=%s', direction.id)
    if not leader_ids:
        logger.warning('No Telegram leader configured for direction=%s education=%s', direction.id, student.education_type)
    # Alert linked VK/MAX leaders through their authenticated accounts too.
    # Every recipient is independently checked with the same applicant cohort
    # policy as Telegram's approve/reject actions.
    try:
        from database import MessengerIdentity
        from services.permissions import can_manage_direction
        from services.messenger_transports import send_message
        for account in MessengerIdentity.query.all():
            leader = Student.query.get(account.student_id)
            if leader and can_manage_direction(leader.tg_id, direction.id, student.education_type):
                if send_message(account.platform, account.external_user_id,
                                f'📥 Новая заявка: {student.full_name} · {direction.name} · '
                                f'{education_label(student.education_type)}. Для рассмотрения: /inbox'):
                    sent += 1
    except Exception:
        logger.exception('Could not notify VK/MAX leadership about application')
    return sent

def student_council_direction():
    """Return the Volunteer Team direction (legacy function name kept for compatibility)."""
    return (Direction.query.filter_by(code='STUDCOUNCIL').first()
            or Direction.query.filter(Direction.name.ilike('%волонтёрка%')).first()
            or Direction.query.filter(Direction.name.ilike('%волонтерка%')).first()
            or Direction.query.filter(Direction.name.ilike('%студенческий совет%')).first()
            or Direction.query.filter(Direction.name.ilike('%студсовет%')).first())

def register_student_with_council(tg_id, full_name, group, phone, education_type, email=None, telegram_username=None, source="telegram"):
    """Create a profile; reject duplicate normalized full names and phone numbers."""
    from services.student_validation import student_duplicate_message

    existing = Student.query.filter_by(tg_id=tg_id).first()
    if existing and existing.council_registered:
        return None, None, 'Профиль уже зарегистрирован.'

    clean_name = " ".join((full_name or "").split())[:255]
    clean_phone = (phone or "").strip()[:30]
    duplicate_error = student_duplicate_message(clean_name, clean_phone, exclude_id=existing.id if existing else None)
    if duplicate_error:
        return None, None, duplicate_error

    if existing:
        # The scientific author keeps the same ID, submissions and messenger links.
        student = existing
        student.full_name = clean_name
        student.group = (group or '').strip()[:50]
        student.phone = clean_phone
        student.education_type = education_type
        student.council_registered = True
        if telegram_username:
            student.telegram_username = telegram_username.strip().lstrip('@')[:255]
    else:
        student = Student(
            tg_id=tg_id, full_name=clean_name, group=(group or "").strip()[:50],
            phone=clean_phone, email=None, education_type=education_type,
            council_registered=True,
            telegram_username=(telegram_username or "").strip().lstrip("@")[:255] or None
        )
    try:
        db.session.add(student)
        db.session.flush()
        activity_action = 'bot_profile_created' if source == 'telegram' else ('student_app_profile_created' if source == 'student_app' else 'profile_created')
        activity_source = {
            'telegram': 'Telegram-бот', 'student_app': 'Telegram Web App',
            'vk': 'VK', 'max': 'MAX', 'web': 'веб-сайт',
        }.get(str(source or '').lower(), 'источник не указан')
        record_activity(activity_action, f'Создан профиль студента через {activity_source}.', student_id=student.id)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return student, None, None

def get_application(student_id, direction_id):
    return db.session.execute(student_directions.select().where(
        (student_directions.c.student_id == student_id) &
        (student_directions.c.direction_id == direction_id)
    )).fetchone()


def latest_application_decision(student_id, direction_id):
    return ApplicationDecision.query.filter_by(
        student_id=student_id, direction_id=direction_id
    ).order_by(ApplicationDecision.id.desc()).first()


def active_application_block(student_id, direction_id, now=None):
    """Return the newest rejection if its seven-day restriction is still active."""
    now = now or datetime.utcnow()
    latest = latest_application_decision(student_id, direction_id)
    if (latest and latest.decision == DirectionStatus.REJECTED.value
            and latest.cleared_at is None and latest.blocked_until
            and latest.blocked_until > now):
        return latest
    return None


def application_block_message(block):
    if not block or not block.blocked_until:
        return "Повторная подача доступна сейчас."
    return ("Повторно подать заявление можно после "
            f"{block.blocked_until.strftime('%d.%m.%Y в %H:%M')}.")


def can_user_manage_direction(user_id, direction_id, education_type):
    """Web accounts and Telegram leadership use the same applicant-level policy."""
    user = User.query.get(user_id) if user_id else None
    if not user:
        return False
    if user.role == UserRole.SUPER_ADMIN.value:
        direction = Direction.query.get(direction_id) if direction_id else None
        return bool(direction and not getattr(direction, 'is_archived', False))
    if user.role == UserRole.STAFF.value:
        from services.staff_access import allowed
        return allowed(user, direction_id, 'applications', 'manage')
    if user.role != UserRole.LEADER.value:
        return False
    if user.tg_id:
        from services.permissions import can_manage_direction, leadership_rows_for_tg
        _, rows = leadership_rows_for_tg(user.tg_id)
        if rows:  # Explicit appointed roles override stale account direction limits.
            return can_manage_direction(user.tg_id, direction_id, education_type)
    # Fallback for older web-only accounts without an appointed StudentLeadership role.
    return bool(user.assigned_direction_id is not None
                and int(user.assigned_direction_id) == int(direction_id)
                and (education_type is None or (user.assigned_education_type or 'all') in {'all', education_type}))


def available_application_directions(student):
    """Return directions this student may currently apply to.

    Keep messenger pickers consistent: an existing pending/active/interview
    application is not offered again, and a rejected application remains hidden
    for the full seven-day restriction even if its membership row was removed.
    """
    if not student or not student.council_registered:
        return []
    links = db.session.execute(
        student_directions.select().where(student_directions.c.student_id == student.id)
    ).fetchall()
    link_by_direction = {row.direction_id: row for row in links}
    directions = Direction.query.order_by(Direction.name).all()
    available = []
    for direction in directions:
        if not direction.available_for(student.education_type):
            continue
        if active_application_block(student.id, direction.id):
            continue
        link = link_by_direction.get(direction.id)
        if link is None or link.status == DirectionStatus.REJECTED.value:
            available.append(direction)
    return available


def submit_application(student, direction, source='web', answers=None):
    """Submit a new application and persist answers to direction-specific questions."""
    if not student or not direction:
        return False, 'Студент или направление не найдены.'
    if not student.council_registered:
        return False, 'Для заявки в направление сначала зарегистрируйтесь в студенческом совете.'
    now = datetime.utcnow()
    block = active_application_block(student.id, direction.id, now)
    if block:
        return False, application_block_message(block)
    link = get_application(student.id, direction.id)
    if link and link.status != DirectionStatus.REJECTED.value:
        return False, 'Заявка по этому направлению уже существует.'

    supplied = answers or {}
    if isinstance(supplied, list):
        supplied = {str(item.get('question_id')): item.get('answer', '') for item in supplied if isinstance(item, dict)}
    elif not isinstance(supplied, dict):
        return False, 'Ответы на дополнительные вопросы имеют неверный формат.'

    question_rows = DirectionQuestion.query.filter_by(direction_id=direction.id).order_by(DirectionQuestion.sort_order, DirectionQuestion.id).all()
    answer_rows = []
    for question in question_rows:
        value = ' '.join(str(supplied.get(str(question.id), supplied.get(question.id, '')) or '').split())[:2000]
        if question.is_required and not value:
            return False, f'Ответьте на обязательный вопрос: «{question.question_text}».'
        if value:
            answer_rows.append({
                'question_id': question.id,
                'question': question.question_text,
                'answer': value,
            })
    extra_json = json.dumps({'answers': answer_rows}, ensure_ascii=False)

    if link:
        db.session.execute(student_directions.update().where(
            (student_directions.c.student_id == student.id) &
            (student_directions.c.direction_id == direction.id)
        ).values(status=DirectionStatus.PENDING.value, joined_at=now, extra_data=extra_json))
    else:
        db.session.execute(student_directions.insert().values(
            student_id=student.id, direction_id=direction.id,
            status=DirectionStatus.PENDING.value, joined_at=now, extra_data=extra_json
        ))
    source_label = {'telegram': 'Telegram-бот', 'student_app': 'Telegram Web App', 'web': 'веб-сайт', 'vk': 'VK', 'max': 'MAX'}.get(source, source)
    description = f'Студент подал заявление в направление «{direction.name}» через {source_label}.'
    if answer_rows:
        description += f' Ответов на дополнительные вопросы: {len(answer_rows)}.'
    record_activity('bot_application_submitted', description, student_id=student.id, direction_id=direction.id)
    db.session.commit()
    from services.staff_alerts import notify_subscribers
    notify_subscribers(direction.id, 'applications', f'📥 Новое заявление в направление «{direction.name}».')
    try:
        notify_leaders_about_application(student, direction)
    except Exception:
        logger.exception('Application notification failed for source=%s', source)
    return True, 'Заявление отправлено на рассмотрение.'

def create_join_request_links(direction):
    from services.telegram import create_direction_invite_links
    return create_direction_invite_links(direction.id)

def notify_approval(student,direction,send_invites=True,immediately_active=False):
    from services.telegram import send_direction_invites
    payload={'direction':f"{direction.icon or '✦'} {direction.name}"}
    # Direct send instead of queue so the response reaches Telegram immediately.
    if immediately_active:
        text=(f"✅ <b>Вы приняты в направление</b>\n\n"
              f"Направление: <b>{html.escape(payload['direction'])}</b>\n"
              "Ваш статус: <b>активный участник</b>. Доступ к направлению открыт.")
    else:
        text=f"✅ <b>Вы приняты в направление</b>\n\nНаправление: <b>{html.escape(payload['direction'])}</b>\nВаш статус: <b>активный участник</b>. Доступ открыт."
    # Give Telegram users a native Mini App button so the approval message
    # opens their personal Student App account directly (not a generic browser tab).
    app_url = None
    try:
        from services.messenger_transports import _public_url, vk_app_url, max_app_url, send_message
        app_url = _public_url(settings.WEBAPP_URL)
    except Exception:
        logger.exception('Could not resolve Student App launch URL')
        vk_app_url = max_app_url = None
        send_message = None
    if student.tg_id and student.tg_id>0:
        payload={'chat_id':int(student.tg_id),'text':text,'parse_mode':'HTML'}
        if app_url:
            payload['reply_markup']={'inline_keyboard':[[{
                'text':'Открыть личный кабинет', 'web_app':{'url':app_url}
            }]]}
        telegram_api('sendMessage',payload)
    # VK/MAX get their own platform launch URL so the signed launch identity is
    # retained by the native mini-app client.
    try:
        from database import MessengerIdentity
        from services.messenger_transports import send_message, vk_app_url, max_app_url
        for link in MessengerIdentity.query.filter_by(student_id=student.id).all():
            launch_url = vk_app_url() if link.platform == 'vk' else max_app_url() if link.platform == 'max' else None
            plain = f'✅ Вы приняты в направление «{direction.name}». Статус: активный участник.'
            if launch_url:
                plain += f'\n\nОткрыть личный кабинет: {launch_url}'
            send_message(link.platform, link.external_user_id, plain)
    except Exception:
        logger.exception('Could not notify linked messenger accounts about approval')
    return send_direction_invites(student,direction) if send_invites else 0

def set_application_status(student_id, direction_id, new_status, actor_tg_id=None,
                           reason=None, actor_user_id=None, source=None):
    link = get_application(student_id, direction_id)
    student = Student.query.get(student_id)
    direction = Direction.query.get(direction_id)
    if not link or not student or not direction:
        return False, 'Заявка не найдена.', 0

    source = source or ('telegram' if actor_tg_id else ('web' if actor_user_id else 'system'))
    if new_status == DirectionStatus.REJECTED.value:
        reason = ' '.join(str(reason or '').split())[:2000]
        if len(reason) < 5:
            return False, 'Укажите причину отказа (не менее 5 символов).', 0
        if source in {'telegram', 'student_app'}:
            official = {'Учёба или экзамены', 'Здоровье', 'Семейные обстоятельства', 'Изменились планы'}
            is_other = reason.startswith('Другая причина: ') and len(reason.removeprefix('Другая причина: ').strip()) >= 5
            if reason not in official and not is_other:
                return False, 'Выберите официальную причину отказа. Для «Другой причины» обязательны пояснения от 5 символов.', 0

    if actor_tg_id:
        from services.permissions import can_manage_direction, has_global_council_access
        if not can_manage_direction(actor_tg_id, direction_id, student.education_type):
            return False, 'Нет прав для этого направления и учебного контура.', 0
    elif actor_user_id and not can_user_manage_direction(actor_user_id, direction_id, student.education_type):
        return False, 'Нет прав для этого направления и учебного контура.', 0

    # There is no intermediate approved state: a positive decision means active membership.
    if new_status == "approved":
        new_status = DirectionStatus.ACTIVE.value
    if link.status not in {DirectionStatus.PENDING.value, DirectionStatus.INTERVIEW.value} and new_status in {
        DirectionStatus.ACTIVE.value, DirectionStatus.REJECTED.value
    }:
        return False, 'Заявка уже обработана.', 0

    previous_status = link.status
    now = datetime.utcnow()
    blocked_until = now + timedelta(days=7) if new_status == DirectionStatus.REJECTED.value else None
    db.session.execute(student_directions.update().where(
        (student_directions.c.student_id == student_id) &
        (student_directions.c.direction_id == direction_id)
    ).values(status=new_status))

    # Keep a durable decision history in the same database as the application.
    decision = ApplicationDecision(
        student_id=student.id, direction_id=direction.id, decision=new_status,
        reason=reason if new_status == DirectionStatus.REJECTED.value else None,
        source=source, actor_tg_id=actor_tg_id, actor_user_id=actor_user_id,
        created_at=now, blocked_until=blocked_until,
    )
    db.session.add(decision)
    if actor_tg_id:
        actor_label = (f"{source.upper()} · студент #{Student.query.filter_by(tg_id=actor_tg_id).first().id}"
                       if source in {'vk', 'max'} else f"Telegram ID {actor_tg_id}")
    elif actor_user_id:
        actor_user = User.query.get(actor_user_id)
        actor_label = f"учётная запись {actor_user.email}" if actor_user else f"пользователь #{actor_user_id}"
    else:
        actor_label = "система"
    decision_text = f'Решение ({source}, {actor_label}): статус заявления изменён с «{previous_status}» на «{new_status}».'
    if reason and new_status == DirectionStatus.REJECTED.value:
        decision_text += f' Причина отказа: {reason}. Повторная подача доступна после {blocked_until.strftime("%d.%m.%Y %H:%M")}.'
    record_activity('application_status_changed', decision_text, student_id=student.id, direction_id=direction.id)
    # Keep all approval/rejection decisions in the website's Telegram activity log,
    # regardless of whether the leader acted from Telegram, Web App, or the site.
    action = 'bot_application_rejected' if new_status == DirectionStatus.REJECTED.value else 'bot_application_approved'
    label = 'отклонена' if new_status == DirectionStatus.REJECTED.value else 'принята и активирована'
    source_label = {
        'telegram': 'Telegram-бот',
        'student_app': 'Telegram Web App',
        'web': 'веб-сайт',
        'vk': 'VK',
        'max': 'MAX',
        'system': 'системный процесс',
    }.get(source, source)
    description = f'Заявка {label} через {source_label}. Направление: «{direction.name}». {actor_label}.'
    if reason and new_status == DirectionStatus.REJECTED.value:
        description += f' Причина: {reason}. Повторная подача после {blocked_until.strftime("%d.%m.%Y %H:%M")}.'
    record_activity(action, description, student_id=student.id, direction_id=direction.id)
    db.session.commit()

    invite_count = 0
    if new_status == DirectionStatus.ACTIVE.value:
        invite_count = notify_approval(student, direction, True, immediately_active=True)
    elif new_status == DirectionStatus.REJECTED.value:
        from services.telegram import remove_student_from_direction_chats
        remove_student_from_direction_chats(student, direction)
        retry_date = blocked_until.strftime('%d.%m.%Y в %H:%M')
        if student.tg_id and student.tg_id > 0:
            text = (f'❌ <b>Заявка отклонена</b>\n\n'
                    f'Направление: <b>{html.escape(direction.name)}</b>\n'
                    f'<b>Причина:</b> {html.escape(reason)}\n\n'
                    f'Повторно подать заявление можно после <b>{retry_date}</b>.')
            telegram_api('sendMessage', {'chat_id': int(student.tg_id), 'text': text, 'parse_mode': 'HTML'})
        try:
            from database import MessengerIdentity
            from services.messenger_transports import send_message
            for account in MessengerIdentity.query.filter_by(student_id=student.id).all():
                send_message(account.platform, account.external_user_id,
                             f'❌ Заявка «{direction.name}» отклонена. Причина: {reason}. '
                             f'Повторная подача после {retry_date}.')
        except Exception:
            logger.exception('Could not notify VK/MAX about rejection')
    if new_status == DirectionStatus.ACTIVE.value:
        return True, 'Студент принят и сразу активирован.', invite_count
    if new_status == DirectionStatus.REJECTED.value:
        return True, f'Заявка отклонена. Повторная подача доступна через 7 дней (после {blocked_until.strftime("%d.%m.%Y %H:%M")}).', invite_count
    return True, 'Статус обновлён.', invite_count



