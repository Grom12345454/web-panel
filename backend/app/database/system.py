from datetime import datetime
from .base import db
class NotificationTemplate(db.Model):
    __tablename__ = "notification_templates"
    __bind_key__ = "system"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    template_text = db.Column(db.Text, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
class PortalSetting(db.Model):
    """Small persistent settings shared by the web panel and Student App."""
    __tablename__ = "portal_settings"
    __bind_key__ = "system"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.String(255), nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

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

class StudentActivity(db.Model):
    """Audit trail for student and administrative actions."""
    __tablename__ = "student_activity"
    __bind_key__ = "system"
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, nullable=True, index=True)
    direction_id = db.Column(db.Integer, nullable=True, index=True)
    quota_id = db.Column(db.Integer, nullable=True, index=True)
    action = db.Column(db.String(80), nullable=False, index=True)
    description = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

def record_activity(action, description, student_id=None, direction_id=None, quota_id=None):
    db.session.add(StudentActivity(action=action, description=description, student_id=student_id,
                                   direction_id=direction_id, quota_id=quota_id))
    _activity_notification(action, description, student_id, direction_id, quota_id)

class CompetitionAnnouncement(db.Model):
    __tablename__ = "competition_announcements"
    __bind_key__ = "system"
    id = db.Column(db.Integer, primary_key=True)
    quota_id = db.Column(db.Integer, nullable=True, index=True)
    title = db.Column(db.String(255), nullable=False)
    body = db.Column(db.Text, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class HttpAuditLog(db.Model):
    """Audit trail for authenticated staff requests and failed HTTP/API requests."""
    __tablename__ = "http_audit_logs"
    __bind_key__ = "system"

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.String(64), nullable=False, index=True)
    actor_user_id = db.Column(db.Integer, nullable=True, index=True)
    actor_login = db.Column(db.String(255), nullable=True, index=True)
    actor_role = db.Column(db.String(40), nullable=True)
    action = db.Column(db.String(80), nullable=False, index=True)
    method = db.Column(db.String(10), nullable=False)
    path = db.Column(db.String(512), nullable=False)
    status_code = db.Column(db.Integer, nullable=False, index=True)
    duration_ms = db.Column(db.Float, nullable=False, default=0.0)
    ip_address = db.Column(db.String(45), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)


class AdminReportSignature(db.Model):
    """Immutable audit record for a PDF generated under the chief-admin account."""
    __tablename__ = "admin_report_signatures"
    __bind_key__ = "system"
    id = db.Column(db.Integer, primary_key=True)
    signature_code = db.Column(db.String(40), nullable=False, unique=True, index=True)
    report_type = db.Column(db.String(30), nullable=False, index=True)
    report_key = db.Column(db.String(120), nullable=False, index=True)
    report_title = db.Column(db.String(255), nullable=False)
    signer_user_id = db.Column(db.Integer, nullable=False, index=True)
    signer_name = db.Column(db.String(255), nullable=False)
    signer_login = db.Column(db.String(255), nullable=False)
    content_sha256 = db.Column(db.String(64), nullable=False)
    document_sha256 = db.Column(db.String(64), nullable=False, default="")
    signed_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)


class BotJournalEvent(db.Model):
    """Operational transport metadata for Telegram, VK and MAX; no message content."""
    __tablename__ = "bot_journal_events"
    __bind_key__ = "system"
    id = db.Column(db.Integer, primary_key=True)
    platform = db.Column(db.String(20), nullable=False, index=True)
    kind = db.Column(db.String(20), nullable=False, index=True)
    action = db.Column(db.String(72), nullable=False, index=True)
    status = db.Column(db.String(16), nullable=False, index=True)
    actor_alias = db.Column(db.String(16), nullable=True, index=True)
    summary = db.Column(db.String(150), nullable=False, default="")
    duration_ms = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, index=True, default=datetime.utcnow)


class BotDeliveryJob(db.Model):
    """Recoverable chat-publication queue; not exposed to student-facing APIs."""
    __tablename__ = "bot_delivery_jobs"
    __bind_key__ = "system"
    id = db.Column(db.Integer, primary_key=True)
    delivery_key = db.Column(db.String(64), unique=True, nullable=False)
    source_type = db.Column(db.String(20), nullable=True, index=True)  # lesson / event
    source_id = db.Column(db.Integer, nullable=True, index=True)
    last_attempt_at = db.Column(db.DateTime, nullable=True)
    platform = db.Column(db.String(16), nullable=False)
    recipient_id = db.Column(db.String(100), nullable=False)
    is_chat = db.Column(db.Boolean, nullable=False, default=True)
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(16), nullable=False, default="pending", index=True)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    last_error = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    next_attempt_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    locked_until = db.Column(db.DateTime)
    delivered_at = db.Column(db.DateTime)


