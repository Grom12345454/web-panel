import enum
import os
import sqlite3
from datetime import datetime
from pathlib import Path

import bcrypt
from flask_sqlalchemy import SQLAlchemy

from config import settings


db = SQLAlchemy()


def hash_password(p):
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()


def verify_password(p, h):
    return bcrypt.checkpw(p.encode(), h.encode())


class UserRole(str, enum.Enum):
    SUPER_ADMIN = "super_admin"


class DirectionStatus(str, enum.Enum):
    PENDING = "pending"
    INTERVIEW = "interview"
    APPROVED = "approved"
    REJECTED = "rejected"
    ACTIVE = "active"


# Core DB: users / students / directions / application links / questions / leadership.
student_directions = db.Table(
    "student_directions",
    db.Column("student_id", db.Integer, db.ForeignKey("students.id"), primary_key=True),
    db.Column("direction_id", db.Integer, db.ForeignKey("directions.id"), primary_key=True),
    db.Column("joined_at", db.DateTime, default=datetime.utcnow),
    db.Column("extra_data", db.Text),
    db.Column("status", db.String(30), default=DirectionStatus.PENDING.value),
)

# Events DB intentionally stores direction IDs without a cross-database FK.
# It is a model (not a plain Table) so Flask-SQLAlchemy reliably routes it
# to the events bind during create_all()/queries. A plain db.Table here was
# treated as part of the default metadata and caused NoReferencedTableError
# because event_quotas belongs to the events bind.
class QuotaDirection(db.Model):
    __tablename__ = "quota_directions"
    __bind_key__ = "events"

    quota_id = db.Column(db.Integer, primary_key=True)
    direction_id = db.Column(db.Integer, nullable=False, primary_key=True)


class StudentQuotaStat(db.Model):
    __tablename__ = "student_quota_stats"
    __bind_key__ = "stats"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, nullable=False)
    direction_id = db.Column(db.Integer, nullable=False)
    total_quotas = db.Column(db.Integer, default=0)
    attended_count = db.Column(db.Integer, default=0)

    @property
    def student(self):
        return Student.query.get(self.student_id)

    @property
    def direction(self):
        return Direction.query.get(self.direction_id)


