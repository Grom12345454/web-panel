import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from flask import current_app
from config import settings
from .base import db, hash_password, student_directions
from .core import Direction, DirectionChat, Student, User, StudentLeadership, EventLeader, TelegramChatCandidate, DirectionQuestion
from .events import EventQuota, EventDay, QuotaDirection, EventQuotaChat, DayParticipation
from .stats import StudentQuotaStat
from .system import NotificationTemplate

logger = logging.getLogger(__name__)

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
    """Replace one event's explicit multi-platform chat assignments.

    Accepts legacy (direction_id, chat_id) tuples as Telegram for migration
    compatibility, or (platform, direction_id, chat_id, title) tuples.
    """
    EventQuotaChat.query.filter_by(quota_id=quota_id).delete(synchronize_session=False)
    seen=set(); rows=[]
    for target in targets:
        try:
            if len(target) == 2:
                did, cid = target
                platform, title = 'telegram', None
            else:
                platform, did, cid, title = target[:4]
            did=int(did)
        except (TypeError, ValueError):
            continue
        platform=str(platform or 'telegram').strip().lower()
        cid=str(cid or '').strip()
        title=' '.join(str(title or '').split())[:255] or None
        key=(platform, cid)
        if platform in {'telegram','vk','max'} and did>0 and cid and key not in seen:
            seen.add(key)
            rows.append(EventQuotaChat(quota_id=quota_id, direction_id=did, platform=platform,
                                       chat_id=cid, title=title))
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

def drop_column_if_exists(path, table, column, indexes=()):
    """Remove a retired SQLite column and its named indexes, when present."""
    if not path or not Path(path).exists() or not _sqlite_table_exists(path, table):
        return
    with sqlite3.connect(path) as conn:
        for index_name in indexes:
            # Index names are constants supplied by this module, not user input.
            conn.execute(f'DROP INDEX IF EXISTS "{index_name}"')
        if column not in _columns(conn, table):
            conn.commit()
            return
        if sqlite3.sqlite_version_info < (3, 35, 0):
            logger.warning('SQLite %s cannot drop column %s.%s; leaving the retired column unused',
                           sqlite3.sqlite_version, table, column)
            conn.commit()
            return
        conn.execute(f'ALTER TABLE "{table}" DROP COLUMN "{column}"')
        conn.commit()

def remove_legacy_telegram_logs():
    """Remove the old message-history table so Telegram message logs are not retained."""
    path = settings.SYSTEM_DATABASE_PATH
    if not Path(path).exists():
        return
    with sqlite3.connect(path) as conn:
        conn.execute("DROP TABLE IF EXISTS chat_message_logs")
        conn.commit()

def _make_science_direction_optional():
    """Preserve old science records when removing the council-only requirement.

    SQLite cannot DROP NOT NULL on an existing column, so rebuild two tables in one
    transaction with their same primary keys and all article/author references intact.
    """
    path = settings.PEOPLE_DATABASE_PATH
    if not _sqlite_table_exists(path, 'science_readings'):
        return
    table_sql = {
        'science_readings': '''CREATE TABLE science_readings_new (
            id INTEGER PRIMARY KEY, title VARCHAR(200) NOT NULL,
            category VARCHAR(80) NOT NULL, direction_id INTEGER NULL REFERENCES directions(id),
            description TEXT, held_at DATETIME, deadline DATETIME,
            is_open BOOLEAN NOT NULL, created_at DATETIME NOT NULL)''',
        'science_submissions': '''CREATE TABLE science_submissions_new (
            id INTEGER PRIMARY KEY, reading_id INTEGER NOT NULL REFERENCES science_readings(id),
            student_id INTEGER NOT NULL REFERENCES students(id),
            direction_id INTEGER NULL REFERENCES directions(id),
            article_title VARCHAR(250) NOT NULL, author_count INTEGER NOT NULL,
            status VARCHAR(20) NOT NULL, created_at DATETIME NOT NULL)''',
    }
    with sqlite3.connect(path) as conn:
        pending = [table for table in table_sql if _sqlite_table_exists(path, table) and
            any(row[1] == 'direction_id' and row[3] for row in conn.execute(f'PRAGMA table_info({table})'))]
        if not pending:
            return
        # Disable foreign-key checks outside the transaction, never between statements.
        conn.execute('PRAGMA foreign_keys=OFF')
        try:
            conn.execute('BEGIN IMMEDIATE')
            for table in pending:
                fresh = table + '_new'
                conn.execute(table_sql[table])
                columns = [row[1] for row in conn.execute(f'PRAGMA table_info({table})')]
                col_sql = ', '.join('"'+c+'"' for c in columns)
                conn.execute(f'INSERT INTO {fresh} ({col_sql}) SELECT {col_sql} FROM {table}')
                conn.execute(f'DROP TABLE {table}')
                conn.execute(f'ALTER TABLE {fresh} RENAME TO {table}')
                for column in ('direction_id', 'reading_id', 'student_id'):
                    if column in columns:
                        conn.execute(f'CREATE INDEX IF NOT EXISTS ix_{table}_{column} ON {table}({column})')
            invalid = conn.execute('PRAGMA foreign_key_check').fetchall()
            if invalid:
                raise sqlite3.IntegrityError('Science migration would violate foreign keys')
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.execute('PRAGMA foreign_keys=ON')

