import enum, json, bcrypt
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

def hash_password(p): return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()
def verify_password(p, h): return bcrypt.checkpw(p.encode(), h.encode())

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
    db.Column('joined_at', db.DateTime, default=datetime.utcnow),
    db.Column('extra_data', db.Text) # JSON с ответами на вопросы
)

quota_directions = db.Table('quota_directions',
    db.Column('quota_id', db.Integer, db.ForeignKey('event_quotas.id'), primary_key=True),
    db.Column('direction_id', db.Integer, db.ForeignKey('directions.id'), primary_key=True)
)

# Таблица для дополнительных вопросов к направлениям
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
    requires_application = db.Column(db.Boolean, default=True) # Флаг: нужна ли заявка
    
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
    event_dates_json = db.Column(db.Text, nullable=False, default="[]") 
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
    
    def current_count(self): return len([p for p in self.participations if p.status != 'cancelled'])
    def available_places(self): return max(0, self.daily_places - self.current_count())

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
    
    directions = db.relationship("Direction", secondary=student_directions, back_populates="students")
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
        
        # Направления с флагом requires_application
        base_directions = [
            {"name": "Театральная студия", "code": "THEATER", "icon": "🎭", "color": "purple", "requires_application": True},
            {"name": "Вокальная студия", "code": "VOCAL", "icon": "🎤", "color": "pink", "requires_application": True},
            {"name": "Танцевальная студия ЭСТРАДА", "code": "DANCE_EST", "icon": "💃", "color": "rose", "requires_application": True},
            {"name": "Танцевальная студия Современные", "code": "DANCE_MOD", "icon": "", "color": "indigo", "requires_application": True},
            {"name": "Спортивный туризм", "code": "TOURISM", "icon": "⛺", "color": "green", "requires_application": True},
            {"name": "Студсовет", "code": "STUDCOUNCIL", "icon": "📢", "color": "blue", "requires_application": False},
            {"name": "Волейбол", "code": "VOLLEYBALL", "icon": "🏐", "color": "orange", "requires_application": True},
            {"name": "Футбол", "code": "FOOTBALL", "icon": "", "color": "emerald", "requires_application": True},
            {"name": "Шахматы", "code": "CHESS", "icon": "♟️", "color": "slate", "requires_application": True}
        ]
        
        for d in base_directions:
            if not Direction.query.filter_by(code=d["code"]).first():
                db.session.add(Direction(**d))
        db.session.commit()
        print("✅ База данных обновлена")