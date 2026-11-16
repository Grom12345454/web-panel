import html
import json
import logging
from datetime import datetime

from aiogram import Router, types, F
from aiogram.filters import CommandStart, Filter
from aiogram.types import (InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo,
                            KeyboardButton, ReplyKeyboardMarkup)
from sqlalchemy.orm import selectinload
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import (
    db, Student, Direction, DirectionQuestion, StudentLeadership, student_directions,
    EventQuota, DayParticipation, EventQuotaDecline, DirectionStatus, record_activity,
)
from config import settings
from bot_messages import text as bot_text

logger = logging.getLogger(__name__)
router = Router()

class EventDeclineFlow(StatesGroup):
    waiting_for_reason = State()

# Temporary, per-user Telegram question flow. Final answers are persisted in student_directions.extra_data.
pending_application_answers = {}

class PendingApplicationAnswer(Filter):
    async def __call__(self, message: types.Message) -> bool:
        state = pending_application_answers.get(message.from_user.id) if message.from_user else None
        return bool(state and state.get("chat_id") == message.chat.id and message.text and not message.text.startswith("/"))

def get_db_session():
    from bot import app_instance
    if not app_instance:
        raise RuntimeError("Flask app не инициализирован")
    ctx = app_instance.app_context()
    ctx.push()
    return ctx

def telegram_student_for(user_id):
    from services.multi_messenger import student_for
    return student_for('telegram', user_id)


def _bottom_reply_keyboard(rows):
    """Create the persistent Telegram keyboard docked beside the message composer."""
    keyboard = []
    for row in rows or ():
        buttons = []
        for item in row:
            label = str(item.label or '')[:64]
            if item.key == 'menu_app':
                from services.messenger_transports import _public_url
                if _public_url(settings.WEBAPP_URL):
                    buttons.append(KeyboardButton(
                        text=label, web_app=WebAppInfo(url=settings.WEBAPP_URL)))
                    continue
            buttons.append(KeyboardButton(text=label))
        if buttons:
            keyboard.append(buttons)
    return ReplyKeyboardMarkup(
        keyboard=keyboard, is_persistent=True, resize_keyboard=True,
        one_time_keyboard=False, input_field_placeholder='Выберите действие',
    )


def home_reply_keyboard(registered=True):
    from services.bot_ui import rows_for_screen
    return _bottom_reply_keyboard(rows_for_screen('home' if registered else 'welcome'))


def welcome_keyboard():
    """Same account-choice flow as VK and MAX, rendered with Telegram callbacks."""
    from services.bot_ui import rows_for_screen
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=b.label, callback_data=b.key) for b in row]
        for row in rows_for_screen('welcome')
    ])


def home_inline(registered: bool = True):
    from services.bot_ui import rows_for_screen
    if not registered:
        return welcome_keyboard()
    rows = []
    for row in rows_for_screen('home'):
        buttons = []
        for button in row:
            if button.key == 'menu_app':
                # Telegram Web Apps require a public HTTPS URL.
                from services.messenger_transports import _public_url
                if _public_url(settings.WEBAPP_URL):
                    buttons.append(InlineKeyboardButton(text=button.label,
                                   web_app=WebAppInfo(url=settings.WEBAPP_URL)))
                else:
                    buttons.append(InlineKeyboardButton(text=button.label, callback_data='menu_app'))
            elif button.key == 'menu_accounts':
                buttons.append(InlineKeyboardButton(text=button.label, callback_data='account_status'))
            else:
                buttons.append(InlineKeyboardButton(text=button.label, callback_data=button.key))
        if buttons:
            rows.append(buttons)
    return InlineKeyboardMarkup(inline_keyboard=rows)

def _overall_status(links):
    if not links:
        return "not_applied", "Не поданы заявки"
    statuses = [row.status for row in links]
    if any(status == DirectionStatus.ACTIVE.value for status in statuses):
        return "active", "Активный участник"
    if any(status in {DirectionStatus.PENDING.value, DirectionStatus.INTERVIEW.value} for status in statuses):
        return "review", "Заявки рассматриваются"
    if all(status == DirectionStatus.REJECTED.value for status in statuses):
        return "rejected", "Нужна новая заявка"
    return "review", "В процессе"

def _overall_status_icon(code):
    return {
        "not_applied": "○",
        "active": "✦",
        "review": "◷",
        "rejected": "↻",
    }.get(code, "•")

def _student_links(student):
    return db.session.execute(
        student_directions.select().where(student_directions.c.student_id == student.id)
    ).fetchall()

def available_application_directions(student):
    """Compatibility wrapper around the shared cross-platform application policy."""
    from services.applications import available_application_directions as get_available
    return get_available(student)

def direction_picker(student):
    from services.bot_ui import rows_for_screen
    directions = available_application_directions(student)
    shared_rows = rows_for_screen('directions', directions=[(d.id, d.icon, d.name) for d in directions])
    rows = [[InlineKeyboardButton(text=item.label, callback_data=item.key) for item in row]
            for row in shared_rows]
    links = _student_links(student)
    intro = bot_text("application_first") if not links else bot_text("application_next")
    if not directions:
        rows.insert(0, [InlineKeyboardButton(text="Все доступные направления уже выбраны", callback_data="noop")])
    return (
        bot_text("application_title") + "\n\n"
        f"{intro}\n\n"
        "Нажмите на карточку направления ниже, чтобы отправить заявку.",
        InlineKeyboardMarkup(inline_keyboard=rows),
    )

