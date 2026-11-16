"""Main-admin-provisioned all-direction, single-direction, and observer accounts."""
from datetime import datetime, timedelta
import re
import uuid
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for, session, jsonify
from sqlalchemy.orm import selectinload
from database import (db, User, UserRole, Direction, DirectionStatus, StaffGrant, Student, StudentLeadership, ApplicationDecision,
                      student_directions, Lesson, EventQuota, EventDay, DayParticipation, QuotaDirection,
                      EventQuotaChat, EventQuotaDecline, EventLeader, CompetitionAnnouncement,
                      StudentActivity, BotDeliveryJob, ActivityChat, AdministrativeOrder, OrderDeliveryJob,
                      hash_password)
from services.staff_access import allowed, direction_ids, SECTIONS, NOTIFICATION_OPTIONS, DEFAULT_EMPLOYEE_GRANTS
from database.helpers import get_quota_direction_ids

# These are the only non-admin account types provisioned from this screen.
# The main administrator remains a separate, protected system account.
ACCOUNT_RANKS = {'employee_all': 'Сотрудник — все направления', 'employee': 'Сотрудник одного направления', 'observer': 'Наблюдатель'}
staff_bp = Blueprint('staff', __name__, url_prefix='/staff')


def login_required(f):
    from web_app import login_required as decorator
    return decorator(f)


def _admin():
    user = User.query.get(session.get('user_id'))
    if not user or user.role != UserRole.SUPER_ADMIN.value or not user.is_active:
        abort(403)
    return user


def _form_account(user):
    login = (request.form.get('login') or '').strip()
    full_name = (request.form.get('full_name') or '').strip()
    position = (request.form.get('position') or '').strip()
    phone = (request.form.get('phone') or '').strip()
    email = (request.form.get('contact_email') or '').strip().lower()
    # Employee accounts use the panel login/password only. Existing confirmed
    # Telegram numeric IDs are retained for OTP and notifications; usernames
    # are not part of employee identity or account provisioning.
    tg_id = str(user.tg_id) if user and user.tg_id else ''
    password = request.form.get('password') or ''
    rank = request.form.get('staff_rank', 'employee')
    home_direction_id = request.form.get('home_direction_id', type=int)
    promoted_student_id = request.form.get('student_id', type=int)
    if rank not in ACCOUNT_RANKS:
        raise ValueError('Некорректная роль сотрудника.')
    # There are three repeatable panel account modes: all-directions employees,
    # one-direction employees, and global read-only observers. The main
    # administrator is a separate protected system role and is never created here.
    if rank in {'observer', 'employee_all'}:
        home_direction_id = None
    if rank == 'employee' and (
        not home_direction_id or not Direction.query.filter_by(id=home_direction_id, is_archived=False).first()
    ):
        raise ValueError('Для сотрудника направления выберите одно действующее направление.')
    if home_direction_id and not Direction.query.filter_by(id=home_direction_id, is_archived=False).first():
        raise ValueError('Выбранное направление не найдено или уже находится в архиве.')
    student = Student.query.get(promoted_student_id) if promoted_student_id else None
    if promoted_student_id and not student:
        raise ValueError('Студент не найден.')
    if user and user.student_id and promoted_student_id != user.student_id:
        raise ValueError('Отвязка или замена профиля студента запрещена; создайте отдельную учётную запись.')
    if student and User.query.filter(User.student_id == student.id,
                                     User.id != (user.id if user else -1)).first():
        raise ValueError('Этот студент уже повышен до сотрудника.')
    if student:
        if full_name and full_name != student.full_name:
            raise ValueError('Имя повышенного студента должно совпадать с карточкой студента.')
        full_name = student.full_name
        tg_id = str(student.tg_id) if student.tg_id and student.tg_id > 0 else ''
        email = email or (student.email or '')
        phone = phone or (student.phone or '')
    if rank == 'observer':
        position = ACCOUNT_RANKS[rank]
    elif not position:
        position = ACCOUNT_RANKS[rank]
    if not re.fullmatch(r'[a-zA-Z0-9_.-]{3,50}', login):
        raise ValueError('Логин: от 3 до 50 латинских букв, цифр, «_», «.» или «-».')
    if not 3 <= len(full_name) <= 255 or not 2 <= len(position) <= 150 or len(phone) > 40:
        raise ValueError('Укажите ФИО и должность сотрудника.')
    if email and (len(email) > 255 or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email)):
        raise ValueError('Укажите корректную рабочую почту сотрудника.')
    if password:
        from services.password_policy import validate_new_password
        password_error = validate_new_password(password, login)
        if password_error:
            raise ValueError('Пароль не соответствует требованиям ИБ: ' + password_error)
    if user is None and not password:
        raise ValueError('Укажите временный пароль для нового сотрудника.')
    match_login = User.query.filter_by(email=login).first()
    match_tg = User.query.filter_by(tg_id=int(tg_id)).first() if tg_id else None
    # Legacy direction leaders sometimes already own the same Telegram identity.
    # Superadmin explicitly promotes that exact student and replaces the old panel
    # role, invalidating earlier sessions instead of creating a second identity.
    if user is None and student and match_tg and match_tg.role == UserRole.LEADER.value:
        user = match_tg
    if ((match_login and match_login.id != getattr(user, 'id', None)) or
        (match_tg and match_tg.id != getattr(user, 'id', None))):
        raise ValueError('Логин или привязанная Telegram-учётная запись уже используется другим сотрудником.')
    is_new_account = user is None
    was_leader_account = bool(user and user.role == UserRole.LEADER.value)

    if user is None:
        user = User(email=login, role=UserRole.STAFF.value, password_hash=hash_password(password))
        db.session.add(user)
    elif user.role not in {UserRole.STAFF.value, UserRole.OBSERVER.value, UserRole.LEADER.value} or (user.role == UserRole.LEADER.value and not student):
        raise ValueError('Можно изменить только сотрудника, наблюдателя или связанного со студентом руководителя.')
    # The selected role is persisted in User.role, not merely displayed as a label.
    # Changing a role increments auth_version below and invalidates old sessions.
    user.role = UserRole.OBSERVER.value if rank == 'observer' else UserRole.STAFF.value
    user.email, user.full_name, user.position, user.phone = login, full_name, position, phone
    user.contact_email = email or None
    user.tg_id = int(tg_id) if tg_id else None
    user.student_id = promoted_student_id
    user.staff_rank = rank
    user.assigned_direction_id = home_direction_id
    user.is_active = request.form.get('is_active') == '1'
    user.notifications = ','.join(key for key in NOTIFICATION_OPTIONS if key in request.form.getlist('notifications'))
    user.auth_version = (user.auth_version or 0) + 1
    if password:
        user.password_hash = hash_password(password)
    if is_new_account or was_leader_account or password:
        user.must_change_password = True
    db.session.flush()
    # Formal student leadership positions are managed separately by the superadmin.
    StaffGrant.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    # Observer inherits global read-only visibility and receives no grants.
    # The all-directions employee receives explicit saved values for current areas
    # (including 'none'); future directions inherit the same default profile. A
    # direction employee receives the default profile for exactly one area.
    if user.role != UserRole.OBSERVER.value:
        if rank == 'employee_all':
            target_direction_ids = [row.id for row in Direction.query.filter_by(is_archived=False).all()]
            if not target_direction_ids:
                raise ValueError('Невозможно создать сотрудника: нет действующих направлений.')
        elif rank == 'employee':
            active_home = Direction.query.filter_by(id=home_direction_id, is_archived=False).first()
            if not active_home:
                raise ValueError('Основное направление сотрудника должно быть действующим.')
            target_direction_ids = [home_direction_id]
        else:
            target_direction_ids = []
        for direction_id in target_direction_ids:
            for section in SECTIONS:
                field = f'grant_{direction_id}_{section}'
                fallback = DEFAULT_EMPLOYEE_GRANTS.get(section, 'none') if is_new_account else 'none'
                value = request.form.get(field, fallback)
                if value in ('view', 'manage') or rank == 'employee_all':
                    # Store explicit 'none' too, so it remains distinguishable
                    # from a future direction that inherits the default profile.
                    db.session.add(StaffGrant(user_id=user.id, direction_id=direction_id,
                                              section=section, access=value if value in ('view', 'manage') else 'none'))
    return user


