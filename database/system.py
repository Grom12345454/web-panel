from datetime import datetime
from .base import db
class NotificationTemplate(db.Model):
    __tablename__ = "notification_templates"
    __bind_key__ = "system"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    template_text = db.Column(db.Text, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
class ChatMessageLog(db.Model):
    __tablename__ = "chat_message_logs"
    __bind_key__ = "system"
    id = db.Column(db.Integer, primary_key=True)
    direction_id = db.Column(db.Integer, nullable=False)
    chat_id = db.Column(db.String(100), nullable=False)
    sender_user_id = db.Column(db.Integer, nullable=True)
    message_text = db.Column(db.Text, nullable=False)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    success = db.Column(db.Boolean, default=False, nullable=False)
    error = db.Column(db.Text)

class StudentInviteLink(db.Model):
    __tablename__ = "student_invite_links"
    __bind_key__ = "system"
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, nullable=False, index=True)
    direction_id = db.Column(db.Integer, nullable=False, index=True)
    chat_id = db.Column(db.String(100), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    invite_link = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (db.UniqueConstraint("student_id", "direction_id", "chat_id", name="uq_student_direction_chat_invite"),)
