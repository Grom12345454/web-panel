"""In-app employee messenger: private conversations, read receipts and polling APIs.

All data lives in the system SQLite bind. User IDs are scalar references because the
users table lives in the people bind; every route re-checks account state and membership.
"""
from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from flask import (Blueprint, abort, current_app, jsonify, redirect, render_template,
                   request, send_file, url_for)
from sqlalchemy import func, or_
from werkzeug.utils import secure_filename

from config import settings
from database import (db, User, UserRole, StaffChatConversation, StaffChatParticipant,
                      StaffChatMessage, StaffChatReaction, StaffChatAttachment,
                      StaffChatTyping, StaffChatChannelPermission, StaffChatPushSubscription,
                      StaffChatUserPreference)
from web_app import login_required

logger = logging.getLogger(__name__)
staff_messenger_bp = Blueprint("staff_messenger", __name__)

CHAT_ROLES = {UserRole.SUPER_ADMIN.value, UserRole.STAFF.value, UserRole.OBSERVER.value}
REACTIONS = ("👍", "❤️", "😂", "🔥", "✅", "👀")
ALLOWED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".pdf",
    ".docx", ".xlsx", ".pptx", ".txt", ".csv",
}
MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
MAX_TOTAL_ATTACHMENT_BYTES = 8 * 1024 * 1024
MAX_ATTACHMENTS = 4


def _check_account(user, write=False):
    if not user or not user.is_active or user.role not in CHAT_ROLES:
        abort(403)
    if write and user.role == UserRole.OBSERVER.value:
        abort(403)


def _user_label(user):
    return (getattr(user, "full_name", None) or user.email or f"Сотрудник #{user.id}").strip()


def _user_position(user):
    """Return the employee's displayed position without exposing internal role codes."""
    position = (getattr(user, "position", None) or "").strip()
    if position:
        return position
    role_labels = {
        UserRole.SUPER_ADMIN.value: "Главный администратор",
        UserRole.OBSERVER.value: "Наблюдатель",
        UserRole.STAFF.value: "Сотрудник",
    }
    return role_labels.get(getattr(user, "role", None), "Сотрудник")


def _user_initials(user):
    words = _user_label(user).split()
    return "".join(word[0] for word in words[:2] if word).upper() or "С"


def _user_profile(user):
    if not user:
        return None
    return {
        "id": user.id,
        "full_name": _user_label(user),
        "position": _user_position(user),
        "initials": _user_initials(user),
    }


def _get_participant(conversation_id, user_id):
    return StaffChatParticipant.query.filter_by(
        conversation_id=conversation_id, user_id=user_id
    ).first()


def _ensure_participant(conversation, user_id, added_by=None):
    participant = _get_participant(conversation.id, user_id)
    if participant:
        return participant
    participant = StaffChatParticipant(
        conversation_id=conversation.id, user_id=user_id, added_by_user_id=added_by
    )
    db.session.add(participant)
    db.session.flush()
    return participant


def _general_conversation(user):
    conversation = StaffChatConversation.query.filter_by(
        conversation_key="staff-general"
    ).first()
    if not conversation:
        conversation = StaffChatConversation(
            kind="general", title="Общий чат сотрудников",
            conversation_key="staff-general", created_by_user_id=user.id,
        )
        db.session.add(conversation)
        try:
            db.session.flush()
        except Exception:
            db.session.rollback()
            conversation = StaffChatConversation.query.filter_by(
                conversation_key="staff-general"
            ).first()
            if not conversation:
                raise
    _ensure_participant(conversation, user.id, added_by=user.id)
    db.session.commit()
    return conversation


def _can_contact(actor, target):
    if (not target or not target.is_active or target.id == actor.id or
            target.role not in CHAT_ROLES):
        return False
    # Internal staff directory is cross-direction by design: every employee may
    # start a private dialog with every other active staff account.
    return True


def _channel_can_post(user, conversation):
    if user.role == UserRole.SUPER_ADMIN.value:
        return True
    if user.role == UserRole.OBSERVER.value:
        return False
    permission = StaffChatChannelPermission.query.filter_by(
        conversation_id=conversation.id, user_id=user.id
    ).first()
    return bool(permission and permission.can_post)


def _can_write_conversation(user, conversation):
    if not user or user.role == UserRole.OBSERVER.value:
        return False
    if user.role == UserRole.SUPER_ADMIN.value:
        return True
    if conversation and conversation.kind == "channel":
        return _channel_can_post(user, conversation)
    return True


def _conversation_access(user, conversation, write=False):
    _check_account(user, write=write)
    if not conversation or conversation.is_archived:
        return False
    # Chief administrator and observer can inspect every conversation. The
    # observer is always read-only, even when a channel ACL lists them as writer.
    if user.role in {UserRole.SUPER_ADMIN.value, UserRole.OBSERVER.value}:
        return not write or _can_write_conversation(user, conversation)
    if conversation.kind == "general":
        return not write or _can_write_conversation(user, conversation)
    if _get_participant(conversation.id, user.id) is None:
        return False
    return not write or _can_write_conversation(user, conversation)


