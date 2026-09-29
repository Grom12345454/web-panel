import html
import json
import logging
from datetime import datetime
import requests
from database import db, Student, Direction, StudentLeadership, DirectionStatus, EducationType, student_directions
from config import settings

logger=logging.getLogger(__name__)

def telegram_api(method,payload,attempts=3,timeout=10):
    if not settings.BOT_TOKEN: return None
    url=f"https://api.telegram.org/bot{settings.BOT_TOKEN}/{method}"
    for attempt in range(attempts):
        try:
            r=requests.post(url,json=payload,timeout=timeout); data=r.json()
            if data.get('ok'): return data
            if r.status_code==429 and attempt<attempts-1:
                import time; time.sleep(min(int((data.get('parameters') or {}).get('retry_after',1)),5)); continue
            return None
        except Exception as exc:
            logger.warning('Telegram %s error: %s',method,exc)
    return None

def education_label(value): return 'Колледж' if value=='college' else 'Институт' if value=='institute' else 'Все'

def leader_records_for(direction_id, education_type):
    rows=StudentLeadership.query.filter_by(direction_id=direction_id).all()
    return [r for r in rows if r.student and r.student.tg_id and r.student.tg_id>0 and r.education_type in {education_type,'all'}]

def notify_leaders_about_application(student, direction):
    if not student or not direction: return 0
    leaders=leader_records_for(direction.id,student.education_type)
    sent=0
    markup={'inline_keyboard':[[
        {'text':'✅ Одобрить','callback_data':f'app:approve:{student.id}:{direction.id}'},
        {'text':'❌ Отклонить','callback_data':f'app:reject:{student.id}:{direction.id}'},
    ]]}
    text=(f"📥 <b>Новая заявка</b>\n\n👤 {html.escape(student.full_name)}\n"
          f"🎓 Контур: <b>{education_label(student.education_type)}</b>\n"
          f"👥 Группа: {html.escape(student.group or '—')}\n📞 {html.escape(student.phone or '—')}\n"
          f"📌 Направление: <b>{html.escape((direction.icon or '✦')+' '+direction.name)}</b>\n\nВыберите действие:")
    for leader in leaders:
        if telegram_api('sendMessage',{'chat_id':int(leader.student.tg_id),'text':text,'parse_mode':'HTML','reply_markup':markup}): sent+=1
    return sent

def get_application(student_id,direction_id):
    return db.session.execute(student_directions.select().where((student_directions.c.student_id==student_id)&(student_directions.c.direction_id==direction_id))).fetchone()

def _active_direction_ids(student_id):
    return {r.direction_id for r in db.session.execute(student_directions.select().where((student_directions.c.student_id==student_id)&(student_directions.c.status==DirectionStatus.ACTIVE.value))).fetchall()}

def create_join_request_links(direction):
    from services.telegram import create_direction_invite_links
    return create_direction_invite_links(direction.id)

def notify_approval(student,direction,send_invites=True):
    from services.telegram import send_direction_invites
    payload={'direction':f"{direction.icon or '✦'} {direction.name}"}
    # Direct send instead of queue so the response reaches Telegram immediately.
    text=f"✅ <b>Заявка одобрена!</b>\n\nВы приняты в направление:\n<b>{html.escape(payload['direction'])}</b>"
    if student.tg_id and student.tg_id>0: telegram_api('sendMessage',{'chat_id':int(student.tg_id),'text':text,'parse_mode':'HTML'})
    return send_direction_invites(student,direction) if send_invites else 0

def set_application_status(student_id,direction_id,new_status,actor_tg_id=None):
    link=get_application(student_id,direction_id)
    student=Student.query.get(student_id); direction=Direction.query.get(direction_id)
    if not link or not student or not direction: return False,'Заявка не найдена.',0
    if link.status not in {DirectionStatus.PENDING.value, DirectionStatus.INTERVIEW.value} and new_status in {DirectionStatus.APPROVED.value, DirectionStatus.REJECTED.value}:
        return False,'Заявка уже обработана.',0
    if actor_tg_id:
        allowed=any(x.student and x.student.tg_id==actor_tg_id and x.direction_id==direction_id and x.education_type in {student.education_type,'all'} for x in StudentLeadership.query.all())
        if not allowed: return False,'Нет прав для этого направления.',0
    db.session.execute(student_directions.update().where((student_directions.c.student_id==student_id)&(student_directions.c.direction_id==direction_id)).values(status=new_status))
    db.session.commit()
    invite_count=0
    if new_status==DirectionStatus.APPROVED.value:
        invite_count=notify_approval(student,direction,True)
    elif new_status==DirectionStatus.REJECTED.value:
        from services.telegram import remove_student_from_direction_chats
        remove_student_from_direction_chats(student,direction)
        if student.tg_id and student.tg_id>0: telegram_api('sendMessage',{'chat_id':int(student.tg_id),'text':f"❌ <b>Заявка отклонена</b>\n\nНаправление: <b>{html.escape(direction.name)}</b>",'parse_mode':'HTML'})
    return True,'Готово',invite_count