class SiteNotification(db.Model):
    """Persistent in-portal alert; delivery is resolved against live permissions."""
    __tablename__ = "site_notifications"
    __bind_key__ = "system"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(180), nullable=False)
    body = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(25), nullable=False, index=True, default="system")
    severity = db.Column(db.String(20), nullable=False, default="info")
    audience = db.Column(db.String(20), nullable=False, default="managers")
    education_type = db.Column(db.String(20), nullable=True)
    student_id = db.Column(db.Integer, nullable=True)
    direction_id = db.Column(db.Integer, nullable=True, index=True)
    link_path = db.Column(db.String(200), nullable=True)
    creator_user_id = db.Column(db.Integer, nullable=True)
    publication_key = db.Column(db.String(64), nullable=True, unique=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)


class SiteNotificationRead(db.Model):
    """Each account has an independent read/unread state."""
    __tablename__ = "site_notification_reads"
    __bind_key__ = "system"
    id = db.Column(db.Integer, primary_key=True)
    notification_id = db.Column(db.Integer, db.ForeignKey("site_notifications.id"), nullable=False)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    read_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (db.UniqueConstraint("notification_id", "user_id", name="uq_notification_read_user"),)


_ACTIVITY_ALERTS = {
    "bot_application_submitted": ("applications", "Новая заявка", "info"),
    "application_submitted": ("applications", "Новый участник", "info"),
    "application_status_changed": ("applications", "Решение по заявке", "success"),
    "application_withdrawn": ("applications", "Изменён состав направления", "warning"),
}


def _activity_notification(action, description, student_id, direction_id, quota_id=None):
    """Add to the same transaction as an audited action, without Telegram dependency."""
    metadata = _ACTIVITY_ALERTS.get(action)
    if action.startswith('science_'):
        metadata = ('science', 'Научная деятельность', 'info')
    if metadata is None:
        if action.startswith(("quota_", "event_")) and not action.startswith("quota_decline"):
            metadata = ("events", "Обновление мероприятия", "info")
        elif action.startswith("lesson_"):
            metadata = ("lessons", "Обновление занятия", "info")
        elif action.startswith(("leadership_", "event_lead_")):
            metadata = ("leadership", "Изменение руководства", "info")
    if metadata is None:
        return
    category, title, severity = metadata
    direction_ids = [direction_id]
    if category == "events" and quota_id and not direction_id:
        # Quota metadata lives in the events bind; fan out only to its directions.
        from .events import QuotaDirection
        direction_ids = [row.direction_id for row in QuotaDirection.query.filter_by(quota_id=quota_id).all()] or [None]
    for target_direction in dict.fromkeys(direction_ids):
        path = (f"/directions/{target_direction}" if target_direction and category == "applications"
                else "/calendar" if category in {"events", "lessons"} else "/notifications")
        db.session.add(SiteNotification(
            title=title, body=(description or title)[:1500], category=category,
            severity=severity, audience="managers", student_id=student_id,
            direction_id=target_direction, link_path=path,
        ))


