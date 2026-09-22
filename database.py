import enum
from datetime import datetime
import json
import bcrypt
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))

class UserRole(str, enum.Enum):
    SUPER_ADMIN = "super_admin"
    COORDINATOR = "coordinator"

class StudentStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ACTIVE = "active"

# Таблицы связей Many-to-Many
student_directions = db.Table('student_directions',
    db.Column('student_id', db.Integer, db.ForeignKey('students.id'), primary_key=True),
    db.Column('direction_id', db.Integer, db.ForeignKey('directions.id'), primary_key=True),
    db.Column('joined_at', db.DateTime, default=datetime.utcnow)
)

quota_directions = db.Table('quota_directions',
    db.Column('quota_id', db.Integer, db.ForeignKey('event_quotas.id'), primary_key=True),
    db.Column('direction_id', db.Integer, db.ForeignKey('directions.id'), primary_key=True)
)

class Direction(db.Model):
    __tablename__ = "directions"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    code = db.Column(db.String(50), nullable=False)
    icon = db.Column(db.String(50))
    description = db.Column(db.Text)
    color = db.Column(db.String(50), default="blue")
    
    quotas = db.relationship("EventQuota", secondary=quota_directions, back_populates="directions")
    groups = db.relationship("VolunteerGroup", back_populates="direction")
    students = db.relationship("Student", secondary=student_directions, back_populates="directions")

class VolunteerGroup(db.Model):
    __tablename__ = "volunteer_groups"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    direction_id = db.Column(db.Integer, db.ForeignKey("directions.id"), nullable=False)
    curator_name = db.Column(db.String(255))
    
    direction = db.relationship("Direction", back_populates="groups")
    members = db.relationship("Student", back_populates="volunteer_group")
    
    def current_size(self):
        return len([s for s in self.members if s.status == StudentStatus.ACTIVE.value])

# ОСНОВНОЕ МЕРОПРИЯТИЕ (Общая информация)
class EventQuota(db.Model):
    __tablename__ = "event_quotas"
    
    id = db.Column(db.Integer, primary_key=True)
    event_title = db.Column(db.String(255), nullable=False)
    event_description = db.Column(db.Text)
    
    # Детали мероприятия
    location = db.Column(db.String(255))
    time_range = db.Column(db.String(100))
    dress_code = db.Column(db.String(255))
    functionality = db.Column(db.Text)
    
    directions = db.relationship("Direction", secondary=quota_directions, back_populates="quotas")
    days = db.relationship("EventDay", back_populates="quota", cascade="all, delete-orphan", order_by="EventDay.date")

# ДЕНЬ МЕРОПРИЯТИЯ (Конкретная дата и места)
class EventDay(db.Model):
    __tablename__ = "event_days"
    
    id = db.Column(db.Integer, primary_key=True)
    quota_id = db.Column(db.Integer, db.ForeignKey("event_quotas.id"), nullable=False)
    date = db.Column(db.DateTime, nullable=False)
    daily_places = db.Column(db.Integer, nullable=False) # Мест именно на этот день
    
    quota = db.relationship("EventQuota", back_populates="days")
    participations = db.relationship("DayParticipation", back_populates="day", cascade="all, delete-orphan")
    
    def current_count(self):
        return len([p for p in self.participations if p.status != 'cancelled'])
    
    def available_places(self):
        return max(0, self.daily_places - self.current_count())

# УЧАСТИЕ В КОНКРЕТНЫЙ ДЕНЬ (Замена старой Participant)
class DayParticipation(db.Model):
    __tablename__ = "day_participations"
    
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    day_id = db.Column(db.Integer, db.ForeignKey("event_days.id"), nullable=False)
    status = db.Column(db.String(20), default="registered") # registered, attended, absent, cancelled
    
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
    group_id = db.Column(db.Integer, db.ForeignKey("volunteer_groups.id"), nullable=True)
    status = db.Column(db.String(30), default=StudentStatus.PENDING.value)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    directions = db.relationship("Direction", secondary=student_directions, back_populates="students")
    volunteer_group = db.relationship("VolunteerGroup", back_populates="members")
    participations = db.relationship("DayParticipation", back_populates="student", cascade="all, delete-orphan")

class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(50), nullable=False)

def init_db(app):
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(email="admin@uni.local").first():
            admin = User(email="admin@uni.local", password_hash=hash_password("admin123"), role=UserRole.SUPER_ADMIN.value)
            db.session.add(admin)
        
        base_directions = [
            {"name": "Спорт", "code": "SPORT", "icon": "🏆", "description": "Спортивно-оздоровительное", "color": "green"},
            {"name": "Культура", "code": "CULTURE", "icon": "🎭", "description": "Художественно-эстетическое", "color": "purple"},
            {"name": "Волонтерство", "code": "VOLUNTEER", "icon": "🤝", "description": "Социально-значимая деятельность", "color": "blue"},
            {"name": "Наука", "code": "SCIENCE", "icon": "🔬", "description": "Интеллектуально-познавательное", "color": "indigo"},
            {"name": "Прочее", "code": "OTHER", "icon": "", "description": "Другие виды деятельности", "color": "gray"}
        ]
        for d in base_directions:
            if not Direction.query.filter_by(code=d["code"]).first():
                db.session.add(Direction(**d))
        db.session.commit()
        print("✅ База данных инициализирована")
        