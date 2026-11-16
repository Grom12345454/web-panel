"""Accounts scoped to departments and scientific-reading submissions."""
from datetime import datetime
import json
from .base import db


class StaffGrant(db.Model):
    __tablename__ = 'staff_grants'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    direction_id = db.Column(db.Integer, db.ForeignKey('directions.id'), nullable=False)
    section = db.Column(db.String(30), nullable=False)
    access = db.Column(db.String(10), nullable=False, default='view')
    __table_args__ = (db.UniqueConstraint('user_id', 'direction_id', 'section', name='uq_staff_grant'),)


class ScienceReading(db.Model):
    __tablename__ = 'science_readings'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    # The legacy SQLite column is named `category`.  It represents the
    # scientific subject area, NOT a direction of the student council.  Keep
    # the physical column so upgrades never lose existing readings.
    category = db.Column(db.String(80), nullable=False)
    science_directions_json = db.Column(db.Text, nullable=True)  # Additional science directions; legacy category remains the first.
    direction_id = db.Column(db.Integer, db.ForeignKey('directions.id'), nullable=True, index=True)
    description = db.Column(db.Text, default='')
    held_at = db.Column(db.DateTime, nullable=True)
    deadline = db.Column(db.DateTime, nullable=True)
    is_open = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    direction = db.relationship('Direction')

    @property
    def science_direction(self):
        """The reading's independent scientific direction (topic/discipline)."""
        return self.category

    @science_direction.setter
    def science_direction(self, value):
        self.category = value

    @property
    def science_directions(self):
        """Science topics are independent of council directions (backward compatible)."""
        try:
            values = json.loads(self.science_directions_json or 'null')
        except (ValueError, TypeError):
            values = None
        if not isinstance(values, list):
            return [self.category] if self.category else []
        result = []
        for item in values:
            if isinstance(item, str) and item.strip() and item.casefold() not in {v.casefold() for v in result}:
                result.append(item.strip())
        return result or ([self.category] if self.category else [])

    def set_science_directions(self, names):
        clean = []
        for name in names:
            name = ' '.join(str(name).split())
            if not 3 <= len(name) <= 80:
                raise ValueError('Длина научного направления должна быть от 3 до 80 символов.')
            if name.casefold() not in {entry.casefold() for entry in clean}:
                clean.append(name)
        if not 1 <= len(clean) <= 12:
            raise ValueError('Выберите от одного до 12 научных направлений.')
        self.category = clean[0]
        self.science_directions_json = json.dumps(clean, ensure_ascii=False)


class ScienceSubmission(db.Model):
    __tablename__ = 'science_submissions'
    id = db.Column(db.Integer, primary_key=True)
    reading_id = db.Column(db.Integer, db.ForeignKey('science_readings.id'), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False, index=True)
    direction_id = db.Column(db.Integer, db.ForeignKey('directions.id'), nullable=True, index=True)
    article_title = db.Column(db.String(250), nullable=False)
    author_count = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='pending_authors')
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    reading = db.relationship('ScienceReading')
    direction = db.relationship('Direction')
    student = db.relationship('Student')
    authors = db.relationship('ScienceAuthor', cascade='all, delete-orphan', back_populates='submission', order_by='ScienceAuthor.position')


class ScienceAuthor(db.Model):
    __tablename__ = 'science_authors'
    id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(db.Integer, db.ForeignKey('science_submissions.id', ondelete='CASCADE'), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False, index=True)
    position = db.Column(db.Integer, nullable=False)
    decision = db.Column(db.String(16), nullable=False, default='pending')
    decided_at = db.Column(db.DateTime)
    submission = db.relationship('ScienceSubmission', back_populates='authors')
    student = db.relationship('Student')
    __table_args__ = (db.UniqueConstraint('submission_id', 'student_id', name='uq_science_submission_student'),)


class ScienceChatMessage(db.Model):
    """One shared moderated conversation per reading; reading_id is room identity.

    No separate Telegram group is created: Telegram bots cannot create group
    chats. These records are accessible through the panel, Student App and
    verified bot private-message commands.
    """
    __tablename__ = 'science_chat_messages'
    id = db.Column(db.Integer, primary_key=True)
    reading_id = db.Column(db.Integer, db.ForeignKey('science_readings.id', ondelete='CASCADE'), nullable=False, index=True)
    student_id = db.Column(db.Integer, nullable=True, index=True)
    staff_user_id = db.Column(db.Integer, nullable=True, index=True)
    author_name = db.Column(db.String(255), nullable=False)
    body = db.Column(db.String(1500), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (db.CheckConstraint('(student_id IS NOT NULL AND staff_user_id IS NULL) OR (student_id IS NULL AND staff_user_id IS NOT NULL)', name='ck_science_chat_author'),)
