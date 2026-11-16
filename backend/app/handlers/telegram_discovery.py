import html
import logging
from aiogram import Router, types, F
from aiogram.filters import Filter, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ForceReply

logger=logging.getLogger(__name__)
router=Router()
pending_rejections = {}  # in-memory prompt state for active Telegram moderation
REJECTION_REASONS = {
    "study": "Учёба или экзамены",
    "health": "Здоровье",
    "family": "Семейные обстоятельства",
    "plans": "Изменились планы",
    "other": "Другая причина",
}

def rejection_reason_keyboard(student_id, direction_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📚 Учёба или экзамены", callback_data=f"reject_reason:study:{student_id}:{direction_id}")],
        [InlineKeyboardButton(text="🩺 Здоровье", callback_data=f"reject_reason:health:{student_id}:{direction_id}")],
        [InlineKeyboardButton(text="👪 Семейные обстоятельства", callback_data=f"reject_reason:family:{student_id}:{direction_id}")],
        [InlineKeyboardButton(text="🔄 Изменились планы", callback_data=f"reject_reason:plans:{student_id}:{direction_id}")],
        [InlineKeyboardButton(text="✍️ Другая причина", callback_data=f"reject_reason:other:{student_id}:{direction_id}")],
        [InlineKeyboardButton(text="↩️ Отмена", callback_data=f"app:cancel_reject:{student_id}:{direction_id}")],
    ])

class PendingRejectionReply(Filter):
    async def __call__(self, message: types.Message) -> bool:
        if not message.from_user or not message.reply_to_message:
            return False
        state = pending_rejections.get(message.from_user.id)
        return bool(
            state and message.chat.id == state.get("chat_id")
            and message.reply_to_message.message_id == state.get("prompt_message_id")
        )

@router.my_chat_member()
async def remember_on_membership_change(event: types.ChatMemberUpdated):
    from bot import remember_telegram_chat
    await remember_telegram_chat(event.chat)

@router.message(F.chat.type.in_({"group", "supergroup"}), ~PendingRejectionReply())
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
            from database import (db, DirectionChat, Student, student_directions, DirectionStatus,
                                  SharedActivityChat, ActivityChat, EventQuotaChat, EventQuota,
                                  EventDay, DayParticipation)
            from services.activity_chats import by_telegram_id, student_has_audience
            room = SharedActivityChat.query.filter_by(chat_id=str(request.chat.id)).first()
            if room:
                student = by_telegram_id(request.from_user.id)
                can_join = room.active and student_has_audience(student, room.audience)
                if can_join:
                    await bot_instance.approve_chat_join_request(chat_id=request.chat.id, user_id=request.from_user.id)
                else:
                    await bot_instance.decline_chat_join_request(chat_id=request.chat.id, user_id=request.from_user.id)
                return
            # A dedicated event group admits only students who currently hold a
            # valid registration for that event. The bot's join-request handler
            # is the access gate for links created during event setup.
            event_targets = EventQuotaChat.query.filter_by(
                chat_id=str(request.chat.id), platform='telegram'
            ).all()
            if event_targets:
                student = by_telegram_id(request.from_user.id)
                eligible_registration = None
                if student:
                    event_ids = {row.quota_id for row in event_targets if row.quota_id is not None}
                    if event_ids:
                        eligible_registration = db.session.query(DayParticipation.id).join(
                            EventDay, EventDay.id == DayParticipation.day_id
                        ).join(EventQuota, EventQuota.id == EventDay.quota_id).filter(
                            EventDay.quota_id.in_(event_ids),
                            DayParticipation.student_id == student.id,
                            DayParticipation.status.in_(['registered', 'attended']),
                            EventQuota.is_closed.is_(False), EventQuota.is_published.is_(True),
                        ).first()
                if eligible_registration:
                    await bot_instance.approve_chat_join_request(
                        chat_id=request.chat.id, user_id=request.from_user.id
                    )
                else:
                    await bot_instance.decline_chat_join_request(
                        chat_id=request.chat.id, user_id=request.from_user.id
                    )
                return
            # Retired per-event chats must not accidentally become open groups.
            if ActivityChat.query.filter_by(chat_id=str(request.chat.id)).first():
                await bot_instance.decline_chat_join_request(chat_id=request.chat.id, user_id=request.from_user.id)
                return
            # A Telegram chat may be associated with more than one direction. Accept
            # the request if the student has active membership in any of them.
            chat_rows = DirectionChat.query.filter_by(chat_id=str(request.chat.id), is_active=True).all()
            direction_ids = {row.direction_id for row in chat_rows}
            from services.multi_messenger import student_for
            student = student_for('telegram', request.from_user.id)
            link = None
            if student and direction_ids:
                link = db.session.execute(student_directions.select().where(
                    (student_directions.c.student_id == student.id)
                    & (student_directions.c.direction_id.in_(direction_ids))
                    & (student_directions.c.status.in_([DirectionStatus.ACTIVE.value]))
                )).first()
            if link:
                await bot_instance.approve_chat_join_request(chat_id=request.chat.id,user_id=request.from_user.id)
            else:
                await bot_instance.decline_chat_join_request(chat_id=request.chat.id,user_id=request.from_user.id)
    except Exception:
        logger.exception("Join request processing failed")

