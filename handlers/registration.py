import logging
import json
from datetime import datetime
from aiogram import Router, types, F
from database import db, Student, StudentStatus, Direction, student_directions, StudentLeadership
from config import RegState, AddState

logger = logging.getLogger(__name__)

router = Router()

# Хранилища состояний
registration_data = {}
adding_data = {}
removing_data = {}

def get_db_session():
    from bot import app_instance
    if not app_instance: raise RuntimeError("Flask app не инициализирован!")
    ctx = app_instance.app_context(); ctx.push(); return ctx

def check_leadership_rights(tg_id):
    """Проверяет, является ли пользователь руководителем ЛЮБОГО направления"""
    try:
        ctx = get_db_session()
        student = Student.query.filter_by(tg_id=tg_id).first()
        if not student: return False, None
            
        leadership = StudentLeadership.query.filter_by(student_id=student.id).first()
        
        if leadership:
            direction = Direction.query.get(leadership.direction_id)
            return True, direction
        return False, None
    except Exception as e:
        logger.error(f"Error checking rights: {e}")
        return False, None
    finally:
        if 'ctx' in locals(): ctx.pop()

# ✅ ОБРАБОТЧИК КНОПКИ "ПОДАТЬ ЗАЯВКУ"
@router.message(F.text == "📝 Подать заявку")
async def start_registration(message: types.Message):
    ctx = None
    try:
        ctx = get_db_session()
        tg_id = message.from_user.id
        
        existing = Student.query.filter_by(tg_id=tg_id).first()
        if existing:
            await message.answer("️ Вы уже зарегистрированы. Используйте 'Мой статус'.")
            return
            
        registration_data[tg_id] = {"step": RegState.NAME}
        await message.answer("<b>Регистрация</b>\n\nОтправьте ваше <b>ФИО</b>:", parse_mode="HTML")
    except Exception as e:
        logger.error(f"Ошибка start_registration: {e}")
        await message.answer(f"️ Ошибка: {str(e)[:100]}")
    finally:
        if ctx: ctx.pop()