def _migrate_event_quota_chats():
    """Upgrade chat assignments to platform-scoped, named event targets."""
    path = settings.EVENTS_DATABASE_PATH
    if not path or not Path(path).exists() or not _sqlite_table_exists(path, 'event_quota_chats'):
        return
    with sqlite3.connect(path) as conn:
        cols = set(_columns(conn, 'event_quota_chats'))
        unique_target = False
        for index in conn.execute('PRAGMA index_list("event_quota_chats")').fetchall():
            if not index[2]:
                continue
            index_name = index[1].replace('\"', '\"\"')
            index_cols = [row[2] for row in conn.execute(f'PRAGMA index_info("{index_name}")').fetchall()]
            if index_cols == ['quota_id', 'platform', 'chat_id']:
                unique_target = True
                break
        required = {'platform', 'title', 'invite_link'}
        if required.issubset(cols) and unique_target:
            return
        conn.execute('PRAGMA foreign_keys=OFF')
        conn.execute('BEGIN')
        try:
            old_platform = 'platform' if 'platform' in cols else "'telegram'"
            old_title = 'title' if 'title' in cols else 'NULL'
            old_invite = 'invite_link' if 'invite_link' in cols else 'NULL'
            conn.execute("""CREATE TABLE event_quota_chats_new (
                id INTEGER PRIMARY KEY,
                quota_id INTEGER NOT NULL,
                direction_id INTEGER NOT NULL,
                platform VARCHAR(15) NOT NULL DEFAULT 'telegram',
                chat_id VARCHAR(100) NOT NULL,
                title VARCHAR(255),
                invite_link VARCHAR(512),
                CONSTRAINT uq_event_quota_platform_chat UNIQUE (quota_id, platform, chat_id)
            )""")
            conn.execute(f"""INSERT OR IGNORE INTO event_quota_chats_new
                (id, quota_id, direction_id, platform, chat_id, title, invite_link)
                SELECT id, quota_id, direction_id, COALESCE({old_platform}, 'telegram'), chat_id,
                       {old_title}, {old_invite} FROM event_quota_chats""")
            conn.execute('DROP TABLE event_quota_chats')
            conn.execute('ALTER TABLE event_quota_chats_new RENAME TO event_quota_chats')
            conn.execute('CREATE INDEX IF NOT EXISTS ix_event_quota_chats_quota_id ON event_quota_chats(quota_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS ix_event_quota_chats_direction_id ON event_quota_chats(direction_id)')
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.execute('PRAGMA foreign_keys=ON')


