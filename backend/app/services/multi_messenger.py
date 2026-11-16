"""Shared student-facing commands for VK and MAX and account-pairing for Telegram.

Only an account already authenticated by its platform may issue /code or /link.
No automatic matching by names, numbers or phone numbers is performed.
"""
from __future__ import annotations
from datetime import datetime, timedelta
import hashlib
import re
import secrets
import threading
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from database import (
    db, Student, Direction, DirectionQuestion, DirectionStatus,
    MessengerIdentity, MessengerLinkCode, EventQuota, EventQuotaDecline, student_directions,
)
from services.applications import (register_student_with_council, submit_application,
                                    available_application_directions)

_flow_lock = threading.Lock()
_flows = {}


def _digest(code):
    from config import settings
    return hashlib.sha256((settings.SECRET_KEY + '|' + code.upper()).encode()).hexdigest()


def identity(platform, user_id):
    return MessengerIdentity.query.filter_by(platform=platform, external_user_id=str(user_id)).first()


def student_for(platform, user_id):
    if platform == 'telegram':
        # Native Telegram profiles use Student.tg_id. Older shared registrations
        # may have been created with a synthetic negative tg_id plus an explicit
        # MessengerIdentity row; keep those accounts accessible as well.
        student = Student.query.filter_by(tg_id=int(user_id)).first()
        if student:
            return student
    link = identity(platform, user_id)
    return Student.query.get(link.student_id) if link else None


LINK_TARGETS = frozenset({'telegram', 'vk', 'max'})


def normalize_public_handle(platform, value):
    """Validate a platform public identifier; never use it as proof of ownership."""
    raw = str(value or '').strip()
    if platform == 'vk':
        raw = re.sub(r'^(?:https?://)?(?:www\.)?(?:m\.)?vk\.(?:com|ru)/id', '', raw, flags=re.I)
        raw = re.sub(r'^(?:vkid|id)', '', raw, flags=re.I)
        if not re.fullmatch(r'[1-9][0-9]{0,18}', raw):
            raise ValueError('Укажите числовой VK ID, например 123456789.')
        return str(int(raw))
    if platform not in {'telegram', 'max'}:
        raise ValueError('Неизвестный мессенджер.')
    raw = raw.lstrip('@')
    # Usernames may be changed by their owner; store verified platform IDs as identities.
    pattern = r'[A-Za-z][A-Za-z0-9_]{4,31}' if platform == 'telegram' else r'[A-Za-z0-9_]{3,64}'
    if not re.fullmatch(pattern, raw):
        raise ValueError('Укажите корректный username в формате @username.')
    return raw.casefold()


def verified_sender_handle(platform, user_id, username=None):
    """Only values from authenticated bot events may be compared against a request."""
    if platform == 'vk':
        return str(int(user_id))
    if not username:
        return None
    try:
        return normalize_public_handle(platform, username)
    except ValueError:
        return None



def linked_account_status(student):
    """Status for the account-owner UI; never return raw external IDs to browsers."""
    linked = {row.platform: row for row in MessengerIdentity.query.filter_by(student_id=student.id).all()}
    telegram_linked = 'telegram' in linked
    telegram_native = bool(student.tg_id and student.tg_id > 0)
    return {
        'telegram': {'connected': telegram_native or telegram_linked, 'primary': telegram_native or telegram_linked},
        'vk': {'connected': 'vk' in linked, 'primary': False},
        'max': {'connected': 'max' in linked, 'primary': False},
    }


def generate_link_code(student, target_platform=None, expected_handle=None):
    """Create a short-lived, single-use proof bound to the selected platform.

    Older bot /code commands are retained for compatibility without a target.
    The new account management interface always supplies VK or MAX explicitly.
    """
    if target_platform is not None and target_platform not in LINK_TARGETS:
        raise ValueError('Unsupported destination platform')
    if expected_handle is not None:
        if not target_platform:
            raise ValueError('Выберите мессенджер перед вводом ID или username.')
        expected_handle = normalize_public_handle(target_platform, expected_handle)
    now = datetime.utcnow()
    if target_platform and linked_account_status(student)[target_platform]['connected']:
        raise ValueError('Этот мессенджер уже подключён к вашему профилю.')
    # Old outstanding codes are revoked; only the newest stays usable.
    MessengerLinkCode.query.filter_by(student_id=student.id, used_at=None).update(
        {'used_at': now}, synchronize_session=False,
    )
    code = secrets.token_hex(10).upper()  # 80 random bits; DB stores only a keyed digest.
    db.session.add(MessengerLinkCode(
        student_id=student.id, code_hash=_digest(code), target_platform=target_platform,
        expected_handle=expected_handle, expires_at=now + timedelta(minutes=10),
    ))
    db.session.commit()
    return code


