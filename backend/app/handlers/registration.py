import html
import logging
from aiogram import Router, types, F
from aiogram.types import (InlineKeyboardMarkup, InlineKeyboardButton,
                            KeyboardButton, ReplyKeyboardMarkup)
from database import db, Student, EducationType
from config import RegState
from bot_messages import text as bot_text

logger=logging.getLogger(__name__)
router=Router(); registration_data={}

def telegram_student_for(user_id):
    from services.multi_messenger import student_for
    return student_for('telegram', user_id)


def sync_telegram_username(tg_user):
    # Keep the stored value in sync with Telegram's current profile, including a removed username.
    if not tg_user:
        return
    student = telegram_student_for(tg_user.id)
    username = (getattr(tg_user, 'username', None) or '').strip().lstrip('@')[:255] or None
    if student and student.telegram_username != username:
        student.telegram_username = username
        db.session.commit()

def get_db_session():
    from bot import app_instance
    if not app_instance: raise RuntimeError('Flask app не инициализирован')
    ctx=app_instance.app_context(); ctx.push(); return ctx

def cancel_markup():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text='✕ Отменить')]],
        resize_keyboard=True, is_persistent=True, one_time_keyboard=False,
        input_field_placeholder='Введите ответ',
    )

async def delete_input_message(message: types.Message):
    """Remove user-entered personal data from the chat when Telegram permits it."""
    try:
        await message.delete()
    except Exception as exc:
        # Some chats/old messages can be non-deletable; never interrupt registration.
        logger.debug('Could not delete user input message (%s)', type(exc).__name__)

def registration_screen(step, title, hint=None, error=None):
    """Render the active registration step inside one editable Telegram message."""
    labels = ['Контур', 'ФИО', 'Группа', 'Телефон']
    progress = ' '.join('▰' if idx < step else '▱' for idx in range(4))
    current = labels[max(0, min(step - 1, 3))]
    pieces = [
        '🪐 <b>Регистрация профиля</b>',
        f'<code>{progress}</code>  <b>Шаг {step} из 4</b> · {current}',
        '',
    ]
    if error:
        pieces.extend([f'⚠️ {html.escape(error)}', ''])
    pieces.append(f'<b>{title}</b>')
    if hint:
        pieces.extend(['', hint])
    return '\n'.join(pieces)

async def update_registration_prompt(message, state, text, reply_markup=None):
    """Edit a single bot message throughout registration; send a fallback only if edit fails."""
    chat_id = state.get('prompt_chat_id') or message.chat.id
    message_id = state.get('prompt_message_id')
    # ReplyKeyboardMarkup is attached to the chat composer, not to a message.
    # Telegram cannot install it through editMessageText, so each step sends a
    # fresh prompt and updates the persistent bottom keyboard.
    sent = await message.answer(
        text,
        reply_markup=reply_markup,
        parse_mode='HTML',
        disable_web_page_preview=True,
    )
    state['prompt_chat_id'] = sent.chat.id
    state['prompt_message_id'] = sent.message_id

def education_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text='🏫 Колледж')],
            [KeyboardButton(text='🎓 Институт')],
            [KeyboardButton(text='✕ Отменить')],
        ], resize_keyboard=True, is_persistent=True, one_time_keyboard=False,
        input_field_placeholder='Выберите учебный контур',
    )

async def start_registration_flow(message: types.Message,tg_id=None,edit=False):
    ctx=None
    try:
        ctx=get_db_session(); tg_id=tg_id or message.from_user.id
        sync_telegram_username(message.from_user)
        student = telegram_student_for(tg_id)
        if student and student.council_registered:
            await message.answer(bot_text('profile_exists'),parse_mode='HTML'); return
        state = {
            'step': RegState.EDUCATION_TYPE,
            'prompt_chat_id': message.chat.id,
            'prompt_message_id': message.message_id if edit else None,
        }
        registration_data[tg_id] = state
        text = registration_screen(1, 'Выберите учебный контур')
        if edit:
            await update_registration_prompt(message, state, text, reply_markup=education_keyboard())
        else:
            sent = await message.answer(text, reply_markup=education_keyboard(), parse_mode='HTML', disable_web_page_preview=True)
            state['prompt_chat_id'] = sent.chat.id
            state['prompt_message_id'] = sent.message_id
    finally:
        if ctx: ctx.pop()

@router.message(F.text=='📝 Подать заявку')
async def start_registration(message: types.Message):
    ctx=None
    try:
        ctx=get_db_session(); sync_telegram_username(message.from_user); existing=telegram_student_for(message.from_user.id)
    finally:
        if ctx: ctx.pop()
    if existing and existing.council_registered:
        await message.answer(bot_text('profile_exists'),parse_mode='HTML'); return
    await start_registration_flow(message)