def migrate_staff_account_roles(path=None):
    """Limit provisioned staff accounts to employee and observer roles.

    Legacy archive-admin accounts are downgraded to unassigned employees (no
    direction grants), while legacy head/deputy staff ranks become ordinary
    employees. Existing explicit grants for those employees are preserved.
    Session versions are bumped whenever permissions are changed.
    """
    path = path or settings.PEOPLE_DATABASE_PATH
    if not _sqlite_table_exists(path, 'users'):
        return
    with sqlite3.connect(path) as conn:
        columns = set(_columns(conn, 'users'))
        if 'role' not in columns:
            return
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if 'staff_grants' in tables:
            conn.execute("""DELETE FROM staff_grants
                WHERE user_id IN (SELECT id FROM users WHERE role='admin')""")
        if 'staff_rank' in columns:
            if 'auth_version' in columns:
                conn.execute("""UPDATE users SET staff_rank='employee',
                    auth_version=COALESCE(auth_version, 0)+1
                    WHERE role='staff' AND staff_rank NOT IN ('employee','employee_all')""")
            else:
                conn.execute("""UPDATE users SET staff_rank='employee'
                    WHERE role='staff' AND staff_rank NOT IN ('employee','employee_all')""")
        if 'assigned_direction_id' in columns and 'auth_version' in columns:
            conn.execute("""UPDATE users SET role='staff', staff_rank='employee',
                assigned_direction_id=NULL, auth_version=COALESCE(auth_version, 0)+1
                WHERE role='admin'""")
        elif 'auth_version' in columns:
            conn.execute("""UPDATE users SET role='staff', staff_rank='employee',
                auth_version=COALESCE(auth_version, 0)+1 WHERE role='admin'""")
        else:
            conn.execute("""UPDATE users SET role='staff', staff_rank='employee'
                WHERE role='admin'""")
        conn.commit()