def _shared_keyboard(screen):
    """Render the common cross-platform navigation contract in Telegram."""
    from services.bot_ui import rows_for_screen
    rows = []
    for row in rows_for_screen(screen):
        buttons = []
        for item in row:
            callback = {'menu_accounts': 'account_status'}.get(item.key, item.key)
            buttons.append(InlineKeyboardButton(text=item.label, callback_data=callback))
        if buttons:
            rows.append(buttons)
    return InlineKeyboardMarkup(inline_keyboard=rows)

def profile_inline():
    return _shared_keyboard('profile')

async def show_home(message, greeting: bool = True, user_id=None):
    ctx = None
    try:
        ctx = get_db_session()
        tg_id = user_id or message.from_user.id
        student = telegram_student_for(tg_id)
        if not student or not student.council_registered:
            from services.bot_ui import welcome_text
            text = html.escape(welcome_text())
            from services.bot_ui import rows_for_screen
            keyboard = _bottom_reply_keyboard(rows_for_screen('welcome'))
        else:
            from services.bot_ui import home_text, rows_for_screen
            text = html.escape(home_text(student.full_name))
            keyboard = _bottom_reply_keyboard(rows_for_screen('home'))

        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    finally:
        if ctx:
            ctx.pop()

async def show_my_status(target, student):
    """Display application status and available chat links for current memberships."""
    ctx = None
    try:
        ctx = get_db_session()
        # Re-fetch after entering the app context so the ORM instance is attached.
        student = Student.query.filter_by(id=student.id).first()
        if not student:
            return
        from services.chair_membership import has_membership_role, sync_student_leadership_memberships
        if has_membership_role(student.id):
            changed = sync_student_leadership_memberships(student.id)
            if changed:
                db.session.commit()
                student = Student.query.filter_by(id=student.id).first()
                if not student:
                    return
        links = _student_links(student)
        lines = [bot_text("status_title"), "", f"ФИО: {html.escape(student.full_name)}", ""]
        buttons = []
        if not links:
            lines.append(bot_text("status_not_applied"))
        else:
            labels = {
                DirectionStatus.PENDING.value: "На рассмотрении",
                DirectionStatus.INTERVIEW.value: "Назначено собеседование",
                DirectionStatus.ACTIVE.value: "Активное участие",
                DirectionStatus.REJECTED.value: "Отклонено",
            }
            from services.telegram import sync_student_direction_invites
            for link in links:
                direction = Direction.query.get(link.direction_id)
                if not direction:
                    continue
                lines.append(f"<b>{html.escape(direction.name)}</b> — {labels.get(link.status, 'Статус уточняется')}.")
                if link.status == DirectionStatus.REJECTED.value:
                    from services.applications import latest_application_decision, active_application_block
                    decision = latest_application_decision(student.id, direction.id)
                    block = active_application_block(student.id, direction.id)
                    if decision and decision.reason:
                        lines.append(f"  Причина отказа: {html.escape(decision.reason)}")
                    if block and block.blocked_until:
                        lines.append(f"  Повторная подача доступна после {block.blocked_until.strftime('%d.%m.%Y в %H:%M')}.")
                    else:
                        lines.append("  Ограничение снято или срок истёк — можно подать заявление повторно.")
                if link.status == DirectionStatus.ACTIVE.value:
                    try:
                        invite_links = sync_student_direction_invites(student, direction)
                    except Exception:
                        logger.exception("Unable to refresh Telegram invite links for student #%s", student.id)
                        invite_links = []
                    for item in invite_links:
                        title = f"{direction.icon or '🔗'} {direction.name} · {item['title']}"
                        buttons.append([InlineKeyboardButton(
                            text=title[:64],
                            url=item["link"],
                        )])
                    if not invite_links:
                        lines.append(
                            "  Ссылка на чат пока недоступна: проверьте, что к направлению подключён активный чат, "
                            "а у бота есть право приглашать участников."
                        )
        from services.bot_ui import rows_for_screen
        for row in rows_for_screen('status'):
            buttons.append([InlineKeyboardButton(text=item.label, callback_data=item.key) for item in row])
        text = "\n".join(lines)
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        if isinstance(target, types.CallbackQuery):
            await target.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await target.answer(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        logger.exception("Unable to render application statuses")
        if isinstance(target, types.CallbackQuery):
            await target.answer("Не удалось получить данные заявлений.", show_alert=True)
    finally:
        if ctx:
            ctx.pop()

async def show_events(message, user_id=None, edit=False):
    ctx = None
    try:
        ctx = get_db_session()
        tg_id = user_id or message.from_user.id
        student = telegram_student_for(tg_id)
        if not student:
            text = "📅 <b>Мероприятия</b>\n\nСначала создайте профиль через «Подать заявку»."
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📝  Подать заявку", callback_data="menu_apply")],
                [InlineKeyboardButton(text="‹  Назад", callback_data="menu_home")],
            ])
            await message.edit_text(text, reply_markup=keyboard, parse_mode="HTML") if edit else await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
            return

        active_direction_ids = {
            row.direction_id for row in db.session.execute(
                student_directions.select().where(
                    (student_directions.c.student_id == student.id) &
                    (student_directions.c.status == DirectionStatus.ACTIVE.value)
                )
            ).fetchall()
        }
        quotas = EventQuota.query.filter_by(is_closed=False).order_by(EventQuota.id.desc()).all()
        visible = [q for q in quotas if any(d.id in active_direction_ids for d in q.directions)]
        if not visible:
            text = "📅 <b>Мои мероприятия</b>\n\nСейчас нет активных мероприятий для ваших направлений."
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="‹  Назад в меню", callback_data="menu_home")],
            ])
            await message.edit_text(text, reply_markup=keyboard, parse_mode="HTML") if edit else await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
            return

        if edit:
            await message.edit_text("📅 <b>Мои мероприятия</b>\n\nНиже — доступные события.", parse_mode="HTML")
        else:
            await message.answer("📅 <b>Мои мероприятия</b>\n\nНиже — доступные события.", parse_mode="HTML")

        for quota in visible[:8]:
            builder = InlineKeyboardBuilder()
            decline = EventQuotaDecline.query.filter_by(quota_id=quota.id, student_id=student.id).first()
            if decline:
                details = [
                    f"📌 <b>{html.escape(quota.event_title)}</b>",
                    f"📍 {html.escape(quota.location or 'Место уточняется')}",
                    "\n⛔ <b>Отказ от мероприятия зарегистрирован</b>",
                    f"Причина: {html.escape(decline.reason)}",
                ]
                if decline.created_at:
                    details.append(f"Дата отказа: {decline.created_at.strftime('%d.%m.%Y %H:%M')}")
                builder.button(text="↩ Вернуться к мероприятию", callback_data=f"return_event_{quota.id}")
            else:
                details = [f"📌 <b>{html.escape(quota.event_title)}</b>", f"📍 {html.escape(quota.location or 'Место уточняется')}"]
                if quota.time_range:
                    details.append(f"🕒 {html.escape(quota.time_range)}")
                if quota.event_description:
                    details.append(f"\n{html.escape(quota.event_description)}")
                active_registration_found = False
                for day in quota.days:
                    if day.date.date() < datetime.utcnow().date():
                        continue
                    participation = DayParticipation.query.filter_by(student_id=student.id, day_id=day.id).first()
                    if participation and participation.status != "cancelled":
                        active_registration_found = True
                        builder.button(
                            text=f"✕ Отказаться · {day.date.strftime('%d.%m')}",
                            callback_data=f"decline_event_{quota.id}",
                        )
                    elif day.available_places() > 0:
                        builder.button(
                            text=f"📅 Записаться · {day.date.strftime('%d.%m')} · мест {day.available_places()}",
                            callback_data=f"join_day_{quota.id}_{day.date.strftime('%Y-%m-%d')}"
                        )
                if not active_registration_found:
                    builder.button(text="✕ Отказаться от мероприятия", callback_data=f"decline_event_{quota.id}")
            builder.button(text="‹ В главное меню", callback_data="menu_home")
            builder.adjust(1)
            await message.answer("\n".join(details), reply_markup=builder.as_markup(), parse_mode="HTML")
    except Exception:
        logger.exception("Events render failed")
        await message.answer("⚠️ Не удалось загрузить мероприятия. Попробуйте ещё раз.")
    finally:
        if ctx:
            ctx.pop()

