from datetime import datetime
from .base import db

class QuotaDirection(db.Model):
    __tablename__ = "quota_directions"
    __bind_key__ = "events"
    quota_id = db.Column(db.Integer, primary_key=True)
    direction_id = db.Column(db.Integer, nullable=False, primary_key=True)

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
    days = db.relationship("EventDay", back_populates="quota", cascade="all, delete-orphan", order_by="EventDay.date")
    @property
    def directions(self):
        from .helpers import get_quota_directions
        return get_quota_directions(self.id)

class EventQuotaChat(db.Model):
    __tablename__ = "event_quota_chats"
    __bind_key__ = "events"
    id = db.Column(db.Integer, primary_key=True)
    quota_id = db.Column(db.Integer, nullable=False, index=True)
    direction_id = db.Column(db.Integer, nullable=False, index=True)
    chat_id = db.Column(db.String(100), nullable=False)
    __table_args__ = (db.UniqueConstraint("quota_id", "chat_id", name="uq_event_quota_chat"),)

class EventDay(db.Model):
    __tablename__ = "event_days"
    __bind_key__ = "events"
    id = db.Column(db.Integer, primary_key=True)
    quota_id = db.Column(db.Integer, db.ForeignKey("event_quotas.id"), nullable=False)
    date = db.Column(db.DateTime, nullable=False)
    daily_places = db.Column(db.Integer, nullable=False)
    quota = db.relationship("EventQuota", back_populates="days")
    participations = db.relationship("DayParticipation", back_populates="day", cascade="all, delete-orphan", order_by="DayParticipation.id")
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
        from .core import Student
        return Student.query.get(self.student_id)
