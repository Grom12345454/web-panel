"""Messenger accounts and connected chats; platform IDs are NOT student IDs."""
from datetime import datetime
from .base import db


class MessengerIdentity(db.Model):
    __tablename__ = 'messenger_identities'
    __bind_key__ = 'system'
    id = db.Column(db.Integer, primary_key=True)
    platform = db.Column(db.String(15), nullable=False)
    external_user_id = db.Column(db.String(100), nullable=False)
    student_id = db.Column(db.Integer, nullable=False, index=True)
    public_username = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (db.UniqueConstraint('platform', 'external_user_id', name='uq_messenger_external_identity'),)


class MessengerLinkCode(db.Model):
    __tablename__ = 'messenger_link_codes'
    __bind_key__ = 'system'
    id = db.Column(db.Integer, primary_key=True)
    code_hash = db.Column(db.String(64), unique=True, nullable=False)
    student_id = db.Column(db.Integer, nullable=False, index=True)
    # Restrict a new confirmation code to the selected destination messenger.
    target_platform = db.Column(db.String(15), nullable=True)
    expected_handle = db.Column(db.String(100), nullable=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime)
    # A code creates a pending claim, not an authenticated connection.
    # The student who issued the code must explicitly approve or reject it.
    pending_external_user_id = db.Column(db.String(100), nullable=True)
    pending_public_username = db.Column(db.String(100), nullable=True)
    requested_at = db.Column(db.DateTime, nullable=True)
    rejected_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class MessengerChat(db.Model):
    __tablename__ = 'messenger_chats'
    __bind_key__ = 'system'
    id = db.Column(db.Integer, primary_key=True)
    platform = db.Column(db.String(15), nullable=False)
    direction_id = db.Column(db.Integer, nullable=False, index=True)
    chat_id = db.Column(db.String(100), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    education_type = db.Column(db.String(20), nullable=False, default='all')
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    __table_args__ = (db.UniqueConstraint('platform', 'direction_id', 'chat_id', name='uq_messenger_direction_chat'),)


class MessengerChatCandidate(db.Model):
    """Chat observed by a bot on /chatid; observation never grants a binding."""
    __tablename__ = 'messenger_chat_candidates'
    __bind_key__ = 'system'
    id = db.Column(db.Integer, primary_key=True)
    platform = db.Column(db.String(15), nullable=False)
    chat_id = db.Column(db.String(100), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    last_seen_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (db.UniqueConstraint('platform', 'chat_id', name='uq_messenger_chat_candidate'),)
