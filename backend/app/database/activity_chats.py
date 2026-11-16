"""Reusable Telegram group directory with legacy per-activity records for migration."""
from datetime import datetime
from .base import db


class ActivityChat(db.Model):
    __tablename__ = 'activity_chats'
    __bind_key__ = 'system'
    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(10), nullable=False)
    activity_id = db.Column(db.Integer, nullable=False)
    chat_id = db.Column(db.String(100), unique=True, nullable=False)
    title = db.Column(db.String(255), nullable=False)
    invite_link = db.Column(db.String(400), nullable=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('kind', 'activity_id', name='uq_activity_chat_one_per_activity'),)


class ActivityChatRemoval(db.Model):
    """Durable work for removing known participants after an activity closes."""
    __tablename__ = 'activity_chat_removals'
    __bind_key__ = 'system'
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.String(100), nullable=False)
    telegram_user_id = db.Column(db.BigInteger, nullable=False)
    status = db.Column(db.String(16), nullable=False, default='pending')
    attempts = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    last_error = db.Column(db.String(120))


class SharedActivityChat(db.Model):
    """Long-lived Telegram room shared by many events/readings, not owned by one."""
    __tablename__ = 'shared_activity_chats'
    __bind_key__ = 'system'
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.String(100), unique=True, nullable=False)
    title = db.Column(db.String(255), nullable=False)
    # event | science | all (mixed audience; only a superadmin may post in all)
    audience = db.Column(db.String(12), nullable=False, default='all')
    invite_link = db.Column(db.String(400))
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
