"""Safe, deduplicated recipients for Telegram system announcements.

No Telegram network calls in this module. The web route queues messages only
once the optional on-site notification has committed successfully.
"""
from __future__ import annotations
import html
from database import DirectionChat, Student, student_directions, DirectionStatus, MessengerChat, MessengerIdentity, Direction

CHANNELS = frozenset({"site", "chats", "dm", "vk_chats", "vk_dm", "max_chats", "max_dm"})
EDUCATION_TYPES = frozenset({"", "college", "institute"})


def chat_matches_cohort(chat, education):
    """Never publish a cohort-specific announcement into an untagged mixed chat."""
    if not education:
        return True
    direction = chat.direction
    scope = direction.education_scope if direction else "both"
    if scope in {"college", "institute"} and scope != education:
        return False
    tag = chat.education_type or "all"
    if tag == education:
        return True
    return tag == "all" and scope == education


def recipients(education="", direction_id=None, channels=()):
    """Compute targets using authoritative database filters, not browser options."""
    result = {"chats": [], "dm": []}
    if "chats" in channels:
        all_active = DirectionChat.query.filter_by(is_active=True).order_by(DirectionChat.id.asc()).all()
        # The same Telegram chat may be linked to multiple directions. Never
        # leak a college-only announcement to it if *any* of its active links
        # has a conflicting or unspecified cohort.
        safe_ids = {}
        if education:
            for linked_chat in all_active:
                chat_id = str(linked_chat.chat_id).strip()
                safe_ids[chat_id] = safe_ids.get(chat_id, True) and chat_matches_cohort(linked_chat, education)
        # A chat connected to more than one direction is a mixed audience.
        # Never leak department-only notices into a shared conversation.
        chat_scopes = {}
        for linked_chat in all_active:
            chat_scopes.setdefault(str(linked_chat.chat_id).strip(), set()).add(linked_chat.direction_id)
        seen = set()
        for chat in all_active:
            if direction_id and len(chat_scopes.get(str(chat.chat_id).strip(), ())) > 1:
                continue
            if direction_id and chat.direction_id != direction_id:
                continue
            if education and not safe_ids.get(str(chat.chat_id).strip(), False):
                continue
            chat_id = str(chat.chat_id).strip()
            if chat_id and chat_id not in seen:
                seen.add(chat_id)
                result["chats"].append(chat_id)
    if "dm" in channels:
        query = Student.query
        if education:
            query = query.filter_by(education_type=education)
        if direction_id:
            query = query.join(student_directions, student_directions.c.student_id == Student.id).filter(
                student_directions.c.direction_id == direction_id,
                student_directions.c.status == DirectionStatus.ACTIVE.value,
            )
        result["dm"] = list(dict.fromkeys(str(student.tg_id) for student in query.order_by(Student.id).all() if student.tg_id and student.tg_id > 0))
    return result


def social_recipients(education="", direction_id=None, channels=()):
    """Resolve VK/MAX targets from the exact same authoritative student records."""
    result = {"vk_chats": [], "vk_dm": [], "max_chats": [], "max_dm": []}
    # Both new transports are resolved against the same students and directions,
    # so a user linked on two messengers gets the same filtered announcement.
    for platform in ('vk', 'max'):
        chat_channel = platform + '_chats'
        dm_channel = platform + '_dm'
        if chat_channel in channels:
            all_active = MessengerChat.query.filter_by(platform=platform, is_active=True).order_by(MessengerChat.id).all()
            directions = {d.id: d for d in Direction.query.all()}
            safe = {}
            if education:
                for chat in all_active:
                    key = chat.chat_id
                    direction = directions.get(chat.direction_id)
                    scope = (direction.education_scope if direction else 'both') or 'both'
                    allowed = (scope in {'both', education} and
                               (chat.education_type == education or
                                (chat.education_type == 'all' and scope == education)))
                    safe[key] = safe.get(key, True) and allowed
            chat_scopes = {}
            for linked in all_active:
                chat_scopes.setdefault(str(linked.chat_id), set()).add(linked.direction_id)
            seen = set()
            for chat in all_active:
                if direction_id and len(chat_scopes.get(str(chat.chat_id), ())) > 1:
                    continue
                if direction_id and chat.direction_id != direction_id:
                    continue
                if education and not safe.get(chat.chat_id, False):
                    continue
                if chat.chat_id not in seen:
                    seen.add(chat.chat_id)
                    result[chat_channel].append(chat.chat_id)
        if dm_channel in channels:
            query = Student.query
            if education:
                query = query.filter_by(education_type=education)
            if direction_id:
                query = query.join(student_directions, student_directions.c.student_id == Student.id).filter(
                    student_directions.c.direction_id == direction_id,
                    student_directions.c.status == DirectionStatus.ACTIVE.value,
                )
            allowed_student_ids = [row.id for row in query.all()]
            if allowed_student_ids:
                rows = MessengerIdentity.query.filter(
                    MessengerIdentity.platform == platform,
                    MessengerIdentity.student_id.in_(allowed_student_ids),
                ).all()
                result[dm_channel] = list(dict.fromkeys(row.external_user_id for row in rows))
    return result


def telegram_message(title, body):
    """Send plain authored content as the bot: no user-supplied HTML is interpreted."""
    return "🔔 <b>Системное уведомление студенческого совета</b>\n\n<b>" + html.escape(title) + "</b>\n\n" + html.escape(body)