@staff_bp.route('/accounts', methods=['GET', 'POST'])
@login_required
def accounts(current_user):
    _admin()
    if request.method == 'POST':
        raw_id = request.form.get('user_id')
        try:
            user = User.query.get(int(raw_id)) if raw_id else None
            if raw_id and not user:
                abort(404)
            account = _form_account(user)
            db.session.commit()
            if request.accept_mimetypes.best == 'application/json':
                return jsonify({'ok': True, 'id':account.id, 'name':account.full_name})
            flash(f'Сотрудник «{account.full_name}» сохранён. Права вступили в силу.', 'success')
            return redirect(url_for('staff.accounts'))
        except ValueError as exc:
            db.session.rollback()
            if request.accept_mimetypes.best == 'application/json':
                return jsonify({'ok': False, 'error': str(exc)}), 400
            flash(str(exc), 'danger')
        except Exception as exc:
            from sqlalchemy.exc import IntegrityError
            db.session.rollback()
            if isinstance(exc, IntegrityError):
                if request.accept_mimetypes.best == 'application/json':
                    return jsonify({'ok': False, 'error': 'Логин уже используется.'}), 409
                flash('Дублирующийся логин.', 'danger')
            else:
                raise
    edit_id = request.args.get('edit', type=int)
    editing = User.query.get(edit_id) if edit_id else None
    if editing and editing.role not in {UserRole.STAFF.value, UserRole.OBSERVER.value}:
        abort(403)
    suggested_student_id = request.args.get('student_id', type=int)
    suggested_student = Student.query.get(suggested_student_id) if (not editing and suggested_student_id is not None) else None
    eligible_students = Student.query.order_by(Student.full_name.asc()).limit(1000).all()
    profile = suggested_student or (Student.query.get(editing.student_id) if editing and editing.student_id else None)
    if profile and not any(item.id == profile.id for item in eligible_students):
        eligible_students.insert(0, profile)
    return render_template('staff/accounts.html',
                           suggested_student=suggested_student,
                           users=User.query.filter(User.role.in_([UserRole.STAFF.value, UserRole.OBSERVER.value])).order_by(User.full_name.asc(), User.id.asc()).all(),
                           editing=editing,
                           grants={(g.direction_id, g.section):g.access for g in editing.grants} if editing else {},
                           directions=Direction.query.filter_by(is_archived=False).order_by(Direction.name).all(),
                           sections=SECTIONS, notification_options=NOTIFICATION_OPTIONS,
                           ranks=ACCOUNT_RANKS, default_employee_grants=DEFAULT_EMPLOYEE_GRANTS,
                           students_for_promotion=eligible_students)