# ✅ ЕДИНЫЙ ОБРАБОТЧИК ВСЕХ ТЕКСТОВЫХ СОСТОЯНИЙ
@router.message(lambda m: m.from_user.id in registration_data or m.from_user.id in adding_data or m.from_user.id in removing_data)
async def handle_input(message: types.Message):
    tg_id = message.from_user.id
    ctx = None
    
    try:
        # --- ЛОГИКА РЕГИСТРАЦИИ ---
        if tg_id in registration_data:
            step = registration_data[tg_id].get("step")
            
            if step == RegState.NAME:
                if len(message.text.split()) < 2: 
                    await message.answer("️ Введите Фамилию и Имя."); return
                registration_data[tg_id]["full_name"] = message.text.strip()
                registration_data[tg_id]["step"] = RegState.GROUP
                await message.answer("✅ ФИО принято.\n\nВаша <b>учебная группа</b>:", parse_mode="HTML"); return

            elif step == RegState.GROUP:
                registration_data[tg_id]["group"] = message.text.strip()
                registration_data[tg_id]["step"] = RegState.PHONE
                await message.answer("✅ Группа принята.\n\nВаш <b>номер телефона</b>:", parse_mode="HTML"); return

            elif step == RegState.PHONE:
                if not any(c.isdigit() for c in message.text): 
                    await message.answer("️ Номер должен содержать цифры."); return
                
                ctx = get_db_session()
                data = registration_data[tg_id]
                
                student = Student(
                    tg_id=tg_id,
                    full_name=data["full_name"], 
                    group=data["group"], 
                    phone=message.text.strip(), 
                    status=StudentStatus.PENDING.value
                )
                db.session.add(student)
                db.session.commit()
                
                # При регистрации показываем только Студсовет
                dirs = Direction.query.filter_by(code='STUDCOUNCIL').all() 
                if not dirs:
                     await message.answer("⚠️ Ошибка конфигурации.")
                     return

                buttons = [[types.InlineKeyboardButton(text=f"{d.icon} {d.name}", callback_data=f"dir_{d.id}")] for d in dirs]
                kb = types.InlineKeyboardMarkup(inline_keyboard=buttons)
                
                await message.answer(f"✅ Заявка #{student.id} создана!\n\nВыберите направление:", reply_markup=kb, parse_mode="HTML")
                registration_data[tg_id]["step"] = RegState.DIR_SELECT
                logger.info(f"New registration: {student.full_name} (TG: {tg_id})")
                return

        # --- ЛОГИКА ДОБАВЛЕНИЯ СТУДЕНТА ---
        elif tg_id in adding_data:
            step = adding_data[tg_id].get("step")
            
            if step == AddState.NAME:
                if len(message.text.split()) < 2: 
                    await message.answer("️ Введите Фамилию и Имя."); return
                adding_data[tg_id]["full_name"] = message.text.strip()
                adding_data[tg_id]["step"] = AddState.GROUP
                await message.answer("✅ ФИО принято.\n\nВведите <b>группу</b>:", parse_mode="HTML"); return

            elif step == AddState.GROUP:
                adding_data[tg_id]["group"] = message.text.strip()
                adding_data[tg_id]["step"] = AddState.PHONE
                await message.answer("✅ Группа принята.\n\nВведите <b>телефон</b>:", parse_mode="HTML"); return

            elif step == AddState.PHONE:
                if not any(c.isdigit() for c in message.text): 
                    await message.answer("⚠️ Номер должен содержать цифры."); return
                
                ctx = get_db_session()
                data = adding_data[tg_id]
                dir_id = data["direction_id"]
                
                existing_student = Student.query.filter_by(full_name=data["full_name"], group=data["group"]).first()
                
                if existing_student:
                    is_in_dir = db.session.execute(student_directions.select().where(
                        (student_directions.c.student_id == existing_student.id) & 
                        (student_directions.c.direction_id == dir_id)
                    )).fetchone()
                    
                    if is_in_dir:
                        await message.answer(f"⚠️ Студент <b>{existing_student.full_name}</b> уже состоит в этом направлении!", parse_mode="HTML")
                        adding_data.pop(tg_id, None)
                        return
                        
                    student = existing_student
                    student.phone = message.text.strip()
                else:
                    student = Student(
                        tg_id=0,
                        full_name=data["full_name"], 
                        group=data["group"], 
                        phone=message.text.strip(), 
                        status=StudentStatus.ACTIVE.value
                    )
                    db.session.add(student)
                    db.session.flush()
                    
                db.session.execute(student_directions.insert().values(
                    student_id=student.id, 
                    direction_id=dir_id, 
                    extra_data=json.dumps({"added_by": tg_id, "date": datetime.utcnow().isoformat()})
                ))
                
                db.session.commit()
                
                await message.answer(
                    f"✅ <b>Студент добавлен!</b>\n\n"
                    f" {student.full_name}\n"
                    f"🎓 {student.group}\n"
                    f"📌 {data['direction_name']}\n"
                    f"Статус: 🚀 Активен",
                    parse_mode="HTML"
                )
                adding_data.pop(tg_id, None)
                return

        # --- ЛОГИКА УДАЛЕНИЯ СТУДЕНТА ---
        elif tg_id in removing_data:
            step = removing_data[tg_id].get("step")
            
            if step == "remove_name":
                ctx = get_db_session()
                data = removing_data[tg_id]
                dir_id = data["direction_id"]
                
                student = Student.query.filter_by(full_name=message.text.strip()).first()
                
                if not student:
                    await message.answer("⚠️ Студент с таким ФИО не найден.")
                    removing_data.pop(tg_id, None)
                    return
                    
                is_in_dir = db.session.execute(student_directions.select().where(
                    (student_directions.c.student_id == student.id) & 
                    (student_directions.c.direction_id == dir_id)
                )).fetchone()
                
                if not is_in_dir:
                    await message.answer(f"⚠️ Студент <b>{student.full_name}</b> не состоит в этом направлении!", parse_mode="HTML")
                    removing_data.pop(tg_id, None)
                    return
                
                db.session.execute(student_directions.delete().where(
                    (student_directions.c.student_id == student.id) & 
                    (student_directions.c.direction_id == dir_id)
                ))
                db.session.commit()
                
                await message.answer(
                    f"✅ <b>Студент удален!</b>\n\n"
                    f"👤 {student.full_name}\n"
                    f" {student.group}",
                    parse_mode="HTML"
                )
                removing_data.pop(tg_id, None)
                return

    except Exception as e:
        logger.error(f"Ошибка handle_input: {e}", exc_info=True)
        await message.answer(f"⚠️ Ошибка: {str(e)[:100]}")
    finally:
        if ctx: ctx.pop()

# ✅ ОБРАБОТЧИК КНОПКИ "ДОБАВИТЬ СТУДЕНТА"
@router.message(F.text == "➕ Добавить студента")
async def start_add_student(message: types.Message):
    ctx = None
    try:
        ctx = get_db_session()
        tg_id = message.from_user.id
        
        has_rights, direction = check_leadership_rights(tg_id)
        
        if not has_rights:
            await message.answer("⚠️ У вас нет прав. Только назначенные руководители могут добавлять студентов.")
            return
            
        adding_data[message.from_user.id] = {
            "step": AddState.NAME,
            "direction_id": direction.id,
            "direction_name": direction.name
        }
        
        await message.answer(
            f"➕ <b>Добавление в «{direction.name}»</b>\n\n"
            f"Отправьте <b>ФИО</b> студента:", 
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка start_add_student: {e}")
        await message.answer(f"⚠️ Ошибка: {str(e)[:100]}")
    finally:
        if ctx: ctx.pop()

# ✅ ОБРАБОТЧИК КНОПКИ "УДАЛИТЬ СТУДЕНТА"
@router.message(F.text == "🗑️ Удалить студента")
async def start_remove_student(message: types.Message):
    ctx = None
    try:
        ctx = get_db_session()
        tg_id = message.from_user.id
        
        has_rights, direction = check_leadership_rights(tg_id)
        
        if not has_rights:
            await message.answer("⚠️ У вас нет прав. Только назначенные руководители могут удалять студентов.")
            return
            
        removing_data[message.from_user.id] = {
            "step": "remove_name",
            "direction_id": direction.id
        }
        
        await message.answer(
            f"🗑️ <b>Удаление из «{direction.name}»</b>\n\n"
            f"Отправьте <b>ФИО</b> студента, которого нужно удалить:", 
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка start_remove_student: {e}")
        await message.answer(f"️ Ошибка: {str(e)[:100]}")
    finally:
        if ctx: ctx.pop()