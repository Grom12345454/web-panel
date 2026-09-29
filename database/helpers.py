import sqlite3
from datetime import datetime
from pathlib import Path
from flask import current_app
from config import settings
from .base import db, hash_password
from .core import Direction, DirectionChat, Student, User, StudentLeadership, TelegramChatCandidate, DirectionQuestion
from .events import EventQuota, EventDay, QuotaDirection, EventQuotaChat, DayParticipation
from .stats import StudentQuotaStat
from .system import NotificationTemplate


def get_quota_direction_ids(quota_id):
    return [r[0] for r in db.session.execute(db.select(QuotaDirection.direction_id).where(QuotaDirection.quota_id == quota_id)).all() if r[0] is not None]

def get_quota_directions(quota_id):
    ids = get_quota_direction_ids(quota_id)
    if not ids: return []
    rows = Direction.query.filter(Direction.id.in_(ids)).all(); by_id={d.id:d for d in rows}
    return [by_id[i] for i in ids if i in by_id]

def set_quota_directions(quota_id, direction_ids):
    QuotaDirection.query.filter_by(quota_id=quota_id).delete(synchronize_session=False)
    clean=[]
    for raw in direction_ids:
        try: v=int(raw)
        except (TypeError,ValueError): continue
        if v>0 and v not in clean: clean.append(v)
    if clean: db.session.add_all([QuotaDirection(quota_id=quota_id,direction_id=v) for v in clean])

def get_quota_chat_targets(quota_id): return EventQuotaChat.query.filter_by(quota_id=quota_id).all()

def set_quota_chat_targets(quota_id, targets):
    EventQuotaChat.query.filter_by(quota_id=quota_id).delete(synchronize_session=False)
    seen=set(); rows=[]
    for did,cid in targets:
        try: did=int(did)
        except (TypeError,ValueError): continue
        cid=str(cid or '').strip(); key=(did,cid)
        if did>0 and cid and key not in seen:
            seen.add(key); rows.append(EventQuotaChat(quota_id=quota_id,direction_id=did,chat_id=cid))
    if rows: db.session.add_all(rows)

def get_direction_quota_ids(direction_id):
    return [r[0] for r in db.session.execute(db.select(QuotaDirection.quota_id).where(QuotaDirection.direction_id == direction_id)).all() if r[0] is not None]

def get_direction_quotas(direction_id):
    ids=get_direction_quota_ids(direction_id)
    if not ids: return []
    rows=EventQuota.query.filter(EventQuota.id.in_(ids)).all(); by_id={q.id:q for q in rows}
    return [by_id[i] for i in ids if i in by_id]

def _sqlite_table_exists(path, table_name):
    if not path or not Path(path).exists(): return False
    with sqlite3.connect(path) as conn:
        return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table_name,)).fetchone() is not None

def _columns(conn, table): return [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]

def ensure_column(path, table, column, ddl):
    if not Path(path).exists() or not _sqlite_table_exists(path, table): return
    with sqlite3.connect(path) as conn:
        cols=_columns(conn,table)
        if column not in cols:
            conn.execute(f'ALTER TABLE "{table}" ADD COLUMN {column} {ddl}')
            conn.commit()

def migrate_schema():
    ensure_column(settings.PEOPLE_DATABASE_PATH,"students","education_type","VARCHAR(20) NOT NULL DEFAULT 'institute'")
    ensure_column(settings.PEOPLE_DATABASE_PATH,"users","assigned_education_type","VARCHAR(20) NOT NULL DEFAULT 'all'")
    ensure_column(settings.PEOPLE_DATABASE_PATH,"student_leadership","education_type","VARCHAR(20) NOT NULL DEFAULT 'institute'")
    ensure_column(settings.PEOPLE_DATABASE_PATH,"directions","education_scope","VARCHAR(20) NOT NULL DEFAULT 'both'")

def _copy_table(legacy_conn,target_path,table_name,columns):
    if not _sqlite_table_exists(settings.LEGACY_DATABASE_PATH,table_name): return 0
    with sqlite3.connect(target_path) as target:
        rows=legacy_conn.execute(f'SELECT {", ".join(columns)} FROM {table_name}').fetchall()
        if not rows: return 0
        ph=','.join('?' for _ in columns)
        target.executemany(f'INSERT OR IGNORE INTO {table_name} ({", ".join(columns)}) VALUES ({ph})',rows)
        target.commit(); return len(rows)

