from datetime import datetime, timedelta
from .base import db
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
        from .core import Direction
        return Direction.query.get(self.direction_id)
    @property
    def end_at(self):
        return self.starts_at + timedelta(minutes=self.duration_minutes or 0)
    @property
    def formatted_date(self): return self.starts_at.strftime("%d.%m.%Y")
    @property
    def formatted_time(self): return self.starts_at.strftime("%H:%M")
