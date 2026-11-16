from datetime import datetime
from .base import db, student_directions, DirectionStatus, EducationType

class Direction(db.Model):
    __tablename__ = "directions"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    code = db.Column(db.String(50), nullable=False, unique=True)
    icon = db.Column(db.String(50))
    description = db.Column(db.Text)
    color = db.Column(db.String(50), default="blue")
    education_scope = db.Column(db.String(20), default="both", nullable=False)
    is_archived = db.Column(db.Boolean, nullable=False, default=False)

    students = db.relationship("Student", secondary=student_directions, back_populates="directions")
    questions = db.relationship("DirectionQuestion", back_populates="direction", order_by="DirectionQuestion.sort_order", cascade="all, delete-orphan")
    chats = db.relationship("DirectionChat", back_populates="direction", order_by="DirectionChat.created_at", cascade="all, delete-orphan")

    @property
    def quotas(self):
        from .helpers import get_direction_quotas
        return get_direction_quotas(self.id)

    @property
    def lessons(self):
        from .lessons import Lesson
        return Lesson.query.filter_by(direction_id=self.id).order_by(Lesson.starts_at.asc()).all()

    def available_for(self, education_type):
        return self.education_scope in {"both", education_type, None, ""}

class DirectionChat(db.Model):
    __tablename__ = "direction_chats"
    id = db.Column(db.Integer, primary_key=True)
    direction_id = db.Column(db.Integer, db.ForeignKey("directions.id"), nullable=False, index=True)
    chat_id = db.Column(db.String(100), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    username = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    # "all" = unspecific/shared chat; cohort-targeted broadcasts require a tagged chat.
    education_type = db.Column(db.String(20), default="all", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_test_at = db.Column(db.DateTime)
    direction = db.relationship("Direction", back_populates="chats")
    __table_args__ = (db.UniqueConstraint("direction_id", "chat_id", name="uq_direction_chat"),)

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

class Student(db.Model):
    __tablename__ = "students"
    id = db.Column(db.Integer, primary_key=True)
    tg_id = db.Column(db.BigInteger, unique=True, nullable=False)
    full_name = db.Column(db.String(255), nullable=False)
    telegram_username = db.Column(db.String(255))
    # A science-only author is not registered for student council participation.
    council_registered = db.Column(db.Boolean, nullable=False, default=True)
    group = db.Column(db.String(50))
    phone = db.Column(db.String(30))
    email = db.Column(db.String(255))
    education_type = db.Column(db.String(20), default=EducationType.INSTITUTE.value, nullable=False)
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
    assigned_education_type = db.Column(db.String(20), default="all", nullable=False)
    assigned_direction = db.relationship("Direction", foreign_keys=[assigned_direction_id])
    full_name = db.Column(db.String(255))
    position = db.Column(db.String(150))
    contact_email = db.Column(db.String(255))
    phone = db.Column(db.String(40))
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    auth_version = db.Column(db.Integer, nullable=False, default=0)
    # Set for provisioned/rotated accounts; login is restricted until a new password is chosen.
    must_change_password = db.Column(db.Boolean, nullable=False, default=False, server_default='0')
    notifications = db.Column(db.String(250), nullable=False, default='science,events,applications')
    # Student promotion keeps the student's original profile and messenger identities.
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), unique=True, nullable=True)
    staff_rank = db.Column(db.String(20), nullable=False, default='employee')
    # Explicit institute-wide science permission, independent of student council directions.
    science_access = db.Column(db.String(10), nullable=False, default='none')
    promoted_student = db.relationship('Student', foreign_keys=[student_id])
    grants = db.relationship('StaffGrant', cascade='all, delete-orphan', backref='user')

class StudentLeadership(db.Model):
    __tablename__ = "student_leadership"
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    direction_id = db.Column(db.Integer, db.ForeignKey("directions.id"), nullable=False)
    education_type = db.Column(db.String(20), default=EducationType.INSTITUTE.value, nullable=False)
    position_name = db.Column(db.String(255), nullable=False)
    # Leadership record managed by the staff promotion system, distinct from manually appointed roles.
    source_user_id = db.Column(db.Integer, nullable=True, unique=True)
    student = db.relationship("Student", backref="leaderships")
    direction = db.relationship("Direction", backref="leaders")

class EventLeader(db.Model):
    __tablename__ = "event_leaders"
    id = db.Column(db.Integer, primary_key=True)
    quota_id = db.Column(db.Integer, unique=True, nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False, index=True)
    position_name = db.Column(db.String(255), nullable=False, default="Главный")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    student = db.relationship("Student", backref="event_leaderships")

class DirectionQuestion(db.Model):
    __tablename__ = "direction_questions"
    id = db.Column(db.Integer, primary_key=True)
    direction_id = db.Column(db.Integer, db.ForeignKey("directions.id"), nullable=False)
    question_text = db.Column(db.String(255), nullable=False)
    is_required = db.Column(db.Boolean, default=True)
    sort_order = db.Column(db.Integer, default=0)
    direction = db.relationship("Direction", back_populates="questions")


class ApplicationDecision(db.Model):
    """Append-only decision history for direction applications and their temporary blocks."""
    __tablename__ = "application_decisions"
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False, index=True)
    direction_id = db.Column(db.Integer, db.ForeignKey("directions.id"), nullable=False, index=True)
    decision = db.Column(db.String(30), nullable=False, index=True)
    reason = db.Column(db.Text)
    source = db.Column(db.String(30), nullable=False, default="web")
    actor_tg_id = db.Column(db.BigInteger)
    actor_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    blocked_until = db.Column(db.DateTime, nullable=True, index=True)
    cleared_at = db.Column(db.DateTime, nullable=True)
    cleared_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    clear_reason = db.Column(db.Text)