@staff_bp.get('/accounts/<int:user_id>/data')
@login_required
def account_data(current_user, user_id):
    """On-demand edit details, checked server-side; credentials are never returned."""
    _admin()
    user = db.get_or_404(User, user_id)
    if user.role not in {UserRole.STAFF.value, UserRole.OBSERVER.value}:
        abort(403)
    grant_map = {f'{g.direction_id}_{g.section}':g.access for g in user.grants if g.section in SECTIONS}
    if user.role == UserRole.STAFF.value and user.staff_rank == 'employee_all':
        for direction in Direction.query.filter_by(is_archived=False).all():
            for section in SECTIONS:
                grant_map.setdefault(f'{direction.id}_{section}', DEFAULT_EMPLOYEE_GRANTS.get(section, 'none'))
    return jsonify({
        'id': user.id, 'login': user.email, 'full_name': user.full_name or '',
        'position': user.position or '', 'contact_email': user.contact_email or '',
        'phone': user.phone or '',
        'is_active': user.is_active,
        'staff_rank': 'observer' if user.role == UserRole.OBSERVER.value else (user.staff_rank if user.staff_rank in {'employee', 'employee_all'} else 'employee'),
        'home_direction_id': user.assigned_direction_id, 'student_id': user.student_id,
        'notifications': [v for v in (user.notifications or '').split(',') if v in NOTIFICATION_OPTIONS],
        'grants': grant_map,
        'bot_bound': bool(user.tg_id and user.tg_id > 0),
    })


@staff_bp.post('/accounts/password-reset')
@login_required
def request_password_rotation(current_user):
    # Require next-login password rotation for one account or all non-admin panel users.
    _admin()
    scope = (request.form.get('scope') or 'one').strip()
    if scope == 'all':
        targets = User.query.filter(
            User.id != current_user.id,
            User.role.in_([UserRole.STAFF.value, UserRole.OBSERVER.value]),
            User.is_active.is_(True),
        ).all()
        if not targets:
            flash('Нет активных аккаунтов для запроса смены пароля.', 'info')
            return redirect(url_for('staff.accounts'))
        message = f'Обязательная смена пароля запрошена для всех активных пользователей панели: {len(targets)}.'
    else:
        user_id = request.form.get('user_id', type=int)
        target = User.query.get(user_id) if user_id else None
        if (not target or target.id == current_user.id or
                target.role not in {UserRole.STAFF.value, UserRole.OBSERVER.value}):
            abort(404)
        targets = [target]
        message = f'Для пользователя «{target.email}» включена обязательная смена пароля при следующем входе.'
    for target in targets:
        target.must_change_password = True
        target.auth_version = (target.auth_version or 0) + 1
    db.session.commit()
    flash(message, 'success')
    return redirect(url_for('staff.accounts'))


@staff_bp.post('/accounts/<int:user_id>/delete')
@login_required
def delete_account(current_user, user_id):
    _admin()
    account = db.get_or_404(User, user_id)
    if account.role not in {UserRole.STAFF.value, UserRole.OBSERVER.value} or account.id == current_user.id:
        abort(403)
    if request.form.get('confirm_login') != account.email:
        return jsonify({'ok':False, 'error':'Подтвердите логин удаляемого сотрудника.'}), 400
    # Keep student card, works, submitted applications and historical decisions.
    # Only employee identity/grants and automatically created leadership are removed.
    try:
        StudentLeadership.query.filter_by(source_user_id=account.id).delete(synchronize_session=False)
        ApplicationDecision.query.filter_by(actor_user_id=account.id).update(
            {ApplicationDecision.actor_user_id:None}, synchronize_session=False)
        ApplicationDecision.query.filter_by(cleared_by_user_id=account.id).update(
            {ApplicationDecision.cleared_by_user_id:None}, synchronize_session=False)
        db.session.delete(account)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    if request.accept_mimetypes.best == 'application/json':
        return jsonify({'ok':True})
    flash('Учётная запись сотрудника удалена. Данные студента и научных статей сохранены.', 'success')
    return redirect(url_for('staff.accounts'))