@router.message(CommandStart())
async def cmd_start(message: types.Message):
    if message.chat.type != 'private':
        await message.answer('Откройте личный чат бота, чтобы создать или подключить аккаунт.')
        return
    await show_home(message, greeting=True)

@router.callback_query(F.data == "noop")
async def noop(callback: types.CallbackQuery):
    await callback.answer("Все доступные направления уже выбраны")

@router.callback_query(F.data == 'onboarding_existing')
async def onboarding_existing(callback: types.CallbackQuery):
    if not callback.message or callback.message.chat.type != 'private':
        await callback.answer('Откройте личный чат бота', show_alert=True)
        return
    await callback.answer()
    await callback.message.answer(
        '🔐 <b>Уже есть аккаунт</b>\n\n'
        'Откройте «Привязанные аккаунты» в существующем боте или Student App, '
        'создайте код для Telegram и введите его здесь.\n\n'
        'Ваш исходный профиль должен одобрить запрос. Без подтверждения доступ не откроется.\n\n'
        'Введите код следующим сообщением:',
        parse_mode='HTML',
        reply_markup=__import__('aiogram').types.ForceReply(selective=True,
                    input_field_placeholder='Одноразовый код (20 символов)'),
    )


@router.callback_query(F.data == 'onboarding_new')
async def onboarding_new(callback: types.CallbackQuery):
    from handlers.registration import start_registration_flow
    if not callback.message or callback.message.chat.type != 'private':
        await callback.answer('Откройте личный чат бота', show_alert=True)
        return
    await callback.answer()
    await start_registration_flow(callback.message, tg_id=callback.from_user.id, edit=True)


@router.callback_query(F.data == 'menu_app')
async def menu_app_info(callback: types.CallbackQuery):
    await callback.answer('Добавьте публичный WEBAPP_URL в .env, чтобы открыть Student App.', show_alert=True)