def pending_link_requests(student):
    """Show only unanswered claims for the current authenticated profile."""
    now = datetime.utcnow()
    rows = MessengerLinkCode.query.filter_by(student_id=student.id, used_at=None).filter(
        MessengerLinkCode.pending_external_user_id.isnot(None),
        MessengerLinkCode.expires_at > now,
    ).order_by(MessengerLinkCode.requested_at.desc()).all()
    return [{"id": row.id, "platform": row.target_platform,
             "handle": (('@' + row.pending_public_username) if row.pending_public_username else
                        ('ID ' + row.pending_external_user_id)),
             "expires_at": row.expires_at.isoformat() + 'Z'} for row in rows]


def redeem_link_code(platform, user_id, code, username=None):
    """Stage a claim made by an authenticated messenger sender. Never link on code alone."""
    if platform not in LINK_TARGETS:
        return 'Неподдерживаемая платформа.'
    if not re.fullmatch(r'[a-fA-F0-9]{20}', code or ''):
        return 'Неверный формат кода. Укажите /link КОД.'
    now = datetime.utcnow()
    row = MessengerLinkCode.query.filter_by(code_hash=_digest(code)).first()
    if not row or row.used_at or row.expires_at <= now:
        return 'Код недействителен или истёк. Получите новый код привязки.'
    if row.target_platform and row.target_platform != platform:
        return 'Код выпущен для другой платформы. Выберите нужный мессенджер в настройках.'
    verified_handle = verified_sender_handle(platform, user_id, username)
    if row.expected_handle and row.expected_handle != verified_handle:
        return ('Аккаунт отправителя не совпадает с указанным VK ID или username. '
                'Проверьте имя пользователя и повторите подтверждение.')
    student = Student.query.get(row.student_id)
    if not student:
        return 'Профиль больше не существует.'
    linked = student_for(platform, user_id)
    if linked and linked.id != student.id:
        return 'Этот аккаунт уже относится к другому профилю. Объединение запрещено.'
    if platform == 'telegram' and student.tg_id > 0 and student.tg_id != int(user_id):
        return 'К профилю уже привязан другой Telegram.'
    if platform != 'telegram':
        existing = MessengerIdentity.query.filter_by(student_id=student.id, platform=platform).first()
        if existing and existing.external_user_id != str(user_id):
            return 'К профилю уже привязан другой аккаунт этой платформы.'
    if linked and linked.id == student.id:
        return 'Этот аккаунт уже подключён к вашему профилю.'
    if row.pending_external_user_id:
        if row.pending_external_user_id == str(user_id):
            return 'Запрос уже отправлен владельцу профиля. Дождитесь подтверждения или отклонения.'
        return 'Код уже предъявлен другим аккаунтом. Владелец может отклонить запрос и создать новый код.'
    # Atomically allow only one candidate account to present this code.
    claimed = db.session.execute(update(MessengerLinkCode).where(
        MessengerLinkCode.id == row.id,
        MessengerLinkCode.used_at.is_(None),
        MessengerLinkCode.expires_at > now,
        MessengerLinkCode.pending_external_user_id.is_(None),
    ).values(pending_external_user_id=str(user_id),
             pending_public_username=verified_handle if platform != 'vk' else None,
             target_platform=platform, requested_at=now))
    if claimed.rowcount != 1:
        db.session.rollback()
        return 'Запрос уже получен. При необходимости создайте новый код.'
    db.session.commit()
    # Message failures cannot turn a pending request into an approved identity.
    try:
        from services.account_link_alerts import notify_link_request
        notify_link_request(student, row.id, platform, verified_handle or str(user_id))
    except Exception:
        import logging
        logging.getLogger(__name__).exception('Could not notify account owner about link request')
    return ('🔐 Код принят. Запрос №' + str(row.id) + ' направлен владельцу профиля. '
            'Он должен нажать «Подтвердить» или «Отклонить». До этого доступ не предоставлен.')