@staff_bp.get('/workspace')
@login_required
def workspace(current_user):
    # Employees use the same full dashboard shell as the main administrator.
    # The admin dashboard applies the employee's explicit direction grants
    # before calculating any figures, so this does not expand their access.
    if current_user.role == UserRole.STAFF.value:
        return redirect(url_for('admin.dashboard'))
    if current_user.role != UserRole.SUPER_ADMIN.value:
        return redirect(url_for('admin.dashboard'))
    # The main administrator keeps the dedicated direction drill-down.
    selected = request.args.get('direction', type=int)
    from services.staff_access import direction_ids
    permitted = set().union(*(direction_ids(current_user, section, 'view') for section in SECTIONS))
    directions = Direction.query.filter(Direction.id.in_(permitted), Direction.is_archived.is_(False)).order_by(Direction.name).all() if permitted else []
    if selected not in permitted:
        preferred = getattr(current_user, 'assigned_direction_id', None)
        if current_user.role == UserRole.STAFF.value and getattr(current_user, 'staff_rank', 'employee') == 'employee_all':
            student_scope = direction_ids(current_user, 'students', 'view')
            preferred = preferred if preferred in student_scope else next(
                (direction.id for direction in directions if direction.id in student_scope), preferred
            )
        selected = preferred if preferred in permitted else (directions[0].id if directions else None)
    sections = {sec:allowed(current_user, selected, sec) for sec in SECTIONS}
    students = []
    lessons = []
    events = []
    notifications = []
    if selected and sections["notifications"]:
        from services.site_notifications import visible_notifications
        notifications = visible_notifications(current_user, direction_id=selected, limit=25)[0]
    if selected and (sections['students'] or sections['applications']):
        # Fetch membership links and student profiles in two bulk queries instead
        # of issuing one SELECT per student (the old pattern became very slow for
        # directions with a large roster).
        membership_rows = db.session.execute(
            student_directions.select().where(student_directions.c.direction_id == selected)
        ).all()
        student_ids = {item.student_id for item in membership_rows if item.student_id}
        students_by_id = ({item.id: item for item in Student.query.filter(Student.id.in_(student_ids)).all()}
                          if student_ids else {})
        students = [(students_by_id.get(item.student_id), item.status) for item in membership_rows
                    if item.student_id in students_by_id]
    if selected and sections['lessons']:
        lessons = Lesson.query.filter_by(direction_id=selected).order_by(Lesson.starts_at.desc()).limit(30).all()
    if selected and sections['events']:
        quota_ids = [q.quota_id for q in QuotaDirection.query.filter_by(direction_id=selected).all()]
        events = (EventQuota.query.options(selectinload(EventQuota.days))
                  .filter(EventQuota.id.in_(quota_ids)).order_by(EventQuota.id.desc()).all()) if quota_ids else []
    today = datetime.now().date()
    deletable_event_ids = {
        item.id for item in events
        if not item.is_closed and not item.closed_at and item.days
        and all(day.date.date() >= today for day in item.days)
    }

    # The global employee sees this direction drill-down within their grants;
    # a scoped employee only has their assigned direction. The main
    # administrator retains site-wide access outside this selected view.
    selected_direction = next((direction for direction in directions if direction.id == selected), None)
    active_members = sum(1 for _student, status in students if status == 'active')
    pending_applications = sum(1 for _student, status in students if status in {'pending', 'interview'})
    upcoming_items = []
    if sections['events']:
        for event in events:
            for event_day in event.days:
                if event_day.date and event_day.date.date() >= today:
                    upcoming_items.append({
                        'date': event_day.date,
                        'title': event.event_title,
                        'detail': event.location or 'Место уточняется',
                        'kind': 'Мероприятие',
                    })
    if sections['lessons']:
        for lesson in lessons:
            if lesson.starts_at and lesson.starts_at.date() >= today:
                detail = ' · '.join(part for part in (lesson.teacher, lesson.room) if part) or 'Занятие направления'
                upcoming_items.append({
                    'date': lesson.starts_at,
                    'title': lesson.title,
                    'detail': detail,
                    'kind': 'Занятие',
                })
    upcoming_items.sort(key=lambda item: item['date'])
    workspace_stats = {
        'students': len(students) if (sections['students'] or sections['applications']) else None,
        'active_members': active_members if (sections['students'] or sections['applications']) else None,
        'pending_applications': pending_applications if sections['applications'] else None,
        'events': len(events) if sections['events'] else None,
        'lessons': len(lessons) if sections['lessons'] else None,
        'notifications': len(notifications) if sections['notifications'] else None,
    }
    attention_items = []
    if sections['applications'] and pending_applications:
        attention_items.append({
            'title': 'Заявления требуют решения',
            'detail': f'На рассмотрении: {pending_applications}',
            'href': '#applications',
            'level': 'warn',
        })
    if sections['events'] and any(not event.is_closed for event in events):
        attention_items.append({
            'title': 'Открыт набор на мероприятия',
            'detail': f'Активных мероприятий: {sum(1 for event in events if not event.is_closed)}',
            'href': '#events',
            'level': 'info',
        })
    return render_template('staff/workspace.html', directions=directions, selected=selected,
                           selected_direction=selected_direction, sections=sections,
                           students=students, lessons=lessons, events=events,
                           deletable_event_ids=deletable_event_ids, notifications=notifications,
                           workspace_stats=workspace_stats, upcoming_items=upcoming_items[:6],
                           attention_items=attention_items, today=today,
                           can_manage=allowed(current_user, selected, 'applications', 'manage'),
                           may_manage=lambda section:allowed(current_user, selected, section, 'manage'),
                           is_chief_admin=current_user.role == UserRole.SUPER_ADMIN.value,
                           is_global_employee=(current_user.role == UserRole.STAFF.value and
                                               getattr(current_user, 'staff_rank', 'employee') == 'employee_all'))