@router.message(__import__('aiogram').filters.Command('inbox', 'approve', 'reject'))
async def telegram_leader_commands(message: types.Message):
    """The same permissions and decision service as VK and MAX."""
    if message.chat.type != 'private':
        return
    ctx = get_db_session()
    try:
        from services.multi_messenger import handle_private_text
        response = handle_private_text('telegram', message.from_user.id, message.text or '')
    finally:
        ctx.pop()
    await message.answer(html.escape(response), parse_mode='HTML',
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                             [InlineKeyboardButton(text='‹ В меню', callback_data='menu_home')]]))


@router.callback_query(F.data == 'menu_inbox')
async def menu_inbox(callback: types.CallbackQuery):
    await callback.answer()
    ctx = get_db_session()
    try:
        from services.multi_messenger import handle_private_text
        body = handle_private_text('telegram', callback.from_user.id, '/inbox')
    finally:
        ctx.pop()
    keyboard = _shared_keyboard('inbox')
    await callback.message.edit_text(html.escape(body), reply_markup=keyboard, parse_mode='HTML')


@router.callback_query(F.data == "menu_home")
async def menu_home(callback: types.CallbackQuery):
    await callback.answer()
    pending_application_answers.pop(callback.from_user.id, None)
    ctx = None
    try:
        ctx = get_db_session()
        student = telegram_student_for(callback.from_user.id)
        if not student or not student.council_registered:
            await callback.message.edit_text(
                html.escape(__import__('services.bot_ui', fromlist=['welcome_text']).welcome_text()),
                reply_markup=welcome_keyboard(),
                parse_mode="HTML",
            )
            return
        await callback.message.edit_text(
            html.escape(__import__('services.bot_ui', fromlist=['home_text']).home_text(student.full_name)),
            reply_markup=home_inline(registered=True),
            parse_mode="HTML"
        )
    finally:
        if ctx:
            ctx.pop()

@router.callback_query(F.data == "menu_leadership")
async def menu_leadership(callback: types.CallbackQuery):
    await callback.answer()
    ctx = None
    try:
        ctx = get_db_session()
        from services.leadership_directory import leadership_cards
        cards = leadership_cards()
        parts = ["<b>🏛 Руководство студсовета</b>"]
        for card in cards:
            item = ("<b>" + html.escape(card['position']) + "</b>\n" +
                    html.escape(card['full_name']) + "\n" +
                    "Ответственность: " + html.escape(card['direction_name']))
            for link in card['links']:
                item += ('\n<a href="' + html.escape(link['url'], quote=True) + '">' +
                         html.escape(link['label'] + ' · ' + link['handle']) + '</a>')
            parts.append(item)
        if not cards:
            parts.append("Список руководителей пока не заполнен.")
        keyboard = _shared_keyboard('leadership')
        body = "\n\n━━━━━━━━━━━━\n\n".join(parts)
        if len(body) <= 3900:
            await callback.message.edit_text(body, reply_markup=keyboard,
                                             parse_mode="HTML", disable_web_page_preview=True)
        else:
            await callback.message.edit_text(parts[0], parse_mode="HTML")
            for part in parts[1:]:
                await callback.message.answer(part, parse_mode="HTML", disable_web_page_preview=True)
            await callback.message.answer("Выберите действие:", reply_markup=keyboard)
    except Exception:
        logger.exception("Could not show leadership directory in Telegram")
        await callback.message.answer("Не удалось загрузить руководство. Попробуйте позже.", reply_markup=home_inline(True))
    finally:
        if ctx:
            ctx.pop()


@router.callback_query(F.data == "menu_apply")
async def menu_apply(callback: types.CallbackQuery):
    from handlers.registration import start_registration_flow

    # Re-opening the application menu abandons any unfinished question flow.
    pending_application_answers.pop(callback.from_user.id, None)
    ctx = None
    try:
        ctx = get_db_session()
        student = telegram_student_for(callback.from_user.id)
        await callback.answer()
        if not student or not student.council_registered:
            from services.bot_ui import welcome_text
            await callback.message.edit_text(html.escape(welcome_text()),
                                             reply_markup=welcome_keyboard(), parse_mode='HTML')
            return
        text, keyboard = direction_picker(student)
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    finally:
        if ctx:
            ctx.pop()

@router.callback_query(F.data == "menu_status")
async def menu_status(callback: types.CallbackQuery):
    ctx = None
    try:
        ctx = get_db_session()
        student = telegram_student_for(callback.from_user.id)
        if not student:
            await callback.answer("Сначала создайте профиль", show_alert=True)
            return
        await callback.answer()
        await show_my_status(callback, student)
    finally:
        if ctx:
            ctx.pop()

@router.callback_query(F.data == "menu_events")
async def menu_events(callback: types.CallbackQuery):
    await callback.answer()
    await show_events(callback.message, callback.from_user.id, edit=True)

@router.callback_query(F.data == "menu_profile")
async def menu_profile(callback: types.CallbackQuery):
    ctx = None
    try:
        ctx = get_db_session()
        student = telegram_student_for(callback.from_user.id)
        if not student:
            await callback.answer("Профиль ещё не создан", show_alert=True)
            return
        await callback.answer()
        await callback.message.edit_text(
            "👤 <b>Профиль</b>\n\n"
            f"<b>{html.escape(student.full_name)}</b>\n"
            f"🎓 Контур: {'Колледж' if student.education_type=='college' else 'Институт'}\n"
            f"🎓 Группа: {html.escape(student.group or '—')}\n"
            f"📞 Телефон: {html.escape(student.phone or '—')}\n",
            reply_markup=profile_inline(),
            parse_mode="HTML",
        )
    finally:
        if ctx:
            ctx.pop()