def migrate_legacy_database():
    legacy=settings.LEGACY_DATABASE_PATH
    if not legacy or not Path(legacy).exists(): return
    marker=settings.DATA_DIR/'.split_migration_v4'
    if marker.exists(): return
    try:
        with sqlite3.connect(legacy) as conn:
            core_tables={
                'directions':['id','name','code','icon','description','color'],
                'students':['id','tg_id','full_name','group','phone','email','created_at'],
                'users':['id','email','password_hash','role','tg_id','assigned_direction_id'],
                'student_directions':['student_id','direction_id','joined_at','extra_data','status'],
                'direction_questions':['id','direction_id','question_text','is_required','sort_order'],
                'student_leadership':['id','student_id','direction_id','position_name'],
                'direction_chats':['id','direction_id','chat_id','title','username','is_active','created_at','last_test_at'],
            }
            for t,c in core_tables.items():
                _copy_table(conn,settings.PEOPLE_DATABASE_PATH,t,c)
            for t,c in {
                'event_quotas':['id','event_title','event_description','location','time_range','dress_code','functionality','total_places','is_closed','closing_reason','closed_at'],
                'event_days':['id','quota_id','date','daily_places'],
                'day_participations':['id','student_id','day_id','status'],
                'quota_directions':['quota_id','direction_id'],
            }.items(): _copy_table(conn,settings.EVENTS_DATABASE_PATH,t,c)
            _copy_table(conn,settings.STATS_DATABASE_PATH,'student_quota_stats',['id','student_id','direction_id','total_quotas','attended_count'])
            _copy_table(conn,settings.SYSTEM_DATABASE_PATH,'notification_templates',['id','key','template_text','updated_at'])
        marker.write_text(datetime.utcnow().isoformat(),encoding='utf-8')
    except Exception as exc: print(f'⚠️ Legacy migration failed: {exc}')

def init_db(app):
    with app.app_context():
        db.create_all()
        migrate_legacy_database()
        migrate_schema()
        # Keep old quota delivery behavior for migrated / pre-v2.6 quotas.
        for quota in EventQuota.query.all():
            if not EventQuotaChat.query.filter_by(quota_id=quota.id).first():
                targets=[]
                for did in get_quota_direction_ids(quota.id):
                    for chat in DirectionChat.query.filter_by(direction_id=did,is_active=True).all(): targets.append((did,chat.chat_id))
                if targets: set_quota_chat_targets(quota.id,targets)
        StudentQuotaStat.query.filter(StudentQuotaStat.total_quotas.is_(None)).update({StudentQuotaStat.total_quotas:0},synchronize_session=False)
        StudentQuotaStat.query.filter(StudentQuotaStat.attended_count.is_(None)).update({StudentQuotaStat.attended_count:0},synchronize_session=False)
        # Upgrade defaults on directions / existing records.
        db.session.execute(db.update(Student).where(Student.education_type.is_(None)).values(education_type='institute'))
        db.session.execute(db.update(User).where(User.assigned_education_type.is_(None)).values(assigned_education_type='all'))
        db.session.execute(db.update(StudentLeadership).where(StudentLeadership.education_type.is_(None)).values(education_type='institute'))
        if not User.query.filter_by(email='admin@uni.local').first():
            db.session.add(User(email='admin@uni.local',password_hash=hash_password('admin123'),role='super_admin',assigned_education_type='all'))
        base=[
            {'name':'Студсовет','code':'STUDCOUNCIL','icon':'🏛️','color':'blue'},
            {'name':'Театральная студия','code':'THEATER','icon':'🎭','color':'purple'},
            {'name':'Вокальная студия','code':'VOCAL','icon':'🎤','color':'pink'},
            {'name':'Танцевальная студия ЭСТРАДА','code':'DANCE_EST','icon':'💃','color':'rose'},
            {'name':'Танцевальная студия Современные','code':'DANCE_MOD','icon':'🕺','color':'indigo'},
            {'name':'Спортивный туризм','code':'TOURISM','icon':'⛰️','color':'green'},
            {'name':'Волейбол','code':'VOLLEYBALL','icon':'🏐','color':'orange'},
            {'name':'Футбол','code':'FOOTBALL','icon':'⚽','color':'emerald'},
            {'name':'Шахматы','code':'CHESS','icon':'♟️','color':'slate'},
        ]
        for item in base:
            if not Direction.query.filter_by(code=item['code']).first(): db.session.add(Direction(**item,education_scope='both'))
        defaults={
            'direction_approved':'✅ <b>Заявка одобрена!</b>\n\nВы приняты в направление:\n<b>{direction}</b>\n\nНиже придут персональные ссылки на чаты.',
            'direction_rejected':'❌ <b>Заявка отклонена</b>\n\nНаправление:\n<b>{direction}</b>',
            'activation':'✦ <b>Вы активированы</b>\n\nНаправление:\n<b>{direction}</b>',
            'leadership_assign':'👥 <b>Новое назначение</b>\n\nДолжность: <b>{position}</b>\nНаправление: <b>{direction}</b>\nКонтур: <b>{education_type}</b>',
            'leadership_remove':'⚪ <b>Назначение снято</b>\n\nДолжность: <b>{position}</b>\nНаправление: <b>{direction}</b>\nПричина: {reason}',
        }
        for key,text in defaults.items():
            if not NotificationTemplate.query.filter_by(key=key).first(): db.session.add(NotificationTemplate(key=key,template_text=text))
        db.session.commit()
