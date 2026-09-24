import logging
import json
from datetime import datetime
from aiogram import Router, types, F
from aiogram.filters import CommandStart
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from database import db, Student, StudentStatus, Direction, student_directions, User, UserRole, StudentLeadership, DirectionQuestion, EventQuota, EventDay, DayParticipation
from config import RegState

logger = logging.getLogger(__name__)

router = Router()
registration_data = {} 

def get_db_session():
    from bot import app_instance
    if not app_instance: raise RuntimeError("Flask app не инициализирован!")
    ctx = app_instance.app_context(); ctx.push(); return ctx

# ✅ КЛАВИАТУРА ДЛЯ ОБЫЧНОГО СТУДЕНТА
def get_student_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📝 Подать заявку")],
        [KeyboardButton(text="ℹ️ Мой статус")]
    ], resize_keyboard=True)

# ✅ КЛАВИАТУРА ТОЛЬКО ДЛЯ РУКОВОДИТЕЛЕЙ ИЗ /LEADERSHIP
def get_leader_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📝 Подать заявку")],
        [KeyboardButton(text="ℹ️ Мой статус")],
        [KeyboardButton(text="➕ Добавить студента")],
        [KeyboardButton(text="🗑️ Удалить студента")]
    ], resize_keyboard=True)

def is_studcouncil_leader(tg_id):
    """Проверяет, является ли пользователь руководителем, назначенным через /leadership"""
    try:
        ctx = get_db_session()
        student = Student.query.filter_by(tg_id=tg_id).first()
        if not student:
            return False
            
        # Строгий фильтр: ищем leadership только для направления STUDCOUNCIL
        leadership = StudentLeadership.query.filter_by(
            student_id=student.id
        ).first()
        
        return leadership is not None
    except Exception as e:
        logger.error(f"Error checking studcouncil leadership: {e}")
        return False
    finally:
        if 'ctx' in locals(): ctx.pop()

