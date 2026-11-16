"""Telegram private account management: VK/MAX pairing and safe disconnection."""
import html

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, ForceReply
from services.multi_messenger import (
    student_for, linked_account_status, generate_link_code, redeem_link_code, unlink_account,
    pending_link_requests, review_link_request,
)

router = Router()


def app_context():
    from bot import app_instance
    if not app_instance:
        raise RuntimeError('Flask not ready')
    return app_instance.app_context()


def account_keyboard(status, pending=None):
    rows = []
    for platform, label in [('vk', 'ВКонтакте'), ('max', 'MAX')]:
        if status[platform]['connected']:
            rows.append([InlineKeyboardButton(text=f'✓ {label} · отвязать', callback_data=f'account_unlink_{platform}')])
        else:
            rows.append([InlineKeyboardButton(text=f'➕ Подключить {label}', callback_data=f'account_code_{platform}')])
    for item in (pending or []):
        rows.append([
            InlineKeyboardButton(text=f"✅ Подтвердить #{item['id']}", callback_data=f"pair:approve:{item['id']}"),
            InlineKeyboardButton(text=f"❌ Отклонить #{item['id']}", callback_data=f"pair:deny:{item['id']}"),
        ])
    rows.append([InlineKeyboardButton(text='↻ Обновить статус', callback_data='account_status')])
    rows.append([InlineKeyboardButton(text='‹ В меню', callback_data='menu_home')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def account_text(status, pending=None):
    return ('🔐 <b>Привязанные аккаунты</b>\n\n'
            'Telegram · ' + ('✅ подключён' if status['telegram']['connected'] else 'не подключён') + '\n'
            'ВКонтакте · ' + ('✅ подключён' if status['vk']['connected'] else 'не подключён') + '\n'
            'MAX · ' + ('✅ подключён' if status['max']['connected'] else 'не подключён') + '\n\n'
            'Новый аккаунт можно указать по VK ID или username Telegram/MAX. '
            'Новый аккаунт НЕ подключается автоматически после ввода кода. '
            'Каждый запрос требует вашего согласия. Если код вводили не вы — отклоните.\n\n'
            + ('Ожидают решения: ' + ', '.join('#'+str(item['id'])+' '+item['platform']+' '+item['handle'] for item in pending)
               if pending else 'Ожидающих запросов нет.'))


@router.message(Command('accounts', 'account'))
async def list_accounts(message: Message):
    if message.chat.type != 'private' or not message.from_user:
        return
    with app_context():
        student = student_for('telegram', message.from_user.id)
        if not student:
            await message.answer('Сначала создайте профиль в Telegram или привяжите его командой /link КОД.')
            return
        status = linked_account_status(student)
        pending = pending_link_requests(student)
    await message.answer(account_text(status, pending), reply_markup=account_keyboard(status, pending), parse_mode='HTML')


@router.callback_query(F.data == 'account_status')
async def refresh_accounts(callback: CallbackQuery):
    with app_context():
        student = student_for('telegram', callback.from_user.id)
        if not student:
            await callback.answer('Профиль не найден.', show_alert=True)
            return
        status = linked_account_status(student)
        pending = pending_link_requests(student)
    await callback.answer()
    await callback.message.edit_text(account_text(status, pending), reply_markup=account_keyboard(status, pending), parse_mode='HTML')


@router.message(Command('code'))
async def create_pair_code(message: Message):
    if message.chat.type != 'private' or not message.from_user:
        return
    arguments = (message.text or '').partition(' ')[2].strip()
    platform, _, handle = arguments.partition(' ')
    platform = platform.lower()
    if platform not in {'vk', 'max'}:
        await message.answer('Формат: /code vk 123456789 или /code max @username. Также есть кнопки в /accounts.')
        return
    with app_context():
        student = student_for('telegram', message.from_user.id)
        if not student:
            response = 'Сначала создайте профиль в Telegram или используйте /link КОД из VK/MAX.'
        else:
            try:
                code = generate_link_code(student, platform, handle.strip() or None)
                response = (f'🔐 Код для {"ВКонтакте" if platform == "vk" else "MAX"}: <code>{code}</code>\n'
                            'Срок: 10 минут. Отправьте <code>/link КОД</code> личным сообщением боту '
                            'на выбранной платформе. Не пересылайте код посторонним.')
            except ValueError as exc:
                response = html.escape(str(exc))
    await message.answer(response, parse_mode='HTML', protect_content=True)


@router.callback_query(F.data.in_({'account_code_vk', 'account_code_max'}))
async def make_code_from_button(callback: CallbackQuery):
    platform = callback.data.rsplit('_', 1)[-1]
    with app_context():
        student = student_for('telegram', callback.from_user.id)
        if not student:
            await callback.answer('Профиль не найден.', show_alert=True)
            return
    label = 'VK ID, например 123456789' if platform == 'vk' else 'username MAX, например @username'
    await callback.answer()
    await callback.message.answer(
        f'🔗 Привязка {platform.upper()}\n\nУкажите свой {label}. '
        'Затем подтвердите запрос в личных сообщениях соответствующего бота.',
        reply_markup=ForceReply(selective=True, input_field_placeholder=label),
    )


@router.message(F.reply_to_message & F.reply_to_message.text.startswith('🔗 Привязка '))
async def account_handle_reply(message: Message):
    if message.chat.type != 'private' or not message.from_user:
        return
    prompt = (message.reply_to_message.text or '')
    platform = 'vk' if prompt.startswith('🔗 Привязка VK') else 'max'
    with app_context():
        student = student_for('telegram', message.from_user.id)
        if not student:
            response = 'Профиль не найден. Сначала зарегистрируйтесь.'
        else:
            try:
                code = generate_link_code(student, platform, (message.text or '').strip())
                response = (f'Код подтверждения: <code>{code}</code>\n'
                            'Отправьте <code>/link ' + code + '</code> в личных сообщениях '
                            'официального бота нужной платформы. Код действует 10 минут. '
                            'Никому не сообщайте код.')
            except ValueError as exc:
                response = html.escape(str(exc))
    await message.answer(response, parse_mode='HTML', protect_content=True)


@router.callback_query(F.data.in_({'account_unlink_vk', 'account_unlink_max'}))
async def confirm_account_unlink(callback: CallbackQuery):
    platform = callback.data.rsplit('_', 1)[-1]
    label = 'ВКонтакте' if platform == 'vk' else 'MAX'
    await callback.answer()
    await callback.message.answer(
        f'Отключить {label}? Доступ к профилю через этот мессенджер прекратится. '
        'Заявки и направления сохранятся.',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='Да, отвязать', callback_data=f'account_confirm_{platform}')],
            [InlineKeyboardButton(text='Отмена', callback_data='account_status')],
        ]),
    )


