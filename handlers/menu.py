import html
import json
import logging
from datetime import datetime

from aiogram import Router, types, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import (
    db, Student, Direction, student_directions, StudentLeadership,
    EventQuota, DayParticipation, DirectionStatus,
)

logger = logging.getLogger(__name__)
router = Router()


def get_db_session():
    from bot import app_instance
    if not app_instance:
        raise RuntimeError("Flask app не инициализирован")
    ctx = app_instance.app_context()
    ctx.push()
    return ctx


def is_any_leader(tg_id):
    ctx = None
    try:
        ctx = get_db_session()
        student = Student.query.filter_by(tg_id=tg_id).first()
        if not student:
            return False
        return StudentLeadership.query.filter_by(student_id=student.id).first() is not None
    except Exception as e:
        logger.error("Leadership check failed: %s", e)
        return False
    finally:
        if ctx:
            ctx.pop()


def home_inline(is_leader: bool = False, registered: bool = True):
    rows = [
        [
            InlineKeyboardButton(text="📝  Подать заявку", callback_data="menu_apply"),
            InlineKeyboardButton(text="📊  Общий статус", callback_data="menu_status"),
        ],
        [
            InlineKeyboardButton(text="📅  Мероприятия", callback_data="menu_events"),
            InlineKeyboardButton(text="👤  Профиль", callback_data="menu_profile"),
        ],
        [InlineKeyboardButton(text="❓  Помощь", callback_data="menu_help")],
    ]
    if is_leader and registered:
        rows.insert(2, [
            InlineKeyboardButton(text="👥  Управление студентами", callback_data="menu_leadership"),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _overall_status(links):
    if not links:
        return "not_applied", "Не поданы заявки"
    statuses = [row.status for row in links]
    if any(status == DirectionStatus.ACTIVE.value for status in statuses):
        return "active", "Активный участник"
    if any(status in {DirectionStatus.PENDING.value, DirectionStatus.INTERVIEW.value, DirectionStatus.APPROVED.value} for status in statuses):
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
    """First application is restricted to Student Council; later applications show all other directions."""
    links = _student_links(student)
    selected_ids = {row.direction_id for row in links}
    directions = Direction.query.order_by(Direction.name).all()

    if not links:
        council = next((d for d in directions if d.code == "STUDCOUNCIL"), None)
        return [council] if council else []

    return [d for d in directions if d.id not in selected_ids]


def direction_picker(student):
    directions = available_application_directions(student)
    rows = []
    if not directions:
        rows.append([InlineKeyboardButton(text="✓ Все доступные направления выбраны", callback_data="noop")])
    else:
        for direction in directions:
            rows.append([
                InlineKeyboardButton(
                    text=f"{direction.icon or '✦'}  {direction.name}",
                    callback_data=f"dir_{direction.id}",
                )
            ])
    links = _student_links(student)
    if not links:
        intro = "Первая заявка подаётся только в <b>Студсовет</b>."
    else:
        intro = "Выберите ещё одно направление. Уже выбранные направления здесь не показываются."
    rows.append([InlineKeyboardButton(text="‹  Назад в меню", callback_data="menu_home")])
    return (
        "📝 <b>Подача заявки</b>\n\n"
        f"{intro}\n\n"
        "Нажмите на карточку направления ниже, чтобы отправить заявку.",
        InlineKeyboardMarkup(inline_keyboard=rows),
    )


def leader_inline():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕  Добавить студента", callback_data="leader_add")],
        [InlineKeyboardButton(text="🗑  Удалить студента", callback_data="leader_remove")],
        [InlineKeyboardButton(text="‹  Назад в меню", callback_data="menu_home")],
    ])


def profile_inline():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊  Общий статус", callback_data="menu_status")],
        [InlineKeyboardButton(text="‹  Назад в меню", callback_data="menu_home")],
    ])


def help_inline():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Подать заявку", callback_data="menu_apply")],
        [InlineKeyboardButton(text="‹ Назад", callback_data="menu_home")],
    ])


async def show_home(message, greeting: bool = True, user_id=None):
    ctx = None
    try:
        ctx = get_db_session()
        tg_id = user_id or message.from_user.id
        student = Student.query.filter_by(tg_id=tg_id).first()
        if not student:
            text = (
                "🎓 <b>University Control</b>\n\n"
                "Добро пожаловать в цифровую среду студенческих направлений.\n\n"
                "Для начала создайте профиль — это займёт несколько шагов."
            )
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🚀  Начать регистрацию", callback_data="menu_apply")],
                [InlineKeyboardButton(text="❓  Как это работает", callback_data="menu_help")],
            ])
        else:
            text = (
                f"🎓 <b>University Control</b>\n\n"
                f"👋 {html.escape(student.full_name)}\n"
                "Ваш личный центр заявок, статусов и мероприятий.\n\n"
                "Выберите нужный раздел — всё управление находится в карточках ниже."
            )
            keyboard = home_inline(is_any_leader(tg_id), registered=True)

        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    finally:
        if ctx:
            ctx.pop()


