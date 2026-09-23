import asyncio, logging, json
from datetime import datetime
from aiogram import Bot, Dispatcher, Router, types, F
from aiogram.filters import CommandStart
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from config import settings
from database import db, Student, StudentStatus, Direction, EventQuota, EventDay, DayParticipation, DirectionQuestion, student_directions

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = Router()
bot_instance = None
app_instance = None

REG_STATE_NAME = "reg_name"
REG_STATE_GROUP = "reg_group"
REG_STATE_PHONE = "reg_phone"
REG_STATE_DIR_SELECT = "reg_dir_select"
REG_STATE_EXTRA_Q = "reg_extra_q"

registration_data = {}

def get_student_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📝 Подать заявку")],
        [KeyboardButton(text="ℹ️ Мой статус")]
    ], resize_keyboard=True)

def get_db_session():
    if not app_instance: raise RuntimeError("Flask app не инициализирован!")
    ctx = app_instance.app_context(); ctx.push(); return ctx

async def show_my_status(message_or_callback, student):
    directions_text = ""
    remove_buttons = []
    if student.directions:
        for d in student.directions:
            directions_text += f"{d.icon} {d.name}\n"
            # ✅ СКРЫВАЕМ КНОПКУ УДАЛЕНИЯ ДЛЯ СТУДСОВЕТА В ИНТЕРФЕЙСЕ
            if d.code != "STUDCOUNCIL":
                remove_buttons.append([InlineKeyboardButton(text=f"❌ Удалить {d.name}", callback_data=f"remove_dir_{d.id}")])
    else:
        directions_text = "⚪ Не выбраны"

    status_map = {'pending': "⏳ Ожидает", 'approved': "✅ Одобрено", 'active': "🚀 Активен", 'rejected': "❌ Отклонено"}
    keyboard = InlineKeyboardMarkup(inline_keyboard=remove_buttons + [[InlineKeyboardButton(text="➕ Добавить направление", callback_data="add_new_direction")]])
    text = f"👤 <b>{student.full_name}</b>\n ID: {student.id}\n📊 {status_map.get(student.status)}\n\n<b>Направления:</b>\n{directions_text}"
    
    try:
        if isinstance(message_or_callback, types.CallbackQuery): await message_or_callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        else: await message_or_callback.answer(text, reply_markup=keyboard, parse_mode="HTML")
    except: pass

@router.message(CommandStart())
async def cmd_start(message: types.Message):
    registration_data.pop(message.from_user.id, None)
    await message.answer("🎓 Технологический университет\n\nВыберите действие:", reply_markup=get_student_keyboard())

@router.message(lambda m: m.text and "Подать заявку" in m.text)
async def start_application(message: types.Message):
    ctx = None
    try:
        ctx = get_db_session()
        existing = Student.query.filter_by(tg_id=message.from_user.id).first()
        if existing and existing.status != StudentStatus.REJECTED.value:
            await show_my_status(message, existing); return
        if existing and existing.status == StudentStatus.REJECTED.value:
             await message.answer("⚠️ Прошлая заявка отклонена. Заполним заново.")
             db.session.execute(student_directions.delete().where(student_directions.c.student_id == existing.id)); db.session.commit()

        registration_data[message.from_user.id] = {"step": REG_STATE_NAME}
        await message.answer("<b>Регистрация</b>\n\nОтправьте ваше <b>ФИО</b>:", parse_mode="HTML")
    except Exception as e:
        logger.error(f"Ошибка start_application: {e}")
        await message.answer(f"⚠️ Ошибка: {str(e)[:100]}")
    finally:
        if ctx: ctx.pop()