def review_link_request(student, request_id, approve):
    """Only an authenticated *existing* owner can approve/reject a presented code."""
    now = datetime.utcnow()
    row = MessengerLinkCode.query.filter_by(id=int(request_id), student_id=student.id).first()
    if not row or row.used_at or row.expires_at <= now or not row.pending_external_user_id:
        raise ValueError('Запрос не найден, истёк или уже обработан.')
    platform, sender_id = row.target_platform, row.pending_external_user_id
    if platform not in LINK_TARGETS:
        raise ValueError('Недопустимая платформа.')
    if approve:
        existing_user = student_for(platform, sender_id)
        if existing_user:
            raise ValueError('Аккаунт уже привязан к профилю. Создайте новый запрос при необходимости.')
        if platform == 'telegram':
            if student.tg_id > 0:
                raise ValueError('Другой Telegram уже подключён.')
        elif MessengerIdentity.query.filter_by(student_id=student.id, platform=platform).first():
            raise ValueError('Этот мессенджер уже подключён. Сначала отвяжите старый аккаунт.')
    claimed = db.session.execute(update(MessengerLinkCode).where(
        MessengerLinkCode.id == row.id,
        MessengerLinkCode.student_id == student.id,
        MessengerLinkCode.used_at.is_(None),
        MessengerLinkCode.expires_at > now,
        MessengerLinkCode.pending_external_user_id == sender_id,
    ).values(used_at=now, rejected_at=now if not approve else None))
    if claimed.rowcount != 1:
        db.session.rollback()
        raise ValueError('Запрос уже обработан. Обновите страницу.')
    if approve:
        if platform == 'telegram':
            student.tg_id = int(sender_id)
            student.telegram_username = row.pending_public_username
        else:
            db.session.add(MessengerIdentity(platform=platform, external_user_id=sender_id,
                                             student_id=student.id,
                                             public_username=row.pending_public_username if platform == 'max' else None))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ValueError('Аккаунт уже занят. Запрос отменён; попробуйте ещё раз.')
    try:
        from services.account_link_alerts import notify_link_result
        notify_link_result(platform, sender_id, approve)
    except Exception:
        import logging
        logging.getLogger(__name__).exception('Unable to send link review notification')
    return ('✅ Аккаунт привязан к общему профилю.' if approve else
            '⛔ Запрос отклонён. Никакой новый аккаунт не подключён.')


def unlink_account(student, platform, *, current_platform=None):
    """Remove VK/MAX only, without deleting the student's profile or applications."""
    if platform not in LINK_TARGETS:
        raise ValueError('Можно отвязать только VK или MAX.')
    if current_platform == platform:
        raise ValueError('Нельзя отвязать аккаунт, через который вы сейчас вошли. Откройте кабинет через другую платформу.')
    account = MessengerIdentity.query.filter_by(student_id=student.id, platform=platform).first()
    if not account:
        raise ValueError('Этот аккаунт не привязан.')
    status = linked_account_status(student)
    if sum(bool(v['connected']) for v in status.values()) <= 1:
        raise ValueError('Нельзя отключить последний способ входа в аккаунт.')
    db.session.delete(account)
    MessengerLinkCode.query.filter_by(student_id=student.id, used_at=None).update(
        {'used_at': datetime.utcnow()}, synchronize_session=False)
    db.session.commit()
    return 'Аккаунт отвязан. Ваши заявки и данные в системе сохранены.'


def new_synthetic_tg_id():
    # 63-bit negative placeholder for an account created outside Telegram.
    # Real Telegram user IDs are positive, so no Telegram API sends to these IDs.
    for _ in range(8):
        value = -(secrets.randbelow(2**60 - 1) + 1)
        if not Student.query.filter_by(tg_id=value).first():
            return value
    raise RuntimeError('Could not allocate temporary student ID')


def _put_flow(platform, user_id, info):
    with _flow_lock:
        _flows[(platform, str(user_id))] = {**info, 'expires': datetime.utcnow() + timedelta(minutes=20)}


def _get_flow(platform, user_id):
    with _flow_lock:
        key = (platform, str(user_id))
        flow = _flows.get(key)
        if flow and flow['expires'] < datetime.utcnow():
            _flows.pop(key, None)
            return None
        return flow


def _clear_flow(platform, user_id):
    with _flow_lock:
        _flows.pop((platform, str(user_id)), None)


def _save_profile(platform, user_id, flow):
    existing = student_for(platform, user_id)
    # Telegram has a stable numeric sender ID, so store it directly. VK/MAX
    # accounts use synthetic Student.tg_id values and their verified identity row.
    profile_tg_id = (int(user_id) if platform == 'telegram' and not existing
                     else existing.tg_id if existing else new_synthetic_tg_id())
    student, _, problem = register_student_with_council(
        profile_tg_id, flow['full_name'], flow['group'], flow['phone'],
        flow['education_type'], source=platform,
    )
    if problem:
        return problem
    if not existing and platform != 'telegram':
        try:
            db.session.add(MessengerIdentity(platform=platform, external_user_id=str(user_id), student_id=student.id,
                                             public_username=flow.get('public_username') if platform == 'max' else None))
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
    return '✅ Регистрация в студенческом совете завершена! Ваш профиль сохранён. Главное меню уже доступно на кнопках внизу чата.'


