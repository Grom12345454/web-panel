import asyncio
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, Router, types, F
from aiogram.filters import CommandStart
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from config import settings
from database import db, Student, StudentStatus, Direction, EventQuota, EventDay, DayParticipation, student_directions

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = Router()
bot_instance = None
app_instance = None  # Глобальное приложение для доступа к БД

REG_STATE_NAME = "reg_name"
REG_STATE_GROUP = "reg_group"
REG_STATE_PHONE = "reg_phone"
registration_data = {}

def get_student_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📝 Подать заявку")],
        [KeyboardButton(text=" Мероприятия")],
        [KeyboardButton(text="ℹ️ Мой статус")]
    ], resize_keyboard=True)

# Безопасный хелпер для активации контекста Flask в потоке бота
def get_db_session():
    if not app_instance:
        raise RuntimeError("Flask app не инициализирован!")
    ctx = app_instance.app_context()
    ctx.push()
    return ctx

async def show_my_status(message_or_callback, student):
    directions_text = ""
    remove_buttons = []
    
    if student.directions:
        dirs_list = []
        for d in student.directions:
            dirs_list.append(f"{d.icon} {d.name}")
            remove_buttons.append([InlineKeyboardButton(
                text=f"❌ Удалить {d.name}", 
                callback_data=f"remove_dir_{d.id}"
            )])
        directions_text = "\n".join(dirs_list)
    else:
        directions_text = "⚪ Направления не выбраны"

    status_map = {
        'pending': "⏳ Ожидает проверки",
        'approved': "✅ Одобрено (ждет отряда)",
        'active': "🚀 Активен",
        'rejected': "❌ Отклонено"
    }
    status_str = status_map.get(student.status, student.status)

    add_btn = [InlineKeyboardButton(text="➕ Добавить направление", callback_data="add_new_direction")]
    keyboard = InlineKeyboardMarkup(inline_keyboard=remove_buttons + [add_btn])

    text = (
        f"👤 <b>{student.full_name}</b>\n"
        f"🆔 ID заявки: {student.id}\n"
        f"📊 Статус: {status_str}\n\n"
        f"<b>Ваши направления:</b>\n{directions_text}\n\n"
        f"Управляйте направлениями ниже:"
    )

    try:
        if isinstance(message_or_callback, types.CallbackQuery):
            await message_or_callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await message_or_callback.answer(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Ошибка отображения статуса: {e}")

@router.message(CommandStart())
async def cmd_start(message: types.Message):
    registration_data.pop(message.from_user.id, None)
    await message.answer("🎓 Технологический университет\n\nВыберите действие:", reply_markup=get_student_keyboard())

# ✅ ИСПРАВЛЕННЫЙ ФИЛЬТР: ищем подстроку вместо точного совпадения
@router.message(lambda m: m.text and "Подать заявку" in m.text)
async def start_application(message: types.Message):
    logger.info(f"Получена заявка от пользователя {message.from_user.id}")
    ctx = None
    try:
        ctx = get_db_session()
        existing = Student.query.filter_by(tg_id=message.from_user.id).first()
        
        if existing and existing.status != StudentStatus.REJECTED.value:
            await show_my_status(message, existing)
            return
            
        if existing and existing.status == StudentStatus.REJECTED.value:
             await message.answer("⚠️ Ваша прошлая заявка была отклонена. Заполним данные заново.")
             stmt = student_directions.delete().where(student_directions.c.student_id == existing.id)
             db.session.execute(stmt)
             db.session.commit()

        registration_data[message.from_user.id] = {"step": REG_STATE_NAME}
        await message.answer("<b>Регистрация новой заявки</b>\n\nПожалуйста, отправьте ваше <b>ФИО</b> полностью:", parse_mode="HTML")
    except Exception as e:
        logger.error(f"Критическая ошибка в start_application: {e}", exc_info=True)
        await message.answer(f"⚠️ Произошла техническая ошибка: {str(e)[:100]}")
    finally:
        if ctx: ctx.pop()

@router.message(lambda m: m.text and m.from_user.id in registration_data)
async def handle_registration_steps(message: types.Message):
    tg_id = message.from_user.id
    current_step = registration_data[tg_id].get("step")
    ctx = None
    
    try:
        if current_step == REG_STATE_NAME:
            if len(message.text.split()) < 2:
                await message.answer("⚠️ Пожалуйста, введите Фамилию и Имя (минимум 2 слова).")
                return
                
            registration_data[tg_id]["full_name"] = message.text.strip()
            registration_data[tg_id]["step"] = REG_STATE_GROUP
            await message.answer("✅ ФИО принято.\n\nТеперь напишите вашу <b>учебную группу</b> (например: ИВТ-101):", parse_mode="HTML")
            return

        elif current_step == REG_STATE_GROUP:
            registration_data[tg_id]["group"] = message.text.strip()
            registration_data[tg_id]["step"] = REG_STATE_PHONE
            await message.answer("✅ Группа принята.\n\nОтправьте ваш <b>номер телефона</b> (для связи):", parse_mode="HTML")
            return

        elif current_step == REG_STATE_PHONE:
            phone = message.text.strip()
            if not any(c.isdigit() for c in phone):
                await message.answer("⚠️ Номер телефона должен содержать цифры. Попробуйте еще раз:")
                return

            ctx = get_db_session()
            data = registration_data[tg_id]
            
            existing = Student.query.filter_by(tg_id=tg_id).first()
            if existing:
                student = existing
                student.full_name = data["full_name"]
                student.group = data["group"]
                student.phone = phone
                student.status = StudentStatus.PENDING.value
            else:
                student = Student(
                    tg_id=tg_id, 
                    full_name=data["full_name"], 
                    group=data["group"],
                    phone=phone,
                    status=StudentStatus.PENDING.value
                )
                db.session.add(student)
                
            db.session.commit()
            
            dirs = Direction.query.all()
            buttons = [[InlineKeyboardButton(text=f"{d.icon} {d.name}", callback_data=f"dir_{d.id}")] for d in dirs]
            kb = InlineKeyboardMarkup(inline_keyboard=buttons)
            
            await message.answer(
                f"✅ Заявка #{student.id} успешно создана!\n"
                f"Статус: <b>Ожидает проверки</b>.\n\n"
                f"Теперь выберите ваши направления (можно несколько):", 
                reply_markup=kb,
                parse_mode="HTML"
            )
            
            del registration_data[tg_id]
    except Exception as e:
        logger.error(f"Ошибка регистрации: {e}", exc_info=True)
        await message.answer(f"️ Ошибка при сохранении: {str(e)[:100]}")
    finally:
        if ctx: ctx.pop()

# ✅ ИСПРАВЛЕННЫЙ ФИЛЬТР ДЛЯ СТАТУСА
@router.message(lambda m: m.text and "Мой статус" in m.text)
async def check_status(message: types.Message):
    ctx = None
    try:
        ctx = get_db_session()
        student = Student.query.filter_by(tg_id=message.from_user.id).first()
        if not student:
            await message.answer("⚠️ Вы еще не подавали заявку. Нажмите '📝 Подать заявку'.")
            return
        await show_my_status(message, student)
    except Exception as e:
        logger.error(f"Ошибка проверки статуса: {e}", exc_info=True)
    finally:
        if ctx: ctx.pop()

@router.callback_query(lambda c: c.data == "add_new_direction")
async def start_add_direction(callback: types.CallbackQuery):
    ctx = None
    try:
        ctx = get_db_session()
        student = Student.query.filter_by(tg_id=callback.from_user.id).first()
        if not student: return

        all_dirs = Direction.query.all()
        current_dir_ids = [d.id for d in student.directions]
        available_dirs = [d for d in all_dirs if d.id not in current_dir_ids]

        if not available_dirs:
            await callback.answer("У вас уже выбраны все доступные направления!", show_alert=True)
            return

        buttons = [[InlineKeyboardButton(text=f"{d.icon} {d.name}", callback_data=f"dir_{d.id}")] for d in available_dirs]
        buttons.append([InlineKeyboardButton(text="🔙 Назад к статусу", callback_data="back_to_status")])
        
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback.message.edit_text("Выберите направление для добавления:", reply_markup=kb)
    except Exception as e:
        logger.error(f"Ошибка добавления направления: {e}", exc_info=True)
    finally:
        if ctx: ctx.pop()

@router.callback_query(lambda c: c.data.startswith("dir_"))
async def choose_direction(callback: types.CallbackQuery):
    dir_id = int(callback.data.split("_")[1])
    ctx = None
    try:
        ctx = get_db_session()
        student = Student.query.filter_by(tg_id=callback.from_user.id).first()
        if not student: return
        
        direction = Direction.query.get(dir_id)
        if not direction: return
        
        existing = db.session.execute(
            student_directions.select().where(
                (student_directions.c.student_id == student.id) &
                (student_directions.c.direction_id == dir_id)
            )
        ).fetchone()
        
        if existing:
            await callback.answer(f"ℹ️ Это направление уже выбрано", show_alert=True)
            await show_my_status(callback, student)
            return
        
        stmt = student_directions.insert().values(student_id=student.id, direction_id=dir_id)
        db.session.execute(stmt)
        db.session.commit()
        
        await callback.answer(f"✅ Добавлено: {direction.name}")
        await show_my_status(callback, student)
    except Exception as e:
        logger.error(f"Ошибка выбора направления: {e}", exc_info=True)
    finally:
        if ctx: ctx.pop()

@router.callback_query(lambda c: c.data.startswith("remove_dir_"))
async def remove_direction(callback: types.CallbackQuery):
    dir_id = int(callback.data.split("remove_dir_")[1])
    ctx = None
    try:
        ctx = get_db_session()
        student = Student.query.filter_by(tg_id=callback.from_user.id).first()
        if not student: return

        stmt = student_directions.delete().where(
            (student_directions.c.student_id == student.id) &
            (student_directions.c.direction_id == dir_id)
        )
        db.session.execute(stmt)
        db.session.commit()
        
        direction = Direction.query.get(dir_id)
        await callback.answer(f"🗑️ Удалено: {direction.name}")
        await show_my_status(callback, student)
    except Exception as e:
        logger.error(f"Ошибка удаления направления: {e}", exc_info=True)
    finally:
        if ctx: ctx.pop()

@router.callback_query(lambda c: c.data == "back_to_status")
async def back_to_status(callback: types.CallbackQuery):
    ctx = None
    try:
        ctx = get_db_session()
        student = Student.query.filter_by(tg_id=callback.from_user.id).first()
        if student:
            await show_my_status(callback, student)
    except Exception as e:
        logger.error(f"Ошибка возврата к статусу: {e}", exc_info=True)
    finally:
        if ctx: ctx.pop()

# ✅ ИСПРАВЛЕННЫЙ ФИЛЬТР ДЛЯ МЕРОПРИЯТИЙ
@router.message(lambda m: m.text and "Мероприятия" in m.text)
async def show_events(message: types.Message):
    logger.info(f"Пользователь {message.from_user.id} нажал кнопку Мероприятия (текст: '{message.text}')")
    ctx = None
    try:
        ctx = get_db_session()
        student = Student.query.filter_by(tg_id=message.from_user.id).first()
        
        if not student:
            await message.answer("⚠️ Вы еще не зарегистрированы. Нажмите '📝 Подать заявку'.")
            return
            
        if not student.directions:
            await message.answer("⚠️ У вас не выбраны направления. Зайдите в 'ℹ️ Мой статус' и добавьте их.")
            return
        
        direction_ids = [d.id for d in student.directions]
        now = datetime.utcnow()
        
        quotas = EventQuota.query.all()
        
        active_quotas = []
        for q in quotas:
            quota_dir_ids = [d.id for d in q.directions]
            if not set(direction_ids).intersection(set(quota_dir_ids)):
                continue
                
            future_days = [d for d in q.days if d.date > now and d.available_places() > 0]
            if future_days:
                q._future_days = future_days
                active_quotas.append(q)
        
        # ✅ ИСПРАВЛЕНИЕ: явно указываем key=lambda d: d.date для min()
        active_quotas.sort(key=lambda x: min(x._future_days, key=lambda d: d.date))

        if not active_quotas:
            await message.answer(" Для ваших направлений пока нет запланированных мероприятий.")
            return
        
        buttons = []
        for q in active_quotas:
            first_day = min(q._future_days, key=lambda d: d.date)
            dir_icon = q.directions[0].icon if q.directions else ""
            
            btn_text = f"{dir_icon} {q.event_title} | {first_day.date.strftime('%d.%m')}"
            buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"eq_{q.id}")])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await message.answer("📅 Доступные мероприятия:", reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Критическая ошибка в show_events: {e}", exc_info=True)
        await message.answer(f"⚠️ Техническая ошибка при загрузке мероприятий: {str(e)[:150]}")
    finally:
        if ctx: ctx.pop()

@router.callback_query(lambda c: c.data.startswith("eq_"))
async def show_event_days(callback: types.CallbackQuery):
    quota_id = int(callback.data.split("_")[1])
    ctx = None
    try:
        ctx = get_db_session()
        quota = EventQuota.query.get(quota_id)
        student = Student.query.filter_by(tg_id=callback.from_user.id).first()
        
        if not quota or not student:
            await callback.answer(" Ошибка", show_alert=True)
            return

        now = datetime.utcnow()
        available_days = [d for d in quota.days if d.date > now and d.available_places() > 0]
        
        if not available_days:
            await callback.answer(" На доступные даты места закончились", show_alert=True)
            return

        buttons = []
        for day in available_days:
            btn_text = f"📅 {day.date.strftime('%d.%m')} ({day.available_places()} мест)"
            buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"reg_day_{day.id}")])
        
        buttons.append([InlineKeyboardButton(text="🔙 Назад к списку", callback_data="back_to_events")])
        
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback.message.edit_text(
            f"📌 <b>{quota.event_title}</b>\nВыберите день для записи:", 
            reply_markup=kb, parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка показа дней: {e}", exc_info=True)
    finally:
        if ctx: ctx.pop()

@router.callback_query(lambda c: c.data.startswith("reg_day_"))
async def register_for_day(callback: types.CallbackQuery):
    day_id = int(callback.data.split("_")[2])
    ctx = None
    try:
        ctx = get_db_session()
        student = Student.query.filter_by(tg_id=callback.from_user.id).first()
        day = EventDay.query.get(day_id)
        
        if not student or not day:
            await callback.answer("❌ Ошибка", show_alert=True)
            return
        
        existing = DayParticipation.query.filter_by(student_id=student.id, day_id=day_id).first()
        if existing:
            await callback.answer("ℹ️ Вы уже записаны на этот день", show_alert=True)
            return
        
        if day.available_places() <= 0:
            await callback.answer("🚫 Места на этот день закончились!", show_alert=True)
            return
        
        participation = DayParticipation(student_id=student.id, day_id=day_id)
        db.session.add(participation)
        db.session.commit()
        
        await callback.message.edit_text(
            f"✅ Вы успешно записаны!\n\n"
            f"📌 <b>{day.quota.event_title}</b>\n"
            f" Дата: {day.date.strftime('%d.%m.%Y')}\n"
            f" Место: {day.quota.location or 'Уточняется'}\n\n"
            f"Ждем вас!",
            parse_mode="HTML"
        )
        await callback.answer("Запись подтверждена!")
    except Exception as e:
        logger.error(f"Ошибка записи на день: {e}", exc_info=True)
    finally:
        if ctx: ctx.pop()

@router.callback_query(lambda c: c.data == "back_to_events")
async def back_to_events(callback: types.CallbackQuery):
    ctx = None
    try:
        fake_msg = types.Message(
            message_id=callback.message.message_id,
            date=datetime.now(),
            chat=callback.message.chat,
            from_user=callback.from_user,
            text="📅 Мероприятия"
        )
        ctx = get_db_session()
        await show_events(fake_msg)
    except Exception as e:
        logger.error(f"Ошибка возврата к мероприятиям: {e}", exc_info=True)
        await callback.answer("Произошла ошибка, попробуйте нажать 'Мероприятия' в меню")
    finally:
        if ctx: ctx.pop()
    await callback.answer()

def send_notification(tg_id: int, text: str):
    global bot_instance
    if bot_instance:
        try:
            asyncio.run(bot_instance.send_message(chat_id=tg_id, text=text))
        except Exception as e:
            print(f"Ошибка отправки уведомления {tg_id}: {e}")

async def run_bot(app):
    global bot_instance, app_instance
    app_instance = app
    
    with app.app_context():
        try:
            count = Student.query.count()
            logger.info(f"БД подключена успешно. Студентов в базе: {count}")
        except Exception as e:
            logger.error(f"Ошибка подключения к БД: {e}", exc_info=True)
    
    bot_instance = Bot(token=settings.BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    print("🤖 Telegram Bot запущен...")
    await dp.start_polling(bot_instance)