@staff_bp.get('/students')
@login_required
def students(current_user):
    """Dedicated student workspace, isolated from the employee home dashboard."""
    if current_user.role not in {UserRole.STAFF.value, UserRole.SUPER_ADMIN.value}:
        return redirect(url_for('admin.dashboard'))

    permitted = (set(direction_ids(current_user, 'students', 'view')) |
                 set(direction_ids(current_user, 'applications', 'view')))
    directions = (Direction.query.filter(Direction.id.in_(permitted), Direction.is_archived.is_(False))
                  .order_by(Direction.name).all()) if permitted else []
    requested_direction = request.args.get('direction', type=int)
    if requested_direction is not None and requested_direction not in permitted:
        abort(403)
    if requested_direction is None:
        preferred = getattr(current_user, 'assigned_direction_id', None)
        selected = preferred if preferred in permitted else (directions[0].id if directions else None)
    else:
        selected = requested_direction

    sections = {
        'students': allowed(current_user, selected, 'students', 'view') if selected else False,
        'applications': allowed(current_user, selected, 'applications', 'view') if selected else False,
    }
    may_manage = lambda section: bool(selected and allowed(current_user, selected, section, 'manage'))
    student_rows = []
    if selected and (sections['students'] or sections['applications']):
        memberships = db.session.execute(
            student_directions.select().where(student_directions.c.direction_id == selected)
        ).all()
        student_ids = {row.student_id for row in memberships if row.student_id}
        profiles = ({row.id: row for row in Student.query.filter(Student.id.in_(student_ids)).all()}
                    if student_ids else {})
        student_rows = [(profiles.get(row.student_id), row.status)
                        for row in memberships if row.student_id in profiles]

    selected_direction = next((item for item in directions if item.id == selected), None)
    return render_template(
        'staff/students.html', directions=directions, selected=selected,
        selected_direction=selected_direction, sections=sections,
        students=student_rows, may_manage=may_manage,
        is_global_employee=(current_user.role == UserRole.STAFF.value and
                            getattr(current_user, 'staff_rank', 'employee') == 'employee_all'),
    )


@staff_bp.post('/applications/<int:student_id>/<int:direction_id>')
@login_required
def application_decision(current_user, student_id, direction_id):
    if not allowed(current_user, direction_id, 'applications', 'manage'):
        abort(403)
    from services.applications import set_application_status
    action = request.form.get('action')
    if action not in {'active', 'rejected'}:
        abort(400)
    ok, message, _ = set_application_status(student_id, direction_id, action,
                                             actor_user_id=current_user.id,
                                             reason=request.form.get('reason',''))
    if not ok:
        flash(message, 'danger')
    else:
        flash('Решение сохранено.', 'success')
    return redirect(url_for('staff.students', direction=direction_id))


@staff_bp.post('/lessons')
@login_required
def create_lesson(current_user):
    direction_id = request.form.get('direction_id', type=int)
    if not allowed(current_user, direction_id, 'lessons', 'manage'):
        abort(403)
    title = ' '.join((request.form.get('title') or '').split())
    try:
        starts_at = datetime.fromisoformat(request.form.get('starts_at',''))
        minutes = int(request.form.get('duration', 90))
        capacity = int(request.form.get('capacity', 0))
        if not 4 <= len(title) <= 200 or not 15 <= minutes <= 480 or not 0 <= capacity <= 1000:
            raise ValueError
    except (TypeError, ValueError):
        flash('Проверьте название, дату и параметры занятия.', 'danger')
        return redirect(url_for('staff.workspace', direction=direction_id))
    item = Lesson(direction_id=direction_id, title=title, starts_at=starts_at,
                  teacher=(request.form.get('teacher') or '').strip()[:255],
                  room=(request.form.get('room') or '').strip()[:255],
                  description=(request.form.get('description') or '').strip()[:2000],
                  capacity=capacity, duration_minutes=minutes)
    db.session.add(item)
    from database import record_activity
    record_activity('lesson_created', f'Сотрудник создал занятие «{title}».', direction_id=direction_id)
    db.session.commit()
    from services.direction_publishing import publish_direction_announcement
    try:
        delivery = publish_direction_announcement([direction_id], title,
            f'Занятие {starts_at:%d.%m.%Y в %H:%M}. {item.room or "Место уточняется"}. {item.description or ""}',
            category='lessons', creator_user_id=current_user.id,
            source_type='lesson', source_id=item.id, batch_key=f'lesson:{item.id}:created')
        flash(f'Занятие в календаре, Student App и панели. В очереди ботов: {delivery["queued"]}.', 'success')
    except Exception:
        import logging
        logging.getLogger(__name__).exception('Lesson announcement enqueue failed')
        db.session.rollback()
        flash('Занятие сохранено, но рассылка не завершена — проверьте журнал.', 'warning')
    return redirect(url_for('staff.workspace', direction=direction_id))