@router.message(lambda m: m.text and m.from_user.id in registration_data)
async def handle_registration(message: types.Message):
    tg_id = message.from_user.id
    step = registration_data[tg_id].get("step")
    ctx = None
    
    try:
        if step == REG_STATE_NAME:
            if len(message.text.split()) < 2: await message.answer("⚠️ Введите Фамилию и Имя."); return
            registration_data[tg_id]["full_name"] = message.text.strip()
            registration_data[tg_id]["step"] = REG_STATE_GROUP
            await message.answer("✅ ФИО принято.\n\nВаша <b>учебная группа</b>:", parse_mode="HTML"); return

        elif step == REG_STATE_GROUP:
            registration_data[tg_id]["group"] = message.text.strip()
            registration_data[tg_id]["step"] = REG_STATE_PHONE
            await message.answer("✅ Группа принята.\n\nВаш <b>номер телефона</b>:", parse_mode="HTML"); return

        elif step == REG_STATE_PHONE:
            if not any(c.isdigit() for c in message.text): await message.answer("⚠️ Номер должен содержать цифры."); return
            
            ctx = get_db_session()
            data = registration_data[tg_id]
            existing = Student.query.filter_by(tg_id=tg_id).first()
            
            if existing:
                student = existing
                student.full_name = data["full_name"]; student.group = data["group"]
                student.phone = message.text.strip(); student.status = StudentStatus.PENDING.value
            else:
                student = Student(tg_id=tg_id, full_name=data["full_name"], group=data["group"], 
                                  phone=message.text.strip(), status=StudentStatus.PENDING.value)
                db.session.add(student)
            db.session.commit()
            
            dirs = Direction.query.filter_by(code='STUDCOUNCIL').all() 
            
            if not dirs:
                 await message.answer("⚠️ Ошибка конфигурации: направление Студсовет не найдено в базе.")
                 return

            buttons = [[InlineKeyboardButton(text=f"{d.icon} {d.name}", callback_data=f"dir_{d.id}")] for d in dirs]
            kb = InlineKeyboardMarkup(inline_keyboard=buttons)
            
            await message.answer(f"✅ Заявка #{student.id} создана!\n\nВыберите направление:", reply_markup=kb, parse_mode="HTML")
            registration_data[tg_id]["step"] = REG_STATE_DIR_SELECT
            return

        elif step == REG_STATE_EXTRA_Q:
            q_index = registration_data[tg_id].get("q_index", 0)
            questions = registration_data[tg_id].get("questions", [])
            answers = registration_data[tg_id].get("answers", {})
            
            if q_index < len(questions):
                q_text = questions[q_index]["text"]
                answers[q_text] = message.text.strip()
                registration_data[tg_id]["answers"] = answers
                q_index += 1
                registration_data[tg_id]["q_index"] = q_index
                
                if q_index < len(questions):
                    await message.answer(f"📝 {questions[q_index]['text']}")
                else:
                    registration_data[tg_id]["step"] = REG_STATE_DIR_SELECT
                    await message.answer("✅ Спасибо! Выберите следующее направление или нажмите 'Готово'.", 
                                         reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Готово", callback_data="reg_finish")]]))
            return

    except Exception as e:
        logger.error(f"Ошибка регистрации: {e}", exc_info=True)
        await message.answer(f"⚠️ Ошибка: {str(e)[:100]}")
    finally:
        if ctx: ctx.pop()

@router.callback_query(lambda c: c.data.startswith("dir_"))
async def choose_direction(callback: types.CallbackQuery):
    dir_id = int(callback.data.split("_")[1])
    ctx = None
    try:
        ctx = get_db_session()
        tg_id = callback.from_user.id
        student = Student.query.filter_by(tg_id=tg_id).first()
        direction = Direction.query.get(dir_id)
        
        if not student or not direction: return
        
        existing_link = db.session.execute(student_directions.select().where(
            (student_directions.c.student_id == student.id) & (student_directions.c.direction_id == dir_id)
        )).fetchone()
        if existing_link:
            await callback.answer("ℹ️ Уже выбрано", show_alert=True); return
        
        questions = [{"id": q.id, "text": q.question_text} for q in direction.questions]
        
        if questions:
            registration_data[tg_id]["step"] = REG_STATE_EXTRA_Q
            registration_data[tg_id]["target_dir_id"] = dir_id
            registration_data[tg_id]["questions"] = questions
            registration_data[tg_id]["q_index"] = 0
            registration_data[tg_id]["answers"] = {}
            
            await callback.message.edit_text(f"📌 <b>{direction.name}</b>\n\nОтветьте на вопросы:", parse_mode="HTML")
            await callback.message.answer(f" {questions[0]['text']}")
            await callback.answer()
        else:
            db.session.execute(student_directions.insert().values(student_id=student.id, direction_id=dir_id, extra_data=json.dumps({})))
            db.session.commit()
            await callback.answer(f"✅ {direction.name} добавлено")
            await show_my_status(callback, student)
    except Exception as e:
        logger.error(f"Ошибка выбора направления: {e}")
    finally:
        if ctx: ctx.pop()

@router.callback_query(lambda c: c.data == "reg_finish")
async def finish_registration(callback: types.CallbackQuery):
    ctx = None
    try:
        ctx = get_db_session()
        tg_id = callback.from_user.id
        student = Student.query.filter_by(tg_id=tg_id).first()
        
        if registration_data.get(tg_id, {}).get("step") == REG_STATE_EXTRA_Q:
            dir_id = registration_data[tg_id]["target_dir_id"]
            answers = registration_data[tg_id]["answers"]
            db.session.execute(student_directions.insert().values(
                student_id=student.id, direction_id=dir_id, extra_data=json.dumps(answers)
            ))
            db.session.commit()
        
        registration_data.pop(tg_id, None)
        await show_my_status(callback, student)
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка завершения: {e}")
    finally:
        if ctx: ctx.pop()

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
        await message.answer(f"⚠️ Техническая ошибка: {str(e)[:100]}")
    finally:
        if ctx: ctx.pop()

@router.callback_query(lambda c: c.data == "add_new_direction")
async def add_new_direction(callback: types.CallbackQuery):
    ctx = None
    try:
        ctx = get_db_session()
        tg_id = callback.from_user.id
        student = Student.query.filter_by(tg_id=tg_id).first()
        
        current_ids = [d.id for d in student.directions]
        available = Direction.query.filter(~Direction.id.in_(current_ids)).order_by(Direction.name).all()
        
        if not available:
            await callback.answer("Все направления уже выбраны!", show_alert=True); return
            
        buttons = [[InlineKeyboardButton(text=f"{d.icon} {d.name}", callback_data=f"dir_{d.id}")] for d in available]
        buttons.append([InlineKeyboardButton(text="🔙 Назад к статусу", callback_data="back_to_status")])
        
        await callback.message.edit_text("Выберите новое направление:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    except Exception as e:
        logger.error(f"Ошибка добавления направления: {e}")
    finally:
        if ctx: ctx.pop()

@router.callback_query(lambda c: c.data == "back_to_status")
async def back_to_status(callback: types.CallbackQuery):
    ctx = None
    try:
        ctx = get_db_session()
        student = Student.query.filter_by(tg_id=callback.from_user.id).first()
        if student: await show_my_status(callback, student)
    except Exception as e:
        logger.error(f"Ошибка возврата к статусу: {e}")
    finally:
        if ctx: ctx.pop()

# ✅ ЗАЩИЩЕННОЕ УДАЛЕНИЕ НАПРАВЛЕНИЯ
@router.callback_query(lambda c: c.data.startswith("remove_dir_"))
async def remove_direction(callback: types.CallbackQuery):
    dir_id = int(callback.data.split("remove_dir_")[1])
    ctx = None
    try:
        ctx = get_db_session()
        student = Student.query.filter_by(tg_id=callback.from_user.id).first()
        
        # ПРОВЕРКА: ЗАПРЕЩАЕМ УДАЛЕНИЕ СТУДСОВЕТА
        direction_to_remove = Direction.query.get(dir_id)
        if direction_to_remove and direction_to_remove.code == "STUDCOUNCIL":
            await callback.answer("️ Направление Студсовет нельзя удалить", show_alert=True)
            return
            
        db.session.execute(student_directions.delete().where(
            (student_directions.c.student_id==student.id) & 
            (student_directions.c.direction_id==dir_id)
        ))
        db.session.commit()
        await callback.answer("Удалено")
        await show_my_status(callback, student)
    except Exception as e:
        logger.error(f"Ошибка удаления: {e}")
    finally:
        if ctx: ctx.pop()

# ✅ ЗАПИСЬ НА КОНКРЕТНУЮ ДАТУ ИЗ СООБЩЕНИЯ
@router.callback_query(lambda c: c.data.startswith("join_day_"))
async def join_specific_day(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    quota_id = int(parts[2])
    target_date_str = parts[3] 
    
    ctx = None
    try:
        ctx = get_db_session()
        student = Student.query.filter_by(tg_id=callback.from_user.id).first()
        quota = EventQuota.query.get(quota_id)
        
        if not student or not quota:
            await callback.answer("⚠️ Мероприятие не найдено", show_alert=True); return
            
        target_date = datetime.strptime(target_date_str, "%Y-%m-%d")
        target_day = None
        for day in quota.days:
            if day.date.date() == target_date.date():
                target_day = day
                break
                
        if not target_day:
            await callback.answer("️ Эта дата больше не доступна", show_alert=True); return
            
        if target_day.available_places() <= 0:
            await callback.answer("🚫 Места на эту дату закончились!", show_alert=True); return
            
        existing = DayParticipation.query.filter_by(student_id=student.id, day_id=target_day.id).first()
        if existing:
            await callback.answer("ℹ️ Вы уже записаны на этот день", show_alert=True); return
            
        participation = DayParticipation(student_id=student.id, day_id=target_day.id)
        db.session.add(participation); db.session.commit()
        
        await callback.message.edit_text(
            f"✅ <b>Вы успешно записаны!</b>\n\n"
            f"📌 {quota.event_title}\n"
            f" {target_day.date.strftime('%d.%m.%Y %H:%M')}\n"
            f"📍 {quota.location or 'Место уточняется'}\n\n"
            f"Ждем вас!",
            parse_mode="HTML"
        )
        await callback.answer("Запись подтверждена!")
        
    except Exception as e:
        logger.error(f"Ошибка записи на дату: {e}", exc_info=True)
        await callback.answer("️ Произошла ошибка при записи", show_alert=True)
    finally:
        if ctx: ctx.pop()

async def run_bot(app):
    global bot_instance, app_instance
    app_instance = app
    with app.app_context():
        logger.info(f"БД подключена. Студентов: {Student.query.count()}")
    bot_instance = Bot(token=settings.BOT_TOKEN)
    dp = Dispatcher(); dp.include_router(router)
    print("🤖 Telegram Bot запущен...")
    await dp.start_polling(bot_instance)