def _flow_message(platform, user_id, message, username=None):
    flow = _get_flow(platform, user_id)
    if not flow:
        return None
    value = ' '.join(message.strip().split())
    if value.lower() in ('/cancel', 'отмена'):
        _clear_flow(platform, user_id)
        return 'Действие отменено.'
    if flow.get('kind') == 'science':
        _clear_flow(platform, user_id)
        return 'Этот раздел больше не доступен.'
    if flow['kind'] == 'target_handle_entry':
        _clear_flow(platform, user_id)
        owner = student_for(platform, user_id)
        if not owner:
            return 'Ваш профиль не найден. Откройте /start.'
        try:
            code = generate_link_code(owner, flow['target_platform'], value)
        except ValueError as exc:
            return str(exc)
        return (f'🔐 Одноразовый код для {flow["target_platform"].upper()}: {code}\n'
                'Введите его в боте целевого мессенджера через /link.\n'
                'Срок действия — 10 минут. Затем подтвердите запрос в этом профиле.')
    if flow['kind'] == 'link_code_entry':
        _clear_flow(platform, user_id)
        return redeem_link_code(platform, user_id, value, username=username)
    if flow['kind'] == 'registration':
        field = flow['field']
        if field == 'education_type':
            val = value.lower()
            if val in {'1', 'колледж', 'college'}:
                flow['education_type'] = 'college'
            elif val in {'2', 'институт', 'institute'}:
                flow['education_type'] = 'institute'
            else:
                return 'Выберите: 1 — колледж, 2 — институт.'
            flow['field'] = 'full_name'
            return 'Введите ФИО (полностью).'
        if field == 'full_name':
            if len(value) < 5 or len(value) > 255 or len(value.split()) < 2:
                return 'Укажите ФИО не короче 5 символов, минимум имя и фамилию.'
            flow['full_name'] = value
            flow['field'] = 'group'
            return 'Укажите учебную группу.'
        if field == 'group':
            if not (2 <= len(value) <= 50):
                return 'Название группы: от 2 до 50 символов.'
            flow['group'] = value
            flow['field'] = 'phone'
            return 'Укажите номер телефона для связи (или «-», если не хотите передавать номер).'
        if field == 'phone':
            if value != '-' and not re.fullmatch(r'[+\d ()-]{7,30}', value):
                return 'Введите корректный номер (7–30 символов) или «-».'
            flow['phone'] = '' if value == '-' else value
            _clear_flow(platform, user_id)
            return _save_profile(platform, user_id, flow)
    if flow['kind'] == 'event_decline':
        from services.shared_event_actions import decline_event
        _clear_flow(platform, user_id)
        return decline_event(student_for(platform,user_id), flow['quota_id'], value, platform=platform)
    if flow['kind'] == 'application':
        questions = flow['questions']
        qid = questions[flow['index']]
        if len(value) > 2000:
            return 'Ответ должен быть не длиннее 2000 символов.'
        if flow['required'][flow['index']] and value in {'', '-'}:
            return 'На этот вопрос нужно ответить. Введите текстовый ответ.'
        if value != '-':
            flow['answers'][str(qid)] = value
        flow['index'] += 1
        if flow['index'] < len(questions):
            q = DirectionQuestion.query.get(questions[flow['index']])
            return f'Вопрос {flow["index"]+1}/{len(questions)}: {q.question_text}\n(«-» — пропуск необязательного вопроса)'
        _clear_flow(platform, user_id)
        student = student_for(platform, user_id)
        direction = Direction.query.get(flow['direction_id'])
        ok, result = submit_application(student, direction, source=platform, answers=flow['answers'])
        return ('✅ ' if ok else '⚠️ ') + result
    return None


