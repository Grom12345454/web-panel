import enum
from datetime import datetime
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
    ACTIVE = "active" # Активный участник мероприятий/отрядов

# НАПРАВЛЕНИЯ ВОСПИТАТЕЛЬНОЙ РАБОТЫ
class Direction(db.Model):
    __tablename__ = "directions"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False) # Спорт, Волонтерство...
    code = db.Column(db.String(50), nullable=False)  # SPORT, VOLUNTEER...
    description = db.Column(db.Text)
    
    quotas = db.relationship("EventQuota", back_populates="direction")
    students = db.relationship("Student", back_populates="direction")
    groups = db.relationship("VolunteerGroup", back_populates="direction")

# ВОЛОНТЕРСКИЕ / СПОРТИВНЫЕ ОТРЯДЫ
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

# КВОТЫ НА МЕРОПРИЯТИЯ ПО НАПРАВЛЕНИЯМ
class EventQuota(db.Model):
    __tablename__ = "event_quotas"
    id = db.Column(db.Integer, primary_key=True)
    event_title = db.Column(db.String(255), nullable=False)
    event_description = db.Column(db.Text)
    event_date = db.Column(db.DateTime, nullable=False)
    category = db.Column(db.String(50), default="other")
    
    direction_id = db.Column(db.Integer, db.ForeignKey("directions.id"), nullable=False)
    total_places = db.Column(db.Integer, nullable=False)
    
    direction = db.relationship("Direction", back_populates="quotas")
    participants = db.relationship("Participant", back_populates="quota", cascade="all, delete-orphan")

    def current_count(self):
        return len([p for p in self.participants if p.status != 'cancelled'])

    def available_places(self):
        return max(0, self.total_places - self.current_count())

class Participant(db.Model):
    __tablename__ = "participants"
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    quota_id = db.Column(db.Integer, db.ForeignKey("event_quotas.id"), nullable=False)
    status = db.Column(db.String(20), default="registered")
    
    student = db.relationship("Student", back_populates="participations")
    quota = db.relationship("EventQuota", back_populates="participants")

class Student(db.Model):
    __tablename__ = "students"
    id = db.Column(db.Integer, primary_key=True)
    tg_id = db.Column(db.BigInteger, unique=True, nullable=False)
    full_name = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(30))
    email = db.Column(db.String(255))
    
    direction_id = db.Column(db.Integer, db.ForeignKey("directions.id"), nullable=True)
    group_id = db.Column(db.Integer, db.ForeignKey("volunteer_groups.id"), nullable=True)
    
    status = db.Column(db.String(30), default=StudentStatus.PENDING.value)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    direction = db.relationship("Direction", back_populates="students")
    volunteer_group = db.relationship("VolunteerGroup", back_populates="members")
    participations = db.relationship("Participant", back_populates="student", cascade="all, delete-orphan")

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
                {"name": "Гражданско-патриотическое", "code": "PATRIOT"},
                {"name": "Спортивно-оздоровительное", "code": "SPORT"},
                {"name": "Трудовое", "code": "LABOR"},
                {"name": "Интеллектуально-познавательное", "code": "INTELLECT"},
                {"name": "Художественно-эстетическое", "code": "ART"},
                {"name": "Экологическое", "code": "ECO"}
            ]
            for d in base_directions:
                if not Direction.query.filter_by(code=d["code"]).first():
                    db.session.add(Direction(**d))
                    
            db.session.commit()
            print("✅ Админ и направления созданы")