def is_legacy_education_reply(message: types.Message) -> bool:
    """Return True only while this user is in the legacy aiogram registration flow."""
    if not message.from_user:
        return False
    state = registration_data.get(message.from_user.id)
    return bool(state and state.get('step') == RegState.EDUCATION_TYPE)


@router.message(F.text.in_({'🏫 Колледж', '🎓 Институт'}), is_legacy_education_reply)
async def choose_education_type_from_bottom(message: types.Message):
    tg_id = message.from_user.id
    value = 'college' if message.text == '🏫 Колледж' else 'institute'
    state = registration_data.get(tg_id)
    state['education_type'] = value
    state['step'] = RegState.NAME
    label = 'Колледж' if value == 'college' else 'Институт'
    await update_registration_prompt(
        message, state,
        registration_screen(2, 'Укажите ФИО',
                            f'Учебный контур: <b>{label}</b>.\nНапишите фамилию и имя; отчество можно добавить при наличии.'),
        reply_markup=cancel_markup(),
    )


@router.message(F.text == '✕ Отменить')
async def cancel_registration_from_bottom(message: types.Message):
    if not message.from_user:
        return
    state = registration_data.pop(message.from_user.id, None)
    if state:
        from services.bot_ui import home_text, rows_for_screen
        from handlers.menu import _bottom_reply_keyboard
        from database import Student
        ctx = None
        try:
            ctx = get_db_session()
            student = telegram_student_for(message.from_user.id)
            registered = bool(student and student.council_registered)
            rows = rows_for_screen('home' if registered else 'welcome')
            greeting = home_text(student.full_name) if registered else 'Регистрация отменена. Вы можете продолжить позже.'
            await message.answer(greeting, reply_markup=_bottom_reply_keyboard(rows))
        finally:
            if ctx:
                ctx.pop()


@router.callback_query(F.data.startswith('reg_edu:'))
async def choose_education_type(callback: types.CallbackQuery):
    tg_id=callback.from_user.id; value=callback.data.split(':',1)[1]
    if value not in {EducationType.COLLEGE.value,EducationType.INSTITUTE.value}: await callback.answer('Неизвестный тип',show_alert=True); return
    state=registration_data.get(tg_id)
    if not state: await callback.answer('Регистрация не запущена',show_alert=True); return
    state['education_type'] = value
    state['step'] = RegState.NAME
    label = 'Колледж' if value == 'college' else 'Институт'
    await callback.answer(label)
    await update_registration_prompt(
        callback.message,
        state,
        registration_screen(2, 'Укажите ФИО', f'Учебный контур: <b>{label}</b>.\nНапишите фамилию и имя; отчество можно добавить при наличии.'),
        reply_markup=cancel_markup(),
    )

@router.callback_query(F.data=='flow_cancel')
async def cancel_flow(callback: types.CallbackQuery):
    tg_id=callback.from_user.id; registration_data.pop(tg_id,None)
    await callback.answer('Действие отменено')
    from handlers.menu import home_inline
    ctx=None
    try:
        ctx=get_db_session(); student=telegram_student_for(tg_id); registered=bool(student and student.council_registered)
        await callback.message.edit_text('↩️ <b>Сценарий отменён</b>\n\nВернулись в главное меню.',reply_markup=home_inline(registered=registered),parse_mode='HTML')
    finally:
        if ctx: ctx.pop()

@router.message(F.text=='↩️ Отмена')
async def cancel_command(message: types.Message):
    registration_data.pop(message.from_user.id,None)
    await message.answer('↩️ Текущий сценарий отменён.')

