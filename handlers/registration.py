import html
import json
import logging
import time
from datetime import datetime
from aiogram import Router, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database import db, Student, Direction, student_directions, StudentLeadership, DirectionStatus, EducationType
from config import RegState, AddState

logger=logging.getLogger(__name__)
router=Router(); registration_data={}; adding_data={}; removing_data={}

def get_db_session():
    from bot import app_instance
    if not app_instance: raise RuntimeError('Flask app не инициализирован')
    ctx=app_instance.app_context(); ctx.push(); return ctx

def cancel_markup(): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='✕ Отменить',callback_data='flow_cancel')]])

def education_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🏫  Колледж',callback_data='reg_edu:college')],
        [InlineKeyboardButton(text='🎓  Институт',callback_data='reg_edu:institute')],
        [InlineKeyboardButton(text='✕  Отмена',callback_data='flow_cancel')],
    ])

def check_leadership_rights(tg_id):
    ctx=None
    try:
        ctx=get_db_session(); student=Student.query.filter_by(tg_id=tg_id).first()
        if not student: return False,None,None
        rows=StudentLeadership.query.filter_by(student_id=student.id).all()
        if rows:
            row=rows[0]; return True,Direction.query.get(row.direction_id),row
        return False,None,None
    except Exception:
        logger.exception('Leadership rights check failed'); return False,None,None
    finally:
        if ctx: ctx.pop()

async def start_registration_flow(message: types.Message,tg_id=None,edit=False):
    ctx=None
    try:
        ctx=get_db_session(); tg_id=tg_id or message.from_user.id
        if Student.query.filter_by(tg_id=tg_id).first():
            await message.answer('ℹ️ <b>Профиль уже создан</b>\n\nИспользуйте «Подать заявку», чтобы выбрать направление.',parse_mode='HTML'); return
        registration_data[tg_id]={'step':RegState.EDUCATION_TYPE}
        text='📝 <b>Регистрация участника</b>\n\nШаг 1 из 4 · Выберите ваш учебный контур:'
        if edit: await message.edit_text(text,reply_markup=education_keyboard(),parse_mode='HTML')
        else: await message.answer(text,reply_markup=education_keyboard(),parse_mode='HTML')
    finally:
        if ctx: ctx.pop()

@router.message(F.text=='📝 Подать заявку')
async def start_registration(message: types.Message):
    ctx=None
    try:
        ctx=get_db_session(); existing=Student.query.filter_by(tg_id=message.from_user.id).first()
    finally:
        if ctx: ctx.pop()
    if existing:
        await message.answer('ℹ️ <b>Профиль уже создан.</b>\n\nОткройте «Подать заявку» в главном меню.',parse_mode='HTML'); return
    await start_registration_flow(message)

@router.callback_query(F.data.startswith('reg_edu:'))
async def choose_education_type(callback: types.CallbackQuery):
    tg_id=callback.from_user.id; value=callback.data.split(':',1)[1]
    if value not in {EducationType.COLLEGE.value,EducationType.INSTITUTE.value}: await callback.answer('Неизвестный тип',show_alert=True); return
    state=registration_data.get(tg_id)
    if not state: await callback.answer('Регистрация не запущена',show_alert=True); return
    state['education_type']=value; state['step']=RegState.NAME
    label='Колледж' if value=='college' else 'Институт'
    await callback.answer(label)
    await callback.message.edit_text(f'✅ <b>{label}</b> выбрано.\n\nШаг 2 из 4 · Укажите <b>ФИО</b>.',reply_markup=cancel_markup(),parse_mode='HTML')

@router.callback_query(F.data=='flow_cancel')
async def cancel_flow(callback: types.CallbackQuery):
    tg_id=callback.from_user.id; registration_data.pop(tg_id,None); adding_data.pop(tg_id,None); removing_data.pop(tg_id,None)
    await callback.answer('Действие отменено')
    from handlers.menu import home_inline,is_any_leader
    ctx=None
    try:
        ctx=get_db_session(); student=Student.query.filter_by(tg_id=tg_id).first(); registered=student is not None
        await callback.message.edit_text('↩️ <b>Сценарий отменён</b>\n\nВернулись в главное меню.',reply_markup=home_inline(is_leader=is_any_leader(tg_id) if registered else False,registered=registered),parse_mode='HTML')
    finally:
        if ctx: ctx.pop()