def migrate_schema():
    # Additive SQLite migration: retain previously issued codes until expiration.
    ensure_column(settings.SYSTEM_DATABASE_PATH, "messenger_link_codes", "target_platform", "VARCHAR(15)")
    ensure_column(settings.SYSTEM_DATABASE_PATH, "messenger_link_codes", "expected_handle", "VARCHAR(100)")
    ensure_column(settings.SYSTEM_DATABASE_PATH, "messenger_link_codes", "pending_external_user_id", "VARCHAR(100)")
    ensure_column(settings.SYSTEM_DATABASE_PATH, "messenger_link_codes", "pending_public_username", "VARCHAR(100)")
    ensure_column(settings.SYSTEM_DATABASE_PATH, "messenger_link_codes", "requested_at", "DATETIME")
    ensure_column(settings.SYSTEM_DATABASE_PATH, "messenger_link_codes", "rejected_at", "DATETIME")
    ensure_column(settings.SYSTEM_DATABASE_PATH, "messenger_identities", "public_username", "VARCHAR(100)")
    ensure_column(settings.PEOPLE_DATABASE_PATH,"students","education_type","VARCHAR(20) NOT NULL DEFAULT 'institute'")
    ensure_column(settings.PEOPLE_DATABASE_PATH,"students","telegram_username","VARCHAR(255)")
    ensure_column(settings.PEOPLE_DATABASE_PATH,"students","council_registered","BOOLEAN NOT NULL DEFAULT 1")
    # Existing staff must rotate the initial credentials once after this release.
    # The column's migration default is only applied when it is first introduced.
    user_columns_before_password_migration = []
    if _sqlite_table_exists(settings.PEOPLE_DATABASE_PATH, 'users'):
        with sqlite3.connect(settings.PEOPLE_DATABASE_PATH) as conn:
            user_columns_before_password_migration = _columns(conn, 'users')
    for name, ddl in (
        ('full_name', 'VARCHAR(255)'), ('position', 'VARCHAR(150)'), ('contact_email', 'VARCHAR(255)'),
        ('phone', 'VARCHAR(40)'), ('auth_version', 'INTEGER NOT NULL DEFAULT 0'),
        ('must_change_password', 'BOOLEAN NOT NULL DEFAULT 1'), ('is_active', 'BOOLEAN NOT NULL DEFAULT 1'),
        ('notifications', "VARCHAR(250) NOT NULL DEFAULT 'science,events,applications'"),
        ('student_id', 'INTEGER'), ('staff_rank', "VARCHAR(20) NOT NULL DEFAULT 'employee'"),
    ):
        ensure_column(settings.PEOPLE_DATABASE_PATH, 'users', name, ddl)
    if 'must_change_password' not in user_columns_before_password_migration and user_columns_before_password_migration:
        with sqlite3.connect(settings.PEOPLE_DATABASE_PATH) as conn:
            conn.execute("UPDATE users SET must_change_password=0 WHERE role != 'staff'")
            conn.commit()
    ensure_column(settings.PEOPLE_DATABASE_PATH,"users","assigned_education_type","VARCHAR(20) NOT NULL DEFAULT 'all'")
    # Only employee and observer are provisionable account roles now.
    migrate_staff_account_roles(settings.PEOPLE_DATABASE_PATH)
    # Employee Telegram usernames are retired. A numeric Telegram ID remains
    # available for accounts that were already linked and still use OTP.
    drop_column_if_exists(settings.PEOPLE_DATABASE_PATH, 'users', 'telegram_username',
                          indexes=('ix_users_telegram_handle',))
    with sqlite3.connect(settings.PEOPLE_DATABASE_PATH) as conn:
        conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS ix_users_promoted_student ON users(student_id) WHERE student_id IS NOT NULL')
    ensure_column(settings.PEOPLE_DATABASE_PATH, 'users', 'science_access', "VARCHAR(10) NOT NULL DEFAULT 'none'")
    _make_science_direction_optional()
    ensure_column(settings.PEOPLE_DATABASE_PATH, 'science_readings', 'science_directions_json', 'TEXT')
    ensure_column(settings.PEOPLE_DATABASE_PATH, 'student_leadership', 'source_user_id', 'INTEGER')
    ensure_column(settings.PEOPLE_DATABASE_PATH,"student_leadership","education_type","VARCHAR(20) NOT NULL DEFAULT 'institute'")
    with sqlite3.connect(settings.PEOPLE_DATABASE_PATH) as conn:
        conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS ix_leadership_managed_source ON student_leadership(source_user_id) WHERE source_user_id IS NOT NULL')
    ensure_column(settings.PEOPLE_DATABASE_PATH,"directions","is_archived","BOOLEAN NOT NULL DEFAULT 0")
    ensure_column(settings.PEOPLE_DATABASE_PATH,"directions","education_scope","VARCHAR(20) NOT NULL DEFAULT 'both'")
    ensure_column(settings.PEOPLE_DATABASE_PATH,"direction_chats","education_type","VARCHAR(20) NOT NULL DEFAULT 'all'") 
    ensure_column(settings.EVENTS_DATABASE_PATH, "event_quotas", "publish_mode", "VARCHAR(20) NOT NULL DEFAULT 'immediate'")
    ensure_column(settings.EVENTS_DATABASE_PATH, "event_quotas", "publish_at", "DATETIME")
    ensure_column(settings.EVENTS_DATABASE_PATH, "event_quotas", "is_published", "BOOLEAN NOT NULL DEFAULT 0")
    ensure_column(settings.EVENTS_DATABASE_PATH, "event_quotas", "chat_selection_explicit", "BOOLEAN NOT NULL DEFAULT 0")
    _migrate_event_quota_chats()
    ensure_column(settings.SYSTEM_DATABASE_PATH, "site_notifications", "publication_key", "VARCHAR(64)")
    with sqlite3.connect(settings.SYSTEM_DATABASE_PATH) as conn:
        conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS ix_site_notification_publication_key ON site_notifications(publication_key) WHERE publication_key IS NOT NULL')
    ensure_column(settings.SYSTEM_DATABASE_PATH, "bot_delivery_jobs", "source_type", "VARCHAR(20)")
    ensure_column(settings.SYSTEM_DATABASE_PATH, "bot_delivery_jobs", "source_id", "INTEGER")
    ensure_column(settings.SYSTEM_DATABASE_PATH, "bot_delivery_jobs", "last_attempt_at", "DATETIME")

    # Composite indexes for the most common admin reports and live journals.
    # These are additive and safe for existing SQLite databases.
    def ensure_indexes(path, definitions):
        if not path or not Path(path).exists():
            return
        with sqlite3.connect(path) as conn:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            for table, name, columns in definitions:
                if table in tables:
                    conn.execute(f'CREATE INDEX IF NOT EXISTS "{name}" ON "{table}" ({columns})')
            conn.commit()

    ensure_indexes(settings.SYSTEM_DATABASE_PATH, [
        ('student_activity', 'ix_student_activity_direction_created_id', 'direction_id, created_at, id'),
        ('student_activity', 'ix_student_activity_quota_created_id', 'quota_id, created_at, id'),
        ('http_audit_logs', 'ix_http_audit_role_created_id', 'actor_role, created_at, id'),
        ('http_audit_logs', 'ix_http_audit_actor_created_id', 'actor_user_id, created_at, id'),
        ('bot_journal_events', 'ix_bot_journal_created_id', 'created_at, id'),
        ('bot_journal_events', 'ix_bot_journal_platform_status_created', 'platform, status, created_at'),
    ])
    ensure_indexes(settings.EVENTS_DATABASE_PATH, [
        ('event_days', 'ix_event_days_quota_date_report', 'quota_id, date'),
        ('day_participations', 'ix_participations_day_status_report', 'day_id, status'),
        ('event_quota_declines', 'ix_event_declines_quota_created', 'quota_id, created_at'),
        ('quota_directions', 'ix_quota_directions_direction_quota', 'direction_id, quota_id'),
    ])
    ensure_indexes(settings.PEOPLE_DATABASE_PATH, [
        ('student_directions', 'ix_student_directions_direction_status', 'direction_id, status'),
        ('application_decisions', 'ix_application_decisions_direction_decision_created', 'direction_id, decision, created_at'),
    ])
    ensure_indexes(settings.LESSONS_DATABASE_PATH, [
        ('lessons', 'ix_lessons_direction_status', 'direction_id, status'),
    ])

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
    except Exception:
        logger.exception("Legacy database migration failed")