class StaffIncidentCase(db.Model):
    """Persisted SOC case metadata; evidence remains immutable HttpAuditLog rows."""
    __tablename__ = "staff_incident_cases"
    __bind_key__ = "system"
    id = db.Column(db.Integer, primary_key=True)
    fingerprint = db.Column(db.String(64), nullable=False, unique=True, index=True)
    rule_key = db.Column(db.String(64), nullable=False, index=True)
    title = db.Column(db.String(180), nullable=False)
    summary = db.Column(db.Text, nullable=False)
    severity = db.Column(db.String(12), nullable=False, default="medium", index=True)
    confidence = db.Column(db.String(12), nullable=False, default="medium")
    status = db.Column(db.String(20), nullable=False, default="open", index=True)
    basis = db.Column(db.Text, nullable=False)
    actor_user_id = db.Column(db.Integer, nullable=True, index=True)
    actor_login = db.Column(db.String(255), nullable=True, index=True)
    actor_role = db.Column(db.String(40), nullable=True)
    ip_address = db.Column(db.String(45), nullable=True, index=True)
    source_ips_json = db.Column(db.Text, nullable=False, default="[]")
    evidence_ids_json = db.Column(db.Text, nullable=False, default="[]")
    evidence_count = db.Column(db.Integer, nullable=False, default=0)
    evidence_sha256 = db.Column(db.String(64), nullable=True)
    assigned_to_user_id = db.Column(db.Integer, nullable=True, index=True)
    resolution_summary = db.Column(db.Text, nullable=True)
    first_seen_at = db.Column(db.DateTime, nullable=False, index=True)
    last_seen_at = db.Column(db.DateTime, nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    closed_at = db.Column(db.DateTime, nullable=True)
    __table_args__ = (
        db.Index("ix_staff_incident_status_severity", "status", "severity"),
        db.Index("ix_staff_incident_actor_last_seen", "actor_user_id", "last_seen_at"),
    )


class StaffIncidentNote(db.Model):
    """Append-only analyst notes attached to a SOC case."""
    __tablename__ = "staff_incident_notes"
    __bind_key__ = "system"
    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.Integer, db.ForeignKey("staff_incident_cases.id", ondelete="CASCADE"), nullable=False, index=True)
    author_user_id = db.Column(db.Integer, nullable=False, index=True)
    body = db.Column(db.Text, nullable=False)
    kind = db.Column(db.String(24), nullable=False, default="note")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)


class ReportArchiveDocument(db.Model):
    """Persisted PDF metadata for the user-facing report archive."""
    __tablename__ = "report_archive_documents"
    __bind_key__ = "system"
    id = db.Column(db.Integer, primary_key=True)
    report_type = db.Column(db.String(32), nullable=False, index=True)
    report_key = db.Column(db.String(160), nullable=False, index=True)
    report_title = db.Column(db.String(255), nullable=False)
    direction_id = db.Column(db.Integer, nullable=True, index=True)
    event_id = db.Column(db.Integer, nullable=True, index=True)
    owner_user_id = db.Column(db.Integer, nullable=True, index=True)
    owner_name = db.Column(db.String(255), nullable=True)
    filename = db.Column(db.String(255), nullable=False)
    relative_path = db.Column(db.String(700), nullable=False, unique=True)
    file_sha256 = db.Column(db.String(64), nullable=False)
    signature_code = db.Column(db.String(40), nullable=True, index=True)
    signed_by_user_id = db.Column(db.Integer, nullable=True, index=True)
    signed_by_name = db.Column(db.String(255), nullable=True)
    signed_at = db.Column(db.DateTime, nullable=True)
    report_year = db.Column(db.Integer, nullable=False, index=True)
    report_month = db.Column(db.Integer, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)