@router.callback_query(F.data.in_({"menu_help", "leader_add", "leader_remove"}))
async def removed_legacy_menu_items(callback: types.CallbackQuery):
    """Old inline keyboards can outlive the menu revision; acknowledge them safely."""
    await callback.answer("Этот пункт меню больше недоступен.", show_alert=True)

@router.callback_query(F.data.startswith("dir_") | F.data.startswith("direction_"))
async def choose_direction(callback: types.CallbackQuery):
    dir_id = int(callback.data.split("_", 1)[1])
    ctx = None
    try:
        ctx = get_db_session()
        student = telegram_student_for(callback.from_user.id)
        direction = Direction.query.get(dir_id)
        if not student or not student.council_registered or not direction:
            await callback.answer("Сначала зарегистрируйтесь в студенческом совете", show_alert=True)
            return

        allowed = {d.id for d in available_application_directions(student)}
        if dir_id not in allowed:
            await callback.answer("Это направление недоступно для текущей заявки", show_alert=True)
            return

        question_rows = DirectionQuestion.query.filter_by(direction_id=direction.id).order_by(DirectionQuestion.sort_order, DirectionQuestion.id).all()
        if question_rows:
            pending_application_answers[callback.from_user.id] = {
                "student_id": student.id,
                "direction_id": direction.id,
                "chat_id": callback.message.chat.id,
                "questions": [{"id": q.id, "question": q.question_text, "required": bool(q.is_required)} for q in question_rows],
                "index": 0,
                "answers": {},
            }
            current = pending_application_answers[callback.from_user.id]["questions"][0]
            await callback.answer("Нужно ответить на вопросы")
            await callback.message.answer(
                f"📝 <b>Дополнительный вопрос 1 из {len(question_rows)}</b>\n\n{html.escape(current['question'])}"
                + ("\n\n<i>Ответ обязателен.</i>" if current["required"] else "\n\n<i>Можно ответить «—», чтобы пропустить.</i>"),
                parse_mode="HTML",
            )
            return
        from services.applications import submit_application
        submitted, submit_message = submit_application(student, direction, source="telegram", answers={})
        if not submitted:
            await callback.answer(submit_message, show_alert=True)
            await show_my_status(callback, student)
            return

        await callback.answer("Заявка отправлена")
        # After one submitted application, return to the exact same main screen
        # that the /start command uses. The callback toast confirms the submission.
        await callback.message.edit_text(
            bot_text("welcome_user", full_name=html.escape(student.full_name)),
            reply_markup=home_inline(registered=True),
            parse_mode="HTML",
        )
    except Exception:
        db.session.rollback()
        logger.exception("Direction selection failed")
        await callback.answer("⚠️ Не удалось отправить заявку", show_alert=True)
    finally:
        if ctx:
            ctx.pop()

@router.message(F.text == "/cancel")
async def cancel_pending_application(message: types.Message):
    if not message.from_user:
        return
    user_id = message.from_user.id
    cancelled = bool(pending_application_answers.pop(user_id, None))
    try:
        from handlers.registration import registration_data
        cancelled = bool(registration_data.pop(user_id, None)) or cancelled
    except Exception:
        pass
    try:
        from services.multi_messenger import _get_flow, _clear_flow
        if _get_flow('telegram', user_id):
            _clear_flow('telegram', user_id)
            cancelled = True
    except Exception:
        logger.debug('Could not clear shared Telegram flow', exc_info=True)
    if cancelled:
        await message.answer("Действие отменено. Вы можете начать заново из меню.",
                             reply_markup=home_reply_keyboard(True))


@router.message(PendingApplicationAnswer())
async def collect_application_answer(message: types.Message):
    state = pending_application_answers.get(message.from_user.id) if message.from_user else None
    if not state:
        return
    answer = " ".join((message.text or "").split())
    question = state["questions"][state["index"]]
    if question["required"] and not answer:
        await message.answer("На этот вопрос нужно ответить. Пожалуйста, введите ответ.")
        return
    if answer and answer != "—":
        state["answers"][str(question["id"])] = answer[:2000]
    state["index"] += 1
    if state["index"] < len(state["questions"]):
        next_q = state["questions"][state["index"]]
        await message.answer(
            f"📝 <b>Дополнительный вопрос {state['index'] + 1} из {len(state['questions'])}</b>\n\n{html.escape(next_q['question'])}"
            + ("\n\n<i>Ответ обязателен.</i>" if next_q["required"] else "\n\n<i>Можно ответить «—», чтобы пропустить.</i>"),
            parse_mode="HTML",
        )
        return
    app_state = dict(state)
    pending_application_answers.pop(message.from_user.id, None)
    ctx = None
    try:
        ctx = get_db_session()
        student = Student.query.get(app_state["student_id"])
        direction = Direction.query.get(app_state["direction_id"])
        if not student or not direction:
            await message.answer("Студент или направление больше не найдены.")
            return
        from services.applications import submit_application
        submitted, result = submit_application(student, direction, source="telegram", answers=app_state["answers"])
        if not submitted:
            await message.answer(result)
            return
        await message.answer("✅ Заявление отправлено на рассмотрение. Ваши ответы прикреплены к заявке.", reply_markup=home_inline(True))
    except Exception:
        db.session.rollback()
        logger.exception("Unable to submit Telegram application with answers")
        await message.answer("Не удалось отправить заявление. Попробуйте снова через меню.")
    finally:
        if ctx:
            ctx.pop()