@router.message(lambda m: m.from_user.id in registration_data)
async def handle_input(message: types.Message):
    tg_id=message.from_user.id; text=(message.text or '').strip(); ctx=None
    # Names, groups and phone numbers are personal data; delete input when possible.
    if tg_id in registration_data:
        await delete_input_message(message)
    try:
        ctx=get_db_session()
        sync_telegram_username(message.from_user)
        if tg_id in registration_data:
            state = registration_data[tg_id]
            step = state.get('step')
            if step == RegState.NAME:
                if len(text) > 255:
                    await update_registration_prompt(message, state, registration_screen(2, 'Укажите ФИО', 'Напишите фамилию и имя.', 'ФИО должно быть не длиннее 255 символов.'), cancel_markup()); return
                if len(text.split()) < 2:
                    await update_registration_prompt(message, state, registration_screen(2, 'Укажите ФИО', 'Напишите минимум фамилию и имя.', 'Недостаточно данных для ФИО.'), cancel_markup()); return
                from services.student_validation import student_duplicate_message
                existing = telegram_student_for(tg_id)
                duplicate_error = student_duplicate_message(text, None, check_name=True, check_phone=False,
                                                            exclude_id=existing.id if existing and not existing.council_registered else None)
                if duplicate_error:
                    await update_registration_prompt(message, state, registration_screen(2, 'Укажите ФИО', 'Проверьте написание и отправьте ФИО ещё раз.', duplicate_error), cancel_markup()); return
                state['full_name'] = ' '.join(text.split())
                state['step'] = RegState.GROUP
                label = 'Колледж' if state.get('education_type') == 'college' else 'Институт'
                await update_registration_prompt(message, state, registration_screen(3, 'Укажите учебную группу', f'✓ ФИО принято. Контур: <b>{label}</b>.\nНапример: ИС-21.'), cancel_markup()); return
            if step == RegState.GROUP:
                if len(text) > 50:
                    await update_registration_prompt(message, state, registration_screen(3, 'Укажите учебную группу', 'Название группы должно быть от 2 до 50 символов.', 'Слишком длинное название группы.'), cancel_markup()); return
                if len(text) < 2:
                    await update_registration_prompt(message, state, registration_screen(3, 'Укажите учебную группу', 'Напишите полное обозначение группы.', 'Группа слишком короткая.'), cancel_markup()); return
                state['group'] = text
                state['step'] = RegState.PHONE
                await update_registration_prompt(message, state, registration_screen(4, 'Укажите контактный телефон', '✓ ФИО и группа сохранены.\nВведите номер телефона, по которому с вами можно связаться.'), cancel_markup()); return
            if step == RegState.PHONE:
                if len(text) > 30:
                    await update_registration_prompt(message, state, registration_screen(4, 'Укажите контактный телефон', 'Напишите номер телефона длиной не более 30 символов.', 'Номер телефона слишком длинный.'), cancel_markup()); return
                if sum(ch.isdigit() for ch in text) < 5:
                    await update_registration_prompt(message, state, registration_screen(4, 'Укажите контактный телефон', 'Пример: +371 2000 0000.', 'В номере должно быть не менее 5 цифр.'), cancel_markup()); return
                data = registration_data[tg_id]
                try:
                    from services.applications import register_student_with_council
                    student, council, error_message = register_student_with_council(
                        tg_id=tg_id, full_name=data['full_name'], group=data['group'],
                        phone=text, education_type=data['education_type'],
                        telegram_username=message.from_user.username, source='telegram'
                    )
                except Exception:
                    logger.exception('Student registration failed')
                    await update_registration_prompt(message, state, registration_screen(4, 'Укажите контактный телефон', 'Попробуйте отправить номер ещё раз. Данные предыдущих шагов сохранены.', 'Не удалось завершить регистрацию из-за технической ошибки.'), cancel_markup())
                    return
                if error_message:
                    hint = 'Этот номер уже используется. Укажите другой контактный телефон.' if 'телефон' in error_message.lower() else 'Проверьте введённые данные и отправьте номер ещё раз.'
                    await update_registration_prompt(message, state, registration_screen(4, 'Укажите контактный телефон', hint, error_message), cancel_markup())
                    return
                label = 'Колледж' if student.education_type == 'college' else 'Институт'
                from handlers.menu import home_reply_keyboard
                success_text = (
                    '✨ <b>Профиль создан</b>\n'
                    '<i>Регистрация успешно завершена</i>\n\n'
                    f'Номер профиля: <b>#{student.id}</b>\n'
                    f'Учебный контур: <b>{label}</b>\n'
                    f'Группа: <b>{html.escape(student.group or "—")}</b>\n\n'
                    'Следующий шаг — выберите направление и отправьте заявление.\n'
                    '<i>Кабинет и данные доступны в Telegram, VK и MAX после привязки аккаунтов.</i>'
                )
                await update_registration_prompt(message, state, success_text, reply_markup=home_reply_keyboard(True))
                registration_data.pop(tg_id, None)
                logger.info('Student profile registration completed (education=%s)', label)
                return

    except Exception:
        if ctx:
            try: db.session.rollback()
            except Exception: pass
        logger.exception('Flow input failed'); await message.answer('⚠️ Произошла техническая ошибка. Попробуйте повторить действие.')
    finally:
        if ctx: ctx.pop()