def _conversation_title(conversation, user):
    if conversation.kind == "direct":
        participant_ids = [row.user_id for row in StaffChatParticipant.query.filter_by(
            conversation_id=conversation.id
        ).all() if row.user_id != user.id]
        other = User.query.filter(User.id.in_(participant_ids)).first() if participant_ids else None
        return _user_label(other) if other else "Диалог"
    return conversation.title or "Групповой чат"


def _message_payload(message, current_user):
    sender = User.query.get(message.sender_user_id)
    reactions = defaultdict(lambda: {"count": 0, "mine": False})
    for reaction in StaffChatReaction.query.filter_by(message_id=message.id).all():
        reactions[reaction.emoji]["count"] += 1
        if reaction.user_id == current_user.id:
            reactions[reaction.emoji]["mine"] = True
    attachments = [{
        "id": item.id,
        "name": item.original_name,
        "size": item.size_bytes,
        "url": url_for("staff_messenger.download_attachment", attachment_id=item.id),
    } for item in message.attachments]
    reply = None
    if message.reply_to_id:
        parent = db.session.get(StaffChatMessage, message.reply_to_id)
        if parent and parent.conversation_id == message.conversation_id and not parent.is_deleted:
            parent_sender = User.query.get(parent.sender_user_id)
            reply_profile = _user_profile(parent_sender)
            reply = {
                "id": parent.id,
                "sender": reply_profile["full_name"] if reply_profile else "Сотрудник",
                "sender_position": reply_profile["position"] if reply_profile else "",
                "body": (parent.body or "Вложение")[:180],
            }
    recipients = StaffChatParticipant.query.filter(
        StaffChatParticipant.conversation_id == message.conversation_id,
        StaffChatParticipant.user_id != message.sender_user_id,
    ).all()
    read_count = sum(1 for row in recipients if row.last_read_message_id >= message.id)
    sender_profile = _user_profile(sender)
    return {
        "id": message.id,
        "sender_id": message.sender_user_id,
        "sender": sender_profile["full_name"] if sender_profile else "Удалённый аккаунт",
        "sender_position": sender_profile["position"] if sender_profile else "",
        "sender_initials": sender_profile["initials"] if sender_profile else "С",
        "body": "Сообщение удалено" if message.is_deleted else (message.body or ""),
        "created_at": message.created_at.strftime("%d.%m.%Y %H:%M"),
        "mine": message.sender_user_id == current_user.id,
        "can_delete": (not message.is_deleted and (message.sender_user_id == current_user.id or current_user.role == UserRole.SUPER_ADMIN.value) and current_user.role != UserRole.OBSERVER.value),
        "is_deleted": bool(message.is_deleted),
        "reply": reply,
        "attachments": attachments,
        "reactions": [{"emoji": emoji, **value} for emoji, value in sorted(reactions.items())],
        "read_count": read_count,
        "recipient_count": len(recipients),
    }


def _conversation_payload(conversation, user):
    participant = _ensure_participant(conversation, user.id, added_by=user.id)
    last_message = StaffChatMessage.query.filter_by(
        conversation_id=conversation.id, is_deleted=False
    ).order_by(StaffChatMessage.id.desc()).first()
    last_sender = User.query.get(last_message.sender_user_id) if last_message else None
    last_sender_profile = _user_profile(last_sender)
    unread = StaffChatMessage.query.filter(
        StaffChatMessage.conversation_id == conversation.id,
        StaffChatMessage.id > participant.last_read_message_id,
        StaffChatMessage.sender_user_id != user.id,
        StaffChatMessage.is_deleted.is_(False),
    ).count()
    member_ids = [row.user_id for row in StaffChatParticipant.query.filter_by(
        conversation_id=conversation.id
    ).all()]
    members = User.query.filter(User.id.in_(member_ids), User.is_active.is_(True)).all() if member_ids else []
    members.sort(key=lambda item: (_user_label(item).casefold(), item.id))
    peer = None
    if conversation.kind == "direct":
        peer = next((item for item in members if item.id != user.id), None)
    peer_profile = _user_profile(peer)
    member_profiles = [_user_profile(item) for item in members]
    if conversation.kind == "direct":
        subtitle = (peer_profile or {}).get("position") or "Личный диалог"
    elif conversation.kind == "general":
        subtitle = f"Основной канал · {len(members)} участников"
    elif conversation.kind == "channel":
        subtitle = f"Канал · {len(members)} участников · права на запись настроены"
    else:
        subtitle = f"Групповой чат · {len(members)} участников"
    preference = StaffChatUserPreference.query.filter_by(
        conversation_id=conversation.id, user_id=user.id
    ).first()
    return {
        "id": conversation.id,
        "is_pinned": bool(preference and preference.is_pinned),
        "is_hidden": bool(preference and preference.is_hidden),
        "can_manage": user.role == UserRole.SUPER_ADMIN.value and conversation.kind != "general",
        "kind": conversation.kind,
        "can_write": _can_write_conversation(user, conversation),
        "title": _conversation_title(conversation, user),
        "preview": ((last_message.body or "Вложение")[:100] if last_message else "Пока нет сообщений"),
        "last_sender": (last_sender_profile or {}).get("full_name", ""),
        "last_sender_position": (last_sender_profile or {}).get("position", ""),
        "updated_at": conversation.updated_at.strftime("%d.%m.%Y %H:%M"),
        "unread": unread,
        "members": [_user_label(item) for item in members],
        "member_profiles": member_profiles,
        "peer": peer_profile,
        "subtitle": subtitle,
        "avatar_initials": (peer_profile or {}).get("initials") or ("◎" if conversation.kind == "general" else "▦"),
        "last_message_id": last_message.id if last_message else 0,
    }


