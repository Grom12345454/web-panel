"""Access-controlled system notifications for the staff web panel."""
from datetime import datetime, timedelta
from database import db, Student, UserRole, SiteNotification, SiteNotificationRead
from services.applications import can_user_manage_direction

NOTIFICATION_TTL = timedelta(minutes=90)


def delete_expired_notifications():
    """Delete old in-app alerts and receipt rows; never cancel bot messages."""
    cutoff = datetime.utcnow() - NOTIFICATION_TTL
    expired = db.session.query(SiteNotification.id).filter(SiteNotification.created_at <= cutoff)
    SiteNotificationRead.query.filter(SiteNotificationRead.notification_id.in_(expired)).delete(synchronize_session=False)
    deleted = SiteNotification.query.filter(SiteNotification.created_at <= cutoff).delete(synchronize_session=False)
    db.session.commit()
    return deleted


CATEGORIES = {
    "system": "Система", "applications": "Заявки", "events": "Мероприятия",
    "lessons": "Занятия", "leadership": "Руководство",
}
SEVERITIES = {"info", "success", "warning"}
# Everyone in the staff panel can read staff announcements. The more restrictive
# restricted audiences remain private when explicitly selected.
AUDIENCES = {"all", "staff", "admins", "managers", "leaders"}
STAFF_ROLES = frozenset({UserRole.SUPER_ADMIN.value, UserRole.OBSERVER.value})


def can_view(user, alert):
    """Never rely on browser filters to conceal someone else's students."""
    role = user.role
    if role == UserRole.STAFF.value:
        from services.staff_access import allowed
        prefs = set((user.notifications or '').split(','))
        section = alert.category if alert.category in {'events','lessons','applications'} else 'notifications'
        if alert.category == 'system' and not alert.student_id:
            # System notices are mandatory panel messages, not optional module
            # alerts. A global admin notice reaches every active employee.
            from services.broadcast_policy import broadcast_direction_ids
            scope = broadcast_direction_ids(user)
            return (alert.audience in {'all', 'staff', 'managers'} and
                    (alert.direction_id is None or alert.direction_id in scope))
        if alert.category not in prefs or not alert.direction_id or not allowed(user, alert.direction_id, section):
            return False
        return alert.audience in {'all','staff','managers'}
    if alert.audience == "staff" and role not in STAFF_ROLES:
        return False
    if alert.audience == "admins" and role != UserRole.SUPER_ADMIN.value:
        return False
    if alert.audience == "leaders" and role not in {UserRole.SUPER_ADMIN.value, UserRole.LEADER.value}:
        return False
    if alert.audience == "managers" and role not in STAFF_ROLES | {UserRole.LEADER.value}:
        return False
    if alert.audience not in AUDIENCES:
        return False
    if alert.student_id:
        student = Student.query.get(alert.student_id)
        if not student:
            return role in STAFF_ROLES
        if alert.education_type and student.education_type != alert.education_type:
            return False
        education = student.education_type
    else:
        education = alert.education_type
    # For cohort-targeted announcements, restrict ordinary web accounts by
    # their own linked Telegram/student profile or their explicit panel scope.
    # Global administrators remain able to audit notices for every cohort.
    if alert.education_type and role not in STAFF_ROLES:
        assigned = getattr(user, "assigned_education_type", "all")
        if assigned not in {alert.education_type}:
            student_profile = Student.query.filter_by(tg_id=user.tg_id).first() if user.tg_id else None
            if not student_profile or student_profile.education_type != alert.education_type:
                return False
    # Observer is a read-only staff role: it may view notices about students,
    # directions and education cohorts, but cannot perform the linked action.
    if role in STAFF_ROLES:
        return True
    if role != UserRole.LEADER.value:
        return False
    if alert.direction_id is None:
        return alert.audience == "all" and not alert.student_id
    # A deputy only receives alerts about applicants in their own review cohort.
    # For general announcements without an education contour a direction leader
    # can see the message, but no student-specific details are attached.
    return can_user_manage_direction(user.id, alert.direction_id, education)


def visible_notifications(user, category="", state="all", direction_id=None, limit=200):
    query = SiteNotification.query.filter(SiteNotification.created_at > datetime.utcnow() - NOTIFICATION_TTL)
    if category in CATEGORIES:
        query = query.filter_by(category=category)
    if direction_id:
        query = query.filter_by(direction_id=direction_id)
    # Bounded server-side scan, independent of arbitrary query-string input.
    candidates = query.order_by(SiteNotification.id.desc()).limit(1000).all()
    visible = [item for item in candidates if can_view(user, item)]
    ids = [item.id for item in visible]
    read_ids = {row.notification_id for row in SiteNotificationRead.query.filter(
        SiteNotificationRead.user_id == user.id,
        SiteNotificationRead.notification_id.in_(ids)
    ).all()} if ids else set()
    unread = len(visible) - len(read_ids)
    items = [(item, item.id in read_ids) for item in visible]
    if state == "unread":
        items = [entry for entry in items if not entry[1]]
    elif state == "read":
        items = [entry for entry in items if entry[1]]
    return items[:limit], unread


def mark_read(user, alerts):
    ids = [alert.id for alert in alerts if can_view(user, alert)]
    if not ids:
        return 0
    existing = {row.notification_id for row in SiteNotificationRead.query.filter(
        SiteNotificationRead.user_id == user.id, SiteNotificationRead.notification_id.in_(ids)
    ).all()}
    for alert_id in ids:
        if alert_id not in existing:
            db.session.add(SiteNotificationRead(notification_id=alert_id, user_id=user.id, read_at=datetime.utcnow()))
    db.session.commit()
    return len(set(ids) - existing)