class NotificationTemplate(db.Model):
    __tablename__ = "notification_templates"
    __bind_key__ = "system"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    template_text = db.Column(db.Text, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class StudentLeadership(db.Model):
    __tablename__ = "student_leadership"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    direction_id = db.Column(db.Integer, db.ForeignKey("directions.id"), nullable=False)
    position_name = db.Column(db.String(255), nullable=False)

    student = db.relationship("Student", backref="leaderships")
    direction = db.relationship("Direction", backref="leaders")


class DirectionQuestion(db.Model):
    __tablename__ = "direction_questions"

    id = db.Column(db.Integer, primary_key=True)
    direction_id = db.Column(db.Integer, db.ForeignKey("directions.id"), nullable=False)
    question_text = db.Column(db.String(255), nullable=False)
    is_required = db.Column(db.Boolean, default=True)
    sort_order = db.Column(db.Integer, default=0)
    direction = db.relationship("Direction", back_populates="questions")


class Direction(db.Model):
    __tablename__ = "directions"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    code = db.Column(db.String(50), nullable=False)
    icon = db.Column(db.String(50))
    description = db.Column(db.Text)
    color = db.Column(db.String(50), default="blue")

    students = db.relationship("Student", secondary=student_directions, back_populates="directions")
    questions = db.relationship(
        "DirectionQuestion",
        back_populates="direction",
        order_by="DirectionQuestion.sort_order",
        cascade="all, delete-orphan",
    )
    chats = db.relationship(
        "DirectionChat",
        back_populates="direction",
        order_by="DirectionChat.created_at",
        cascade="all, delete-orphan",
    )

    @property
    def quotas(self):
        return get_direction_quotas(self.id)

    @property
    def lessons(self):
        return Lesson.query.filter_by(direction_id=self.id).order_by(Lesson.starts_at.asc()).all()


class DirectionChat(db.Model):
    __tablename__ = "direction_chats"

    id = db.Column(db.Integer, primary_key=True)
    direction_id = db.Column(db.Integer, db.ForeignKey("directions.id"), nullable=False, index=True)
    chat_id = db.Column(db.String(100), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    username = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_test_at = db.Column(db.DateTime)

    direction = db.relationship("Direction", back_populates="chats")

    __table_args__ = (
        db.UniqueConstraint("direction_id", "chat_id", name="uq_direction_chat"),
    )


class TelegramChatCandidate(db.Model):
    __tablename__ = "telegram_chat_candidates"
    __bind_key__ = "system"

    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.String(100), unique=True, nullable=False, index=True)
    title = db.Column(db.String(255))
    username = db.Column(db.String(255))
    chat_type = db.Column(db.String(30))
    first_seen_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_seen_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class EventQuota(db.Model):
    __tablename__ = "event_quotas"
    __bind_key__ = "events"

    id = db.Column(db.Integer, primary_key=True)
    event_title = db.Column(db.String(255), nullable=False)
    event_description = db.Column(db.Text)
    location = db.Column(db.String(255))
    time_range = db.Column(db.String(100))
    dress_code = db.Column(db.String(255))
    functionality = db.Column(db.Text)
    total_places = db.Column(db.Integer, nullable=False)
    is_closed = db.Column(db.Boolean, default=False)
    closing_reason = db.Column(db.Text)
    closed_at = db.Column(db.DateTime)

    days = db.relationship(
        "EventDay",
        back_populates="quota",
        cascade="all, delete-orphan",
        order_by="EventDay.date",
    )

    @property
    def directions(self):
        return get_quota_directions(self.id)


class EventQuotaChat(db.Model):
    __tablename__ = "event_quota_chats"
    __bind_key__ = "events"

    id = db.Column(db.Integer, primary_key=True)
    quota_id = db.Column(db.Integer, nullable=False, index=True)
    direction_id = db.Column(db.Integer, nullable=False, index=True)
    chat_id = db.Column(db.String(100), nullable=False)

    __table_args__ = (
        db.UniqueConstraint("quota_id", "chat_id", name="uq_event_quota_chat"),
    )


class EventDay(db.Model):
    __tablename__ = "event_days"
    __bind_key__ = "events"

    id = db.Column(db.Integer, primary_key=True)
    quota_id = db.Column(db.Integer, db.ForeignKey("event_quotas.id"), nullable=False)
    date = db.Column(db.DateTime, nullable=False)
    daily_places = db.Column(db.Integer, nullable=False)

    quota = db.relationship("EventQuota", back_populates="days")
    participations = db.relationship(
        "DayParticipation",
        back_populates="day",
        cascade="all, delete-orphan",
        order_by="DayParticipation.id",
    )

    def current_count(self):
        return len([p for p in self.participations if p.status != "cancelled"])

    def available_places(self):
        return max(0, (self.daily_places or 0) - self.current_count())


class DayParticipation(db.Model):
    __tablename__ = "day_participations"
    __bind_key__ = "events"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, nullable=False)
    day_id = db.Column(db.Integer, db.ForeignKey("event_days.id"), nullable=False)
    status = db.Column(db.String(20), default="registered")

    day = db.relationship("EventDay", back_populates="participations")

    @property
    def student(self):
        return Student.query.get(self.student_id)


class Lesson(db.Model):
    __tablename__ = "lessons"
    __bind_key__ = "lessons"

    id = db.Column(db.Integer, primary_key=True)
    direction_id = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    teacher = db.Column(db.String(255))
    room = db.Column(db.String(255))
    starts_at = db.Column(db.DateTime, nullable=False)
    duration_minutes = db.Column(db.Integer, default=90, nullable=False)
    capacity = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(30), default="scheduled", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def direction(self):
        return Direction.query.get(self.direction_id)

    @property
    def end_at(self):
        from datetime import timedelta
        return self.starts_at + timedelta(minutes=self.duration_minutes or 0)

    @property
    def formatted_date(self):
        return self.starts_at.strftime("%d.%m.%Y")

    @property
    def formatted_time(self):
        return self.starts_at.strftime("%H:%M")


class Student(db.Model):
    __tablename__ = "students"

    id = db.Column(db.Integer, primary_key=True)
    tg_id = db.Column(db.BigInteger, unique=True, nullable=False)
    full_name = db.Column(db.String(255), nullable=False)
    group = db.Column(db.String(50))
    phone = db.Column(db.String(30))
    email = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    directions = db.relationship("Direction", secondary=student_directions, back_populates="students")


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(50), nullable=False)
    tg_id = db.Column(db.BigInteger, unique=True, nullable=True)

    assigned_direction_id = db.Column(db.Integer, db.ForeignKey("directions.id"))
    assigned_direction = db.relationship("Direction", foreign_keys=[assigned_direction_id])


def _sqlite_table_exists(path, table_name):
    if not path or not Path(path).exists():
        return False
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
        ).fetchone()
    return row is not None