@staff_bp.post('/events')
@login_required
def create_event(current_user):
    direction_id = request.form.get('direction_id', type=int)
    if not allowed(current_user, direction_id, 'events', 'manage'):
        abort(403)
    title = ' '.join((request.form.get('title') or '').split())
    try:
        starts_at = datetime.fromisoformat(request.form.get('starts_at',''))
        capacity = int(request.form.get('capacity', 0))
        if not 4 <= len(title) <= 200 or not 1 <= capacity <= 10000:
            raise ValueError
    except (ValueError, TypeError):
        flash('Проверьте название, дату и количество мест мероприятия.', 'danger')
        return redirect(url_for('staff.workspace', direction=direction_id))
    from database import EventDay, record_activity
    item = EventQuota(event_title=title,
                      event_description=(request.form.get('description') or '').strip()[:2000],
                      location=(request.form.get('location') or '').strip()[:255],
                      total_places=capacity, is_closed=False, publish_mode='immediate',
                      is_published=True)
    db.session.add(item)
    db.session.flush()
    db.session.add(QuotaDirection(quota_id=item.id, direction_id=direction_id))
    db.session.add(EventDay(quota_id=item.id, date=starts_at, daily_places=capacity))
    record_activity('event_created', f'Сотрудник опубликовал «{title}».',
                    direction_id=direction_id, quota_id=item.id)
    db.session.commit()
    from services.direction_publishing import publish_direction_announcement
    try:
        delivery = publish_direction_announcement([direction_id], title,
            f'Мероприятие {starts_at:%d.%m.%Y в %H:%M}. {item.location or "Место уточняется"}. {item.event_description or ""}',
            category='events', creator_user_id=current_user.id,
            source_type='event', source_id=item.id, batch_key=f'event:{item.id}:created')
        flash(f'Мероприятие опубликовано в календаре, Student App и панели. В очереди ботов: {delivery["queued"]}.', 'success')
    except Exception:
        import logging
        logging.getLogger(__name__).exception('Event announcement enqueue failed')
        db.session.rollback()
        flash('Мероприятие сохранено, но рассылка не завершена — проверьте журнал.', 'warning')
    return redirect(url_for('staff.workspace', direction=direction_id))


@staff_bp.post('/events/<int:quota_id>/close')
@login_required
def close_event(current_user, quota_id):
    quota = db.get_or_404(EventQuota, quota_id)
    dirs = {r.direction_id for r in QuotaDirection.query.filter_by(quota_id=quota_id).all()}
    # Never change events shared with other directions without rights to ALL of them.
    if not dirs or any(not allowed(current_user, did, 'events', 'manage') for did in dirs):
        abort(403)
    quota.is_closed = True
    quota.closed_at = datetime.utcnow()
    quota.closing_reason = 'Закрыто сотрудником направления'
    from database import record_activity
    for did in dirs:
        record_activity('event_closed', f'Набор на мероприятие «{quota.event_title}» закрыт.', direction_id=did, quota_id=quota_id)
    db.session.commit()
    try:
        from services.activity_chats import close_activity_chat
        queued = close_activity_chat('event', quota_id)
    except Exception:
        import logging
        logging.getLogger(__name__).exception('Не удалось поставить участников в очередь удаления из чата мероприятия #%s', quota_id)
        queued = 0
    flash('Приём на мероприятие закрыт.' + (f' Удаление из чата мероприятия поставлено в очередь: {queued}.' if queued else ''), 'success')
    return redirect(url_for('staff.workspace', direction=next(iter(dirs))))