def init_db(app):
    with app.app_context():
        db.create_all()
        remove_legacy_telegram_logs()
        migrate_legacy_database()
        migrate_schema()
        # Convert exclusive event chat links into reusable rooms. Preserve Telegram
        # chat IDs and invitations, and CANCEL queued auto-removals for these rooms.
        from .activity_chats import ActivityChat, ActivityChatRemoval, SharedActivityChat
        for legacy_chat in ActivityChat.query.all():
            existing = SharedActivityChat.query.filter_by(chat_id=legacy_chat.chat_id).first()
            if not existing:
                db.session.add(SharedActivityChat(
                    chat_id=legacy_chat.chat_id, title=legacy_chat.title,
                    invite_link=legacy_chat.invite_link,
                    audience=legacy_chat.kind if legacy_chat.kind in ('event', 'science') else 'all',
                    active=bool(legacy_chat.active)))
            if legacy_chat.active:
                legacy_chat.active = False
            ActivityChatRemoval.query.filter_by(chat_id=legacy_chat.chat_id).filter(
                ActivityChatRemoval.status.in_(['pending', 'retry', 'failed'])).update(
                    {ActivityChatRemoval.status: 'cancelled'}, synchronize_session=False)
        # Preserve legacy event delivery targets once; all newly created events
        # use an explicit (possibly empty) per-event chat selection.
        from .messengers import MessengerChat
        for quota in EventQuota.query.all():
            existing_targets = EventQuotaChat.query.filter_by(quota_id=quota.id).all()
            if quota.chat_selection_explicit:
                continue
            # V10 already stored Telegram targets but still delivered to VK/MAX
            # direction chats implicitly. Add those social targets once so old
            # events retain their previous delivery behavior after the upgrade.
            targets = [
                (getattr(row, 'platform', 'telegram') or 'telegram', row.direction_id,
                 row.chat_id, row.title)
                for row in existing_targets
            ]
            seen = {(platform, str(chat_id)) for platform, _, chat_id, _ in targets}
            direction_ids = get_quota_direction_ids(quota.id)
            for did in direction_ids:
                for chat in DirectionChat.query.filter_by(direction_id=did, is_active=True).all():
                    target_key = ('telegram', str(chat.chat_id))
                    if target_key not in seen:
                        targets.append(('telegram', did, chat.chat_id, chat.title))
                        seen.add(target_key)
                for chat in MessengerChat.query.filter_by(direction_id=did, is_active=True).all():
                    target_key = (chat.platform, str(chat.chat_id))
                    if target_key not in seen:
                        targets.append((chat.platform, did, chat.chat_id, chat.title))
                        seen.add(target_key)
            if targets:
                set_quota_chat_targets(quota.id, targets)
            quota.chat_selection_explicit = True
        StudentQuotaStat.query.filter(StudentQuotaStat.total_quotas.is_(None)).update({StudentQuotaStat.total_quotas:0},synchronize_session=False)
        StudentQuotaStat.query.filter(StudentQuotaStat.attended_count.is_(None)).update({StudentQuotaStat.attended_count:0},synchronize_session=False)
        # Remove the obsolete intermediate "approved" status. Legacy rows are
        # migrated to active so students retain access and no screen shows approval.
        db.session.execute(student_directions.update().where(
            student_directions.c.status == 'approved'
        ).values(status='active'))
        # Keep historical decision records aligned with the final membership state.
        try:
            from .core import ApplicationDecision
            db.session.query(ApplicationDecision).filter_by(decision='approved').update(
                {ApplicationDecision.decision: 'active'}, synchronize_session=False
            )
        except Exception:
            logger.exception("Could not normalize legacy approval decisions")
        # Upgrade defaults on directions / existing records.
        db.session.execute(db.update(Student).where(Student.education_type.is_(None)).values(education_type='institute'))
        # Student email is not used by this service; clear historical values as well.
        db.session.execute(db.update(Student).where(Student.email.is_not(None)).values(email=None))
        db.session.execute(db.update(User).where(User.assigned_education_type.is_(None)).values(assigned_education_type='all'))
        db.session.execute(db.update(StudentLeadership).where(StudentLeadership.education_type.is_(None)).values(education_type='institute'))
        # Bootstrap only the main administrator. Employee and observer accounts
        # are created and maintained by the main administrator in the staff panel.
        panel_users = [
            (settings.ADMIN_USERNAME, settings.ADMIN_PASSWORD, 'super_admin'),
        ]
        # Explicit administrator bot binding; never silently overwrite an existing ID.
        admin = User.query.filter_by(email=settings.ADMIN_USERNAME, role='super_admin').first()
        if admin and settings.ADMIN_TG_ID.isdecimal() and not admin.tg_id:
            admin.tg_id = int(settings.ADMIN_TG_ID)
        for username, password, role in panel_users:
            # An empty password disables bootstrap rather than creating a
            # known/default credential. Set a unique admin password in .env.
            # The existing `email` DB column is retained as a migration-compatible
            # login identifier; no email address is requested or displayed.
            if username and password and not User.query.filter_by(email=username).first():
                db.session.add(User(
                    email=username,
                    password_hash=hash_password(password),
                    role=role,
                    assigned_education_type='all',
                    tg_id=int(settings.ADMIN_TG_ID) if role == 'super_admin' and settings.ADMIN_TG_ID.isdecimal() else None,
                ))
        # Built-in directions use typography and color accents, not emoji icons.
        # Clear legacy icon values for these codes as well, so an existing DB
        # receives the same clean presentation as a fresh installation.
        base=[
            {'name':'Волонтёрка','code':'STUDCOUNCIL','color':'blue'},
            {'name':'Театральная студия','code':'THEATER','color':'purple'},
            {'name':'Вокальная студия','code':'VOCAL','color':'pink'},
            {'name':'Танцевальная студия ЭСТРАДА','code':'DANCE_EST','color':'rose'},
            {'name':'Танцевальная студия Современные','code':'DANCE_MOD','color':'indigo'},
            {'name':'Волейбол','code':'VOLLEYBALL','color':'orange'},
            {'name':'Футбол','code':'FOOTBALL','color':'emerald'},
            # Council membership is optional and entirely separate from
            # registering as an author at a scientific reading.
            {'name':'Научная деятельность','code':'SCIENCE','color':'cyan'},
        ]
        for item in base:
            existing_direction = Direction.query.filter_by(code=item['code']).first()
            if existing_direction:
                existing_direction.icon = None
                continue
            # An administrator could have created this council direction
            # manually before installing the update.  Do not duplicate it or
            # overwrite its identifier/code and break existing memberships.
            if item['code'] == 'SCIENCE':
                existing_science = Direction.query.filter_by(name=item['name']).first()
                if existing_science:
                    existing_science.icon = None
                    continue
            db.session.add(Direction(**item, education_scope='both'))
        volunteer_direction = Direction.query.filter_by(code='STUDCOUNCIL').first()
        if volunteer_direction:
            volunteer_direction.name = 'Волонтёрка'
            volunteer_direction.icon = None
            if not volunteer_direction.education_scope:
                volunteer_direction.education_scope = 'both'

        for leader in StudentLeadership.query.all():
            normalized = ' '.join((leader.position_name or '').strip().casefold().replace('ё', 'е').split())
            if normalized in {'председатель студсовета', 'председатель волонтерки'}:
                leader.position_name = 'Председатель студсовета'
                leader.education_type = 'all'
            elif normalized in {
                'заместитель председателя студсовета', 'заместитель студсовета',
                'зампред студсовета', 'заместитель председателя волонтерки',
            }:
                target_type = leader.education_type if leader.education_type in {'college', 'institute'} else 'institute'
                if leader.education_type == 'all':
                    college_exists = StudentLeadership.query.filter(
                        StudentLeadership.student_id == leader.student_id,
                        StudentLeadership.direction_id == leader.direction_id,
                        StudentLeadership.position_name == 'Заместитель председателя студсовета по колледжу',
                    ).first()
                    if not college_exists:
                        db.session.add(StudentLeadership(
                            student_id=leader.student_id,
                            direction_id=leader.direction_id,
                            position_name='Заместитель председателя студсовета по колледжу',
                            education_type='college',
                        ))
                    target_type = 'institute'
                leader.position_name = ('Заместитель председателя студсовета по колледжу'
                                        if target_type == 'college' else 'Заместитель председателя студсовета по институту')
                leader.education_type = target_type
            elif normalized in {'заместитель председателя волонтерки по колледжу', 'заместитель председателя студсовета по колледжу'}:
                leader.position_name = 'Заместитель председателя студсовета по колледжу'
                leader.education_type = 'college'
            elif normalized in {'заместитель председателя волонтерки по институту', 'заместитель председателя студсовета по институту'}:
                leader.position_name = 'Заместитель председателя студсовета по институту'
                leader.education_type = 'institute'

        # Earlier builds stored one chair assignment per direction. Merge only
        # repeated rows for the same student; do not silently unappoint someone else.
        known_chairs = set()
        for row in StudentLeadership.query.order_by(StudentLeadership.id.asc()).all():
            if row.position_name != 'Председатель студсовета':
                continue
            if row.student_id in known_chairs:
                db.session.delete(row)
            else:
                known_chairs.add(row.student_id)
        if len(known_chairs) > 1:
            logger.error('Несколько действующих председателей в старой базе: %s. '
                         'Администратор должен снять лишние назначения.', sorted(known_chairs))

        defaults={
            'direction_approved':'✅ <b>Вы приняты в направление</b>\n\nНаправление: <b>{direction}</b>\n\nВаш статус — активный участник. Ниже придут персональные ссылки на чаты.',
            'direction_rejected':'❌ <b>Заявка отклонена</b>\n\nНаправление:\n<b>{direction}</b>',
            'activation':'✦ <b>Вы активированы</b>\n\nНаправление:\n<b>{direction}</b>',
            'leadership_assign':'👥 <b>Новое назначение</b>\n\nДолжность: <b>{position}</b>',
            'leadership_remove':'⚪ <b>Назначение снято</b>\n\nДолжность: <b>{position}</b>\nПричина: {reason}',
            'event_lead_assign':'👑 <b>Вы назначены главным</b>\n\nМероприятие: <b>{event_title}</b>\nРоль: <b>{position}</b>\nДаты: {date}',
        }
        for key,text in defaults.items():
            if not NotificationTemplate.query.filter_by(key=key).first(): db.session.add(NotificationTemplate(key=key,template_text=text))
        from .system import CompetitionAnnouncement
        if not CompetitionAnnouncement.query.first():
            db.session.add(CompetitionAnnouncement(title=settings.COMPETITION_TITLE, body=settings.COMPETITION_BODY, is_active=True))
        db.session.commit()
        # Prune only the new operational journal, never old decisions or student data.
        if settings.BOT_JOURNAL_RETENTION_DAYS:
            try:
                from services.bot_journal import prune_bot_journal
                prune_bot_journal(days=settings.BOT_JOURNAL_RETENTION_DAYS)
            except Exception:
                logger.warning("Could not apply bot journal retention at startup", exc_info=True)
        # Startup repair: existing council chairs/deputies may have roles but no
        # corresponding active student_directions memberships from older versions.
        try:
            from services.chair_membership import sync_existing_chairs
            sync_existing_chairs()
        except Exception:
            db.session.rollback()
            logger.exception("Could not synchronize council leadership memberships")