def _copy_table(legacy_conn, target_path, table_name, columns):
    if not _sqlite_table_exists(settings.LEGACY_DATABASE_PATH, table_name):
        return 0
    with sqlite3.connect(target_path) as target:
        src_rows = legacy_conn.execute(
            f"SELECT {', '.join(columns)} FROM {table_name}"
        ).fetchall()
        if not src_rows:
            return 0
        placeholders = ",".join("?" for _ in columns)
        target.executemany(
            f"INSERT OR IGNORE INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})",
            src_rows,
        )
        target.commit()
        return len(src_rows)


def migrate_legacy_database():
    """Migrate the former single SQLite DB into separate subsystem DBs once."""
    legacy_path = settings.LEGACY_DATABASE_PATH
    if not legacy_path or not Path(legacy_path).exists():
        return

    marker = Path(settings.DATABASE_DIR) / ".split_migration_v23"
    if marker.exists():
        return

    try:
        with sqlite3.connect(legacy_path) as legacy:
            # Core database.
            core_tables = {
                # Parent tables first so the migration remains safe if SQLite foreign keys are enabled.
                "directions": ["id", "name", "code", "icon", "description", "color"],
                "students": ["id", "tg_id", "full_name", "group", "phone", "email", "created_at"],
                "users": ["id", "email", "password_hash", "role", "tg_id", "assigned_direction_id"],
                "student_directions": ["student_id", "direction_id", "joined_at", "extra_data", "status"],
                "direction_questions": ["id", "direction_id", "question_text", "is_required", "sort_order"],
                "student_leadership": ["id", "student_id", "direction_id", "position_name"],
                "direction_chats": ["id", "direction_id", "chat_id", "title", "username", "is_active", "created_at", "last_test_at"],
            }
            for table, columns in core_tables.items():
                _copy_table(legacy, settings.PEOPLE_DATABASE_PATH, table, columns)

            # Events database.
            event_tables = {
                "event_quotas": ["id", "event_title", "event_description", "location", "time_range", "dress_code", "functionality", "total_places", "is_closed", "closing_reason", "closed_at"],
                "event_days": ["id", "quota_id", "date", "daily_places"],
                "day_participations": ["id", "student_id", "day_id", "status"],
                "quota_directions": ["quota_id", "direction_id"],
            }
            for table, columns in event_tables.items():
                _copy_table(legacy, settings.EVENTS_DATABASE_PATH, table, columns)

            # Statistics database.
            _copy_table(
                legacy,
                settings.STATS_DATABASE_PATH,
                "student_quota_stats",
                ["id", "student_id", "direction_id", "total_quotas", "attended_count"],
            )

            # System database.
            _copy_table(
                legacy,
                settings.SYSTEM_DATABASE_PATH,
                "notification_templates",
                ["id", "key", "template_text", "updated_at"],
            )

        marker.write_text(datetime.utcnow().isoformat(), encoding="utf-8")
        print("✅ Старая university.db распределена по отдельным базам данных")
    except Exception as exc:
        print(f"⚠️ Не удалось перенести legacy БД: {exc}")


def get_quota_direction_ids(quota_id):
    rows = db.session.execute(
        db.select(QuotaDirection.direction_id).where(QuotaDirection.quota_id == quota_id)
    ).all()
    return [row[0] for row in rows if row[0] is not None]


def get_quota_directions(quota_id):
    ids = get_quota_direction_ids(quota_id)
    if not ids:
        return []
    directions = Direction.query.filter(Direction.id.in_(ids)).all()
    by_id = {d.id: d for d in directions}
    return [by_id[i] for i in ids if i in by_id]


def set_quota_directions(quota_id, direction_ids):
    QuotaDirection.query.filter_by(quota_id=quota_id).delete(synchronize_session=False)
    clean_ids = []
    for raw in direction_ids:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value > 0 and value not in clean_ids:
            clean_ids.append(value)
    if clean_ids:
        db.session.add_all(
            [QuotaDirection(quota_id=quota_id, direction_id=did) for did in clean_ids]
        )


def get_quota_chat_targets(quota_id):
    return EventQuotaChat.query.filter_by(quota_id=quota_id).all()


def set_quota_chat_targets(quota_id, targets):
    EventQuotaChat.query.filter_by(quota_id=quota_id).delete(synchronize_session=False)
    rows = []
    seen = set()
    for direction_id, chat_id in targets:
        try:
            did = int(direction_id)
        except (TypeError, ValueError):
            continue
        cid = str(chat_id or '').strip()
        key = (did, cid)
        if did > 0 and cid and key not in seen:
            seen.add(key)
            rows.append(EventQuotaChat(quota_id=quota_id, direction_id=did, chat_id=cid))
    if rows:
        db.session.add_all(rows)


