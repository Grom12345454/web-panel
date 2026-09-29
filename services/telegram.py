import html, logging, time, requests
from config import settings
from database import db, DirectionChat, StudentInviteLink
logger=logging.getLogger(__name__)

def telegram_api(method,payload,attempts=3,timeout=10):
    if not settings.BOT_TOKEN: return None
    url=f"https://api.telegram.org/bot{settings.BOT_TOKEN}/{method}"
    last=None
    for a in range(attempts):
        try:
            r=requests.post(url,json=payload,timeout=timeout)
            data=r.json(); last=data
            if data.get('ok'): return data
            if r.status_code==429 and a<attempts-1:
                time.sleep(min(max(int((data.get('parameters') or {}).get('retry_after',1)),1),5)); continue
            return None
        except requests.RequestException as e:
            if a<attempts-1: time.sleep(a+1)
            else: logger.error('Telegram network error: %s',e)
    return last if last and last.get('ok') else None

def resolve_chat_id(chat_id):
    raw=str(chat_id or '').strip()
    if not raw: return None
    if not raw.startswith('@'): return raw
    data=telegram_api('getChat',{'chat_id':raw},attempts=2)
    return str((data or {}).get('result',{}).get('id')) if data else None

def send_tg(chat_id,text,reply_markup=None):
    p={'chat_id':str(chat_id),'text':text,'parse_mode':'HTML','disable_web_page_preview':True}
    if reply_markup: p['reply_markup']=reply_markup
    return bool(telegram_api('sendMessage',p))

def send_direction_chat(direction_id,text,reply_markup=None):
    count=0
    chats=DirectionChat.query.filter_by(direction_id=direction_id,is_active=True).all()
    for chat in chats:
        resolved=resolve_chat_id(chat.chat_id)
        if resolved and send_tg(resolved,text,reply_markup): count+=1
    return count

def create_direction_invite_links(direction_id,student_name=None):
    links=[]
    chats=DirectionChat.query.filter_by(direction_id=direction_id,is_active=True).all()
    for chat in chats:
        resolved=resolve_chat_id(chat.chat_id)
        if not resolved: continue
        data=telegram_api('createChatInviteLink',{'chat_id':resolved,'name':f'University Control • {student_name or "Студент"}'[:32],'creates_join_request':True})
        link=(data or {}).get('result',{}).get('invite_link')
        if link: links.append({'title':chat.title or resolved,'link':link,'chat_id':resolved})
    return links

def send_direction_invites(student,direction):
    if not student or not student.tg_id or student.tg_id<=0: return 0
    links=create_direction_invite_links(direction.id,student.full_name)
    sent=0
    header=f"🔗 <b>Чаты направления «{html.escape(direction.name)}»</b>\n\n"
    for item in links:
        existing=StudentInviteLink.query.filter_by(student_id=student.id,direction_id=direction.id,chat_id=str(item['chat_id'])).first()
        if existing:
            existing.title=item['title']; existing.invite_link=item['link']
        else:
            db.session.add(StudentInviteLink(student_id=student.id,direction_id=direction.id,chat_id=str(item['chat_id']),title=item['title'],invite_link=item['link']))
        msg=header+f"<b>{html.escape(item['title'])}</b>\n<a href=\"{html.escape(item['link'],quote=True)}\">Открыть приглашение</a>"
        if send_tg(student.tg_id,msg): sent+=1
    db.session.commit()
    return sent

def remove_student_from_direction_chats(student,direction):
    if not student or not student.tg_id or student.tg_id<=0: return 0
    count=0
    for chat in DirectionChat.query.filter_by(direction_id=direction.id,is_active=True).all():
        resolved=resolve_chat_id(chat.chat_id)
        if not resolved: continue
        if telegram_api('banChatMember',{'chat_id':resolved,'user_id':int(student.tg_id),'revoke_messages':False}):
            telegram_api('unbanChatMember',{'chat_id':resolved,'user_id':int(student.tg_id),'only_if_banned':True}); count+=1
    return count