@router.message(F.text=='↩️ Отмена')
async def cancel_command(message: types.Message):
    registration_data.pop(message.from_user.id,None); adding_data.pop(message.from_user.id,None); removing_data.pop(message.from_user.id,None)
    await message.answer('↩️ Текущий сценарий отменён.')

@router.message(lambda m: m.from_user.id in registration_data or m.from_user.id in adding_data or m.from_user.id in removing_data)
async def handle_input(message: types.Message):
    tg_id=message.from_user.id; text=(message.text or '').strip(); ctx=None
    try:
        if tg_id in registration_data:
            state=registration_data[tg_id]; step=state.get('step')
            if step==RegState.NAME:
                if len(text.split())<2: await message.answer('⚠️ Укажите минимум имя и фамилию.'); return
                state['full_name']=text; state['step']=RegState.GROUP
                await message.answer('✅ ФИО сохранено.\n\nШаг 3 из 4 · Укажите <b>учебную группу</b>.',reply_markup=cancel_markup(),parse_mode='HTML'); return
            if step==RegState.GROUP:
                if len(text)<2: await message.answer('⚠️ Укажите корректную учебную группу.'); return
                state['group']=text; state['step']=RegState.PHONE
                await message.answer('✅ Группа сохранена.\n\nШаг 4 из 4 · Отправьте <b>номер телефона</b>.',reply_markup=cancel_markup(),parse_mode='HTML'); return
            if step==RegState.PHONE:
                if sum(ch.isdigit() for ch in text)<5: await message.answer('⚠️ В номере должно быть не меньше 5 цифр.'); return
                ctx=get_db_session(); data=registration_data[tg_id]
                student=Student(tg_id=tg_id,full_name=data['full_name'],group=data['group'],phone=text,education_type=data['education_type'])
                db.session.add(student); db.session.commit()
                council=Direction.query.filter_by(code='STUDCOUNCIL').first()
                buttons=[]
                if council: buttons.append([InlineKeyboardButton(text=f'{council.icon or "✦"}  {council.name}',callback_data=f'dir_{council.id}')])
                buttons.append([InlineKeyboardButton(text='‹  В главное меню',callback_data='menu_home')])
                label='Колледж' if student.education_type=='college' else 'Институт'
                await message.answer(f'✅ <b>Профиль создан · #{student.id}</b>\n\nКонтур: <b>{label}</b>\n\nПервая заявка доступна только в <b>Студсовет</b>.',reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),parse_mode='HTML')
                registration_data.pop(tg_id,None); logger.info('Registered student #%s (%s, %s)',student.id,student.full_name,label); return

        if tg_id in adding_data:
            state=adding_data[tg_id]; step=state.get('step')
            if step==AddState.NAME:
                if len(text.split())<2: await message.answer('⚠️ Укажите Фамилию и Имя.'); return
                state['full_name']=text; state['step']=AddState.GROUP; await message.answer('✅ ФИО принято.\n\nУкажите <b>группу</b>.',reply_markup=cancel_markup(),parse_mode='HTML'); return
            if step==AddState.GROUP:
                state['group']=text; state['step']=AddState.PHONE; await message.answer('✅ Группа принята.\n\nУкажите <b>телефон</b>.',reply_markup=cancel_markup(),parse_mode='HTML'); return
            if step==AddState.PHONE:
                if sum(ch.isdigit() for ch in text)<5: await message.answer('⚠️ Введите корректный номер телефона.'); return
                ctx=get_db_session(); data=adding_data[tg_id]; direction_id=data['direction_id']
                existing=Student.query.filter_by(full_name=data['full_name'],group=data['group']).first()
                if existing:
                    student=existing; student.phone=text
                    link=db.session.execute(student_directions.select().where((student_directions.c.student_id==student.id)&(student_directions.c.direction_id==direction_id))).fetchone()
                    if link: await message.answer('⚠️ Этот студент уже состоит в направлении.'); adding_data.pop(tg_id,None); return
                else:
                    student=Student(tg_id=-time.time_ns(),full_name=data['full_name'],group=data['group'],phone=text,education_type=data.get('education_type','institute'))
                    db.session.add(student); db.session.flush()
                db.session.execute(student_directions.insert().values(student_id=student.id,direction_id=direction_id,status=DirectionStatus.ACTIVE.value,extra_data=json.dumps({'added_by':tg_id,'date':datetime.utcnow().isoformat()})))
                db.session.commit(); await message.answer(f'✅ <b>Студент добавлен</b>\n\n👤 {html.escape(student.full_name)}\n🎓 {html.escape(student.group or "—")}\n📌 {html.escape(data["direction_name"])}\n✦ Активен',parse_mode='HTML'); adding_data.pop(tg_id,None); return

        if tg_id in removing_data and removing_data[tg_id].get('step')=='remove_name':
            ctx=get_db_session(); data=removing_data[tg_id]; student=Student.query.filter_by(full_name=text).first()
            if not student: await message.answer('⚠️ Студент с таким ФИО не найден.'); removing_data.pop(tg_id,None); return
            link=db.session.execute(student_directions.select().where((student_directions.c.student_id==student.id)&(student_directions.c.direction_id==data['direction_id']))).fetchone()
            if not link: await message.answer('⚠️ Студент не состоит в выбранном направлении.'); removing_data.pop(tg_id,None); return
            db.session.execute(student_directions.delete().where((student_directions.c.student_id==student.id)&(student_directions.c.direction_id==data['direction_id']))); db.session.commit()
            await message.answer(f'✅ <b>Студент удалён из направления</b>\n\n👤 {html.escape(student.full_name)}',parse_mode='HTML'); removing_data.pop(tg_id,None)
    except Exception:
        if ctx:
            try: db.session.rollback()
            except Exception: pass
        logger.exception('Flow input failed'); await message.answer('⚠️ Произошла техническая ошибка. Попробуйте повторить действие.')
    finally:
        if ctx: ctx.pop()

