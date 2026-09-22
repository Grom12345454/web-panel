import asyncio
from datetime import datetime
from aiogram import Bot, Dispatcher, Router, types, F
from aiogram.filters import CommandStart
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from config import settings
from database import db, Student, StudentStatus, Direction, EventQuota, Participant

router = Router()
bot_instance = None 

@router.message(CommandStart())
async def cmd_start(message: types.Message):
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📝 Подать заявку")],
        [KeyboardButton(text="📅 Мероприятия")],
        [KeyboardButton(text="ℹ️ Мой статус")]
    ], resize_keyboard=True)
    await message.answer("🎓 Технологический университет\n\nВыберите действие:", reply_markup=kb)

@router.message(F.text == " Подать заявку")
async def start_application(message: types.Message):
    from web_app import create_app
    app = create_app()
    with app.app_context():
        existing = Student.query.filter_by(tg_id=message.from_user.id).first()
        if existing:
            await message.answer(f"⚠️ У вас уже есть заявка №{existing.id}. Статус: {existing.status}")
            return
    await message.answer("Отправьте ваше ФИО полностью:")

@router.message(lambda m: m.text and len(m.text.split()) >= 2 and m.text != "📝 Подать заявку")
async def register_student(message: types.Message):
    from web_app import create_app
    app = create_app()
    with app.app_context():
        student = Student(tg_id=message.from_user.id, full_name=message.text.strip(), status=StudentStatus.PENDING.value)
        db.session.add(student)
        db.session.commit()
        
        dirs = Direction.query.all()
        buttons = [[InlineKeyboardButton(text=d.name, callback_data=f"dir_{d.id}")] for d in dirs]
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        await message.answer(f"✅ Заявка #{student.id} создана.\nСтатус: Ожидает проверки.\n\nВыберите направление:", reply_markup=kb)

@router.callback_query(lambda c: c.data.startswith("dir_"))
async def choose_direction(callback: types.CallbackQuery):
    from web_app import create_app
    app = create_app()
    dir_id = int(callback.data.split("_")[1])
    
    with app.app_context():
        student = Student.query.filter_by(tg_id=callback.from_user.id).first()
        if student:
            student.direction_id = dir_id
            db.session.commit()
            direction = Direction.query.get(dir_id)
            await callback.message.edit_text(f"📌 Направление: {direction.name}\n\nОжидайте одобрения координатором.")

@router.message(F.text == "📅 Мероприятия")
async def show_events(message: types.Message):
    from web_app import create_app
    app = create_app()
    with app.app_context():
        student = Student.query.filter_by(tg_id=message.from_user.id).first()
        if not student or not student.direction_id:
            await message.answer("️ Сначала выберите направление в заявке.")
            return
            
        quotas = EventQuota.query.filter(
            EventQuota.direction_id == student.direction_id,
            EventQuota.event_date > datetime.utcnow()
        ).order_by(EventQuota.event_date).all()
        
        if not quotas:
            await message.answer("📭 Для вашего направления пока нет мероприятий.")
            return
            
        buttons = []
        for q in quotas:
            free = q.available_places()
            btn_text = f"📌 {q.event_title} ({free} мест)"
            buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"eq_{q.id}")])
            
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await message.answer("Выберите мероприятие:", reply_markup=keyboard)

@router.callback_query(lambda c: c.data.startswith("eq_"))
async def register_for_quota(callback: types.CallbackQuery):
    from web_app import create_app
    app = create_app()
    quota_id = int(callback.data.split("_")[1])
    
    with app.app_context():
        student = Student.query.filter_by(tg_id=callback.from_user.id).first()
        quota = EventQuota.query.get(quota_id)
        
        if not student or not quota:
            await callback.answer("❌ Ошибка", show_alert=True)
            return
        existing = Participant.query.filter_by(student_id=student.id, quota_id=quota_id).first()
        if existing:
            await callback.answer("ℹ️ Вы уже записаны", show_alert=True)
            return
        if quota.available_places() <= 0:
            await callback.answer("🚫 Места закончились!", show_alert=True)
            return
            
        participation = Participant(student_id=student.id, quota_id=quota_id)
        db.session.add(participation)
        db.session.commit()
        
        await callback.message.edit_text(
            f"✅ Вы записаны!\n\n📌 {quota.event_title}\n"
            f"📅 {quota.event_date.strftime('%d.%m.%Y в %H:%M')}\n"
            f"🎓 Направление: {quota.direction.name}"
        )
    await callback.answer("Запись подтверждена!")

def send_notification(tg_id: int, text: str):
    global bot_instance
    if bot_instance:
        try:
            asyncio.run(bot_instance.send_message(chat_id=tg_id, text=text))
        except Exception as e:
            print(f"Ошибка отправки уведомления {tg_id}: {e}")

async def run_bot():
    global bot_instance
    bot_instance = Bot(token=settings.BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    print("🤖 Telegram Bot запущен...")
    await dp.start_polling(bot_instance)