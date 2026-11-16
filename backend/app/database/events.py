from datetime import datetime
from sqlalchemy import func, or_
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
    publish_mode = db.Column(db.String(20), nullable=False, default="immediate")
    publish_at = db.Column(db.DateTime, nullable=True)
    is_published = db.Column(db.Boolean, nullable=False, default=False)
    # True means chat targets were explicitly chosen for this event, including an intentional empty set.
    chat_selection_explicit = db.Column(db.Boolean, nullable=False, default=False)
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
    platform = db.Column(db.String(15), nullable=False, default="telegram")
    chat_id = db.Column(db.String(100), nullable=False)
    title = db.Column(db.String(255))
    invite_link = db.Column(db.String(512))
    __table_args__ = (db.UniqueConstraint("quota_id", "platform", "chat_id", name="uq_event_quota_platform_chat"),)

class EventQuotaDecline(db.Model):
    """A student's formal refusal to participate in an event, including its reason."""
    __tablename__ = "event_quota_declines"
    __bind_key__ = "events"
    id = db.Column(db.Integer, primary_key=True)
    quota_id = db.Column(db.Integer, nullable=False, index=True)
    student_id = db.Column(db.Integer, nullable=False, index=True)
    reason = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (db.UniqueConstraint("quota_id", "student_id", name="uq_quota_decline_student"),)

class EventDay(db.Model):
    __tablename__ = "event_days"
    __bind_key__ = "events"
    __table_args__ = (db.Index("ix_event_days_quota_date", "quota_id", "date"),)
    id = db.Column(db.Integer, primary_key=True)
    quota_id = db.Column(db.Integer, db.ForeignKey("event_quotas.id"), nullable=False)
    date = db.Column(db.DateTime, nullable=False)
    daily_places = db.Column(db.Integer, nullable=False)
    quota = db.relationship("EventQuota", back_populates="days")
    participations = db.relationship("DayParticipation", back_populates="day", cascade="all, delete-orphan", order_by="DayParticipation.id")
    def current_count(self):
        # Reuse an already-loaded collection, but do not load every participation
        # row just to count it (common in the bot and quota admin page).
        loaded = self.__dict__.get("participations")
        if loaded is not None:
            return sum(1 for participation in loaded if participation.status != "cancelled")
        if self.id is None:
            return 0
        count = db.session.query(func.count(DayParticipation.id)).filter(
            DayParticipation.day_id == self.id,
            or_(DayParticipation.status.is_(None), DayParticipation.status != "cancelled"),
        ).scalar()
        return int(count or 0)

    def available_places(self):
        return max(0, (self.daily_places or 0) - self.current_count())

class DayParticipation(db.Model):
    __tablename__ = "day_participations"
    __bind_key__ = "events"
    __table_args__ = (
        db.Index("ix_day_participations_student_status", "student_id", "status"),
        db.Index("ix_day_participations_day_status", "day_id", "status"),
    )
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, nullable=False)
    day_id = db.Column(db.Integer, db.ForeignKey("event_days.id"), nullable=False)
    status = db.Column(db.String(20), default="registered")
    day = db.relationship("EventDay", back_populates="participations")
    @property
    def student(self):
        from .core import Student
        return Student.query.get(self.student_id)