class ReportArchiveBackup(db.Model):
    """Proof that the mandatory pre-deletion ZIP was built and retained."""
    __tablename__ = "report_archive_backups"
    __bind_key__ = "system"
    id = db.Column(db.Integer, primary_key=True)
    report_year = db.Column(db.Integer, nullable=False, index=True)
    backup_token = db.Column(db.String(64), nullable=False, unique=True)
    relative_path = db.Column(db.String(700), nullable=False)
    file_sha256 = db.Column(db.String(64), nullable=False)
    document_set_sha256 = db.Column(db.String(64), nullable=False, default="")
    created_by_user_id = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class ReportArchiveDocumentDirection(db.Model):
    """Many-to-many direction scope for cross-direction event reports."""
    __tablename__ = "report_archive_document_directions"
    __bind_key__ = "system"
    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey("report_archive_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    direction_id = db.Column(db.Integer, nullable=False, index=True)
    __table_args__ = (db.UniqueConstraint("document_id", "direction_id", name="uq_report_doc_direction"),)


class StaffChatConversation(db.Model):
    """Private in-app staff conversations, stored in the system SQLite bind."""
    __tablename__ = "staff_chat_conversations"
    __bind_key__ = "system"
    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(16), nullable=False, default="direct", index=True)  # general | direct | group
    title = db.Column(db.String(160), nullable=True)
    conversation_key = db.Column(db.String(100), nullable=True, unique=True, index=True)
    created_by_user_id = db.Column(db.Integer, nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    is_archived = db.Column(db.Boolean, nullable=False, default=False, index=True)
    participants = db.relationship("StaffChatParticipant", back_populates="conversation", cascade="all, delete-orphan")
    messages = db.relationship("StaffChatMessage", back_populates="conversation", cascade="all, delete-orphan")


class StaffChatParticipant(db.Model):
    """Per-account membership and read receipt; user IDs belong to the people DB bind."""
    __tablename__ = "staff_chat_participants"
    __bind_key__ = "system"
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("staff_chat_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    added_by_user_id = db.Column(db.Integer, nullable=True)
    joined_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    last_read_message_id = db.Column(db.Integer, nullable=False, default=0)
    last_read_at = db.Column(db.DateTime, nullable=True)
    is_muted = db.Column(db.Boolean, nullable=False, default=False)
    conversation = db.relationship("StaffChatConversation", back_populates="participants")
    __table_args__ = (db.UniqueConstraint("conversation_id", "user_id", name="uq_staff_chat_participant"),)


class StaffChatUserPreference(db.Model):
    """Per-user chat list state (pin/hide) without changing shared conversations."""
    __tablename__ = "staff_chat_user_preferences"
    __bind_key__ = "system"
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("staff_chat_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    is_pinned = db.Column(db.Boolean, nullable=False, default=False)
    is_hidden = db.Column(db.Boolean, nullable=False, default=False)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint("conversation_id", "user_id", name="uq_staff_chat_user_preference"),)


class StaffChatChannelPermission(db.Model):
    """Per-channel membership capabilities; non-writers are read-only."""
    __tablename__ = "staff_chat_channel_permissions"
    __bind_key__ = "system"
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("staff_chat_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    can_post = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint("conversation_id", "user_id", name="uq_staff_chat_channel_permission"),)


class StaffChatPushSubscription(db.Model):
    """Browser/PWA Web Push subscriptions bound to an authenticated staff account."""
    __tablename__ = "staff_chat_push_subscriptions"
    __bind_key__ = "system"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    endpoint = db.Column(db.Text, nullable=False, unique=True)
    p256dh = db.Column(db.String(255), nullable=False)
    auth = db.Column(db.String(255), nullable=False)
    user_agent = db.Column(db.String(512), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class StaffChatMessage(db.Model):
    """A text message or attachment-only message with an optional reply target."""
    __tablename__ = "staff_chat_messages"
    __bind_key__ = "system"
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("staff_chat_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    sender_user_id = db.Column(db.Integer, nullable=False, index=True)
    body = db.Column(db.Text, nullable=False, default="")
    reply_to_id = db.Column(db.Integer, db.ForeignKey("staff_chat_messages.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    edited_at = db.Column(db.DateTime, nullable=True)
    is_deleted = db.Column(db.Boolean, nullable=False, default=False)
    conversation = db.relationship("StaffChatConversation", back_populates="messages")
    reply_to = db.relationship("StaffChatMessage", remote_side=[id], foreign_keys=[reply_to_id], uselist=False)
    attachments = db.relationship("StaffChatAttachment", back_populates="message", cascade="all, delete-orphan")
    reactions = db.relationship("StaffChatReaction", back_populates="message", cascade="all, delete-orphan")


class StaffChatReaction(db.Model):
    """One emoji reaction per user and message; a user may choose multiple emojis."""
    __tablename__ = "staff_chat_reactions"
    __bind_key__ = "system"
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey("staff_chat_messages.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    emoji = db.Column(db.String(12), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    message = db.relationship("StaffChatMessage", back_populates="reactions")
    __table_args__ = (db.UniqueConstraint("message_id", "user_id", "emoji", name="uq_staff_chat_reaction"),)


class StaffChatAttachment(db.Model):
    """Private attachment metadata; bytes are stored outside the public static tree."""
    __tablename__ = "staff_chat_attachments"
    __bind_key__ = "system"
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey("staff_chat_messages.id", ondelete="CASCADE"), nullable=False, index=True)
    uploaded_by_user_id = db.Column(db.Integer, nullable=False, index=True)
    original_name = db.Column(db.String(255), nullable=False)
    storage_name = db.Column(db.String(80), nullable=False, unique=True)
    extension = db.Column(db.String(12), nullable=False)
    mime_type = db.Column(db.String(100), nullable=False, default="application/octet-stream")
    size_bytes = db.Column(db.Integer, nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    message = db.relationship("StaffChatMessage", back_populates="attachments")


class StaffChatTyping(db.Model):
    """Short-lived typing status, refreshed by the active browser tab."""
    __tablename__ = "staff_chat_typing"
    __bind_key__ = "system"
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("staff_chat_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint("conversation_id", "user_id", name="uq_staff_chat_typing"),)