async def show_my_status(message_or_callback, student):
    directions_text = ""
    remove_buttons = []
    
    if student and student.directions:
        for d in student.directions:
            directions_text += f"{d.icon or ''} {d.name}\n"
            if d.code != "STUDCOUNCIL":
                remove_buttons.append([InlineKeyboardButton(text=f"❌ Удалить {d.name}", callback_data=f"remove_dir_{d.id}")])
    else:
        directions_text = "⚪ Не выбраны"

    status_map = {'pending': " Ожидает", 'approved': "✅ Одобрено", 'active': "🚀 Активен", 'rejected': "❌ Отклонено"}
    
    action_buttons = []
    # Кнопка добавления направления только для руководителей из /leadership
    if is_studcouncil_leader(student.tg_id):
        action_buttons.append([InlineKeyboardButton(text="➕ Добавить направление", callback_data="add_new_direction")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=remove_buttons + action_buttons)
    
    tg_info = f"🆔 ID: {student.id}"
    if student.tg_id and student.tg_id != 0:
        try:
            username = message_or_callback.from_user.username
            tg_info += f"\n📱 TG: @{username or 'N/A'}"
        except AttributeError:
            tg_info += "\n📱 TG: Привязан"
    else:
        tg_info += "\n️ TG-аккаунт не привязан"
        
    text = f"👤 <b>{student.full_name}</b>\n{tg_info}\n📊 {status_map.get(student.status)}\n\n<b>Направления:</b>\n{directions_text}"
    
    try:
        if isinstance(message_or_callback, types.CallbackQuery): 
            await message_or_callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        else: 
            await message_or_callback.answer(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Ошибка отображения статуса: {e}")
        try:
            if isinstance(message_or_callback, types.CallbackQuery):
                await message_or_callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
            else:
                await message_or_callback.answer(text, parse_mode="HTML")
        except: pass

@router.message(CommandStart())
async def cmd_start(message: types.Message):
    registration_data.pop(message.from_user.id, None)
    ctx = None
    
    try:
        ctx = get_db_session()
        tg_id = message.from_user.id
        
        # ✅ ДИНАМИЧЕСКАЯ ПРОВЕРКА ПРАВ ПРИ КАЖДОМ ЗАПУСКЕ
        if is_studcouncil_leader(tg_id):
            kb = get_leader_keyboard()
            logger.info(f"Leader from /leadership {tg_id} started bot")
        else:
            kb = get_student_keyboard()
            logger.info(f"Regular user {tg_id} started bot")
            
    except Exception as e:
        logger.error(f"Error in cmd_start: {e}", exc_info=True)
        kb = get_student_keyboard() # Fallback на обычную клавиатуру при ошибке
    finally:
        if ctx: 
            ctx.pop()

    await message.answer("🎓 Технологический университет\n\nВыберите действие:", reply_markup=kb)

# ✅ МГНОВЕННОЕ ДОБАВЛЕНИЕ НАПРАВЛЕНИЯ (БЕЗ ВОПРОСОВ)
@router.callback_query(F.data.startswith("dir_"))
async def choose_direction(callback: types.CallbackQuery):
    dir_id = int(callback.data.split("_")[1])
    ctx = None
    try:
        ctx = get_db_session()
        tg_id = callback.from_user.id
        student = Student.query.filter_by(tg_id=tg_id).first()
        direction = Direction.query.get(dir_id)
        
        if not student or not direction: 
            await callback.answer("⚠️ Ошибка данных", show_alert=True); return
        
        existing_link = db.session.execute(student_directions.select().where(
            (student_directions.c.student_id == student.id) & (student_directions.c.direction_id == dir_id)
        )).fetchone()
        
        if existing_link:
            await callback.answer("ℹ️ Это направление уже выбрано", show_alert=True)
            await show_my_status(callback, student)
            return
        
        # ✅ МГНОВЕННОЕ ДОБАВЛЕНИЕ БЕЗ ВОПРОСОВ
        db.session.execute(student_directions.insert().values(
            student_id=student.id, direction_id=dir_id, extra_data=json.dumps({})
        ))
        db.session.commit()
        await callback.answer(f"✅ {direction.name} добавлено")
        await show_my_status(callback, student)
            
    except Exception as e:
        logger.error(f"Ошибка выбора направления: {e}", exc_info=True)
        await callback.answer("⚠️ Произошла ошибка", show_alert=True)
    finally:
        if ctx: ctx.pop()

@router.message(F.text == "ℹ️ Мой статус")
async def check_status(message: types.Message):
    ctx = None
    try:
        ctx = get_db_session()
        tg_id = message.from_user.id
        student = Student.query.filter_by(tg_id=tg_id).first()
        
        if not student:
            await message.answer("⚠️ Вы еще не подавали заявку. Нажмите '📝 Подать заявку'.")
            return
        await show_my_status(message, student)
    except Exception as e:
        logger.error(f"Ошибка проверки статуса: {e}", exc_info=True)
        await message.answer(f"⚠️ Техническая ошибка: {str(e)[:100]}")
    finally:
        if ctx: ctx.pop()

@router.callback_query(F.data.startswith("join_day_"))
async def join_specific_day(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    if len(parts) != 4:
        await callback.answer("⚠️ Ошибка данных мероприятия", show_alert=True); return
        
    quota_id = int(parts[2])
    target_date_str = parts[3] 
    
    ctx = None
    try:
        ctx = get_db_session()
        student = Student.query.filter_by(tg_id=callback.from_user.id).first()
        quota = EventQuota.query.get(quota_id)
        
        if not student or not quota:
            await callback.answer("⚠️ Мероприятие или студент не найдены", show_alert=True); return
            
        if student.status != 'active':
            await callback.answer("⚠️ Для записи необходимо иметь активный статус", show_alert=True); return
            
        target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
        target_day = next((day for day in quota.days if day.date.date() == target_date), None)
                
        if not target_day:
            await callback.answer("️ Эта дата больше не доступна", show_alert=True); return
            
        current_count = len([p for p in target_day.participations if p.status != 'cancelled'])
        if current_count >= target_day.daily_places:
            await callback.answer("🚫 Места на эту дату закончились!", show_alert=True); return
            
        existing = DayParticipation.query.filter_by(student_id=student.id, day_id=target_day.id).first()
        if existing:
            await callback.answer("ℹ️ Вы уже записаны на этот день", show_alert=True); return
            
        participation = DayParticipation(student_id=student.id, day_id=target_day.id, status="registered")
        db.session.add(participation)
        db.session.commit()
        
        await callback.message.edit_text(
            f"✅ <b>Вы успешно записаны!</b>\n\n"
            f" {quota.event_title}\n"
            f"📅 {target_day.date.strftime('%d.%m.%Y %H:%M')}\n"
            f"📍 {quota.location or 'Место уточняется'}\n\n"
            f"Ждем вас!",
            parse_mode="HTML"
        )
        await callback.answer("Запись подтверждена!")
        logger.info(f"Student {student.id} joined event {quota_id} on {target_date_str}")
        
    except Exception as e:
        logger.error(f"Ошибка записи на дату: {e}", exc_info=True)
        await callback.answer("⚠️ Произошла ошибка при записи", show_alert=True)
    finally:
        if ctx: ctx.pop()

@router.callback_query(F.data.startswith("remove_dir_"))
async def remove_direction(callback: types.CallbackQuery):
    dir_id = int(callback.data.split("remove_dir_")[1])
    ctx = None
    try:
        ctx = get_db_session()
        student = Student.query.filter_by(tg_id=callback.from_user.id).first()
        direction_to_remove = Direction.query.get(dir_id)
        
        if direction_to_remove and direction_to_remove.code == "STUDCOUNCIL":
            await callback.answer("⚠️ Направление Студсовет нельзя удалить", show_alert=True)
            return
            
        db.session.execute(student_directions.delete().where(
            (student_directions.c.student_id==student.id) & (student_directions.c.direction_id==dir_id)
        ))
        db.session.commit()
        await callback.answer("Удалено")
        await show_my_status(callback, student)
    except Exception as e:
        logger.error(f"Ошибка удаления: {e}")
    finally:
        if ctx: ctx.pop()

@router.callback_query(F.data == "add_new_direction")
async def add_new_direction(callback: types.CallbackQuery):
    ctx = None
    try:
        ctx = get_db_session()
        tg_id = callback.from_user.id
        student = Student.query.filter_by(tg_id=tg_id).first()
        
        if not student:
            await callback.answer("⚠️ Сначала зарегистрируйтесь", show_alert=True); return

        # ✅ ПРОВЕРКА НА РУКОВОДИТЕЛЯ ИЗ /LEADERSHIP
        if not is_studcouncil_leader(tg_id):
            await callback.answer("️ Эта функция доступна только руководителям Студсовета", show_alert=True); return

        current_ids = [d.id for d in student.directions]
        available = Direction.query.filter(~Direction.id.in_(current_ids)).order_by(Direction.name).all()
        
        if not available:
            await callback.answer("✅ Вы уже выбрали все доступные направления!", show_alert=True); return
            
        buttons = [[InlineKeyboardButton(text=f"{d.icon or ''} {d.name}", callback_data=f"dir_{d.id}")] for d in available]
        buttons.append([InlineKeyboardButton(text="🔙 Назад к статусу", callback_data="back_to_status")])
        
        await callback.message.edit_text("Выберите новое направление:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    except Exception as e:
        logger.error(f"Ошибка добавления направления: {e}", exc_info=True)
        await callback.answer("️ Произошла техническая ошибка", show_alert=True)
    finally:
        if ctx: ctx.pop()

@router.callback_query(F.data == "back_to_status")
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