def handle_private_text(platform, user_id, message, username=None):
    """Return a plain-text reply. Caller must authenticate the user using platform events."""
    text = (message or '').strip()[:4000]
    if not text:
        flow = _get_flow(platform, user_id)
        if flow:
            if flow.get('kind') == 'application' and flow.get('required', [])[flow.get('index', 0)]:
                return 'На этот вопрос нужно ответить текстом. Введите ответ или /cancel для отмены.'
            return 'Отправьте текстовый ответ или /cancel для отмены.'
        return None
    command, _, rest = text.partition(' ')
    command = command.lower().split('@', 1)[0]
    if command in {'/cancel', 'отмена'}:
        _clear_flow(platform, user_id)
        return 'Отменено.'
    from services.bot_ui import welcome_text, home_text
    if command in {'/start', 'меню'}:
        _clear_flow(platform, user_id)
        owner = student_for(platform, user_id)
        return home_text(owner.full_name) if owner and owner.council_registered else welcome_text()
    if command in {'/help', 'помощь'}:
        return ('✦ ПОМОЩЬ · Студенческий совет\n'
                '━━━━━━━━━━━━━━━━━━━━\n\n'
                'Основные разделы доступны через кнопки внизу чата.\n\n'
                'Команды на случай, если меню скрыто:\n'
                '• /start — главное меню\n• /directions — подать заявление\n'
                '• /status — мои заявления\n• /events — мероприятия\n'
                '• /me — профиль\n• /accounts — подключённые аккаунты\n'
                '• /leadership — руководство\n• /my_chats — мои чаты событий\n'
                '• /app — личный кабинет\n• /cancel — отменить текущий шаг')
    if command in {'/app', '/student_app'}:
        owner = student_for(platform, user_id)
        if not owner:
            return welcome_text()
        from services.messenger_transports import vk_app_url, max_app_url
        app_url = vk_app_url() if platform == 'vk' else max_app_url() if platform == 'max' else None
        if platform == 'telegram':
            from config import settings
            app_url = settings.WEBAPP_URL if settings.WEBAPP_URL.startswith('https://') else None
        if not app_url:
            return ('🌐 ЛИЧНЫЙ КАБИНЕТ\n━━━━━━━━━━━━━━━━━━━━\n\nВеб-приложение пока не опубликовано по публичному HTTPS-адресу. '
                    'Попросите администратора настроить WEBAPP_URL и параметры Mini App. '
                    'Профиль и заявления доступны через меню бота.')
        return ('🌐 ЛИЧНЫЙ КАБИНЕТ\n━━━━━━━━━━━━━━━━━━━━\nОткройте приложение по ссылке ниже. '
                'Заявки, мероприятия, расписание и профиль общие для всех трёх платформ.')
    if command == '/unlink':
        owner = student_for(platform, user_id)
        target = rest.strip().lower()
        if not owner or target not in {'vk', 'max'}:
            return 'Формат: /unlink vk или /unlink max. Отключить можно только VK/MAX.'
        if target == platform:
            return 'Нельзя отключить платформу, через которую вы сейчас вошли.'
        _put_flow(platform, user_id, {'kind': 'unlink_confirm', 'target_platform': target})
        label = 'ВКонтакте' if target == 'vk' else 'MAX'
        return f'Подтвердите отключение {label}. Профиль, заявления и история сохранятся.'
    if command == '/unlink_confirm':
        owner = student_for(platform, user_id)
        target = rest.strip().lower()
        flow = _get_flow(platform, user_id)
        if not owner or target not in {'vk', 'max'} or not flow or flow.get('kind') != 'unlink_confirm' or flow.get('target_platform') != target:
            return 'Запрос на отключение устарел. Откройте /accounts и повторите.'
        _clear_flow(platform, user_id)
        try:
            return unlink_account(owner, target, current_platform=platform)
        except ValueError as exc:
            return str(exc)
    if command in {'/connecttelegram', '/connectvk', '/connectmax'}:
        target = {'/connecttelegram':'telegram', '/connectvk':'vk', '/connectmax':'max'}[command]
        owner = student_for(platform, user_id)
        if not owner:
            return welcome_text()
        if linked_account_status(owner)[target]['connected']:
            return 'Этот мессенджер уже подключён к вашему профилю.'
        _put_flow(platform, user_id, {'kind':'target_handle_entry', 'target_platform':target})
        return ('🔗 Укажите свой VK ID (цифрами):' if target == 'vk' else
                f'🔗 Укажите ваш username {target.upper()}, например @username:')
    if command in {'/start_link', '/existing'}:
        command = '/link'
    if command == '/link':
        if not rest.strip():
            _put_flow(platform, user_id, {'kind': 'link_code_entry'})
            return '🔐 Введите одноразовый код привязки (20 символов) следующим сообщением или /cancel.'
        return redeem_link_code(platform, user_id, rest.strip(), username=username)
    if command in {'/pairapprove', '/pairdeny'}:
        owner = student_for(platform, user_id)
        if not owner:
            return 'Только владелец зарегистрированного профиля может решить запрос.'
        if not rest.strip().isdigit():
            return 'Укажите номер запроса, например /pairapprove 12 или /pairdeny 12.'
        try:
            return review_link_request(owner, int(rest.strip()), command == '/pairapprove')
        except ValueError as exc:
            return str(exc)
    student = student_for(platform, user_id)
    if platform == 'max' and student and username:
        handle = verified_sender_handle(platform, user_id, username)
        linked_row = identity(platform, user_id)
        if linked_row and linked_row.public_username != handle:
            linked_row.public_username = handle
            db.session.commit()
    if command in {'/accounts', '/account'}:
        if not student:
            return 'Сначала зарегистрируйтесь или отправьте /link КОД, выданный в вашем основном аккаунте.'
        status = linked_account_status(student)
        labels = {'telegram': 'Telegram', 'vk': 'ВКонтакте', 'max': 'MAX'}
        return ('🔐 Ваши подключения\n' + '\n'.join(
            ('✅ ' if status[p]['connected'] else '○ ') + labels[p]
            for p in ('telegram', 'vk', 'max'))
             + '\n\nНовые подключения требуют вашего согласия. Запросы: ' + (', '.join('#'+str(x['id'])+' ('+x['platform']+')' for x in pending_link_requests(student)) or 'нет') + '\nПривязка: /code vk 123456789, /code telegram @username, /code max @username. Решение: /pairapprove НОМЕР или /pairdeny НОМЕР.')
    if command in {'/my_chats', '/chats'}:
        if not student:
            return welcome_text()
        from database import SharedActivityChat
        from services.activity_chats import student_has_audience
        entries = []
        for room in SharedActivityChat.query.filter_by(active=True).all():
            if room.invite_link and student_has_audience(student, room.audience):
                entries.append(f'• {room.title}: {room.invite_link}')
        return ('💬 МОИ ЧАТЫ СОБЫТИЙ И ЧТЕНИЙ\n\n' + '\n'.join(entries[:20])
                if entries else '💬 Постоянные чаты появятся после подтверждения участия.')
    if command == '/code':
        if not student:
            return 'Сначала зарегистрируйтесь или привяжите профиль через /link КОД.'
        target, _, handle = rest.strip().partition(' ')
        target = target.lower()
        if target not in LINK_TARGETS:
            return 'Укажите нужную платформу: /code telegram, /code vk или /code max.'
        try:
            code = generate_link_code(student, target, handle.strip() or None)
        except ValueError as exc:
            return str(exc)
        label = {'telegram': 'Telegram', 'vk': 'ВКонтакте', 'max': 'MAX'}[target]
        return (f'Код для {label} (10 минут): {code}\n'
                'Откройте личный чат бота нужной платформы и введите код через /link. Затем ПОДТВЕРДИТЕ запрос здесь, либо отклоните его.')
    if command == '/register':
        if student and student.council_registered:
            return 'Профиль уже создан. Используйте /me.'
        _put_flow(platform, user_id, {'kind': 'registration', 'field': 'education_type',
                                      'public_username': verified_sender_handle(platform, user_id, username)
                                      if platform == 'max' else None})
        return '✨ Регистрация · шаг 1 из 4\nВыберите учебный контур: 🏫 колледж или 🎓 институт.\nДля отмены — /cancel.'
    if command in {'/science', '/readings', '/science_apply', '/science_confirm', '/science_decline'}:
        return 'Неизвестная команда. Список команд: /help.'
    flow_reply = _flow_message(platform, user_id, text, username=username)
    if flow_reply is not None:
        return flow_reply
    if not student or not student.council_registered:
        return welcome_text()
    if command in {'/leadership', '/leaders', '/руководство'}:
        from services.leadership_directory import leadership_plain_text
        return leadership_plain_text()
    if command == '/me':
        scope = 'Колледж' if student.education_type == 'college' else 'Институт'
        return f'👤 {student.full_name}\n🏫 {scope}\nГруппа: {student.group or "—"}\nВаш профиль синхронизирован.'
    if command == '/directions':
        dirs = available_application_directions(student)
        if not dirs:
            return '📝 Сейчас нет направлений, в которые можно подать новое заявление. Проверьте статусы заявок или обратитесь к руководителю.'
        return '📝 Направления для заявки\n\n' + '\n'.join(f'{d.id}. {d.icon or "•"} {d.name}' for d in dirs[:50]) + '\n\nВыберите направление кнопкой ниже.'
    if command == '/apply':
        if not rest.strip().isdigit():
            return 'Укажите номер направления: /apply 3. Посмотрите номера через /directions.'
        direction = Direction.query.get(int(rest.strip()))
        allowed_ids = {item.id for item in available_application_directions(student)}
        if not direction or direction.id not in allowed_ids:
            return ('Направление сейчас недоступно для новой заявки. Проверьте статус существующей заявки '
                    'или срок ограничения после отказа и откройте /directions заново.')
        questions = DirectionQuestion.query.filter_by(direction_id=direction.id).order_by(DirectionQuestion.sort_order, DirectionQuestion.id).all()
        if questions:
            _put_flow(platform, user_id, {
                'kind': 'application', 'direction_id': direction.id,
                'questions': [q.id for q in questions], 'required': [q.is_required for q in questions],
                'index': 0, 'answers': {},
            })
            return f'Заявка: {direction.name}\nВопрос 1/{len(questions)}: {questions[0].question_text}'
        ok, result = submit_application(student, direction, source=platform)
        return ('✅ ' if ok else '⚠️ ') + result
    if command == '/inbox':
        from services.permissions import can_manage_direction
        rows = db.session.execute(student_directions.select().where(
            student_directions.c.status.in_([DirectionStatus.PENDING.value, DirectionStatus.INTERVIEW.value])
        ).limit(300)).all()
        directions = {row.id: row.name for row in Direction.query.all()}
        pending = []
        for row in rows:
            applicant = Student.query.get(row.student_id)
            if not applicant or not can_manage_direction(student.tg_id, row.direction_id, applicant.education_type):
                continue
            pending.append(f'#{applicant.id}: {applicant.full_name} · {directions.get(row.direction_id, "Направление")} (ID {row.direction_id})')
            if len(pending) >= 25:
                break
        if not pending:
            return 'Нет заявок, доступных вам для рассмотрения.'
        return ('Заявки на рассмотрении:\n' + '\n'.join(pending) +
                '\n\nДля принятия: /approve ID_СТУДЕНТА ID_НАПРАВЛЕНИЯ'
                '\nДля отказа: /reject ID_СТУДЕНТА ID_НАПРАВЛЕНИЯ Причина')
    if command in {'/approve', '/reject'}:
        values = rest.strip().split(maxsplit=2)
        if len(values) < 2 or not values[0].isdigit() or not values[1].isdigit():
            return (f'Формат: {command} ID_СТУДЕНТА ID_НАПРАВЛЕНИЯ' +
                    (' Причина (не менее 5 символов)' if command == '/reject' else ''))
        reason = values[2] if len(values) == 3 else None
        # The shared service applies role, direction AND applicant-cohort checks.
        from services.applications import set_application_status
        decision = DirectionStatus.ACTIVE.value if command == '/approve' else DirectionStatus.REJECTED.value
        ok, result, _ = set_application_status(
            int(values[0]), int(values[1]), decision,
            actor_tg_id=student.tg_id, reason=reason, source=platform,
        )
        return ('✅ ' if ok else '⚠️ ') + result
    if command == '/status':
        rows = db.session.execute(student_directions.select().where(student_directions.c.student_id == student.id)).all()
        if not rows:
            return 'У вас пока нет заявок. Используйте /directions.'
        names = {d.id: d.name for d in Direction.query.all()}
        labels = {'pending':'на рассмотрении','interview':'собеседование','active':'участник','rejected':'отклонена'}
        return 'Ваши заявки:\n' + '\n'.join(f'• {names.get(row.direction_id,"Направление")} — {labels.get(row.status,row.status)}' for row in rows)
    if command in {'/events', '/event', '/join', '/decline', '/return'}:
        from services.shared_event_actions import (visible_events, event_for_student,
                 event_detail, join_event, decline_event, return_to_event)
        if command == '/events':
            events = visible_events(student)
            if not events:
                return '🎟 Мои мероприятия\n\nСейчас нет открытых мероприятий для ваших активных направлений.'
            return '🎟 Мои мероприятия\n\n' + '\n'.join(
                f'• #{q.id}: {q.event_title}' for q in events[:20]) + \
                '\n\nНажмите на мероприятие ниже, чтобы посмотреть даты и записаться.'
        if command == '/event':
            if not rest.isdigit():
                return 'Выберите мероприятие из /events.'
            return event_detail(student, int(rest))
        if command == '/join':
            bits = rest.split()
            if len(bits) != 2 or not bits[0].isdigit():
                return 'Выберите дату в карточке мероприятия /events.'
            return join_event(student, int(bits[0]), bits[1], platform=platform)
        if command == '/decline':
            quota, _, reason = rest.partition(' ')
            if not quota.isdigit():
                return 'Выберите мероприятие из /events.'
            if not reason.strip():
                if not event_for_student(student, int(quota)):
                    return 'Мероприятие недоступно.'
                _put_flow(platform, user_id, {'kind':'event_decline', 'quota_id':int(quota)})
                return '✕ Укажите причину отказа (от 5 до 2000 символов) следующим сообщением. /cancel — отмена.'
            return decline_event(student, int(quota), reason, platform=platform)
        if command == '/return':
            if not rest.isdigit():
                return 'Выберите мероприятие из /events.'
            return return_to_event(student, int(rest), platform=platform)
    return 'Неизвестная команда. Список команд: /help.'


