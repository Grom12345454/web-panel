import html
import json
import logging
import time
from datetime import datetime

from aiogram import Router, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from database import db, Student, Direction, student_directions, StudentLeadership, DirectionStatus
from config import RegState, AddState

logger = logging.getLogger(__name__)
router = Router()
registration_data = {}
adding_data = {}
removing_data = {}


def get_db_session():
    from bot import app_instance
    if not app_instance:
        raise RuntimeError("Flask app не инициализирован")
    ctx = app_instance.app_context()
    ctx.push()
    return ctx


def cancel_markup():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✕ Отменить", callback_data="flow_cancel")
    ]])


def check_leadership_rights(tg_id):
    ctx = None
    try:
        ctx = get_db_session()
        student = Student.query.filter_by(tg_id=tg_id).first()
        if not student:
            return False, None
        leadership = StudentLeadership.query.filter_by(student_id=student.id).first()
        if leadership:
            return True, Direction.query.get(leadership.direction_id)
        return False, None
    except Exception:
        logger.exception("Leadership rights check failed")
        return False, None
    finally:
        if ctx:
            ctx.pop()


async def start_registration_flow(message: types.Message, tg_id=None, edit=False):
    ctx = None
    try:
        ctx = get_db_session()
        tg_id = tg_id or message.from_user.id
        existing = Student.query.filter_by(tg_id=tg_id).first()
        if existing:
            await message.answer(
                "ℹ️ <b>Профиль уже создан</b>\n\n"
                "Используйте «ℹ️ Мой статус», чтобы выбрать новое направление.",
                parse_mode="HTML"
            )
            return
        registration_data[tg_id] = {"step": RegState.NAME}
        registration_text = (
            "📝 <b>Регистрация участника</b>\n\n"
            "Шаг 1 из 3 · Укажите ваше <b>ФИО</b>.\n"
            "Например: <i>Иванов Иван Иванович</i>"
        )
        if edit:
            await message.edit_text(registration_text, reply_markup=cancel_markup(), parse_mode="HTML")
        else:
            await message.answer(registration_text, reply_markup=cancel_markup(), parse_mode="HTML")
    except Exception:
        logger.exception("Registration start failed")
        await message.answer("⚠️ Не удалось начать регистрацию. Попробуйте ещё раз.")
    finally:
        if ctx:
            ctx.pop()


@router.message(F.text == "📝 Подать заявку")
async def start_registration(message: types.Message):
    # Повторная регистрация не создаёт новый профиль; пользователь может добавить другое направление.
    ctx = None
    try:
        ctx = get_db_session()
        existing = Student.query.filter_by(tg_id=message.from_user.id).first()
    finally:
        if ctx:
            ctx.pop()
    if existing:
        await message.answer(
            "ℹ️ <b>Профиль уже создан.</b>\n\nОткройте карточку «Подать заявку» в главном меню.",
            parse_mode="HTML"
        )
        return
    await start_registration_flow(message)