@router.callback_query(F.data.startswith("remove_dir_"))
async def remove_direction(callback: types.CallbackQuery):
    dir_id = int(callback.data.split("remove_dir_")[1])
    ctx = None
    try:
        ctx = get_db_session()
        student = telegram_student_for(callback.from_user.id)
        if not student:
            await callback.answer("Профиль не найден", show_alert=True)
            return
        link = db.session.execute(student_directions.select().where(
            (student_directions.c.student_id == student.id) &
            (student_directions.c.direction_id == dir_id)
        )).fetchone()
        if not link:
            await callback.answer("Заявка уже удалена", show_alert=True)
            return
        from services.chair_membership import direction_required_by_current_role
        if direction_required_by_current_role(student.id, dir_id):
            await callback.answer("Членство связано с вашей текущей должностью. Сначала снимите должность в веб-панели.", show_alert=True)
            return
        if link.status not in {DirectionStatus.PENDING.value, DirectionStatus.INTERVIEW.value, DirectionStatus.ACTIVE.value, DirectionStatus.REJECTED.value}:
            await callback.answer("Эту заявку нельзя отозвать", show_alert=True)
            return
        db.session.execute(student_directions.delete().where(
            (student_directions.c.student_id == student.id) &
            (student_directions.c.direction_id == dir_id)
        ))
        direction = Direction.query.get(dir_id)
        record_activity(
            "bot_application_withdrawn",
            f'Студент отозвал через Telegram-бота заявление из направления «{direction.name if direction else dir_id}».',
            student_id=student.id,
            direction_id=dir_id,
        )
        db.session.commit()
        # Always reconcile chat access after removing the association, even if
        # its status was pending/rejected: stale invite links may still exist.
        try:
            from services.telegram import remove_student_from_direction_chats
            remove_student_from_direction_chats(student, Direction.query.get(dir_id))
        except Exception:
            logger.exception("Не удалось удалить студента из Telegram-чатов после отзыва")
        await callback.answer("Направление удалено")
        await show_my_status(callback, student)
    except Exception:
        logger.exception("Direction removal failed")
        await callback.answer("⚠️ Не удалось отозвать заявку", show_alert=True)
    finally:
        if ctx:
            ctx.pop()

@router.callback_query(F.data.startswith("decline_event_"))
async def start_event_decline(callback: types.CallbackQuery, state: FSMContext):
    ctx = None
    try:
        quota_id = int(callback.data.rsplit("_", 1)[1])
        ctx = get_db_session()
        student = telegram_student_for(callback.from_user.id)
        quota = EventQuota.query.get(quota_id)
        if not student or not quota or quota.is_closed:
            await callback.answer("Мероприятие недоступно", show_alert=True)
            return
        active_ids = {row.direction_id for row in db.session.execute(student_directions.select().where(
            (student_directions.c.student_id == student.id) &
            (student_directions.c.status == DirectionStatus.ACTIVE.value)
        )).fetchall()}
        if not any(direction.id in active_ids for direction in quota.directions):
            await callback.answer("Мероприятие недоступно для вашего профиля", show_alert=True)
            return
        await state.update_data(event_quota_id=quota.id)
        await state.set_state(EventDeclineFlow.waiting_for_reason)
        await callback.message.answer(
            "📝 " + bot_text("decline_prompt", title=html.escape(quota.event_title)),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Не отказываться", callback_data="cancel_event_decline")]
            ]),
            parse_mode="HTML",
        )
        await callback.answer()
    except (ValueError, TypeError):
        await callback.answer("Некорректный идентификатор мероприятия", show_alert=True)
    except Exception:
        logger.exception("Could not start event decline flow")
        await callback.answer("Не удалось открыть форму отказа", show_alert=True)
    finally:
        if ctx:
            ctx.pop()

@router.callback_query(F.data == "cancel_event_decline")
async def cancel_event_decline(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        bot_text("decline_cancelled"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📅 Мои мероприятия", callback_data="menu_events")],
            [InlineKeyboardButton(text="‹ В меню", callback_data="menu_home")],
        ]),
    )
    await callback.answer()