def _visible_conversations(user):
    _check_account(user)
    general = _general_conversation(user)
    participant_ids = [row.conversation_id for row in StaffChatParticipant.query.filter_by(user_id=user.id).all()]
    query = StaffChatConversation.query.filter(StaffChatConversation.is_archived.is_(False))
    if user.role in {UserRole.SUPER_ADMIN.value, UserRole.OBSERVER.value}:
        # Global oversight: every chat, including private and group conversations.
        pass
    else:
        query = query.filter(or_(StaffChatConversation.kind == "general",
                                 StaffChatConversation.id.in_(participant_ids or [-1])))
    preferences = StaffChatUserPreference.query.filter_by(user_id=user.id).all()
    hidden_ids = {item.conversation_id for item in preferences if item.is_hidden}
    pinned_ids = {item.conversation_id for item in preferences if item.is_pinned and not item.is_hidden}
    if hidden_ids:
        query = query.filter(~StaffChatConversation.id.in_(hidden_ids))
    conversations = query.order_by(StaffChatConversation.updated_at.desc(), StaffChatConversation.id.desc()).limit(250).all()
    if all(item.id != general.id for item in conversations) and general.id not in hidden_ids:
        conversations.insert(0, general)
    payloads = [_conversation_payload(item, user) for item in conversations]
    payloads.sort(key=lambda item: (not item["is_pinned"], -item["last_message_id"], -item["id"]))
    return payloads


def _available_contacts(user):
    users = User.query.filter(
        User.is_active.is_(True), User.role.in_(CHAT_ROLES), User.id != user.id
    ).order_by(User.full_name.asc(), User.email.asc()).limit(500).all()
    return [item for item in users if _can_contact(user, item)]


def _attachment_root():
    path = Path(current_app.instance_path) / "staff_chat_attachments"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _load_messages(conversation_id, after_id=0, limit=60):
    return StaffChatMessage.query.filter(
        StaffChatMessage.conversation_id == conversation_id,
        StaffChatMessage.id > after_id,
    ).order_by(StaffChatMessage.id.asc()).limit(max(1, min(int(limit), 100))).all()


def _typing_users(conversation_id, current_user_id):
    now = datetime.utcnow()
    rows = StaffChatTyping.query.filter(
        StaffChatTyping.conversation_id == conversation_id,
        StaffChatTyping.user_id != current_user_id,
        StaffChatTyping.expires_at > now,
    ).all()
    if not rows:
        return []
    users = User.query.filter(User.id.in_([row.user_id for row in rows]), User.is_active.is_(True)).all()
    return [f"{_user_label(item)} · {_user_position(item)}" for item in users]


@staff_messenger_bp.get("/communications")
@login_required
def communications(current_user):
    """The messenger is available only from the installed desktop client."""
    _check_account(current_user)
    abort(404)


@staff_messenger_bp.get("/staff-messenger")
@staff_messenger_bp.get("/messenger")
@staff_messenger_bp.get("/messenger/desktop")
@login_required
def index(current_user):
    _check_account(current_user)
    # The desktop shell marks its requests with a client header. This is only
    # a presentation gate (never an authorization mechanism); all APIs still
    # require the normal authenticated session and role checks.
    if request.headers.get("X-StudSovet-Desktop") != "1":
        abort(404)
    rows = _visible_conversations(current_user)
    selected_id = request.args.get("conversation", type=int)
    selected_row = next((row for row in rows if row["id"] == selected_id), None)
    if selected_row is None:
        selected_row = next((row for row in rows if row["kind"] == "general"), rows[0] if rows else None)
    selected = None
    messages = []
    can_start_chats = current_user.role != UserRole.OBSERVER.value
    can_write = can_start_chats
    if selected_row:
        conversation = db.session.get(StaffChatConversation, selected_row["id"])
        if not _conversation_access(current_user, conversation):
            abort(404)
        can_write = _can_write_conversation(current_user, conversation)
        selected = selected_row
        found = StaffChatMessage.query.filter_by(
            conversation_id=conversation.id, is_deleted=False
        ).order_by(StaffChatMessage.id.desc()).limit(60).all()
        messages = [_message_payload(message, current_user) for message in reversed(found)]
    return render_template(
        "messenger/staff_messenger.html",
        conversations=rows, selected=selected, messages=messages,
        contacts=_available_contacts(current_user) if can_start_chats else [],
        can_write=can_write, can_start_chats=can_start_chats,
        current_profile=_user_profile(current_user),
        channel_permissions=([{
            "profile": _user_profile(member),
            "can_post": bool((StaffChatChannelPermission.query.filter_by(
                conversation_id=selected_row["id"], user_id=member.id
            ).first() or type("PermissionDefault", (), {"can_post": False})()).can_post),
        } for member in User.query.filter(User.id.in_([
            row.user_id for row in StaffChatParticipant.query.filter_by(conversation_id=selected_row["id"]).all()
        ]), User.is_active.is_(True)).all()] if selected_row and selected_row["kind"] == "channel" and current_user.role == UserRole.SUPER_ADMIN.value else []),
        is_super_admin=current_user.role == UserRole.SUPER_ADMIN.value,
        is_observer=current_user.role == UserRole.OBSERVER.value,
        can_create_group=(current_user.role == UserRole.SUPER_ADMIN.value or (getattr(current_user, "staff_rank", "employee") or "employee") == "employee_all"),
        can_create_channel=(current_user.role == UserRole.SUPER_ADMIN.value or
                            (current_user.role == UserRole.STAFF.value and
                             (getattr(current_user, "staff_rank", "employee") or "employee") == "employee_all")),
        desktop_mode=True,
        native_desktop=True,
        unread_total=sum(item["unread"] for item in rows),
    )