@router.callback_query(F.data == "flow_cancel")
async def cancel_flow(callback: types.CallbackQuery):
    tg_id = callback.from_user.id
    registration_data.pop(tg_id, None)
    adding_data.pop(tg_id, None)
    removing_data.pop(tg_id, None)
    await callback.answer("Действие отменено")
    from handlers.menu import home_inline, is_any_leader
    ctx = None
    try:
        ctx = get_db_session()
        student = Student.query.filter_by(tg_id=tg_id).first()
        registered = student is not None
        keyboard = home_inline(is_leader=is_any_leader(tg_id) if registered else False, registered=registered)
        await callback.message.edit_text(
            "↩️ <b>Сценарий отменён</b>\n\nВернулись в главное меню.",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
    finally:
        if ctx:
            ctx.pop()


@router.message(F.text == "↩️ Отмена")
async def cancel_command(message: types.Message):
    registration_data.pop(message.from_user.id, None)
    adding_data.pop(message.from_user.id, None)
    removing_data.pop(message.from_user.id, None)
    await message.answer("↩️ Текущий сценарий отменён.", parse_mode="HTML")


@router.message(lambda m: m.from_user.id in registration_data or m.from_user.id in adding_data or m.from_user.id in removing_data)
async def handle_input(message: types.Message):
    tg_id = message.from_user.id
    text = (message.text or "").strip()
    ctx = None
    try:
        if tg_id in registration_data:
            state = registration_data[tg_id]
            step = state.get("step")
            if step == RegState.NAME:
                if len(text.split()) < 2:
                    await message.answer("⚠️ Укажите минимум имя и фамилию.", parse_mode="HTML")
                    return
                state["full_name"] = text
                state["step"] = RegState.GROUP
                await message.answer("✅ ФИО сохранено.\n\nШаг 2 из 3 · Укажите <b>учебную группу</b>.", reply_markup=cancel_markup(), parse_mode="HTML")
                return
            if step == RegState.GROUP:
                if len(text) < 2:
                    await message.answer("⚠️ Укажите корректную учебную группу.")
                    return
                state["group"] = text
                state["step"] = RegState.PHONE
                await message.answer("✅ Группа сохранена.\n\nШаг 3 из 3 · Отправьте <b>номер телефона</b>.", reply_markup=cancel_markup(), parse_mode="HTML")
                return
            if step == RegState.PHONE:
                if sum(ch.isdigit() for ch in text) < 5:
                    await message.answer("⚠️ В номере должно быть не меньше 5 цифр.")
                    return
                ctx = get_db_session()
                data = registration_data[tg_id]
                student = Student(tg_id=tg_id, full_name=data["full_name"], group=data["group"], phone=text)
                db.session.add(student)
                db.session.commit()
                student_council = Direction.query.filter_by(code="STUDCOUNCIL").first()
                buttons = []
                if student_council:
                    buttons.append([InlineKeyboardButton(
                        text=f"{student_council.icon or '✦'}  {student_council.name}",
                        callback_data=f"dir_{student_council.id}",
                    )])
                buttons.append([InlineKeyboardButton(text="‹  В главное меню", callback_data="menu_home")])
                await message.answer(
                    f"✅ <b>Профиль создан · #{student.id}</b>\n\n"
                    "Первая заявка доступна только в <b>Студсовет</b>.\n\n"
                    "После подачи первой заявки вы сможете открыть дополнительные направления.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML"
                )
                registration_data.pop(tg_id, None)
                logger.info("Registered student #%s (%s)", student.id, student.full_name)
                return

        if tg_id in adding_data:
            state = adding_data[tg_id]
            step = state.get("step")
            if step == AddState.NAME:
                if len(text.split()) < 2:
                    await message.answer("⚠️ Укажите Фамилию и Имя.")
                    return
                state["full_name"] = text
                state["step"] = AddState.GROUP
                await message.answer("✅ ФИО принято.\n\nУкажите <b>группу</b>.", reply_markup=cancel_markup(), parse_mode="HTML")
                return
            if step == AddState.GROUP:
                state["group"] = text
                state["step"] = AddState.PHONE
                await message.answer("✅ Группа принята.\n\nУкажите <b>телефон</b>.", reply_markup=cancel_markup(), parse_mode="HTML")
                return
            if step == AddState.PHONE:
                if sum(ch.isdigit() for ch in text) < 5:
                    await message.answer("⚠️ Введите корректный номер телефона.")
                    return
                ctx = get_db_session()
                data = adding_data[tg_id]
                direction_id = data["direction_id"]
                existing_student = Student.query.filter_by(full_name=data["full_name"], group=data["group"]).first()
                if existing_student:
                    is_in_dir = db.session.execute(student_directions.select().where(
                        (student_directions.c.student_id == existing_student.id) &
                        (student_directions.c.direction_id == direction_id)
                    )).fetchone()
                    if is_in_dir:
                        await message.answer("⚠️ Этот студент уже состоит в направлении.")
                        adding_data.pop(tg_id, None)
                        return
                    student = existing_student
                    student.phone = text
                else:
                    student = Student(tg_id=-time.time_ns(), full_name=data["full_name"], group=data["group"], phone=text)
                    db.session.add(student)
                    db.session.flush()

                db.session.execute(student_directions.insert().values(
                    student_id=student.id,
                    direction_id=direction_id,
                    status=DirectionStatus.ACTIVE.value,
                    extra_data=json.dumps({"added_by": tg_id, "date": datetime.utcnow().isoformat()})
                ))
                db.session.commit()
                await message.answer(
                    "✅ <b>Студент добавлен</b>\n\n"
                    f"👤 {html.escape(student.full_name)}\n"
                    f"🎓 {html.escape(student.group or '—')}\n"
                    f"📌 {html.escape(data['direction_name'])}\n"
                    "Статус: ✦ Активен",
                    parse_mode="HTML"
                )
                adding_data.pop(tg_id, None)
                return

        if tg_id in removing_data and removing_data[tg_id].get("step") == "remove_name":
            ctx = get_db_session()
            data = removing_data[tg_id]
            student = Student.query.filter_by(full_name=text).first()
            if not student:
                await message.answer("⚠️ Студент с таким ФИО не найден.")
                removing_data.pop(tg_id, None)
                return
            is_in_dir = db.session.execute(student_directions.select().where(
                (student_directions.c.student_id == student.id) &
                (student_directions.c.direction_id == data["direction_id"])
            )).fetchone()
            if not is_in_dir:
                await message.answer("⚠️ Студент не состоит в выбранном направлении.")
                removing_data.pop(tg_id, None)
                return
            db.session.execute(student_directions.delete().where(
                (student_directions.c.student_id == student.id) &
                (student_directions.c.direction_id == data["direction_id"])
            ))
            db.session.commit()
            await message.answer(
                f"✅ <b>Студент удалён из направления</b>\n\n👤 {html.escape(student.full_name)}\n🎓 {html.escape(student.group or '—')}",
                parse_mode="HTML"
            )
            removing_data.pop(tg_id, None)
    except Exception:
        if ctx:
            try:
                db.session.rollback()
            except Exception:
                pass
        logger.exception("Flow input failed")
        await message.answer("⚠️ Произошла техническая ошибка. Попробуйте повторить действие.")
    finally:
        if ctx:
            ctx.pop()


@router.message(F.text == "➕ Добавить студента")
async def start_add_student(message: types.Message, tg_id=None):
    ctx = None
    try:
        ctx = get_db_session()
        tg_id = tg_id or message.from_user.id
        has_rights, direction = check_leadership_rights(tg_id)
        if not has_rights:
            await message.answer("⚠️ Доступ доступен только назначенным руководителям направления.")
            return
        adding_data[tg_id] = {"step": AddState.NAME, "direction_id": direction.id, "direction_name": direction.name}
        await message.answer(
            f"➕ <b>Добавление в «{html.escape(direction.name)}»</b>\n\n"
            "Шаг 1 из 3 · Отправьте <b>ФИО</b> студента.",
            reply_markup=cancel_markup(), parse_mode="HTML"
        )
    except Exception:
        logger.exception("Add student start failed")
        await message.answer("⚠️ Не удалось начать добавление студента.")
    finally:
        if ctx:
            ctx.pop()


@router.message(F.text == "🗑️ Удалить студента")
async def start_remove_student(message: types.Message, tg_id=None):
    ctx = None
    try:
        ctx = get_db_session()
        tg_id = tg_id or message.from_user.id
        has_rights, direction = check_leadership_rights(tg_id)
        if not has_rights:
            await message.answer("⚠️ У вас нет прав для этого действия.")
            return
        removing_data[tg_id] = {"step": "remove_name", "direction_id": direction.id}
        await message.answer(
            f"🗑 <b>Удаление из «{html.escape(direction.name)}»</b>\n\n"
            "Отправьте точное <b>ФИО</b> студента.",
            reply_markup=cancel_markup(), parse_mode="HTML"
        )
    except Exception:
        logger.exception("Remove student start failed")
        await message.answer("⚠️ Не удалось начать удаление студента.")
    finally:
        if ctx:
            ctx.pop()