@staff_bp.post('/events/<int:quota_id>/delete')
@login_required
def delete_event(current_user, quota_id):
    """Delete only an upcoming, still-open event managed in every linked direction."""
    quota = db.get_or_404(EventQuota, quota_id)
    direction_ids_for_event = sorted({row.direction_id for row in
        QuotaDirection.query.filter_by(quota_id=quota_id).all() if row.direction_id})
    # A shared event is a single object. A staff member must control every
    # linked direction; partial access must never allow cross-department deletion.
    if not direction_ids_for_event or any(
        not allowed(current_user, direction_id, 'events', 'manage')
        for direction_id in direction_ids_for_event
    ):
        abort(403)

    event_days = EventDay.query.filter_by(quota_id=quota_id).all()
    today = datetime.now().date()
    if quota.is_closed or quota.closed_at:
        flash('Закрытое мероприятие удалить нельзя.', 'warning')
        return redirect(url_for('staff.workspace', direction=direction_ids_for_event[0]))
    if not event_days or any(day.date.date() < today for day in event_days):
        flash('Мероприятие нельзя удалить: дата уже прошла или не указана.', 'warning')
        return redirect(url_for('staff.workspace', direction=direction_ids_for_event[0]))

    title = quota.event_title
    day_ids = [day.id for day in event_days]
    order_files = AdministrativeOrder.query.filter_by(target_kind='event', target_id=quota_id).all()
    order_ids = [item.id for item in order_files]
    try:
        # Queue participant removal / revoke dedicated event invitations in
        # the same ORM transaction. Permanent and shared chats are protected by
        # close_activity_chat itself.
        from services.activity_chats import close_activity_chat
        close_activity_chat('event', quota_id, commit=False)

        if day_ids:
            DayParticipation.query.filter(DayParticipation.day_id.in_(day_ids)).delete(synchronize_session=False)
        EventDay.query.filter_by(quota_id=quota_id).delete(synchronize_session=False)
        EventQuotaChat.query.filter_by(quota_id=quota_id).delete(synchronize_session=False)
        EventQuotaDecline.query.filter_by(quota_id=quota_id).delete(synchronize_session=False)
        EventLeader.query.filter_by(quota_id=quota_id).delete(synchronize_session=False)
        QuotaDirection.query.filter_by(quota_id=quota_id).delete(synchronize_session=False)
        StudentActivity.query.filter_by(quota_id=quota_id).delete(synchronize_session=False)
        CompetitionAnnouncement.query.filter_by(quota_id=quota_id).update(
            {CompetitionAnnouncement.quota_id: None}, synchronize_session=False)
        BotDeliveryJob.query.filter(
            BotDeliveryJob.source_type == 'event', BotDeliveryJob.source_id == quota_id,
            BotDeliveryJob.status.in_(('pending', 'retry', 'blocked', 'sending')),
        ).update({BotDeliveryJob.status: 'cancelled', BotDeliveryJob.locked_until: None},
                 synchronize_session=False)
        ActivityChat.query.filter_by(kind='event', activity_id=quota_id).delete(synchronize_session=False)
        if order_ids:
            OrderDeliveryJob.query.filter(OrderDeliveryJob.order_id.in_(order_ids)).delete(synchronize_session=False)
        AdministrativeOrder.query.filter_by(target_kind='event', target_id=quota_id).delete(synchronize_session=False)
        db.session.delete(quota)

        from database import record_activity
        for direction_id in direction_ids_for_event:
            record_activity('event_deleted', f'Сотрудник удалил предстоящее мероприятие «{title}».',
                            direction_id=direction_id)
        db.session.commit()
        from services.orders import delete_order_files
        delete_order_files(order_files)
    except Exception:
        db.session.rollback()
        import logging
        logging.getLogger(__name__).exception('Could not delete event #%s by staff user #%s', quota_id, current_user.id)
        flash('Не удалось удалить мероприятие. Изменения отменены.', 'danger')
        return redirect(url_for('staff.workspace', direction=direction_ids_for_event[0]))

    flash(f'Мероприятие «{title}» и связанные записи удалены.', 'success')
    return redirect(url_for('staff.workspace', direction=direction_ids_for_event[0]))


@staff_bp.post('/lessons/<int:lesson_id>/delete')
@login_required
def delete_lesson(current_user, lesson_id):
    """Delete a lesson only when the employee has manage rights for its direction."""
    lesson = db.get_or_404(Lesson, lesson_id)
    direction_id = lesson.direction_id
    if not allowed(current_user, direction_id, 'lessons', 'manage'):
        abort(403)
    title = lesson.title
    try:
        # Prevent queued announcements from publishing a lesson after deletion.
        BotDeliveryJob.query.filter(
            BotDeliveryJob.source_type == 'lesson', BotDeliveryJob.source_id == lesson_id,
            BotDeliveryJob.status.in_(('pending', 'retry', 'blocked', 'sending')),
        ).update({BotDeliveryJob.status: 'cancelled', BotDeliveryJob.locked_until: None},
                 synchronize_session=False)
        from database import record_activity
        record_activity('lesson_deleted', f'Сотрудник удалил занятие «{title}».', direction_id=direction_id)
        db.session.delete(lesson)
        db.session.commit()
    except Exception:
        db.session.rollback()
        import logging
        logging.getLogger(__name__).exception('Could not delete lesson #%s by staff user #%s', lesson_id, current_user.id)
        flash('Не удалось удалить занятие. Изменения отменены.', 'danger')
        return redirect(url_for('staff.workspace', direction=direction_id))

    flash(f'Занятие «{title}» удалено.', 'success')
    return redirect(url_for('staff.workspace', direction=direction_id))