def get_direction_quota_ids(direction_id):
    return [
        row[0]
        for row in db.session.execute(
            db.select(QuotaDirection.quota_id).where(QuotaDirection.direction_id == direction_id)
        ).all()
        if row[0] is not None
    ]


def get_direction_quotas(direction_id):
    ids = get_direction_quota_ids(direction_id)
    if not ids:
        return []
    quotas = EventQuota.query.filter(EventQuota.id.in_(ids)).all()
    by_id = {q.id: q for q in quotas}
    return [by_id[i] for i in ids if i in by_id]


def init_db(app):
    with app.app_context():
        db.create_all()
        migrate_legacy_database()

        # Preserve delivery behavior for quotas created before per-chat targeting: 
        # attach every currently active chat of each selected direction once.
        for quota in EventQuota.query.all():
            if not EventQuotaChat.query.filter_by(quota_id=quota.id).first():
                targets = []
                for direction_id in get_quota_direction_ids(quota.id):
                    for chat in DirectionChat.query.filter_by(direction_id=direction_id, is_active=True).all():
                        targets.append((direction_id, chat.chat_id))
                if targets:
                    set_quota_chat_targets(quota.id, targets)

        StudentQuotaStat.query.filter(StudentQuotaStat.total_quotas.is_(None)).update(
            {StudentQuotaStat.total_quotas: 0}, synchronize_session=False
        )
        StudentQuotaStat.query.filter(StudentQuotaStat.attended_count.is_(None)).update(
            {StudentQuotaStat.attended_count: 0}, synchronize_session=False
        )
        db.session.commit()

        if not User.query.filter_by(email="admin@uni.local").first():
            admin = User(
                email="admin@uni.local",
                password_hash=hash_password("admin123"),
                role=UserRole.SUPER_ADMIN.value,
            )
            db.session.add(admin)

        base_directions = [
            {"name": "Театральная студия", "code": "THEATER", "icon": "🎭", "color": "purple"},
            {"name": "Вокальная студия", "code": "VOCAL", "icon": "🎤", "color": "pink"},
            {"name": "Танцевальная студия ЭСТРАДА", "code": "DANCE_EST", "icon": "💃", "color": "rose"},
            {"name": "Танцевальная студия Современные", "code": "DANCE_MOD", "icon": "🕺", "color": "indigo"},
            {"name": "Спортивный туризм", "code": "TOURISM", "icon": "⛰️", "color": "green"},
            {"name": "Студсовет", "code": "STUDCOUNCIL", "icon": "🏛️", "color": "blue"},
            {"name": "Волейбол", "code": "VOLLEYBALL", "icon": "🏐", "color": "orange"},
            {"name": "Футбол", "code": "FOOTBALL", "icon": "⚽", "color": "emerald"},
            {"name": "Шахматы", "code": "CHESS", "icon": "♟️", "color": "slate"},
        ]
        for item in base_directions:
            if not Direction.query.filter_by(code=item["code"]).first():
                db.session.add(Direction(**item))

        default_templates = {
            "leadership_assign": " <b>Поздравляем с назначением!</b>\n\nВы назначены на должность:\n<b>{position}</b>\n\nв направлении:\n{direction}\n\nЖелаем успехов! ",
            "leadership_remove": "️ <b>Изменение статуса</b>\n\nВы сняты с должности:\n<b>{position}</b>\n\nв направлении:\n{direction}\n\nПричина: {reason}",
            "interview_invite": "🎓 <b>Приглашение на собеседование</b>\n\nЗдравствуйте, <b>{student_name}</b>!\n\nВас приглашают в направление <b>{direction}</b>.\n\n📅 <b>Дата:</b> {date}\n📍 <b>Место:</b> {location}\n\nПодтвердите явку кнопкой ниже 👇",
            "direction_approved": "✅ <b>Заявка одобрена!</b>\n\nПоздравляем! Вы приняты в направление:\n<b>{direction}</b>\n\nЖелаем успехов!",
            "direction_rejected": "❌ <b>Заявка отклонена</b>\n\nК сожалению, ваша заявка в направление:\n<b>{direction}</b>\n\nбыла отклонена.",
            "activation": "✦ <b>Вы активированы</b>\n\nТеперь вы можете участвовать в мероприятиях направления:\n<b>{direction}</b>\n\nСледите за уведомлениями в этом чате.",
        }
        for key, text in default_templates.items():
            if not NotificationTemplate.query.filter_by(key=key).first():
                db.session.add(NotificationTemplate(key=key, template_text=text))

        db.session.commit()
        print("✅ Базы данных инициализированы: people / events / lessons / stats / system")
