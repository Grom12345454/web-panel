"""Private archived orders attached to completed events or scientific readings.

The event quota records are in a separate SQLite bind, so we intentionally store
(target_kind, target_id) instead of a cross-database foreign key.
"""
from datetime import datetime
from .base import db


class AdministrativeOrder(db.Model):
    __tablename__ = 'administrative_orders'
    id = db.Column(db.Integer, primary_key=True)
    target_kind = db.Column(db.String(12), nullable=False, index=True)  # event/science
    target_id = db.Column(db.Integer, nullable=False, index=True)
    original_name = db.Column(db.String(255), nullable=False)
    stored_name = db.Column(db.String(70), nullable=False, unique=True)
    mime_type = db.Column(db.String(100), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    uploaded_by = db.Column(db.Integer, nullable=False)
    uploaded_by_name = db.Column(db.String(255), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (db.Index('ix_admin_orders_target', 'target_kind', 'target_id'),)


class OrderDeliveryJob(db.Model):
    """One durable Telegram document delivery attempt per recipient and order.

    No attachment bytes are stored in the queue; file paths are always resolved
    using the server-generated `stored_name` of the related private order.
    """
    __tablename__ = 'order_delivery_jobs'
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('administrative_orders.id', ondelete='CASCADE'), nullable=False, index=True)
    student_id = db.Column(db.Integer, nullable=False)
    platform = db.Column(db.String(12), nullable=False, default='telegram')
    recipient_id = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(16), nullable=False, default='pending')
    attempts = db.Column(db.Integer, nullable=False, default=0)
    next_attempt_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    locked_until = db.Column(db.DateTime)
    last_error = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    delivered_at = db.Column(db.DateTime)
    __table_args__ = (db.UniqueConstraint('order_id', 'student_id', 'platform', name='uq_order_student_platform'),)
