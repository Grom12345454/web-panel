import logging
from aiogram import Router, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

logger=logging.getLogger(__name__)
router=Router()

@router.my_chat_member()
async def remember_on_membership_change(event: types.ChatMemberUpdated):
    from bot import remember_telegram_chat
    await remember_telegram_chat(event.chat)

@router.message()
async def remember_on_message(message: types.Message):
    if message.chat.type in {"group","supergroup","channel"}:
        from bot import remember_telegram_chat
        await remember_telegram_chat(message.chat)

@router.channel_post()
async def remember_on_channel_post(message: types.Message):
    from bot import remember_telegram_chat
    await remember_telegram_chat(message.chat)

@router.chat_join_request()
async def approve_direction_join_request(request: types.ChatJoinRequest):
    try:
        from bot import app_instance, bot_instance
        if not app_instance or not bot_instance: return
        with app_instance.app_context():
            from database import db, DirectionChat, Student, student_directions, DirectionStatus
            chat=DirectionChat.query.filter_by(chat_id=str(request.chat.id),is_active=True).first()
            if not chat:
                return
            link=db.session.execute(student_directions.select().where((student_directions.c.student_id==Student.id)&(student_directions.c.direction_id==chat.direction_id)&(student_directions.c.status.in_([DirectionStatus.APPROVED.value,DirectionStatus.ACTIVE.value]))&(Student.tg_id==request.from_user.id))).first()
            if link:
                await bot_instance.approve_chat_join_request(chat_id=request.chat.id,user_id=request.from_user.id)
            else:
                await bot_instance.decline_chat_join_request(chat_id=request.chat.id,user_id=request.from_user.id)
    except Exception:
        logger.exception("Join request processing failed")

@router.callback_query(F.data.startswith("app:"))
async def application_decision(callback: types.CallbackQuery):
    try:
        parts=callback.data.split(":")
        if len(parts)!=4: await callback.answer("Ошибка данных",show_alert=True); return
        action,student_id,direction_id=parts[1],int(parts[2]),int(parts[3])
        if action not in {"approve","reject"}: await callback.answer("Неизвестное действие",show_alert=True); return
        from bot import app_instance, bot_instance
        if not app_instance or not bot_instance: await callback.answer("Бот не готов",show_alert=True); return
        with app_instance.app_context():
            from database import StudentLeadership, Student, Direction
            from services.applications import set_application_status
            student=Student.query.get(student_id); direction=Direction.query.get(direction_id)
            if not student or not direction: await callback.answer("Заявка не найдена",show_alert=True); return
            allowed=any(r.student and r.student.tg_id==callback.from_user.id and r.direction_id==direction_id and r.education_type in {student.education_type,"all"} for r in StudentLeadership.query.all())
            if not allowed: await callback.answer("Нет прав для этой заявки",show_alert=True); return
            new_status="approved" if action=="approve" else "rejected"
            ok,msg,invite_count=set_application_status(student_id,direction_id,new_status,actor_tg_id=callback.from_user.id)
            if not ok: await callback.answer(msg,show_alert=True); return
            decision="одобрена" if action=="approve" else "отклонена"
            await callback.message.edit_text(f"📌 Заявка <b>{decision}</b>\n\n👤 {student.full_name}\n📍 {direction.name}" + (f"\n🔗 Ссылок отправлено: {invite_count}" if action=="approve" else ""),parse_mode="HTML")
            await callback.answer("Готово")
    except Exception:
        logger.exception("Application decision failed")
        await callback.answer("Не удалось обработать заявку",show_alert=True)
