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


class StudentLeadership(db.Model):
    __tablename__ = "student_leadership"
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    direction_id = db.Column(db.Integer, db.ForeignKey("directions.id"), nullable=False)
    education_type = db.Column(db.String(20), default=EducationType.INSTITUTE.value, nullable=False)
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