@staff_messenger_bp.get("/staff-messenger/api/notifications")
@login_required
def notification_feed(current_user):
    """Return only new messages from chats visible to this authenticated user."""
    _check_account(current_user)
    after_id = max(0, request.args.get("after", type=int) or 0)
    bootstrap = request.args.get("bootstrap") == "1"
    if current_user.role in {UserRole.SUPER_ADMIN.value, UserRole.OBSERVER.value}:
        conversation_query = StaffChatConversation.query.filter(StaffChatConversation.is_archived.is_(False))
    else:
        member_ids = [row.conversation_id for row in StaffChatParticipant.query.filter_by(user_id=current_user.id).all()]
        conversation_query = StaffChatConversation.query.filter(
            StaffChatConversation.is_archived.is_(False),
            or_(StaffChatConversation.kind == "general", StaffChatConversation.id.in_(member_ids or [-1]))
        )
    conversation_ids = [row.id for row in conversation_query.with_entities(StaffChatConversation.id).all()]
    if not conversation_ids:
        return jsonify({"ok": True, "cursor": after_id, "notifications": []})
    latest_id = db.session.query(func.max(StaffChatMessage.id)).filter(
        StaffChatMessage.conversation_id.in_(conversation_ids)
    ).scalar() or 0
    if bootstrap:
        return jsonify({"ok": True, "cursor": int(latest_id), "notifications": []})
    rows = StaffChatMessage.query.filter(
        StaffChatMessage.conversation_id.in_(conversation_ids),
        StaffChatMessage.id > after_id,
        StaffChatMessage.is_deleted.is_(False),
    ).order_by(StaffChatMessage.id.asc()).limit(80).all()
    notices = []
    for message in rows:
        if message.sender_user_id == current_user.id:
            continue
        conversation = db.session.get(StaffChatConversation, message.conversation_id)
        if not _conversation_access(current_user, conversation):
            continue
        sender = User.query.get(message.sender_user_id)
        title = conversation.title if conversation.kind in {"general", "group", "channel"} else _conversation_title(conversation, current_user)
        body = (message.body or "Отправлен файл").strip().replace("\n", " ")[:180]
        notices.append({
            "id": message.id,
            "conversation_id": conversation.id,
            "kind": conversation.kind,
            "title": title or "Новое сообщение",
            "sender": _user_label(sender) if sender else "Сотрудник",
            "body": body,
            "url": url_for("staff_messenger.index", conversation=conversation.id),
        })
    return jsonify({"ok": True, "cursor": int(rows[-1].id if rows else max(after_id, latest_id)), "notifications": notices})


def _web_push_configuration():
    public_key = os.environ.get("VAPID_PUBLIC_KEY", "").strip()
    private_key = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
    if not public_key or not private_key:
        return "", ""
    if "BEGIN PRIVATE KEY" not in private_key:
        try:
            if not Path(private_key).expanduser().is_file():
                return "", ""
        except OSError:
            return "", ""
    try:
        import pywebpush  # noqa: F401
    except ImportError:
        return "", ""
    return public_key, private_key


@staff_messenger_bp.get("/staff-messenger/api/push-public-key")
@login_required
def push_public_key(current_user):
    _check_account(current_user)
    public_key, _ = _web_push_configuration()
    return jsonify({"ok": True, "public_key": public_key})


@staff_messenger_bp.post("/staff-messenger/api/push-subscriptions")
@login_required
def save_push_subscription(current_user):
    _check_account(current_user)
    payload = request.get_json(silent=True) or {}
    endpoint = str(payload.get("endpoint", "")).strip()
    keys = payload.get("keys") if isinstance(payload.get("keys"), dict) else {}
    p256dh = str(keys.get("p256dh", "")).strip()
    auth_key = str(keys.get("auth", "")).strip()
    if not endpoint.startswith("https://") or len(endpoint) > 2048 or not p256dh or not auth_key:
        return jsonify({"ok": False, "error": "Некорректная подписка на уведомления."}), 400
    subscription = StaffChatPushSubscription.query.filter_by(endpoint=endpoint).first()
    now = datetime.utcnow()
    if not subscription:
        subscription = StaffChatPushSubscription(endpoint=endpoint, user_id=current_user.id,
            p256dh=p256dh, auth=auth_key, created_at=now, updated_at=now)
        db.session.add(subscription)
    else:
        subscription.user_id = current_user.id
        subscription.p256dh = p256dh
        subscription.auth = auth_key
        subscription.updated_at = now
    subscription.user_agent = (request.headers.get("User-Agent") or "")[:512]
    db.session.commit()
    return jsonify({"ok": True})