def bot_screen(platform, user_id, command, *, action=None):
    """Return a native-keyboard-independent screen for Telegram, VK and MAX.

    Called after handle_private_text while a Flask app context is active.
    """
    from services.bot_ui import rows_for_screen
    user = student_for(platform, user_id)
    flow = _get_flow(platform, user_id)
    action = (action or command).lower().split(' ', 1)[0]
    if action in {'/science', '/readings', '/science_apply', '/science_confirm', '/science_decline'}:
        action = '/help'
    if not user or not user.council_registered:
        if flow and flow['kind'] == 'link_code_entry':
            return {'screen': 'link', 'rows': rows_for_screen('link'), 'app': False}
        if flow and flow['kind'] == 'registration':
            name = 'education' if flow.get('field') == 'education_type' else 'registration'
            return {'screen': name, 'rows': rows_for_screen(name), 'app': False}
        return {'screen': 'welcome', 'rows': rows_for_screen('welcome'), 'app': False}
    if flow and flow['kind'] == 'unlink_confirm':
        return {'screen': 'unlink_confirm',
                'rows': rows_for_screen('unlink_confirm', target_platform=flow.get('target_platform')), 'app': False}
    if flow and flow['kind'] in ('target_handle_entry','link_code_entry','registration','application','event_decline'):
        return {'screen': 'question', 'rows': rows_for_screen('question'), 'app': False}
    action = (action or command).lower().split(' ', 1)[0]
    aliases = {'/event':'event','/start':'home','/help':'home','/directions':'directions',
               '/apply':'question','/status':'status','/me':'profile','/accounts':'accounts',
               '/leadership':'leadership','/events':'events','/inbox':'inbox',
               '/my_chats':'home','/chats':'home','/code':'accounts','/app':'app','/student_app':'app'}
    screen = aliases.get(action, 'home')
    kwargs = {}
    if screen == 'directions':
        kwargs['directions'] = [(d.id, d.icon, d.name)
                                for d in available_application_directions(user)]
    if screen == 'events':
        from services.shared_event_actions import visible_events
        kwargs['events'] = [(q.id,q.event_title) for q in visible_events(user)]
    if screen == 'event':
        from services.shared_event_actions import event_for_student
        parts = command.strip().split()
        quota = event_for_student(user, int(parts[1])) if len(parts) == 2 and parts[1].isdigit() else None
        if quota:
            declined = bool(EventQuotaDecline.query.filter_by(quota_id=quota.id,student_id=user.id).first())
            days = [d.date.strftime('%Y-%m-%d') for d in quota.days if d.date.date() >= datetime.utcnow().date() and d.available_places()>0]
            kwargs['event'] = (quota.id,days,declined)
    if screen == 'accounts':
        kwargs['pending'] = [r['id'] for r in pending_link_requests(user)]
        status = linked_account_status(user)
        kwargs['linked'] = [name for name, val in status.items() if val['connected']]
        kwargs['current_platform'] = platform
    from services.messenger_transports import vk_app_url, max_app_url
    app_available = bool(vk_app_url() if platform == 'vk' else max_app_url() if platform == 'max' else False)
    return {'screen': screen, 'rows': rows_for_screen(screen, **kwargs),
            'app': screen in {'home','events','profile','status'} or (screen == 'app' and app_available)}


def handle_private_action(platform, user_id, action, username=None):
    """Map only allowlisted UI keys to the same command handlers as typed input."""
    from services.bot_ui import action_to_command
    if action in {'account_vk','account_max','account_telegram'}:
        command = {'account_vk':'/connectvk','account_max':'/connectmax',
                   'account_telegram':'/connecttelegram'}[action]
    else:
        command = action_to_command(action)
    if command is None:
        return '⚠️ Кнопка недействительна. Откройте /start.'
    return handle_private_text(platform, user_id, command, username=username)