@staff_bp.post('/students/<int:direction_id>/create')
@login_required
def create_student(current_user, direction_id):
    """Create a student profile; this action is exclusive to the chief administrator."""
    if current_user.role != UserRole.SUPER_ADMIN.value:
        abort(403)
    direction = Direction.query.filter_by(id=direction_id, is_archived=False).first()
    if not direction or not allowed(current_user, direction_id, 'students', 'manage'):
        abort(403)

    full_name = ' '.join((request.form.get('full_name') or '').split())
    group = ' '.join((request.form.get('group') or '').split())[:50]
    phone = (request.form.get('phone') or '').strip()[:30]
    education_type = (request.form.get('education_type') or 'institute').strip()
    status = (request.form.get('status') or DirectionStatus.PENDING.value).strip()
    if education_type not in {'college', 'institute'}:
        education_type = 'institute'
    if status not in {DirectionStatus.PENDING.value, DirectionStatus.INTERVIEW.value, DirectionStatus.ACTIVE.value}:
        abort(400)
    if not 3 <= len(full_name) <= 255:
        flash('Укажите ФИО студента (не менее трёх символов).', 'danger')
        return redirect(url_for('staff.students', direction=direction_id))

    from services.student_validation import student_duplicate_message
    duplicate_error = student_duplicate_message(full_name, phone, check_phone=bool(phone))
    if duplicate_error:
        flash(duplicate_error, 'danger')
        return redirect(url_for('staff.students', direction=direction_id))

    try:
        # Staff-created profiles have no messenger identity until a student
        # explicitly links an account through the bot/Student App.
        tg_id = None
        for _attempt in range(5):
            candidate = -int(uuid.uuid4().int % 8_500_000_000_000_000_000) or -1
            if not Student.query.filter_by(tg_id=candidate).first():
                tg_id = candidate
                break
        if tg_id is None:
            raise RuntimeError('Не удалось выделить технический идентификатор профиля.')
        student = Student(
            full_name=full_name, group=group or None, phone=phone or None,
            email=None, education_type=education_type, tg_id=tg_id,
            council_registered=True,
        )
        db.session.add(student)
        db.session.flush()
        db.session.execute(student_directions.insert().values(
            student_id=student.id, direction_id=direction_id,
            status=status, joined_at=datetime.utcnow(),
        ))
        from database import record_activity
        record_activity('student_created', f'Сотрудник создал карточку студента «{full_name}».',
                        student_id=student.id, direction_id=direction_id)
        db.session.commit()
        flash(f'Студент «{full_name}» добавлен в направление «{direction.name}».', 'success')
    except Exception:
        db.session.rollback()
        import logging
        logging.getLogger(__name__).exception('Could not create student in direction #%s', direction_id)
        flash('Не удалось добавить студента. Проверьте данные и повторите попытку.', 'danger')
    return redirect(url_for('staff.students', direction=direction_id))


@staff_bp.post('/students/<int:student_id>/<int:direction_id>/profile')
@login_required
def update_student_profile(current_user, student_id, direction_id):
    if not allowed(current_user, direction_id, 'students', 'manage'):
        abort(403)
    student = db.get_or_404(Student, student_id)
    membership_rows = db.session.execute(student_directions.select().where(
        student_directions.c.student_id == student_id
    )).fetchall()
    linked_direction_ids = {int(row.direction_id) for row in membership_rows if row.direction_id is not None}
    if direction_id not in linked_direction_ids:
        abort(404)
    # Student profiles are shared between directions. A limited-scope employee
    # may edit the shared identity only when every linked direction is inside
    # their own students:manage scope; otherwise an edit could affect another team.
    manageable_ids = set(direction_ids(current_user, 'students', 'manage'))
    if not linked_direction_ids or not linked_direction_ids.issubset(manageable_ids):
        abort(403)

    full_name = ' '.join((request.form.get('full_name') or '').split())
    group = ' '.join((request.form.get('group') or '').split())[:50]
    phone = (request.form.get('phone') or '').strip()[:30]
    if not 3 <= len(full_name) <= 255:
        flash('Укажите ФИО студента (не менее трёх символов).', 'danger')
        return redirect(url_for('staff.students', direction=direction_id))

    from services.student_validation import normalize_full_name, normalize_phone, student_duplicate_message
    name_changed = normalize_full_name(full_name) != normalize_full_name(student.full_name)
    phone_changed = normalize_phone(phone) != normalize_phone(student.phone)
    duplicate_error = None
    if name_changed or phone_changed:
        duplicate_error = student_duplicate_message(
            full_name, phone, exclude_id=student.id,
            check_name=name_changed, check_phone=phone_changed and bool(phone),
        )
    if duplicate_error:
        flash(duplicate_error, 'danger')
        return redirect(url_for('staff.students', direction=direction_id))

    student.full_name = full_name
    student.group = group or None
    student.phone = phone or None
    from database import record_activity
    record_activity('student_updated', 'Сотрудник обновил данные карточки студента.',
                    student_id=student_id, direction_id=direction_id)
    db.session.commit()
    flash('Данные студента обновлены.', 'success')
    return redirect(url_for('staff.students', direction=direction_id))


@staff_bp.post('/notifications')
@login_required
def publish_notice(current_user):
    # Legacy direction notice form was removed from the workspace. Employees
    # must use the bot-only TG/VK/MAX composer in admin.notifications.
    if current_user.role == UserRole.STAFF.value:
        abort(403)
    abort(404)