def _send_web_push(message, conversation):
    """Best-effort Web Push delivery. In-app polling remains available without VAPID."""
    public_key, private_key = _web_push_configuration()
    if not public_key or not private_key:
        return
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        return
    recipient_ids = {row.user_id for row in StaffChatParticipant.query.filter_by(
        conversation_id=conversation.id
    ).all() if row.user_id != message.sender_user_id}
    # Main channel is broadcast to all staff. Super-admins and observers have
    # organization-wide visibility into every conversation and get the same notice.
    if conversation.kind == "general":
        global_users = User.query.filter(User.is_active.is_(True), User.role.in_(CHAT_ROLES)).all()
        recipient_ids.update(item.id for item in global_users if item.id != message.sender_user_id)
    else:
        global_users = User.query.filter(
            User.is_active.is_(True),
            User.role.in_([UserRole.SUPER_ADMIN.value, UserRole.OBSERVER.value]),
        ).all()
        recipient_ids.update(item.id for item in global_users if item.id != message.sender_user_id)
    if not recipient_ids:
        return
    subscriptions = StaffChatPushSubscription.query.filter(
        StaffChatPushSubscription.user_id.in_(recipient_ids)
    ).all()
    if not subscriptions:
        return
    sender = User.query.get(message.sender_user_id)
    payload = {
        "title": conversation.title if conversation.kind in {"general", "group", "channel"} else (_user_label(sender) if sender else "Личный диалог"),
        "body": f"{_user_label(sender) if sender else 'Сотрудник'}: {(message.body or 'Отправлен файл')[:140]}",
        "url": url_for("staff_messenger.index", conversation=conversation.id),
        "tag": f"studsovet-message-{message.id}",
    }
    claims = {"sub": os.environ.get("VAPID_CLAIMS_EMAIL", "mailto:admin@example.com")}
    stale_ids = []
    for subscription in subscriptions:
        try:
            webpush(
                subscription_info={"endpoint": subscription.endpoint,
                    "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth}},
                data=json.dumps(payload, ensure_ascii=False),
                vapid_private_key=private_key,
                vapid_claims=claims,
                timeout=5,
            )
        except WebPushException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in {404, 410}:
                stale_ids.append(subscription.id)
            logger.info("web_push_delivery_failed status=%s", status)
        except Exception:
            logger.exception("web_push_delivery_error")
    if stale_ids:
        StaffChatPushSubscription.query.filter(StaffChatPushSubscription.id.in_(stale_ids)).delete(synchronize_session=False)
        db.session.commit()


@staff_messenger_bp.post("/staff-messenger/api/conversations")
@login_required
def create_conversation(current_user):
    _check_account(current_user, write=True)
    payload = request.get_json(silent=True) or request.form
    kind = str(payload.get("kind", "direct")).strip().lower()
    if kind not in {"direct", "group", "channel"}:
        return jsonify({"ok": False, "error": "Можно создать личный диалог, группу или канал."}), 400
    can_manage_channels = (
        current_user.role == UserRole.SUPER_ADMIN.value
        or (current_user.role == UserRole.STAFF.value
            and (getattr(current_user, "staff_rank", "employee") or "employee") == "employee_all")
    )
    if kind == "channel" and not can_manage_channels:
        abort(403)
    raw_ids = payload.get("participant_ids", [])
    if isinstance(raw_ids, str):
        raw_ids = [item for item in raw_ids.split(",") if item.strip()]
    try:
        participant_ids = sorted({int(item) for item in raw_ids if int(item) != current_user.id})
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Некорректный список участников."}), 400
    if kind == "direct" and len(participant_ids) != 1:
        return jsonify({"ok": False, "error": "Для личного диалога выберите одного сотрудника."}), 400
    if kind == "group" and current_user.role != UserRole.SUPER_ADMIN.value and (getattr(current_user, "staff_rank", "employee") or "employee") != "employee_all":
        return jsonify({"ok": False, "error": "Создавать общие группы могут сотрудники по всем направлениям."}), 403
    if kind == "group" and not 2 <= len(participant_ids) <= 19:
        return jsonify({"ok": False, "error": "Для группы выберите от двух до девятнадцати сотрудников."}), 400
    if kind == "channel" and not 1 <= len(participant_ids) <= 200:
        return jsonify({"ok": False, "error": "Добавьте в канал хотя бы одного сотрудника."}), 400
    users = User.query.filter(User.id.in_(participant_ids), User.is_active.is_(True)).all() if participant_ids else []
    if len(users) != len(participant_ids) or any(not _can_contact(current_user, item) for item in users):
        abort(403)
    if kind == "direct":
        key = "direct:" + ":".join(str(item) for item in sorted([current_user.id, participant_ids[0]]))
        conversation = StaffChatConversation.query.filter_by(conversation_key=key).first()
        if conversation:
            _ensure_participant(conversation, current_user.id, added_by=current_user.id)
            db.session.commit()
            return jsonify({"ok": True, "conversation_id": conversation.id,
                            "url": url_for("staff_messenger.index", conversation=conversation.id), "existing": True})
        title = None
    else:
        key = None
        title = " ".join(str(payload.get("title", "")).split())[:160]
        if len(title) < 2:
            return jsonify({"ok": False, "error": "Укажите название канала." if kind == "channel" else "Укажите название группового чата."}), 400
    conversation = StaffChatConversation(
        kind=kind, title=title, conversation_key=key, created_by_user_id=current_user.id,
        updated_at=datetime.utcnow(),
    )
    db.session.add(conversation)
    db.session.flush()
    _ensure_participant(conversation, current_user.id, added_by=current_user.id)
    for target in users:
        _ensure_participant(conversation, target.id, added_by=current_user.id)
    if kind == "channel":
        raw_writer_ids = payload.get("writer_ids", [])
        if isinstance(raw_writer_ids, str):
            raw_writer_ids = [item for item in raw_writer_ids.split(",") if item.strip()]
        try:
            writer_ids = {int(item) for item in raw_writer_ids}
        except (TypeError, ValueError):
            db.session.rollback()
            return jsonify({"ok": False, "error": "Некорректный список авторов канала."}), 400
        if not writer_ids.issubset(set(participant_ids)):
            db.session.rollback()
            return jsonify({"ok": False, "error": "Писать могут только участники канала."}), 400
        for target in users:
            db.session.add(StaffChatChannelPermission(
                conversation_id=conversation.id, user_id=target.id,
                can_post=target.id in writer_ids,
            ))
    db.session.commit()
    return jsonify({"ok": True, "conversation_id": conversation.id,
                    "url": url_for("staff_messenger.index", conversation=conversation.id), "existing": False})


@staff_messenger_bp.post("/staff-messenger/api/conversations/<int:conversation_id>/preferences")
@login_required
def update_conversation_preferences(current_user, conversation_id):
    # Pin/hide are personal list preferences; read-only observers may use them too.
    _check_account(current_user)
    conversation = db.session.get(StaffChatConversation, conversation_id)
    if not _conversation_access(current_user, conversation):
        abort(404)
    payload = request.get_json(silent=True) or {}
    action = str(payload.get("action", "")).strip().lower()
    preference = StaffChatUserPreference.query.filter_by(
        conversation_id=conversation.id, user_id=current_user.id
    ).first()
    if preference is None:
        preference = StaffChatUserPreference(conversation_id=conversation.id, user_id=current_user.id)
        db.session.add(preference)
    if action == "pin":
        preference.is_pinned = True
    elif action == "unpin":
        preference.is_pinned = False
    elif action in {"hide", "delete_for_me"}:
        preference.is_hidden = True
        preference.is_pinned = False
    elif action == "archive":
        if current_user.role != UserRole.SUPER_ADMIN.value or conversation.kind == "general":
            abort(403)
        conversation.is_archived = True
    else:
        return jsonify({"ok": False, "error": "Неизвестное действие."}), 400
    db.session.commit()
    return jsonify({"ok": True, "action": action})


@staff_messenger_bp.post("/staff-messenger/api/conversations/<int:conversation_id>/channel-permissions")
@login_required
def update_channel_permissions(current_user, conversation_id):
    _check_account(current_user, write=True)
    if current_user.role != UserRole.SUPER_ADMIN.value:
        abort(403)
    conversation = db.session.get(StaffChatConversation, conversation_id)
    if not conversation or conversation.kind != "channel" or conversation.is_archived:
        abort(404)
    payload = request.get_json(silent=True) or {}
    raw_ids = payload.get("writer_ids", [])
    try:
        writer_ids = {int(value) for value in raw_ids}
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Некорректный список сотрудников."}), 400
    participant_ids = {row.user_id for row in StaffChatParticipant.query.filter_by(conversation_id=conversation.id).all()}
    if not writer_ids.issubset(participant_ids):
        return jsonify({"ok": False, "error": "Публиковать могут только участники канала."}), 400
    participants = StaffChatParticipant.query.filter_by(conversation_id=conversation.id).all()
    for participant in participants:
        if participant.user_id == current_user.id:
            continue
        permission = StaffChatChannelPermission.query.filter_by(
            conversation_id=conversation.id, user_id=participant.user_id
        ).first()
        if permission is None:
            permission = StaffChatChannelPermission(conversation_id=conversation.id, user_id=participant.user_id)
            db.session.add(permission)
        permission.can_post = participant.user_id in writer_ids
    db.session.commit()
    return jsonify({"ok": True, "writer_count": len(writer_ids)})


@staff_messenger_bp.get("/staff-messenger/api/conversations/<int:conversation_id>/messages")
@login_required
def poll_messages(current_user, conversation_id):
    _check_account(current_user)
    conversation = db.session.get(StaffChatConversation, conversation_id)
    if not _conversation_access(current_user, conversation):
        abort(404)
    before_id = max(0, request.args.get("before", type=int) or 0)
    after_id = max(0, request.args.get("after", type=int) or 0)
    if before_id:
        rows = StaffChatMessage.query.filter(
            StaffChatMessage.conversation_id == conversation.id,
            StaffChatMessage.id < before_id,
        ).order_by(StaffChatMessage.id.desc()).limit(40).all()
        rows.reverse()
    else:
        rows = _load_messages(conversation.id, after_id=after_id)
    own_recent = StaffChatMessage.query.filter_by(
        conversation_id=conversation.id
    ).order_by(StaffChatMessage.id.desc()).limit(60).all()
    return jsonify({
        "ok": True,
        "messages": [_message_payload(item, current_user) for item in rows],
        "status_updates": [_message_payload(item, current_user) for item in own_recent],
        "typing": _typing_users(conversation.id, current_user.id),
        "server_time": datetime.utcnow().strftime("%H:%M:%S"),
    })


@staff_messenger_bp.post("/staff-messenger/api/conversations/<int:conversation_id>/read")
@login_required
def mark_read(current_user, conversation_id):
    _check_account(current_user)
    conversation = db.session.get(StaffChatConversation, conversation_id)
    if not _conversation_access(current_user, conversation):
        abort(404)
    participant = _ensure_participant(conversation, current_user.id, added_by=current_user.id)
    last_message = StaffChatMessage.query.filter_by(
        conversation_id=conversation.id, is_deleted=False
    ).order_by(StaffChatMessage.id.desc()).first()
    if last_message and last_message.id > participant.last_read_message_id:
        participant.last_read_message_id = last_message.id
        participant.last_read_at = datetime.utcnow()
    db.session.query(StaffChatTyping).filter_by(
        conversation_id=conversation.id, user_id=current_user.id
    ).delete(synchronize_session=False)
    db.session.commit()
    return jsonify({"ok": True, "last_read_message_id": participant.last_read_message_id})


@staff_messenger_bp.post("/staff-messenger/api/conversations/<int:conversation_id>/typing")
@login_required
def update_typing(current_user, conversation_id):
    _check_account(current_user, write=True)
    conversation = db.session.get(StaffChatConversation, conversation_id)
    if not _conversation_access(current_user, conversation, write=True):
        abort(404)
    now = datetime.utcnow()
    row = StaffChatTyping.query.filter_by(
        conversation_id=conversation.id, user_id=current_user.id
    ).first()
    if not row:
        row = StaffChatTyping(conversation_id=conversation.id, user_id=current_user.id,
                              expires_at=now + timedelta(seconds=9), updated_at=now)
        db.session.add(row)
    else:
        row.expires_at = now + timedelta(seconds=9)
        row.updated_at = now
    db.session.commit()
    return jsonify({"ok": True})


@staff_messenger_bp.post("/staff-messenger/api/conversations/<int:conversation_id>/messages")
@login_required
def send_message(current_user, conversation_id):
    _check_account(current_user, write=True)
    conversation = db.session.get(StaffChatConversation, conversation_id)
    if not _conversation_access(current_user, conversation, write=True):
        abort(404)
    body = (request.form.get("body") or "").strip()
    if len(body) > 5000:
        return jsonify({"ok": False, "error": "Сообщение не должно превышать 5000 символов."}), 400
    uploads = [item for item in request.files.getlist("attachments") if item and item.filename]
    if len(uploads) > MAX_ATTACHMENTS:
        return jsonify({"ok": False, "error": f"Можно прикрепить не более {MAX_ATTACHMENTS} файлов."}), 400
    reply_to_id = request.form.get("reply_to", type=int)
    reply = db.session.get(StaffChatMessage, reply_to_id) if reply_to_id else None
    if reply_to_id and (not reply or reply.conversation_id != conversation.id or reply.is_deleted):
        return jsonify({"ok": False, "error": "Сообщение для ответа не найдено."}), 400
    if not body and not uploads:
        return jsonify({"ok": False, "error": "Напишите сообщение или прикрепите файл."}), 400
    staged = []
    total_size = 0
    root = _attachment_root()
    for uploaded in uploads:
        filename = secure_filename(Path(uploaded.filename).name)[:180]
        extension = Path(filename).suffix.lower()
        if not filename or extension not in ALLOWED_EXTENSIONS:
            for item in staged:
                item["path"].unlink(missing_ok=True)
            return jsonify({"ok": False, "error": f"Тип файла «{filename or uploaded.filename}» не разрешён."}), 400
        content = uploaded.stream.read(MAX_ATTACHMENT_BYTES + 1)
        if len(content) > MAX_ATTACHMENT_BYTES:
            for item in staged:
                item["path"].unlink(missing_ok=True)
            return jsonify({"ok": False, "error": f"Файл «{filename}» больше 5 МБ."}), 400
        total_size += len(content)
        if total_size > MAX_TOTAL_ATTACHMENT_BYTES:
            for item in staged:
                item["path"].unlink(missing_ok=True)
            return jsonify({"ok": False, "error": "Суммарный размер вложений превышает 8 МБ."}), 400
        storage_name = uuid.uuid4().hex
        staged_path = root / storage_name
        staged_path.write_bytes(content)
        staged.append({
            "path": staged_path, "name": filename, "storage_name": storage_name,
            "extension": extension, "size": len(content), "sha256": hashlib.sha256(content).hexdigest(),
            "mime": mimetypes.guess_type(filename)[0] or "application/octet-stream",
        })
    now = datetime.utcnow()
    message = StaffChatMessage(
        conversation_id=conversation.id, sender_user_id=current_user.id,
        body=body, reply_to_id=reply.id if reply else None, created_at=now,
    )
    db.session.add(message)
    db.session.flush()
    for item in staged:
        db.session.add(StaffChatAttachment(
            message_id=message.id, uploaded_by_user_id=current_user.id,
            original_name=item["name"], storage_name=item["storage_name"],
            extension=item["extension"], mime_type=item["mime"],
            size_bytes=item["size"], sha256=item["sha256"],
        ))
    conversation.updated_at = now
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        for item in staged:
            item["path"].unlink(missing_ok=True)
        logger.exception("staff_messenger_message_commit_failed")
        return jsonify({"ok": False, "error": "Не удалось сохранить сообщение."}), 500
    db.session.refresh(message)
    try:
        _send_web_push(message, conversation)
    except Exception:
        logger.exception("staff_messenger_web_push_dispatch_failed")
    return jsonify({"ok": True, "message": _message_payload(message, current_user)}), 201


@staff_messenger_bp.post("/staff-messenger/api/messages/<int:message_id>/delete")
@login_required
def delete_message(current_user, message_id):
    _check_account(current_user, write=True)
    message = db.session.get(StaffChatMessage, message_id)
    conversation = db.session.get(StaffChatConversation, message.conversation_id) if message else None
    if not message or not _conversation_access(current_user, conversation, write=True):
        abort(404)
    if message.sender_user_id != current_user.id and current_user.role != UserRole.SUPER_ADMIN.value:
        abort(403)
    if not message.is_deleted:
        message.is_deleted = True
        message.body = ""
        for attachment in list(message.attachments):
            try:
                (_attachment_root() / attachment.storage_name).unlink(missing_ok=True)
            except OSError:
                logger.warning("Could not remove deleted chat attachment %s", attachment.id)
            db.session.delete(attachment)
        db.session.query(StaffChatReaction).filter_by(message_id=message.id).delete(synchronize_session=False)
        db.session.commit()
    return jsonify({"ok": True, "message": _message_payload(message, current_user)})


@staff_messenger_bp.post("/staff-messenger/api/messages/<int:message_id>/reactions")
@login_required
def toggle_reaction(current_user, message_id):
    _check_account(current_user, write=True)
    message = db.session.get(StaffChatMessage, message_id)
    if not message or not _conversation_access(
        current_user, db.session.get(StaffChatConversation, message.conversation_id), write=True
    ) or message.is_deleted:
        abort(404)
    payload = request.get_json(silent=True) or request.form
    emoji = str(payload.get("emoji", "")).strip()
    if emoji not in REACTIONS:
        return jsonify({"ok": False, "error": "Недопустимая реакция."}), 400
    existing = StaffChatReaction.query.filter_by(
        message_id=message.id, user_id=current_user.id, emoji=emoji
    ).first()
    if existing:
        db.session.delete(existing)
        active = False
    else:
        db.session.add(StaffChatReaction(message_id=message.id, user_id=current_user.id, emoji=emoji))
        active = True
    db.session.commit()
    db.session.refresh(message)
    # Return the updated aggregate so the client can update only the reaction
    # strip without re-rendering (or replacing) the surrounding message card.
    return jsonify({"ok": True, "active": active, "message": _message_payload(message, current_user)})


@staff_messenger_bp.get("/staff-messenger/search")
@login_required
def search_messages(current_user):
    _check_account(current_user)
    conversation_id = request.args.get("conversation", type=int)
    query = " ".join((request.args.get("q") or "").split())[:100]
    if len(query) < 2:
        return jsonify({"ok": True, "results": []})
    conversation = db.session.get(StaffChatConversation, conversation_id) if conversation_id else None
    if not _conversation_access(current_user, conversation):
        abort(404)
    rows = StaffChatMessage.query.filter(
        StaffChatMessage.conversation_id == conversation.id,
        StaffChatMessage.is_deleted.is_(False),
        StaffChatMessage.body.ilike(f"%{query}%", escape="\\"),
    ).order_by(StaffChatMessage.id.desc()).limit(30).all()
    results = []
    for item in rows:
        sender = User.query.get(item.sender_user_id)
        profile = _user_profile(sender)
        results.append({
        "id": item.id,
        "sender": profile["full_name"] if profile else "Сотрудник",
        "sender_position": profile["position"] if profile else "",
        "body": item.body[:280],
        "created_at": item.created_at.strftime("%d.%m.%Y %H:%M"),
        })
    return jsonify({"ok": True, "results": results})


@staff_messenger_bp.get("/staff-messenger/attachments/<int:attachment_id>")
@login_required
def download_attachment(current_user, attachment_id):
    _check_account(current_user)
    item = db.session.get(StaffChatAttachment, attachment_id)
    if not item:
        abort(404)
    message = db.session.get(StaffChatMessage, item.message_id)
    conversation = db.session.get(StaffChatConversation, message.conversation_id) if message else None
    if not message or message.is_deleted or not _conversation_access(current_user, conversation):
        abort(404)
    path = _attachment_root() / item.storage_name
    if not path.is_file() or path.stat().st_size != item.size_bytes:
        abort(404)
    response = send_file(path, mimetype=item.mime_type, as_attachment=True,
                         download_name=item.original_name, max_age=0, conditional=True)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response

