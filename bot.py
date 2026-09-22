import asyncio
from datetime import datetime

from aiogram import Bot, Dispatcher, Router, types, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

from config import settings
from database import db, Student, StudentStatus, Direction, EventQuota, Participant

router = Router()

@router.message(CommandStart())
async def cmd_start(message: types.Message):
    keyboard = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📝 Подать заявку")],
        [KeyboardButton(text="📅 Мои квоты")]
    ], resize_keyboard=True)
    await message.answer(
        "🎓 Добро пожаловать!\n\nОтправьте ФИО для регистрации:",
        reply_markup=keyboard
    )

@router.message(F.text == "📅 Мои квоты")
async def show_my_quotas(message: types.Message):
    from web_app import create_app
    app = create_app()
    with app.app_context():
        student = Student.query.filter_by(tg_id=message.from_user.id).first()
        if not student:
            await message.answer("⚠️ Сначала зарегистрируйтесь командой /start")
            return
        if not student.direction_id:
            await message.answer("️ Вам еще не назначено направление. Ожидайте решения комиссии.")
            return
            
        quotas = EventQuota.query.filter(
            EventQuota.direction_id == student.direction_id,
            EventQuota.event_date > datetime.utcnow()
        ).order_by(EventQuota.event_date).all()
        
        if not quotas:
            await message.answer("📭 Для вашего направления пока нет активных квот.")
            return
            
        buttons = []
        for q in quotas:
            free = q.available_places()
            btn_text = f"📌 {q.event_title} ({free} мест)"
            buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"eq_{q.id}")])
            
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await message.answer("Выберите квоту для записи:", reply_markup=keyboard)

@router.callback_query(F.data.startswith("eq_"))
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
            f" {quota.event_date.strftime('%d.%m.%Y в %H:%M')}\n"
            f"🎓 Направление: {quota.direction.name}"
        )
    await callback.answer("Запись подтверждена!")

@router.message(lambda m: m.text and len(m.text.strip().split()) >= 2 and m.text != "📅 Мои квоты")
async def register_student(message: types.Message):
    from web_app import create_app
    app = create_app()
    with app.app_context():
        existing = Student.query.filter_by(tg_id=message.from_user.id).first()
        if existing:
            await message.answer("⚠️ Вы уже зарегистрированы!")
            return
        student = Student(
            tg_id=message.from_user.id,
            full_name=message.text.strip(),
            status=StudentStatus.PENDING.value,
        )
        db.session.add(student)
        db.session.commit()
    await message.answer(
        f"✅ Заявка принята!\nФИО: {message.text}\nСтатус:  На проверке\n\n"
        f"После назначения направления вам станут доступны квоты."
    )

async def run_bot():
    bot = Bot(token=settings.BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    print("🤖 Telegram бот запущен...")
    await dp.start_polling(bot)