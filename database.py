import enum
import json
import bcrypt
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

def hash_password(p): 
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()

def verify_password(p, h): 
    return bcrypt.checkpw(p.encode(), h.encode())

class UserRole(str, enum.Enum):
    SUPER_ADMIN = "super_admin"
    # Роль COORDINATOR удалена полностью

class StudentStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ACTIVE = "active"

# Таблицы связей
student_directions = db.Table('student_directions',
    db.Column('student_id', db.Integer, db.ForeignKey('students.id'), primary_key=True),
    db.Column('direction_id', db.Integer, db.ForeignKey('directions.id'), primary_key=True),
    db.Column('joined_at', db.DateTime, default=datetime.utcnow),
    db.Column('extra_data', db.Text)
)

quota_directions = db.Table('quota_directions',
    db.Column('quota_id', db.Integer, db.ForeignKey('event_quotas.id'), primary_key=True),
    db.Column('direction_id', db.Integer, db.ForeignKey('directions.id'), primary_key=True)
)

class NotificationTemplate(db.Model):
    __tablename__ = "notification_templates"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    template_text = db.Column(db.Text, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class StudentLeadership(db.Model):
    __tablename__ = "student_leadership"
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    direction_id = db.Column(db.Integer, db.ForeignKey('directions.id'), nullable=False)
    position_name = db.Column(db.String(255), nullable=False)
    
    student = db.relationship("Student", backref="leaderships")
    direction = db.relationship("Direction", backref="leaders")

class DirectionQuestion(db.Model):
    __tablename__ = "direction_questions"
    id = db.Column(db.Integer, primary_key=True)
    direction_id = db.Column(db.Integer, db.ForeignKey('directions.id'), nullable=False)
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
    
    quotas = db.relationship("EventQuota", secondary=quota_directions, back_populates="directions")
    students = db.relationship("Student", secondary=student_directions, back_populates="directions")
    questions = db.relationship("DirectionQuestion", back_populates="direction", order_by="DirectionQuestion.sort_order")

class EventQuota(db.Model):
    __tablename__ = "event_quotas"
    id = db.Column(db.Integer, primary_key=True)
    event_title = db.Column(db.String(255), nullable=False)
    event_description = db.Column(db.Text)
    location = db.Column(db.String(255))
    time_range = db.Column(db.String(100))
    dress_code = db.Column(db.String(255))
    functionality = db.Column(db.Text)
    total_places = db.Column(db.Integer, nullable=False)
    
    directions = db.relationship("Direction", secondary=quota_directions, back_populates="quotas")
    days = db.relationship("EventDay", back_populates="quota", cascade="all, delete-orphan", order_by="EventDay.date")

class EventDay(db.Model):
    __tablename__ = "event_days"
    id = db.Column(db.Integer, primary_key=True)
    quota_id = db.Column(db.Integer, db.ForeignKey("event_quotas.id"), nullable=False)
    date = db.Column(db.DateTime, nullable=False)
    daily_places = db.Column(db.Integer, nullable=False)
    
    quota = db.relationship("EventQuota", back_populates="days")
    participations = db.relationship("DayParticipation", back_populates="day", cascade="all, delete-orphan")
    
    def current_count(self): 
        return len([p for p in self.participations if p.status != 'cancelled'])
    
    def available_places(self): 
        return max(0, self.daily_places - self.current_count())

class DayParticipation(db.Model):
    __tablename__ = "day_participations"
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    day_id = db.Column(db.Integer, db.ForeignKey("event_days.id"), nullable=False)
    status = db.Column(db.String(20), default="registered")
    
    student = db.relationship("Student", back_populates="participations")
    day = db.relationship("EventDay", back_populates="participations")

class Student(db.Model):
    __tablename__ = "students"
    id = db.Column(db.Integer, primary_key=True)
    tg_id = db.Column(db.BigInteger, unique=True, nullable=False)
    full_name = db.Column(db.String(255), nullable=False)
    group = db.Column(db.String(50))
    phone = db.Column(db.String(30))
    email = db.Column(db.String(255))
    status = db.Column(db.String(30), default=StudentStatus.PENDING.value)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    interview_date = db.Column(db.DateTime)
    interview_location = db.Column(db.String(255))
    
    directions = db.relationship("Direction", secondary=student_directions, back_populates="students")
    participations = db.relationship("DayParticipation", back_populates="student", cascade="all, delete-orphan")

# ✅ МОДЕЛЬ USER БЕЗ РОЛИ COORDINATOR
class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(50), nullable=False)
    tg_id = db.Column(db.BigInteger, unique=True, nullable=True) 
    
    assigned_direction_id = db.Column(db.Integer, db.ForeignKey('directions.id'))
    assigned_direction = db.relationship("Direction", foreign_keys=[assigned_direction_id])

def init_db(app):
    with app.app_context():
        db.create_all()
        
        # Создаем супер-админа, если его нет
        if not User.query.filter_by(email="admin@uni.local").first():
            admin = User(email="admin@uni.local", password_hash=hash_password("admin123"), role=UserRole.SUPER_ADMIN.value)
            db.session.add(admin)
        
        # Базовые направления
        base_directions = [
            {"name": "Театральная студия", "code": "THEATER", "icon": "", "color": "purple"},
            {"name": "Вокальная студия", "code": "VOCAL", "icon": "🎤", "color": "pink"},
            {"name": "Танцевальная студия ЭСТРАДА", "code": "DANCE_EST", "icon": "", "color": "rose"},
            {"name": "Танцевальная студия Современные", "code": "DANCE_MOD", "icon": "", "color": "indigo"},
            {"name": "Спортивный туризм", "code": "TOURISM", "icon": "", "color": "green"},
            {"name": "Студсовет", "code": "STUDCOUNCIL", "icon": "", "color": "blue"},
            {"name": "Волейбол", "code": "VOLLEYBALL", "icon": "", "color": "orange"},
            {"name": "Футбол", "code": "FOOTBALL", "icon": "", "color": "emerald"},
            {"name": "Шахматы", "code": "CHESS", "icon": "♟️", "color": "slate"}
        ]
        
        for d in base_directions:
            if not Direction.query.filter_by(code=d["code"]).first():
                db.session.add(Direction(**d))
        
        # Создание дефолтных шаблонов уведомлений
        default_templates = {
            "leadership_assign": "🎉 <b>Поздравляем с назначением!</b>\n\nВы назначены на должность:\n<b>{position}</b>\n\nв направлении:\n{direction}\n\nЖелаем успехов! 🚀",
            "leadership_remove": "⚠️ <b>Изменение статуса</b>\n\nВы сняты с должности:\n<b>{position}</b>\n\nв направлении:\n{direction}\n\nПричина: {reason}",
            "interview_invite": " <b>Приглашение на собеседование</b>\n\nЗдравствуйте, <b>{student_name}</b>!\n\nВас приглашают в направление <b>{direction}</b>.\n\n <b>Дата:</b> {date}\n📍 <b>Место:</b> {location}\n\nПодтвердите явку кнопкой ниже 👇",
            "activation": " <b>Поздравляем! Вы приняты!</b>\n\nЗдравствуйте, <b>{student_name}</b>!\n\nВаша заявка прошла проверку.\n\n<b>Ваши направления:</b>\n{directions}\n\nТеперь вы можете добавить кружки 👇"
        }
        
        for key, text in default_templates.items():
            if not NotificationTemplate.query.filter_by(key=key).first():
                db.session.add(NotificationTemplate(key=key, template_text=text))
                
        db.session.commit()
        print("✅ База данных обновлена")