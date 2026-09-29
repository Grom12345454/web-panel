import enum
from datetime import datetime
import bcrypt
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


class UserRole(str, enum.Enum):
    SUPER_ADMIN = "super_admin"
    OPERATOR = "operator"
    LEADER = "leader"


class EducationType(str, enum.Enum):
    COLLEGE = "college"
    INSTITUTE = "institute"


class DirectionStatus(str, enum.Enum):
    PENDING = "pending"
    INTERVIEW = "interview"
    APPROVED = "approved"
    REJECTED = "rejected"
    ACTIVE = "active"

student_directions = db.Table(
    "student_directions",
    db.Column("student_id", db.Integer, db.ForeignKey("students.id"), primary_key=True),
    db.Column("direction_id", db.Integer, db.ForeignKey("directions.id"), primary_key=True),
    db.Column("joined_at", db.DateTime, default=datetime.utcnow),
    db.Column("extra_data", db.Text),
    db.Column("status", db.String(30), default=DirectionStatus.PENDING.value),
)