async def show_my_status(target, student):
    ctx = None
    try:
        ctx = get_db_session()
        links = _student_links(student)
        code, label = _overall_status(links)
        active_count = sum(row.status == DirectionStatus.ACTIVE.value for row in links)
        review_count = sum(row.status in {DirectionStatus.PENDING.value, DirectionStatus.INTERVIEW.value, DirectionStatus.APPROVED.value} for row in links)
        rejected_count = sum(row.status == DirectionStatus.REJECTED.value for row in links)

        text = (
            f"📊 <b>Общий статус</b>\n\n"
            f"{_overall_status_icon(code)} <b>{label}</b>\n\n"
            f"👤 {html.escape(student.full_name)}\n"
            f"🎓 Группа: {html.escape(student.group or '—')}\n\n"
            f"<b>Сводка</b>\n"
            f"• Направлений: <b>{len(links)}</b>\n"
            f"• Активных: <b>{active_count}</b>\n"
            f"• На рассмотрении: <b>{review_count}</b>\n"
            f"• Отклонённых: <b>{rejected_count}</b>"
        )
        buttons = []
        if any(row.status in {DirectionStatus.PENDING.value, DirectionStatus.REJECTED.value} for row in links):
            buttons.append([InlineKeyboardButton(text="↻  Управление заявками", callback_data="menu_apply")])
        buttons.extend([
            [InlineKeyboardButton(text="📝  Подать ещё заявку", callback_data="menu_apply")],
            [InlineKeyboardButton(text="‹  Назад в меню", callback_data="menu_home")],
        ])
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

        if isinstance(target, types.CallbackQuery):
            await target.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await target.answer(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        logger.exception("Unable to render student status")
        if isinstance(target, types.CallbackQuery):
            await target.answer("Не удалось получить статус", show_alert=True)
    finally:
        if ctx:
            ctx.pop()


async def show_events(message, user_id=None, edit=False):
    ctx = None
    try:
        ctx = get_db_session()
        tg_id = user_id or message.from_user.id
        student = Student.query.filter_by(tg_id=tg_id).first()
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
            for day in quota.days:
                if day.date.date() >= datetime.utcnow().date() and day.available_places() > 0:
                    builder.button(
                        text=f"📅 {day.date.strftime('%d.%m')} · мест {day.available_places()}",
                        callback_data=f"join_day_{quota.id}_{day.date.strftime('%Y-%m-%d')}"
                    )
            builder.button(text="‹ Назад", callback_data="menu_home")
            builder.adjust(1)
            details = [f"📌 <b>{html.escape(quota.event_title)}</b>", f"📍 {html.escape(quota.location or 'Место уточняется')}"]
            if quota.time_range:
                details.append(f"🕒 {html.escape(quota.time_range)}")
            if quota.event_description:
                details.append(f"\n{html.escape(quota.event_description)}")
            await message.answer("\n".join(details), reply_markup=builder.as_markup(), parse_mode="HTML")
    except Exception:
        logger.exception("Events render failed")
        await message.answer("⚠️ Не удалось загрузить мероприятия. Попробуйте ещё раз.")
    finally:
        if ctx:
            ctx.pop()


@router.message(CommandStart())
async def cmd_start(message: types.Message):
    await show_home(message, greeting=True)


@router.callback_query(F.data == "noop")
async def noop(callback: types.CallbackQuery):
    await callback.answer("Все доступные направления уже выбраны")


@router.callback_query(F.data == "menu_home")
async def menu_home(callback: types.CallbackQuery):
    await callback.answer()
    ctx = None
    try:
        ctx = get_db_session()
        student = Student.query.filter_by(tg_id=callback.from_user.id).first()
        if not student:
            await callback.message.edit_text(
                "🎓 <b>University Control</b>\n\nСоздайте профиль, чтобы начать работу.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🚀  Начать регистрацию", callback_data="menu_apply")],
                    [InlineKeyboardButton(text="❓  Помощь", callback_data="menu_help")],
                ]),
                parse_mode="HTML",
            )
            return
        await callback.message.edit_text(
            f"🎛 <b>Главное меню</b>\n\n👋 {html.escape(student.full_name)}\nВыберите нужный раздел.",
            reply_markup=home_inline(is_any_leader(callback.from_user.id), registered=True),
            parse_mode="HTML"
        )
    finally:
        if ctx:
            ctx.pop()


@router.callback_query(F.data == "menu_apply")
async def menu_apply(callback: types.CallbackQuery):
    from handlers.registration import start_registration_flow

    ctx = None
    try:
        ctx = get_db_session()
        student = Student.query.filter_by(tg_id=callback.from_user.id).first()
        await callback.answer()
        if not student:
            await start_registration_flow(callback.message, callback.from_user.id, edit=True)
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
        student = Student.query.filter_by(tg_id=callback.from_user.id).first()
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
        student = Student.query.filter_by(tg_id=callback.from_user.id).first()
        if not student:
            await callback.answer("Профиль ещё не создан", show_alert=True)
            return
        await callback.answer()
        await callback.message.edit_text(
            "👤 <b>Профиль</b>\n\n"
            f"<b>{html.escape(student.full_name)}</b>\n"
            f"🎓 Группа: {html.escape(student.group or '—')}\n"
            f"📞 Телефон: {html.escape(student.phone or '—')}\n"
            f"✉️ Email: {html.escape(student.email or '—')}",
            reply_markup=profile_inline(),
            parse_mode="HTML",
        )
    finally:
        if ctx:
            ctx.pop()


