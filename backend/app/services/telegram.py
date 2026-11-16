"""Telegram utilities for direction announcements, invitations and access revocation."""
from __future__ import annotations

import html
import logging
import time
import requests
from sqlalchemy.exc import IntegrityError

from config import settings
from database import db, DirectionChat, StudentInviteLink, student_directions

logger = logging.getLogger(__name__)

def telegram_api(method, payload, attempts=3, timeout=10):
    if not settings.BOT_TOKEN:
        return None
    url = f"https://api.telegram.org/bot{settings.BOT_TOKEN}/{method}"
    last = None
    for attempt in range(attempts):
        try:
            response = requests.post(url, json=payload, timeout=timeout)
            try:
                data = response.json()
            except ValueError:
                data = {"ok": False, "description": response.text[:500]}
            last = data
            if data.get("ok"):
                return data
            if response.status_code == 429 and attempt < attempts - 1:
                retry_after = int((data.get("parameters") or {}).get("retry_after", 1))
                time.sleep(min(max(retry_after, 1), 5))
                continue
            return None
        except requests.RequestException as exc:
            if attempt < attempts - 1:
                time.sleep(attempt + 1)
            else:
                logger.error("Telegram network error (%s)", type(exc).__name__)
    return last if last and last.get("ok") else None

def resolve_chat_id(chat_id):
    raw = str(chat_id or "").strip()
    if not raw:
        return None
    if not raw.startswith("@"):
        return raw
    data = telegram_api("getChat", {"chat_id": raw}, attempts=2)
    return str((data or {}).get("result", {}).get("id")) if data else None