@router.message(EventDeclineFlow.waiting_for_reason, F.text)
async def save_event_decline(message: types.Message, state: FSMContext):
    reason = (message.text or "").strip()
    if len(reason) < 5:
        await message.answer(bot_text("decline_reason_short"))
        return
    if len(reason) > 2000:
        await message.answer("Причина слишком длинная. Максимум 2 000 символов.")
        return
    ctx = None
    try:
        data = await state.get_data()
        quota_id = int(data.get("event_quota_id") or 0)
        ctx = get_db_session()
        student = telegram_student_for(message.from_user.id)
        quota = EventQuota.query.get(quota_id)
        if not student or not quota or quota.is_closed:
            await state.clear()
            await message.answer("Мероприятие больше недоступно. Обновите список мероприятий.")
            return
        active_ids = {row.direction_id for row in db.session.execute(student_directions.select().where(
            (student_directions.c.student_id == student.id) &
            (student_directions.c.status == DirectionStatus.ACTIVE.value)
        )).fetchall()}
        if not any(direction.id in active_ids for direction in quota.directions):
            await state.clear()
            await message.answer("Мероприятие больше недоступно для вашего профиля.")
            return
        decline = EventQuotaDecline.query.filter_by(quota_id=quota.id, student_id=student.id).first()
        if decline:
            decline.reason = reason
            decline.created_at = datetime.utcnow()
        else:
            db.session.add(EventQuotaDecline(quota_id=quota.id, student_id=student.id, reason=reason))
        for day in quota.days:
            participation = DayParticipation.query.filter_by(student_id=student.id, day_id=day.id).first()
            if participation and participation.status == "registered":
                participation.status = "cancelled"
        record_activity(
            "bot_quota_declined",
            f'Студент отказался через Telegram-бота от мероприятия «{quota.event_title}». Причина: {reason}',
            student_id=student.id,
            quota_id=quota.id,
        )
        db.session.commit()
        await state.clear()
        await message.answer(
            bot_text("decline_saved", title=html.escape(quota.event_title), reason=html.escape(reason)),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="↩ Вернуться к мероприятию", callback_data=f"return_event_{quota.id}")],
                [InlineKeyboardButton(text="📅 Мои мероприятия", callback_data="menu_events")],
            ]),
            parse_mode="HTML",
        )
    except Exception:
        if ctx:
            db.session.rollback()
        logger.exception("Could not store event decline")
        await message.answer(bot_text("decline_save_error"))
    finally:
        if ctx:
            ctx.pop()

@router.callback_query(F.data.startswith("return_event_"))
async def return_to_event(callback: types.CallbackQuery):
    ctx = None
    try:
        quota_id = int(callback.data.rsplit("_", 1)[1])
        ctx = get_db_session()
        student = telegram_student_for(callback.from_user.id)
        quota = EventQuota.query.get(quota_id)
        if not student or not quota or quota.is_closed:
            await callback.answer("Мероприятие недоступно", show_alert=True)
            return
        active_ids = {row.direction_id for row in db.session.execute(student_directions.select().where(
            (student_directions.c.student_id == student.id) &
            (student_directions.c.status == DirectionStatus.ACTIVE.value)
        )).fetchall()}
        if not any(direction.id in active_ids for direction in quota.directions):
            await callback.answer("Мероприятие недоступно для вашего профиля", show_alert=True)
            return
        decline = EventQuotaDecline.query.filter_by(quota_id=quota.id, student_id=student.id).first()
        if not decline:
            await callback.answer("Активный отказ уже отсутствует")
            return
        db.session.delete(decline)
        record_activity(
            "bot_quota_decline_reversed",
            f'Студент вернулся через Telegram-бота к мероприятию «{quota.event_title}»; отказ удалён.',
            student_id=student.id,
            quota_id=quota.id,
        )
        db.session.commit()
        await callback.message.edit_text(
            bot_text("decline_reversed", title=html.escape(quota.event_title)),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📅 Мои мероприятия", callback_data="menu_events")],
                [InlineKeyboardButton(text="‹ В меню", callback_data="menu_home")],
            ]),
            parse_mode="HTML",
        )
        await callback.answer("Отказ удалён")
    except (ValueError, TypeError):
        await callback.answer("Некорректный идентификатор мероприятия", show_alert=True)
    except Exception:
        if ctx:
            db.session.rollback()
        logger.exception("Could not reverse event decline")
        await callback.answer("Не удалось вернуть мероприятие", show_alert=True)
    finally:
        if ctx:
            ctx.pop()