@router.message(F.text=='➕ Добавить студента')
async def start_add_student(message: types.Message,tg_id=None):
    ctx=None
    try:
        ctx=get_db_session(); tg_id=tg_id or message.from_user.id; ok,direction,lead=check_leadership_rights(tg_id)
        if not ok: await message.answer('⚠️ Доступ только назначенному руководству.'); return
        leader_student=Student.query.filter_by(tg_id=tg_id).first()
        adding_data[tg_id]={'step':AddState.NAME,'direction_id':direction.id,'direction_name':direction.name,'education_type':leader_student.education_type if leader_student else 'institute'}
        await message.answer(f'➕ <b>Добавление в «{html.escape(direction.name)}»</b>\n\nОтправьте <b>ФИО</b> студента.',reply_markup=cancel_markup(),parse_mode='HTML')
    finally:
        if ctx: ctx.pop()

@router.message(F.text=='🗑️ Удалить студента')
async def start_remove_student(message: types.Message,tg_id=None):
    ctx=None
    try:
        ctx=get_db_session(); tg_id=tg_id or message.from_user.id; ok,direction,_=check_leadership_rights(tg_id)
        if not ok: await message.answer('⚠️ У вас нет прав для этого действия.'); return
        removing_data[tg_id]={'step':'remove_name','direction_id':direction.id}
        await message.answer(f'🗑 <b>Удаление из «{html.escape(direction.name)}»</b>\n\nОтправьте точное <b>ФИО</b> студента.',reply_markup=cancel_markup(),parse_mode='HTML')
    finally:
        if ctx: ctx.pop()