@router.callback_query(F.data == "menu_help")
async def menu_help(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        "❓ <b>Как это работает</b>\n\n"
        "1. Создайте профиль.\n"
        "2. Первая заявка доступна только в Студсовет.\n"
        "3. После первой заявки можно выбирать дополнительные направления.\n"
        "4. В «Общем статусе» отображается сводка по всем заявкам без отдельного списка статусов по каждому направлению.\n"
        "5. В «Мероприятиях» доступны события только для активных направлений.",
        reply_markup=help_inline(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu_leadership")
async def menu_leadership(callback: types.CallbackQuery):
    if not is_any_leader(callback.from_user.id):
        await callback.answer("Раздел доступен руководителям", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(
        "👥 <b>Управление студентами</b>\n\nВыберите операцию для вашего направления.",
        reply_markup=leader_inline(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("dir_"))
async def choose_direction(callback: types.CallbackQuery):
    dir_id = int(callback.data.split("_")[1])
    ctx = None
    try:
        ctx = get_db_session()
        student = Student.query.filter_by(tg_id=callback.from_user.id).first()
        direction = Direction.query.get(dir_id)
        if not student or not direction:
            await callback.answer("⚠️ Данные не найдены", show_alert=True)
            return

        allowed = {d.id for d in available_application_directions(student)}
        if dir_id not in allowed:
            await callback.answer("Это направление недоступно для текущей заявки", show_alert=True)
            return

        existing_link = db.session.execute(student_directions.select().where(
            (student_directions.c.student_id == student.id) &
            (student_directions.c.direction_id == dir_id)
        )).fetchone()
        if existing_link:
            await callback.answer("Это направление уже выбрано", show_alert=True)
            await show_my_status(callback, student)
            return

        db.session.execute(student_directions.insert().values(
            student_id=student.id,
            direction_id=dir_id,
            status=DirectionStatus.PENDING.value,
            extra_data=json.dumps({})
        ))
        db.session.commit()

        await callback.answer("Заявка отправлена")
        await callback.message.edit_text(
            f"✅ <b>Заявка принята в обработку</b>\n\n"
            f"Направление: <b>{html.escape(direction.name)}</b>\n"
            "Общий статус: ⏳ Заявка рассматривается.\n\n"
            "Открывайте «Общий статус», чтобы видеть актуальную сводку.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📊  Общий статус", callback_data="menu_status")],
                [InlineKeyboardButton(text="＋  Ещё направление", callback_data="menu_apply")],
                [InlineKeyboardButton(text="‹  В меню", callback_data="menu_home")],
            ]),
            parse_mode="HTML",
        )
    except Exception:
        db.session.rollback()
        logger.exception("Direction selection failed")
        await callback.answer("⚠️ Не удалось отправить заявку", show_alert=True)
    finally:
        if ctx:
            ctx.pop()


@router.callback_query(F.data.startswith("remove_dir_"))
async def remove_direction(callback: types.CallbackQuery):
    dir_id = int(callback.data.split("remove_dir_")[1])
    ctx = None
    try:
        ctx = get_db_session()
        student = Student.query.filter_by(tg_id=callback.from_user.id).first()
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
        if link.status not in {DirectionStatus.PENDING.value, DirectionStatus.REJECTED.value}:
            await callback.answer("Одобренную или активную заявку отозвать нельзя", show_alert=True)
            return
        db.session.execute(student_directions.delete().where(
            (student_directions.c.student_id == student.id) &
            (student_directions.c.direction_id == dir_id)
        ))
        db.session.commit()
        await callback.answer("Заявка отозвана")
        await show_my_status(callback, student)
    except Exception:
        logger.exception("Direction removal failed")
        await callback.answer("⚠️ Не удалось отозвать заявку", show_alert=True)
    finally:
        if ctx:
            ctx.pop()


@router.callback_query(F.data.startswith("leader_add"))
async def leader_add(callback: types.CallbackQuery):
    from handlers.registration import start_add_student
    if not is_any_leader(callback.from_user.id):
        await callback.answer("Раздел доступен руководителям", show_alert=True)
        return
    await callback.answer()
    await start_add_student(callback.message, callback.from_user.id)


@router.callback_query(F.data.startswith("leader_remove"))
async def leader_remove(callback: types.CallbackQuery):
    from handlers.registration import start_remove_student
    if not is_any_leader(callback.from_user.id):
        await callback.answer("Раздел доступен руководителям", show_alert=True)
        return
    await callback.answer()
    await start_remove_student(callback.message, callback.from_user.id)


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
        student = Student.query.filter_by(tg_id=callback.from_user.id).first()
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
        db.session.commit()

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