@router.message(PendingRejectionReply(), F.text)
async def capture_application_rejection_reason(message: types.Message):
    """Capture a leader's reply to the bot's ForceReply rejection prompt."""
    if not message.from_user or not message.text:
        return
    state = pending_rejections.get(message.from_user.id)
    if not state:
        return
    if (message.chat.id != state.get("chat_id") or
            message.reply_to_message.message_id != state.get("prompt_message_id")):
        return
    reason = " ".join(message.text.split())
    if not state.get("waiting_custom_reason"):
        await message.answer("Сначала выберите официальную причину отказа на карточке заявки.")
        return
    reason = f"{state.get('reason_category', 'Другая причина')}: {reason}"
    if len(reason) < 5:
        from bot import bot_instance
        prompt = await message.answer(
            "Причина должна содержать не менее 5 символов. Ответьте на это сообщение новой причиной.",
            reply_markup=ForceReply(selective=True, input_field_placeholder="Причина отказа (минимум 5 символов)"),
        )
        state["prompt_message_id"] = prompt.message_id
        return

    from bot import app_instance, bot_instance
    if not app_instance or not bot_instance:
        pending_rejections.pop(message.from_user.id, None)
        await message.answer("Бот не готов. Попробуйте снова через минуту.")
        return
    try:
        with app_instance.app_context():
            from database import Student, Direction
            from services.applications import set_application_status, latest_application_decision
            student = Student.query.get(state["student_id"])
            direction = Direction.query.get(state["direction_id"])
            if not student or not direction:
                pending_rejections.pop(message.from_user.id, None)
                await message.answer("Заявка больше не найдена.")
                return
            ok, result, _ = set_application_status(
                student.id, direction.id, "rejected", actor_tg_id=message.from_user.id,
                reason=reason, source="telegram",
            )
            if not ok:
                pending_rejections.pop(message.from_user.id, None)
                await message.answer(result)
                return
            decision = latest_application_decision(student.id, direction.id)
            until = decision.blocked_until.strftime("%d.%m.%Y в %H:%M") if decision and decision.blocked_until else "через 7 дней"
            student_name = student.full_name or '—'
            direction_name = direction.name or '—'
        pending_rejections.pop(message.from_user.id, None)
        original_text = (
            f"📌 Заявка <b>отклонена</b>\n\n"
            f"👤 {html.escape(student_name)}\n"
            f"📍 {html.escape(direction_name)}\n"
            f"📝 <b>Причина:</b> {html.escape(reason)}\n"
            f"⏳ Повторная подача доступна после <b>{until}</b>."
        )
        try:
            await bot_instance.edit_message_text(
                chat_id=state["chat_id"], message_id=state["original_message_id"],
                text=original_text, parse_mode="HTML",
            )
        except Exception:
            logger.debug("Unable to edit original application message after rejection", exc_info=True)
        await message.answer("Причина сохранена. Заявка отклонена, блокировка действует 7 дней.")
    except Exception:
        logger.exception("Could not save application rejection reason")
        pending_rejections.pop(message.from_user.id, None)
        await message.answer("Не удалось сохранить отказ. Повторите действие с карточки заявки.")
    finally:
        if app_instance:
            from database import db
            db.session.remove()


@router.callback_query(F.data.startswith("reject_reason:"))
async def choose_rejection_reason(callback: types.CallbackQuery):
    try:
        _, key, student_raw, direction_raw = callback.data.split(":", 3)
        student_id, direction_id = int(student_raw), int(direction_raw)
        reason = REJECTION_REASONS.get(key)
        state = pending_rejections.get(callback.from_user.id)
        if not reason or not state or state.get("student_id") != student_id or state.get("direction_id") != direction_id:
            await callback.answer("Сценарий отказа завершён или недоступен", show_alert=True)
            return
        from bot import app_instance
        if not app_instance:
            await callback.answer("Бот не готов", show_alert=True)
            return
        with app_instance.app_context():
            from database import Student, Direction
            from services.permissions import can_manage_direction
            student = Student.query.get(student_id)
            direction = Direction.query.get(direction_id)
            if not student or not direction or not can_manage_direction(callback.from_user.id, direction_id, student.education_type):
                pending_rejections.pop(callback.from_user.id, None)
                await callback.answer("Нет прав для этой заявки", show_alert=True)
                return
            if key == "other":
                state["reason_category"] = reason
                prompt = await callback.message.answer(
                    "✍️ Укажите конкретную причину отказа. Это обязательное поле (не менее 5 символов):",
                    reply_markup=ForceReply(selective=True, input_field_placeholder="Обязательная причина отказа"),
                )
                state["prompt_message_id"] = prompt.message_id
                state["waiting_custom_reason"] = True
                await callback.answer("Нужен комментарий")
                return
            from services.applications import set_application_status, latest_application_decision
            ok, result, _ = set_application_status(student_id, direction_id, "rejected", actor_tg_id=callback.from_user.id, reason=reason, source="telegram")
            if not ok:
                await callback.answer(result, show_alert=True)
                return
            decision = latest_application_decision(student_id, direction_id)
            until = decision.blocked_until.strftime("%d.%m.%Y в %H:%M") if decision and decision.blocked_until else "через 7 дней"
            await callback.message.edit_text(
                f"📌 Заявка <b>отклонена</b>\n\n👤 {html.escape(student.full_name or '—')}\n"
                f"📍 {html.escape(direction.name or '—')}\n📝 <b>Причина:</b> {html.escape(reason)}\n"
                f"⏳ Повторная подача доступна после <b>{until}</b>.", parse_mode="HTML")
            pending_rejections.pop(callback.from_user.id, None)
            await callback.answer("Причина сохранена")
    except Exception:
        logger.exception("Unable to select rejection reason")
        await callback.answer("Не удалось сохранить причину", show_alert=True)