def send_tg(chat_id, text, reply_markup=None):
    from services.bot_journal import record_bot_event
    payload = {"chat_id": str(chat_id), "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    started = time.monotonic()
    success = bool(telegram_api("sendMessage", payload))
    record_bot_event('telegram', 'outgoing', 'message_sent' if success else 'message_failed',
                     'success' if success else 'error', actor_id=chat_id,
                     summary='Отправка сообщения через Telegram', duration_ms=(time.monotonic() - started) * 1000)
    return success


def send_direction_chat(direction_id, text, reply_markup=None):
    count = 0
    for chat in DirectionChat.query.filter_by(direction_id=direction_id, is_active=True).all():
        resolved = resolve_chat_id(chat.chat_id)
        if resolved and send_tg(resolved, text, reply_markup):
            count += 1
    return count

def create_direction_invite_links(direction_id, student_name=None):
    """Create invite links for active chats; caller may cache them for a student."""
    links = []
    if not settings.BOT_TOKEN:
        return links
    for chat in DirectionChat.query.filter_by(direction_id=direction_id, is_active=True).all():
        resolved = resolve_chat_id(chat.chat_id)
        if not resolved:
            continue
        payload = {
            "chat_id": resolved,
            "name": f"Студсовет • {student_name or 'Студент'}"[:32],
            "creates_join_request": True,
        }
        data = telegram_api("createChatInviteLink", payload, attempts=2)
        invite = (data or {}).get("result", {}).get("invite_link")
        if invite:
            links.append({"title": chat.title or resolved, "link": invite, "chat_id": resolved})
    return links

def _revoke_invite(chat_id, invite_link):
    if not chat_id or not invite_link:
        return False
    data = telegram_api("revokeChatInviteLink", {"chat_id": str(chat_id), "invite_link": invite_link}, attempts=1, timeout=6)
    if not data:
        logger.warning("Could not revoke cached Telegram invite link for chat %s; check bot admin rights", chat_id)
    return bool(data)

def sync_student_direction_invites(student, direction):
    """Return cached invite links for every currently active chat, creating only missing ones.

    Unlike the old cache check, this reconciles the cache per chat, so a chat added
    after the student's first visit becomes visible and a disconnected chat's link
    is revoked and removed. Repeated API calls do not create duplicate invite links.
    """
    if not student or not direction:
        return []

    # If Telegram is temporarily unavailable or the bot token is not configured,
    # keep showing cached links only for chats that are still connected and active.
    # Do not return links belonging to chats that have already been disconnected.
    if not settings.BOT_TOKEN:
        active_chat_ids = {
            str(chat.chat_id)
            for chat in DirectionChat.query.filter_by(direction_id=direction.id, is_active=True).all()
        }
        return [
            {"title": row.title, "link": row.invite_link, "chat_id": str(row.chat_id)}
            for row in StudentInviteLink.query.filter_by(
                student_id=student.id, direction_id=direction.id
            ).all()
            if str(row.chat_id) in active_chat_ids
        ]

    active_chats = {}
    for chat in DirectionChat.query.filter_by(direction_id=direction.id, is_active=True).all():
        resolved = resolve_chat_id(chat.chat_id)
        if not resolved:
            continue
        active_chats[resolved] = chat
        if str(chat.chat_id) != resolved:
            chat.chat_id = resolved

    cached = StudentInviteLink.query.filter_by(student_id=student.id, direction_id=direction.id).all()
    cached_by_chat = {str(row.chat_id): row for row in cached}

    # Remove and revoke cached links for chats that are no longer attached/active.
    for cache_chat_id, cached_row in list(cached_by_chat.items()):
        if cache_chat_id not in active_chats:
            _revoke_invite(cached_row.chat_id, cached_row.invite_link)
            db.session.delete(cached_row)
            cached_by_chat.pop(cache_chat_id, None)

    # Create a unique link only for active chats without a cached link.
    for chat_id, chat in active_chats.items():
        if chat_id in cached_by_chat:
            cached_by_chat[chat_id].title = chat.title or chat_id
            continue
        data = telegram_api("createChatInviteLink", {
            "chat_id": chat_id,
            "name": f"Студсовет • {student.full_name or 'Студент'}"[:32],
            "creates_join_request": True,
        }, attempts=2)
        link = (data or {}).get("result", {}).get("invite_link")
        if not link:
            continue
        row = StudentInviteLink(
            student_id=student.id,
            direction_id=direction.id,
            chat_id=chat_id,
            title=(chat.title or chat_id)[:255],
            invite_link=link,
        )
        db.session.add(row)
        try:
            db.session.commit()
            cached_by_chat[chat_id] = row
        except IntegrityError:
            # Another browser tab may have created the same link cache at once.
            db.session.rollback()
            _revoke_invite(chat_id, link)
            existing = StudentInviteLink.query.filter_by(
                student_id=student.id, direction_id=direction.id, chat_id=chat_id
            ).first()
            if existing:
                cached_by_chat[chat_id] = existing
        except Exception:
            db.session.rollback()
            logger.exception("Could not cache invite link for student #%s direction #%s", student.id, direction.id)

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("Could not save synchronized invite cache for student #%s", student.id)

    # Re-query after commits/rollbacks; only links to currently active chats belong in UI.
    active_ids = set(active_chats)
    return [
        {"title": row.title, "link": row.invite_link, "chat_id": str(row.chat_id)}
        for row in StudentInviteLink.query.filter_by(student_id=student.id, direction_id=direction.id).all()
        if str(row.chat_id) in active_ids
    ]

def send_direction_invites(student, direction):
    if not student or not student.tg_id or student.tg_id <= 0:
        return 0
    links = sync_student_direction_invites(student, direction)
    sent = 0
    header = f"🔗 <b>Чаты направления «{html.escape(direction.name)}»</b>\n\n"
    for item in links:
        message = header + f"<b>{html.escape(item['title'])}</b>\n<a href=\"{html.escape(item['link'], quote=True)}\">Открыть приглашение</a>"
        if send_tg(student.tg_id, message):
            sent += 1
    return sent

def _remaining_direction_ids(student_id, removing_ids):
    """Return remaining directions that still grant active chat access.

    Pending, interview and rejected applications do not justify remaining in a
    Telegram group after another role/direction access is revoked.
    """
    rows = db.session.execute(
        student_directions.select().where(student_directions.c.student_id == student_id)
    ).mappings().all()
    entitled_statuses = {"active"}
    return {
        int(row["direction_id"])
        for row in rows
        if int(row["direction_id"]) not in removing_ids
        and row.get("status") in entitled_statuses
    }

def remove_student_from_direction_chats_for_ids(student, direction_ids):
    """Revoke role/application access and remove student from affected chats.

    Any other direction membership the student still has is preserved. If a chat
    is shared by a remaining (including personally selected) direction, the bot
    does not kick the student from that shared chat. Cached invite links for the
    removed directions are revoked so they cannot be reused later.
    """
    if not student or not student.tg_id or int(student.tg_id) <= 0:
        return 0
    removing_ids = {int(value) for value in direction_ids if value is not None}
    if not removing_ids:
        return 0

    remaining_ids = _remaining_direction_ids(student.id, removing_ids)
    preserved_chat_ids = set()
    if remaining_ids:
        for chat in DirectionChat.query.filter(
            DirectionChat.direction_id.in_(remaining_ids), DirectionChat.is_active.is_(True)
        ).all():
            resolved = resolve_chat_id(chat.chat_id)
            if resolved:
                preserved_chat_ids.add(resolved)

    removed_count = 0
    seen_to_remove = set()
    chats = DirectionChat.query.filter(
        DirectionChat.direction_id.in_(removing_ids), DirectionChat.is_active.is_(True)
    ).all()
    for chat in chats:
        resolved = resolve_chat_id(chat.chat_id)
        if not resolved or resolved in preserved_chat_ids or resolved in seen_to_remove:
            continue
        seen_to_remove.add(resolved)
        banned = telegram_api("banChatMember", {
            "chat_id": resolved,
            "user_id": int(student.tg_id),
            "revoke_messages": False,
        }, attempts=2, timeout=8)
        if banned:
            # Kick without permanently blocking a student who may later receive a new invite.
            telegram_api("unbanChatMember", {
                "chat_id": resolved,
                "user_id": int(student.tg_id),
                "only_if_banned": True,
            }, attempts=2, timeout=8)
            removed_count += 1
        else:
            logger.warning("Could not remove student #%s from Telegram chat %s; check bot admin rights", student.id, resolved)

    # Revoke cached invites for precisely the directions being removed.
    cached_rows = StudentInviteLink.query.filter(
        StudentInviteLink.student_id == student.id,
        StudentInviteLink.direction_id.in_(removing_ids),
    ).all()
    for row in cached_rows:
        _revoke_invite(row.chat_id, row.invite_link)
        db.session.delete(row)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("Could not remove cached invite links for student #%s", student.id)
    return removed_count

def remove_student_from_direction_chats(student, direction):
    """Remove access for one withdrawn direction while preserving other memberships."""
    if not direction:
        return 0
    return remove_student_from_direction_chats_for_ids(student, {direction.id})

def revoke_invites_for_chat(chat_id, direction_id=None):
    """Revoke cached student invite links when a chat is disconnected from a direction."""
    resolved = resolve_chat_id(chat_id)
    query = StudentInviteLink.query.filter_by(chat_id=str(resolved or chat_id))
    if direction_id is not None:
        query = query.filter_by(direction_id=int(direction_id))
    rows = query.all()
    for row in rows:
        _revoke_invite(row.chat_id, row.invite_link)
        db.session.delete(row)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("Could not revoke cached links for disconnected chat %s", resolved or chat_id)
    return len(rows)
