import logging
from aiogram import Router, types

logger = logging.getLogger(__name__)
router = Router()


@router.my_chat_member()
async def remember_on_membership_change(event: types.ChatMemberUpdated):
    from bot import remember_telegram_chat
    await remember_telegram_chat(event.chat)


@router.message()
async def remember_on_message(message: types.Message):
    if message.chat.type in {"group", "supergroup", "channel"}:
        from bot import remember_telegram_chat
        await remember_telegram_chat(message.chat)


@router.channel_post()
async def remember_on_channel_post(message: types.Message):
    from bot import remember_telegram_chat
    await remember_telegram_chat(message.chat)


@router.chat_join_request()
async def approve_direction_join_request(request: types.ChatJoinRequest):
    """Automatically approve students who received a direction invite link."""
    try:
        from bot import app_instance, bot_instance
        if not app_instance or not bot_instance:
            return
        with app_instance.app_context():
            from database import db, DirectionChat, Student, student_directions, DirectionStatus
            chat_id = str(request.chat.id)
            chat = DirectionChat.query.filter_by(chat_id=chat_id, is_active=True).first()
            if not chat:
                return
            link = db.session.execute(student_directions.select().where(
                (student_directions.c.student_id == Student.id) &
                (student_directions.c.direction_id == chat.direction_id) &
                (student_directions.c.status.in_([DirectionStatus.APPROVED.value, DirectionStatus.ACTIVE.value])) &
                (Student.tg_id == request.from_user.id)
            )).first()
            if link:
                await bot_instance.approve_chat_join_request(chat_id=request.chat.id, user_id=request.from_user.id)
                logger.info("Approved join request: user=%s direction=%s chat=%s", request.from_user.id, chat.direction_id, chat_id)
            else:
                await bot_instance.decline_chat_join_request(chat_id=request.chat.id, user_id=request.from_user.id)
                logger.info("Declined unauthorized join request: user=%s direction=%s chat=%s", request.from_user.id, chat.direction_id, chat_id)
    except Exception:
        logger.exception("Join request processing failed")