@router.callback_query(F.data.startswith("join_day_"))
async def join_specific_day(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    if len(parts) != 4:
        await callback.answer("⚠️ Ошибка данных мероприятия", show_alert=True)
        return
    quota_id, target_date_str = int(parts[2]), parts[3]
    ctx = None
    try:
        ctx = get_db_session()
        student = telegram_student_for(callback.from_user.id)
        quota = EventQuota.query.get(quota_id)
        if not student or not quota or quota.is_closed:
            await callback.answer("Мероприятие недоступно", show_alert=True)
            return

        active_direction_ids = {
            row.direction_id for row in db.session.execute(student_directions.select().where(
                (student_directions.c.student_id == student.id) &
                (student_directions.c.status == DirectionStatus.ACTIVE.value)
            )).fetchall()
        }
        if not any(d.id in active_direction_ids for d in quota.directions):
            await callback.answer("Для записи нужен активный статус в направлении мероприятия", show_alert=True)
            return
        if EventQuotaDecline.query.filter_by(quota_id=quota.id, student_id=student.id).first():
            await callback.answer("Сначала вернитесь к мероприятию — активный отказ будет удалён", show_alert=True)
            return

        target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
        target_day = next((day for day in quota.days if day.date.date() == target_date), None)
        if not target_day:
            await callback.answer("Эта дата больше недоступна", show_alert=True)
            return
        if target_day.available_places() <= 0:
            await callback.answer("Места на эту дату закончились", show_alert=True)
            return

        existing = DayParticipation.query.filter_by(student_id=student.id, day_id=target_day.id).first()
        if existing and existing.status != "cancelled":
            await callback.answer("Вы уже записаны на этот день", show_alert=True)
            return
        if existing and existing.status == "cancelled":
            existing.status = "registered"
        else:
            db.session.add(DayParticipation(student_id=student.id, day_id=target_day.id, status="registered"))
        record_activity(
            "bot_event_registered",
            f'Студент записался через Telegram-бота на мероприятие «{quota.event_title}» ({target_day.date.strftime("%d.%m.%Y")}).',
            student_id=student.id,
            quota_id=quota.id,
        )
        db.session.commit()
        try:
            from services.activity_chats import queue_student_invite
            queue_student_invite('event', quota.id, student)
        except Exception:
            logger.exception('Не удалось поставить приглашение мероприятия в очередь')

        await callback.message.edit_text(
            f"✅ <b>Запись подтверждена</b>\n\n"
            f"📌 {html.escape(quota.event_title)}\n"
            f"📅 {target_day.date.strftime('%d.%m.%Y')}\n"
            f"📍 {html.escape(quota.location or 'Место уточняется')}\n\n"
            "Добавьте событие в календарь и приходите вовремя.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📅  Мои мероприятия", callback_data="menu_events")],
                [InlineKeyboardButton(text="‹  В меню", callback_data="menu_home")],
            ]),
            parse_mode="HTML",
        )
        await callback.answer("Вы записаны")
    except Exception:
        logger.exception("Event registration failed")
        await callback.answer("⚠️ Ошибка при записи", show_alert=True)
    finally:
        if ctx:
            ctx.pop()


@router.callback_query(F.data == 'activity_chats_menu')
async def show_activity_chats_menu(callback: types.CallbackQuery):
    if not callback.message or callback.message.chat.type != 'private':
        await callback.answer('Доступно в личном чате с ботом.', show_alert=True)
        return
    from services.activity_chats import student_has_audience, by_telegram_id
    from database import SharedActivityChat
    from bot import app_instance
    if not app_instance:
        await callback.answer('Бот пока не готов.', show_alert=True)
        return
    with app_instance.app_context():
        student = by_telegram_id(callback.from_user.id)
        entries = []
        if student:
            for group in SharedActivityChat.query.filter_by(active=True).all():
                if group.invite_link and student_has_audience(student, group.audience):
                    entries.append(f'• {html.escape(group.title)}: {html.escape(group.invite_link)}')
        output = '💬 <b>Ваши чаты событий и чтений</b>\n\n' + ('\n'.join(entries[:20]) if entries else 'Доступных приглашений пока нет.')
    await callback.answer()
    await callback.message.answer(output[:3900], parse_mode='HTML')


@router.message(F.text)
async def bottom_keyboard_action(message: types.Message):
    """Dispatch persistent Telegram reply-keyboard labels and shared flow answers."""
    if not message.from_user or message.chat.type != 'private':
        return
    text = (message.text or '').strip()
    if not text or text.startswith('/'):
        return
    ctx = None
    try:
        ctx = get_db_session()
        from services.messenger_transports import _action_from_button_text
        from services.multi_messenger import (_get_flow, handle_private_action,
                                              handle_private_text, bot_screen)
        from services.bot_ui import action_to_command
        user_id = message.from_user.id
        action = _action_from_button_text('telegram', text, user_id)
        if action:
            # Clear Telegram-native form state when the shared bottom Cancel button is used.
            if action == 'flow_cancel':
                pending_application_answers.pop(user_id, None)
                try:
                    from handlers.registration import registration_data
                    registration_data.pop(user_id, None)
                except Exception:
                    pass
            response = handle_private_action('telegram', user_id, action,
                                             username=message.from_user.username)
            command = action_to_command(action) or {
                'account_vk': '/connectvk', 'account_max': '/connectmax',
                'account_telegram': '/connecttelegram',
            }.get(action, '/start')
        elif _get_flow('telegram', user_id):
            # Text entered for registration, application questions, account linking,
            # or event decline must continue the exact same state machine.
            response = handle_private_text('telegram', user_id, text,
                                           username=message.from_user.username)
            command = '/start'
        else:
            return
        screen = bot_screen('telegram', str(user_id), command, action=command)
        keyboard = _bottom_reply_keyboard(screen.get('rows', ()))
        if response:
            app_url = None
            if action == 'menu_app':
                from services.messenger_transports import _public_url
                if _public_url(settings.WEBAPP_URL):
                    app_url = settings.WEBAPP_URL
            if app_url:
                response += '\n' + app_url
            await message.answer(response, reply_markup=keyboard,
                                 disable_web_page_preview=True)
        else:
            await message.answer('Раздел обновлён.', reply_markup=keyboard)
    except Exception:
        logger.exception('Telegram bottom keyboard action failed')
        try:
            await message.answer('⚠️ Не удалось выполнить действие. Попробуйте ещё раз или отправьте /start.',
                                 reply_markup=home_reply_keyboard(True))
        except Exception:
            logger.debug('Could not send bottom keyboard fallback', exc_info=True)
    finally:
        if ctx:
            ctx.pop()