@router.callback_query(F.data.startswith("app:"))
async def application_decision(callback: types.CallbackQuery):
    try:
        parts = callback.data.split(":")
        if len(parts) != 4:
            await callback.answer("Ошибка данных", show_alert=True)
            return
        action, student_id, direction_id = parts[1], int(parts[2]), int(parts[3])
        if action not in {"approve", "reject", "cancel_reject"}:
            await callback.answer("Неизвестное действие", show_alert=True)
            return
        from bot import app_instance
        if not app_instance:
            await callback.answer("Бот не готов", show_alert=True)
            return
        if action == "cancel_reject":
            state = pending_rejections.get(callback.from_user.id)
            if state and state.get("student_id") == student_id and state.get("direction_id") == direction_id:
                pending_rejections.pop(callback.from_user.id, None)
                await callback.message.edit_text("↩️ Отклонение отменено. Заявка не изменена.")
                await callback.answer("Отмена")
            else:
                await callback.answer("Запрос на отказ уже завершён", show_alert=True)
            return

        with app_instance.app_context():
            from database import Student, Direction
            from services.applications import set_application_status
            from services.permissions import can_manage_direction
            student = Student.query.get(student_id)
            direction = Direction.query.get(direction_id)
            if not student or not direction:
                await callback.answer("Заявка не найдена", show_alert=True)
                return
            if not can_manage_direction(callback.from_user.id, direction_id, student.education_type):
                await callback.answer("Нет прав для этой заявки", show_alert=True)
                return
            if action == "reject":
                if callback.from_user.id in pending_rejections:
                    await callback.answer("Сначала завершите предыдущий отказ или отмените его.", show_alert=True)
                    return
                pending_rejections[callback.from_user.id] = {
                    "student_id": student_id,
                    "direction_id": direction_id,
                    "chat_id": callback.message.chat.id,
                    "original_message_id": callback.message.message_id,
                }
                await callback.message.edit_text(
                    f"❌ <b>Отклонение заявки</b>\n\n👤 {html.escape(student.full_name or '—')}\n"
                    f"📍 {html.escape(direction.name or '—')}\n\n"
                    "Выберите официальную причину отказа. Для пункта «Другая причина» потребуется обязательный комментарий. "
                    "После отказа повторная подача будет закрыта на 7 дней.",
                    reply_markup=rejection_reason_keyboard(student_id, direction_id), parse_mode="HTML",
                )
                await callback.answer("Выберите причину отказа")
                return

            ok, msg, invite_count = set_application_status(
                student_id, direction_id, "active", actor_tg_id=callback.from_user.id,
                source="telegram",
            )
            if not ok:
                await callback.answer(msg, show_alert=True)
                return
            decision = "принята и сразу активирована"
            await callback.message.edit_text(
                f"📌 Заявка <b>{html.escape(decision)}</b>\n\n👤 {html.escape(student.full_name or '—')}\n"
                f"📍 {html.escape(direction.name or '—')}\n🔗 Ссылок отправлено: {invite_count}",
                parse_mode="HTML",
            )
            await callback.answer("Готово")
    except Exception:
        logger.exception("Application decision failed")
        await callback.answer("Не удалось обработать заявку", show_alert=True)



@router.message(Command('my_chats'))
async def my_activity_chats(message: types.Message):
    """Show only personally authorized reading/event group invitations."""
    if message.chat.type != 'private' or not message.from_user:
        return
    from bot import app_instance
    if app_instance is None:
        return
    with app_instance.app_context():
        from database import Student, SharedActivityChat
        from services.activity_chats import student_has_audience, by_telegram_id
        student = by_telegram_id(message.from_user.id)
        entries = []
        if student:
            for room in SharedActivityChat.query.filter_by(active=True).all():
                if room.invite_link and student_has_audience(student, room.audience):
                    entries.append(f'• {html.escape(room.title)}: {html.escape(room.invite_link)}')
        text = '💬 <b>Мои чаты событий и научных чтений</b>\n\n' + (\
            '\n'.join(entries[:20]) if entries else 'Постоянные чаты появятся после подтверждения участия.')
    await message.answer(text[:3900], parse_mode='HTML')