@router.callback_query(F.data.in_({'account_confirm_vk', 'account_confirm_max'}))
async def perform_account_unlink(callback: CallbackQuery):
    platform = callback.data.rsplit('_', 1)[-1]
    with app_context():
        student = student_for('telegram', callback.from_user.id)
        if not student:
            await callback.answer('Профиль не найден.', show_alert=True)
            return
        try:
            message = unlink_account(student, platform, current_platform='telegram')
            status = linked_account_status(student)
            pending = pending_link_requests(student)
        except ValueError as exc:
            await callback.answer(str(exc), show_alert=True)
            return
    await callback.answer('Аккаунт отключён.')
    await callback.message.edit_text(account_text(status, pending) + '\n\n' + html.escape(message),
                                     reply_markup=account_keyboard(status, pending), parse_mode='HTML')


@router.message(Command('link'))
async def link_messenger(message: Message):
    if message.chat.type != 'private' or not message.from_user:
        return
    code = (message.text or '').partition(' ')[2].strip()
    if not code:
        await message.answer('🔐 Введите код привязки (20 символов), полученный из вашего профиля:',
                             reply_markup=ForceReply(selective=True, input_field_placeholder='Одноразовый код'))
        return
    with app_context():
        response = redeem_link_code('telegram', message.from_user.id, code, username=message.from_user.username)
    await message.answer(response, protect_content=True)


@router.message(F.reply_to_message & (F.reply_to_message.text.startswith('🔐 Введите код привязки') | F.reply_to_message.text.startswith('🔐 Уже есть аккаунт')))
async def link_code_reply(message: Message):
    if message.chat.type != 'private' or not message.from_user:
        return
    with app_context():
        response = redeem_link_code('telegram', message.from_user.id, (message.text or '').strip(),
                                    username=message.from_user.username)
    await message.answer(response, protect_content=True)


@router.message(Command('pairapprove', 'pairdeny'))
async def pairing_decision_command(message: Message):
    if message.chat.type != 'private' or not message.from_user:
        return
    action, _, value = (message.text or '').partition(' ')
    with app_context():
        owner = student_for('telegram', message.from_user.id)
        if not owner or not value.strip().isdigit():
            response = 'Нужен ваш профиль и номер запроса: /pairapprove 12 либо /pairdeny 12.'
        else:
            try:
                response = review_link_request(owner, int(value.strip()), action.split('@')[0] == '/pairapprove')
            except ValueError as exc:
                response = str(exc)
    await message.answer(response)


@router.callback_query(F.data.startswith('pair:'))
async def pairing_decision_callback(callback: CallbackQuery):
    if not callback.from_user or not callback.message or callback.message.chat.type != 'private':
        return
    pieces = (callback.data or '').split(':')
    if len(pieces) != 3 or pieces[1] not in {'approve', 'deny'} or not pieces[2].isdigit():
        await callback.answer('Некорректный запрос', show_alert=True)
        return
    with app_context():
        owner = student_for('telegram', callback.from_user.id)
        if not owner:
            response = 'Запрос может обработать только владелец исходного профиля.'
        else:
            try:
                response = review_link_request(owner, int(pieces[2]), pieces[1] == 'approve')
            except ValueError as exc:
                response = str(exc)
    await callback.answer(response[:190], show_alert=True)
    await callback.message.answer(response)
