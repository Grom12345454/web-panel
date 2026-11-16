"""Direction-scoped employee alerts for active council workflows."""
from database import User, UserRole
from services.staff_access import allowed


def notify_subscribers(direction_id, category, text):
    if category not in {"applications", "events", "lessons", "system"} or not direction_id:
        return 0
    from web_app import notification_queue
    section = "notifications" if category == "system" else category
    count = 0
    for user in User.query.filter_by(role=UserRole.STAFF.value, is_active=True).all():
        if not user.tg_id or category not in (user.notifications or "").split(","):
            continue
        if allowed(user, direction_id, section):
            notification_queue.put_nowait((int(user.tg_id), str(text)[:1400]))
            count += 1
    return count
