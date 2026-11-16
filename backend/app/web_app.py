from functools import wraps
from pathlib import Path
import html
from datetime import datetime, timedelta
import requests, threading, json, os, logging, queue, io, uuid, time, hmac, hashlib, urllib.parse, secrets, re, zipfile
from flask import Blueprint, Flask, Response, after_this_request, flash, redirect, render_template, request, session, url_for, jsonify, abort, send_from_directory, send_file, g, current_app
from sqlalchemy import and_, case as sa_case, event, func, or_, text as sql_text, false, true
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError
from itsdangerous import URLSafeSerializer
from config import settings
from bot_messages import text as bot_message_text
from database import (
    db, verify_password, hash_password, Student, User, Direction, EventQuota, EventDay, DayParticipation,
    DirectionQuestion, StudentLeadership, DirectionStatus, NotificationTemplate, DirectionChat, TelegramChatCandidate,
    EducationType, StudentInviteLink, CompetitionAnnouncement, EventLeader, EventQuotaDecline, StudentActivity, HttpAuditLog, AdminReportSignature, ReportArchiveDocument, ReportArchiveDocumentDirection, ReportArchiveBackup, PortalSetting, ApplicationDecision, SiteNotification, SiteNotificationRead, record_activity,
    student_directions, UserRole, StudentQuotaStat, Lesson, QuotaDirection, EventQuotaChat, MessengerChat, MessengerChatCandidate, MessengerIdentity, StaffIncidentCase, StaffIncidentNote,
    get_direction_quota_ids, get_quota_direction_ids, get_quota_directions, set_quota_directions, get_quota_chat_targets, set_quota_chat_targets,
)

logger = logging.getLogger(__name__)
from services.portal import BOT_COMMANDS

notification_queue = queue.Queue()
_flask_app_instance = None
_login_failures = {}
_otp_failures = {}
_otp_issued = {}
_api_rate_windows = {}
_api_rate_lock = threading.Lock()
_api_rate_last_cleanup = 0.0
_application_block_expiry_lock = threading.Lock()
_staff_incident_refresh_lock = threading.Lock()
_staff_incident_refresh_last_monotonic = 0.0

def csrf_token():
    """Return a per-session synchronizer token used by all non-Mini-App writes."""
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token

def _student_app_rate_limited(remote_addr, is_write, route_key=None, cap_override=None):
    """Per-route in-process fallback guard for public app APIs and bot ingress.

    The route key prevents many different endpoints from consuming a single shared-IP
    bucket (common behind campus NAT or a reverse proxy). A separate cap can be used
    for the MAX webhook while the same bounded counter store is reused.
    """
    global _api_rate_last_cleanup
    now = time.monotonic()
    key = (remote_addr or "unknown", str(route_key or "student-app-api"), "write" if is_write else "read")
    # The write cap mirrors the stricter distributed quota. Reads stay generous
    # because one campus NAT can represent many simultaneously active students.
    cap = max(1, int(cap_override)) if cap_override is not None else (180 if is_write else 3600)
    with _api_rate_lock:
        if now - _api_rate_last_cleanup > 60:
            stale_before = now - 60
            for old_key in list(_api_rate_windows):
                bucket = _api_rate_windows[old_key]
                while bucket and bucket[0] <= stale_before:
                    bucket.pop(0)
                if not bucket:
                    _api_rate_windows.pop(old_key, None)
            # Never clear every counter when arbitrary source addresses create
            # many keys. Evict only the oldest entries and retain active buckets.
            if len(_api_rate_windows) > 10000:
                overflow = len(_api_rate_windows) - 9000
                oldest = sorted(
                    _api_rate_windows,
                    key=lambda item: _api_rate_windows[item][-1] if _api_rate_windows[item] else 0,
                )[:overflow]
                for old_key in oldest:
                    _api_rate_windows.pop(old_key, None)
            _api_rate_last_cleanup = now
        bucket = _api_rate_windows.setdefault(key, [])
        cutoff = now - 60
        while bucket and bucket[0] <= cutoff:
            bucket.pop(0)
        if len(bucket) >= cap:
            return True
        bucket.append(now)
        return False

def set_flask_app(app):
    global _flask_app_instance
    _flask_app_instance = app

def notification_worker():
    while True:
        try:
            task = notification_queue.get(timeout=1)
            if task is None: break
            try:
                if len(task) == 2:  # Backward-compatible Telegram delivery jobs.
                    chat_id, text = task
                    if not settings.BOT_TOKEN:
                        continue
                    from services.telegram import send_tg
                    if not send_tg(chat_id, text):
                        logger.warning("Telegram delivery failed for an announcement")
                    time.sleep(0.06)
                else:
                    platform, recipient_id, text, is_chat = task
                    from services.messenger_transports import send_message
                    if not send_message(platform, recipient_id, text, is_chat=is_chat):
                        logger.warning("%s announcement delivery failed", platform)
                    time.sleep(0.12)
            except Exception:
                logger.exception("Messenger delivery failed")
        except queue.Empty: continue
        except Exception as e: logger.error("Notification worker error (%s)", type(e).__name__)


def _telegram_api(method, payload, attempts=3, timeout=10):
    """Call Telegram Bot API with retries for transient network/server failures."""
    if not settings.BOT_TOKEN:
        return None
    url = f"https://api.telegram.org/bot{settings.BOT_TOKEN}/{method}"
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            resp = requests.post(url, json=payload, timeout=timeout)
            try:
                data = resp.json()
            except ValueError:
                data = {"ok": False, "description": resp.text[:500]}
            if data.get("ok"):
                return data
            last_error = data.get("description") or resp.text[:500]
            # Retry rate limits and Telegram/server-side transient failures.
            if resp.status_code in {429, 500, 502, 503, 504} and attempt < attempts:
                retry_after = (data.get("parameters") or {}).get("retry_after", 1)
                import time
                time.sleep(min(max(int(retry_after), 1), 5))
                continue
            logger.error("Telegram API %s failed (attempt %s/%s): %s", method, attempt, attempts, last_error)
            return None
        except requests.RequestException as exc:
            last_error = f"network error ({type(exc).__name__})"
            if attempt < attempts:
                import time
                time.sleep(attempt)
                continue
            logger.error("Telegram API %s network error (%s)", method, type(exc).__name__)
    return None

def _get_bot_identity():
    data = _telegram_api("getMe", {}, attempts=2, timeout=8)
    if not data:
        return None
    return data.get("result") or {}

def _resolve_chat_id(chat_id):
    """Resolve a public @username or keep a numeric chat ID.

    A bot username is deliberately rejected: it identifies the bot's private
    user account, not the group/channel where announcements should be posted.
    """
    raw = str(chat_id or '').strip()
    if not raw:
        return None, {"error": "Chat ID не указан."}
    if not raw.startswith('@'):
        return raw, None
    data = _telegram_api('getChat', {'chat_id': raw}, attempts=2, timeout=8)
    if not data:
        return None, {"error": "Telegram не смог найти чат по этому username."}
    chat = data.get('result') or {}
    bot = _get_bot_identity()
    bot_username = (bot.get("username") or "").lower()
    chat_username = (chat.get("username") or "").lower()
    if bot_username and chat_username == bot_username and chat.get("type") == "private":
        return None, {"error": "Вы указали username самого бота. Нужен username группы/канала или числовой Chat ID (-100...)."}
    resolved = chat.get('id')
    if resolved is None:
        return None, {"error": "Telegram вернул чат без ID."}
    if chat.get("type") not in {"group", "supergroup", "channel"}:
        return None, {"error": "Для направления нужен групповой чат, супергруппа или канал. Username пользователя/бота не подходит."}
    return str(resolved), chat

def _send_tg(chat_id, text, reply_markup=None):
    if not chat_id or not settings.BOT_TOKEN:
        return False
    payload = {"chat_id": str(chat_id), "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    started = time.monotonic()
    data = _telegram_api('sendMessage', payload, attempts=3, timeout=10)
    from services.bot_journal import record_bot_event
    record_bot_event('telegram', 'outgoing', 'message_sent' if data else 'message_failed',
                     'success' if data else 'error', actor_id=chat_id,
                     summary='Отправка из веб-панели', duration_ms=(time.monotonic()-started)*1000)
    return bool(data)


def _send_tg_detailed(chat_id, text, reply_markup=None, attempts=3, timeout=10):
    if not chat_id or not settings.BOT_TOKEN:
        return False, "BOT_TOKEN не задан."
    payload = {"chat_id": str(chat_id), "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    started = time.monotonic()
    data, error = _telegram_api_detailed("sendMessage", payload, attempts=attempts, timeout=timeout)
    from services.bot_journal import record_bot_event
    record_bot_event('telegram', 'outgoing', 'message_sent' if data else 'message_failed',
                     'success' if data else 'error', actor_id=chat_id,
                     summary='Отправка из веб-панели', duration_ms=(time.monotonic()-started)*1000)
    return bool(data), error


def process_expired_application_blocks(limit=25):
    """Close due application blocks once, log the system decision, and notify the student."""
    if not _application_block_expiry_lock.acquire(blocking=False):
        return 0
    try:
        now = datetime.utcnow()
        latest_ids = db.session.query(
            ApplicationDecision.student_id.label("student_id"),
            ApplicationDecision.direction_id.label("direction_id"),
            func.max(ApplicationDecision.id).label("latest_id"),
        ).group_by(ApplicationDecision.student_id, ApplicationDecision.direction_id).subquery()
        due_blocks = ApplicationDecision.query.join(
            latest_ids, ApplicationDecision.id == latest_ids.c.latest_id
        ).filter(
            ApplicationDecision.decision == DirectionStatus.REJECTED.value,
            ApplicationDecision.blocked_until.is_not(None),
            ApplicationDecision.blocked_until <= now,
            ApplicationDecision.cleared_at.is_(None),
        ).order_by(ApplicationDecision.blocked_until.asc()).limit(max(1, min(int(limit), 100))).all()
        if not due_blocks:
            return 0

        notification_targets = []
        for decision in due_blocks:
            student = Student.query.get(decision.student_id)
            direction = Direction.query.get(decision.direction_id)
            decision.cleared_at = now
            decision.cleared_by_user_id = None
            decision.clear_reason = "Автоматически снята системой: срок блокировки истёк."
            student_name = student.full_name if student else f"ID {decision.student_id}"
            direction_name = direction.name if direction else f"ID {decision.direction_id}"
            record_activity(
                "application_block_auto_expired",
                f'Система автоматически сняла блокировку студента «{student_name}» по направлению '
                f'«{direction_name}»: срок истёк {decision.blocked_until.strftime("%d.%m.%Y %H:%M")}. '
                "Студент снова может подать заявление.",
                student_id=decision.student_id, direction_id=decision.direction_id,
            )
            notification_targets.append((decision, student, direction, student_name, direction_name))

        # Commit the state change before sending Telegram messages. If notification
        # delivery fails, the unblocking still remains effective and the failure is logged.
        db.session.commit()
        for decision, student, direction, student_name, direction_name in notification_targets:
            delivered = False
            error = "У студента не указан Telegram ID."
            if student and student.tg_id and int(student.tg_id) > 0:
                message = (
                    "✅ <b>Срок блокировки истёк</b>\n\n"
                    f"Здравствуйте, {html.escape(student_name)}!\n"
                    f"Ограничение на подачу заявления в направлении «{html.escape(direction_name)}» снято автоматически, "
                    f"так как установленный срок закончился {decision.blocked_until.strftime('%d.%m.%Y в %H:%M')}.\n\n"
                    "Теперь вы снова можете подать заявление в это направление."
                )
                delivered, error = _send_tg_detailed(student.tg_id, message, attempts=1, timeout=6)
            record_activity(
                "application_block_clear_notice_sent" if delivered else "application_block_clear_notice_failed",
                (f'Уведомление об автоматическом снятии блокировки студенту «{student_name}» по направлению '
                 f'«{direction_name}» {"доставлено через Telegram-бота" if delivered else "не доставлено через Telegram-бота"}. '
                 + ("" if delivered else f"Причина: {error or 'неизвестна'}")),
                student_id=decision.student_id, direction_id=decision.direction_id,
            )
        db.session.commit()
        return len(due_blocks)
    except Exception:
        db.session.rollback()
        logger.exception("Не удалось обработать истёкшие блокировки заявлений")
        return 0
    finally:
        _application_block_expiry_lock.release()


def _telegram_api_detailed(method, payload, attempts=3, timeout=10):
    if not settings.BOT_TOKEN:
        return None, "BOT_TOKEN не задан."
    url = f"https://api.telegram.org/bot{settings.BOT_TOKEN}/{method}"
    last_error = None
    import time
    for attempt in range(1, attempts + 1):
        try:
            resp = requests.post(url, json=payload, timeout=timeout)
            try:
                data = resp.json()
            except ValueError:
                data = {"ok": False, "description": resp.text[:500]}
            if data.get("ok"):
                return data, None
            last_error = data.get("description") or resp.text[:500] or f"HTTP {resp.status_code}"
            if resp.status_code in {429, 500, 502, 503, 504} and attempt < attempts:
                retry_after = (data.get("parameters") or {}).get("retry_after", 1)
                time.sleep(min(max(int(retry_after), 1), 5))
                continue
            break
        except requests.RequestException as exc:
            last_error = f"network error ({type(exc).__name__})"
            if attempt < attempts:
                time.sleep(attempt)
    logger.error("Telegram API %s failed: %s", method, last_error)
    return None, last_error or "Неизвестная ошибка Telegram."

def send_direction_chat(direction_id, text, reply_markup=None):
    """Send an announcement to every active Telegram chat linked to a direction."""
    sent = 0
    try:
        chats = DirectionChat.query.filter_by(direction_id=direction_id, is_active=True).all()
        logger.info("Broadcast to direction %s: %s active Telegram chat(s)", direction_id, len(chats))
        for chat in chats:
            stable_chat_id, _ = _resolve_chat_id(chat.chat_id)
            if not stable_chat_id:
                logger.error("Cannot resolve configured direction chat (record #%s)", chat.id)
                continue
            if stable_chat_id != str(chat.chat_id):
                chat.chat_id = stable_chat_id
                db.session.commit()
            if _send_tg(stable_chat_id, text, reply_markup=reply_markup):
                sent += 1
            else:
                logger.error("Broadcast failed for direction %s", direction_id)
    except Exception:
        logger.exception("Direction chat broadcast failed for direction %s", direction_id)
    logger.info("Broadcast result for direction %s: %s/%s delivered", direction_id, sent, len(chats) if 'chats' in locals() else 0)
    return sent

def is_student_council_direction(direction):
    """The Volunteer Team direction broadcasts system-wide posts to its active chats."""
    if not direction:
        return False
    value = f"{direction.name or ''} {direction.code or ''}".strip().lower().replace("ё", "е")
    return ("волонтерка" in value or "волонтёрка" in value or
            "student council" in value or "student_council" in value or
            value.strip() in {"studcouncil", "volunteer", "volunteering", "сс", "sc"})

def create_direction_invite_links(direction_id, student_name=None):
    """Create join-request invite links for every active chat of a direction."""
    links = []
    if not settings.BOT_TOKEN:
        return links
    try:
        chats = DirectionChat.query.filter_by(direction_id=direction_id, is_active=True).all()
        for chat in chats:
            stable_chat_id, _ = _resolve_chat_id(chat.chat_id)
            if not stable_chat_id:
                continue
            if stable_chat_id != str(chat.chat_id):
                chat.chat_id = stable_chat_id
            payload = {
                "chat_id": stable_chat_id,
                "name": f"Студсовет • {student_name or 'Студент'}"[:32],
                "creates_join_request": True,
            }
            data = _telegram_api("createChatInviteLink", payload, attempts=3, timeout=10)
            invite = (data or {}).get("result", {}).get("invite_link")
            if invite:
                links.append({"title": chat.title or stable_chat_id, "link": invite, "chat_id": stable_chat_id})
        db.session.commit()
    except Exception:
        logger.exception("Не удалось создать invite-ссылки для направления %s", direction_id)
        db.session.rollback()
    return links

def send_direction_invites(student, direction):
    """Send one invite link message per active direction chat to the student."""
    if not student or not student.tg_id or student.tg_id <= 0:
        return 0
    links = create_direction_invite_links(direction.id, student.full_name)
    if not links:
        return 0
    sent = 0
    for item in links:
        text = (
            f"🔗 <b>Приглашение в «{html.escape(direction.name)}»</b>\n\n"
            f"Чат: <b>{html.escape(item['title'])}</b>\n\n"
            f"<a href=\"{html.escape(item['link'], quote=True)}\">Вступить в чат</a>"
        )
        if _send_tg(student.tg_id, text):
            sent += 1
    return sent

def remove_student_from_direction_chats(student, direction):
    """Revoke access to a withdrawn direction while preserving shared/other chosen chats."""
    try:
        from services.telegram import remove_student_from_direction_chats as _remove
        return _remove(student, direction)
    except Exception:
        logger.exception("Не удалось обновить членство в чатах направления %s", getattr(direction, "id", None))
        return 0

def telegram_targets_for_directions(direction_ids):
    """Resolve active Telegram chats from selected directions, never from submitted chat IDs.

    Deduplicate chat identifiers across directions; publishing a saved event also
    resolves the *current* chat configuration, including chats attached later.
    """
    ids = {int(value) for value in direction_ids if value is not None}
    if not ids:
        return []
    rows = DirectionChat.query.filter(
        DirectionChat.direction_id.in_(ids), DirectionChat.is_active.is_(True)
    ).order_by(DirectionChat.id).all()
    seen, result = set(), []
    for chat in rows:
        key = str(chat.chat_id).strip()
        if key and key not in seen:
            seen.add(key)
            result.append((chat.direction_id, key))
    return result


def _event_chat_picker_options():
    """Return only chats that can safely be assigned to this specific event.

    Telegram groups already wired as direction-wide or permanent rooms are
    excluded from event-specific assignments, because closing an event must
    never remove members from a shared community. Unbound Telegram groups are
    available after the bot has discovered them. VK/MAX choices must be active
    and connected to a direction selected for the event.
    """
    from database import SharedActivityChat
    rows = {}
    direction_names = {direction.id: direction.name for direction in Direction.query.all()}
    direction_chat_ids = {str(row.chat_id) for row in DirectionChat.query.all()}
    permanent_chat_ids = {str(row.chat_id) for row in SharedActivityChat.query.all()}
    assigned_chat_ids = {str(row.chat_id) for row in EventQuotaChat.query.filter_by(platform='telegram').all()}
    unavailable_telegram = direction_chat_ids | permanent_chat_ids | assigned_chat_ids

    for candidate in TelegramChatCandidate.query.order_by(TelegramChatCandidate.title.asc()).all():
        chat_id = str(candidate.chat_id or '').strip()
        if (not chat_id or candidate.chat_type not in {'group', 'supergroup'}
                or chat_id in unavailable_telegram):
            continue
        key = ('telegram', chat_id)
        rows[key] = {
            'key': f'telegram|{chat_id}', 'platform': 'telegram', 'platform_label': 'Telegram',
            'chat_id': chat_id, 'title': candidate.title or f'Группа Telegram {chat_id}',
            'direction_ids': [], 'directions_label': 'Отдельная группа мероприятия',
            'dedicated': True,
        }

    for chat in MessengerChat.query.filter(
            MessengerChat.is_active.is_(True), MessengerChat.platform.in_(['vk', 'max'])
    ).order_by(MessengerChat.platform.asc(), MessengerChat.title.asc()).all():
        chat_id = str(chat.chat_id or '').strip()
        if not chat_id:
            continue
        key = (chat.platform, chat_id)
        item = rows.get(key)
        if item is None:
            item = {
                'key': f'{chat.platform}|{chat_id}', 'platform': chat.platform,
                'platform_label': 'VK' if chat.platform == 'vk' else 'MAX',
                'chat_id': chat_id, 'title': chat.title or f'Чат {chat.platform.upper()}',
                'direction_ids': [], 'directions_label': '', 'dedicated': False,
            }
            rows[key] = item
        if chat.direction_id not in item['direction_ids']:
            item['direction_ids'].append(chat.direction_id)

    for item in rows.values():
        item['direction_ids'].sort()
        labels = [direction_names[did] for did in item['direction_ids'] if did in direction_names]
        if labels:
            item['directions_label'] = 'Направления: ' + ', '.join(labels)
    order = {'telegram': 0, 'vk': 1, 'max': 2}
    return sorted(rows.values(), key=lambda item: (order.get(item['platform'], 9), item['title'].casefold(), item['chat_id']))


def _resolve_event_chat_selection(valid_direction_ids, requested_keys):
    """Resolve posted keys against current active server-side chat configuration."""
    available = _event_chat_picker_options()
    by_key = {item['key']: item for item in available}
    selected = []
    invalid = []
    valid_directions = set(valid_direction_ids)
    for key in dict.fromkeys(str(value or '').strip() for value in requested_keys):
        if not key:
            continue
        item = by_key.get(key)
        if not item:
            invalid.append(key)
            continue
        associated = set(item['direction_ids'])
        if associated and not (associated & valid_directions):
            invalid.append(key)
            continue
        did = next((value for value in valid_direction_ids if value in associated), None)
        if did is None:
            # Dedicated Telegram groups do not belong to a direction-wide chat
            # binding; keep the first event direction as audit/context metadata.
            did = valid_direction_ids[0] if valid_direction_ids else None
        if did is None:
            invalid.append(key)
            continue
        selected.append((item['platform'], did, item['chat_id'], item['title']))
    return available, selected, invalid


def queue_social_chat_announcement(direction_ids, message):
    """Submit a common announcement once per active VK/MAX chat via each bot."""
    from services.system_broadcasts import social_recipients
    ids = {int(value) for value in direction_ids if value is not None}
    pending = set()
    for did in ids:
        for platform in ('vk', 'max'):
            if not getattr(settings, 'VK_BOT_TOKEN' if platform == 'vk' else 'MAX_BOT_TOKEN'):
                continue
            for recipient in social_recipients(direction_id=did, channels={platform + '_chats'})[platform + '_chats']:
                pending.add((platform, str(recipient)))
    for platform, recipient in sorted(pending):
        notification_queue.put_nowait((platform, recipient, message, True))
    return len(pending)


def _event_chat_announcement(quota):
    """Build one consistent event card for initial, scheduled and calendar sends."""
    days = sorted(getattr(quota, 'days', []) or [], key=lambda day: day.date)
    dates = ', '.join(day.date.strftime('%d.%m.%Y') for day in days) or 'уточняется'
    lines = [
        f"✦ <b>{html.escape(quota.event_title or 'Мероприятие')}</b>",
        '',
        f"📅 <b>Даты:</b> {html.escape(dates)}",
        f"🕒 <b>Время:</b> {html.escape(quota.time_range or 'уточняется')}",
        f"📍 <b>Место:</b> {html.escape(quota.location or 'уточняется')}",
        f"👥 <b>Мест:</b> {int(quota.total_places or 0)}",
    ]
    if getattr(quota, 'dress_code', None):
        lines.append(f"👔 <b>Дресс-код:</b> {html.escape(quota.dress_code)}")
    if getattr(quota, 'functionality', None):
        lines.append(f"🧩 <b>Что понадобится / функционал:</b> {html.escape(quota.functionality)}")
    if getattr(quota, 'event_description', None):
        lines.extend(['', html.escape(quota.event_description)])
    return '\n'.join(lines)


def queue_other_messenger_event(quota, message, *, batch_key=None):
    """Queue an event announcement only to the chat targets saved on that event."""
    from services.delivery_outbox import enqueue_calendar_announcement
    target_rows = EventQuotaChat.query.filter_by(quota_id=quota.id).all()
    targets = [(getattr(row, 'platform', 'telegram') or 'telegram', row.chat_id)
               for row in target_rows]
    result = enqueue_calendar_announcement(
        get_quota_direction_ids(quota.id), message,
        explicit_targets=targets,
        batch_key=batch_key or (f"quota:{quota.id}:scheduled" if quota.publish_mode == "scheduled"
                                else f"quota:{quota.id}:publish:{uuid.uuid4().hex}"),
        source_type='event', source_id=quota.id,
    )
    if result['missing_token'] and any(result['missing_token'].values()):
        logger.warning('Quota #%s: delivery skipped for chats with unconfigured bot tokens', quota.id)
    logger.info('Quota #%s chat dispatch: targets=%s queued=%s blocked=%s',
                quota.id, result['available'], result['queued'], result['blocked'])
    if not result['available']:
        logger.warning('Quota #%s: no explicitly selected event chat targets', quota.id)
        from services.bot_journal import record_bot_event
        for platform in ('telegram', 'vk', 'max'):
            record_bot_event(platform, 'chat', 'calendar_no_chats', 'error',
                             summary=f'Мероприятие #{quota.id}: нет выбранных чатов для отправки')
    elif sum(result['blocked'].values()):
        from services.bot_journal import record_bot_event
        for platform, count in result['blocked'].items():
            if count:
                record_bot_event(platform, 'system', 'calendar_token_missing', 'ignored',
                                 summary=f'Мероприятие #{quota.id}: ожидают токен {count} чатов')
    return result['queued']


def send_notification_by_template(student, template_key, variables):
    try:
        nt = NotificationTemplate.query.filter_by(key=template_key).first()
        if not nt: return False
        text = nt.template_text
        for var_name, var_value in variables.items():
            text = text.replace(f"{{{var_name}}}", html.escape(str(var_value)))
        queued = False
        if student.tg_id and student.tg_id > 0:
            notification_queue.put((student.tg_id, text))
            queued = True
        from database import MessengerIdentity
        from services.messenger_transports import send_message
        # Telegram template content may contain HTML. Strip markup before
        # sending to plain-text messenger adapters.
        from html import unescape
        import re
        plain = unescape(re.sub(r'<[^>]+>', '', text))
        for account in MessengerIdentity.query.filter_by(student_id=student.id).all():
            notification_queue.put((account.platform, account.external_user_id, plain, False))
            queued = True
        return queued
    except Exception as e: logger.error("Notification processing error (%s)", type(e).__name__)
    return False

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")
admin_bp = Blueprint("admin", __name__)
directions_bp = Blueprint("directions", __name__, url_prefix="/directions")
quotas_bp = Blueprint("quotas", __name__, url_prefix="/quotas")

@quotas_bp.before_request
def _employee_quota_scope_guard():
    """Keep employee event actions inside explicitly granted directions."""
    user_id = session.get("user_id")
    user = User.query.get(user_id) if user_id else None
    if not user or not user.is_active or user.role != UserRole.STAFF.value:
        return None
    from services.staff_access import direction_ids as staff_direction_ids
    endpoint = request.endpoint or ''
    level = 'manage' if request.method not in {'GET', 'HEAD', 'OPTIONS'} else 'view'
    permitted = set(staff_direction_ids(user, 'events', level))
    if endpoint == 'quotas.create_quota':
        manage_ids = set(staff_direction_ids(user, 'events', 'manage'))
        if not manage_ids:
            abort(403)
        if request.method == 'POST':
            submitted = set(request.form.getlist('direction_ids', type=int))
            if not submitted or not submitted.issubset(manage_ids):
                abort(403)
        return None
    if endpoint == 'quotas.quotas_list':
        return None
    if endpoint not in {'quotas.quota_participants', 'quotas.close_quota',
                        'quotas.publish_quota', 'quotas.mark_attendance'}:
        abort(403)
    quota_id = (request.view_args or {}).get('qid')
    if quota_id is None and (request.view_args or {}).get('pid') is not None:
        participation = DayParticipation.query.get(int(request.view_args['pid']))
        quota_id = participation.day.quota_id if participation and participation.day else None
    linked_ids = _quota_direction_scope_ids(int(quota_id)) if quota_id is not None else set()
    if not linked_ids or not linked_ids.issubset(permitted):
        abort(403)

@directions_bp.before_request
def _employee_direction_scope_guard():
    """Enforce direction grants for both global and single-direction employees."""
    user_id = session.get("user_id")
    user = User.query.get(user_id) if user_id else None
    if not user or not user.is_active or user.role != UserRole.STAFF.value:
        return None
    from services.staff_access import allowed as staff_allowed
    endpoint = request.endpoint or ''
    view_args = request.view_args or {}
    direction_id = view_args.get('did')
    if endpoint == 'directions.directions_list':
        return None
    if direction_id is None:
        return None
    direction = Direction.query.get(int(direction_id))
    if not direction or direction.is_archived:
        abort(404)
    # Staff may send messages to already-connected chats, but chat discovery,
    # assignment and configuration belong exclusively to the chief administrator.
    staff_chat_configuration_endpoints = {
        'directions.connect_chat_candidate',
        'directions.connect_social_chat',
        'directions.remove_social_chat',
        'directions.add_chat',
        'directions.chat_audience',
        'directions.delete_chat',
        'directions.test_chat',
    }
    if endpoint in staff_chat_configuration_endpoints:
        abort(403)
    section_for_endpoint = {
        'directions.approve_student': 'applications',
        'directions.activate_student': 'applications',
        'directions.reject_student': 'applications',
        'directions.manage_questions': 'applications',
        'directions.add_existing_student': 'students',
        'directions.remove_student': 'students',
        'directions.update_student_status': 'students',
        'directions.chat_message': 'chats',
    }
    if endpoint in {'directions.archive_direction', 'directions.restore_direction'}:
        abort(403)
    if endpoint in section_for_endpoint:
        section = section_for_endpoint[endpoint]
        if not staff_allowed(user, direction_id, section, 'manage'):
            abort(403)
        return None
    if endpoint in {'directions.direction_detail'}:
        if not any(staff_allowed(user, direction_id, section, 'view') or
                   staff_allowed(user, direction_id, section, 'manage')
                   for section in ('students', 'applications', 'events', 'lessons', 'notifications', 'chats')):
            abort(403)
        return None
    abort(403)
stats_bp = Blueprint("stats", __name__, url_prefix="/stats")
lessons_bp = Blueprint("lessons", __name__, url_prefix="/lessons")

student_app_bp = Blueprint("student_app", __name__)

STUDENT_APP_SEASONS = {
    "spring": {"label": "Весна", "emoji": "🌸", "object": "🌷", "group": "season", "description": "Розовое цветение, свежая мята и глубокая морская бирюза.", "palette": ['#F0A8C8', '#54DDAA', '#0B3540']},
    "summer": {"label": "Лето", "emoji": "☀️", "object": "🪁", "group": "season", "description": "Медовое золото, бирюзовый свет и океанический синий с более живой подсветкой.", "palette": ['#FFC46B', '#4CE0CB', '#0B3447']},
    "autumn": {"label": "Осень", "emoji": "🍂", "object": "🍁", "group": "season", "description": "Янтарь, медь и малиновый закат на графитовом фоне.", "palette": ['#FFB26B', '#EE637D', '#301724']},
    "winter": {"label": "Зима", "emoji": "❄️", "object": "⛄", "group": "season", "description": "Снежный белый, ледяной голубой и глубокая полярная ночь.", "palette": ['#E9F6FF', '#7CCAFF', '#0C2550']},
    "march_8": {"label": "8 Марта", "emoji": "🌷", "object": "💐", "group": "holiday", "description": "Тёплый розовый, сиреневая дымка и весенняя бирюза с праздничным свечением.", "palette": ['#FF9BC9', '#B38CFF', '#12314B']},
    "russia_day": {"label": "День России", "emoji": "✦", "object": "🎗️", "group": "holiday", "description": "Российский триколор в космическом оформлении: небесно-синий свет, рубиновые акценты и глубокий тёмно-синий фон.", "palette": ['#78AFFF', '#E7465B', '#0D2350']},
    "cosmonautics_day": {"label": "День космонавтики", "emoji": "🚀", "object": "🌌", "group": "holiday", "description": "Энергичная бирюза, фиолетовая глубина и динамичный свет старта.", "palette": ['#31D9FF', '#9B7BFF', '#0A2452']},
    "defender_day": {"label": "День защитника Отечества", "emoji": "🎖️", "object": "🛡️", "group": "holiday", "description": "Инженерный хвойный, сталь и сдержанная бронза.", "palette": ['#D0E6C6', '#CDA052', '#142E27']},
    "unity_day": {"label": "День народного единства", "emoji": "🤝", "object": "🕊️", "group": "holiday", "description": "Торжественный синий и рубиновый акценты на глубоком ночном фоне с белыми световыми деталями.", "palette": ['#6598FF', '#D94D65', '#111D37']},
    "new_year": {"label": "Новый год", "emoji": "✦", "object": "🎄", "group": "holiday", "description": "Изумрудное сияние, праздничное золото и полярная ночь.", "palette": ['#41F0CC', '#FFD77A', '#18264A']},
    "flag_day": {"label": "День Государственного флага России", "emoji": "✦", "object": "🏛️", "group": "holiday", "description": "Выразительная тема флага России: холодный синий, рубиновый акцент и глубокий тёмно-синий фон.", "palette": ['#4D87F5', '#E43E52', '#0D1B36']},
    "constitution_day": {"label": "День Конституции России", "emoji": "⚖️", "object": "📜", "group": "holiday", "description": "Торжественное оформление: бело-сине-красный триколор, глубокий государственный синий и сдержанное золотое свечение.", "palette": ['#F4E9C5', '#3978ED', '#101A32']},
    "student_day": {"label": "День российского студенчества", "emoji": "🎓", "object": "📚", "group": "holiday", "description": "Академический синий, сияющая лазурь и золотистый цвет достижений.", "palette": ['#5CB7FF', '#FFC857', '#18254A']},
    "christmas": {"label": "Рождество Христово", "emoji": "✦", "object": "🕯️", "group": "holiday", "description": "Сдержанное зимнее оформление: молочный свет, сапфировые оттенки и тёплое золото.", "palette": ['#E8F2FF', '#D9B66F', '#102344']},
    "spring_labour_day": {"label": "Праздник Весны и Труда", "emoji": "🌿", "object": "🌼", "group": "holiday", "description": "Свежая зелень, чистый небесный тон и солнечный янтарный акцент.", "palette": ['#8BD6A0', '#FFD078', '#12344A']},
    "victory_day": {"label": "День Победы", "emoji": "⭐", "object": "🌺", "group": "holiday", "description": "Памятная торжественная тема: глубокий синий, благородное золото и приглушённый гранатовый акцент.", "palette": ['#E7C36D', '#D86B70', '#10264A']},
}

# Each choice controls the entire Student App theme, not only its accent.
# RGB triplets are kept explicitly so translucent gradients render consistently
# in Chromium, mobile browsers and Telegram's embedded WebView.
STUDENT_APP_THEME_CSS = {
    "spring": {"season-accent": "#F0A8C8", "season-accent-rgb": "240,168,200", "season-secondary": "#54DDAA", "season-secondary-rgb": "84,221,170", "season-bg-a": "#1E1B31", "season-bg-b": "#0B3540", "season-bg-c": "#040D18", "season-panel-rgb": "28,54,61", "season-panel-dark-rgb": "10,24,34", "season-border-rgb": "240,168,200"},
    "summer": {"season-accent": "#FFC46B", "season-accent-rgb": "255,196,107", "season-secondary": "#4CE0CB", "season-secondary-rgb": "76,224,203", "season-bg-a": "#151D32", "season-bg-b": "#0B3447", "season-bg-c": "#06131F", "season-panel-rgb": "24,52,65", "season-panel-dark-rgb": "5,24,37", "season-border-rgb": "255,196,107"},
    "autumn": {"season-accent": "#FFB26B", "season-accent-rgb": "255,178,107", "season-secondary": "#EE637D", "season-secondary-rgb": "238,99,125", "season-bg-a": "#21111E", "season-bg-b": "#2A1B2D", "season-bg-c": "#100D1A", "season-panel-rgb": "47,29,43", "season-panel-dark-rgb": "21,14,28", "season-border-rgb": "255,178,107"},
    "winter": {"season-accent": "#E9F6FF", "season-accent-rgb": "233,246,255", "season-secondary": "#7CCAFF", "season-secondary-rgb": "124,202,255", "season-bg-a": "#06152D", "season-bg-b": "#0C2550", "season-bg-c": "#030A1A", "season-panel-rgb": "13,39,73", "season-panel-dark-rgb": "4,19,43", "season-border-rgb": "124,202,255"},
    "march_8": {"season-accent": "#FF9BC9", "season-accent-rgb": "255,155,201", "season-secondary": "#B38CFF", "season-secondary-rgb": "179,140,255", "season-bg-a": "#1A1632", "season-bg-b": "#12314B", "season-bg-c": "#090B18", "season-panel-rgb": "31,37,71", "season-panel-dark-rgb": "14,14,32", "season-border-rgb": "255,155,201"},
    "russia_day": {"season-accent": "#78AFFF", "season-accent-rgb": "120,175,255", "season-secondary": "#E7465B", "season-secondary-rgb": "231,70,91", "season-bg-a": "#07162D", "season-bg-b": "#10294D", "season-bg-c": "#050B1B", "season-panel-rgb": "14,39,69", "season-panel-dark-rgb": "4,16,34", "season-border-rgb": "120,175,255"},
    "cosmonautics_day": {"season-accent": "#31D9FF", "season-accent-rgb": "49,217,255", "season-secondary": "#9B7BFF", "season-secondary-rgb": "155,123,255", "season-bg-a": "#05142E", "season-bg-b": "#0A2452", "season-bg-c": "#020918", "season-panel-rgb": "10,37,73", "season-panel-dark-rgb": "3,14,35", "season-border-rgb": "49,217,255"},
    "defender_day": {"season-accent": "#D0E6C6", "season-accent-rgb": "208,230,198", "season-secondary": "#CDA052", "season-secondary-rgb": "205,160,82", "season-bg-a": "#071A17", "season-bg-b": "#142E27", "season-bg-c": "#040D0B", "season-panel-rgb": "18,47,39", "season-panel-dark-rgb": "5,19,15", "season-border-rgb": "208,230,198"},
    "unity_day": {"season-accent": "#6598FF", "season-accent-rgb": "101,152,255", "season-secondary": "#D94D65", "season-secondary-rgb": "217,77,101", "season-bg-a": "#09152D", "season-bg-b": "#12294A", "season-bg-c": "#070C1B", "season-panel-rgb": "16,40,69", "season-panel-dark-rgb": "5,17,34", "season-border-rgb": "101,152,255"},
    "new_year": {"season-accent": "#41F0CC", "season-accent-rgb": "65,240,204", "season-secondary": "#FFD77A", "season-secondary-rgb": "255,215,122", "season-bg-a": "#09172E", "season-bg-b": "#18264A", "season-bg-c": "#050B1C", "season-panel-rgb": "18,39,72", "season-panel-dark-rgb": "5,16,36", "season-border-rgb": "65,240,204"},
    "flag_day": {"season-accent": "#4D87F5", "season-accent-rgb": "77,135,245", "season-secondary": "#E43E52", "season-secondary-rgb": "228,62,82", "season-bg-a": "#08162F", "season-bg-b": "#14284B", "season-bg-c": "#070C1C", "season-panel-rgb": "16,39,69", "season-panel-dark-rgb": "5,17,35", "season-border-rgb": "77,135,245"},
    "constitution_day": {"season-accent": "#F4E9C5", "season-accent-rgb": "244,233,197", "season-secondary": "#3978ED", "season-secondary-rgb": "57,120,237", "season-bg-a": "#101A32", "season-bg-b": "#172C4E", "season-bg-c": "#070D1B", "season-panel-rgb": "24,39,64", "season-panel-dark-rgb": "7,17,35", "season-border-rgb": "244,233,197"},
    "student_day": {"season-accent": "#5CB7FF", "season-accent-rgb": "92,183,255", "season-secondary": "#FFC857", "season-secondary-rgb": "255,200,87", "season-bg-a": "#09162F", "season-bg-b": "#18254A", "season-bg-c": "#050B1B", "season-panel-rgb": "18,39,72", "season-panel-dark-rgb": "5,16,35", "season-border-rgb": "92,183,255"},
    "christmas": {"season-accent": "#E8F2FF", "season-accent-rgb": "232,242,255", "season-secondary": "#D9B66F", "season-secondary-rgb": "217,182,111", "season-bg-a": "#101C36", "season-bg-b": "#102344", "season-bg-c": "#050B1B", "season-panel-rgb": "23,42,69", "season-panel-dark-rgb": "7,17,35", "season-border-rgb": "232,242,255"},
    "spring_labour_day": {"season-accent": "#8BD6A0", "season-accent-rgb": "139,214,160", "season-secondary": "#FFD078", "season-secondary-rgb": "255,208,120", "season-bg-a": "#102A2C", "season-bg-b": "#12344A", "season-bg-c": "#06131D", "season-panel-rgb": "23,57,61", "season-panel-dark-rgb": "7,25,34", "season-border-rgb": "139,214,160"},
    "victory_day": {"season-accent": "#E7C36D", "season-accent-rgb": "231,195,109", "season-secondary": "#D86B70", "season-secondary-rgb": "216,107,112", "season-bg-a": "#101B35", "season-bg-b": "#10264A", "season-bg-c": "#070D1C", "season-panel-rgb": "25,42,69", "season-panel-dark-rgb": "8,17,35", "season-border-rgb": "231,195,109"},
}
for _theme_key, _theme_config in STUDENT_APP_SEASONS.items():
    _theme_config["css_vars"] = STUDENT_APP_THEME_CSS[_theme_key]

DEFAULT_STUDENT_APP_SEASON = "spring"

def current_student_app_season():
    setting = PortalSetting.query.filter_by(key="student_app_season").first()
    if setting and setting.value in STUDENT_APP_SEASONS:
        return setting.value
    return DEFAULT_STUDENT_APP_SEASON


def _hex_rgb_triplet(value, fallback="#FFB26B"):
    """Return a CSS-safe RGB triplet for the shared theme variables."""
    candidate = str(value or fallback).strip()
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", candidate):
        candidate = fallback
    return ",".join(str(int(candidate[index:index + 2], 16)) for index in (1, 3, 5))

# A read receipt changes only the current user's notification state, not
# student data or administrative settings. Observers may perform this action.
OBSERVER_READ_RECEIPT_ENDPOINTS = frozenset({
    "admin.notification_read", "admin.notifications_read_all", "staff_messenger.mark_read",
})
# Password rotation and logout are account-safety operations; unlike workspace
# mutations, they remain available to a read-only observer account.
OBSERVER_SAFE_POST_ENDPOINTS = OBSERVER_READ_RECEIPT_ENDPOINTS | frozenset({
    "auth.logout", "auth.change_password",
})


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth.login"))
        user = User.query.get(session["user_id"])
        if not user or not user.is_active or user.role not in {UserRole.SUPER_ADMIN.value, UserRole.STAFF.value, UserRole.OBSERVER.value, UserRole.LEADER.value} or session.get("auth_version") != (user.auth_version or 0):
            session.clear()
            return redirect(url_for("auth.login"))
        # The database is authoritative: role changes and disabled/renamed accounts
        # must take effect immediately instead of trusting stale session metadata.
        session["user_role"] = user.role
        session["user_login"] = user.email
        g.audit_actor_user_id = user.id
        g.audit_actor_login = user.email
        g.audit_actor_role = user.role
        if getattr(user, "must_change_password", False) and request.endpoint not in {"auth.change_password", "auth.logout"}:
            return redirect(url_for("auth.change_password"))
        if (user.role == UserRole.OBSERVER.value
                and request.method not in {"GET", "HEAD", "OPTIONS"}
                and not (request.method == "POST" and request.endpoint in OBSERVER_SAFE_POST_ENDPOINTS)):
            flash("У этой роли доступ только для просмотра.", "warning")
            fallback = url_for("admin.dashboard")
            return redirect(request.referrer or fallback)
        return f(*args, current_user=user, **kwargs)
    return decorated

def super_admin_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, current_user=None, **kwargs):
        if current_user.role != UserRole.SUPER_ADMIN.value:
            flash("Этот раздел доступен только главному администратору.", "danger")
            return redirect(url_for("admin.dashboard"))
        return f(*args, current_user=current_user, **kwargs)
    return decorated


def _staff_visible_direction_ids(user, sections=None):
    """Return the global admin scope or the permission-based employee scope."""
    if not user or not user.is_active:
        return set()
    if user.role == UserRole.SUPER_ADMIN.value:
        # The main administrator is never narrowed by assigned_direction_id.
        # Include archived directions for global reports and archive inspection.
        return {direction.id for direction in Direction.query.all()}
    from services.staff_access import SECTIONS as STAFF_SECTIONS, direction_ids as staff_direction_ids
    selected_sections = tuple(sections or STAFF_SECTIONS)
    return set().union(*(staff_direction_ids(user, section, 'view') for section in selected_sections))


def _quota_direction_scope_ids(quota_id):
    """Resolve all explicit and chat-linked directions associated with an event."""
    direction_ids = {int(value) for value in get_quota_direction_ids(quota_id) if value is not None}
    direction_ids.update(int(value) for (value,) in EventQuotaChat.query.with_entities(
        EventQuotaChat.direction_id
    ).filter(EventQuotaChat.quota_id == quota_id, EventQuotaChat.direction_id.is_not(None)).all())
    return direction_ids


def _quota_ids_exclusively_in_scope(direction_scope):
    """Events wholly assigned to the visible directions, never mixed with foreign directions."""
    allowed_ids = {int(value) for value in (direction_scope or set()) if value is not None}
    if not allowed_ids:
        return set()
    links = {}
    for quota_id, direction_id in QuotaDirection.query.with_entities(
        QuotaDirection.quota_id, QuotaDirection.direction_id
    ).all():
        if quota_id is not None and direction_id is not None:
            links.setdefault(int(quota_id), set()).add(int(direction_id))
    for quota_id, direction_id in EventQuotaChat.query.with_entities(
        EventQuotaChat.quota_id, EventQuotaChat.direction_id
    ).filter(EventQuotaChat.direction_id.is_not(None)).all():
        if quota_id is not None and direction_id is not None:
            links.setdefault(int(quota_id), set()).add(int(direction_id))
    return {quota_id for quota_id, linked_ids in links.items()
            if linked_ids and linked_ids.issubset(allowed_ids)}

def _statistics_period_window(period, date_from_value=None, date_to_value=None):
    """Parse a safe, inclusive event-date period into naive datetime bounds.

    EventDay.date is stored without a timezone. The exclusive upper bound keeps
    the complete final calendar day in the selected range.
    """
    today = datetime.utcnow().date()
    period = str(period or 'all').strip().lower()
    start_day = end_day = None
    if period == '7d':
        start_day, end_day = today - timedelta(days=6), today
    elif period == '30d':
        start_day, end_day = today - timedelta(days=29), today
    elif period == '90d':
        start_day, end_day = today - timedelta(days=89), today
    elif period == 'month':
        start_day, end_day = today.replace(day=1), today
    elif period == 'prev_month':
        end_day = today.replace(day=1) - timedelta(days=1)
        start_day = end_day.replace(day=1)
    elif period == 'year':
        start_day, end_day = today.replace(month=1, day=1), today
    elif period == 'custom':
        def parse_optional_date(value):
            if not value:
                return None
            try:
                return datetime.strptime(str(value), '%Y-%m-%d').date()
            except (TypeError, ValueError):
                return None
        start_day = parse_optional_date(date_from_value)
        end_day = parse_optional_date(date_to_value)
        if not start_day and not end_day:
            period = 'all'
    else:
        period = 'all'
    if start_day and end_day and end_day < start_day:
        start_day, end_day = end_day, start_day
    start_dt = datetime.combine(start_day, datetime.min.time()) if start_day else None
    end_exclusive = datetime.combine(end_day + timedelta(days=1), datetime.min.time()) if end_day else None
    return {
        'period': period,
        'date_from': start_day.isoformat() if start_day else '',
        'date_to': end_day.isoformat() if end_day else '',
        'start_dt': start_dt,
        'end_exclusive': end_exclusive,
        'is_filtered': bool(start_dt or end_exclusive),
    }

def _apply_statistics_day_window(query, period_filter):
    """Apply the same inclusive date window to any query joined to EventDay."""
    if period_filter.get('start_dt'):
        query = query.filter(EventDay.date >= period_filter['start_dt'])
    if period_filter.get('end_exclusive'):
        query = query.filter(EventDay.date < period_filter['end_exclusive'])
    return query


def analytics_view_required(f):
    """Allow the chief admin and observers to read analytics; observers stay read-only."""
    @wraps(f)
    @login_required
    def decorated(*args, current_user=None, **kwargs):
        if current_user.role not in {UserRole.SUPER_ADMIN.value, UserRole.STAFF.value, UserRole.OBSERVER.value}:
            abort(403)
        if current_user.role == UserRole.STAFF.value:
            from services.staff_access import direction_ids as staff_direction_ids
            if not staff_direction_ids(current_user, 'statistics', 'view'):
                abort(403)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            abort(403)
        return f(*args, current_user=current_user, **kwargs)
    return decorated


def archive_year_admin_required(f):
    """Allow the chief admin and archive admin to back up/delete one report year."""
    @wraps(f)
    @login_required
    def decorated(*args, current_user=None, **kwargs):
        if current_user.role != UserRole.SUPER_ADMIN.value:
            abort(403)
        return f(*args, current_user=current_user, **kwargs)
    return decorated

def _lesson_access_scope(current_user):
    """Return None for full lesson access, a set of allowed direction IDs, or an empty set.

    Employee visibility follows explicit lessons grants across active directions.
    The observer sees active directions read-only. A leader's web account is
    restricted to the assigned direction or a separately verified global council role.
    Student Mini App identities never reach these routes because they do not have
    a web-panel login session.
    """
    if current_user.role == UserRole.SUPER_ADMIN.value:
        # Main administrator has institution-wide access, independent of the
        # optional preferred direction saved for dashboard navigation.
        return _staff_visible_direction_ids(current_user)
    if current_user.role == UserRole.STAFF.value:
        from services.staff_access import direction_ids as staff_direction_ids
        return set(staff_direction_ids(current_user, 'lessons', 'view'))
    if current_user.role == UserRole.OBSERVER.value:
        return {direction.id for direction in Direction.query.all()
                if not getattr(direction, "is_archived", False)}
    if current_user.role != UserRole.LEADER.value:
        return set()

    if current_user.tg_id:
        student = Student.query.filter_by(tg_id=current_user.tg_id).first()
        if student:
            try:
                from services.permissions import has_global_council_access, allowed_direction_ids
                if has_global_council_access(student_id=student.id):
                    return None
                allowed = allowed_direction_ids(student.id)
                if allowed:
                    return set(allowed)
            except Exception:
                logger.exception("Не удалось определить область доступа руководителя к занятиям")

    if current_user.assigned_direction_id:
        return {int(current_user.assigned_direction_id)}
    return set()

def _lesson_can_manage_direction(current_user, direction_id):
    if current_user.role == UserRole.STAFF.value:
        from services.staff_access import allowed as staff_allowed
        return staff_allowed(current_user, direction_id, 'lessons', 'manage')
    scope = _lesson_access_scope(current_user)
    return scope is None or int(direction_id) in scope

def _lesson_manage_scope(current_user):
    if current_user.role == UserRole.STAFF.value:
        from services.staff_access import direction_ids as staff_direction_ids
        return set(staff_direction_ids(current_user, 'lessons', 'manage'))
    return _lesson_access_scope(current_user)

def _lesson_directions_for_user(current_user):
    scope = _lesson_manage_scope(current_user)
    query = Direction.query.order_by(Direction.name.asc())
    if scope is not None:
        if not scope:
            return []
        query = query.filter(Direction.id.in_(scope))
    return query.all()

def lesson_manager_required(f):
    """Require a web-panel manager role for all lesson write workflows."""
    @wraps(f)
    @login_required
    def decorated(*args, current_user=None, **kwargs):
        if current_user.role == UserRole.OBSERVER.value:
            # These endpoints render editor forms. Observers can see the same
            # data in the calendar, but should not be offered a change workflow.
            flash("В режиме наблюдателя доступен просмотр расписания без редактирования.", "info")
            return redirect(url_for("admin.calendar", date=request.args.get("date", "")[:10] or None))
        if _lesson_manage_scope(current_user) == set():
            flash("Управление занятиями доступно только аккаунтам с соответствующим разрешением.", "warning")
            return redirect(url_for("lessons.list_lessons"))
        return f(*args, current_user=current_user, **kwargs)
    return decorated

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        now = time.time()
        client = request.remote_addr or "unknown"
        # Prune old entries periodically and prevent unbounded growth from arbitrary source IPs.
        for old_client in list(_login_failures):
            if not _login_failures[old_client] or now - _login_failures[old_client][-1] >= 900:
                _login_failures.pop(old_client, None)
        if len(_login_failures) > 10000:
            overflow = len(_login_failures) - 9000
            oldest_clients = sorted(
                _login_failures,
                key=lambda item: _login_failures[item][-1] if _login_failures[item] else 0,
            )[:overflow]
            for old_client in oldest_clients:
                _login_failures.pop(old_client, None)
        for stale_user_id in list(_otp_issued):
            recent_codes = [stamp for stamp in _otp_issued[stale_user_id] if now - stamp < 900]
            if recent_codes:
                _otp_issued[stale_user_id] = recent_codes
            else:
                _otp_issued.pop(stale_user_id, None)
        attempts = [stamp for stamp in _login_failures.get(client, []) if now - stamp < 900]
        if len(attempts) >= 8:
            flash("Слишком много попыток входа. Повторите попытку через 15 минут.", "danger")
            return render_template("auth/login.html"), 429
        username = request.form.get("username", "").strip()[:255]
        user = User.query.filter_by(email=username).first()
        password = request.form.get("password", "")
        password_ok = False
        # bcrypt accepts at most 72 UTF-8 bytes; oversized input is a normal failed login.
        if user and len(password.encode("utf-8", errors="ignore")) <= 72:
            try:
                password_ok = verify_password(password, user.password_hash)
            except (ValueError, TypeError):
                password_ok = False
        if password_ok and user.is_active and user.role in {UserRole.SUPER_ADMIN.value, UserRole.STAFF.value, UserRole.OBSERVER.value, UserRole.LEADER.value}:
            # Telegram linking is optional for every supported panel role.
            # Accounts without a usable numeric link (or while the bot is not
            # configured) authenticate with their issued login and password.
            # Existing linked accounts retain the additional Telegram OTP.
            if not user.tg_id or int(user.tg_id) <= 0 or not settings.BOT_TOKEN:
                _login_failures.pop(client, None)
                session.clear()
                session['user_id'] = user.id
                session['user_role'] = user.role
                session['user_login'] = user.email
                session['auth_version'] = user.auth_version or 0
                session.permanent = True
                g.audit_actor_user_id = user.id
                g.audit_actor_login = user.email
                g.audit_actor_role = user.role
                if user.must_change_password:
                    return redirect(url_for('auth.change_password'))
                return redirect(url_for('admin.dashboard'))
            requests_recent = [t for t in _otp_issued.get(user.id, []) if now - t < 900]
            if requests_recent and (now - requests_recent[-1] < 15 or len(requests_recent) >= 5):
                flash('Повторная отправка кода временно ограничена. Попробуйте позднее.', 'warning')
                return render_template('auth/login.html'), 429
            otp = f'{secrets.randbelow(1000000):06d}'
            # Retry once for transient Telegram/network errors. The same code is
            # used for both attempts, so duplicate delivery does not invalidate it.
            delivery = _telegram_api('sendMessage', {
                'chat_id': int(user.tg_id),
                'text': f'🔐 Код входа: {otp}\nДействует 30 секунд. Никому не сообщайте его. '
                        'Если вы не входите в панель, проигнорируйте сообщение.',
            }, attempts=2, timeout=5)
            if not delivery:
                # Failed delivery must not consume the resend cooldown. Otherwise
                # a transient Telegram failure locks the user out for 15 seconds.
                logger.warning('admin_otp_delivery_failed user_id=%s', user.id)
                flash('Telegram временно не доставил код. Проверьте, что личный чат с ботом открыт, и повторите вход.', 'danger')
                return render_template('auth/login.html'), 503
            _otp_issued[user.id] = requests_recent + [time.time()]
            session.clear()
            session['pending_user_id'] = user.id
            session['pending_otp_hash'] = hmac.new(settings.SECRET_KEY.encode(),
                f'{user.id}:{otp}'.encode(), hashlib.sha256).hexdigest()
            session['pending_otp_expires'] = time.time() + 30
            session['pending_otp_attempts'] = 0
            session['pending_auth_version'] = user.auth_version or 0
            session.permanent = False
            return redirect(url_for('auth.verify_otp'), code=303)
        attempts.append(now)
        _login_failures[client] = attempts
        flash("Неверный логин или пароль.", "danger")
    return render_template("auth/login.html")

@auth_bp.route('/verify', methods=['GET', 'POST'])
def verify_otp():
    pending = session.get('pending_user_id')
    expires = session.get('pending_otp_expires', 0)
    if not pending or not session.get('pending_otp_hash'):
        return redirect(url_for('auth.login'))
    remaining = max(0, int(expires - time.time() + 0.999))
    if remaining == 0 or session.get('pending_otp_attempts', 0) >= 3:
        session.clear()
        flash('Срок кода истёк. Введите логин и пароль заново.', 'warning')
        return redirect(url_for('auth.login'))
    # An attacker who knows a password still cannot request unlimited OTP guesses.
    attempts = [t for t in _otp_failures.get(pending, []) if time.time() - t < 900]
    if len(attempts) >= 8:
        session.clear()
        flash('Слишком много попыток подтверждения. Повторите позже.', 'danger')
        return redirect(url_for('auth.login'))
    if request.method == 'POST':
        code = (request.form.get('code') or '').strip()
        user = User.query.get(pending)
        expected = hmac.new(settings.SECRET_KEY.encode(), f'{pending}:{code}'.encode(), hashlib.sha256).hexdigest()
        if (user and user.is_active and user.role in {UserRole.SUPER_ADMIN.value, UserRole.STAFF.value, UserRole.OBSERVER.value, UserRole.LEADER.value} and user.tg_id and
            (user.auth_version or 0) == session.get('pending_auth_version') and
            time.time() < expires and re.fullmatch(r'\d{6}', code) and
            hmac.compare_digest(expected, session.get('pending_otp_hash',''))):
            _otp_failures.pop(pending, None)
            _login_failures.pop(request.remote_addr or 'unknown', None)
            session.clear()
            session['user_id'] = user.id
            session['user_role'] = user.role
            session['user_login'] = user.email
            session['auth_version'] = user.auth_version or 0
            session.permanent = True
            g.audit_actor_user_id = user.id
            g.audit_actor_login = user.email
            g.audit_actor_role = user.role
            if user.must_change_password:
                return redirect(url_for('auth.change_password'))
            return redirect(url_for('admin.dashboard'))
        attempts.append(time.time())
        _otp_failures[pending] = attempts
        session['pending_otp_attempts'] = session.get('pending_otp_attempts', 0) + 1
        flash('Неверный или просроченный код.', 'danger')
    return render_template('auth/verify.html', remaining=remaining)

@auth_bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password(current_user):
    """Change a password and establish a fresh session using the new auth version."""
    user = current_user
    error = None
    logger.info("password_change_request user_id=%s method=%s forced=%s",
                user.id, request.method, bool(user.must_change_password))
    if request.method == "POST":
        password = request.form.get("new_password", "")
        confirmation = request.form.get("confirm_password", "")
        from services.password_policy import validate_new_password
        error = validate_new_password(password, user.email, user.password_hash, verify_password)
        if not error and password != confirmation:
            error = "Пароли не совпадают. Проверьте подтверждение."
        if not error:
            try:
                # Prepare and verify the replacement hash before touching the row.
                # This also prevents an unexpected hash backend error from partially
                # changing the user's account state.
                replacement_hash = hash_password(password)
                if not verify_password(password, replacement_hash):
                    raise RuntimeError("Password hash self-check failed")
                next_auth_version = int(user.auth_version or 0) + 1
                user_id, user_role, user_login = user.id, user.role, user.email
                user.password_hash = replacement_hash
                user.must_change_password = False
                user.auth_version = next_auth_version
                db.session.commit()

                # Rebuild the browser session only after the DB commit succeeds.
                # Clearing the old session avoids stale OTP/login metadata and
                # stale CSRF tokens surviving the password rotation.
                session.clear()
                session["user_id"] = user_id
                session["user_role"] = user_role
                session["user_login"] = user_login
                session["auth_version"] = next_auth_version
                session["_csrf_token"] = secrets.token_urlsafe(32)
                session.permanent = True
                session.modified = True
                g.audit_actor_user_id = user_id
                g.audit_actor_login = user_login
                g.audit_actor_role = user_role
                logger.info("mandatory_password_change_succeeded user_id=%s", user_id)
                flash("Пароль обновлён. Теперь можно продолжить работу.", "success")
                return redirect(url_for("admin.dashboard"), code=303)
            except Exception:
                db.session.rollback()
                logger.exception("Mandatory password change failed for user id=%s", user.id)
                error = "Не удалось сохранить пароль. Обновите страницу и повторите попытку."
    return render_template("auth/change_password.html", current_user=user,
                           forced=bool(user.must_change_password), error=error)


@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))

@admin_bp.route("/notifications", methods=["GET"])
@login_required
def notifications(current_user):
    from services.site_notifications import CATEGORIES, visible_notifications
    category = request.args.get("category", "").strip()[:25]
    if category not in CATEGORIES:
        category = ""
    state = request.args.get("state", "all")
    if state not in {"all", "unread", "read"}:
        state = "all"
    direction_id = request.args.get("direction", type=int)
    if direction_id and not Direction.query.get(direction_id):
        direction_id = None
    alerts, unread_count = visible_notifications(current_user, category, state, direction_id)
    from services.broadcast_policy import broadcast_direction_ids
    from services.staff_access import allowed as staff_allowed
    scope = broadcast_direction_ids(current_user)
    all_directions = Direction.query.order_by(Direction.name).all()
    scoped_directions = all_directions if scope is None else [d for d in all_directions if d.id in scope]
    broadcast_directions = (all_directions if scope is None else
                            [d for d in scoped_directions if staff_allowed(current_user, d.id, 'notifications', 'manage')])
    return render_template("system/notifications.html", notification_ttl=timedelta(minutes=90), alerts=alerts, unread_count=unread_count,
                           categories=CATEGORIES, category=category, state=state,
                           direction_id=direction_id,
                           directions=scoped_directions,
                           broadcast_directions=broadcast_directions,
                           can_broadcast=scope is None or bool(broadcast_directions),
                           is_superadmin=scope is None,
                           current_user=current_user)


@admin_bp.route("/notifications/api/unread", methods=["GET"])
@login_required
def notifications_unread(current_user):
    from services.site_notifications import visible_notifications
    _, unread_count = visible_notifications(current_user, limit=1)
    return jsonify({"ok": True, "unread": unread_count})


@admin_bp.route("/notifications/<int:notification_id>/read", methods=["POST"])
@login_required
def notification_read(notification_id, current_user):
    from services.site_notifications import mark_read, can_view, visible_notifications
    notification = SiteNotification.query.get_or_404(notification_id)
    if not can_view(current_user, notification):
        abort(403)
    marked = mark_read(current_user, [notification])
    # A read receipt is personal to the signed-in account. JSON allows the
    # notification center to update immediately; a regular form still works.
    if "application/json" in request.headers.get("Accept", ""):
        _, unread_count = visible_notifications(current_user, limit=1)
        return jsonify({"ok": True, "marked": marked, "unread": unread_count})
    return redirect(url_for("admin.notifications"))


@admin_bp.route("/notifications/read-all", methods=["POST"])
@login_required
def notifications_read_all(current_user):
    from services.site_notifications import CATEGORIES, visible_notifications, mark_read
    category = request.form.get("category", "")
    if category not in CATEGORIES:
        category = ""
    state = request.form.get("state", "all")
    if state not in {"all", "unread", "read"}:
        state = "all"
    direction_id = request.form.get("direction", type=int)
    alerts, _ = visible_notifications(current_user, category, state, direction_id)
    count = mark_read(current_user, [alert for alert, _ in alerts])
    if "application/json" in request.headers.get("Accept", ""):
        _, unread_count = visible_notifications(current_user, limit=1)
        return jsonify({"ok": True, "marked": count, "unread": unread_count})
    flash(f"Отмечено прочитанными: {count}.", "success")
    return redirect(url_for("admin.notifications", category=category, state=state, direction=direction_id or ""))


@admin_bp.route("/notifications/publish", methods=["POST"])
@login_required
def notifications_publish(current_user):
    """One audited, durable delivery path for superadmin and scoped employees."""
    from services.site_notifications import CATEGORIES, AUDIENCES, SEVERITIES
    from services.direction_publishing import publish_direction_announcement, ALL_CHANNELS
    from services.broadcast_policy import authorize_broadcast
    from services.system_broadcasts import EDUCATION_TYPES

    title = ' '.join(request.form.get('title', '').split())
    body = (request.form.get('body') or '').strip()
    category = request.form.get('category', 'system')
    audience = request.form.get('audience', 'all')
    severity = request.form.get('severity', 'info')
    education = request.form.get('education_type', '')
    selected_channels = request.form.getlist('channels')
    channels = set(selected_channels)
    global_broadcast = request.form.get('scope') == 'all'
    raw_ids = request.form.getlist('direction_ids')
    # Compatibility with previous single-direction form.
    legacy_id = request.form.get('direction_id')
    if legacy_id:
        raw_ids.append(legacy_id)
    try:
        if (not title or len(title) > 180 or not body or len(body) > 2000 or
                category not in CATEGORIES or audience not in AUDIENCES or
                severity not in SEVERITIES or education not in EDUCATION_TYPES or
                not channels or channels - ALL_CHANNELS or
                len(selected_channels) != len(channels)):
            raise ValueError('Проверьте текст, аудиторию и способы доставки.')
        try:
            selected_ids = [int(raw) for raw in raw_ids]
        except (TypeError, ValueError):
            raise ValueError('Некорректное направление.')
        if any(did <= 0 for did in selected_ids):
            raise ValueError('Некорректное направление.')
        selection = authorize_broadcast(current_user, selected_ids,
                                        global_broadcast=global_broadcast)
        if current_user.role != UserRole.SUPER_ADMIN.value:
            # Employees may use this composer only as a bot relay. They cannot
            # create/publish an on-site notification or target staff inboxes.
            # Chat binding/discovery remains exclusively in the superadmin panel.
            if 'site' in channels or 'staff_dm' in channels:
                raise PermissionError('Сотрудникам доступны только рассылки через Telegram, VK и MAX.')
            audience = 'all'
            category = 'system'
        if selection is not None:
            directions = Direction.query.filter(Direction.id.in_(selection)).all()
            if len(directions) != len(set(selection)):
                raise ValueError('Некоторые направления не найдены.')
            if education and any(not direction.available_for(education) for direction in directions):
                raise ValueError('Направление не относится к выбранному учебному контуру.')
        result = publish_direction_announcement(
            selection or [], title, body, category=category,
            creator_user_id=current_user.id, channels=channels,
            education=education, audience=audience, severity=severity,
            global_broadcast=global_broadcast,
            link_path='/notifications',
        )
    except PermissionError:
        abort(403)
    except ValueError as exc:
        flash(str(exc), 'danger')
        return redirect(url_for('admin.notifications'))
    except Exception:
        db.session.rollback()
        logger.exception('Could not persist system announcement')
        flash('Рассылка не сохранена. Проверьте журнал сервера.', 'danger')
        return redirect(url_for('admin.notifications'))
    flash(f"Уведомление сохранено. Получателей: {result['targets']}; "
          f"в очереди: {result['queued']}; ожидание токена: {result['blocked']}. "
          'Это не подтверждение доставки: статусы обновляются обработчиком очереди.',
          'success' if result['queued'] or result['site'] else 'warning')
    return redirect(url_for('admin.notifications'))


@admin_bp.route("/notifications/messenger-chats/add", methods=["POST"])
@super_admin_required
def messenger_chat_create(current_user):
    platform = request.form.get('platform', '').strip()
    direction_id = request.form.get('direction_id', type=int)
    education = request.form.get('education_type', 'all')
    candidate = MessengerChatCandidate.query.get(request.form.get('candidate_id', type=int))
    if not candidate or candidate.platform != platform:
        flash('Сначала добавьте бота в чат и выполните /chatid. Произвольный ID не подключается.', 'danger')
        return redirect(url_for('admin.notifications'))
    chat_id = candidate.chat_id
    title = ' '.join(request.form.get('title', '').split())[:255] or candidate.title
    direction = Direction.query.get(direction_id) if direction_id else None
    if (platform not in {'vk', 'max'} or not direction or education not in {'all','college','institute'}
            or not chat_id.lstrip('-').isdigit() or len(chat_id) > 100 or not title
            or (education != 'all' and not direction.available_for(education))):
        flash('Проверьте платформу, ID чата, название и аудиторию.', 'danger')
        return redirect(url_for('admin.notifications'))
    chat = MessengerChat.query.filter_by(platform=platform, direction_id=direction_id, chat_id=chat_id).first()
    if not chat:
        chat = MessengerChat(platform=platform, direction_id=direction_id, chat_id=chat_id, title=title,
                             education_type=education)
        db.session.add(chat)
    else:
        chat.title = title
        chat.education_type = education
        chat.is_active = True
    db.session.commit()
    flash('Чат подключён главным администратором. Без разрешения чаты не подключаются автоматически.', 'success')
    return redirect(url_for('admin.notifications'))


@admin_bp.route("/notifications/messenger-chats/<int:chat_id>/remove", methods=["POST"])
@super_admin_required
def messenger_chat_remove(chat_id, current_user):
    chat = MessengerChat.query.get_or_404(chat_id)
    chat.is_active = False
    db.session.commit()
    flash('Чат отключён от рассылок.', 'success')
    return redirect(url_for('admin.notifications'))


# Every UserRole is a registered web account; retain the old constant name
# for the separate staff-journal routes and older integrations.
REGISTERED_WEB_ACCOUNT_ROLES = tuple(role.value for role in UserRole)
STAFF_AUDIT_ROLES = REGISTERED_WEB_ACCOUNT_ROLES


def _staff_audit_base_query():
    """Return actions by staff accounts plus failed logins targeting known accounts.

    Authenticated actions are attributed by the live User ID and role. A failed
    login has no authenticated actor yet, so it is included only when its
    attempted login matches the email of a real staff account. Unknown visitors
    and bot identities remain outside this employee investigation view.
    """
    known_logins = [str(row[0]).strip().lower() for row in User.query.with_entities(User.email)
                    .filter(User.role.in_(STAFF_AUDIT_ROLES)).all() if row[0]]
    authenticated_actor = and_(
        HttpAuditLog.actor_user_id.isnot(None),
        HttpAuditLog.actor_role.in_(STAFF_AUDIT_ROLES),
    )
    known_account_login_attempt = and_(
        HttpAuditLog.actor_user_id.is_(None),
        func.lower(HttpAuditLog.actor_login).in_(known_logins) if known_logins else false(),
        HttpAuditLog.action.in_(('auth.login.failed', 'auth.login.rate_limited')),
    )
    return HttpAuditLog.query.filter(or_(authenticated_actor, known_account_login_attempt))


def _filtered_audit_queries(args):
    """Build bounded, parameterized filters for staff actions and their CSV export."""
    search = (args.get('q') or '').strip()[:100]
    level = (args.get('level') or 'all').strip()
    if level not in ('all', 'errors', 'success', 'slow'):
        level = 'all'
    scope = (args.get('scope') or 'review').strip()
    if scope not in ('review', 'all', 'writes', 'errors', 'slow'):
        scope = 'review'
    method = (args.get('method') or '').upper().strip()[:10]
    if method not in ('', 'POST', 'PUT', 'PATCH', 'DELETE', 'GET'):
        method = ''
    actor = (args.get('actor') or '').strip()[:80]
    role = (args.get('role') or '').strip()
    if role not in STAFF_AUDIT_ROLES:
        role = ''
    start = (args.get('start') or '').strip()[:10]
    end = (args.get('end') or '').strip()[:10]

    query = _staff_audit_base_query()
    # Default investigation view suppresses successful page-open noise while
    # retaining every write, failure and unusually slow request. `all` remains
    # available for a complete forensic timeline.
    if scope == 'review':
        query = query.filter(or_(
            HttpAuditLog.method != 'GET',
            HttpAuditLog.status_code >= 400,
            HttpAuditLog.duration_ms >= 1500,
        ))
    elif scope == 'writes':
        query = query.filter(HttpAuditLog.method.in_(('POST', 'PUT', 'PATCH', 'DELETE')))
    elif scope == 'errors':
        query = query.filter(HttpAuditLog.status_code >= 400)
    elif scope == 'slow':
        query = query.filter(HttpAuditLog.duration_ms >= 1500)
    if search:
        # S-, STAFF-, legacy HTTP- and A- IDs resolve to the same staff event ID.
        direct_id = re.fullmatch(r'(?:S|STAFF|HTTP|A)-(\d{1,12})', search, flags=re.I)
        if direct_id:
            query = query.filter(HttpAuditLog.id == int(direct_id.group(1)))
        else:
            pattern = '%' + search.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
            search_fields = [
                HttpAuditLog.actor_login.ilike(pattern, escape='\\'),
                HttpAuditLog.actor_role.ilike(pattern, escape='\\'),
                HttpAuditLog.action.ilike(pattern, escape='\\'),
                HttpAuditLog.path.ilike(pattern, escape='\\'),
                HttpAuditLog.ip_address.ilike(pattern, escape='\\'),
                HttpAuditLog.request_id.ilike(pattern, escape='\\'),
            ]
            if search.isdecimal():
                numeric_value = int(search)
                search_fields.append(HttpAuditLog.id == numeric_value)
                if 100 <= numeric_value <= 599:
                    search_fields.append(HttpAuditLog.status_code == numeric_value)
            query = query.filter(or_(*search_fields))

    if actor:
        actor_pattern = '%' + actor.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        query = query.filter(or_(
            HttpAuditLog.actor_login.ilike(actor_pattern, escape='\\'),
            HttpAuditLog.actor_role.ilike(actor_pattern, escape='\\'),
        ))
    if role:
        query = query.filter(HttpAuditLog.actor_role == role)
    if method:
        query = query.filter(HttpAuditLog.method == method)
    if level == 'slow':
        query = query.filter(HttpAuditLog.duration_ms >= 1500)
    elif level == 'errors':
        query = query.filter(HttpAuditLog.status_code >= 400)
    elif level == 'success':
        query = query.filter(HttpAuditLog.status_code < 400)

    for name, value in (('start', start), ('end', end)):
        try:
            parsed_date = datetime.strptime(value, '%Y-%m-%d') if value else None
        except ValueError:
            parsed_date = None
            if name == 'start':
                start = ''
            else:
                end = ''
        if parsed_date:
            if name == 'end':
                parsed_date += timedelta(days=1)
                query = query.filter(HttpAuditLog.created_at < parsed_date)
            else:
                query = query.filter(HttpAuditLog.created_at >= parsed_date)

    return query, dict(q=search, level=level, scope=scope, method=method, actor=actor,
                       role=role, start=start, end=end)


def _staff_audit_assessment(row):
    """Explain the review priority from persisted request evidence, not assumptions."""
    method = (row.method or 'GET').upper()
    path = (row.path or '').lower()
    action = (row.action or '').lower()
    if row.status_code >= 500:
        return {'level': 'high', 'label': 'Высокий', 'reason': 'Серверная ошибка 5xx'}
    if any(token in action for token in ('rate_limited', '.failed', '.denied', '.rejected')):
        return {'level': 'medium', 'label': 'Средний', 'reason': 'Действие завершилось отказом или ограничением'}
    sensitive_path = any(token in path or token in action for token in (
        'delete', 'remove', 'clear', 'maintenance', 'restore', 'permission',
        'accounts', 'roles', 'password', 'export', 'backup', 'token',
    ))
    if method == 'DELETE' or sensitive_path:
        return {'level': 'high', 'label': 'Высокий', 'reason': 'Изменение или доступ к чувствительной функции'}
    if row.status_code >= 400:
        return {'level': 'medium', 'label': 'Средний', 'reason': f'Запрос завершился статусом {row.status_code}'}
    if method in {'POST', 'PUT', 'PATCH'}:
        return {'level': 'medium', 'label': 'Средний', 'reason': 'Запрос изменяющего типа'}
    if (row.duration_ms or 0) >= 1500:
        return {'level': 'medium', 'label': 'Средний', 'reason': 'Необычно длительный запрос'}
    return {'level': 'info', 'label': 'Инфо', 'reason': 'Успешный запрос без признаков повышенного риска'}


def _staff_audit_action_label(row):
    action = (row.action or '').strip()
    known = {
        'auth.login.succeeded': 'Успешный вход в систему',
        'auth.login.failed': 'Неудачная попытка входа',
        'auth.login.rate_limited': 'Ограничение частоты входа',
        'auth.logout': 'Выход из системы',
        'auth.verify_otp.succeeded': 'Подтверждение входа кодом',
        'auth.change_password': 'Изменение пароля',
    }
    if action in known:
        return known[action]
    label = action.replace('.failed', ' · ошибка').replace('.view', ' · просмотр')
    label = label.replace('.', ' · ').replace('_', ' ').strip(' ·')
    return label[:180].capitalize() if label else 'Запрос к системе'


def _staff_audit_area(path):
    value = (path or '').lower()
    if value.startswith('/auth'):
        return 'Авторизация и доступ'
    if 'student' in value or 'application' in value or 'direction' in value:
        return 'Студенты и заявления'
    if 'event' in value or 'quota' in value or 'calendar' in value:
        return 'Мероприятия и календарь'
    if 'staff' in value or 'user' in value or 'permission' in value:
        return 'Учётные записи и права'
    if 'system' in value or 'database' in value or 'maintenance' in value:
        return 'Система и инфраструктура'
    if 'export' in value or 'report' in value or 'stat' in value:
        return 'Отчёты и экспорт'
    return 'Рабочие разделы'


STAFF_INCIDENT_STATUS_LABELS = {
    "open": "Новый", "investigating": "Расследуется",
    "resolved": "Решён", "false_positive": "Ложное срабатывание",
}
STAFF_INCIDENT_SEVERITY_LABELS = {"high": "Высокий", "medium": "Средний", "low": "Низкий"}


def _staff_incident_bucket(value, minutes):
    value = value.replace(second=0, microsecond=0)
    return value.replace(minute=(value.minute // minutes) * minutes)


def _staff_incident_fingerprint(rule_key, identity, bucket):
    raw = "|".join((rule_key, str(identity), bucket.isoformat(timespec="minutes")))
    return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()


def _staff_incident_evidence_digest(rows):
    """Return a stable SHA-256 over persisted evidence fields, excluding secrets/payloads."""
    fields = ("id", "request_id", "actor_user_id", "actor_login", "actor_role", "action",
              "method", "path", "status_code", "duration_ms", "ip_address", "created_at")
    snapshot = []
    for row in sorted(rows, key=lambda item: (item.id or 0)):
        item = {}
        for name in fields:
            value = getattr(row, name, None)
            if isinstance(value, datetime):
                value = value.isoformat(timespec="microseconds")
            item[name] = value
        snapshot.append(item)
    canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8", "replace")).hexdigest()


def _staff_incident_candidates(now=None):
    """Create explainable detections from fields actually persisted in HttpAuditLog."""
    now = now or datetime.utcnow()
    rows = (_staff_audit_base_query()
            .filter(HttpAuditLog.created_at >= now - timedelta(days=14))
            .order_by(HttpAuditLog.created_at.asc()).limit(5000).all())
    candidates = []

    def add(rule, title, severity, confidence, basis, grouped, identity, bucket):
        grouped = sorted({row.id: row for row in grouped}.values(), key=lambda row: (row.created_at or now, row.id or 0))
        if not grouped:
            return
        latest, first = grouped[-1], grouped[0]
        candidates.append({
            "fingerprint": _staff_incident_fingerprint(rule, identity, bucket),
            "rule_key": rule, "title": title, "severity": severity, "confidence": confidence,
            "basis": basis,
            "summary": f"Сигнал сформирован по {len(grouped)} сохранённым HTTP-событиям. Период: {first.created_at:%Y-%m-%d %H:%M:%S} — {latest.created_at:%Y-%m-%d %H:%M:%S} UTC.",
            "actor_user_id": latest.actor_user_id, "actor_login": latest.actor_login,
            "actor_role": latest.actor_role, "ip_address": latest.ip_address,
            "source_ips": sorted({row.ip_address for row in grouped if row.ip_address}),
            "evidence_ids": [row.id for row in grouped],
            "first_seen_at": first.created_at or now, "last_seen_at": latest.created_at or now,
        })

    failed = [row for row in rows if row.action in {"auth.login.failed", "auth.login.rate_limited"}
              and (row.actor_login or "").strip() and (row.ip_address or "").strip()]
    groups = {}
    for row in failed:
        bucket = _staff_incident_bucket(row.created_at or now, 15)
        identity = ((row.actor_login or "").strip().lower(), row.ip_address or "unknown")
        groups.setdefault((identity, bucket), []).append(row)
    for (identity, bucket), grouped in groups.items():
        if len(grouped) >= 4:
            add("repeated_auth_failures", "Повторные неудачные попытки входа", "high", "high",
                f"Не менее 4 неудачных/ограниченных попыток входа к известной учётной записи за один 15-минутный интервал с одного IP. Фактическое число: {len(grouped)}.", grouped, identity, bucket)

    account_groups = {}
    for row in failed:
        bucket = _staff_incident_bucket(row.created_at or now, 15)
        account_key = ((row.actor_login or "").strip().lower(), bucket)
        account_groups.setdefault(account_key, []).append(row)
    for (account, bucket), grouped in account_groups.items():
        source_ips = {row.ip_address for row in grouped if row.ip_address}
        if len(grouped) >= 8 and len(source_ips) >= 3:
            add("distributed_auth_failures", "Распределённые попытки входа к одной учётной записи", "high", "high",
                f"Не менее 8 неудачных/ограниченных попыток за 15 минут с не менее чем 3 разных сохранённых IP-адресов. Фактическое число: {len(grouped)}; источников: {len(source_ips)}. Геолокация и принадлежность IP не определяются.",
                grouped, account, bucket)

    denied = [row for row in rows if row.status_code in (401, 403) and row.actor_user_id is not None
              and (row.ip_address or "").strip()]
    groups = {}
    for row in denied:
        bucket = _staff_incident_bucket(row.created_at or now, 10)
        identity = (row.actor_user_id, row.ip_address or "unknown")
        groups.setdefault((identity, bucket), []).append(row)
    for (identity, bucket), grouped in groups.items():
        if len(grouped) >= 5:
            add("repeated_access_denials", "Серия отказов в доступе", "medium", "medium",
                f"Не менее 5 ответов 401/403 для одной учётной записи за 10 минут с одного IP. Фактическое число: {len(grouped)}. Проверьте, соответствуют ли обращения назначенным правам.", grouped, identity, bucket)

    writes = [row for row in rows if row.actor_user_id is not None and row.method in {"POST", "PUT", "PATCH", "DELETE"}
              and (row.ip_address or "").strip()]
    groups = {}
    for row in writes:
        bucket = _staff_incident_bucket(row.created_at or now, 5)
        identity = (row.actor_user_id, row.ip_address or "unknown")
        groups.setdefault((identity, bucket), []).append(row)
    for (identity, bucket), grouped in groups.items():
        if len(grouped) >= 20:
            add("write_request_burst", "Высокая частота изменяющих операций", "low", "medium",
                f"Не менее 20 POST/PUT/PATCH/DELETE-запросов одной учётной записи за 5 минут. Фактическое число: {len(grouped)}. Это может быть массовая штатная операция; требуется контекстная проверка.", grouped, identity, bucket)

    server_errors = [row for row in rows if row.actor_user_id is not None and row.status_code >= 500]
    groups = {}
    for row in server_errors:
        bucket = _staff_incident_bucket(row.created_at or now, 5)
        endpoint = (row.action or row.path or "unknown")[:80]
        identity = (row.actor_user_id, endpoint)
        groups.setdefault((identity, bucket), []).append(row)
    for (identity, bucket), grouped in groups.items():
        if len(grouped) >= 3:
            add("repeated_server_errors", "Повторяющиеся серверные ошибки", "medium", "high",
                f"Не менее 3 ответов 5xx на одном endpoint для одной учётной записи за 5 минут. Это операционный сигнал доступности, а не доказательство атаки. Фактическое число: {len(grouped)}.", grouped, identity, bucket)

    sensitive_tokens = ("export", "backup", "restore", "permission", "accounts", "roles", "delete", "remove", "maintenance")
    sensitive = [row for row in rows if row.actor_user_id is not None and (
        row.method == "DELETE"
        or (row.method in {"POST", "PUT", "PATCH"} and any(
            token in (row.path or "").lower() or token in (row.action or "").lower()
            for token in sensitive_tokens if token != "export"
        ))
        or ("export" in (row.path or "").lower() or "export" in (row.action or "").lower())
    )]
    groups = {}
    for row in sensitive:
        bucket = _staff_incident_bucket(row.created_at or now, 15)
        identity = (row.actor_user_id, row.ip_address or "unknown")
        groups.setdefault((identity, bucket), []).append(row)
    for (identity, bucket), grouped in groups.items():
        add("sensitive_operation_review", "Проверка чувствительной операции", "low", "high",
            f"Обнаружены изменяющие/экспортирующие операции в чувствительном разделе ({len(grouped)} событий). Такие операции могут быть штатными; проверьте основание и полномочия.", grouped, identity, bucket)
    return candidates


def _refresh_staff_incident_cases(now=None, force=False):
    """Idempotently update derived cases; source HttpAuditLog rows remain untouched.

    The web request path is throttled per worker to avoid rescanning 5,000 audit
    rows on every dashboard refresh. An explicit refresh button can bypass it.
    """
    global _staff_incident_refresh_last_monotonic
    supplied_time = now is not None
    now = now or datetime.utcnow()
    if not supplied_time:
        with _staff_incident_refresh_lock:
            monotonic_now = time.monotonic()
            if not force and monotonic_now - _staff_incident_refresh_last_monotonic < 10:
                return []
            _staff_incident_refresh_last_monotonic = monotonic_now
    try:
        candidates = _staff_incident_candidates(now)
        for item in candidates:
            case = StaffIncidentCase.query.filter_by(fingerprint=item["fingerprint"]).first()
            if case is None:
                evidence_rows = HttpAuditLog.query.filter(HttpAuditLog.id.in_(item["evidence_ids"])).all()
                db.session.add(StaffIncidentCase(
                    fingerprint=item["fingerprint"], rule_key=item["rule_key"], title=item["title"],
                    summary=item["summary"], severity=item["severity"], confidence=item["confidence"],
                    status="open", basis=item["basis"], actor_user_id=item["actor_user_id"],
                    actor_login=item["actor_login"], actor_role=item["actor_role"], ip_address=item["ip_address"],
                    source_ips_json=json.dumps(item.get("source_ips", [])),
                    evidence_ids_json=json.dumps(item["evidence_ids"]), evidence_count=len(item["evidence_ids"]),
                    evidence_sha256=_staff_incident_evidence_digest(evidence_rows),
                    first_seen_at=item["first_seen_at"], last_seen_at=item["last_seen_at"],
                ))
                continue
            try:
                known_ids = {int(value) for value in json.loads(case.evidence_ids_json or "[]")}
            except (TypeError, ValueError, json.JSONDecodeError):
                known_ids = set()
            combined = sorted(known_ids.union(item["evidence_ids"]))
            try:
                known_ips = set(json.loads(case.source_ips_json or "[]"))
            except (TypeError, ValueError, json.JSONDecodeError):
                known_ips = set()
            merged_ips = sorted(known_ips.union(item.get("source_ips", [])))
            evidence_changed = len(combined) != len(known_ids)
            identity_changed = merged_ips != sorted(known_ips)
            if evidence_changed:
                case.evidence_ids_json = json.dumps(combined)
                case.evidence_count = len(combined)
                case.last_seen_at = max(case.last_seen_at or item["last_seen_at"], item["last_seen_at"])
                case.summary = item["summary"]
                case.basis = item["basis"]
                case.severity = item["severity"]
                case.confidence = item["confidence"]
                case.actor_user_id = item["actor_user_id"]
                case.actor_login = item["actor_login"]
                case.actor_role = item["actor_role"]
                case.ip_address = item["ip_address"]
                evidence_rows = HttpAuditLog.query.filter(HttpAuditLog.id.in_(combined)).all()
                case.evidence_sha256 = _staff_incident_evidence_digest(evidence_rows)
                if case.status in {"resolved", "false_positive"}:
                    case.status, case.closed_at, case.resolution_summary = "open", None, None
            if identity_changed or evidence_changed:
                case.source_ips_json = json.dumps(merged_ips)
                case.updated_at = now
        if candidates:
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
        return candidates
    except Exception:
        db.session.rollback()
        if not supplied_time:
            with _staff_incident_refresh_lock:
                _staff_incident_refresh_last_monotonic = 0.0
        raise


def _staff_incident_filtered_query(args):
    status = (args.get("case_status") or "active").strip()
    if status not in {"active", "all", "open", "investigating", "resolved", "false_positive"}:
        status = "active"
    severity = (args.get("severity") or "all").strip()
    if severity not in {"all", "high", "medium", "low"}:
        severity = "all"
    rule = (args.get("rule") or "all").strip()
    allowed_rules = {"repeated_auth_failures", "distributed_auth_failures", "repeated_access_denials", "write_request_burst", "repeated_server_errors", "sensitive_operation_review"}
    if rule not in allowed_rules and rule != "all":
        rule = "all"
    actor_role = (args.get("actor_role") or "all").strip()
    if actor_role not in STAFF_AUDIT_ROLES and actor_role != "all":
        actor_role = "all"
    assigned = (args.get("assigned") or "all").strip()[:20]
    if assigned != "all" and assigned != "unassigned" and not assigned.isdecimal():
        assigned = "all"
    q = (args.get("case_q") or "").strip()[:100]
    start = (args.get("case_start") or "").strip()[:10]
    end = (args.get("case_end") or "").strip()[:10]
    parsed_start = parsed_end = None
    try:
        parsed_start = datetime.strptime(start, "%Y-%m-%d") if start else None
    except ValueError:
        start, parsed_start = "", None
    try:
        parsed_end = datetime.strptime(end, "%Y-%m-%d") if end else None
    except ValueError:
        end, parsed_end = "", None
    if parsed_start and parsed_end and parsed_start > parsed_end:
        parsed_start, parsed_end = parsed_end, parsed_start
        start, end = end, start

    query = StaffIncidentCase.query
    if status == "active":
        query = query.filter(StaffIncidentCase.status.in_(("open", "investigating")))
    elif status != "all":
        query = query.filter(StaffIncidentCase.status == status)
    if severity != "all":
        query = query.filter(StaffIncidentCase.severity == severity)
    if rule != "all":
        query = query.filter(StaffIncidentCase.rule_key == rule)
    if actor_role != "all":
        query = query.filter(StaffIncidentCase.actor_role == actor_role)
    if assigned == "unassigned":
        query = query.filter(StaffIncidentCase.assigned_to_user_id.is_(None))
    elif assigned.isdecimal():
        query = query.filter(StaffIncidentCase.assigned_to_user_id == int(assigned))
    if parsed_start:
        query = query.filter(StaffIncidentCase.last_seen_at >= parsed_start)
    if parsed_end:
        query = query.filter(StaffIncidentCase.first_seen_at < parsed_end + timedelta(days=1))
    if q:
        incident_match = re.fullmatch(r"INC[-#]?(\d{1,12})", q, flags=re.I)
        user_match = re.fullmatch(r"(?:USER|UID)[-#]?(\d{1,12})", q, flags=re.I)
        numeric_match = re.fullmatch(r"\d{1,12}", q)
        if incident_match:
            query = query.filter(StaffIncidentCase.id == int(incident_match.group(1)))
        elif user_match:
            query = query.filter(StaffIncidentCase.actor_user_id == int(user_match.group(1)))
        elif numeric_match:
            value = int(q)
            query = query.filter(or_(StaffIncidentCase.id == value, StaffIncidentCase.actor_user_id == value))
        else:
            pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            query = query.filter(or_(StaffIncidentCase.title.ilike(pattern, escape="\\"),
                                     StaffIncidentCase.actor_login.ilike(pattern, escape="\\"),
                                     StaffIncidentCase.ip_address.ilike(pattern, escape="\\"),
                                     StaffIncidentCase.basis.ilike(pattern, escape="\\")))
    return query, {"case_status": status, "severity": severity, "rule": rule, "actor_role": actor_role,
                   "case_q": q, "assigned": assigned, "case_start": start, "case_end": end}


def _staff_incident_case_evidence(case):
    try:
        ids = [int(value) for value in json.loads(case.evidence_ids_json or "[]") if str(value).isdigit()]
    except (TypeError, ValueError, json.JSONDecodeError):
        ids = []
    if not ids:
        return []
    return (HttpAuditLog.query.filter(HttpAuditLog.id.in_(ids))
            .order_by(HttpAuditLog.created_at.asc(), HttpAuditLog.id.asc()).all())


@admin_bp.get("/audit-log/incidents/export.csv")
@super_admin_required
def admin_audit_incident_export(current_user):
    """Deprecated case workflow export; use the employee action ledger."""
    return redirect(url_for('admin.user_activity_log'))

@admin_bp.get("/audit-log/incidents/<int:incident_id>/evidence.csv")
@super_admin_required
def admin_audit_incident_evidence_export(incident_id, current_user):
    """Deprecated case workflow evidence URL."""
    return redirect(url_for('admin.user_activity_log', q=f'S-{incident_id}'))

@admin_bp.get("/audit-log/incidents/<int:incident_id>")
@super_admin_required
def admin_audit_incident_detail(incident_id, current_user):
    """Deprecated incident-case page; the site now exposes an action ledger only."""
    return redirect(url_for('admin.user_activity_log'))

@admin_bp.post("/audit-log/incidents/<int:incident_id>/update")
@super_admin_required
def admin_audit_incident_update(incident_id, current_user):
    """Incident status workflow has been retired from the monitoring UI."""
    return redirect(url_for('admin.user_activity_log'))

@admin_bp.route('/audit-log')
@super_admin_required
def admin_audit_log(current_user):
    """Legacy URL: show the plain staff action ledger, not an incident workflow."""
    return redirect(url_for('admin.user_activity_log', **request.args))


@admin_bp.get('/audit-log/check')
@super_admin_required
def admin_audit_check(current_user):
    """Staff-only journal heartbeat; never transmits log contents."""
    latest_staff_id = _staff_audit_base_query().with_entities(func.max(HttpAuditLog.id)).scalar() or 0
    response = jsonify(ok=True, actions=latest_staff_id, http=latest_staff_id,
                       staff_actions=latest_staff_id)
    response.headers['Cache-Control'] = 'no-store'
    return response


@admin_bp.get('/audit-log/export.csv')
@super_admin_required
def admin_audit_export(current_user):
    """Legacy export URL; redirect to the plain employee action export."""
    allowed = {key: request.args.get(key) for key in ('q', 'actor', 'role', 'method', 'start', 'end') if request.args.get(key)}
    return redirect(url_for('admin.user_activity_export', **allowed))


def _registered_user_activity_section_predicates():
    """SQL predicates for the five business areas shown in the staff ledger."""
    student_membership = and_(
        HttpAuditLog.action.like('directions.%'),
        or_(HttpAuditLog.action.like('%approve_student%'),
            HttpAuditLog.action.like('%activate_student%'),
            HttpAuditLog.action.like('%reject_student%'),
            HttpAuditLog.action.like('%add_existing_student%'),
            HttpAuditLog.action.like('%remove_student%'),
            HttpAuditLog.action.like('%update_student_status%')),
    )
    dashboard = or_(HttpAuditLog.action.like('admin.dashboard%'),
                    HttpAuditLog.action.like('staff.workspace%'), HttpAuditLog.path.like('/dashboard%'))
    analytics = or_(HttpAuditLog.action.like('stats.%'), HttpAuditLog.path.like('/stats%'))
    students = or_(
        and_(HttpAuditLog.action.like('admin.student%'), ~HttpAuditLog.action.like('admin.student_app_design%')),
        HttpAuditLog.action.like('admin.students_%'), HttpAuditLog.action.like('student_app.%'),
        HttpAuditLog.path.like('/students%'), HttpAuditLog.path.like('/api/students%'),
        HttpAuditLog.path.like('/student-app%'), student_membership,
    )
    council = and_(
        or_(HttpAuditLog.action.like('directions.%'), HttpAuditLog.action.like('quotas.%'),
            HttpAuditLog.action.like('lessons.%'), HttpAuditLog.action.like('admin.calendar%'),
            HttpAuditLog.action.like('admin.notifications%'), HttpAuditLog.path.like('/directions%'),
            HttpAuditLog.path.like('/quotas%'), HttpAuditLog.path.like('/lessons%'),
            HttpAuditLog.path.like('/calendar%'), HttpAuditLog.path.like('/notifications%')),
        ~student_membership,
    )
    return {
        'dashboard': dashboard,
        'analytics': analytics,
        'students': students,
        'council': council,
        'administration': ~or_(dashboard, analytics, students, council),
    }


USER_ACTIVITY_SECTION_LABELS = {
    'administration': 'Администрирование',
    'analytics': 'Аналитика',
    'students': 'Студенты и участники',
    'council': 'Работа совета',
    'dashboard': 'Рабочий стол',
}


def _registered_user_activity_base_query():
    """Only requests made by an authenticated, registered web account (User)."""
    return HttpAuditLog.query.filter(
        HttpAuditLog.actor_user_id.isnot(None),
        HttpAuditLog.actor_role.in_(REGISTERED_WEB_ACCOUNT_ROLES),
        # Student App verifies its own student identity with the messenger SDK;
        # a browser may also carry an unrelated staff cookie. Never cross-attribute it.
        ~HttpAuditLog.path.like('/student-app%'),
        ~HttpAuditLog.action.like('student_app.%'),
    )


def _registered_user_activity_query(args):
    """Build the exact same safe filters for the activity table and CSV export."""
    values = {
        'q': (args.get('q') or '').strip()[:100],
        'actor': (args.get('actor') or '').strip()[:80],
        'role': (args.get('role') or '').strip(),
        'method': (args.get('method') or '').upper().strip(),
        'level': (args.get('level') or 'all').strip(),
        'section': (args.get('section') or 'all').strip(),
        'start': (args.get('start') or '').strip()[:10],
        'end': (args.get('end') or '').strip()[:10],
    }
    if values['role'] not in REGISTERED_WEB_ACCOUNT_ROLES:
        values['role'] = ''
    if values['method'] not in {'', 'GET', 'POST', 'PUT', 'PATCH', 'DELETE'}:
        values['method'] = ''
    if values['level'] not in {'all', 'success', 'errors', 'slow'}:
        values['level'] = 'all'
    section_predicates = _registered_user_activity_section_predicates()
    if values['section'] not in {'all', *section_predicates.keys()}:
        values['section'] = 'all'

    query = _registered_user_activity_base_query()
    if values['section'] in section_predicates:
        query = query.filter(section_predicates[values['section']])

    if values['role']:
        query = query.filter(HttpAuditLog.actor_role == values['role'])
    if values['method']:
        query = query.filter(HttpAuditLog.method == values['method'])
    else:
        # Main staff ledger is an action ledger, not a page-view counter.
        query = query.filter(HttpAuditLog.method.in_(('POST', 'PUT', 'PATCH', 'DELETE')))
    if values['level'] == 'errors':
        query = query.filter(HttpAuditLog.status_code >= 400)
    elif values['level'] == 'success':
        query = query.filter(HttpAuditLog.status_code < 400)
    elif values['level'] == 'slow':
        query = query.filter(HttpAuditLog.duration_ms >= 1500)

    def escaped_like(value):
        return '%' + value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'

    def matching_account_ids(value):
        if not value:
            return []
        pattern = escaped_like(value)
        try:
            return [row[0] for row in User.query.with_entities(User.id).filter(or_(
                User.email.ilike(pattern, escape='\\'),
                User.full_name.ilike(pattern, escape='\\'),
            )).limit(1000).all()]
        except Exception:
            logger.warning('Could not resolve account names for the admin activity filter', exc_info=True)
            return []

    if values['q']:
        query_text = values['q']
        record_match = re.fullmatch(r'(?:U|HTTP|A)-?(\d{1,12})', query_text, flags=re.I)
        if record_match:
            query = query.filter(HttpAuditLog.id == int(record_match.group(1)))
        else:
            pattern = escaped_like(query_text)
            search_terms = [
                HttpAuditLog.actor_login.ilike(pattern, escape='\\'),
                HttpAuditLog.actor_role.ilike(pattern, escape='\\'),
                HttpAuditLog.action.ilike(pattern, escape='\\'),
                HttpAuditLog.path.ilike(pattern, escape='\\'),
                HttpAuditLog.ip_address.ilike(pattern, escape='\\'),
                HttpAuditLog.request_id.ilike(pattern, escape='\\'),
            ]
            if query_text.isdecimal():
                numeric_value = int(query_text)
                search_terms.append(HttpAuditLog.id == numeric_value)
                search_terms.append(HttpAuditLog.actor_user_id == numeric_value)
                if 100 <= numeric_value <= 599:
                    search_terms.append(HttpAuditLog.status_code == numeric_value)
            q_account_ids = matching_account_ids(query_text)
            if q_account_ids:
                search_terms.append(HttpAuditLog.actor_user_id.in_(q_account_ids))
            query = query.filter(or_(*search_terms))

    if values['actor']:
        pattern = escaped_like(values['actor'])
        actor_terms = [
            HttpAuditLog.actor_login.ilike(pattern, escape='\\'),
            HttpAuditLog.actor_role.ilike(pattern, escape='\\'),
        ]
        if values['actor'].isdecimal():
            actor_terms.append(HttpAuditLog.actor_user_id == int(values['actor']))
        actor_account_ids = matching_account_ids(values['actor'])
        if actor_account_ids:
            actor_terms.append(HttpAuditLog.actor_user_id.in_(actor_account_ids))
        query = query.filter(or_(*actor_terms))

    for key in ('start', 'end'):
        value = values[key]
        try:
            parsed = datetime.strptime(value, '%Y-%m-%d') if value else None
        except ValueError:
            parsed = None
            values[key] = ''
        if parsed and key == 'start':
            query = query.filter(HttpAuditLog.created_at >= parsed)
        elif parsed and key == 'end':
            query = query.filter(HttpAuditLog.created_at < parsed + timedelta(days=1))
    return query, values


def _registered_user_activity_section(row):
    action = row.action or ''
    path = row.path or ''
    membership_action = action.startswith('directions.') and any(token in action for token in (
        'approve_student', 'activate_student', 'reject_student', 'add_existing_student',
        'remove_student', 'update_student_status'))
    if action.startswith(('admin.dashboard', 'staff.workspace')) or path.startswith('/dashboard'):
        return 'dashboard'
    if action.startswith('stats.') or path.startswith('/stats'):
        return 'analytics'
    if ((action.startswith(('admin.student', 'admin.students_', 'student_app.'))
         and not action.startswith('admin.student_app_design'))
            or path.startswith(('/students', '/api/students', '/student-app')) or membership_action):
        return 'students'
    if (action.startswith(('directions.', 'quotas.', 'lessons.', 'admin.calendar', 'admin.notifications'))
            or path.startswith(('/directions', '/quotas', '/lessons', '/calendar', '/notifications'))):
        return 'council'
    return 'administration'


USER_ACTIVITY_ROUTE_LABELS = {
    'admin.dashboard': 'Главная панель',
    'staff.workspace': 'Рабочий стол сотрудника',
    'staff.students': 'Работа со студентами',
    'admin.calendar': 'Календарь',
    'admin.students_management': 'Список студентов',
    'admin.student_detail': 'Карточка студента',
    'admin.edit_student': 'Редактирование студента',
    'admin.add_student': 'Добавление студента',
    'admin.delete_student': 'Удаление студента',
    'admin.student_app_design': 'Настройка оформления Student App',
    'admin.notifications': 'Центр уведомлений',
    'admin.notifications_publish': 'Публикация уведомления',
    'admin.notifications_read': 'Отметка уведомления как прочитанного',
    'admin.notifications_read_all': 'Отметка всех уведомлений как прочитанных',
    'admin.students_management': 'Список студентов',
    'admin.student_detail': 'Просмотр карточки студента',
    'admin.edit_student': 'Редактирование карточки студента',
    'admin.add_student': 'Добавление студента',
    'admin.delete_student': 'Удаление карточки студента',
    'admin.student_groups': 'Просмотр учебных групп',
    'admin.delete_student_group': 'Удаление учебной группы',
    'admin.search_students': 'Поиск студентов',
    'admin.most_active_students': 'Просмотр рейтинга активности',
    'admin.manage_leadership': 'Управление руководящими ролями',
    'admin.system_runtime': 'Просмотр состояния системы',
    'admin.system_maintenance': 'Обслуживание системы',
    'admin.create_manual_database_backup': 'Создание резервной копии',
    'admin.check_database_backup_action': 'Проверка резервной копии',
    'admin.restore_database_backup_action': 'Восстановление резервной копии',
    'directions.directions_list': 'Список направлений',
    'directions.direction_detail': 'Карточка направления',
    'directions.create_direction': 'Создание направления',
    'directions.archive_direction': 'Архивация направления',
    'directions.restore_direction': 'Восстановление направления',
    'directions.approve_student': 'Принятие студента в направление',
    'directions.activate_student': 'Активация студента в направлении',
    'directions.reject_student': 'Отклонение заявки студента',
    'directions.manage_questions': 'Управление вопросами направления',
    'directions.add_existing_student': 'Добавление студента в направление',
    'directions.remove_student': 'Удаление студента из направления',
    'directions.update_student_status': 'Изменение статуса студента в направлении',
    'directions.chat_message': 'Просмотр или отправка сообщения чата',
    'directions.connect_chat_candidate': 'Подключение чата направления',
    'directions.connect_social_chat': 'Подключение социального чата',
    'directions.remove_social_chat': 'Отключение социального чата',
    'directions.add_chat': 'Добавление чата направления',
    'directions.chat_audience': 'Изменение аудитории чата',
    'directions.delete_chat': 'Удаление чата направления',
    'directions.test_chat': 'Проверка чата направления',
    'lessons.list_lessons': 'Список занятий',
    'lessons.create_lesson': 'Создание занятия',
    'lessons.edit_lesson': 'Редактирование занятия',
    'lessons.publish_lesson': 'Публикация занятия',
    'lessons.delete_lesson': 'Удаление занятия',
    'quotas.quotas_list': 'Список мероприятий',
    'quotas.competition_announcement': 'Просмотр или изменение объявления',
    'quotas.publish_competition_announcement': 'Публикация объявления о мероприятии',
    'quotas.close_quota': 'Закрытие регистрации на мероприятие',
    'quotas.create_quota': 'Создание мероприятия',
    'quotas.publish_quota': 'Публикация мероприятия',
    'quotas.quota_participants': 'Просмотр участников мероприятия',
    'quotas.mark_attendance': 'Отметка посещаемости',
    'stats.overview_statistics': 'Общая статистика',
    'stats.directions_statistics': 'Статистика направлений',
    'stats.attendance_statistics': 'Статистика посещаемости',
    'stats.events_statistics': 'Статистика мероприятий',
    'stats.declines_statistics': 'Статистика отказов',
    'staff.workspace': 'Рабочее пространство сотрудника',
    'staff.students': 'Работа со студентами',
    'staff.accounts': 'Управление аккаунтами сотрудников',
    'auth.login': 'Вход в аккаунт',
    'auth.verify_otp': 'Подтверждение входа кодом',
    'auth.change_password': 'Смена пароля',
    'auth.logout': 'Выход из аккаунта',
    'student_app.student_app': 'Открытие Student App',
    'student_app.student_app_me': 'Загрузка личного профиля Student App',
    'student_app.student_app_register': 'Регистрация в Student App',
}


def _registered_user_activity_subcategory(row):
    """Return the concrete staff function nested under a five-area section."""
    action = row.action or ''
    base_action = action[:-6] if action.endswith('.view') else action
    base_action = base_action[:-7] if base_action.endswith('.failed') else base_action
    label = USER_ACTIVITY_ROUTE_LABELS.get(base_action)
    if label:
        return label
    if action.startswith('auth.'):
        return 'Вход и безопасность'
    if action.startswith('staff.'):
        return 'Управление сотрудниками'
    if action.startswith('stats.'):
        return 'Отчёты и показатели'
    if action.startswith('student_app.') or (row.path or '').startswith('/student-app'):
        return 'Student App'
    if action.startswith('directions.'):
        return 'Участники и направления'
    if action.startswith('quotas.'):
        return 'Квоты и мероприятия'
    if action.startswith(('lessons.', 'admin.calendar')):
        return 'Занятия и календарь'
    if action.startswith('admin.notifications'):
        return 'Уведомления и публикации'
    if action.startswith('admin.student'):
        return 'Карточки и списки студентов'
    tail = base_action.rsplit('.', 1)[-1] if base_action else ''
    if not tail:
        tail = (row.path or '').strip('/').split('/')[-1]
    return tail.replace('_', ' ').replace('-', ' ').strip().capitalize() or 'Общие настройки'


def _registered_user_activity_description(row):
    action = row.action or ''
    base_action = action[:-6] if action.endswith('.view') else action
    base_action = base_action[:-7] if base_action.endswith('.failed') else base_action
    route_label = USER_ACTIVITY_ROUTE_LABELS.get(base_action)
    if not route_label:
        route_label = (base_action.rsplit('.', 1)[-1] if base_action else row.path or 'раздел')
        route_label = route_label.replace('_', ' ').replace('-', ' ').strip().capitalize()
    if action == 'auth.login.succeeded':
        return 'Успешно вошёл в аккаунт'
    if action == 'auth.logout':
        return 'Вышел из аккаунта'
    if action.endswith('.failed') or (row.status_code or 0) >= 400:
        return f'Ошибка при действии: {route_label}'
    if row.method == 'GET':
        return f'Открыл: {route_label}'
    if row.method == 'POST':
        return f'Отправил действие: {route_label}'
    if row.method in {'PUT', 'PATCH'}:
        return f'Изменил данные: {route_label}'
    if row.method == 'DELETE':
        return f'Удалил или отменил: {route_label}'
    return f'Взаимодействие: {route_label}'




def _report_safe_activity_description(row):
    """Keep useful business context while stripping free-text refusal reasons."""
    description = str(getattr(row, 'description', '') or '').strip()
    action = str(getattr(row, 'action', '') or '').lower()
    if action in {'quota_declined', 'bot_quota_declined', 'quota_decline_reversed',
                  'application_withdrawn'}:
        description = re.sub(r'\s*(?:Причина|Причину)\s*:.+$', '', description,
                             flags=re.IGNORECASE | re.DOTALL).strip()
    return description or action.replace('_', ' ').capitalize() or 'Действие'


def _report_time(value):
    return value.strftime('%d.%m.%Y %H:%M:%S') if value else '—'


def _activity_report_dict(row, direction_names=None, event_titles=None):
    direction_names = direction_names or {}
    event_titles = event_titles or {}
    return {
        'id': row.id,
        'created_at': _report_time(row.created_at),
        'action': (row.action or 'action').replace('_', ' ').capitalize(),
        'action_code': row.action or '',
        'description': _report_safe_activity_description(row),
        'direction': direction_names.get(row.direction_id, '—'),
        'object': event_titles.get(row.quota_id, f'Мероприятие #{row.quota_id}' if row.quota_id else 'Направление'),
        'quota_id': row.quota_id,
        'direction_id': row.direction_id,
    }


def _event_report_data(quota):
    direction_ids = get_quota_direction_ids(quota.id)
    directions = Direction.query.filter(Direction.id.in_(direction_ids)).all() if direction_ids else []
    direction_names = {direction.id: direction.name for direction in directions}
    dates = [day.date.strftime('%d.%m.%Y') for day in quota.days if day.date]
    participation_rows = [participation for day in quota.days for participation in day.participations]
    student_ids = {item.student_id for item in participation_rows if item.student_id is not None}
    students = {item.id: item for item in Student.query.filter(Student.id.in_(student_ids)).all()} if student_ids else {}
    labels = {'registered': 'Записан', 'attended': 'Был', 'absent': 'Не был', 'cancelled': 'Отменил'}
    counts = {'registered': 0, 'attended': 0, 'absent': 0, 'cancelled': 0, 'declined': 0, 'total': len(participation_rows)}
    attendance = []
    for day in quota.days:
        for participation in day.participations:
            status = (participation.status or 'registered').lower()
            if status in counts:
                counts[status] += 1
            student = students.get(participation.student_id)
            attendance.append({
                'name': student.full_name if student else f'Студент #{participation.student_id}',
                'group': getattr(student, 'group', None) or '—',
                'date': day.date.strftime('%d.%m.%Y') if day.date else '—',
                'status': labels.get(status, status),
            })

    declines = EventQuotaDecline.query.filter_by(quota_id=quota.id).order_by(EventQuotaDecline.created_at.asc()).all()
    if declines:
        counts['declined'] = len(declines)
    decline_student_ids = {row.student_id for row in declines if row.student_id is not None}
    decline_students = {item.id: item for item in Student.query.filter(Student.id.in_(decline_student_ids)).all()} if decline_student_ids else {}
    decline_items = [{
        'name': (decline_students.get(row.student_id).full_name if decline_students.get(row.student_id) else f'Студент #{row.student_id}'),
        'date': _report_time(row.created_at),
    } for row in declines]

    activity_filter = [StudentActivity.quota_id == quota.id]
    if direction_ids:
        activity_filter.append(StudentActivity.direction_id.in_(direction_ids))
    activity_rows = (StudentActivity.query.filter(or_(*activity_filter))
                     .order_by(StudentActivity.created_at.asc(), StudentActivity.id.asc()).all())
    actions = [_activity_report_dict(row, direction_names, {quota.id: quota.event_title}) for row in activity_rows]
    return {
        'event_id': quota.id,
        'title': quota.event_title,
        'description': quota.event_description or '',
        'location': quota.location or '—',
        'time_range': quota.time_range or '—',
        'dates': ', '.join(dates) or '—',
        'capacity': sum(day.daily_places or 0 for day in quota.days),
        'publication_status': 'Опубликовано' if quota.is_published else ('Закрыто' if quota.is_closed else 'Черновик / не опубликовано'),
        'directions': [direction.name for direction in directions],
        'direction_ids': direction_ids,
        'attendance': attendance,
        'declines': decline_items,
        'counts': counts,
        'actions': actions,
    }


def _direction_event_report_details(event_ids, batch_size=120):
    """Build event report payloads in batches to keep SQL bind lists bounded."""
    clean_ids = list(dict.fromkeys(int(value) for value in (event_ids or []) if value is not None))
    reports = []
    for offset in range(0, len(clean_ids), max(1, int(batch_size))):
        reports.extend(_direction_event_report_details_batch(clean_ids[offset:offset + max(1, int(batch_size))]))
    return reports


def _direction_event_report_details_batch(event_ids):
    """Build full per-event report payloads for one bounded batch of events.

    Data is fetched in batches per database bind (events, students, activity journal),
    avoiding the per-event query fan-out that would otherwise make large direction
    reports slow to generate.
    """
    event_ids = list(dict.fromkeys(int(value) for value in (event_ids or []) if value is not None))
    if not event_ids:
        return []

    quota_rows = EventQuota.query.with_entities(
        EventQuota.id, EventQuota.event_title, EventQuota.event_description,
        EventQuota.location, EventQuota.time_range, EventQuota.is_published, EventQuota.is_closed,
    ).filter(EventQuota.id.in_(event_ids)).all()
    quota_map = {
        row.id: {
            'title': row.event_title, 'description': row.event_description or '',
            'location': row.location or '—', 'time_range': row.time_range or '—',
            'is_published': bool(row.is_published), 'is_closed': bool(row.is_closed),
        }
        for row in quota_rows
    }

    links = QuotaDirection.query.with_entities(
        QuotaDirection.quota_id, QuotaDirection.direction_id
    ).filter(QuotaDirection.quota_id.in_(event_ids)).all()
    direction_ids_by_event = {event_id: [] for event_id in event_ids}
    all_direction_ids = set()
    for quota_id, direction_id in links:
        direction_ids_by_event.setdefault(quota_id, []).append(direction_id)
        all_direction_ids.add(direction_id)
    direction_rows = Direction.query.with_entities(Direction.id, Direction.name).filter(
        Direction.id.in_(all_direction_ids)
    ).all() if all_direction_ids else []
    direction_names = {row.id: row.name for row in direction_rows}

    # One attendance query for all events; each row carries its day metadata.
    day_rows = db.session.query(
        EventDay.quota_id, EventDay.date, EventDay.daily_places,
        DayParticipation.student_id, DayParticipation.status,
    ).outerjoin(DayParticipation, DayParticipation.day_id == EventDay.id).filter(
        EventDay.quota_id.in_(event_ids)
    ).order_by(EventDay.quota_id.desc(), EventDay.date.asc(), DayParticipation.id.asc()).all()

    event_builders = {
        event_id: {
            'dates': [], 'date_keys': set(), 'capacity': 0,
            'attendance_rows': [],
            'counts': {'registered': 0, 'attended': 0, 'absent': 0, 'cancelled': 0,
                       'declined': 0, 'total': 0},
        }
        for event_id in event_ids
    }
    student_ids = set()
    status_labels = {'registered': 'Записан', 'attended': 'Был', 'absent': 'Не был', 'cancelled': 'Отменил'}
    for quota_id, event_date, daily_places, student_id, status in day_rows:
        target = event_builders.get(quota_id)
        if target is None:
            continue
        target['capacity'] += int(daily_places or 0)
        date_key = event_date.strftime('%d.%m.%Y') if event_date else '—'
        if event_date and date_key not in target['date_keys']:
            target['date_keys'].add(date_key)
            target['dates'].append(date_key)
        if student_id is None:
            continue
        status_key = (status or 'registered').lower()
        target['counts']['total'] += 1
        if status_key in target['counts']:
            target['counts'][status_key] += 1
        target['attendance_rows'].append((date_key, student_id, status_key))
        student_ids.add(student_id)

    decline_rows = (EventQuotaDecline.query.with_entities(
        EventQuotaDecline.quota_id, EventQuotaDecline.student_id, EventQuotaDecline.created_at
    ).filter(EventQuotaDecline.quota_id.in_(event_ids))
     .order_by(EventQuotaDecline.quota_id.asc(), EventQuotaDecline.created_at.asc()).all())
    declines_by_event = {event_id: [] for event_id in event_ids}
    for quota_id, student_id, created_at in decline_rows:
        declines_by_event.setdefault(quota_id, []).append((student_id, created_at))
        if student_id is not None:
            student_ids.add(student_id)

    student_rows = []
    student_id_list = list(student_ids)
    for offset in range(0, len(student_id_list), 500):
        student_rows.extend(Student.query.with_entities(
            Student.id, Student.full_name, Student.group
        ).filter(Student.id.in_(student_id_list[offset:offset + 500])).all())
    students = {row.id: {'name': row.full_name, 'group': row.group or '—'} for row in student_rows}

    # Query all potentially relevant activity rows once. A standalone event report
    # includes event-linked actions plus actions attached to any linked direction.
    action_filter = [StudentActivity.quota_id.in_(event_ids)]
    if all_direction_ids:
        action_filter.append(StudentActivity.direction_id.in_(all_direction_ids))
    action_rows = (StudentActivity.query.filter(or_(*action_filter))
                   .order_by(StudentActivity.created_at.asc(), StudentActivity.id.asc()).all())
    quota_titles = {event_id: data['title'] for event_id, data in quota_map.items()}
    actions_by_event = {event_id: [] for event_id in event_ids}
    events_by_direction = {}
    for event_id, linked_ids in direction_ids_by_event.items():
        for linked_direction_id in linked_ids:
            events_by_direction.setdefault(linked_direction_id, set()).add(event_id)
    for row in action_rows:
        matching_events = set()
        if row.quota_id in actions_by_event:
            matching_events.add(row.quota_id)
        if row.direction_id in events_by_direction:
            matching_events.update(events_by_direction[row.direction_id])
        if not matching_events:
            continue
        activity = _activity_report_dict(row, direction_names, quota_titles)
        for event_id in matching_events:
            actions_by_event[event_id].append(activity)

    result = []
    for event_id in event_ids:
        meta = quota_map.get(event_id)
        if not meta:
            continue
        target = event_builders[event_id]
        attendance = [{
            'name': students.get(student_id, {}).get('name') or f'Студент #{student_id}',
            'group': students.get(student_id, {}).get('group') or '—',
            'date': date_key,
            'status': status_labels.get(status_key, status_key),
        } for date_key, student_id, status_key in target['attendance_rows']]
        decline_items = [{
            'name': students.get(student_id, {}).get('name') or f'Студент #{student_id}',
            'date': _report_time(created_at),
        } for student_id, created_at in declines_by_event.get(event_id, [])]
        counts = dict(target['counts'])
        counts['declined'] = len(decline_items)
        linked_ids = direction_ids_by_event.get(event_id, [])
        dates = ', '.join(target['dates']) or '—'
        result.append({
            'event_id': event_id,
            'title': meta['title'],
            'description': meta['description'],
            'location': meta['location'],
            'time_range': meta['time_range'],
            'dates': dates,
            'capacity': target['capacity'],
            'publication_status': 'Опубликовано' if meta['is_published'] else (
                'Закрыто' if meta['is_closed'] else 'Черновик / не опубликовано'
            ),
            'directions': [direction_names[value] for value in linked_ids if value in direction_names],
            'direction_ids': linked_ids,
            'attendance': attendance,
            'declines': decline_items,
            'counts': counts,
            'actions': actions_by_event.get(event_id, []),
        })
    return result


def _direction_report_data(direction, action_page=None, action_page_size=200, include_event_reports=False,
                           exclusive_event_scope=False):
    """Build one complete direction report from SQL aggregates and bounded action rows."""
    event_ids = get_direction_quota_ids(direction.id)
    if exclusive_event_scope:
        event_ids = [quota_id for quota_id in event_ids
                     if _quota_direction_scope_ids(quota_id) == {int(direction.id)}]
    event_rows = (EventQuota.query.with_entities(EventQuota.id, EventQuota.event_title)
                  .filter(EventQuota.id.in_(event_ids)).order_by(EventQuota.id.desc()).all()
                  if event_ids else [])
    event_titles = {event_id: title for event_id, title in event_rows}

    event_summary = {
        event_id: {"dates": [], "participants": 0, "attended": 0,
                   "absent": 0, "cancelled": 0, "registered": 0}
        for event_id, _title in event_rows
    }
    if event_ids:
        event_day_rows = (db.session.query(
            EventDay.quota_id, EventDay.date,
            func.count(DayParticipation.id).label("participants"),
            func.sum(sa_case((DayParticipation.status == "attended", 1), else_=0)).label("attended"),
            func.sum(sa_case((DayParticipation.status == "absent", 1), else_=0)).label("absent"),
            func.sum(sa_case((DayParticipation.status == "cancelled", 1), else_=0)).label("cancelled"),
            func.sum(sa_case((DayParticipation.status == "registered", 1), else_=0)).label("registered"),
        ).outerjoin(DayParticipation, DayParticipation.day_id == EventDay.id)
         .filter(EventDay.quota_id.in_(event_ids)).group_by(EventDay.id)
         .order_by(EventDay.quota_id.desc(), EventDay.date.asc()).all())
        for quota_id, event_date, participants, attended, absent, cancelled, registered in event_day_rows:
            summary = event_summary.setdefault(quota_id, {"dates": [], "participants": 0,
                "attended": 0, "absent": 0, "cancelled": 0, "registered": 0})
            if event_date:
                summary["dates"].append(event_date.strftime('%d.%m.%Y'))
            for key, value in (("participants", participants), ("attended", attended),
                               ("absent", absent), ("cancelled", cancelled), ("registered", registered)):
                summary[key] += int(value or 0)

    decline_counts = dict(db.session.query(EventQuotaDecline.quota_id, func.count(EventQuotaDecline.id))
                          .filter(EventQuotaDecline.quota_id.in_(event_ids))
                          .group_by(EventQuotaDecline.quota_id).all()) if event_ids else {}
    event_details = []
    attendance_totals = {"registered": 0, "attended": 0, "absent": 0, "cancelled": 0, "declined": 0, "total": 0}
    for event_id, title in event_rows:
        summary = event_summary[event_id]
        declined = int(decline_counts.get(event_id, 0) or 0)
        summary["declined"] = declined
        event_details.append({
            'id': event_id, 'title': title,
            'dates': ', '.join(summary['dates']) or '—',
            'participants': summary['participants'], 'attended': summary['attended'],
            'absent': summary['absent'], 'cancelled': summary['cancelled'],
            'registered': summary['registered'], 'declined': declined,
        })
        for key in attendance_totals:
            if key == 'total':
                attendance_totals[key] += summary['participants']
            else:
                attendance_totals[key] += summary.get(key, 0)

    action_filter = [StudentActivity.direction_id == direction.id]
    if event_ids:
        action_filter.append(StudentActivity.quota_id.in_(event_ids))
    action_query = StudentActivity.query.filter(or_(*action_filter))
    action_count = action_query.count()
    bot_action_count = action_query.filter(
        StudentActivity.action.in_(tuple(BOT_MONITOR_ACTION_LABELS.keys()))
    ).count()
    actions = []
    # The PDF intentionally omits the business-action history. Do not materialize
    # every journal row merely to discard it; the HTML page still loads 200 rows
    # per page for administrators who explicitly open the history.
    if action_page is not None:
        action_query = action_query.order_by(StudentActivity.created_at.asc(), StudentActivity.id.asc())
        action_query = action_query.offset((max(1, action_page) - 1) * action_page_size).limit(action_page_size)
        action_rows = action_query.all()
        actions = [_activity_report_dict(row, {direction.id: direction.name}, event_titles) for row in action_rows]

    student_count = int(db.session.query(func.count()).select_from(student_directions).filter(
        student_directions.c.direction_id == direction.id
    ).scalar() or 0)
    member_status_rows = (db.session.query(student_directions.c.status, func.count(student_directions.c.student_id))
        .filter(student_directions.c.direction_id == direction.id)
        .group_by(student_directions.c.status).all())
    status_labels = {'pending': 'На рассмотрении', 'interview': 'Собеседование',
                     'active': 'Активные', 'rejected': 'Отклонённые'}
    member_status_counts = {status_labels.get(status, status or 'Не указан'): int(count or 0)
                             for status, count in member_status_rows}
    application_rows = (db.session.query(ApplicationDecision.decision, func.count(ApplicationDecision.id))
        .filter(ApplicationDecision.direction_id == direction.id)
        .group_by(ApplicationDecision.decision).all())
    application_labels = {'submitted': 'Подано', 'pending': 'На рассмотрении',
                          'approved': 'Принято', 'active': 'Активировано', 'rejected': 'Отклонено',
                          'withdrawn': 'Отозвано', 'interview': 'Собеседование'}
    application_counts = {application_labels.get(value, value or 'Не указано'): int(count or 0)
                          for value, count in application_rows}
    lesson_rows = (db.session.query(Lesson.status, func.count(Lesson.id))
                   .filter(Lesson.direction_id == direction.id).group_by(Lesson.status).all())
    lesson_status_counts = {str(status or 'Не указан'): int(count or 0) for status, count in lesson_rows}
    lesson_count = sum(lesson_status_counts.values())
    return {
        'direction_id': direction.id, 'name': direction.name, 'code': direction.code,
        'status': 'Архивное' if direction.is_archived else 'Активное',
        'student_count': student_count, 'event_count': len(event_rows),
        'lesson_count': lesson_count, 'action_count': action_count,
        'bot_action_count': bot_action_count,
        'attendance_totals': attendance_totals,
        'member_status_counts': member_status_counts,
        'application_counts': application_counts,
        'lesson_status_counts': lesson_status_counts,
        'events': event_details, 'actions': actions,
        'event_reports': _direction_event_report_details(event_ids) if include_event_reports else [],
    }


def _report_archive_root():
    root = Path(current_app.instance_path) / 'report_archive'
    root.mkdir(parents=True, exist_ok=True)
    return root


def _report_safe_filename(value, fallback='report'):
    text = str(value or fallback).strip()
    text = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', '-', text)
    text = re.sub(r'\s+', ' ', text).strip(' .-_')
    if text.lower().endswith('.pdf'):
        text = text[:-4]
    return (text[:150] or fallback) + '.pdf'


def _store_report_archive_pdf(*, pdf_bytes, report_type, report_key, report_title,
                              filename, owner_user=None, direction_id=None, direction_ids=None, event_id=None,
                              signature_code=None, signed_by_user=None, signed_at=None,
                              archive_year=None, archive_month=None):
    """Persist a generated PDF and an indexed row; files are never served by static routes."""
    now = datetime.utcnow()
    year = int(archive_year or now.year)
    month = int(archive_month or now.month)
    if year < 2000 or year > now.year + 1 or month < 1 or month > 12:
        raise ValueError('Invalid report archive period')
    safe_name = _report_safe_filename(filename)
    folder = _report_archive_root() / str(year) / f'{month:02d}'
    folder.mkdir(parents=True, exist_ok=True)
    unique_prefix = (str(signature_code or secrets.token_hex(4)).replace('/', '-')[:40])
    stored_name = f'{Path(safe_name).stem}_{unique_prefix}.pdf'
    target = folder / stored_name
    temp = folder / (stored_name + '.tmp')
    temp.write_bytes(pdf_bytes)
    temp.replace(target)
    relative_path = target.relative_to(_report_archive_root()).as_posix()
    row = ReportArchiveDocument(
        report_type=str(report_type)[:32], report_key=str(report_key)[:160],
        report_title=str(report_title)[:255], direction_id=direction_id, event_id=event_id,
        owner_user_id=getattr(owner_user, 'id', None),
        owner_name=((getattr(owner_user, 'full_name', None) or getattr(owner_user, 'email', None))
                    if owner_user else None),
        filename=safe_name, relative_path=relative_path,
        file_sha256=hashlib.sha256(pdf_bytes).hexdigest(),
        signature_code=signature_code,
        signed_by_user_id=getattr(signed_by_user, 'id', None),
        signed_by_name=((getattr(signed_by_user, 'full_name', None) or getattr(signed_by_user, 'email', None))
                        if signed_by_user else None),
        signed_at=signed_at, report_year=year, report_month=month, created_at=now,
    )
    try:
        db.session.add(row)
        db.session.flush()
        clean_direction_ids = set(int(value) for value in (direction_ids or []) if value)
        if direction_id:
            clean_direction_ids.add(int(direction_id))
        if clean_direction_ids:
            db.session.add_all([
                ReportArchiveDocumentDirection(document_id=row.id, direction_id=value)
                for value in sorted(clean_direction_ids)
            ])
        db.session.commit()
    except Exception:
        db.session.rollback()
        try:
            target.unlink(missing_ok=True)
        except Exception:
            pass
        raise
    return row


def _report_archive_can_view(user, document):
    role = getattr(user, 'role', '')
    if role == UserRole.SUPER_ADMIN.value:
        # The main administrator can inspect every report, including legacy
        # documents without direction metadata and reports for archived areas.
        return True
    if role == UserRole.OBSERVER.value:
        # Leadership accounts can read reports for active directions only.
        if document.report_type not in {'direction', 'event'}:
            return False
        linked_ids = {int(document.direction_id)} if document.direction_id else set()
        linked_ids.update(int(row.direction_id) for row in ReportArchiveDocumentDirection.query.filter_by(
            document_id=document.id).all())
        if not linked_ids:
            return False
        active_ids = {row.id for row in Direction.query.filter(
            Direction.id.in_(linked_ids), Direction.is_archived.is_(False)).all()}
        return active_ids == linked_ids
    if role == UserRole.STAFF.value:
        # Each document must belong wholly to the employee's explicitly granted
        # report-archive scope. Mixed documents cannot leak data from a foreign area.
        from services.staff_access import direction_ids as staff_direction_ids
        permitted_ids = set(staff_direction_ids(user, 'report_archive', 'view'))
        if not permitted_ids:
            return False
        if document.report_type == 'staff_work':
            return document.owner_user_id == user.id
        if document.report_type not in {'direction', 'event'}:
            return False
        linked_ids = {int(document.direction_id)} if document.direction_id else set()
        linked_ids.update(int(row.direction_id) for row in ReportArchiveDocumentDirection.query.filter_by(
            document_id=document.id).all())
        return bool(linked_ids) and linked_ids.issubset(permitted_ids)
    return bool(document.report_type == 'staff_work' and document.owner_user_id == user.id)


def _report_archive_file(document):
    root = _report_archive_root().resolve()
    path = (root / document.relative_path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        abort(404)
    return path


def _file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _create_signed_report_response(*, current_user, report_type, report_key, report_title,
                                   report_data, pdf_builder, filename, direction_id=None, direction_ids=None, event_id=None):
    """Build a signed PDF, retain its signature evidence, and add it to the archive."""
    canonical = json.dumps(report_data, ensure_ascii=False, sort_keys=True,
                           separators=(',', ':'), default=str).encode('utf-8')
    source_hash = hashlib.sha256(canonical).hexdigest()
    signer_name = (getattr(current_user, 'full_name', None) or current_user.email or 'Главный администратор').strip()
    signature_code = f"ADM-{datetime.utcnow():%Y%m%d}-{secrets.token_hex(4).upper()}"
    signed_at = datetime.utcnow()
    signature_row = AdminReportSignature(
        signature_code=signature_code,
        report_type=report_type,
        report_key=str(report_key)[:120],
        report_title=str(report_title)[:255],
        signer_user_id=current_user.id,
        signer_name=signer_name[:255],
        signer_login=(current_user.email or '')[:255],
        content_sha256=source_hash,
        document_sha256='',
        signed_at=signed_at,
    )
    try:
        db.session.add(signature_row)
        db.session.flush()
        signature = {
            'id': signature_row.id,
            'signature_code': signature_code,
            'signer_name': signer_name,
            'signer_login': current_user.email or '',
            'signed_at': signed_at.strftime('%d.%m.%Y %H:%M:%S UTC'),
            'content_sha256': source_hash,
        }
        pdf_bytes = pdf_builder(report_data, signature)
        signature_row.document_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
        db.session.commit()
        _store_report_archive_pdf(
            pdf_bytes=pdf_bytes, report_type=report_type, report_key=report_key,
            report_title=report_title, filename=filename, owner_user=current_user,
            direction_id=direction_id, direction_ids=direction_ids, event_id=event_id, signature_code=signature_code,
            signed_by_user=current_user, signed_at=signed_at,
        )
    except Exception:
        db.session.rollback()
        logger.exception('Could not create chief-admin signed PDF report type=%s key=%s', report_type, report_key)
        raise

    response = send_file(io.BytesIO(pdf_bytes), mimetype='application/pdf', as_attachment=True,
                         download_name=filename, max_age=0)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Report-Signature'] = signature_code
    response.headers['X-Report-SHA256'] = signature_row.document_sha256
    return response


@admin_bp.route('/event-reports')
@super_admin_required
def event_reports(current_user):
    """Institution-wide report hub for the main administrator."""
    directions = Direction.query.order_by(Direction.name.asc()).all()
    # Aggregate once instead of walking up to 500 event -> day -> participation
    # relationship trees on every page view (the old page caused a large N+1 query fan-out).
    from database import BotJournalEvent
    event_links = (db.session.query(
        QuotaDirection.quota_id, QuotaDirection.direction_id, EventQuota.event_title
    ).join(EventQuota, EventQuota.id == QuotaDirection.quota_id).all())
    directions_by_event = {}
    events_by_direction = {direction.id: {} for direction in directions}
    for quota_id, direction_id, event_title in event_links:
        directions_by_event.setdefault(quota_id, set()).add(direction_id)
        events_by_direction.setdefault(direction_id, {})[quota_id] = {
            'id': quota_id, 'title': event_title or f'Мероприятие #{quota_id}'
        }
    action_groups = (db.session.query(
        StudentActivity.direction_id, StudentActivity.quota_id, func.count(StudentActivity.id)
    ).group_by(StudentActivity.direction_id, StudentActivity.quota_id).all())
    direction_activity = {}
    for activity_direction_id, quota_id, action_total in action_groups:
        action_total = int(action_total or 0)
        if activity_direction_id is not None:
            direction_activity[activity_direction_id] = direction_activity.get(activity_direction_id, 0) + action_total
        for linked_direction_id in directions_by_event.get(quota_id, ()):
            if linked_direction_id != activity_direction_id:
                direction_activity[linked_direction_id] = direction_activity.get(linked_direction_id, 0) + action_total
    bot_business_actions = tuple(BOT_MONITOR_ACTION_LABELS.keys())
    stats = {
        'directions': len(directions),
        'events': EventQuota.query.count(),
        'actions': StudentActivity.query.count(),
        'staff_actions': HttpAuditLog.query.filter(
            HttpAuditLog.actor_user_id.isnot(None),
            HttpAuditLog.actor_role.in_(STAFF_AUDIT_ROLES),
        ).count(),
        'bot_actions': StudentActivity.query.filter(StudentActivity.action.in_(bot_business_actions)).count(),
        'bot_system_events': BotJournalEvent.query.count(),
        'signatures': AdminReportSignature.query.count(),
    }
    student_counts = dict(db.session.query(student_directions.c.direction_id, func.count(student_directions.c.student_id))
                          .group_by(student_directions.c.direction_id).all())
    lesson_counts = dict(db.session.query(Lesson.direction_id, func.count(Lesson.id))
                         .group_by(Lesson.direction_id).all())
    direction_rows = []
    for direction in directions:
        direction_rows.append({
            'id': direction.id,
            'name': direction.name,
            'code': direction.code,
            'status': 'Архивное' if direction.is_archived else 'Активное',
            'actions': direction_activity.get(direction.id, 0),
            'students': student_counts.get(direction.id, 0),
            'lessons': lesson_counts.get(direction.id, 0),
            'events': sorted(events_by_direction.get(direction.id, {}).values(),
                             key=lambda event: (str(event['title']).casefold(), event['id'])),
        })
    signature_log = AdminReportSignature.query.order_by(
        AdminReportSignature.signed_at.desc(), AdminReportSignature.id.desc()
    ).limit(20).all()
    return render_template(
        'events/reports.html', directions=direction_rows, summary=stats,
        admin_signer_name=(getattr(current_user, 'full_name', None) or current_user.email),
        signature_log=signature_log,
    )


@admin_bp.get('/direction-reports/<int:direction_id>')
@super_admin_required
def direction_report_html(current_user, direction_id):
    """Dedicated HTML report page for one direction."""
    if direction_id not in _staff_visible_direction_ids(current_user):
        abort(403)
    direction = db.session.get(Direction, direction_id)
    if not direction:
        abort(404)
    page = max(1, request.args.get('page', 1, type=int))
    page_size = 200
    report_data = _direction_report_data(
        direction, action_page=page, action_page_size=page_size,
        exclusive_event_scope=False,
    )
    return render_template(
        'events/direction_report.html', report=report_data, action_page=page,
        action_pages=max(1, (report_data['action_count'] + page_size - 1) // page_size),
        admin_signer_name=(getattr(current_user, 'full_name', None) or current_user.email),
    )


@admin_bp.get('/event-reports/<int:event_id>')
@super_admin_required
def event_report_html(current_user, event_id):
    # Dedicated HTML report page for one event.
    quota = (EventQuota.query.options(selectinload(EventQuota.days).selectinload(EventDay.participations))
             .filter_by(id=event_id).first())
    if not quota:
        abort(404)
    report_data = _event_report_data(quota)
    return render_template(
        'events/event_report.html', report=report_data,
        admin_signer_name=(getattr(current_user, 'full_name', None) or current_user.email),
    )


@admin_bp.get('/event-reports/<int:event_id>.pdf')
@super_admin_required
def event_report_pdf(current_user, event_id):
    quota = (EventQuota.query.options(selectinload(EventQuota.days).selectinload(EventDay.participations))
             .filter_by(id=event_id).first())
    if not quota:
        abort(404)
    from services.report_pdfs import build_event_report_pdf
    report_data = _event_report_data(quota)
    return _create_signed_report_response(
        current_user=current_user, report_type='event', report_key=f'event:{event_id}',
        report_title=f"Мероприятие: {quota.event_title}", report_data=report_data,
        pdf_builder=build_event_report_pdf, filename=f'event-report-{event_id}.pdf',
        event_id=event_id, direction_ids=get_quota_direction_ids(event_id),
        direction_id=(get_quota_direction_ids(event_id) or [None])[0],
    )


@admin_bp.get('/event-reports/<int:event_id>.csv')
@super_admin_required
def event_report_export(current_user, event_id):
    """Legacy attendance CSV export; official signed copies are generated as PDF."""
    quota = (EventQuota.query.options(selectinload(EventQuota.days).selectinload(EventDay.participations))
             .filter_by(id=event_id).first())
    if not quota:
        abort(404)
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(('Мероприятие', 'Дата', 'Студент', 'Группа', 'Посещаемость'))
    for day in quota.days:
        for participation in day.participations:
            student = participation.student
            status = (participation.status or 'registered').lower()
            label = {'registered':'Записан','attended':'Был','absent':'Не был','cancelled':'Отменил'}.get(status, status)
            writer.writerow((quota.event_title, day.date.strftime('%d.%m.%Y') if day.date else '',
                             student.full_name if student else f'Студент #{participation.student_id}',
                             getattr(student, 'group', None) or '—', label))
    response = Response('\ufeff' + output.getvalue(), mimetype='text/csv; charset=utf-8')
    response.headers['Content-Disposition'] = f'attachment; filename="event-attendance-{event_id}.csv"'
    response.headers['Cache-Control'] = 'no-store'
    return response


@admin_bp.get('/direction-reports/<int:direction_id>.pdf')
@super_admin_required
def direction_report_pdf(current_user, direction_id):
    if direction_id not in _staff_visible_direction_ids(current_user):
        abort(403)
    direction = db.session.get(Direction, direction_id)
    if not direction:
        abort(404)
    from services.report_pdfs import build_direction_report_pdf
    report_data = _direction_report_data(
        direction, include_event_reports=True,
        exclusive_event_scope=False,
    )
    return _create_signed_report_response(
        current_user=current_user, report_type='direction', report_key=f'direction:{direction_id}',
        report_title=f"Направление: {direction.name}", report_data=report_data,
        pdf_builder=build_direction_report_pdf, filename=f"{_report_safe_filename(direction.name).removesuffix('.pdf')}.pdf",
        direction_id=direction_id, direction_ids=[direction_id],
    )


@admin_bp.get('/report-archive')
@login_required
def report_archive(current_user):
    """User-facing report library with role-scoped visibility and downloads."""
    role = current_user.role
    query = ReportArchiveDocument.query
    if role == UserRole.SUPER_ADMIN.value:
        # No direction filter for the main administrator: this is the site-wide
        # archive, including documents linked to inactive/archived directions.
        query = query
    elif role == UserRole.OBSERVER.value:
        query = query.filter(ReportArchiveDocument.report_type.in_(('direction', 'event')))
    elif role == UserRole.STAFF.value:
        # Do not borrow visibility from students/events/etc.: the archive has
        # its own explicit grant and is always restricted to the assigned area.
        from services.staff_access import direction_ids as staff_direction_ids
        active_ids = set(staff_direction_ids(current_user, 'report_archive', 'view'))
        mapped_docs = db.session.query(ReportArchiveDocumentDirection.document_id).filter(
            ReportArchiveDocumentDirection.direction_id.in_(active_ids)) if active_ids else db.session.query(ReportArchiveDocumentDirection.document_id).filter(db.false())
        query = query.filter(
            (ReportArchiveDocument.report_type.in_(('direction', 'event')) &
             (ReportArchiveDocument.direction_id.in_(active_ids) | ReportArchiveDocument.id.in_(mapped_docs)))
            | and_(ReportArchiveDocument.report_type == 'staff_work',
                  ReportArchiveDocument.owner_user_id == current_user.id))
    else:
        own_work_filter = and_(
            ReportArchiveDocument.owner_user_id == current_user.id,
            ReportArchiveDocument.report_type == 'staff_work',
        )
        query = query.filter(own_work_filter)

    years = [int(value) for (value,) in query.with_entities(
        ReportArchiveDocument.report_year
    ).distinct().order_by(ReportArchiveDocument.report_year.desc()).all()]
    selected_year = request.args.get('year', type=int)
    if selected_year not in years:
        selected_year = years[0] if years else datetime.utcnow().year
    selected_month = request.args.get('month', type=int)
    if selected_month is not None and not 1 <= selected_month <= 12:
        selected_month = None
    selected_direction = request.args.get('direction', type=int)
    if role not in {UserRole.SUPER_ADMIN.value, UserRole.OBSERVER.value, UserRole.STAFF.value}:
        selected_direction = None
    elif role == UserRole.STAFF.value and selected_direction:
        from services.staff_access import direction_ids as staff_direction_ids
        if selected_direction not in staff_direction_ids(current_user, 'report_archive', 'view'):
            abort(403)

    if selected_year:
        query = query.filter(ReportArchiveDocument.report_year == selected_year)
    if selected_month:
        query = query.filter(ReportArchiveDocument.report_month == selected_month)
    if selected_direction:
        direction_document_ids = db.session.query(ReportArchiveDocumentDirection.document_id).filter_by(
            direction_id=selected_direction
        )
        query = query.filter(or_(ReportArchiveDocument.direction_id == selected_direction,
                                 ReportArchiveDocument.id.in_(direction_document_ids)))
    documents = query.order_by(
        ReportArchiveDocument.report_year.desc(), ReportArchiveDocument.report_month.desc(),
        ReportArchiveDocument.created_at.desc(), ReportArchiveDocument.id.desc()
    ).limit(500).all()
    # Apply the same object-level access check to every role, even after the
    # SQL scope above. This protects legacy/multi-direction document mappings.
    documents = [document for document in documents if _report_archive_can_view(current_user, document)]
    direction_ids = {row.direction_id for row in documents if row.direction_id}
    direction_map_rows = ReportArchiveDocumentDirection.query.filter(
        ReportArchiveDocumentDirection.document_id.in_([row.id for row in documents])
    ).all() if documents else []
    for mapping in direction_map_rows:
        direction_ids.add(mapping.direction_id)
    direction_names = {row.id: row.name for row in Direction.query.filter(Direction.id.in_(direction_ids)).all()} if direction_ids else {}
    document_direction_ids = {item.id: ({int(item.direction_id)} if item.direction_id else set()) for item in documents}
    for mapping in direction_map_rows:
        document_direction_ids.setdefault(mapping.document_id, set()).add(int(mapping.direction_id))
    document_direction_names = {
        document_id: ', '.join(direction_names[direction_id] for direction_id in sorted(values)
                                if direction_id in direction_names)
        for document_id, values in document_direction_ids.items()
    }

    if role == UserRole.SUPER_ADMIN.value:
        directions = Direction.query.order_by(Direction.name.asc()).all()
        year_backups, archive_backup_token, can_manage_years = {}, None, True
    elif role == UserRole.STAFF.value:
        from services.staff_access import direction_ids as staff_direction_ids
        visible_ids = set(staff_direction_ids(current_user, 'report_archive', 'view'))
        directions = Direction.query.filter(Direction.id.in_(visible_ids), Direction.is_archived.is_(False)).order_by(Direction.name.asc()).all() if visible_ids else []
        year_backups, archive_backup_token, can_manage_years = {}, None, False
    elif role == UserRole.OBSERVER.value:
        directions = Direction.query.filter_by(is_archived=False).order_by(Direction.name.asc()).all()
        year_backups, archive_backup_token, can_manage_years = {}, None, False
    else:
        # Personal work exports are not direction-wide documents.
        directions = []
        year_backups, archive_backup_token, can_manage_years = {}, None, False

    return render_template(
        'events/report_archive.html', documents=documents, years=years,
        directions=directions, direction_names=direction_names,
        document_direction_names=document_direction_names,
        selected_year=selected_year, selected_month=selected_month,
        selected_direction=selected_direction, can_manage_years=can_manage_years,
        archive_backup_token=archive_backup_token,
        year_backups=year_backups,
        is_chief_admin=(role == UserRole.SUPER_ADMIN.value),
        can_create_own_report=(role == UserRole.LEADER.value),
    )


@admin_bp.get('/report-archive/<int:document_id>/download')
@login_required
def report_archive_download(current_user, document_id):
    document = db.session.get(ReportArchiveDocument, document_id)
    if not document or not _report_archive_can_view(current_user, document):
        abort(404)
    path = _report_archive_file(document)
    if _file_sha256(path) != document.file_sha256:
        logger.error('Report archive integrity check failed for document id=%s', document.id)
        abort(409, description='Контрольная сумма PDF не совпадает.')
    response = send_file(path, mimetype='application/pdf', as_attachment=True,
                         download_name=document.filename, max_age=0, conditional=True)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@admin_bp.get('/report-archive/my-work.pdf')
@login_required
def report_archive_my_work_pdf(current_user):
    """Export only this employee's own authenticated actions for the selected month."""
    # Personal work exports are a separate create action; employees have only
    # read/download rights in the report archive, so this action is leader-only.
    if current_user.role != UserRole.LEADER.value:
        abort(403)
    year = request.args.get('year', type=int) or datetime.utcnow().year
    month = request.args.get('month', type=int) or datetime.utcnow().month
    if year < 2000 or year > datetime.utcnow().year + 1 or not 1 <= month <= 12:
        abort(400)
    start = datetime(year, month, 1)
    end = datetime(year + (month == 12), (month % 12) + 1, 1)
    rows = (HttpAuditLog.query.filter(
        HttpAuditLog.actor_user_id == current_user.id,
        HttpAuditLog.created_at >= start, HttpAuditLog.created_at < end,
        HttpAuditLog.actor_role.in_((UserRole.STAFF.value, UserRole.LEADER.value)),
    ).order_by(HttpAuditLog.created_at.asc(), HttpAuditLog.id.asc()).limit(10000).all())
    if not rows:
        flash('За выбранный месяц в журнале нет зафиксированных действий вашего аккаунта.', 'info')
        return redirect(url_for('admin.report_archive', year=year, month=month))
    from services.report_pdfs import build_staff_journal_pdf
    entries = []
    for row in rows:
        entries.append({
            'created_at': row.created_at.strftime('%d.%m.%Y %H:%M:%S') if row.created_at else '—',
            'account': f"{getattr(current_user, 'full_name', None) or current_user.email}\\n{current_user.email}\\nСотрудник",
            'action': f"{row.method} · {row.action} · HTTP {row.status_code}",
            'section': (row.path or '/').split('/')[1][:80] or 'Главная',
        })
    raw_name = getattr(current_user, 'full_name', None) or current_user.email
    code = f"SELF-{year}{month:02d}-{secrets.token_hex(3).upper()}"
    canonical = json.dumps(entries, ensure_ascii=False, sort_keys=True).encode('utf-8')
    signature = {
        'signature_code': code, 'signer_name': raw_name,
        'signed_at': datetime.utcnow().strftime('%d.%m.%Y %H:%M:%S UTC'),
        'content_sha256': hashlib.sha256(canonical).hexdigest(),
        'is_official_signature': False,
    }
    data = {'total': len(entries), 'entries': entries, 'filter_summary': f'Личные действия аккаунта за {month:02d}.{year}.'}
    pdf_bytes = build_staff_journal_pdf(data, signature)
    filename = _report_safe_filename(f'Личные действия {raw_name} {year}-{month:02d}')
    _store_report_archive_pdf(
        pdf_bytes=pdf_bytes, report_type='staff_work',
        report_key=f'staff-work:{current_user.id}:{year}-{month:02d}',
        report_title=f'Личные действия: {raw_name} · {month:02d}.{year}',
        filename=filename, owner_user=current_user, signature_code=code,
        archive_year=year, archive_month=month,
    )
    response = send_file(io.BytesIO(pdf_bytes), mimetype='application/pdf', as_attachment=True,
                         download_name=filename, max_age=0)
    response.headers['Cache-Control'] = 'no-store'
    return response


@admin_bp.get('/report-archive/year/<int:year>/backup.zip')
@archive_year_admin_required
def report_archive_year_backup(current_user, year):
    """Create and download a pre-deletion ZIP containing only signed general direction PDFs."""
    if year < 2000 or year > datetime.utcnow().year + 1:
        abort(400)
    documents = ReportArchiveDocument.query.filter_by(
        report_year=year, report_type='direction'
    ).filter(ReportArchiveDocument.signature_code.isnot(None)).order_by(
        ReportArchiveDocument.id.asc()
    ).all()
    if not documents:
        flash('За выбранный год нет подписанных общих отчётов направлений для архивации.', 'warning')
        return redirect(url_for('admin.report_archive', year=year))
    document_set = [
        {'id': row.id, 'relative_path': row.relative_path, 'sha256': row.file_sha256,
         'signature_code': row.signature_code, 'month': row.report_month}
        for row in documents
    ]
    document_set_hash = hashlib.sha256(json.dumps(
        document_set, ensure_ascii=False, sort_keys=True, separators=(',', ':')
    ).encode('utf-8')).hexdigest()
    token = secrets.token_urlsafe(24)
    backup_root = Path(current_app.instance_path) / 'report_archive_backups'
    backup_root.mkdir(parents=True, exist_ok=True)
    backup_path = backup_root / f'reports-{year}-{token[:10]}.zip'
    temp = backup_path.with_suffix('.zip.tmp')
    manifest = [f'Архив общих отчётов направлений за {year} год',
                'Оформление: ГОСТ Р 7.0.97-2025',
                'В ZIP включены только подписанные общие PDF-отчёты направлений.', '']
    try:
        with zipfile.ZipFile(temp, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for document in documents:
                path = _report_archive_file(document)
                digest = _file_sha256(path)
                if digest != document.file_sha256:
                    abort(409, description=f'Нарушена целостность файла: {document.filename}')
                archive_name = f'{year}/{document.report_month:02d}/{Path(document.relative_path).name}'
                archive.write(path, archive_name)
                manifest.append(f'{archive_name} | SHA-256: {digest} | Подпись: {document.signature_code}')
            archive.writestr(f'{year}/MANIFEST.txt', '\n'.join(manifest).encode('utf-8'))
        # Test the ZIP central directory before making it available for deletion approval.
        with zipfile.ZipFile(temp, 'r') as archive:
            bad_member = archive.testzip()
            if bad_member is not None:
                raise ValueError(f'Повреждённый файл в ZIP: {bad_member}')
        temp.replace(backup_path)
    except Exception:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            logger.exception('Could not clean temporary report archive: %s', temp)
        raise
    rel_path = backup_path.relative_to(Path(current_app.instance_path)).as_posix()
    backup_row = ReportArchiveBackup(
        report_year=year, backup_token=token, relative_path=rel_path,
        file_sha256=_file_sha256(backup_path), document_set_sha256=document_set_hash,
        created_by_user_id=current_user.id,
    )
    db.session.add(backup_row)
    db.session.commit()
    tokens = dict(session.get('report_archive_backup_tokens', {}))
    tokens[str(year)] = token
    session['report_archive_backup_tokens'] = tokens
    response = send_file(backup_path, mimetype='application/zip', as_attachment=True,
                         download_name=f'Отчёты-направлений-{year}.zip', max_age=0)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@admin_bp.post('/report-archive/year/<int:year>/delete')
@archive_year_admin_required
def report_archive_year_delete(current_user, year):
    """Delete a year's general direction reports only after a verified ZIP exists."""
    token = request.form.get('backup_token', '')
    backup = ReportArchiveBackup.query.filter_by(
        report_year=year, backup_token=token, created_by_user_id=current_user.id
    ).first()
    if not backup:
        abort(409, description='Сначала сформируйте ZIP-архив этого года.')
    backup_path = (Path(current_app.instance_path) / backup.relative_path).resolve()
    backup_root = (Path(current_app.instance_path) / 'report_archive_backups').resolve()
    if not backup_path.is_relative_to(backup_root) or not backup_path.is_file():
        abort(409, description='Предварительный ZIP не найден.')
    if _file_sha256(backup_path) != backup.file_sha256:
        abort(409, description='Контрольная сумма предварительного ZIP не совпадает.')
    docs = ReportArchiveDocument.query.filter_by(report_year=year, report_type='direction').filter(
        ReportArchiveDocument.signature_code.isnot(None)
    ).order_by(ReportArchiveDocument.id.asc()).all()
    current_document_set = [
        {'id': row.id, 'relative_path': row.relative_path, 'sha256': row.file_sha256,
         'signature_code': row.signature_code, 'month': row.report_month}
        for row in docs
    ]
    current_document_set_hash = hashlib.sha256(json.dumps(
        current_document_set, ensure_ascii=False, sort_keys=True, separators=(',', ':')
    ).encode('utf-8')).hexdigest()
    if current_document_set_hash != backup.document_set_sha256:
        abort(409, description='После создания ZIP состав отчётов изменился. Сформируйте новый ZIP перед удалением.')
    files_to_delete = []
    for document in docs:
        path = _report_archive_file(document)
        if _file_sha256(path) != document.file_sha256:
            abort(409, description=f'Файл отчёта изменён после архивации: {document.filename}')
        files_to_delete.append(path)
        ReportArchiveDocumentDirection.query.filter_by(document_id=document.id).delete(synchronize_session=False)
        db.session.delete(document)
    # Commit the index changes before removing files. A database rollback must
    # never leave live archive rows pointing at PDFs already unlinked on disk.
    db.session.commit()
    for path in files_to_delete:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.exception('Could not remove archived direction PDF after year deletion: %s', path)
    tokens = dict(session.get('report_archive_backup_tokens', {}))
    tokens.pop(str(year), None)
    session['report_archive_backup_tokens'] = tokens
    flash(f'Общие отчёты направлений за {year} год удалены. Резервный ZIP сохранён.', 'success')
    return redirect(url_for('admin.report_archive', year=year))


@admin_bp.get('/analytics-report.pdf')
@super_admin_required
def analytics_report_pdf(current_user):
    """Signed whole-site analytics PDF, built from compact aggregate queries."""
    from database import BotJournalEvent, QuotaDirection
    from services.report_pdfs import build_analytics_report_pdf

    attendance_rows = (db.session.query(DayParticipation.status, func.count(DayParticipation.id))
        .group_by(DayParticipation.status).all())
    attendance = {str(status or 'unknown'): int(count or 0) for status, count in attendance_rows}
    decline_count = EventQuotaDecline.query.count()
    application_rows = (db.session.query(ApplicationDecision.decision, func.count(ApplicationDecision.id))
        .group_by(ApplicationDecision.decision).all())
    application_decisions = {str(status or 'unknown'): int(count or 0) for status, count in application_rows}

    # One grouped query per data domain avoids building a full direction report
    # for every direction merely to populate the site-wide analytics summary.
    direction_rows = (db.session.query(
        Direction.id, Direction.name,
        func.count(student_directions.c.student_id).label('students')
    ).outerjoin(student_directions, student_directions.c.direction_id == Direction.id)
     .group_by(Direction.id, Direction.name).order_by(Direction.name.asc()).all())
    event_links = QuotaDirection.query.with_entities(
        QuotaDirection.quota_id, QuotaDirection.direction_id
    ).all()
    event_counts = {}
    directions_by_event = {}
    for quota_id, direction_id in event_links:
        event_counts[direction_id] = event_counts.get(direction_id, 0) + 1
        directions_by_event.setdefault(quota_id, set()).add(direction_id)
    activity_groups = (db.session.query(
        StudentActivity.direction_id, StudentActivity.quota_id, func.count(StudentActivity.id)
    ).group_by(StudentActivity.direction_id, StudentActivity.quota_id).all())
    action_counts = {}
    for activity_direction_id, quota_id, action_total in activity_groups:
        action_total = int(action_total or 0)
        if activity_direction_id is not None:
            action_counts[activity_direction_id] = action_counts.get(activity_direction_id, 0) + action_total
        for linked_direction_id in directions_by_event.get(quota_id, ()):
            if linked_direction_id != activity_direction_id:
                action_counts[linked_direction_id] = action_counts.get(linked_direction_id, 0) + action_total
    direction_attendance_rows = (db.session.query(
        QuotaDirection.direction_id,
        func.sum(sa_case((DayParticipation.status == 'attended', 1), else_=0)),
    ).join(EventDay, EventDay.quota_id == QuotaDirection.quota_id)
     .join(DayParticipation, DayParticipation.day_id == EventDay.id)
     .group_by(QuotaDirection.direction_id).all())
    visits_by_direction = {direction_id: int(count or 0) for direction_id, count in direction_attendance_rows}
    direction_decline_rows = (db.session.query(
        QuotaDirection.direction_id, func.count(EventQuotaDecline.id)
    ).join(EventQuotaDecline, EventQuotaDecline.quota_id == QuotaDirection.quota_id)
     .group_by(QuotaDirection.direction_id).all())
    declines_by_direction = {direction_id: int(count or 0) for direction_id, count in direction_decline_rows}
    direction_summary = [{
        'name': name, 'students': int(students or 0),
        'actions': int(action_counts.get(direction_id, 0) or 0),
        'events': int(event_counts.get(direction_id, 0) or 0),
        'visits': int(visits_by_direction.get(direction_id, 0) or 0),
        'declines': int(declines_by_direction.get(direction_id, 0) or 0),
    } for direction_id, name, students in direction_rows]
    data = {
        'generated_at': _report_time(datetime.utcnow()),
        'totals': {
            'directions': Direction.query.count(), 'students': Student.query.filter_by(council_registered=True).count(),
            'events': EventQuota.query.count(), 'lessons': Lesson.query.count(),
            'activities': StudentActivity.query.count(),
            'staff_actions': HttpAuditLog.query.filter(
                HttpAuditLog.actor_user_id.isnot(None),
                HttpAuditLog.actor_role.in_(STAFF_AUDIT_ROLES),
            ).count(),
            'bot_business_actions': StudentActivity.query.filter(
                StudentActivity.action.in_(tuple(BOT_MONITOR_ACTION_LABELS.keys()))
            ).count(),
            'bot_system_events': BotJournalEvent.query.count(), 'declines': decline_count,
            'signed_reports': AdminReportSignature.query.count(),
        },
        'attendance': attendance, 'application_decisions': application_decisions,
        'directions': direction_summary,
    }
    return _create_signed_report_response(
        current_user=current_user, report_type='site_analytics', report_key='site-analytics',
        report_title='Общая аналитика сайта', report_data=data,
        pdf_builder=build_analytics_report_pdf, filename='site-analytics-report.pdf',
    )


@admin_bp.get('/bot-actions-report.pdf')
@super_admin_required
def bot_actions_report_pdf(current_user):
    """Signed report combining bot business actions and bot transport journal."""
    from database import BotJournalEvent
    from services.report_pdfs import build_bot_journal_pdf

    action_keys = tuple(BOT_MONITOR_ACTION_LABELS.keys())
    activity_query = StudentActivity.query.filter(StudentActivity.action.in_(action_keys))
    business_action_total = activity_query.count()
    activity_rows = list(reversed(activity_query.order_by(
        StudentActivity.created_at.desc(), StudentActivity.id.desc()
    ).limit(10000).all()))
    student_ids = sorted({row.student_id for row in activity_rows if row.student_id is not None})
    direction_ids = sorted({row.direction_id for row in activity_rows if row.direction_id is not None})
    quota_ids = sorted({row.quota_id for row in activity_rows if row.quota_id is not None})
    students = {row.id: row for row in Student.query.filter(Student.id.in_(student_ids)).all()} if student_ids else {}
    directions = {row.id: row for row in Direction.query.filter(Direction.id.in_(direction_ids)).all()} if direction_ids else {}
    quotas = {row.id: row for row in EventQuota.query.filter(EventQuota.id.in_(quota_ids)).all()} if quota_ids else {}
    entries = []
    for row in activity_rows:
        entries.append({
            'created_at': _report_time(row.created_at), 'source': 'Бизнес-действие бота',
            'platform': 'Telegram / Web App / сайт',
            'actor': (students[row.student_id].full_name if row.student_id in students else 'Пользователь бота'),
            'action': BOT_MONITOR_ACTION_LABELS.get(row.action, (row.action, ''))[0],
            'object': (directions[row.direction_id].name if row.direction_id in directions else '')
                      or (quotas[row.quota_id].event_title if row.quota_id in quotas else '—'),
            'status': 'Зафиксировано', 'duration_ms': '—',
            'description': _safe_bot_activity_description(row.action),
            '_sort_at': row.created_at or datetime.min,
        })
    system_event_total = BotJournalEvent.query.count()
    journal_rows = list(reversed(BotJournalEvent.query.order_by(
        BotJournalEvent.created_at.desc(), BotJournalEvent.id.desc()
    ).limit(10000).all()))
    for row in journal_rows:
        entries.append({
            'created_at': _report_time(row.created_at), 'source': 'Журнал доставки / интеграции',
            'platform': (row.platform or '—').upper(), 'actor': row.actor_alias or 'Системный бот',
            'action': f'{row.kind or "event"}: {row.action or "—"}',
            'object': 'Интеграция бота', 'status': row.status or '—',
            'duration_ms': row.duration_ms if row.duration_ms is not None else '—',
            'description': row.summary or 'Техническое событие; содержимое сообщений не включено.',
            '_sort_at': row.created_at or datetime.min,
        })
    entries.sort(key=lambda item: item['_sort_at'])
    for entry in entries:
        entry.pop('_sort_at', None)
    data = {
        'total': business_action_total + system_event_total,
        'business_actions': business_action_total, 'system_events': system_event_total,
        'entries': entries,
        'filter_summary': ('Полная история бизнес-действий ботов и технических событий Telegram / VK / MAX. '
                           'Тексты личных причин и содержимое сообщений не включены. '
                           + ("Показаны последние 10 000 записей каждого типа." if business_action_total > 10000 or system_event_total > 10000 else "Включены все записи.")),
    }
    stamp = datetime.utcnow().strftime('%Y%m%d-%H%M%S')
    return _create_signed_report_response(
        current_user=current_user, report_type='bot_journal', report_key=f'bot-journal:{stamp}',
        report_title='Журнал действий ботов', report_data=data,
        pdf_builder=build_bot_journal_pdf, filename=f'bot-action-journal-{stamp}.pdf',
    )


@admin_bp.route('/user-activity')
@super_admin_required
def user_activity_log(current_user):
    """Show what registered web accounts actually request and do on the site.

    The page is deliberately based only on authenticated HttpAuditLog rows.
    StudentActivity and bot journals are separate business/transport histories:
    they can describe actions performed by a staff member on a student and must
    never be attributed to the student as the actor here. request bodies, form
    contents, passwords, tokens and URL query strings are never displayed.
    """
    query, filters = _registered_user_activity_query(request.args)
    try:
        page = max(1, min(int(request.args.get('page', 1)), 100000))
    except (TypeError, ValueError):
        page = 1
    page_size = 40
    selected_count = query.count()
    pages = max(1, (selected_count + page_size - 1) // page_size)
    page = min(page, pages)
    selected_accounts = query.with_entities(func.count(func.distinct(HttpAuditLog.actor_user_id))).scalar() or 0
    selected_views = query.filter(HttpAuditLog.method == 'GET').count()
    selected_changes = query.filter(HttpAuditLog.method.in_(('POST', 'PUT', 'PATCH', 'DELETE'))).count()
    rows = (query.order_by(HttpAuditLog.created_at.desc(), HttpAuditLog.id.desc())
            .offset((page - 1) * page_size).limit(page_size).all())

    account_ids = sorted({row.actor_user_id for row in rows if row.actor_user_id is not None})
    account_map = {}
    if account_ids:
        try:
            account_map = {user.id: user for user in User.query.filter(User.id.in_(account_ids)).all()}
        except Exception:
            logger.warning('Could not enrich registered-user activity with account profiles', exc_info=True)

    role_labels = {
        'super_admin': 'Главный администратор',
        'admin': 'Администратор',
        'staff': 'Сотрудник',
        'leader': 'Руководитель',
        'observer': 'Наблюдатель',
    }
    for row in rows:
        user = account_map.get(row.actor_user_id)
        row.account_name = (getattr(user, 'full_name', None) or getattr(user, 'email', None)
                            or row.actor_login or f'Аккаунт #{row.actor_user_id}')
        row.account_login = row.actor_login or getattr(user, 'email', None) or 'Логин не сохранён'
        row.account_state = ('Активен' if user.is_active else 'Отключён') if user else 'Аккаунт удалён или недоступен'
        row.role_label = role_labels.get(row.actor_role, row.actor_role or '—')
        row.section_key = _registered_user_activity_section(row)
        row.section_label = USER_ACTIVITY_SECTION_LABELS[row.section_key]
        row.subcategory_label = _registered_user_activity_subcategory(row)
        row.action_label = _registered_user_activity_description(row)

    return render_template(
        'activity/user_activity.html', rows=rows, filters=filters,
        page=page, pages=pages, page_size=page_size,
        selected_count=selected_count, selected_accounts=selected_accounts,
        selected_views=selected_views, selected_changes=selected_changes,
        section_labels=USER_ACTIVITY_SECTION_LABELS,
    )


@admin_bp.get('/user-activity/export.csv')
@super_admin_required
def user_activity_export(current_user):
    """Export registered-account request history using the on-screen filters."""
    import csv
    import io
    from flask import Response

    query, _filters = _registered_user_activity_query(request.args)
    account_ids = sorted({row[0] for row in query.with_entities(HttpAuditLog.actor_user_id).distinct().limit(10000).all()
                          if row[0] is not None})
    account_map = {}
    for offset in range(0, len(account_ids), 500):
        batch = account_ids[offset:offset + 500]
        if batch:
            account_map.update({user.id: user for user in User.query.filter(User.id.in_(batch)).all()})
    out = io.StringIO(newline='')
    writer = csv.writer(out)
    writer.writerow(('ID записи', 'Дата UTC', 'ID аккаунта', 'Пользователь', 'Логин', 'Роль',
                     'Раздел', 'Подкатегория', 'Что сделал'))

    def spreadsheet_safe(value):
        result = str(value if value is not None else '')
        return "'" + result if result.lstrip().startswith(('=', '+', '-', '@')) else result

    for row in query.order_by(HttpAuditLog.created_at.desc(), HttpAuditLog.id.desc()).limit(10000).yield_per(500):
        user = account_map.get(row.actor_user_id)
        display = getattr(user, 'full_name', None) or getattr(user, 'email', None) or row.actor_login or ''
        section = USER_ACTIVITY_SECTION_LABELS[_registered_user_activity_section(row)]
        description = _registered_user_activity_description(row)
        writer.writerow(map(spreadsheet_safe, (
            f'U-{row.id}', row.created_at.isoformat(' ') if row.created_at else '',
            row.actor_user_id, display, row.actor_login or '', row.actor_role or '',
            section, _registered_user_activity_subcategory(row), description,
        )))
    response = Response('\ufeff' + out.getvalue(), mimetype='text/csv; charset=utf-8')
    response.headers['Content-Disposition'] = 'attachment; filename="registered-user-activity.csv"'
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@admin_bp.get('/user-activity/export.pdf')
@super_admin_required
def user_activity_pdf(current_user):
    """Export the complete filtered staff action journal as a signed PDF."""
    from services.report_pdfs import build_staff_journal_pdf

    query, filters = _registered_user_activity_query(request.args)
    total = query.count()
    rows = list(reversed(query.order_by(HttpAuditLog.created_at.desc(), HttpAuditLog.id.desc()).limit(10000).all()))
    account_ids = sorted({row.actor_user_id for row in rows if row.actor_user_id is not None})
    account_map = {}
    for offset in range(0, len(account_ids), 500):
        batch = account_ids[offset:offset + 500]
        if batch:
            account_map.update({user.id: user for user in User.query.filter(User.id.in_(batch)).all()})

    role_labels = {
        'super_admin': 'Главный администратор',
        'admin': 'Администратор',
        'staff': 'Сотрудник',
        'leader': 'Руководитель',
        'observer': 'Наблюдатель',
    }
    entries = []
    for row in rows:
        user = account_map.get(row.actor_user_id)
        account_name = (getattr(user, 'full_name', None) or getattr(user, 'email', None)
                        or row.actor_login or f'Аккаунт #{row.actor_user_id}')
        login = row.actor_login or getattr(user, 'email', None) or 'Логин не сохранён'
        role = role_labels.get(row.actor_role, row.actor_role or '—')
        entries.append({
            'created_at': row.created_at.strftime('%d.%m.%Y %H:%M:%S') if row.created_at else '—',
            'account': f'{account_name}\n{login}\n{role}',
            'action': _registered_user_activity_description(row),
            'section': (USER_ACTIVITY_SECTION_LABELS[_registered_user_activity_section(row)]
                        + ' / ' + _registered_user_activity_subcategory(row)),
        })

    filter_parts = []
    if filters.get('q'):
        filter_parts.append(f"Поиск: {filters['q']}")
    if filters.get('section') != 'all':
        filter_parts.append(f"Раздел: {USER_ACTIVITY_SECTION_LABELS.get(filters['section'], filters['section'])}")
    if filters.get('role'):
        filter_parts.append(f"Роль: {role_labels.get(filters['role'], filters['role'])}")
    if filters.get('actor'):
        filter_parts.append(f"Сотрудник: {filters['actor']}")
    if filters.get('method'):
        filter_parts.append(f"Тип операции: {filters['method']}")
    if filters.get('level') and filters['level'] != 'all':
        filter_parts.append(f"Состояние: {filters['level']}")
    if filters.get('start'):
        filter_parts.append(f"Дата от (UTC): {filters['start']}")
    if filters.get('end'):
        filter_parts.append(f"Дата до (UTC): {filters['end']}")

    report_data = {
        'total': total,
        'entries': entries,
        'filters': filters,
        'filter_summary': (('; '.join(filter_parts) if filter_parts else 'Все изменения и операции авторизованных аккаунтов; просмотры GET по умолчанию не включены.')
                           + (f' Показаны последние 10 000 из {total} записей.' if total > 10000 else f' Записей в выборке: {total}.')),
    }
    stamp = datetime.utcnow().strftime('%Y%m%d-%H%M%S')
    return _create_signed_report_response(
        current_user=current_user, report_type='staff_journal', report_key=f'staff-journal:{stamp}',
        report_title='Журнал действий сотрудников', report_data=report_data,
        pdf_builder=build_staff_journal_pdf, filename=f'staff-action-journal-{stamp}.pdf',
    )


@admin_bp.route("/activity")
@super_admin_required
def activity_log(current_user):
    """Legacy activity URL: keep the old endpoint closed and redirect to the scoped ledger.

    The previous page exposed raw StudentActivity descriptions to every authenticated
    account. Those descriptions may contain personal explanations entered by users.
    The consolidated bot journal now renders only approved business-event labels.
    """
    return redirect(url_for('admin.messenger_monitoring') + '#bot-actions')

BOT_ACTIVITY_ACTION_LABELS = {
    "bot_profile_created": "Регистрация профиля в боте",
    "bot_application_submitted": "Заявка в направление",
    "bot_application_approved": "Принятие и активация участника",
    "bot_application_rejected": "Отклонение заявки с причиной и блокировкой",
    "bot_application_withdrawn": "Отзыв заявления",
    "application_block_cleared": "Главный администратор снял блокировку заявления",
    "application_block_auto_expired": "Автоматическое снятие блокировки по сроку",
    "application_block_clear_notice_sent": "Уведомление о снятии блокировки доставлено",
    "application_block_clear_notice_failed": "Не удалось доставить уведомление о снятии блокировки",
    "application_block_updated": "Главный администратор изменил срок блокировки",
    "application_block_added_by_admin": "Администратор добавил блокировку",
    "application_block_notice_sent": "Уведомление о блокировке доставлено",
    "application_block_notice_failed": "Не удалось доставить уведомление о блокировке",
    "bot_event_registered": "Запись на мероприятие",
    "bot_quota_declined": "Отказ от мероприятия",
    "bot_quota_decline_reversed": "Возврат к мероприятию",
}
BOT_ACTIVITY_CATEGORIES = {
    "registrations": {
        "title": "Регистрации",
        "subtitle": "Профили, созданные пользователями непосредственно в Telegram-боте.",
        "actions": ("bot_profile_created",),
        "endpoint": "admin.bot_activity_registrations",
    },
    "applications": {
        "title": "Заявления по направлениям",
        "subtitle": "Подача, принятие с немедленной активацией и отказ по заявлениям через Telegram, Web App и веб-сайт, включая причину и срок повторной подачи.",
        "actions": ("bot_application_submitted", "bot_application_approved", "bot_application_rejected", "bot_application_withdrawn", "application_block_cleared", "application_block_auto_expired", "application_block_clear_notice_sent", "application_block_clear_notice_failed", "application_block_updated", "application_block_added_by_admin", "application_block_notice_sent", "application_block_notice_failed"),
        "endpoint": "admin.bot_activity_applications",
    },
    "events": {
        "title": "Записи на квоты и мероприятия",
        "subtitle": "Записи на даты, отказы от мероприятий и возвраты к участию.",
        "actions": ("bot_event_registered", "bot_quota_declined", "bot_quota_decline_reversed"),
        "endpoint": "admin.bot_activity_events",
    },
    "history": {
        "title": "Полный журнал бота",
        "subtitle": "Журнал действий Telegram-бота и решений по заявлениям из Telegram, Web App и веб-сайта.",
        "actions": tuple(BOT_ACTIVITY_ACTION_LABELS.keys()),
        "endpoint": "admin.bot_activity_history",
    },
}

@admin_bp.route("/bot-activity")
@super_admin_required
def bot_activity(current_user):
    """Legacy endpoint redirects to the unified bot monitoring workspace."""
    return redirect(url_for('admin.messenger_monitoring') + '#bot-actions')
    action_keys = tuple(BOT_ACTIVITY_ACTION_LABELS.keys())
    registered_student_ids = [row[0] for row in Student.query.with_entities(Student.id).filter(
        Student.council_registered.is_(True)
    ).all()]
    registered_bot_activity = StudentActivity.query.filter(StudentActivity.student_id.in_(registered_student_ids))
    totals = {
        "registrations": registered_bot_activity.filter_by(action="bot_profile_created").count(),
        "applications": registered_bot_activity.filter_by(action="bot_application_submitted").count(),
        "event_signups": registered_bot_activity.filter_by(action="bot_event_registered").count(),
        "declines": registered_bot_activity.filter_by(action="bot_quota_declined").count(),
        "all_actions": registered_bot_activity.filter(StudentActivity.action.in_(action_keys)).count(),
    }

    active_application_statuses = [
        DirectionStatus.PENDING.value, DirectionStatus.INTERVIEW.value,
        DirectionStatus.ACTIVE.value,
    ]
    direction_rows = (db.session.query(
            student_directions.c.direction_id, func.count(student_directions.c.student_id)
        ).join(Student, Student.id == student_directions.c.student_id)
        .filter(Student.council_registered.is_(True),
                student_directions.c.status.in_(active_application_statuses))
        .group_by(student_directions.c.direction_id)
        .order_by(func.count(student_directions.c.student_id).desc()).limit(6).all())
    quota_rows = (db.session.query(EventDay.quota_id, func.count(DayParticipation.id))
        .join(DayParticipation, DayParticipation.day_id == EventDay.id)
        .filter(DayParticipation.student_id.in_(registered_student_ids),
                DayParticipation.status != "cancelled")
        .group_by(EventDay.quota_id)
        .order_by(func.count(DayParticipation.id).desc()).limit(6).all())
    summary_direction_ids = {did for did, _count in direction_rows}
    summary_quota_ids = {qid for qid, _count in quota_rows}
    summary_directions = {obj.id: obj for obj in Direction.query.filter(Direction.id.in_(summary_direction_ids)).all()} if summary_direction_ids else {}
    summary_quotas = {obj.id: obj for obj in EventQuota.query.filter(EventQuota.id.in_(summary_quota_ids)).all()} if summary_quota_ids else {}
    top_directions = [{"name": summary_directions[did].name if did in summary_directions else "Удалённое направление", "count": count} for did, count in direction_rows]
    top_quotas = [{"name": summary_quotas[qid].event_title if qid in summary_quotas else "Удалённое мероприятие", "count": count} for qid, count in quota_rows]
    return render_template("activity/bot_activity.html", totals=totals,
                           top_directions=top_directions, top_quotas=top_quotas)


@admin_bp.route("/bot-activity/live-summary")
@super_admin_required
def bot_activity_live_summary(current_user):
    """Admin-only polling endpoint for overview counts and current rankings."""
    action_keys = tuple(BOT_ACTIVITY_ACTION_LABELS.keys())
    registered_student_ids = [row[0] for row in Student.query.with_entities(Student.id).filter(
        Student.council_registered.is_(True)
    ).all()]
    registered_bot_activity = StudentActivity.query.filter(StudentActivity.student_id.in_(registered_student_ids))
    totals = {
        "registrations": registered_bot_activity.filter_by(action="bot_profile_created").count(),
        "applications": registered_bot_activity.filter_by(action="bot_application_submitted").count(),
        "event_signups": registered_bot_activity.filter_by(action="bot_event_registered").count(),
        "declines": registered_bot_activity.filter_by(action="bot_quota_declined").count(),
        "all_actions": registered_bot_activity.filter(StudentActivity.action.in_(action_keys)).count(),
    }
    active_statuses = [DirectionStatus.PENDING.value, DirectionStatus.INTERVIEW.value,
                       DirectionStatus.ACTIVE.value]
    direction_rows = (db.session.query(student_directions.c.direction_id,
                                       func.count(student_directions.c.student_id))
        .join(Student, Student.id == student_directions.c.student_id)
        .filter(Student.council_registered.is_(True),
                student_directions.c.status.in_(active_statuses))
        .group_by(student_directions.c.direction_id)
        .order_by(func.count(student_directions.c.student_id).desc()).limit(6).all())
    quota_rows = (db.session.query(EventDay.quota_id, func.count(DayParticipation.id))
        .join(DayParticipation, DayParticipation.day_id == EventDay.id)
        .filter(DayParticipation.student_id.in_(registered_student_ids),
                DayParticipation.status != "cancelled")
        .group_by(EventDay.quota_id)
        .order_by(func.count(DayParticipation.id).desc()).limit(6).all())
    direction_ids = {did for did, _count in direction_rows}
    quota_ids = {qid for qid, _count in quota_rows}
    directions = {obj.id: obj for obj in Direction.query.filter(Direction.id.in_(direction_ids)).all()} if direction_ids else {}
    quotas = {obj.id: obj for obj in EventQuota.query.filter(EventQuota.id.in_(quota_ids)).all()} if quota_ids else {}
    response = jsonify({
        "ok": True,
        "totals": totals,
        "top_directions": [{"name": directions[did].name if did in directions else "Удалённое направление", "count": count}
                           for did, count in direction_rows],
        "top_quotas": [{"name": quotas[qid].event_title if qid in quotas else "Удалённое мероприятие", "count": count}
                       for qid, count in quota_rows],
    })
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return response


@admin_bp.route("/bot-activity/live/<category_key>")
@super_admin_required
def bot_activity_live(category_key, current_user):
    """Return new log events since a cursor. Endpoint is super-admin-only."""
    if category_key not in BOT_ACTIVITY_CATEGORIES:
        abort(404)
    action_keys = BOT_ACTIVITY_CATEGORIES[category_key]["actions"]
    try:
        after_id = max(0, int(request.args.get("after_id", "0")))
    except (TypeError, ValueError):
        after_id = 0

    registered_student_ids = [row[0] for row in Student.query.with_entities(Student.id).filter(
        Student.council_registered.is_(True)
    ).all()]
    registered_activity = StudentActivity.query.filter(
        StudentActivity.student_id.in_(registered_student_ids), StudentActivity.action.in_(action_keys)
    )
    latest_id = registered_activity.with_entities(func.max(StudentActivity.id)).scalar() or 0
    query = registered_activity.filter(StudentActivity.id > after_id)
    selected_action = request.args.get("action", "").strip()
    if selected_action in action_keys:
        query = query.filter(StudentActivity.action == selected_action)
    start_value = request.args.get("start", "").strip()
    end_value = request.args.get("end", "").strip()
    if start_value:
        try:
            query = query.filter(StudentActivity.created_at >= datetime.strptime(start_value, "%Y-%m-%d"))
        except ValueError:
            pass
    if end_value:
        try:
            query = query.filter(StudentActivity.created_at < datetime.strptime(end_value, "%Y-%m-%d") + timedelta(days=1))
        except ValueError:
            pass
    search = request.args.get("q", "").strip()[:120]
    if search:
        pattern = f"%{search}%"
        search_parts = [StudentActivity.description.ilike(pattern)]
        matching_student_ids = [row[0] for row in Student.query.with_entities(Student.id).filter(or_(
            Student.full_name.ilike(pattern), Student.group.ilike(pattern), Student.phone.ilike(pattern)
        )).all()]
        matching_direction_ids = [row[0] for row in Direction.query.with_entities(Direction.id).filter(Direction.name.ilike(pattern)).all()]
        matching_quota_ids = [row[0] for row in EventQuota.query.with_entities(EventQuota.id).filter(EventQuota.event_title.ilike(pattern)).all()]
        if matching_student_ids:
            search_parts.append(StudentActivity.student_id.in_(matching_student_ids))
        if matching_direction_ids:
            search_parts.append(StudentActivity.direction_id.in_(matching_direction_ids))
        if matching_quota_ids:
            search_parts.append(StudentActivity.quota_id.in_(matching_quota_ids))
        query = query.filter(or_(*search_parts))

    rows = query.order_by(StudentActivity.id.asc()).limit(50).all()
    student_ids = {row.student_id for row in rows if row.student_id}
    direction_ids = {row.direction_id for row in rows if row.direction_id}
    quota_ids = {row.quota_id for row in rows if row.quota_id}
    students = {obj.id: obj for obj in Student.query.filter(Student.id.in_(student_ids)).all()} if student_ids else {}
    directions = {obj.id: obj for obj in Direction.query.filter(Direction.id.in_(direction_ids)).all()} if direction_ids else {}
    quotas = {obj.id: obj for obj in EventQuota.query.filter(EventQuota.id.in_(quota_ids)).all()} if quota_ids else {}
    events = []
    for row in rows:
        student = students.get(row.student_id)
        direction = directions.get(row.direction_id)
        quota = quotas.get(row.quota_id)
        events.append({
            "id": row.id,
            "timestamp": row.created_at.strftime("%d.%m.%Y %H:%M:%S") if row.created_at else "—",
            "action": row.action,
            "action_label": BOT_ACTIVITY_ACTION_LABELS.get(row.action, row.action),
            "student": student.full_name if student else "",
            "group": (student.group or "Группа не указана") if student else "",
            "direction": direction.name if direction else "",
            "direction_icon": (direction.icon or "◈") if direction else "◈",
            "quota": quota.event_title if quota else "",
            "description": _safe_bot_activity_description(row.action),
        })
    # If the response hit the batch cap, continue from the last delivered row;
    # otherwise advance over any non-matching events as well.
    cursor = rows[-1].id if len(rows) >= 50 else max(int(latest_id), after_id)
    response = jsonify({"ok": True, "events": events, "cursor": cursor})
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return response


def _render_bot_activity_table(category_key):
    category = BOT_ACTIVITY_CATEGORIES[category_key]
    action_keys = category["actions"]
    search = request.args.get("q", "").strip()[:120]
    start_value = request.args.get("start", "").strip()
    end_value = request.args.get("end", "").strip()
    selected_action = request.args.get("action", "").strip()

    registered_student_ids = [row[0] for row in Student.query.with_entities(Student.id).filter(
        Student.council_registered.is_(True)
    ).all()]
    query = StudentActivity.query.filter(
        StudentActivity.student_id.in_(registered_student_ids), StudentActivity.action.in_(action_keys)
    )
    if selected_action in action_keys:
        query = query.filter(StudentActivity.action == selected_action)
    else:
        selected_action = ""

    start_dt = None
    if start_value:
        try:
            start_dt = datetime.strptime(start_value, "%Y-%m-%d")
            query = query.filter(StudentActivity.created_at >= start_dt)
        except ValueError:
            start_value = ""
    if end_value:
        try:
            # Inclusive date in the UI; exclusive bound keeps the query index-friendly.
            end_dt = datetime.strptime(end_value, "%Y-%m-%d") + timedelta(days=1)
            query = query.filter(StudentActivity.created_at < end_dt)
        except ValueError:
            end_value = ""

    if search:
        # Search only approved metadata; never search arbitrary user-entered
        # activity descriptions or contact details from this legacy helper.
        pattern = f"%{search}%"
        search_parts = []
        matching_student_ids = [row[0] for row in Student.query.with_entities(Student.id).filter(or_(
            Student.full_name.ilike(pattern), Student.group.ilike(pattern)
        )).all()]
        matching_direction_ids = [row[0] for row in Direction.query.with_entities(Direction.id).filter(Direction.name.ilike(pattern)).all()]
        matching_quota_ids = [row[0] for row in EventQuota.query.with_entities(EventQuota.id).filter(EventQuota.event_title.ilike(pattern)).all()]
        if matching_student_ids:
            search_parts.append(StudentActivity.student_id.in_(matching_student_ids))
        if matching_direction_ids:
            search_parts.append(StudentActivity.direction_id.in_(matching_direction_ids))
        if matching_quota_ids:
            search_parts.append(StudentActivity.quota_id.in_(matching_quota_ids))
        query = query.filter(or_(*search_parts) if search_parts else false())

    filtered_total = query.count()
    per_page = 40
    try:
        page = max(1, int(request.args.get("page", "1")))
    except (TypeError, ValueError):
        page = 1
    pages = max(1, (filtered_total + per_page - 1) // per_page)
    page = min(page, pages)
    rows = query.order_by(StudentActivity.created_at.desc(), StudentActivity.id.desc()).offset((page - 1) * per_page).limit(per_page).all()

    student_ids = {row.student_id for row in rows if row.student_id}
    direction_ids = {row.direction_id for row in rows if row.direction_id}
    quota_ids = {row.quota_id for row in rows if row.quota_id}
    students = {obj.id: obj for obj in Student.query.filter(Student.id.in_(student_ids)).all()} if student_ids else {}
    directions = {obj.id: obj for obj in Direction.query.filter(Direction.id.in_(direction_ids)).all()} if direction_ids else {}
    quotas = {obj.id: obj for obj in EventQuota.query.filter(EventQuota.id.in_(quota_ids)).all()} if quota_ids else {}
    items = [{
        "activity": row,
        "action_label": BOT_ACTIVITY_ACTION_LABELS.get(row.action, row.action),
        "safe_description": _safe_bot_activity_description(row.action),
        "student": students.get(row.student_id),
        "direction": directions.get(row.direction_id),
        "quota": quotas.get(row.quota_id),
    } for row in rows]
    latest_id = query.with_entities(func.max(StudentActivity.id)).scalar() or 0
    return render_template(
        "activity/bot_activity_table.html", category=category, category_key=category_key,
        items=items, action_labels=BOT_ACTIVITY_ACTION_LABELS,
        action_options=[(key, BOT_ACTIVITY_ACTION_LABELS[key]) for key in action_keys],
        total=filtered_total, page=page, pages=pages, search=search,
        start_value=start_value, end_value=end_value, selected_action=selected_action,
        latest_id=latest_id,
    )

@admin_bp.route("/bot-activity/registrations")
@super_admin_required
def bot_activity_registrations(current_user):
    return redirect(url_for('admin.messenger_monitoring') + '#bot-actions')
    return _render_bot_activity_table("registrations")

@admin_bp.route("/bot-activity/applications")
@super_admin_required
def bot_activity_applications(current_user):
    return redirect(url_for('admin.messenger_monitoring') + '#bot-actions')
    return _render_bot_activity_table("applications")

@admin_bp.route("/bot-activity/events")
@super_admin_required
def bot_activity_events(current_user):
    return redirect(url_for('admin.messenger_monitoring') + '#bot-actions')
    return _render_bot_activity_table("events")

@admin_bp.route("/bot-activity/history")
@super_admin_required
def bot_activity_history(current_user):
    return redirect(url_for('admin.messenger_monitoring') + '#bot-actions')
    return _render_bot_activity_table("history")

@admin_bp.route("/blocked-students")
@login_required
def blocked_students(current_user):
    """All authenticated website users can view active application blocks."""
    process_expired_application_blocks(limit=2)
    now = datetime.utcnow()
    latest_ids = db.session.query(
        ApplicationDecision.student_id.label("student_id"),
        ApplicationDecision.direction_id.label("direction_id"),
        func.max(ApplicationDecision.id).label("latest_id"),
    ).group_by(ApplicationDecision.student_id, ApplicationDecision.direction_id).subquery()
    rows_query = ApplicationDecision.query.join(
        latest_ids, ApplicationDecision.id == latest_ids.c.latest_id
    ).filter(
        ApplicationDecision.decision == DirectionStatus.REJECTED.value,
        ApplicationDecision.blocked_until.is_not(None),
        ApplicationDecision.blocked_until > now,
        ApplicationDecision.cleared_at.is_(None),
    )
    if current_user.role == UserRole.STAFF.value:
        from services.staff_access import direction_ids as staff_direction_ids
        scoped_direction_ids = set(staff_direction_ids(current_user, 'students', 'view'))
        rows_query = rows_query.filter(ApplicationDecision.direction_id.in_(scoped_direction_ids)) if scoped_direction_ids else rows_query.filter(ApplicationDecision.id == -1)
    rows = rows_query.order_by(ApplicationDecision.blocked_until.asc()).all()
    student_ids = {row.student_id for row in rows}
    direction_ids = {row.direction_id for row in rows}
    students = {x.id: x for x in Student.query.filter(Student.id.in_(student_ids)).all()} if student_ids else {}
    directions = {x.id: x for x in Direction.query.filter(Direction.id.in_(direction_ids)).all()} if direction_ids else {}
    items = [{"decision": row, "student": students.get(row.student_id), "direction": directions.get(row.direction_id)} for row in rows]
    can_edit = current_user.role == UserRole.SUPER_ADMIN.value
    block_students = []  # Search results are loaded on demand for large student cohorts.
    block_directions = Direction.query.order_by(Direction.name.asc()).all() if can_edit else []
    return render_template(
        "students/blocked.html", items=items, can_edit=can_edit,
        block_students=block_students, block_directions=block_directions,
    )


@admin_bp.route("/blocked-students/add", methods=["POST"])
@super_admin_required
def add_application_block(current_user):
    """Block a student from one direction or every direction available to their cohort."""
    student_id = request.form.get("student_id", type=int)
    direction_raw = str(request.form.get("direction_id") or "").strip()
    all_directions = direction_raw.casefold() in {"all", "*", "0"}
    direction_id = None if all_directions else (int(direction_raw) if direction_raw.isdigit() else None)
    try:
        days = int(str(request.form.get("days", "7") or "").strip())
    except (TypeError, ValueError):
        days = 0
    reason = " ".join(str(request.form.get("reason") or "").split())[:1000]
    if not student_id or (not all_directions and not direction_id):
        flash("Выберите студента и направление либо вариант «Все направления».", "danger")
        return redirect(url_for("admin.blocked_students"))
    if days < 1 or days > 3650:
        flash("Укажите срок блокировки от 1 до 3650 дней.", "danger")
        return redirect(url_for("admin.blocked_students"))
    if len(reason) < 5:
        flash("Укажите причину блокировки (не менее 5 символов).", "danger")
        return redirect(url_for("admin.blocked_students"))

    student = Student.query.get(student_id)
    if not student:
        flash("Студент не найден.", "danger")
        return redirect(url_for("admin.blocked_students"))
    if all_directions:
        targets = [d for d in Direction.query.order_by(Direction.name.asc()).all()
                   if d.available_for(student.education_type)]
    else:
        one = Direction.query.get(direction_id)
        targets = [one] if one and one.available_for(student.education_type) else []
    if not targets:
        flash("Для этого студента не найдено доступных направлений для блокировки.", "danger")
        return redirect(url_for("admin.blocked_students"))

    now = datetime.utcnow()
    blocked_until = now + timedelta(days=days)
    from services.applications import active_application_block
    added, already_blocked = [], []
    for direction in targets:
        current_block = active_application_block(student.id, direction.id, now=now)
        if current_block:
            # For a global block, extend any shorter existing restriction so no
            # direction reopens before the requested all-directions lock expires.
            if not (all_directions and current_block.blocked_until and current_block.blocked_until < blocked_until):
                already_blocked.append(direction.name)
                continue
        existing_link = db.session.execute(student_directions.select().where(
            (student_directions.c.student_id == student.id) &
            (student_directions.c.direction_id == direction.id)
        )).fetchone()
        if existing_link and existing_link.status in {DirectionStatus.PENDING.value, DirectionStatus.INTERVIEW.value}:
            db.session.execute(student_directions.update().where(
                (student_directions.c.student_id == student.id) &
                (student_directions.c.direction_id == direction.id)
            ).values(status=DirectionStatus.REJECTED.value))
        db.session.add(ApplicationDecision(
            student_id=student.id, direction_id=direction.id,
            decision=DirectionStatus.REJECTED.value, reason=reason, source="admin_manual",
            actor_user_id=current_user.id, created_at=now, blocked_until=blocked_until,
        ))
        record_activity(
            "application_block_added_by_admin",
            f'Главный администратор {current_user.email} заблокировал студента «{student.full_name}» '
            f'по направлению «{direction.name}» на {days} дн. до {blocked_until.strftime("%d.%m.%Y %H:%M")}. Причина: {reason}.',
            student_id=student.id, direction_id=direction.id,
        )
        added.append(direction.name)
    if not added:
        flash("По выбранным направлениям у студента уже действуют блокировки.", "warning")
        return redirect(url_for("admin.blocked_students"))
    db.session.commit()

    notification_sent = False
    notification_error = "У студента не указан Telegram ID."
    if student.tg_id and int(student.tg_id) > 0:
        scope_label = "всех доступных направлений" if all_directions else f'направления «{added[0]}»'
        directions_text = "\n".join(f"• {name}" for name in added) if all_directions else added[0]
        message = (
            "⛔ <b>Уведомление о блокировке</b>\n\n"
            f"Здравствуйте, {html.escape(student.full_name)}!\n"
            f"Главный администратор установил ограничение на {days} дн. для {html.escape(scope_label)}.\n\n"
            f"<b>Направления:</b>\n{html.escape(directions_text)}\n\n"
            f"<b>Причина:</b> {html.escape(reason)}\n"
            f"<b>Ограничение действует до:</b> {blocked_until.strftime('%d.%m.%Y в %H:%M')}\n\n"
            "При возникновении вопросов обратитесь к главному администратору."
        )
        notification_sent, notification_error = _send_tg_detailed(student.tg_id, message)

    record_activity(
        "application_block_notice_sent" if notification_sent else "application_block_notice_failed",
        (f'Уведомление о блокировке студенту «{student.full_name}» '
         f'{"по всем доступным направлениям" if all_directions else f"по направлению «{added[0]}»"} '
         f'{"доставлено через Telegram-бота" if notification_sent else "не доставлено через Telegram-бота"}. '
         + ("" if notification_sent else f"Причина: {notification_error or 'неизвестна'}")),
        student_id=student.id, direction_id=None if all_directions else targets[0].id,
    )
    db.session.commit()
    summary = f"Блокировка добавлена на {days} дн. по направлениям: {len(added)}."
    if already_blocked:
        summary += f" Уже были заблокированы: {len(already_blocked)}."
    if notification_sent:
        flash(summary + " Студент уведомлён через Telegram.", "success")
    else:
        flash(summary + f" Telegram-уведомление не доставлено: {notification_error or 'неизвестная ошибка'}", "warning")
    return redirect(url_for("admin.blocked_students"))


@admin_bp.route("/blocked-students/<int:decision_id>", methods=["POST"])
@super_admin_required
def edit_application_block(decision_id, current_user):
    """Only the super administrator can change or clear a rejection block."""
    decision = ApplicationDecision.query.get_or_404(decision_id)
    from services.applications import latest_application_decision
    latest = latest_application_decision(decision.student_id, decision.direction_id)
    if latest is None or latest.id != decision.id or decision.decision != DirectionStatus.REJECTED.value:
        flash("Можно изменять только актуальную блокировку по последнему решению.", "danger")
        return redirect(url_for("admin.blocked_students"))
    action = (request.form.get("action") or "").strip().lower()
    admin_reason = " ".join(str(request.form.get("admin_reason") or "").split())[:1000]
    student = Student.query.get(decision.student_id)
    direction = Direction.query.get(decision.direction_id)
    if action == "clear":
        if decision.cleared_at is not None:
            flash("Блокировка уже снята.", "warning")
        else:
            cleared_at = datetime.utcnow()
            student_name = student.full_name if student else f"ID {decision.student_id}"
            direction_name = direction.name if direction else f"ID {decision.direction_id}"
            decision.cleared_at = cleared_at
            decision.cleared_by_user_id = current_user.id
            decision.clear_reason = admin_reason or "Досрочно снята главным администратором."
            record_activity(
                "application_block_cleared",
                f'Главный администратор {current_user.email} снял блокировку студента «{student_name}» в направлении «{direction_name}». '
                f'Причина: {decision.clear_reason}',
                student_id=decision.student_id, direction_id=decision.direction_id,
            )
            db.session.commit()

            notification_sent = False
            notification_error = "У студента не указан Telegram ID."
            if student and student.tg_id and int(student.tg_id) > 0:
                message = (
                    "✅ <b>Блокировка снята</b>\n\n"
                    f"Здравствуйте, {html.escape(student_name)}!\n"
                    f"Главный администратор снял ограничение на подачу заявления в направлении «{html.escape(direction_name)}».\n\n"
                    f"<b>Дата снятия:</b> {cleared_at.strftime('%d.%m.%Y в %H:%M')}\n"
                    f"<b>Комментарий:</b> {html.escape(decision.clear_reason)}\n\n"
                    "Теперь вы снова можете подать заявление в это направление."
                )
                notification_sent, notification_error = _send_tg_detailed(student.tg_id, message)
            record_activity(
                "application_block_clear_notice_sent" if notification_sent else "application_block_clear_notice_failed",
                (f'Уведомление о снятии блокировки студенту «{student_name}» по направлению «{direction_name}» '
                 f'{"доставлено через Telegram-бота" if notification_sent else "не доставлено через Telegram-бота"}. '
                 + ("" if notification_sent else f"Причина: {notification_error or 'неизвестна'}")),
                student_id=decision.student_id, direction_id=decision.direction_id,
            )
            db.session.commit()
            if notification_sent:
                flash("Блокировка снята. Студент уведомлён через Telegram-бота.", "success")
            else:
                flash(f"Блокировка снята, но уведомление через Telegram не доставлено: {notification_error or 'неизвестная ошибка'}", "warning")
    elif action == "update":
        if decision.cleared_at is not None:
            flash("Эта блокировка уже снята. Изменить её срок нельзя.", "warning")
            return redirect(url_for("admin.blocked_students"))
        raw_until = (request.form.get("blocked_until") or "").strip()
        try:
            new_until = datetime.fromisoformat(raw_until)
        except ValueError:
            flash("Укажите корректную дату и время окончания блокировки.", "danger")
            return redirect(url_for("admin.blocked_students"))
        old_until = decision.blocked_until
        decision.blocked_until = new_until
        description = (f'Главный администратор {current_user.email} изменил срок блокировки студента «{student.full_name if student else decision.student_id}» '
                       f'в направлении «{direction.name if direction else decision.direction_id}» с '
                       f'{old_until.strftime("%d.%m.%Y %H:%M") if old_until else "—"} на {new_until.strftime("%d.%m.%Y %H:%M")}.')
        if admin_reason:
            description += f' Причина изменения: {admin_reason}'
        record_activity("application_block_updated", description, student_id=decision.student_id, direction_id=decision.direction_id)
        db.session.commit()
        flash("Срок блокировки обновлён.", "success")
    else:
        flash("Неизвестное действие.", "danger")
    return redirect(url_for("admin.blocked_students"))


@admin_bp.route("/")
@login_required
def dashboard(current_user):
    """One dashboard foundation with data and actions scoped to the account role."""
    role = current_user.role

    if role not in {UserRole.SUPER_ADMIN.value, UserRole.STAFF.value, UserRole.OBSERVER.value, UserRole.LEADER.value}:
        abort(403)

    # The main administrator sees and manages the entire site. The global
    # employee follows explicit grants across directions, scoped employees stay
    # inside one assigned direction, and observers see active data read-only.
    if role == UserRole.SUPER_ADMIN.value:
        scope_ids = _staff_visible_direction_ids(current_user)
    else:
        active_direction_ids = {row[0] for row in Direction.query.with_entities(Direction.id).filter(
            Direction.is_archived.is_(False)
        ).all()}
        if role == UserRole.STAFF.value:
            # Both employee account types aggregate only directions where they
            # have explicit working grants; direction employees naturally have
            # at most one such direction.
            granted_scope = _staff_visible_direction_ids(current_user, ('students', 'applications', 'events', 'lessons'))
            scope_ids = granted_scope & active_direction_ids
        elif role == UserRole.OBSERVER.value:
            scope_ids = active_direction_ids
        else:
            assigned_scope = _lesson_access_scope(current_user)
            scope_ids = active_direction_ids if assigned_scope is None else (set(assigned_scope) & active_direction_ids)

    scoped = scope_ids is not None
    direction_query = Direction.query.order_by(Direction.name.asc())
    if scoped:
        direction_query = direction_query.filter(Direction.id.in_(scope_ids))
    dirs = direction_query.all()
    visible_direction_ids = {direction.id for direction in dirs}
    if scoped:
        scope_ids = visible_direction_ids

    # Keep aggregate queries server-side and scoped by direction. The list of
    # student IDs is used only for the bounded bot-activity lookup below.
    if scoped:
        registered_student_ids = [row[0] for row in db.session.query(
            student_directions.c.student_id
        ).join(Student, Student.id == student_directions.c.student_id).filter(
            Student.council_registered.is_(True),
            student_directions.c.direction_id.in_(scope_ids),
        ).distinct().all()]
    else:
        registered_student_ids = [row[0] for row in Student.query.with_entities(Student.id).filter(
            Student.council_registered.is_(True)
        ).all()]

    participation_count = func.count(sa_case((
        or_(DayParticipation.status.is_(None), DayParticipation.status != "cancelled"),
        DayParticipation.id,
    ), else_=None))
    quota_scope = _quota_ids_exclusively_in_scope(scope_ids) if scoped else None

    day_capacity_query = db.session.query(
        EventDay.daily_places, participation_count.label("occupied")
    ).outerjoin(DayParticipation, DayParticipation.day_id == EventDay.id)
    if scoped:
        day_capacity_query = day_capacity_query.filter(EventDay.quota_id.in_(quota_scope))
    day_capacity_rows = day_capacity_query.group_by(EventDay.id, EventDay.daily_places).all()
    free_places = sum(max(0, int(capacity or 0) - int(occupied or 0))
                      for capacity, occupied in day_capacity_rows)

    pending_query = db.session.query(student_directions.c.student_id).join(
        Student, Student.id == student_directions.c.student_id
    ).filter(student_directions.c.status == "pending", Student.council_registered.is_(True))
    active_query = db.session.query(student_directions.c.student_id).join(
        Student, Student.id == student_directions.c.student_id
    ).filter(student_directions.c.status == "active", Student.council_registered.is_(True))
    if scoped:
        pending_query = pending_query.filter(student_directions.c.direction_id.in_(scope_ids))
        active_query = active_query.filter(student_directions.c.direction_id.in_(scope_ids))
    event_query = EventQuota.query
    stats_query = StudentQuotaStat.query
    if scoped:
        event_query = event_query.filter(EventQuota.id.in_(quota_scope))
        stats_query = stats_query.filter(StudentQuotaStat.direction_id.in_(scope_ids))
    stats = {
        "total_students": len(registered_student_ids),
        "pending_apps": pending_query.count(),
        "active_members": active_query.count(),
        "free_places": free_places,
        "event_count": event_query.count(),
        "stats_rows": stats_query.count(),
    }

    question_query = db.session.query(DirectionQuestion.direction_id).group_by(DirectionQuestion.direction_id)
    registered_direction_query = db.session.query(
        student_directions.c.direction_id, func.count(student_directions.c.student_id)
    ).join(Student, Student.id == student_directions.c.student_id).filter(
        Student.council_registered.is_(True)
    )
    if scoped:
        question_query = question_query.filter(DirectionQuestion.direction_id.in_(scope_ids))
        registered_direction_query = registered_direction_query.filter(student_directions.c.direction_id.in_(scope_ids))
    question_direction_ids = {row[0] for row in question_query.all()}
    registered_direction_counts = dict(registered_direction_query.group_by(student_directions.c.direction_id).all())
    dir_stats = [{
        "id": direction.id, "name": direction.name, "code": getattr(direction, "code", None),
        "icon": direction.icon, "color": direction.color, "description": direction.description,
        "count": int(registered_direction_counts.get(direction.id, 0)),
        "has_questions": direction.id in question_direction_ids,
    } for direction in dirs]

    # The chart uses only registered profiles in the viewer's allowed scope.
    period = 30 if request.args.get("period") == "30" else 7
    today = datetime.utcnow().date()
    first_day = today - timedelta(days=period - 1)
    activity_by_date = {}
    for start_index in range(0, len(registered_student_ids), 700):
        id_chunk = registered_student_ids[start_index:start_index + 700]
        activity_rows = (db.session.query(func.date(StudentActivity.created_at), func.count(StudentActivity.id))
                         .filter(StudentActivity.student_id.in_(id_chunk),
                                 StudentActivity.action.like(r"bot\_%", escape="\\"),
                                 StudentActivity.created_at >= datetime.combine(first_day, datetime.min.time()))
                         .group_by(func.date(StudentActivity.created_at)).all()) if id_chunk else []
        for day, count in activity_rows:
            key = str(day)
            activity_by_date[key] = activity_by_date.get(key, 0) + int(count or 0)
    activity_days = [{
        "day": (first_day + timedelta(days=index)).strftime("%d.%m"),
        "date": (first_day + timedelta(days=index)).isoformat(),
        "count": activity_by_date.get((first_day + timedelta(days=index)).isoformat(), 0),
    } for index in range(period)]
    activity_max = max([item["count"] for item in activity_days] + [1])
    for item in activity_days:
        item["height_pct"] = round(item["count"] / activity_max * 100)

    recent_students_query = Student.query.filter(
        Student.council_registered.is_(True),
        Student.created_at >= datetime.combine(first_day, datetime.min.time()),
    )
    if scoped:
        recent_students_query = recent_students_query.filter(Student.id.in_(registered_student_ids))
    recent_students = recent_students_query.count()

    member_counts_query = db.session.query(
        student_directions.c.direction_id, func.count(student_directions.c.student_id)
    ).join(Student, Student.id == student_directions.c.student_id).filter(
        student_directions.c.status == "active", Student.council_registered.is_(True)
    )
    if scoped:
        member_counts_query = member_counts_query.filter(student_directions.c.direction_id.in_(scope_ids))
    member_counts = dict(member_counts_query.group_by(student_directions.c.direction_id).all())
    direction_members = sorted(({
        "id": direction.id, "name": direction.name,
        "count": int(member_counts.get(direction.id, 0)),
    } for direction in dirs), key=lambda item: (-item["count"], item["name"].lower()))
    max_members = max([item["count"] for item in direction_members] + [1])
    for item in direction_members:
        item["width_pct"] = round(item["count"] / max_members * 100)

    upcoming_query = db.session.query(
        EventQuota.event_title, EventDay.date, EventQuota.location,
        EventDay.daily_places, EventQuota.is_published, participation_count.label("occupied"),
    ).join(EventDay, EventDay.quota_id == EventQuota.id).outerjoin(
        DayParticipation, DayParticipation.day_id == EventDay.id
    ).filter(
        EventQuota.is_closed.is_(False),
        EventDay.date >= datetime.combine(today, datetime.min.time()),
    )
    if scoped:
        upcoming_query = upcoming_query.filter(EventQuota.id.in_(quota_scope))
    upcoming_rows = upcoming_query.group_by(EventDay.id, EventQuota.id).order_by(
        EventDay.date.asc()
    ).limit(4).all()
    upcoming_events = [{
        "title": title, "date": event_date, "location": location,
        "free": max(0, int(capacity or 0) - int(occupied or 0)),
        "published": bool(published),
    } for title, event_date, location, capacity, published, occupied in upcoming_rows]
    dashboard_upcoming_items = [{
        "date": event["date"], "title": event["title"],
        "detail": event["location"] or "Место уточняется", "free": event["free"],
        "published": event["published"], "kind": "Мероприятие",
    } for event in upcoming_events]

    if role == UserRole.SUPER_ADMIN.value:
        dashboard_hero = {
            "kicker": "ГЛАВНЫЙ АДМИНИСТРАТОР · ПОЛНЫЙ ДОСТУП",
            "title": "Центр", "accent": "управления",
            "description": "Полное управление сайтом, всеми активными и архивными направлениями, сотрудниками, мероприятиями, чатами, документами и настройками системы.",
            "caption": "ГЛОБАЛЬНАЯ ПАНЕЛЬ · ВСЕ НАПРАВЛЕНИЯ · ВСЕ РАЗДЕЛЫ",
            "actions": [
                {"href": url_for("directions.directions_list"), "label": "Все направления", "style": "primary"},
                {"href": url_for("staff.accounts"), "label": "Сотрудники и доступы", "style": "ghost"},
            ],
        }
        dashboard_tools = [
            {"href": url_for("staff.workspace"), "class": "galaxy-tool-people", "icon": "◎", "title": "Студенты и заявления", "description": "Управление студенческими профилями и заявками по всему сайту.", "cta": "Открыть рабочее пространство"},
            {"href": url_for("directions.directions_list"), "class": "galaxy-tool-calendar", "icon": "◈", "title": "Все направления", "description": "Создание, настройка, архивирование и восстановление направлений.", "cta": "Открыть направления"},
            {"href": url_for("admin.calendar"), "class": "galaxy-tool-events", "icon": "✴", "title": "Единый календарь", "description": "Все мероприятия и занятия всех активных направлений.", "cta": "Открыть календарь"},
            {"href": url_for("activity_chats.index"), "class": "galaxy-tool-notifications", "icon": "◌", "title": "Чаты мероприятий", "description": "Управление чатами и сообщениями по всем мероприятиям.", "cta": "Открыть чаты"},
            {"href": url_for("admin.notifications"), "class": "galaxy-tool-notifications", "icon": "✉", "title": "Уведомления", "description": "Общесайтовые и направленные уведомления, подключение чатов.", "cta": "Открыть уведомления"},
            {"href": url_for("staff.accounts"), "class": "galaxy-tool-people", "icon": "♙", "title": "Сотрудники и наблюдатели", "description": "Создание нескольких сотрудников всех направлений, сотрудников отдельных направлений и наблюдателей.", "cta": "Управление аккаунтами"},
            {"href": url_for("stats.overview_statistics"), "class": "galaxy-tool-events", "icon": "▥", "title": "Аналитика", "description": "Глобальная статистика и показатели по всем направлениям.", "cta": "Открыть аналитику"},
            {"href": url_for("admin.event_reports"), "class": "galaxy-tool-leaders", "icon": "▧", "title": "Отчёты мероприятий", "description": "Формирование и просмотр отчётов по всем направлениям.", "cta": "Открыть отчёты"},
            {"href": url_for("admin.report_archive"), "class": "galaxy-tool-leaders", "icon": "▤", "title": "Архив отчётов", "description": "Полный архив документов, включая архивные направления.", "cta": "Открыть архив"},
            {"href": url_for("orders.archive"), "class": "galaxy-tool-leaders", "icon": "▧", "title": "Приказы и документы", "description": "Приказы и документы завершённых мероприятий по всему сайту.", "cta": "Открыть архив документов"},
        ]
        dashboard_metrics = [
            {"href": url_for("staff.workspace"), "icon": "◎", "label": "Всего студентов", "value": stats["total_students"], "detail": "По всему сайту"},
            {"href": url_for("staff.workspace"), "icon": "◷", "label": "Заявки на рассмотрении", "value": stats["pending_apps"], "detail": "По всем направлениям", "attention": bool(stats["pending_apps"])},
            {"href": url_for("directions.directions_list"), "icon": "✧", "label": "Активные участия", "value": stats["active_members"], "detail": "По всему сайту"},
            {"href": url_for("admin.calendar"), "icon": "✦", "label": "Свободные места", "value": stats["free_places"], "detail": "На мероприятиях всех направлений"},
        ]
    elif role == UserRole.STAFF.value:
        is_all_directions_employee = getattr(current_user, "staff_rank", "employee") == "employee_all"
        staff_scope_label = "в рамках выданных прав во всех направлениях" if is_all_directions_employee else "только вашего назначенного направления"
        staff_detail = "По всем направлениям в рамках доступа" if is_all_directions_employee else "В вашем направлении"
        home_name = getattr(getattr(current_user, "assigned_direction", None), "name", None)
        dashboard_hero = {
            "kicker": ("СОТРУДНИК · ВСЕ НАПРАВЛЕНИЯ" if is_all_directions_employee else (f"СОТРУДНИК · {home_name.upper()}" if home_name else "СОТРУДНИК · НАПРАВЛЕНИЕ НЕ НАЗНАЧЕНО")), 
            "title": "Центр", "accent": "управления",
            "description": "Рабочая панель сотрудника с доступом к выданным разделам всех активных направлений." if is_all_directions_employee else (f"Рабочая панель сотрудника в направлении «{home_name}». Все данные и действия ограничены этим направлением и выданными разрешениями." if home_name else "Главный администратор ещё не назначил вам основное направление."),
            "caption": "ДОСТУП КО ВСЕМ НАПРАВЛЕНИЯМ В РАМКАХ ВЫДАННЫХ ПРАВ · БЕЗ АДМИНИСТРИРОВАНИЯ СИСТЕМЫ" if is_all_directions_employee else "ДОСТУП ТОЛЬКО К ОДНОМУ НАЗНАЧЕННОМУ НАПРАВЛЕНИЮ · БЕЗ АДМИНИСТРИРОВАНИЯ СИСТЕМЫ",
            "actions": [
                {"href": url_for("staff.students"), "label": "Открыть студентов и заявления", "style": "primary"},
                {"href": url_for("admin.calendar"), "label": "Единый календарь", "style": "ghost"},
            ],
        }
        dashboard_tools = [
            {"href": url_for("staff.students"), "class": "galaxy-tool-people", "icon": "◎", "title": "Студенты и заявления", "description": f"Участники и обращения {staff_scope_label}.", "cta": "Открыть рабочее пространство"},
            {"href": url_for("directions.directions_list"), "class": "galaxy-tool-calendar", "icon": "◈", "title": "Направления", "description": "Доступные направления и их рабочие страницы в рамках выданных разрешений.", "cta": "Открыть направления"},
            {"href": url_for("admin.calendar"), "class": "galaxy-tool-events", "icon": "✴", "title": "Единый календарь", "description": f"Мероприятия и занятия {staff_scope_label}.", "cta": "Открыть календарь"},
            {"href": url_for("orders.archive"), "class": "galaxy-tool-leaders", "icon": "▧", "title": "Приказы и документы", "description": f"Документы по завершённым мероприятиям {staff_scope_label}.", "cta": "Открыть архив документов"},
            {"href": url_for("activity_chats.index"), "class": "galaxy-tool-notifications", "icon": "◌", "title": "Чаты мероприятий", "description": "Работа с чатами только тех направлений, где выдано соответствующее разрешение.", "cta": "Открыть чаты"},
            {"href": url_for("admin.notifications"), "class": "galaxy-tool-notifications", "icon": "✉", "title": "Уведомления", "description": f"Уведомления и объявления {staff_scope_label}.", "cta": "Открыть уведомления"},
            {"href": url_for("stats.overview_statistics"), "class": "galaxy-tool-events", "icon": "▥", "title": "Аналитика", "description": f"Сводные показатели {staff_scope_label}.", "cta": "Открыть аналитику"},
            {"href": url_for("admin.report_archive"), "class": "galaxy-tool-leaders", "icon": "▤", "title": "Архив отчётов", "description": f"Просмотр и скачивание отчётов {staff_scope_label}, без управления архивом.", "cta": "Открыть архив отчётов"},
        ]
        dashboard_metrics = [
            {"href": url_for("staff.students"), "icon": "◎", "label": "Всего студентов", "value": stats["total_students"], "detail": staff_detail},
            {"href": url_for("staff.students"), "icon": "◷", "label": "Заявки на рассмотрении", "value": stats["pending_apps"], "detail": staff_detail, "attention": bool(stats["pending_apps"])},
            {"href": url_for("directions.directions_list"), "icon": "✧", "label": "Активные участия", "value": stats["active_members"], "detail": staff_detail},
            {"href": url_for("admin.calendar"), "icon": "✦", "label": "Свободные места", "value": stats["free_places"], "detail": "По датам доступных мероприятий"},
        ]
    elif role == UserRole.OBSERVER.value:
        dashboard_hero = {
            "kicker": "НАБЛЮДАТЕЛЬ · РЕЖИМ ПРОСМОТРА", "title": "Центр", "accent": "наблюдения",
            "description": "Единая картина активных направлений, участников и предстоящих событий. Все показатели доступны только для чтения.",
            "caption": "ПРОСМОТР БЕЗ ИЗМЕНЕНИЯ ДАННЫХ",
            "actions": [
                {"href": url_for("stats.overview_statistics"), "label": "Открыть аналитику", "style": "primary"},
                {"href": url_for("admin.calendar"), "label": "Открыть календарь", "style": "ghost"},
            ],
        }
        dashboard_tools = [
            {"href": url_for("admin.students_management"), "class": "galaxy-tool-people", "icon": "◎", "title": "Студенты", "description": "Просмотр профилей и состава активных направлений.", "cta": "Только просмотр"},
            {"href": url_for("admin.calendar"), "class": "galaxy-tool-events", "icon": "✴", "title": "Календарь", "description": "Просмотр занятий, дат и мероприятий.", "cta": "Открыть календарь"},
            {"href": url_for("stats.overview_statistics"), "class": "galaxy-tool-leaders", "icon": "▥", "title": "Аналитика", "description": "Сводные показатели и статистика активных направлений.", "cta": "Изучить показатели"},
            {"href": url_for("directions.directions_list"), "class": "galaxy-tool-calendar", "icon": "◈", "title": "Направления", "description": "Просмотр состава и информации направлений.", "cta": "Открыть направления"},
            {"href": url_for("admin.report_archive"), "class": "galaxy-tool-notifications", "icon": "▤", "title": "Архив отчётов", "description": "Доступные для просмотра архивные документы.", "cta": "Перейти в архив"},
        ]
        dashboard_metrics = [
            {"href": url_for("admin.students_management"), "icon": "◎", "label": "Всего студентов", "value": stats["total_students"], "detail": "В вашем направлении"},
            {"href": url_for("admin.students_management"), "icon": "◷", "label": "Ожидают решения", "value": stats["pending_apps"], "detail": "Заявки на рассмотрении"},
            {"href": url_for("directions.directions_list"), "icon": "✧", "label": "Активные участия", "value": stats["active_members"], "detail": "По активным направлениям"},
            {"href": url_for("admin.calendar"), "icon": "✦", "label": "Свободные места", "value": stats["free_places"], "detail": "По датам мероприятий"},
        ]
    else:  # Direction leader: one dashboard with only the appointed scope.
        dashboard_hero = {
            "kicker": "РУКОВОДИТЕЛЬ · ДОСТУП ПО НАЗНАЧЕНИЮ", "title": "Центр", "accent": "направлений",
            "description": "Показатели, участники и события только тех активных направлений, за которые вы отвечаете.",
            "caption": "ДАННЫЕ ОГРАНИЧЕНЫ НАЗНАЧЕННЫМ НАПРАВЛЕНИЕМ",
            "actions": [
                {"href": url_for("directions.directions_list"), "label": "Мои направления", "style": "primary"},
                {"href": url_for("admin.calendar"), "label": "Календарь", "style": "ghost"},
            ],
        }
        dashboard_tools = [
            {"href": url_for("directions.directions_list"), "class": "galaxy-tool-people", "icon": "◈", "title": "Мои направления", "description": "Просмотр назначенных направлений и доступных рабочих функций.", "cta": "Открыть направления"},
            {"href": url_for("admin.calendar"), "class": "galaxy-tool-events", "icon": "✴", "title": "Календарь", "description": "Занятия и мероприятия в пределах вашего назначения.", "cta": "Открыть календарь"},
            {"href": url_for("admin.report_archive"), "class": "galaxy-tool-leaders", "icon": "▤", "title": "Архив отчётов", "description": "Документы, доступные вашей учётной записи.", "cta": "Перейти в архив"},
        ]
        directions_href = url_for("directions.directions_list")
        dashboard_metrics = [
            {"href": directions_href, "icon": "◎", "label": "Участники", "value": stats["total_students"], "detail": "В назначенных направлениях"},
            {"href": directions_href, "icon": "◷", "label": "Заявки на рассмотрении", "value": stats["pending_apps"], "detail": "В пределах вашего назначения", "attention": bool(stats["pending_apps"])},
            {"href": directions_href, "icon": "✧", "label": "Активные участия", "value": stats["active_members"], "detail": "В назначенных направлениях"},
            {"href": url_for("admin.calendar"), "icon": "✦", "label": "Свободные места", "value": stats["free_places"], "detail": "По доступным мероприятиям"},
        ]

    attention_items = []
    if stats["pending_apps"]:
        attention_items.append({
            "title": "Заявления на рассмотрении",
            "detail": f"Ожидают решения: {stats['pending_apps']}",
            "endpoint": ("staff.students" if role == UserRole.STAFF.value else ("admin.students_management" if role != UserRole.LEADER.value else "directions.directions_list")),
            "level": "warn",
        })
    nearly_full = sum(1 for event in upcoming_events if event["free"] <= 3)
    if nearly_full:
        attention_items.append({
            "title": "Места на мероприятиях",
            "detail": f"Ближайших дат с 0–3 местами: {nearly_full}",
            "endpoint": "admin.calendar", "level": "info",
        })
    dashboard_attention_items = [{
        "title": item["title"], "detail": item["detail"], "level": item["level"],
        "href": url_for(item["endpoint"]),
    } for item in attention_items]

    return render_template(
        "dashboard/overview.html", dashboard_mode="full", dashboard_hero=dashboard_hero,
        dashboard_metrics=dashboard_metrics, dashboard_tools=dashboard_tools,
        dashboard_attention_items=dashboard_attention_items, dashboard_upcoming_items=dashboard_upcoming_items,
        dashboard_show_overview_panels=True, dashboard_calendar_href=url_for("admin.calendar"),
        dashboard_show_analytics=role in {UserRole.SUPER_ADMIN.value, UserRole.STAFF.value, UserRole.OBSERVER.value},
        dashboard_show_directions=True, stats=stats, directions=dirs, direction_stats=dir_stats,
        period=period, activity_days=activity_days, activity_total=sum(item["count"] for item in activity_days),
        recent_students=recent_students, direction_members=direction_members, upcoming_events=upcoming_events,
        attention_items=attention_items, current_user=current_user,
    )


BOT_MONITOR_ACTION_LABELS = {
    'bot_profile_created': ('Регистрация профиля', 'registration'),
    'student_app_profile_created': ('Регистрация в Student App', 'registration'),
    'profile_created': ('Регистрация профиля', 'registration'),
    'bot_application_submitted': ('Подача заявления', 'applications'),
    'bot_application_approved': ('Заявление принято', 'applications'),
    'bot_application_rejected': ('Заявление отклонено', 'declines'),
    'bot_application_withdrawn': ('Отзыв заявления', 'declines'),
    'bot_event_registered': ('Запись на квоту / мероприятие', 'quotas'),
    'bot_quota_declined': ('Отказ от квоты / мероприятия', 'declines'),
    'bot_quota_decline_reversed': ('Возврат записи на квоту', 'declines'),
}
BOT_MONITOR_EVENT_TYPES = {
    'registration': ('bot_profile_created', 'student_app_profile_created', 'profile_created'),
    'application': ('bot_application_submitted', 'bot_application_approved', 'bot_application_rejected', 'bot_application_withdrawn'),
    'accepted': ('bot_application_approved',),
    'rejected': ('bot_application_rejected',),
    'event_signup': ('bot_event_registered',),
    'event_decline': ('bot_quota_declined',),
    'withdrawal': ('bot_application_withdrawn', 'bot_quota_decline_reversed'),
}


def _registered_student_id_chunks(chunk_size=700):
    ids = [row[0] for row in Student.query.with_entities(Student.id).filter(
        Student.council_registered.is_(True)
    ).order_by(Student.id.asc()).all()]
    return ids, [ids[index:index + chunk_size] for index in range(0, len(ids), chunk_size)]


def _registered_bot_activity_summary(now=None):
    """Count only durable activity attached to currently registered student profiles."""
    now = now or datetime.utcnow()
    registered_count = Student.query.filter(Student.council_registered.is_(True)).count()
    _ids, chunks = _registered_student_id_chunks()
    actions = tuple(BOT_MONITOR_ACTION_LABELS.keys())
    counts = {key: 0 for key in actions}
    since = now - timedelta(days=30)
    for chunk in chunks:
        rows = (StudentActivity.query.filter(
            StudentActivity.student_id.in_(chunk),
            StudentActivity.action.in_(actions),
            StudentActivity.created_at >= since,
        ).with_entities(StudentActivity.action, func.count(StudentActivity.id))
         .group_by(StudentActivity.action).all())
        for action, count in rows:
            counts[action] = counts.get(action, 0) + int(count or 0)
    return {
        'registered_profiles': registered_count,
        'registrations_30d': sum(counts.get(key, 0) for key in BOT_MONITOR_EVENT_TYPES['registration']),
        'applications_30d': counts.get('bot_application_submitted', 0),
        'accepted_30d': counts.get('bot_application_approved', 0),
        'rejected_30d': counts.get('bot_application_rejected', 0),
        'event_signups_30d': counts.get('bot_event_registered', 0),
        'event_declines_30d': counts.get('bot_quota_declined', 0),
        'withdrawals_30d': counts.get('bot_application_withdrawn', 0),
        'window_days': 30,
    }


def _activity_platform_label(description):
    text_value = (description or '').lower()
    if 'telegram web app' in text_value or 'student app' in text_value or 'студенческий кабинет' in text_value:
        return 'Telegram Web App / Student App'
    if 'telegram' in text_value:
        return 'Telegram'
    if 'vk' in text_value or 'вконтакте' in text_value:
        return 'VK'
    if 'max' in text_value:
        return 'MAX'
    if 'веб-сайт' in text_value or 'сайт' in text_value:
        return 'Сайт'
    return 'Источник не указан'


BOT_MONITOR_SAFE_DESCRIPTIONS = {
    'bot_profile_created': 'Создан зарегистрированный профиль.',
    'student_app_profile_created': 'Создан зарегистрированный профиль в Student App.',
    'profile_created': 'Создан зарегистрированный профиль.',
    'bot_application_submitted': 'Заявление отправлено на рассмотрение.',
    'bot_application_approved': 'Заявление принято; участник активирован.',
    'bot_application_rejected': 'Заявление отклонено. Персональное основание хранится отдельно.',
    'bot_application_withdrawn': 'Заявление отозвано.',
    'bot_event_registered': 'Участник записан на квоту или мероприятие.',
    'bot_quota_declined': 'Участник отказался от квоты или мероприятия. Персональная причина хранится отдельно.',
    'bot_quota_decline_reversed': 'Отказ от участия отменён.',
}


def _safe_bot_activity_description(action):
    """Return an approved business label; never render free-form activity text."""
    return BOT_MONITOR_SAFE_DESCRIPTIONS.get(action, 'Бизнес-действие зарегистрировано.')


def _collect_registered_bot_activities(args=None, *, export_limit=0):
    """Build a registered-profile-only event timeline with safe cross-bind lookups."""
    args = args or {}
    registered_ids, chunks = _registered_student_id_chunks()
    filters = {
        'q': (args.get('q') or '').strip()[:100],
        'event_type': (args.get('event_type') or '').strip(),
        'platform': (args.get('platform') or '').strip(),
        'start': (args.get('start') or '').strip()[:10],
        'end': (args.get('end') or '').strip()[:10],
    }
    if filters['event_type'] not in BOT_MONITOR_EVENT_TYPES:
        filters['event_type'] = ''
    if filters['platform'] not in ('telegram', 'vk', 'max', 'student_app', 'site'):
        filters['platform'] = ''
    actions = tuple(BOT_MONITOR_ACTION_LABELS.keys())
    if filters['event_type']:
        actions = BOT_MONITOR_EVENT_TYPES[filters['event_type']]
    now = datetime.utcnow()
    if not filters['start']:
        filters['start'] = (now - timedelta(days=30)).strftime('%Y-%m-%d')
    try:
        start_dt = datetime.strptime(filters['start'], '%Y-%m-%d') if filters['start'] else now - timedelta(days=30)
    except ValueError:
        filters['start'] = ''
        start_dt = now - timedelta(days=30)
    try:
        end_dt = datetime.strptime(filters['end'], '%Y-%m-%d') + timedelta(days=1) if filters['end'] else None
    except ValueError:
        filters['end'] = ''
        end_dt = None

    search_ids = set()
    search_direction_ids = set()
    search_quota_ids = set()
    if filters['q']:
        pattern = '%' + filters['q'].replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        name_rows = Student.query.filter(
            Student.council_registered.is_(True),
            or_(Student.full_name.ilike(pattern, escape='\\'),
                Student.group.ilike(pattern, escape='\\'),
                Student.telegram_username.ilike(pattern, escape='\\')),
        ).with_entities(Student.id).limit(5000).all()
        direction_rows = Direction.query.filter(Direction.name.ilike(pattern, escape='\\')).with_entities(Direction.id).limit(1000).all()
        quota_rows = EventQuota.query.filter(EventQuota.event_title.ilike(pattern, escape='\\')).with_entities(EventQuota.id).limit(1000).all()
        search_ids = {row[0] for row in name_rows}
        search_direction_ids = {row[0] for row in direction_rows}
        search_quota_ids = {row[0] for row in quota_rows}

    if export_limit:
        page = 1
        per_page = min(max(int(export_limit), 1), 10000)
    else:
        try:
            page = min(max(int(args.get('page', '1')), 1), 40)
        except (TypeError, ValueError):
            page = 1
        per_page = 30
    fetch_limit = min(page * per_page, 10000)
    total = 0
    candidates = []
    for chunk in chunks:
        query = StudentActivity.query.filter(
            StudentActivity.student_id.in_(chunk),
            StudentActivity.action.in_(actions),
            StudentActivity.created_at >= start_dt,
        )
        if end_dt:
            query = query.filter(StudentActivity.created_at < end_dt)
        if filters['platform']:
            platform_patterns = {
                'telegram': and_(StudentActivity.description.ilike('%telegram%'),
                                 ~StudentActivity.description.ilike('%telegram web app%')),
                'vk': or_(StudentActivity.description.ilike('%vk%'), StudentActivity.description.ilike('%вконтакте%')) ,
                'max': StudentActivity.description.ilike('%max%'),
                'student_app': or_(StudentActivity.description.ilike('%telegram web app%'),
                                   StudentActivity.description.ilike('%student app%'),
                                   StudentActivity.description.ilike('%студенческий кабинет%')) ,
                'site': StudentActivity.description.ilike('%веб-сайт%'),
            }
            query = query.filter(platform_patterns[filters['platform']])
        if filters['q']:
            search_predicates = []
            chunk_search_ids = list(search_ids.intersection(chunk))
            if chunk_search_ids:
                search_predicates.append(StudentActivity.student_id.in_(chunk_search_ids))
            if search_direction_ids:
                search_predicates.append(StudentActivity.direction_id.in_(list(search_direction_ids)))
            if search_quota_ids:
                search_predicates.append(StudentActivity.quota_id.in_(list(search_quota_ids)))
            query = query.filter(or_(*search_predicates) if search_predicates else false())
        total += query.count()
        candidates.extend(query.order_by(StudentActivity.created_at.desc(), StudentActivity.id.desc()).limit(fetch_limit).all())
    candidates.sort(key=lambda item: (item.created_at or datetime.min, item.id), reverse=True)
    if not export_limit:
        candidates = candidates[(page - 1) * per_page: page * per_page]
    else:
        candidates = candidates[:per_page]

    student_ids = {item.student_id for item in candidates if item.student_id}
    direction_ids = {item.direction_id for item in candidates if item.direction_id}
    quota_ids = {item.quota_id for item in candidates if item.quota_id}
    students = {row.id: row for row in Student.query.filter(
        Student.id.in_(student_ids), Student.council_registered.is_(True)
    ).all()} if student_ids else {}
    directions = {row.id: row for row in Direction.query.filter(Direction.id.in_(direction_ids)).all()} if direction_ids else {}
    quotas = {row.id: row for row in EventQuota.query.filter(EventQuota.id.in_(quota_ids)).all()} if quota_ids else {}
    events = []
    for item in candidates:
        student = students.get(item.student_id)
        if not student:
            continue
        label, group = BOT_MONITOR_ACTION_LABELS.get(
            item.action, (item.action.replace('_', ' ').capitalize(), 'other')
        )
        # StudentActivity.description is free-form legacy data and may contain
        # user-entered rejection/decline reasons. Only approved labels may leave
        # this function for the admin UI or any derived timeline response.
        safe_description = _safe_bot_activity_description(item.action)
        events.append({
            'id': item.id,
            'created_at': item.created_at,
            'student_id': student.id,
            'student_name': student.full_name,
            'student_group': student.group or 'Группа не указана',
            'action': item.action,
            'action_label': label,
            'event_group': group,
            'event_group_label': {'registration': 'Регистрация', 'applications': 'Заявления', 'quotas': 'Квоты и мероприятия', 'declines': 'Отказы и отмены'}.get(group, 'Другие действия'),
            'platform': _activity_platform_label(item.description),
            'direction': directions.get(item.direction_id).name if item.direction_id in directions else '',
            'quota': quotas.get(item.quota_id).event_title if item.quota_id in quotas else '',
            'description': safe_description,
        })
    pages = max(1, (total + per_page - 1) // per_page)
    return {'events': events, 'total': total, 'page': min(page, pages), 'pages': pages,
            'per_page': per_page, 'filters': filters, 'registered_profiles': len(registered_ids)}


def _recent_bot_transport_incidents(limit=12):
    from database import BotJournalEvent
    from services.bot_journal import safe_summary
    rows = (BotJournalEvent.query.filter_by(status='error')
            .order_by(BotJournalEvent.created_at.desc(), BotJournalEvent.id.desc())
            .limit(max(1, min(int(limit), 50))).all())
    # Old rows may predate summary allow-listing. Sanitize on read as well as
    # on write, so legacy free-form provider responses are never rendered.
    for row in rows:
        row.safe_summary = safe_summary(row.summary)
    return rows


def _messenger_monitoring_snapshot_data():
    """Return safe operational aggregates for Telegram, VK and MAX.

    This is durable journal telemetry, not a network-level online check. Never
    expose recipient IDs, message bodies, credentials or raw transport payloads.
    """
    from database import BotJournalEvent, BotDeliveryJob

    now = datetime.utcnow()
    since = now - timedelta(hours=24)
    platform_labels = (("telegram", "Telegram"), ("vk", "ВКонтакте"), ("max", "MAX"))
    queue_states = ("pending", "retry", "sending", "blocked", "failed", "delivered")
    platforms = []
    totals = {"events": 0, "success": 0, "errors": 0, "queue_active": 0, "queue_blocked": 0, "queue_failed": 0}

    for key, label in platform_labels:
        events = BotJournalEvent.query.filter_by(platform=key).filter(BotJournalEvent.created_at >= since)
        latest = (BotJournalEvent.query.filter_by(platform=key)
                  .order_by(BotJournalEvent.created_at.desc(), BotJournalEvent.id.desc()).first())
        last_send = (BotJournalEvent.query.filter_by(platform=key, kind="outgoing", status="success")
                     .order_by(BotJournalEvent.created_at.desc(), BotJournalEvent.id.desc()).first())
        counts = {state: BotDeliveryJob.query.filter_by(platform=key, status=state).count()
                  for state in queue_states}
        row = {
            "platform": key,
            "label": label,
            "events_24h": events.count(),
            "success_24h": events.filter_by(status="success").count(),
            "errors_24h": events.filter_by(status="error").count(),
            "average_duration_ms": int(round(events.with_entities(func.avg(BotJournalEvent.duration_ms)).scalar() or 0)),
            "queue": counts,
            "queue_active": counts["pending"] + counts["retry"] + counts["sending"],
            "last_event": latest.created_at.isoformat() if latest and latest.created_at else None,
            "last_event_status": latest.status if latest else None,
            "last_send": last_send.created_at.isoformat() if last_send and last_send.created_at else None,
        }
        platforms.append(row)
        totals["events"] += row["events_24h"]
        totals["success"] += row["success_24h"]
        totals["errors"] += row["errors_24h"]
        totals["queue_active"] += row["queue_active"]
        totals["queue_blocked"] += counts["blocked"]
        totals["queue_failed"] += counts["failed"]

    return {
        "generated_at": now.isoformat(), "window_hours": 24, "totals": totals,
        "platforms": platforms,
        "student_summary": _registered_bot_activity_summary(now),
    }


@admin_bp.get("/messenger-monitoring")
@super_admin_required
def messenger_monitoring(current_user):
    """Super-admin view: integration health plus one grouped business-action ledger."""
    snapshot = _messenger_monitoring_snapshot_data()
    activity = _collect_registered_bot_activities(request.args)
    from services.bot_journal_views import PLATFORM_NAMES, ACTION_NAMES
    transport_incidents = _recent_bot_transport_incidents(12)
    return render_template(
        "system/messenger_monitoring.html", snapshot=snapshot, activity=activity,
        transport_incidents=transport_incidents, platform_names=PLATFORM_NAMES,
        transport_action_names=ACTION_NAMES,
    )


@admin_bp.get("/messenger-monitoring/student-events.csv")
@super_admin_required
def messenger_monitoring_student_events_export(current_user):
    """Export only registered-profile events; never export non-registered contacts."""
    out = io.StringIO(newline='')
    writer = __import__('csv').writer(out)
    writer.writerow(('ID события', 'Время UTC', 'Участник', 'Группа', 'Платформа',
                     'Раздел действий', 'Что произошло', 'Направление', 'Квота / мероприятие'))
    payload = _collect_registered_bot_activities(request.args, export_limit=10000)
    def safe_cell(value):
        text_value = str(value if value is not None else '')
        return "'" + text_value if text_value.lstrip().startswith(('=', '+', '-', '@')) else text_value
    for row in payload['events']:
        writer.writerow(map(safe_cell, (
            f'B-{row["id"]}', row['created_at'].isoformat(' ') if row['created_at'] else '',
            row['student_name'], row['student_group'], row['platform'], row['event_group_label'],
            row['action_label'], row['direction'], row['quota'],
        )))
    response = Response('\ufeff' + out.getvalue(), mimetype='text/csv; charset=utf-8')
    response.headers['Content-Disposition'] = 'attachment; filename="registered-student-bot-activity.csv"'
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@admin_bp.get("/messenger-monitoring/bot-events.csv")
@super_admin_required
def messenger_monitoring_bot_events_export(current_user):
    """Legacy URL now exports grouped registered-profile business actions."""
    allowed = {}
    for source, target in (('bot_q', 'q'), ('bot_platform', 'platform'),
                           ('bot_start', 'start'), ('bot_end', 'end')):
        value = (request.args.get(source) or '').strip()
        if value:
            allowed[target] = value
    return redirect(url_for('admin.messenger_monitoring_student_events_export', **allowed))


@admin_bp.get("/messenger-monitoring/snapshot")
@super_admin_required
def messenger_monitoring_snapshot(current_user):
    """Private aggregate polling endpoint; raw events and message data stay hidden."""
    response = jsonify({"ok": True, **_messenger_monitoring_snapshot_data()})
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@admin_bp.route("/calendar")
@login_required
def calendar(current_user):
    """One real server-backed month/agenda timeline for lessons and quota days."""
    from services.permissions import allowed_direction_ids
    selected_date = request.args.get("date", "").strip()[:10]
    try:
        datetime.strptime(selected_date, "%Y-%m-%d")
    except ValueError:
        selected_date = datetime.now().strftime("%Y-%m-%d")
    selected_kind = request.args.get("kind", "all").strip().lower()
    if selected_kind not in {"all", "lesson", "event"}:
        selected_kind = "all"
    allowed_ids = None
    if current_user.role == UserRole.LEADER.value:
        allowed_ids = set()
        if current_user.tg_id:
            actor = Student.query.filter_by(tg_id=current_user.tg_id).first()
            if actor:
                allowed_ids = allowed_direction_ids(actor.id)
        if not allowed_ids and current_user.assigned_direction_id:
            allowed_ids = {current_user.assigned_direction_id}
    event_allowed_ids = None
    lesson_allowed_ids = None
    if current_user.role in {UserRole.STAFF.value, UserRole.SUPER_ADMIN.value}:
        from services.staff_access import direction_ids as staff_direction_ids
        event_allowed_ids = set(staff_direction_ids(current_user, 'events', 'view'))
        lesson_allowed_ids = set(staff_direction_ids(current_user, 'lessons', 'view'))
        allowed_ids = event_allowed_ids | lesson_allowed_ids
    elif current_user.role == UserRole.OBSERVER.value:
        event_allowed_ids = _lesson_access_scope(current_user) or set()
        lesson_allowed_ids = event_allowed_ids
        allowed_ids = event_allowed_ids
    elif current_user.role == UserRole.LEADER.value:
        event_allowed_ids = allowed_ids
        lesson_allowed_ids = allowed_ids
    direction_query = Direction.query.order_by(Direction.name.asc())
    if allowed_ids is not None:
        direction_query = direction_query.filter(Direction.id.in_(allowed_ids))
    directions = direction_query.all()
    direction_names = {d.id: d.name for d in directions}
    # For leaders and observers, allowed_ids already came from the same scope
    # resolver above; reuse it rather than repeating the permission lookups.
    scope = (lesson_allowed_ids if current_user.role in {UserRole.OBSERVER.value, UserRole.STAFF.value, UserRole.SUPER_ADMIN.value}
             else allowed_ids if current_user.role == UserRole.LEADER.value else _lesson_access_scope(current_user))
    if current_user.role in {UserRole.STAFF.value, UserRole.SUPER_ADMIN.value}:
        from services.staff_access import direction_ids as staff_direction_ids
        lesson_manage_ids = set(staff_direction_ids(current_user, 'lessons', 'manage'))
        event_manage_ids = set(staff_direction_ids(current_user, 'events', 'manage'))
        can_manage_lessons = bool(lesson_manage_ids)
        can_create_events = bool(event_manage_ids)
    else:
        can_manage_lessons = current_user.role != UserRole.OBSERVER.value and (scope is None or bool(scope))
        can_create_events = current_user.role == UserRole.SUPER_ADMIN.value and bool(event_allowed_ids)
    can_manage_events = bool(event_manage_ids) if current_user.role in {UserRole.STAFF.value, UserRole.SUPER_ADMIN.value} else False

    # Resolve the lesson scope once per request. Re-running this permission
    # resolver for every lesson caused repeated student/leadership queries.
    calendar_events = []
    lesson_query = Lesson.query
    if lesson_allowed_ids is not None:
        lesson_query = lesson_query.filter(Lesson.direction_id.in_(lesson_allowed_ids))
    for lesson in lesson_query.order_by(Lesson.starts_at.desc()).limit(1500).all():
        if current_user.role == UserRole.STAFF.value:
            from services.staff_access import allowed as staff_allowed
            can_edit = staff_allowed(current_user, lesson.direction_id, 'lessons', 'manage')
        else:
            can_edit = bool(can_manage_lessons and (scope is None or lesson.direction_id in scope))
        calendar_events.append({
            "id": f"lesson-{lesson.id}", "type": "lesson", "title": lesson.title,
            "start": lesson.starts_at.isoformat(timespec="minutes"),
            "end": lesson.end_at.isoformat(timespec="minutes"),
            "directionId": lesson.direction_id, "directionIds": [lesson.direction_id],
            "direction": direction_names.get(lesson.direction_id, "Направление"),
            "description": lesson.description or "", "teacher": lesson.teacher or "",
            "location": lesson.room or "", "duration": lesson.duration_minutes,
            "capacity": lesson.capacity, "status": lesson.status,
            "editUrl": url_for("lessons.edit_lesson", lesson_id=lesson.id, return_to="calendar", date=selected_date) if can_edit else None,
            "publishUrl": url_for("lessons.publish_lesson", lesson_id=lesson.id) if can_edit else None,
            "deleteUrl": url_for("lessons.delete_lesson", lesson_id=lesson.id) if can_edit else None,
        })

    # Calendar rendering used to issue up to three extra queries per event:
    # direction links, chat targets, and the lazy-loaded day collection. Fetch
    # these relationships in bounded batches so a large calendar stays fast.
    quota_rows = (EventQuota.query.options(selectinload(EventQuota.days))
                  .order_by(EventQuota.id.desc()).limit(1500).all())
    quota_ids = [quota.id for quota in quota_rows]
    directions_by_quota = {}
    chats_by_quota = {}
    if quota_ids:
        for link in QuotaDirection.query.filter(QuotaDirection.quota_id.in_(quota_ids)).all():
            directions_by_quota.setdefault(link.quota_id, []).append(link.direction_id)
        for row in EventQuotaChat.query.filter(EventQuotaChat.quota_id.in_(quota_ids)).all():
            chats_by_quota.setdefault(row.quota_id, []).append(row)
            if row.direction_id is not None:
                directions_by_quota.setdefault(row.quota_id, []).append(row.direction_id)

    for quota in quota_rows:
        dids = directions_by_quota.get(quota.id, [])
        event_scope = event_allowed_ids if current_user.role in {UserRole.STAFF.value, UserRole.OBSERVER.value, UserRole.LEADER.value, UserRole.SUPER_ADMIN.value} else allowed_ids
        visible = [did for did in dids if event_scope is None or did in event_scope]
        # Do not expose an event that is shared with directions outside this
        # account's scope; editing it would affect foreign workspaces too.
        if event_scope is not None and (not visible or set(visible) != set(dids)):
            continue
        direction_label = ", ".join(direction_names.get(did, "Направление") for did in visible) or "Общее мероприятие"
        event_chat_rows = chats_by_quota.get(quota.id, [])
        event_chat_targets = [{
            "platform": (getattr(row, "platform", None) or "telegram"),
            "platformLabel": {"telegram": "Telegram", "vk": "VK", "max": "MAX"}.get(
                (getattr(row, "platform", None) or "telegram"), "Мессенджер"),
            "title": row.title or row.chat_id,
        } for row in event_chat_rows]
        event_chat_summary = ", ".join(
            f"{item['platformLabel']}: {item['title']}" for item in event_chat_targets
        ) or "Чаты не выбраны"
        if quota.publish_mode == "scheduled" and not quota.is_published and quota.publish_at:
            calendar_events.append({
                "id": f"announcement-{quota.id}", "type": "event", "isAnnouncement": True,
                "title": f"Публикация в чаты: {quota.event_title}",
                "start": quota.publish_at.isoformat(timespec="minutes"), "end": "", "allDay": False,
                "directionIds": visible, "direction": direction_label,
                "description": quota.event_description or "",
                "location": "", "timeRange": "Автопубликация", "published": False,
                "capacity": quota.total_places, "status": "Автопубликация запланирована",
                "chatTargets": event_chat_targets, "chatSummary": event_chat_summary,
                "participantsUrl": None,
                "publishUrl": url_for("quotas.publish_quota", qid=quota.id, return_to="calendar", date=selected_date) if can_manage_events else None,
                "closeUrl": None, "detailUrl": None,
            })
        for day in quota.days:
            calendar_events.append({
                "id": f"event-{quota.id}-{day.id}", "type": "event", "title": quota.event_title,
                "start": day.date.date().isoformat(), "end": day.date.date().isoformat(), "allDay": True,
                "directionIds": visible, "direction": direction_label,
                "description": quota.event_description or "", "location": quota.location or "",
                "timeRange": quota.time_range or "", "published": quota.is_published,
                "capacity": day.daily_places, "status": ("Закрыто" if quota.is_closed else "Опубликовано" if quota.is_published else "Черновик / запланировано"),
                "chatTargets": event_chat_targets, "chatSummary": event_chat_summary,
                "participantsUrl": url_for("quotas.quota_participants", qid=quota.id, return_to="calendar", date=selected_date) if can_manage_events else None,
                "publishUrl": url_for("quotas.publish_quota", qid=quota.id, return_to="calendar", date=selected_date) if can_manage_events else None,
                "closeUrl": url_for("quotas.close_quota", qid=quota.id) if can_manage_events and not quota.is_closed else None,
                "detailUrl": None,
            })
    return render_template(
        "calendar/index.html", calendar_events=calendar_events,
        directions=directions, selected_date=selected_date, selected_direction=request.args.get("direction_id", type=int), csrf_token_value=csrf_token(),
        can_manage_lessons=can_manage_lessons, can_manage_events=can_manage_events,
        can_create_events=can_create_events, selected_kind=selected_kind,
    )


@admin_bp.post("/student-app/design/live")
@super_admin_required
def student_app_design_live(current_user):
    """Persist a theme choice without a page reload; clients pick it up via theme sync."""
    requested_season = str(request.form.get("season", "")).strip().lower()
    if requested_season not in STUDENT_APP_SEASONS:
        return jsonify({"ok": False, "error": "invalid_theme"}), 400
    setting = PortalSetting.query.filter_by(key="student_app_season").first()
    if setting is None:
        setting = PortalSetting(key="student_app_season", value=requested_season)
        db.session.add(setting)
    else:
        setting.value = requested_season
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("live_theme_save_failed actor_id=%s", current_user.id)
        return jsonify({"ok": False, "error": "save_failed"}), 500
    response = jsonify({"ok": True, "key": requested_season, "label": STUDENT_APP_SEASONS[requested_season]["label"]})
    response.headers["Cache-Control"] = "no-store"
    return response


@admin_bp.route("/student-app/design", methods=["GET", "POST"])
@super_admin_required
def student_app_design(current_user):
    selected_season = current_student_app_season()
    if request.method == "POST":
        requested_season = str(request.form.get("season", "")).strip().lower()
        if requested_season not in STUDENT_APP_SEASONS:
            flash("Выберите сезонную или праздничную тему оформления.", "danger")
            return redirect(url_for("admin.student_app_design"))
        setting = PortalSetting.query.filter_by(key="student_app_season").first()
        if setting is None:
            setting = PortalSetting(key="student_app_season", value=requested_season)
            db.session.add(setting)
        else:
            setting.value = requested_season
        try:
            db.session.commit()
            flash(f"Тема «{STUDENT_APP_SEASONS[requested_season]['label']}» применена к веб-панели и Student App.", "success")
            return redirect(url_for("admin.student_app_design", theme_changed=1))
        except Exception:
            db.session.rollback()
            logger.exception("Failed to save Student App seasonal theme for admin %s", current_user.id)
            flash("Не удалось сохранить оформление. Попробуйте ещё раз.", "danger")
            return redirect(url_for("admin.student_app_design"))
    return render_template(
        "system/student_app_design.html",
        themes=STUDENT_APP_SEASONS,
        selected_season=selected_season,
        selected_theme=STUDENT_APP_SEASONS[selected_season],
    )


def _bot_log_count():
    from database import BotJournalEvent
    return BotJournalEvent.query.count()


def _runtime_health_snapshot():
    """Collect live operational checks without exposing secrets or raw paths."""
    import shutil
    import sys
    from pathlib import Path
    from services.runtime_supervisor import worker_snapshots
    from database import BotDeliveryJob

    now = datetime.utcnow()
    workers = worker_snapshots()
    database_labels = {
        "people": "Профили и сотрудники",
        "events": "Мероприятия и регистрации",
        "lessons": "Занятия",
        "stats": "Статистика",
        "system": "Системные данные и журналы",
    }
    database_checks = []
    engines_unavailable = False
    try:
        engines = list(db.engines.items())
    except Exception as error:
        engines = []
        engines_unavailable = True
        logger.warning("runtime_database_registry_unavailable error_type=%s", type(error).__name__)

    for bind_key, engine in engines:
        bind = str(bind_key or "people")
        started = time.perf_counter()
        state = "ok"
        error_type = None
        try:
            with engine.connect() as connection:
                connection.execute(sql_text("SELECT 1"))
        except Exception as error:
            state = "error"
            error_type = type(error).__name__
            logger.warning("runtime_database_check_failed bind=%s error_type=%s", bind, error_type)
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        size_mb = None
        try:
            database_path = engine.url.database
            if engine.url.get_backend_name() == "sqlite" and database_path and Path(database_path).is_file():
                size_mb = round(Path(database_path).stat().st_size / (1024 * 1024), 2)
        except (OSError, TypeError, ValueError):
            size_mb = None
        database_checks.append({
            "bind": bind,
            "label": database_labels.get(bind, "База данных"),
            "state": state,
            "status_label": "Доступна" if state == "ok" else "Ошибка подключения",
            "latency_ms": latency_ms,
            "size_mb": size_mb,
            "error_type": error_type,
        })

    databases_ok = bool(database_checks) and not engines_unavailable and all(item["state"] == "ok" for item in database_checks)

    since = now - timedelta(hours=24)
    http_metrics = {
        "available": True,
        "requests_24h": 0,
        "staff_actions_24h": 0,
        "client_errors_24h": 0,
        "server_errors_24h": 0,
    }
    try:
        recent_http = HttpAuditLog.query.filter(HttpAuditLog.created_at >= since)
        grouped_statuses = recent_http.with_entities(HttpAuditLog.status_code, func.count(HttpAuditLog.id)).group_by(HttpAuditLog.status_code).all()
        http_metrics["requests_24h"] = sum(int(count or 0) for _, count in grouped_statuses)
        http_metrics["client_errors_24h"] = sum(int(count or 0) for status, count in grouped_statuses if 400 <= int(status) < 500)
        http_metrics["server_errors_24h"] = sum(int(count or 0) for status, count in grouped_statuses if int(status) >= 500)
        http_metrics["staff_actions_24h"] = recent_http.filter(HttpAuditLog.actor_user_id.isnot(None)).count()
    except Exception as error:
        db.session.rollback()
        http_metrics["available"] = False
        logger.warning("runtime_http_metrics_unavailable error_type=%s", type(error).__name__)

    queue_statuses = {}
    queue_metrics = {"pending": 0, "failed": 0, "blocked": 0, "sending": 0, "retry": 0, "delivered": 0}
    try:
        for status, count in db.session.query(BotDeliveryJob.status, func.count(BotDeliveryJob.id)).group_by(BotDeliveryJob.status).all():
            queue_statuses[str(status or "unknown")] = int(count or 0)
        queue_metrics["pending"] = sum(queue_statuses.get(key, 0) for key in ("pending", "retry", "sending"))
        queue_metrics["retry"] = queue_statuses.get("retry", 0)
        queue_metrics["sending"] = queue_statuses.get("sending", 0)
        queue_metrics["failed"] = queue_statuses.get("failed", 0)
        queue_metrics["blocked"] = queue_statuses.get("blocked", 0)
        queue_metrics["delivered"] = sum(queue_statuses.get(key, 0) for key in ("sent", "delivered", "done"))
    except Exception as error:
        db.session.rollback()
        queue_metrics["available"] = False
        logger.warning("runtime_delivery_metrics_unavailable error_type=%s", type(error).__name__)

    integrations = [
        {
            "key": "telegram", "label": "Telegram",
            "configured": bool(settings.BOT_TOKEN),
            "status_label": "Конфигурация задана" if settings.BOT_TOKEN else "Отключён: нет токена",
            "detail": "BOT_TOKEN задан; фактическая связь проверяется журналом и логами." if settings.BOT_TOKEN else "Для включения задайте BOT_TOKEN в .env.",
        },
        {
            "key": "vk", "label": "VK",
            "configured": bool(settings.VK_BOT_TOKEN and settings.VK_GROUP_ID),
            "status_label": "Конфигурация задана" if settings.VK_BOT_TOKEN and settings.VK_GROUP_ID else "Отключён: нет данных доступа",
            "detail": "VK_BOT_TOKEN и VK_GROUP_ID заданы; фактическая связь здесь не пингуется." if settings.VK_BOT_TOKEN and settings.VK_GROUP_ID else "Требуются VK_BOT_TOKEN и VK_GROUP_ID.",
        },
        {
            "key": "max", "label": "MAX",
            "configured": bool(settings.MAX_BOT_TOKEN and (settings.MAX_MODE != "webhook" or settings.MAX_WEBHOOK_ENDPOINT)),
            "status_label": "Конфигурация задана" if settings.MAX_BOT_TOKEN and (settings.MAX_MODE != "webhook" or settings.MAX_WEBHOOK_ENDPOINT) else "Не настроен полностью",
            "detail": (f"Токен задан, режим: {settings.MAX_MODE}. Статус соединения не подтверждается одной конфигурацией." if settings.MAX_BOT_TOKEN and (settings.MAX_MODE != "webhook" or settings.MAX_WEBHOOK_ENDPOINT) else "Проверьте MAX_BOT_TOKEN, режим и публичный HTTPS WEBAPP_URL для webhook."),
        },
    ]

    started_epoch = current_app.extensions.get("portal_runtime_started_epoch", time.time())
    started_at = current_app.extensions.get("portal_runtime_started_at_utc", "Неизвестно")
    uptime_seconds = max(0, int(time.time() - float(started_epoch)))

    data_dir = Path(settings.DATA_DIR)
    try:
        disk = shutil.disk_usage(data_dir)
        disk_metrics = {"free_gb": round(disk.free / (1024 ** 3), 2), "total_gb": round(disk.total / (1024 ** 3), 2), "available": True}
    except OSError:
        disk_metrics = {"free_gb": None, "total_gb": None, "available": False}

    log_path = Path(os.getenv("SITE_LOG_DIR") or (data_dir / "logs")).expanduser() / "portal.jsonl"
    log_metrics = {"available": False, "status_label": "Файл пока не создан", "size_mb": None, "modified_at": None}
    try:
        if log_path.is_file() and os.access(log_path, os.R_OK):
            log_stat = log_path.stat()
            log_metrics = {
                "available": True,
                "status_label": "Доступен для чтения",
                "size_mb": round(log_stat.st_size / (1024 * 1024), 2),
                "modified_at": datetime.fromtimestamp(log_stat.st_mtime).strftime("%d.%m.%Y %H:%M:%S"),
            }
        elif os.access(log_path.parent, os.W_OK):
            log_metrics["status_label"] = "Ожидает первой записи"
    except OSError:
        log_metrics["status_label"] = "Нет доступа к файлу"

    try:
        import platform
        python_version = platform.python_version()
    except Exception:
        python_version = sys.version.split()[0]

    degraded_workers = [item for item in workers if item.get("state") in {"restarting", "cooldown", "stopped"}]
    production_config_warning = (not settings.LOCAL_DEMO) and (settings.DEBUG or not settings.SECRET_KEY_CONFIGURED)
    if not databases_ok:
        health = {"state": "critical", "label": "Есть сбой базы данных", "detail": "Как минимум одна база не ответила на SELECT 1. Проверьте список баз ниже и файл журнала."}
    elif http_metrics["server_errors_24h"] or degraded_workers or production_config_warning:
        reasons = []
        if http_metrics["server_errors_24h"]:
            reasons.append(f"HTTP 5xx за 24 ч: {http_metrics['server_errors_24h']}")
        if degraded_workers:
            reasons.append(f"фоновые задачи с проблемным статусом: {len(degraded_workers)}")
        if production_config_warning:
            reasons.append("проверьте настройки DEBUG и SECRET_KEY")
        health = {"state": "attention", "label": "Требует внимания", "detail": "; ".join(reasons) + "."}
    else:
        health = {"state": "ok", "label": "Основные проверки пройдены", "detail": "Базы данных отвечают. В журнале последних 24 часов не найдено HTTP 5xx; состояние фоновых задач показано ниже."}

    checked_at = now.strftime("%d.%m.%Y %H:%M:%S UTC")
    return {
        "workers": workers,
        "health": health,
        "checked_at": checked_at,
        "database_checks": database_checks,
        "databases_healthy": sum(item["state"] == "ok" for item in database_checks),
        "databases_total": len(database_checks),
        "databases_ok": databases_ok,
        "http_metrics": http_metrics,
        "queue_metrics": queue_metrics,
        "queue_statuses": queue_statuses,
        "integrations": integrations,
        "process": {
            "started_at": started_at,
            "uptime_seconds": uptime_seconds,
            "python_version": python_version,
            "pid": os.getpid(),
            "mode": "Локальный демо-режим" if settings.LOCAL_DEMO else "Рабочий режим",
            "debug_enabled": bool(settings.DEBUG),
            "secret_key_configured": bool(settings.SECRET_KEY_CONFIGURED),
        },
        "disk_metrics": disk_metrics,
        "log_metrics": log_metrics,
    }


@admin_bp.route("/system/runtime")
@super_admin_required
def system_runtime(current_user):
    """Detailed admin-only runtime, diagnostics and recovery actions."""
    from services.maintenance import list_database_backups
    try:
        recent_backups = list_database_backups(limit=5)
    except OSError:
        logger.exception("database_backup_list_unavailable")
        recent_backups = []
    return render_template("system/runtime.html", recent_backups=recent_backups, **_runtime_health_snapshot())


@admin_bp.get("/system/runtime/status")
@super_admin_required
def system_runtime_status(current_user):
    response = jsonify({"ok": True, **_runtime_health_snapshot()})
    response.headers["Cache-Control"] = "no-store"
    return response


@admin_bp.route("/system/maintenance")
@super_admin_required
def system_maintenance(current_user):
    from services.database_guardian import guardian_status
    from services.maintenance import list_database_backups
    try:
        backups = list_database_backups(limit=6)
    except OSError:
        logger.exception("database_backup_list_unavailable")
        backups = []
    return render_template(
        "system/maintenance.html",
        event_count=EventQuota.query.count(),
        lesson_count=Lesson.query.count(),
        guardian=guardian_status(),
        backups=backups,
    )


@admin_bp.route("/system/backup", methods=["POST"])
@super_admin_required
def create_manual_database_backup(current_user):
    """Create a user-requested consistent snapshot of all five SQLite databases."""
    from services.maintenance import create_database_backup
    try:
        backup_path = create_database_backup(automatic=False)
        logger.info("manual_database_backup_created actor_id=%s file=%s", current_user.id, backup_path.name)
        flash(f"Резервная копия успешно создана: {backup_path.name}", "success")
    except Exception as error:
        logger.exception("manual_database_backup_failed actor_id=%s", current_user.id)
        flash(f"Не удалось создать резервную копию ({type(error).__name__}). Данные не удалены.", "danger")
    return redirect(url_for("admin.system_maintenance"))


@admin_bp.route("/system/backup/check", methods=["POST"])
@super_admin_required
def check_database_backup_action(current_user):
    """Verify a backup archive and all SQLite files without changing live data."""
    from services.maintenance import verify_database_backup
    archive_name = str(request.form.get("backup_name", ""))
    try:
        result = verify_database_backup(archive_name)
        logger.info("database_backup_verified actor_id=%s file=%s databases=%s", current_user.id, result["name"], result["database_count"])
        flash(f"Копия проверена: ZIP исправен, целостность всех {result['database_count']} баз подтверждена ({result['name']}). Данные сайта не изменялись.", "success")
    except Exception as error:
        logger.exception("database_backup_verification_failed actor_id=%s file=%s", current_user.id, archive_name)
        flash(f"Проверка резервной копии не пройдена ({type(error).__name__}). Восстановление не запускалось.", "danger")
    return redirect(url_for("admin.system_maintenance"))

@admin_bp.route("/system/restore", methods=["POST"])
@super_admin_required
def restore_database_backup_action(current_user):
    """Restore a complete verified backup; only the super administrator may do this."""
    from services.maintenance import restore_database_backup
    archive_name = str(request.form.get("backup_name", ""))
    try:
        restored = restore_database_backup(archive_name, db)
        logger.warning("manual_database_restore_completed actor_id=%s file=%s", current_user.id, restored.name)
        flash(f"Данные восстановлены из копии {restored.name}. Перед восстановлением создана страховочная копия.", "success")
    except Exception as error:
        logger.exception("manual_database_restore_failed actor_id=%s file=%s", current_user.id, archive_name)
        flash(f"Восстановление не выполнено ({type(error).__name__}). Текущие данные сохранены либо возвращены из страховочной копии.", "danger")
    return redirect(url_for("admin.system_maintenance"))


@admin_bp.route("/system/clear-events", methods=["POST"])
@super_admin_required
def clear_events(current_user):
    """Completely remove event records and every related registration/history row."""
    try:
        event_count = EventQuota.query.count()
        from services.activity_chats import close_activity_chat
        from database import ActivityChat
        for group in ActivityChat.query.filter_by(kind='event', active=True).all():
            close_activity_chat('event', group.activity_id)
        # Delete dependent records first. These tables live across several SQLAlchemy
        # binds, so do not rely on ORM cascades or cross-database foreign-key behavior.
        participation_count = DayParticipation.query.delete(synchronize_session=False)
        day_count = EventDay.query.delete(synchronize_session=False)
        direction_link_count = QuotaDirection.query.delete(synchronize_session=False)
        chat_link_count = EventQuotaChat.query.delete(synchronize_session=False)
        refusal_count = EventQuotaDecline.query.delete(synchronize_session=False)
        leader_count = EventLeader.query.delete(synchronize_session=False)
        activity_count = StudentActivity.query.filter(StudentActivity.quota_id.isnot(None)).delete(synchronize_session=False)
        # Competition announcements are independent content; keep them but remove stale
        # references to event IDs that are about to disappear.
        CompetitionAnnouncement.query.filter(CompetitionAnnouncement.quota_id.isnot(None)).update(
            {CompetitionAnnouncement.quota_id: None}, synchronize_session=False
        )
        EventQuota.query.delete(synchronize_session=False)
        # Permanent rooms are independent of individual event records.
        ActivityChat.query.filter_by(kind='event').delete(synchronize_session=False)
        from database import AdministrativeOrder, OrderDeliveryJob
        from services.orders import delete_order_files
        order_files = AdministrativeOrder.query.filter_by(target_kind='event').all()
        order_ids = [item.id for item in order_files]
        if order_ids:
            OrderDeliveryJob.query.filter(OrderDeliveryJob.order_id.in_(order_ids)).delete(synchronize_session=False)
        AdministrativeOrder.query.filter_by(target_kind='event').delete(synchronize_session=False)
        db.session.commit()
        delete_order_files(order_files)
        flash(
            "База мероприятий полностью очищена без резервной копии. "
            f"Удалено мероприятий: {event_count}, дат: {day_count}, записей/отметок посещения: {participation_count}, "
            f"отказов: {refusal_count}. Все связи и связанные журнальные записи удалены.",
            "success",
        )
    except Exception:
        db.session.rollback()
        logger.exception("Failed to clear events by admin %s", current_user.id)
        flash("Не удалось очистить мероприятия. Изменения отменены.", "danger")
    return redirect(url_for("admin.system_maintenance"))

@admin_bp.route("/system/clear-lessons", methods=["POST"])
@super_admin_required
def clear_lessons(current_user):
    try:
        deleted = Lesson.query.delete(synchronize_session=False)
        db.session.commit()
        flash(f"База занятий очищена. Удалено занятий: {deleted}.", "success")
    except Exception:
        db.session.rollback()
        logger.exception("Failed to clear lessons by admin %s", current_user.id)
        flash("Не удалось очистить занятия. Изменения отменены.", "danger")
    return redirect(url_for("admin.system_maintenance"))

def _mark_bot_history_cleared(connection):
    """Hide completed delivery receipts while keeping durable deduplication keys.

    In-flight, blocked and failed jobs remain visible; removing those jobs would
    risk losing an announcement or sending it twice after a scheduler restart.
    """
    when = datetime.utcnow()
    key = "bot_delivery_history_visible_since"
    changed = connection.execute(
        PortalSetting.__table__.update().where(PortalSetting.key == key).values(
            value=when.isoformat(timespec="microseconds"), updated_at=when))
    if not changed.rowcount:
        connection.execute(PortalSetting.__table__.insert().values(
            key=key, value=when.isoformat(timespec="microseconds"), updated_at=when))


@admin_bp.route("/system/clear-logs", methods=["POST"])
@super_admin_required
def clear_logs(current_user):
    """Delete ALL persisted journal tables, NOT queued or delivered messages.

    The durable delivery outbox is operational data, not a log. Deleting it
    would silently lose pending broadcasts or cause duplicate publications.
    """
    if request.form.get("confirmation", "").strip() != "ОЧИСТИТЬ":
        flash("Для очистки всех журналов введите ОЧИСТИТЬ.", "danger")
        return redirect(url_for("admin.system_maintenance"))
    from database import BotJournalEvent
    try:
        # All three log tables share the system database: delete atomically.
        with db.engines["system"].begin() as connection:
            activity = connection.execute(StudentActivity.__table__.delete()).rowcount
            audit = connection.execute(HttpAuditLog.__table__.delete()).rowcount
            bots = connection.execute(BotJournalEvent.__table__.delete()).rowcount
            _mark_bot_history_cleared(connection)
        flash(
            f"Журнал действий очищен. Стерто записей: действия {activity}, "
            f"HTTP {audit}, Telegram/VK/MAX {bots}. "
            "Очередь публикаций и данные студентов сохранены.", "success"
        )
    except Exception:
        logger.exception("Cannot clear all journals; actor=%s", current_user.id)
        flash("Журналы не удалось очистить. Проверьте серверные логи.", "danger")
    return redirect(url_for("admin.system_maintenance"))

@admin_bp.route("/system/clear-bot-journal", methods=["POST"])
@super_admin_required
def clear_bot_journal(current_user):
    """Clear TG/VK/MAX event metadata without dropping transport jobs."""
    if request.form.get("confirmation", "").strip() != "БОТЫ":
        flash("Для очистки журнала ботов введите БОТЫ.", "danger")
        return redirect(url_for("admin.bot_journal"))
    from database import BotJournalEvent
    try:
        with db.engines["system"].begin() as connection:
            deleted = connection.execute(BotJournalEvent.__table__.delete()).rowcount
            _mark_bot_history_cleared(connection)
        flash(f"Журнал Telegram/VK/MAX очищен: {deleted} записей. Очередь доставки сохранена.", "success")
    except Exception:
        logger.exception("Cannot clear messenger journal; actor=%s", current_user.id)
        flash("Не удалось очистить журнал ботов.", "danger")
    return redirect(url_for("admin.bot_journal"))

@admin_bp.route("/system/clear-statistics", methods=["POST"])
@super_admin_required
def clear_statistics(current_user):
    """Wipe visit/refusal facts used to calculate overall statistics; retain events and lessons."""
    try:
        snapshot_stats = StudentQuotaStat.query.delete(synchronize_session=False)
        active_refusals = EventQuotaDecline.query.delete(synchronize_session=False)
        attendance_records = DayParticipation.query.delete(synchronize_session=False)
        activity_records = StudentActivity.query.filter(
            StudentActivity.action.in_(["event_registered", "event_unregistered", "quota_declined"])
        ).delete(synchronize_session=False)
        db.session.commit()
        flash(
            "Общая статистика очищена без сохранения истории. "
            f"Удалено записей: посещений/регистраций — {attendance_records}, отказов — {active_refusals}, "
            f"сводных показателей — {snapshot_stats}, записей журнала мероприятий — {activity_records}.",
            "success",
        )
    except Exception:
        db.session.rollback()
        logger.exception("Failed to clear statistics by admin %s", current_user.id)
        flash("Не удалось очистить общую статистику. Изменения отменены.", "danger")
    return redirect(url_for("admin.system_maintenance"))

@admin_bp.route("/students/add", methods=["POST"], endpoint="add_student")
@super_admin_required
def add_student(current_user):
    full_name = " ".join(request.form.get("full_name", "").split())
    group = request.form.get("group", "").strip()
    phone = request.form.get("phone", "").strip()
    education_type = request.form.get("education_type", "institute")
    if education_type not in {"college", "institute"}: education_type = "institute"
    tg_raw = request.form.get("tg_id", "").strip()
    direction_ids = request.form.getlist("direction_ids", type=int)
    status = request.form.get("status", DirectionStatus.ACTIVE.value)
    if status not in {x.value for x in DirectionStatus}:
        status = DirectionStatus.ACTIVE.value
    if status == DirectionStatus.REJECTED.value:
        flash("Отклонять заявление нужно отдельно с обязательной причиной отказа.", "danger")
        return redirect(url_for("admin.students_management"))
    if not full_name:
        flash("ФИО студента обязательно.", "danger")
        return redirect(url_for("admin.students_management"))
    from services.student_validation import student_duplicate_message
    duplicate_error = student_duplicate_message(full_name, phone)
    if duplicate_error:
        flash(duplicate_error, "danger")
        return redirect(url_for("admin.students_management"))
    try:
        tg_id = int(tg_raw) if tg_raw else -int(uuid.uuid4().int % 8_500_000_000_000_000_000)
        if Student.query.filter_by(tg_id=tg_id).first():
            flash("Такой Telegram ID уже привязан к другому студенту.", "danger")
            return redirect(url_for("admin.students_management"))
        student = Student(full_name=full_name, group=group, phone=phone, email=None, education_type=education_type, tg_id=tg_id)
        db.session.add(student)
        db.session.flush()
        clean_dids = []
        for did in direction_ids:
            if did not in clean_dids and Direction.query.get(did):
                clean_dids.append(did)
                db.session.execute(student_directions.insert().values(
                    student_id=student.id, direction_id=did, status=status
                ))
        record_activity("student_created", f'Создана карточка студента «{full_name}».', student_id=student.id)
        db.session.commit()
        flash(f"Студент «{full_name}» добавлен.", "success")
    except Exception:
        db.session.rollback()
        logger.exception("Unable to add student")
        flash("Не удалось добавить студента.", "danger")
    return redirect(url_for("admin.students_management"))

@admin_bp.route("/students/<int:sid>", methods=["GET"], endpoint="student_detail")
@login_required
def student_detail(sid, current_user):
    """Read-only profile; staff see only memberships in their granted directions."""
    student = Student.query.get_or_404(sid)
    if current_user.role == UserRole.STAFF.value:
        from services.staff_access import direction_ids as staff_direction_ids
        permitted = set(staff_direction_ids(current_user, 'students', 'view'))
        links = db.session.execute(student_directions.select().where(
            (student_directions.c.student_id == student.id) &
            (student_directions.c.direction_id.in_(permitted or {-1}))
        )).fetchall()
        visible_ids = {int(row.direction_id) for row in links if row.direction_id is not None}
        if not visible_ids:
            abort(404)
        visible_directions = Direction.query.filter(Direction.id.in_(visible_ids)).order_by(Direction.name).all()
    else:
        visible_directions = list(student.directions)
    from services.student_contacts import public_student_contacts
    messenger_contacts = public_student_contacts([student.id]).get(student.id, {})
    return render_template("students/view.html", student=student,
                           visible_directions=visible_directions,
                           is_staff_profile=current_user.role == UserRole.STAFF.value,
                           messenger_contacts=messenger_contacts)


@admin_bp.route("/students/<int:sid>/edit", methods=["GET", "POST"], endpoint="edit_student")
@login_required
def edit_student(sid, current_user):
    student = Student.query.get_or_404(sid)
    if current_user.role == UserRole.OBSERVER.value:
        flash("Карточки студентов доступны только для просмотра.", "info")
        return redirect(request.referrer or url_for("admin.students_management"))
    if request.method == "POST":
        full_name = " ".join(request.form.get("full_name", "").split())
        group = request.form.get("group", "").strip()
        phone = request.form.get("phone", "").strip()
        education_type = request.form.get("education_type", student.education_type or "institute")
        if education_type not in {"college", "institute"}: education_type = student.education_type or "institute"
        tg_raw = request.form.get("tg_id", "").strip()
        if not full_name:
            flash("ФИО студента обязательно.", "danger")
            return redirect(url_for("admin.edit_student", sid=sid))
        from services.student_validation import (
            normalize_full_name, normalize_phone, student_duplicate_message,
        )
        name_changed = normalize_full_name(full_name) != normalize_full_name(student.full_name)
        phone_changed = normalize_phone(phone) != normalize_phone(student.phone)
        duplicate_error = None
        if name_changed or phone_changed:
            duplicate_error = student_duplicate_message(
                full_name, phone, exclude_id=student.id,
                check_name=name_changed, check_phone=phone_changed,
            )
        if duplicate_error:
            flash(duplicate_error, "danger")
            return redirect(url_for("admin.edit_student", sid=sid))
        student.full_name = full_name
        student.group = group
        student.phone = phone
        student.education_type = education_type
        if tg_raw:
            try:
                new_tg = int(tg_raw)
                duplicate = Student.query.filter(Student.tg_id == new_tg, Student.id != sid).first()
                if duplicate:
                    flash("Этот Telegram ID уже используется другим студентом.", "danger")
                    return redirect(url_for("admin.edit_student", sid=sid))
                student.tg_id = new_tg
            except ValueError:
                flash("Telegram ID должен быть числом.", "danger")
                return redirect(url_for("admin.edit_student", sid=sid))
        record_activity("student_updated", f'Обновлена карточка студента «{student.full_name}».', student_id=student.id)
        db.session.commit()
        flash("Карточка студента обновлена.", "success")
        return redirect(url_for("admin.students_management"))
    from services.student_contacts import public_student_contacts
    messenger_contacts = public_student_contacts([student.id]).get(student.id, {})
    return render_template("students/form.html", student=student, messenger_contacts=messenger_contacts)

@admin_bp.route("/students/<int:sid>/delete", methods=["POST"], endpoint="delete_student")
@login_required
def delete_student(sid, current_user):
    student = Student.query.get_or_404(sid)
    if User.query.filter_by(student_id=sid).first():
        flash('У студента есть учётная запись сотрудника. Сначала отключите связь через безопасную административную процедуру.', 'danger')
        return redirect(url_for('admin.students_management'))
    name = student.full_name
    try:
        # Capture every direction covered by a personal membership or leadership row.
        direction_ids = {
            int(row.direction_id) for row in db.session.execute(
                student_directions.select().where(student_directions.c.student_id == sid)
            ).fetchall()
        }
        direction_ids.update(int(row.direction_id) for row in StudentLeadership.query.filter_by(student_id=sid).all())
        # Remove dependent records and membership rows first, while retaining invite
        # cache entries long enough to revoke the actual Telegram invite links.
        # Remove records that reference the student before deleting the profile.
        # Several of these tables live on separate SQLite binds in this project.
        DayParticipation.query.filter_by(student_id=sid).delete(synchronize_session=False)
        StudentQuotaStat.query.filter_by(student_id=sid).delete(synchronize_session=False)
        StudentLeadership.query.filter_by(student_id=sid).delete(synchronize_session=False)
        EventLeader.query.filter_by(student_id=sid).delete(synchronize_session=False)
        ApplicationDecision.query.filter_by(student_id=sid).delete(synchronize_session=False)
        EventQuotaDecline.query.filter_by(student_id=sid).delete(synchronize_session=False)
        StudentActivity.query.filter_by(student_id=sid).delete(synchronize_session=False)
        db.session.execute(student_directions.delete().where(student_directions.c.student_id == sid))
        db.session.flush()
        if direction_ids:
            try:
                from services.telegram import remove_student_from_direction_chats_for_ids
                remove_student_from_direction_chats_for_ids(student, direction_ids)
            except Exception:
                logger.exception("Could not revoke Telegram chats during deletion of student #%s", sid)
        # Keep invite links until the Telegram revocation routine has read them.
        StudentInviteLink.query.filter_by(student_id=sid).delete(synchronize_session=False)
        record_activity("student_deleted", f'Удалена карточка студента «{name}».', student_id=sid)
        db.session.delete(student)
        db.session.commit()
        flash(f"Студент «{name}» и его связанные записи удалены; приглашения отозваны, где это разрешено Telegram.", "success")
    except Exception:
        db.session.rollback()
        logger.exception("Unable to delete student record")
        flash("Не удалось удалить студента. Изменения отменены.", "danger")
    return redirect(url_for("admin.students_management"))

@admin_bp.route("/api/students/search")
@super_admin_required
def search_students(current_user):
    """Search students by full name or group without loading the entire roster into the browser."""
    query = " ".join(str(request.args.get("q") or "").split())[:100]
    if len(query) < 2:
        return jsonify({"items": []})
    pattern = f"%{query}%"
    rows = Student.query.filter(Student.council_registered.is_(True), or_(Student.full_name.ilike(pattern), Student.group.ilike(pattern))) \
        .order_by(Student.full_name.asc()).limit(40).all()
    return jsonify({"items": [{
        "id": row.id, "full_name": row.full_name, "group": row.group or "Группа не указана",
        "education_type": row.education_type or "institute",
        "telegram_username": (row.telegram_username or "").lstrip("@"),
    } for row in rows]})


@admin_bp.route("/students/groups")
@super_admin_required
def student_groups(current_user):
    """One-page roster overview for safe whole-group deletion."""
    group_rows = db.session.query(
        Student.group.label("group_name"), func.count(Student.id).label("student_count")
    ).filter(Student.council_registered.is_(True), Student.group.is_not(None), func.trim(Student.group) != "") \
     .group_by(Student.group).order_by(func.lower(Student.group)).all()
    group_names = [row.group_name for row in group_rows]
    members_by_group = {name: [] for name in group_names}
    if group_names:
        # One ordered query keeps the page scalable; only a short preview is rendered per group.
        members = db.session.query(Student.group, Student.full_name).filter(
            Student.council_registered.is_(True), Student.group.in_(group_names)
        ).order_by(Student.full_name.asc()).all()
        for group_name, full_name in members:
            bucket = members_by_group.get(group_name)
            if bucket is not None:
                bucket.append(full_name)
    groups = [{"group_name": row.group_name, "student_count": row.student_count,
               "preview": members_by_group.get(row.group_name, [])[:5],
               "remaining": max(0, row.student_count - 5)} for row in group_rows]
    no_group_count = Student.query.filter(Student.council_registered.is_(True),
        or_(Student.group.is_(None), func.trim(Student.group) == "")).count()
    return render_template("students/groups.html", groups=groups, no_group_count=no_group_count,
                           total_students=Student.query.filter(Student.council_registered.is_(True)).count())


@admin_bp.route("/students/groups/delete", methods=["POST"])
@super_admin_required
def delete_student_group(current_user):
    """Delete every student with the exact selected group name, including dependent records."""
    group_name = str(request.form.get("group_name") or "").strip()[:100]
    confirm_text = str(request.form.get("confirm_text") or "").strip()
    if not group_name:
        flash("Выберите конкретную учебную группу.", "danger")
        return redirect(url_for("admin.student_groups"))
    students = Student.query.filter(Student.council_registered.is_(True),
                                    Student.group == group_name).order_by(Student.id.asc()).all()
    if not students:
        flash("В этой группе больше нет студентов.", "warning")
        return redirect(url_for("admin.student_groups"))
    if confirm_text != f"УДАЛИТЬ {group_name}":
        flash("Для подтверждения введите точное название группы в формате, показанном в окне.", "danger")
        return redirect(url_for("admin.student_groups"))

    student_ids = [student.id for student in students]
    if User.query.filter(User.student_id.in_(student_ids)).first():
        flash('Группа содержит студентов с учётными записями сотрудников. Массовое удаление заблокировано.', 'danger')
        return redirect(url_for('admin.student_groups'))
    direction_map = {}
    for student in students:
        direction_map[student.id] = {
            int(row.direction_id) for row in db.session.execute(
                student_directions.select().where(student_directions.c.student_id == student.id)
            ).fetchall()
        }
        direction_map[student.id].update(
            int(row.direction_id) for row in StudentLeadership.query.filter_by(student_id=student.id).all()
        )
    group_label = group_name
    try:
        # Best-effort Telegram cleanup while student records and chat membership data still exist.
        try:
            from services.telegram import remove_student_from_direction_chats_for_ids
            for student in students:
                if direction_map.get(student.id):
                    remove_student_from_direction_chats_for_ids(student, direction_map[student.id])
        except Exception:
            logger.exception("Could not revoke all Telegram group memberships during bulk deletion")

        DayParticipation.query.filter(DayParticipation.student_id.in_(student_ids)).delete(synchronize_session=False)
        StudentQuotaStat.query.filter(StudentQuotaStat.student_id.in_(student_ids)).delete(synchronize_session=False)
        StudentLeadership.query.filter(StudentLeadership.student_id.in_(student_ids)).delete(synchronize_session=False)
        EventLeader.query.filter(EventLeader.student_id.in_(student_ids)).delete(synchronize_session=False)
        StudentInviteLink.query.filter(StudentInviteLink.student_id.in_(student_ids)).delete(synchronize_session=False)
        ApplicationDecision.query.filter(ApplicationDecision.student_id.in_(student_ids)).delete(synchronize_session=False)
        EventQuotaDecline.query.filter(EventQuotaDecline.student_id.in_(student_ids)).delete(synchronize_session=False)
        StudentActivity.query.filter(StudentActivity.student_id.in_(student_ids)).delete(synchronize_session=False)
        db.session.execute(student_directions.delete().where(student_directions.c.student_id.in_(student_ids)))
        for student in students:
            record_activity("student_deleted", f'Удалён студент «{student.full_name}» в результате массового удаления группы «{group_label}».', student_id=student.id)
        Student.query.filter(Student.id.in_(student_ids)).delete(synchronize_session=False)
        db.session.commit()
        flash(f"Группа «{group_label}» удалена после выпуска: профилей удалено — {len(student_ids)}. Связанные заявки, роли, статистика и посещаемость очищены.", "success")
    except Exception:
        db.session.rollback()
        logger.exception("Unable to delete student group %s", group_label)
        flash("Не удалось удалить группу: операция отменена, данные не изменены.", "danger")
    return redirect(url_for("admin.student_groups"))


@admin_bp.route("/students")
@login_required
def students_management(current_user):
    # Staff and direction leaders must work inside their grant/appointment scope;
    # never expose the institution-wide student register through this route.
    if current_user.role == UserRole.SUPER_ADMIN.value:
        return redirect(url_for("staff.students"))
    if current_user.role == UserRole.STAFF.value:
        return redirect(url_for("staff.workspace"))
    if current_user.role == UserRole.LEADER.value:
        return redirect(url_for("directions.directions_list"))
    status_filter = request.args.get("status", "all")
    links = db.session.execute(student_directions.select()).fetchall()
    by_student = {}
    for link in links:
        by_student.setdefault(link.student_id, []).append(link)

    students = []
    all_students = Student.query.options(selectinload(Student.directions)).filter(
        Student.council_registered.is_(True)).order_by(Student.full_name).all()
    quotas_for_attendance = EventQuota.query.options(
        selectinload(EventQuota.days).selectinload(EventDay.participations)
    ).all()
    quota_by_id = {quota.id: quota for quota in quotas_for_attendance}
    attended_quota_ids_by_student = {}
    for quota in quotas_for_attendance:
        for day in quota.days:
            for participation in day.participations:
                if participation.status == "attended" and participation.student_id is not None:
                    attended_quota_ids_by_student.setdefault(participation.student_id, set()).add(quota.id)

    leadership_ids = {
        row.student_id for row in StudentLeadership.query.with_entities(StudentLeadership.student_id).all()
    }
    counts = {"total": 0, "pending": 0, "active": 0, "rejected": 0, "interview": 0}
    for student in all_students:
        student_links = by_student.get(student.id, [])
        statuses = ["active" if getattr(link, "status", None) == "approved" else getattr(link, "status", None) for link in student_links]
        primary = next((st for st in ["pending", "interview", "active", "rejected"] if st in statuses), None)
        if primary:
            counts["total"] += 1
            if primary in counts:
                counts[primary] += 1
        if status_filter != "all" and primary != status_filter:
            continue
        student.status = primary or "—"
        student.is_direction_leader = student.id in leadership_ids
        student.attended_events = [quota_by_id[qid] for qid in sorted(attended_quota_ids_by_student.get(student.id, set()), reverse=True) if qid in quota_by_id]
        students.append(student)

    from services.student_roles import student_leadership_labels
    leadership_labels = student_leadership_labels(
        StudentLeadership.query.filter(StudentLeadership.student_id.in_([s.id for s in students])).all(),
    ) if students else {}
    for student in students:
        student.leadership_labels = leadership_labels.get(student.id, [])

    from services.student_contacts import public_student_contacts
    messenger_by_student = public_student_contacts(s.id for s in students)

    # Refusal counters are aggregated in SQL so the student list does not load
    # every refusal row into Python when the institution grows.
    decline_counts = {
        student_id: total
        for student_id, total in db.session.query(
            EventQuotaDecline.student_id, func.count(EventQuotaDecline.id)
        ).group_by(EventQuotaDecline.student_id).all()
    }
    return render_template("students/list.html", students=students, stats=counts, status_filter=status_filter,
                           directions=Direction.query.order_by(Direction.name).all(), decline_counts=decline_counts,
                           messenger_by_student=messenger_by_student)

@admin_bp.route("/most-active-students")
@analytics_view_required
def most_active_students(current_user):
    # Aggregate the stats database in SQL and load all referenced people in two
    # bounded lookups instead of issuing one SELECT per winner.
    totals_query = db.session.query(
        StudentQuotaStat.direction_id, StudentQuotaStat.student_id,
        func.sum(StudentQuotaStat.attended_count).label("attended_count"),
    )
    if current_user.role in {UserRole.STAFF.value, UserRole.SUPER_ADMIN.value}:
        visible_ids = _staff_visible_direction_ids(current_user, ('statistics',))
        totals_query = totals_query.filter(StudentQuotaStat.direction_id.in_(visible_ids)) if visible_ids else totals_query.filter(false())
    totals = totals_query.group_by(StudentQuotaStat.direction_id, StudentQuotaStat.student_id).all()
    best_by_direction = {}
    for direction_id, student_id, count in totals:
        candidate = int(count or 0)
        previous = best_by_direction.get(direction_id)
        if previous is None or candidate > previous["count"]:
            best_by_direction[direction_id] = {"student_id": student_id, "count": candidate}
    student_ids = {row["student_id"] for row in best_by_direction.values()}
    direction_ids = set(best_by_direction)
    students = {row.id: row for row in Student.query.filter(Student.id.in_(student_ids)).all()} if student_ids else {}
    directions_by_id = {row.id: row for row in Direction.query.filter(Direction.id.in_(direction_ids)).all()} if direction_ids else {}
    winners = []
    for direction_id, winner in best_by_direction.items():
        student, direction = students.get(winner["student_id"]), directions_by_id.get(direction_id)
        if student and direction:
            winners.append({"student": student, "direction": direction, "count": winner["count"]})
    ranking = sorted(winners, key=lambda x: (x["direction"].name.casefold(), -x["count"]))
    directions_query = Direction.query
    if current_user.role in {UserRole.STAFF.value, UserRole.SUPER_ADMIN.value}:
        visible_ids = _staff_visible_direction_ids(current_user, ('statistics',))
        directions_query = directions_query.filter(Direction.id.in_(visible_ids)) if visible_ids else directions_query.filter(false())
    return render_template("students/most_active.html", ranking=ranking, directions=directions_query.order_by(Direction.name.asc()).all())

# ✅ ПОЛОЖИТЕЛЬНОЕ РЕШЕНИЕ: сразу активирует участника (student_directions)
@directions_bp.route("/<int:did>/approve/<int:sid>", methods=["POST"])
@login_required
def approve_student(did, sid, current_user):
    from services.applications import set_application_status
    ok, msg, invite_count = set_application_status(
        sid, did, DirectionStatus.ACTIVE.value, actor_user_id=current_user.id, source="web"
    )
    if ok:
        student = Student.query.get(sid)
        flash(f"Студент {student.full_name} принят и сразу активирован. Отправлено приглашений: {invite_count}", "success")
    else:
        flash(msg, "danger")
    return redirect(url_for("directions.direction_detail", did=did))

# ✅ ИСПРАВЛЕННАЯ АКТИВАЦИЯ СТУДЕНТА (переводит в ACTIVE)
@directions_bp.route("/<int:did>/activate/<int:sid>", methods=["POST"])
@login_required
def activate_student(did, sid, current_user):
    from services.applications import can_user_manage_direction
    candidate = Student.query.get(sid)
    if not candidate or not can_user_manage_direction(current_user.id, did, candidate.education_type):
        abort(403)
    link = db.session.execute(student_directions.select().where(
        (student_directions.c.student_id == sid) & (student_directions.c.direction_id == did)
    )).fetchone()
    
    if link:
        if link.status == DirectionStatus.REJECTED.value:
            from services.applications import active_application_block
            block = active_application_block(sid, did)
            if block:
                flash(f"Блокировка действует до {block.blocked_until.strftime('%d.%m.%Y %H:%M')}.", "danger")
            else:
                flash("Отклонённую заявку нельзя активировать напрямую — студент должен подать новое заявление.", "danger")
            return redirect(url_for("directions.direction_detail", did=did))
        db.session.execute(student_directions.update().where(
            (student_directions.c.student_id == sid) & (student_directions.c.direction_id == did)
        ).values(status=DirectionStatus.ACTIVE.value))
        student = Student.query.get(sid)
        direction = Direction.query.get(did)
        record_activity("application_status_changed", "Студент переведён в статус «active». ", student_id=sid, direction_id=did)
        db.session.commit()
        from services.applications import notify_approval
        notify_approval(student, direction, send_invites=True, immediately_active=True)

        flash(f"Студент {student.full_name} активирован", "success")
    else:
        flash("Связь студента с направлением не найдена", "danger")
        
    return redirect(url_for("directions.direction_detail", did=did))

# ✅ ОТКЛОНЕНИЕ ЗАЯВКИ
@directions_bp.route("/<int:did>/reject/<int:sid>", methods=["POST"])
@login_required
def reject_student(did, sid, current_user):
    from services.applications import set_application_status
    reason = " ".join(str(request.form.get("reason") or "").split())
    ok, msg, _ = set_application_status(
        sid, did, DirectionStatus.REJECTED.value, reason=reason,
        actor_user_id=current_user.id, source="web",
    )
    flash(msg if ok else msg, "success" if ok else "danger")
    return redirect(url_for("directions.direction_detail", did=did))

@admin_bp.route("/leadership", methods=["GET", "POST"], endpoint="manage_leadership")
@login_required
def manage_leadership(current_user):
    if current_user.role != UserRole.SUPER_ADMIN.value:
        flash("Доступ к назначению ролей есть только у главного администратора.", "danger")
        return redirect(url_for("admin.dashboard"))

    role_labels = {
        "council_chair": "Председатель студсовета",
        "council_deputy_college": "Заместитель председателя студсовета по колледжу",
        "council_deputy_institute": "Заместитель председателя студсовета по институту",
        "direction_head": "Глава направления",
        "direction_deputy": "Заместитель главы направления",
    }
    global_roles = {
        "Председатель студсовета",
        "Представитель студсовета",
        "Заместитель председателя студсовета по колледжу",
        "Заместитель председателя студсовета по институту",
        # Legacy display names remain recognized while old data is migrated.
        "Заместитель председателя волонтёрки по колледжу",
        "Заместитель председателя волонтёрки по институту",
    }

    def notification_targets(role_name, direction):
        normalized_role = " ".join(str(role_name or "").casefold().replace("ё", "е").split())
        if normalized_role in {"председатель студсовета", "председатель волонтерки", "представитель", "представитель студсовета"}:
            candidates = DirectionChat.query.filter_by(is_active=True).all()
        elif role_name in {
            "Заместитель председателя студсовета по колледжу",
            "Заместитель председателя волонтёрки по колледжу",
            "Заместитель председателя студсовета по институту",
            "Заместитель председателя волонтёрки по институту",
        }:
            cohort = "college" if role_name.endswith("по колледжу") else "institute"
            candidates = []
            for candidate in DirectionChat.query.filter_by(is_active=True).all():
                target_direction = Direction.query.get(candidate.direction_id)
                if target_direction and target_direction.available_for(cohort):
                    candidates.append(candidate)
        else:
            candidates = DirectionChat.query.filter_by(direction_id=direction.id, is_active=True).all() if direction else []
        # A chat can be linked to multiple records. Do not publish duplicate notices.
        result, seen = [], set()
        for item in candidates:
            key = str(item.chat_id or "").strip()
            if key and key not in seen:
                seen.add(key)
                result.append(item)
        return result

    def refresh_student_telegram_username(student):
        """Refresh username from Telegram when possible; the stored profile is the fallback."""
        if not settings.BOT_TOKEN:
            return
        tg_id = getattr(student, "tg_id", None)
        if not tg_id or tg_id <= 0:
            return
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{settings.BOT_TOKEN}/getChat",
                json={"chat_id": int(tg_id)}, timeout=4,
            )
            payload = response.json() if response.ok else {}
            result = payload.get("result") or {}
            if payload.get("ok") and str(result.get("id", "")) == str(tg_id):
                # An empty username is valid in Telegram; keep the field in sync.
                username = (result.get("username") or "").strip().lstrip("@")
                student.telegram_username = username[:255] or None
                db.session.flush()
        except Exception:
            # Username is optional metadata; never block a role change on lookup failure.
            logger.debug("Could not resolve Telegram username for student record #%s", student.id)

    def student_telegram_label(student):
        username = (getattr(student, "telegram_username", None) or "").strip().lstrip("@")
        return f"@{html.escape(username)}" if username else "не указан в профиле"

    def announcement_intro(student, role_name, direction):
        # Telegram username is synced from the student's Telegram profile; it is never entered manually.
        name = html.escape(student.full_name or "Студент")
        username = student_telegram_label(student)
        normalized_role = " ".join(str(role_name or "").casefold().replace("ё", "е").split())
        display_role = role_name
        # Keep the specific direction inside the position title, without separate
        # "Направление" or "Зона ответственности" fields in assignment/removal notices.
        if normalized_role in {"глава направления", "заместитель главы направления"} and direction:
            display_role = f'{role_name} «{direction.name}»'
        role = html.escape(display_role)
        return "\n".join([
            f"<b>ФИО:</b> {name}",
            f"<b>Telegram:</b> {username}",
            f"<b>Должность:</b> {role}",
        ])

    def send_role_change_notice(student, role_name, direction, action, reason=""):
        """Publish a formal role announcement to relevant chats; return (sent, attempted)."""
        refresh_student_telegram_username(student)
        targets = notification_targets(role_name, direction)
        details = announcement_intro(student, role_name, direction)
        if action == "назначен":
            body = bot_message_text("leadership_assign_group", details=details)
        else:
            reason_line = f"\n<b>Основание:</b> {html.escape(reason[:500])}" if reason else ""
            body = bot_message_text("leadership_remove_group", details=details, reason_line=reason_line)

        sent = 0
        for chat in targets:
            stable_id, error = _resolve_chat_id(chat.chat_id)
            if not stable_id:
                logger.warning("Leadership notice skipped: unable to resolve configured chat record #%s", chat.id)
                continue
            if stable_id != str(chat.chat_id):
                chat.chat_id = stable_id
            if _send_tg(stable_id, body):
                sent += 1
            else:
                logger.warning("Leadership notice delivery failed for chat record #%s", chat.id)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception("Could not persist normalized chat IDs after leadership notice")
        logger.info("Leadership %s notice: delivered %s of %s targeted chat(s)", action, sent, len(targets))
        return sent, len(targets)

    def send_personal_role_notice(student, role_name, direction, action, reason=""):
        """Deliver a professional direct notice to the student if Telegram is available."""
        tg_id = getattr(student, "tg_id", None)
        if not tg_id or tg_id <= 0:
            return False
        name = html.escape(student.full_name or "Студент")
        details = announcement_intro(student, role_name, direction)
        if action == "назначен":
            message = bot_message_text(
                "leadership_assign_personal",
                full_name=name,
                details=details,
            )
        else:
            reason_line = f"\n<b>Основание:</b> {html.escape(reason[:500])}" if reason else ""
            message = bot_message_text(
                "leadership_remove_personal",
                full_name=name,
                details=details,
                reason_line=reason_line,
            )
        if _send_tg(tg_id, message):
            return True
        logger.warning("Personal leadership notice could not be delivered (student record #%s)", student.id)
        return False

    if request.method == "POST":
        action = request.form.get("action", "")
        if action == "resolve_chair":
            from services.permissions import role_label as canonical_role_label
            retained_student_id = request.form.get("chair_student_id", type=int)
            chair_rows = [row for row in StudentLeadership.query.all()
                          if canonical_role_label(row.position_name) == "Председатель студсовета"]
            chair_ids = {row.student_id for row in chair_rows}
            if retained_student_id not in chair_ids or len(chair_ids) <= 1:
                flash("Выберите действующего председателя из конфликтующих назначений.", "warning")
            else:
                # Explicitly authorized, auditable resolution; other posts cannot
                # remove or change a chair through guessed student IDs.
                affected_students = sorted(chair_ids - {retained_student_id})
                retained = False
                for row in chair_rows:
                    if row.student_id != retained_student_id or retained:
                        db.session.delete(row)
                    else:
                        retained = True
                        row.position_name = "Председатель студсовета"
                        row.education_type = "all"
                db.session.flush()
                from services.chair_membership import (
                    sync_student_leadership_memberships,
                    role_owned_memberships_lost_after_role_change,
                )
                lost_chats_by_student = {}
                for affected_id in affected_students:
                    lost_chats_by_student[affected_id] = role_owned_memberships_lost_after_role_change(affected_id)
                    sync_student_leadership_memberships(affected_id)
                sync_student_leadership_memberships(retained_student_id)
                record_activity("chair_conflict_resolved",
                                "Главный администратор разрешил конфликт председателей; "
                                f"оставлен студент #{retained_student_id}; сняты назначения: {affected_students}.",
                                student_id=retained_student_id)
                db.session.commit()
                # Revoke memberships in Telegram chats that were granted ONLY by
                # the removed leadership roles; keep independently joined chats.
                from services.telegram import remove_student_from_direction_chats_for_ids
                for affected_id, lost_direction_ids in lost_chats_by_student.items():
                    if not lost_direction_ids:
                        continue
                    try:
                        affected_student = Student.query.get(affected_id)
                        if affected_student:
                            remove_student_from_direction_chats_for_ids(affected_student, lost_direction_ids)
                    except Exception:
                        logger.exception("Could not revoke chair-related Telegram chat access for #%s", affected_id)
                flash("Теперь у студсовета один действующий председатель. Права остальных назначений обновлены.", "success")
            return redirect(url_for("admin.manage_leadership"))
        if action == "assign":
            sid = request.form.get("student_id", type=int)
            role_key = request.form.get("role_code", "direction_head")
            role_name = role_labels.get(role_key)
            did = request.form.get("direction_id", type=int)
            education_type = request.form.get("education_type", "institute")
            if education_type not in {"college", "institute", "all"}:
                education_type = "institute"
            if role_key == "council_chair":
                education_type = "all"
            elif role_key == "council_deputy_college":
                education_type = "college"
            elif role_key == "council_deputy_institute":
                education_type = "institute"
            council_direction = Direction.query.filter_by(code="STUDCOUNCIL").first()
            is_global = role_name in global_roles if role_name else False
            all_directions = Direction.query.order_by(Direction.id.asc()).all()
            if role_key == "council_chair":
                # One appointment record is enough: role_scope('chair') covers all
                # directions, so we no longer replicate it for each direction.
                direction = council_direction or (all_directions[0] if all_directions else None)
                assignment_directions = [direction] if direction else []
            elif is_global:
                direction = council_direction
                assignment_directions = [direction] if direction else []
            else:
                direction = Direction.query.get(did) if did else None
                assignment_directions = [direction] if direction else []
            student = Student.query.get(sid) if sid else None
            from services.permissions import role_label as canonical_role_label
            if not student or not role_name or not direction or not assignment_directions:
                flash("Проверьте студента, роль и направление.", "danger")
            elif role_key == 'council_chair' and any(
                    old.student_id != sid and canonical_role_label(old.position_name) == 'Председатель студсовета'
                    for old in StudentLeadership.query.all()):
                flash("Председатель студсовета уже назначен. Сначала снимите действующего председателя.", "danger")
            else:
                # Match by normalized display role, rather than by student + direction
                # alone. This preserves a chair assignment when the same student also
                # leads a specific direction and makes repeated chair assignment idempotent.
                from services.permissions import role_label as canonical_role_label
                for target_direction in assignment_directions:
                    rows = StudentLeadership.query.filter_by(
                        student_id=sid, direction_id=target_direction.id
                    ).all()
                    existing = next((row for row in rows
                                     if canonical_role_label(row.position_name) == role_name), None)
                    if existing:
                        existing.position_name = role_name
                        existing.education_type = education_type
                    else:
                        db.session.add(StudentLeadership(
                            student_id=sid, direction_id=target_direction.id,
                            position_name=role_name, education_type=education_type
                        ))

                if role_key == 'council_chair':
                    for old in StudentLeadership.query.filter_by(student_id=sid).all():
                        if (old.direction_id != direction.id and
                                canonical_role_label(old.position_name) == 'Председатель студсовета'):
                            db.session.delete(old)
                    db.session.flush()

                # Reconcile all membership-bearing roles (chair, cohort deputies,
                # direction heads and deputies). This also preserves a membership the
                # student already selected before a role was assigned.
                from services.chair_membership import sync_student_leadership_memberships
                sync_student_leadership_memberships(student.id)
                db.session.commit()
                group_sent, group_total = send_role_change_notice(student, role_name, direction, "назначен")
                personal_sent = send_personal_role_notice(student, role_name, direction, "назначен")
                activity_direction_id = None if role_key == "council_chair" else direction.id
                record_activity("leadership_assigned", f"Назначена роль «{role_name}». Охват: {'все направления' if role_key == 'council_chair' else len(assignment_directions)}. Уведомления: {group_sent}/{group_total} чатов, личное: {'да' if personal_sent else 'нет'}.", student_id=student.id, direction_id=activity_direction_id)
                db.session.commit()
                delivered = group_sent + int(personal_sent)
                if delivered:
                    flash(f"Назначена роль «{role_name}» (охват: {'все направления' if role_key == 'council_chair' else len(assignment_directions)}). Отправлено уведомлений: {group_sent} из {group_total} чатов; личное сообщение: {'отправлено' if personal_sent else 'не доставлено'}.", "success" if group_sent == group_total else "warning")
                else:
                    flash(f"Роль назначена (охват: {'все направления' if role_key == 'council_chair' else len(assignment_directions)}), но уведомления не доставлены. Проверьте BOT_TOKEN, подключение активных Telegram-чатов к направлениям, права бота и Telegram ID студента.", "warning")

        elif action == "remove":
            lid = request.form.get("leadership_id", type=int)
            reason = request.form.get("removal_reason", "").strip()
            leader = StudentLeadership.query.get(lid) if lid else None
            if leader:
                student = leader.student
                direction = leader.direction
                role_name = leader.position_name
                group_sent, group_total = send_role_change_notice(student, role_name, direction, "снят", reason)
                personal_sent = send_personal_role_notice(student, role_name, direction, "снят", reason)
                from services.permissions import role_label as canonical_role_label, role_scope
                canonical_role = canonical_role_label(role_name)
                scope = role_scope(role_name, getattr(leader, "education_type", None))
                if scope in {"all", "college", "institute"}:
                    # Remove every duplicate row for this council role.
                    for role_row in StudentLeadership.query.filter_by(student_id=student.id).all():
                        if canonical_role_label(role_row.position_name) == canonical_role:
                            db.session.delete(role_row)
                    activity_direction_id = None
                else:
                    # Direction-specific roles are removed independently.
                    db.session.delete(leader)
                    activity_direction_id = direction.id if direction else None

                # Flush the role change first, calculate which memberships were
                # created only by the role and are no longer justified, then sync.
                db.session.flush()
                from services.chair_membership import (
                    role_owned_memberships_lost_after_role_change,
                    sync_student_leadership_memberships,
                )
                lost_direction_ids = role_owned_memberships_lost_after_role_change(student.id)
                sync_student_leadership_memberships(student.id)
                record_activity("leadership_removed", f"Снята роль «{role_name}». Уведомления: {group_sent}/{group_total} чатов, личное: {'да' if personal_sent else 'нет'}. Причина: {reason or 'не указана'}", student_id=student.id, direction_id=activity_direction_id)
                db.session.commit()
                if lost_direction_ids:
                    try:
                        from services.telegram import remove_student_from_direction_chats_for_ids
                        removed_from_chats = remove_student_from_direction_chats_for_ids(student, lost_direction_ids)
                        logger.info("Role removal revoked student #%s from %s chat(s), directions=%s", student.id, removed_from_chats, sorted(lost_direction_ids))
                    except Exception:
                        logger.exception("Could not revoke Telegram access after leadership removal for student #%s", student.id)
                delivered = group_sent + int(personal_sent)
                if delivered:
                    flash(f"Роль снята. Отправлено уведомлений: {group_sent} из {group_total} чатов; личное сообщение: {'отправлено' if personal_sent else 'не доставлено'}.", "success" if group_sent == group_total else "warning")
                else:
                    flash("Роль снята, но уведомления не доставлены. Проверьте BOT_TOKEN, связанные Telegram-чаты, права бота и Telegram ID студента.", "warning")
            else:
                flash("Назначение не найдено или уже снято.", "warning")

    raw_leaders = StudentLeadership.query.order_by(StudentLeadership.id.desc()).all()
    from services.permissions import role_label as canonical_role_label
    from services.chair_display import management_leadership_rows
    # Show exactly one chair in the main list. Historical appointments for
    # different students remain visible in the conflict-resolution control
    # until a super-admin explicitly chooses the legitimate chair.
    leaders, chair_candidates, chair_conflict_count = management_leadership_rows(
        raw_leaders, canonical_role_label
    )
    students = []  # Student lookup is server-side and paginated for large cohorts.
    directions = Direction.query.order_by(Direction.name.asc()).all()
    return render_template("leadership/manage.html", leaders=leaders, students=students,
                           directions=directions, role_labels=role_labels,
                           chair_conflict_count=chair_conflict_count,
                           chair_candidates=chair_candidates)

@admin_bp.route("/leadership-overview", endpoint="leadership_public")
@login_required
def leadership_public(current_user):
    """Read-only leadership directory; employees see only their direction's leaders."""
    leaders_query = StudentLeadership.query.options(
        selectinload(StudentLeadership.student), selectinload(StudentLeadership.direction)
    ).order_by(StudentLeadership.id.desc())
    from services.permissions import role_label as canonical_role_label, is_global_role_name
    from services.leadership_directory import leadership_cards
    direction_scope = None
    if current_user.role == UserRole.STAFF.value:
        from services.staff_access import direction_ids as staff_direction_ids
        direction_scope = set(staff_direction_ids(current_user, 'students', 'view'))
        leaders_query = leaders_query.filter(StudentLeadership.direction_id.in_(direction_scope)) if direction_scope else leaders_query.filter(db.false())
    raw_leaders = leaders_query.all() if direction_scope is None or direction_scope else []
    if direction_scope is not None:
        raw_leaders = [leader for leader in raw_leaders
                       if not is_global_role_name(leader.position_name)]
    leaders = []
    seen_chairs = set()
    for leader in raw_leaders:
        if not leader.student:
            continue
        canonical = canonical_role_label(leader.position_name)
        if canonical == "Председатель студсовета":
            key = (leader.student_id, canonical)
            if key in seen_chairs:
                continue
            seen_chairs.add(key)
        leaders.append(leader)
    cards = leadership_cards(direction_ids=direction_scope) if direction_scope is not None else leadership_cards()
    return render_template("leadership/directory.html", leaders=leaders,
                           cards=cards, can_manage=current_user.role == UserRole.SUPER_ADMIN.value)


def _lesson_message(lesson, heading="Объявление о занятии"):
    direction = lesson.direction
    direction_name = direction.name if direction else "Неуказанное направление"
    date_text = lesson.starts_at.strftime("%d.%m.%Y")
    time_text = lesson.starts_at.strftime("%H:%M")
    end_text = lesson.end_at.strftime("%H:%M")
    lines = [
        f"<b>{html.escape(heading)}</b>", "",
        f"<b>Занятие:</b> {html.escape(lesson.title)}",
        f"<b>Направление:</b> {html.escape(direction_name)}",
        f"<b>Дата:</b> {date_text}",
        f"<b>Время:</b> {time_text}–{end_text}",
    ]
    if lesson.room:
        lines.append(f"<b>Место:</b> {html.escape(lesson.room)}")
    if lesson.teacher:
        lines.append(f"<b>Ответственный:</b> {html.escape(lesson.teacher)}")
    if lesson.description:
        lines.extend(["", html.escape(lesson.description)])
    return "\n".join(lines)

def _publish_lesson_to_direction_chats(lesson, heading="Объявление о занятии"):
    """Persist chat jobs for TG/VK/MAX without blocking lesson creation.

    Return (queued, configured targets); actual delivery is asynchronous and
    its outcome is recorded in the delivery table and the bot event journal.
    """
    from services.delivery_outbox import enqueue_calendar_announcement
    result = enqueue_calendar_announcement(
        [lesson.direction_id], _lesson_message(lesson, heading),
        batch_key=f"lesson:{lesson.id}:{uuid.uuid4().hex}",
        source_type='lesson', source_id=lesson.id,
    )
    return result['queued'], result['available']


def _lesson_form_values(current_user=None):
    direction_id = request.form.get("direction_id", type=int)
    direction = Direction.query.get(direction_id) if direction_id else None
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    teacher = request.form.get("teacher", "").strip()
    room = request.form.get("room", "").strip()
    starts_raw = request.form.get("starts_at", "").strip()
    duration_raw = request.form.get("duration_minutes", "").strip()
    capacity_raw = request.form.get("capacity", "").strip()
    try:
        duration = int(duration_raw) if duration_raw else 90
    except ValueError:
        duration = -1
    try:
        capacity = int(capacity_raw) if capacity_raw else 0
    except ValueError:
        capacity = -1
    try:
        starts_at = datetime.strptime(starts_raw, "%Y-%m-%dT%H:%M")
    except ValueError:
        starts_at = None
    if not direction:
        return None, "Выберите существующее направление."
    if current_user is not None and not _lesson_can_manage_direction(current_user, direction.id):
        return None, "У вас нет прав на управление занятиями этого направления."
    if len(title) < 3:
        return None, "Название занятия должно содержать не менее трёх символов."
    if starts_at is None:
        return None, "Укажите корректные дату и время занятия."
    if not 15 <= duration <= 600:
        return None, "Продолжительность должна составлять от 15 до 600 минут."
    if capacity < 0 or capacity > 100000:
        return None, "Проверьте указанную вместимость."
    return {
        "direction_id": direction.id, "title": title[:255],
        "description": description[:10000], "teacher": teacher[:255] or None,
        "room": room[:255] or None, "starts_at": starts_at,
        "duration_minutes": duration, "capacity": capacity,
    }, None

@lessons_bp.route("/")
@login_required
def list_lessons(current_user):
    """Compatibility link: both schedules now live in one real calendar."""
    direction_id = request.args.get("direction_id", type=int)
    params = {"direction_id": direction_id} if direction_id else {}
    return redirect(url_for("admin.calendar", **params))

@lessons_bp.route("/create", methods=["GET", "POST"])
@lesson_manager_required
def create_lesson(current_user):
    directions = _lesson_directions_for_user(current_user)
    if request.method == "GET":
        requested_direction = request.args.get("direction_id", type=int)
        scope = _lesson_access_scope(current_user)
        if requested_direction and scope is not None and requested_direction not in scope:
            flash("Можно создавать занятия только в разрешённом направлении.", "warning")
            requested_direction = None
        selected_calendar_date = request.args.get("date", "")[:10]
        try:
            datetime.strptime(selected_calendar_date, "%Y-%m-%d")
        except ValueError:
            selected_calendar_date = datetime.now().strftime("%Y-%m-%d")
        selected_datetime = f"{selected_calendar_date}T09:00"
        return render_template("lessons/form.html", lesson=None, directions=directions,
                               selected_direction=requested_direction, selected_datetime=selected_datetime,
                               selected_calendar_date=selected_calendar_date,
                               return_to_calendar=request.args.get("return_to") == "calendar")
    values, error = _lesson_form_values(current_user)
    if error:
        flash(error, "danger")
        return redirect(url_for("lessons.create_lesson", direction_id=request.form.get("direction_id", type=int)))
    lesson = Lesson(**values)
    db.session.add(lesson)
    db.session.flush()
    record_activity("lesson_created", f'Создано занятие «{lesson.title}» на {lesson.starts_at.strftime("%d.%m.%Y %H:%M")}.', direction_id=lesson.direction_id)
    db.session.commit()
    try:
        from services.direction_publishing import publish_direction_announcement
        publish_direction_announcement([lesson.direction_id], lesson.title,
            f'Занятие {lesson.starts_at:%d.%m.%Y в %H:%M}. {lesson.room or "Место уточняется"}. {lesson.description or ""}',
            category='lessons', creator_user_id=current_user.id,
            channels={'site', 'dm', 'vk_dm', 'max_dm', 'staff_dm'},
            source_type='lesson', source_id=lesson.id, batch_key=f'lesson:{lesson.id}:personal')
    except Exception:
        logger.exception('Lesson #%s was saved but personal announcements could not be queued', lesson.id)
        db.session.rollback()
    sent = total = 0
    lesson_enqueue_error = False
    announce = True  # Every newly published class is announced in approved chats.
    if announce:
        try:
            sent, total = _publish_lesson_to_direction_chats(lesson)
        except Exception:
            logger.exception('Lesson #%s saved but announcement queue failed', lesson.id)
            lesson_enqueue_error = True
        if sent:
            record_activity("lesson_announced", f'Объявление о занятии «{lesson.title}» поставлено в очередь: {sent} сообщений.', direction_id=lesson.direction_id)
            db.session.commit()
    if lesson_enqueue_error:
        flash("Занятие сохранено, но очередь рассылки временно недоступна. Проверьте журнал и диагностику.", "warning")
    elif announce and total and not sent:
        flash("Занятие создано, но объявление не поставлено в очередь. Проверьте токены ботов и подключённые чаты направления.", "warning")
    elif announce and sent:
        flash(f"Занятие создано. В очереди TG/VK/MAX: {sent} сообщений.", "success")
    elif announce and not total:
        flash("Занятие создано. У направления нет активных подключённых чатов Telegram/VK/MAX для объявления.", "warning")
    else:
        flash("Занятие создано.", "success")
    if request.form.get("return_to") == "calendar":
        return redirect(url_for("admin.calendar", date=request.form.get("calendar_date") or lesson.starts_at.strftime("%Y-%m-%d")))
    return redirect(url_for("lessons.list_lessons", direction_id=lesson.direction_id))

@lessons_bp.route("/<int:lesson_id>/edit", methods=["GET", "POST"])
@lesson_manager_required
def edit_lesson(lesson_id, current_user):
    lesson = Lesson.query.get_or_404(lesson_id)
    if not _lesson_can_manage_direction(current_user, lesson.direction_id):
        flash("У вас нет прав на изменение занятия этого направления.", "danger")
        return redirect(url_for("lessons.list_lessons"))
    directions = _lesson_directions_for_user(current_user)
    if request.method == "GET":
        return_to_calendar = request.args.get("return_to") == "calendar"
        return render_template("lessons/form.html", lesson=lesson, directions=directions,
                               selected_direction=lesson.direction_id, selected_datetime="",
                               selected_calendar_date=request.args.get("date") or lesson.starts_at.strftime("%Y-%m-%d"),
                               return_to_calendar=return_to_calendar)
    values, error = _lesson_form_values(current_user)
    if error:
        flash(error, "danger")
        return redirect(url_for("lessons.edit_lesson", lesson_id=lesson.id))
    lesson.direction_id = values["direction_id"]
    lesson.title = values["title"]
    lesson.description = values["description"]
    lesson.teacher = values["teacher"]
    lesson.room = values["room"]
    lesson.starts_at = values["starts_at"]
    lesson.duration_minutes = values["duration_minutes"]
    lesson.capacity = values["capacity"]
    lesson.updated_at = datetime.utcnow()
    record_activity("lesson_updated", f'Обновлено занятие «{lesson.title}».', direction_id=lesson.direction_id)
    db.session.commit()
    if request.form.get("announce") == "1":
        lesson_enqueue_error = False
        try:
            sent, total = _publish_lesson_to_direction_chats(lesson, "Изменение расписания")
        except Exception:
            logger.exception('Lesson #%s updated but announcement queue failed', lesson.id)
            lesson_enqueue_error = True
            sent, total = 0, 0
        if sent:
            record_activity("lesson_announced", f'Изменение занятия «{lesson.title}» поставлено в очередь: {sent} сообщений.', direction_id=lesson.direction_id)
            db.session.commit()
            flash(f"Изменения сохранены; уведомления поставлены в очередь: {sent}.", "success")
        elif lesson_enqueue_error:
            flash("Изменения сохранены, но очередь рассылки временно недоступна. Проверьте журнал и диагностику.", "warning")
        elif total:
            flash("Изменения сохранены, но объявление не отправлено. Проверьте настройки и токены Telegram/VK/MAX.", "warning")
        else:
            flash("Изменения сохранены. У направления нет активных подключённых чатов Telegram/VK/MAX.", "warning")
    else:
        flash("Изменения сохранены.", "success")
    if request.form.get("return_to") == "calendar":
        return redirect(url_for("admin.calendar", date=request.form.get("calendar_date") or lesson.starts_at.strftime("%Y-%m-%d")))
    return redirect(url_for("lessons.list_lessons", direction_id=lesson.direction_id))

@lessons_bp.route("/<int:lesson_id>/publish", methods=["POST"])
@lesson_manager_required
def publish_lesson(lesson_id, current_user):
    lesson = Lesson.query.get_or_404(lesson_id)
    if not _lesson_can_manage_direction(current_user, lesson.direction_id):
        flash("У вас нет прав на публикацию в чатах этого направления.", "danger")
        return redirect(url_for("lessons.list_lessons"))
    try:
        sent, total = _publish_lesson_to_direction_chats(lesson, "Объявление о занятии")
    except Exception:
        logger.exception('Lesson #%s publication could not be queued', lesson.id)
        flash('Очередь рассылки временно недоступна. Занятие осталось в расписании.', 'danger')
        return redirect(url_for('lessons.list_lessons', direction_id=lesson.direction_id))
    if sent:
        record_activity("lesson_announced", f'Объявление о занятии «{lesson.title}» поставлено в очередь: {sent} сообщений.', direction_id=lesson.direction_id)
        db.session.commit()
        flash(f"В очереди TG/VK/MAX: {sent} сообщений.", "success")
    elif total:
        flash("Не удалось отправить объявление. Проверьте токены ботов и подключение чатов.", "danger")
    else:
        flash("У направления нет активных подключённых чатов Telegram/VK/MAX.", "warning")
    return redirect(url_for("admin.calendar", date=lesson.starts_at.strftime("%Y-%m-%d"), direction_id=lesson.direction_id))

@lessons_bp.route("/<int:lesson_id>/delete", methods=["POST"])
@lesson_manager_required
def delete_lesson(lesson_id, current_user):
    lesson = Lesson.query.get_or_404(lesson_id)
    if not _lesson_can_manage_direction(current_user, lesson.direction_id):
        flash("У вас нет прав на удаление занятия этого направления.", "danger")
        return redirect(url_for("lessons.list_lessons"))
    title, did = lesson.title, lesson.direction_id
    record_activity("lesson_deleted", f'Удалено занятие «{title}».', direction_id=did)
    db.session.delete(lesson)
    db.session.commit()
    flash("Занятие удалено.", "success")
    return redirect(url_for("lessons.list_lessons", direction_id=did))

@stats_bp.route("/")
@stats_bp.route("/directions", endpoint="directions_statistics")
@stats_bp.route("/attendance", endpoint="attendance_statistics")
@stats_bp.route("/events", endpoint="events_statistics")
@stats_bp.route("/declines", endpoint="declines_statistics")
@analytics_view_required
def overview_statistics(current_user):
    """Load only the active statistics view; never build five full reports at once."""
    # v1.9.18: statistics is a single per-direction report. Legacy URLs
    # remain valid for bookmarks, but all render the same consolidated table.
    active_section = "overview"

    # Tab counters are cheap COUNT queries; details are fetched only for the
    # selected tab. This avoids loading all students, attendances, events and
    # refusal history on every statistics-page request.
    staff_scope = _staff_visible_direction_ids(current_user, ('statistics',)) if current_user.role in {UserRole.STAFF.value, UserRole.SUPER_ADMIN.value} else None
    directions_query = Direction.query
    if staff_scope is not None:
        directions_query = directions_query.filter(Direction.id.in_(staff_scope))
    directions = directions_query.order_by(Direction.name.asc()).all()
    direction_count = len(directions)
    available_direction_ids = {int(direction.id) for direction in directions}

    # One consistent filter model is shared by every analytics page.
    period_filter = _statistics_period_window(
        request.args.get('period', 'all'),
        request.args.get('date_from'), request.args.get('date_to'),
    )
    requested_direction_id = request.args.get('direction_id', type=int)
    if requested_direction_id and requested_direction_id not in available_direction_ids:
        if current_user.role == UserRole.STAFF.value:
            abort(403)
        requested_direction_id = None

    # Build the authoritative event -> direction map once. Legacy chat links
    # are only used if an event has no explicit QuotaDirection rows at all.
    explicit_direction_rows = QuotaDirection.query.with_entities(
        QuotaDirection.quota_id, QuotaDirection.direction_id
    ).all()
    explicit_quota_ids = {int(qid) for qid, _did in explicit_direction_rows if qid is not None}
    event_directions = {}
    for quota_id, direction_id in explicit_direction_rows:
        if quota_id is not None and direction_id is not None and (staff_scope is None or direction_id in staff_scope):
            event_directions.setdefault(int(quota_id), set()).add(int(direction_id))
    legacy_direction_rows = EventQuotaChat.query.with_entities(
        EventQuotaChat.quota_id, EventQuotaChat.direction_id
    ).filter(EventQuotaChat.direction_id.is_not(None)).all()
    for quota_id, direction_id in legacy_direction_rows:
        if quota_id is not None and direction_id is not None and int(quota_id) not in explicit_quota_ids:
            if staff_scope is None or direction_id in staff_scope:
                event_directions.setdefault(int(quota_id), set()).add(int(direction_id))

    if staff_scope is not None:
        scoped_student_ids = {row[0] for row in db.session.query(
            student_directions.c.student_id
        ).filter(student_directions.c.direction_id.in_(staff_scope)).distinct().all()} if staff_scope else set()
        scoped_quota_ids = _quota_ids_exclusively_in_scope(staff_scope) if staff_scope else set()
    else:
        scoped_student_ids = None
        scoped_quota_ids = None

    if requested_direction_id:
        selected_student_ids = {row[0] for row in db.session.query(
            student_directions.c.student_id
        ).filter(student_directions.c.direction_id == requested_direction_id).distinct().all()}
        scoped_student_ids = selected_student_ids if scoped_student_ids is None else scoped_student_ids.intersection(selected_student_ids)
        selected_quota_ids = {quota_id for quota_id, linked_ids in event_directions.items()
                              if requested_direction_id in linked_ids}
        scoped_quota_ids = selected_quota_ids if scoped_quota_ids is None else scoped_quota_ids.intersection(selected_quota_ids)

    if period_filter['is_filtered']:
        period_quota_query = EventDay.query.with_entities(EventDay.quota_id).distinct()
        period_quota_query = _apply_statistics_day_window(period_quota_query, period_filter)
        period_quota_ids = {int(row[0]) for row in period_quota_query.all() if row[0] is not None}
        scoped_quota_ids = period_quota_ids if scoped_quota_ids is None else scoped_quota_ids.intersection(period_quota_ids)

    students_count_query = Student.query.filter(Student.council_registered.is_(True))
    if scoped_student_ids is not None:
        students_count_query = students_count_query.filter(Student.id.in_(scoped_student_ids)) if scoped_student_ids else students_count_query.filter(false())
    attendance_count = int(students_count_query.count() or 0)
    events_count_query = EventQuota.query
    declines_count_query = EventQuotaDecline.query
    if scoped_quota_ids is not None:
        events_count_query = events_count_query.filter(EventQuota.id.in_(scoped_quota_ids)) if scoped_quota_ids else events_count_query.filter(false())
        declines_count_query = declines_count_query.filter(EventQuotaDecline.quota_id.in_(scoped_quota_ids)) if scoped_quota_ids else declines_count_query.filter(false())
    event_count = int(events_count_query.count() or 0)
    decline_count = int(declines_count_query.count() or 0)

    direction_stats = []
    attendance_rows = []
    event_rows = []
    decline_items = []
    metrics = {
        "students": attendance_count, "directions": (1 if requested_direction_id else direction_count),
        "events": event_count, "visits": 0, "attenders": 0,
        "registrations": 0, "attendance_rate": 0, "declines": decline_count,
        "not_attended": 0, "attender_rate": 0, "average_visits": 0,
    }
    attendance_summary = {"students": 0, "with_visits": 0, "without_visits": 0, "average_visits": 0}
    events_summary = {"events": 0, "registrations": 0, "attendees": 0, "attendance_rate": 0, "active": 0, "closed": 0}

    if active_section == "overview":
        attended_pairs = db.session.query(
            DayParticipation.student_id, EventDay.quota_id
        ).join(EventDay, EventDay.id == DayParticipation.day_id).filter(
            DayParticipation.status == "attended"
        ).filter(EventDay.quota_id.in_(scoped_quota_ids) if scoped_quota_ids is not None else true())
        attended_pairs = _apply_statistics_day_window(attended_pairs, period_filter)
        attended_pairs = attended_pairs.distinct().subquery()
        registered_pairs = db.session.query(
            DayParticipation.student_id, EventDay.quota_id
        ).join(EventDay, EventDay.id == DayParticipation.day_id).filter(
            DayParticipation.status.in_(("registered", "attended", "absent"))
        ).filter(EventDay.quota_id.in_(scoped_quota_ids) if scoped_quota_ids is not None else true())
        registered_pairs = _apply_statistics_day_window(registered_pairs, period_filter)
        registered_pairs = registered_pairs.distinct().subquery()
        metrics["visits"] = int(db.session.query(func.count()).select_from(attended_pairs).scalar() or 0)
        metrics["registrations"] = int(db.session.query(func.count()).select_from(registered_pairs).scalar() or 0)
        attenders_query = db.session.query(
            func.count(func.distinct(DayParticipation.student_id))
        ).join(EventDay, EventDay.id == DayParticipation.day_id).filter(
            DayParticipation.status == "attended"
        )
        if scoped_quota_ids is not None:
            attenders_query = attenders_query.filter(EventDay.quota_id.in_(scoped_quota_ids)) if scoped_quota_ids else attenders_query.filter(false())
        attenders_query = _apply_statistics_day_window(attenders_query, period_filter)
        metrics["attenders"] = int(attenders_query.scalar() or 0)
        metrics["attendance_rate"] = round(
            metrics["visits"] / metrics["registrations"] * 100
        ) if metrics["registrations"] else 0
        metrics["not_attended"] = max(0, metrics["registrations"] - metrics["visits"])
        metrics["attender_rate"] = round(metrics["attenders"] / metrics["students"] * 100) if metrics["students"] else 0
        metrics["average_visits"] = round(metrics["visits"] / metrics["attenders"], 1) if metrics["attenders"] else 0

    if active_section in ("overview", "directions"):
        # event_directions is built once above; overview and directions share this same per-direction aggregate.

        member_query = db.session.query(
            student_directions.c.direction_id, func.count(student_directions.c.student_id)
        ).join(Student, Student.id == student_directions.c.student_id).filter(
            student_directions.c.status == DirectionStatus.ACTIVE.value,
            Student.council_registered.is_(True),
        )
        if staff_scope is not None:
            member_query = member_query.filter(student_directions.c.direction_id.in_(staff_scope))
        member_counts = dict(member_query.group_by(student_directions.c.direction_id).all())
        event_sets = {direction.id: set() for direction in directions}
        visit_sets = {direction.id: set() for direction in directions}
        attender_sets = {direction.id: set() for direction in directions}
        for quota_id, linked_directions in event_directions.items():
            if scoped_quota_ids is not None and quota_id not in scoped_quota_ids:
                continue
            for direction_id in linked_directions:
                if direction_id in event_sets:
                    event_sets[direction_id].add(quota_id)
        visible_quota_ids = set(event_directions)
        if scoped_quota_ids is not None:
            visible_quota_ids.intersection_update(scoped_quota_ids)
        attended_pairs_query = db.session.query(
            DayParticipation.student_id, EventDay.quota_id
        ).join(EventDay, EventDay.id == DayParticipation.day_id).filter(
            DayParticipation.status == "attended",
            EventDay.quota_id.in_(visible_quota_ids) if visible_quota_ids else false(),
        )
        attended_pairs_query = _apply_statistics_day_window(attended_pairs_query, period_filter)
        attended_pairs = attended_pairs_query.distinct().all()
        student_visits_by_direction = {direction.id: {} for direction in directions}
        for student_id, quota_id in attended_pairs:
            for direction_id in event_directions.get(quota_id, ()):
                if direction_id in visit_sets:
                    visit_sets[direction_id].add((student_id, quota_id))
                    attender_sets[direction_id].add(student_id)
                    per_student = student_visits_by_direction[direction_id]
                    per_student[student_id] = per_student.get(student_id, 0) + 1
        top_student_ids = {
            student_id
            for by_student in student_visits_by_direction.values() if by_student
            for student_id, count in by_student.items()
            if count == max(by_student.values())
        }
        top_students_by_id = {student.id: student for student in Student.query.filter(
            Student.id.in_(top_student_ids)
        ).all()} if top_student_ids else {}
        max_visits = max((len(values) for values in visit_sets.values()), default=0)
        for direction in directions:
            if requested_direction_id and direction.id != requested_direction_id:
                continue
            visits = len(visit_sets[direction.id])
            by_student = student_visits_by_direction[direction.id]
            leader_count = max(by_student.values(), default=0)
            leaders = [
                {"student": top_students_by_id[student_id], "visits": count}
                for student_id, count in sorted(by_student.items(), key=lambda pair: (-pair[1], top_students_by_id.get(pair[0]).full_name.casefold() if top_students_by_id.get(pair[0]) else ""))
                if count == leader_count and student_id in top_students_by_id
            ][:3] if leader_count else []
            direction_stats.append({
                "direction": direction,
                "members": int(member_counts.get(direction.id, 0)),
                "event_count": len(event_sets[direction.id]),
                "visit_count": visits,
                "attenders": len(attender_sets[direction.id]),
                "leaders": leaders,
                "top_student_visits": leader_count,
                "bar_height": max(10, round(visits / max_visits * 100)) if max_visits else 10,
            })
        direction_stats.sort(key=lambda item: (
            item["visit_count"], item["members"], item["direction"].name.lower()
        ), reverse=True)

    elif active_section == "attendance":
        students_query = Student.query.filter(Student.council_registered.is_(True))
        if scoped_student_ids is not None:
            students_query = students_query.filter(Student.id.in_(scoped_student_ids))
        students = students_query.order_by(Student.full_name.asc()).all()
        active_direction_query = db.session.query(
            student_directions.c.student_id, func.count(student_directions.c.direction_id)
        ).join(Student, Student.id == student_directions.c.student_id).filter(
            student_directions.c.status == DirectionStatus.ACTIVE.value,
            Student.council_registered.is_(True),
        )
        if staff_scope is not None:
            active_direction_query = active_direction_query.filter(student_directions.c.direction_id.in_(staff_scope))
        if requested_direction_id:
            active_direction_query = active_direction_query.filter(student_directions.c.direction_id == requested_direction_id)
        active_direction_counts = dict(active_direction_query.group_by(student_directions.c.student_id).all())
        attended_event_query = db.session.query(
            DayParticipation.student_id, EventDay.quota_id, func.max(EventDay.date)
        ).join(EventDay, EventDay.id == DayParticipation.day_id).filter(
            DayParticipation.status == "attended"
        ).filter(EventDay.quota_id.in_(scoped_quota_ids) if scoped_quota_ids is not None else true())
        attended_event_query = _apply_statistics_day_window(attended_event_query, period_filter)
        attended_event_rows = attended_event_query.group_by(DayParticipation.student_id, EventDay.quota_id).all()
        attended_by_student = {}
        event_ids = {quota_id for _sid, quota_id, _date in attended_event_rows}
        for student_id, quota_id, event_date in attended_event_rows:
            attended_by_student.setdefault(student_id, []).append((event_date, quota_id))
        event_titles = dict(EventQuota.query.with_entities(
            EventQuota.id, EventQuota.event_title
        ).filter(EventQuota.id.in_(event_ids)).all()) if event_ids else {}
        for student in students:
            recent = sorted(attended_by_student.get(student.id, ()), key=lambda item: (item[0], item[1]), reverse=True)
            attendance_rows.append({
                "student": student,
                "attended": len(recent),
                "active_directions": int(active_direction_counts.get(student.id, 0)),
                "last_events": [event_titles[qid] for _date, qid in recent[:3] if qid in event_titles],
            })
        attendance_rows.sort(key=lambda item: (-item["attended"], item["student"].full_name.casefold()))
        attendance_summary = {
            "students": len(attendance_rows),
            "with_visits": sum(1 for row in attendance_rows if row["attended"] > 0),
            "without_visits": sum(1 for row in attendance_rows if row["attended"] == 0),
            "average_visits": round(sum(row["attended"] for row in attendance_rows) / len(attendance_rows), 1) if attendance_rows else 0,
        }

    elif active_section == "events":
        # Reuse the shared event -> direction map built for this request.
        direction_names = {direction.id: direction.name for direction in directions}
        attendee_query = db.session.query(
            EventDay.quota_id, func.count(func.distinct(DayParticipation.student_id))
        ).join(DayParticipation, DayParticipation.day_id == EventDay.id).filter(
            DayParticipation.status == "attended"
        )
        if scoped_quota_ids is not None:
            attendee_query = attendee_query.filter(EventDay.quota_id.in_(scoped_quota_ids)) if scoped_quota_ids else attendee_query.filter(false())
        attendee_query = _apply_statistics_day_window(attendee_query, period_filter)
        attendee_counts = dict(attendee_query.group_by(EventDay.quota_id).all())
        registration_query = db.session.query(
            EventDay.quota_id, func.count(func.distinct(DayParticipation.student_id))
        ).join(DayParticipation, DayParticipation.day_id == EventDay.id).filter(
            DayParticipation.status.in_(("registered", "attended", "absent"))
        )
        if scoped_quota_ids is not None:
            registration_query = registration_query.filter(EventDay.quota_id.in_(scoped_quota_ids)) if scoped_quota_ids else registration_query.filter(false())
        registration_query = _apply_statistics_day_window(registration_query, period_filter)
        registration_counts = dict(registration_query.group_by(EventDay.quota_id).all())
        events_query = EventQuota.query
        if scoped_quota_ids is not None:
            events_query = events_query.filter(EventQuota.id.in_(scoped_quota_ids))
        events = events_query.order_by(EventQuota.id.desc()).all()
        for event in events:
            linked_ids = sorted(event_directions.get(event.id, set()))
            attendees = int(attendee_counts.get(event.id, 0))
            registrations = int(registration_counts.get(event.id, 0))
            event_days_in_scope = [day for day in event.days
                                   if (not period_filter.get('start_dt') or day.date >= period_filter['start_dt'])
                                   and (not period_filter.get('end_exclusive') or day.date < period_filter['end_exclusive'])]
            event_rows.append({
                "event": event,
                "days_in_scope": event_days_in_scope,
                "attendees": attendees,
                "registrations": registrations,
                "not_attended": max(0, registrations - attendees),
                "attendance_rate": round(attendees / registrations * 100) if registrations else 0,
                "directions": len(linked_ids),
                "direction_ids": linked_ids,
                "direction_names": [direction_names[did] for did in linked_ids if did in direction_names],
            })
        event_rows.sort(key=lambda item: (-item["attendees"], item["event"].event_title.casefold()))
        events_summary = {
            "events": len(event_rows),
            "registrations": sum(row["registrations"] for row in event_rows),
            "attendees": sum(row["attendees"] for row in event_rows),
            "active": sum(1 for row in event_rows if not row["event"].is_closed),
            "closed": sum(1 for row in event_rows if row["event"].is_closed),
        }
        events_summary["attendance_rate"] = round(events_summary["attendees"] / events_summary["registrations"] * 100) if events_summary["registrations"] else 0

    elif active_section == "declines":
        declines_query = EventQuotaDecline.query
        if scoped_quota_ids is not None:
            declines_query = declines_query.filter(EventQuotaDecline.quota_id.in_(scoped_quota_ids))
        declines = declines_query.order_by(EventQuotaDecline.created_at.desc()).all()
        student_ids = {row.student_id for row in declines}
        quota_ids = {row.quota_id for row in declines}
        decline_counts_query = db.session.query(
            EventQuotaDecline.student_id, func.count(EventQuotaDecline.id)
        )
        if scoped_quota_ids is not None:
            decline_counts_query = decline_counts_query.filter(EventQuotaDecline.quota_id.in_(scoped_quota_ids))
        decline_counts = dict(decline_counts_query.group_by(EventQuotaDecline.student_id).all())
        decline_students = {row.id: row for row in Student.query.filter(
            Student.id.in_(student_ids)
        ).all()} if student_ids else {}
        decline_events = {row.id: row for row in EventQuota.query.filter(
            EventQuota.id.in_(quota_ids)
        ).all()} if quota_ids else {}
        # Direction labels use the same authoritative links as the other sections.
        direction_names = {direction.id: direction.name for direction in directions}
        for row in declines:
            event = decline_events.get(row.quota_id)
            if not event:
                continue
            linked_ids = sorted(direction_id for direction_id in event_directions.get(event.id, set())
                                if staff_scope is None or direction_id in staff_scope)
            decline_items.append({
                "decline": row,
                "student": decline_students.get(row.student_id),
                "event": event,
                "student_decline_count": int(decline_counts.get(row.student_id, 0)),
                "direction_ids": linked_ids,
                "direction_names": [direction_names[did] for did in linked_ids if did in direction_names],
            })

    stats_reset_url = {
        'overview': url_for('stats.overview_statistics'),
        'directions': url_for('stats.directions_statistics'),
        'attendance': url_for('stats.attendance_statistics'),
        'events': url_for('stats.events_statistics'),
        'declines': url_for('stats.declines_statistics'),
    }.get(active_section, url_for('stats.overview_statistics'))
    # Keep the selected report window and direction when following drill-down links.
    stats_query_args = {'period': period_filter['period']}
    if period_filter['date_from']:
        stats_query_args['date_from'] = period_filter['date_from']
    if period_filter['date_to']:
        stats_query_args['date_to'] = period_filter['date_to']
    if requested_direction_id:
        stats_query_args['direction_id'] = requested_direction_id
    stats_section_urls = {
        'overview': url_for('stats.overview_statistics', **stats_query_args),
        'directions': url_for('stats.directions_statistics', **stats_query_args),
        'attendance': url_for('stats.attendance_statistics', **stats_query_args),
        'events': url_for('stats.events_statistics', **stats_query_args),
        'declines': url_for('stats.declines_statistics', **stats_query_args),
    }
    return render_template(
        "statistics/overview.html",
        students=[], directions=directions,
        direction_stats=direction_stats,
        attendance_rows=attendance_rows,
        event_rows=event_rows,
        metrics=metrics,
        decline_items=decline_items,
        active_section=active_section,
        direction_count=direction_count,
        attendance_count=attendance_count,
        event_count=event_count,
        decline_count=decline_count,
        attendance_summary=attendance_summary,
        events_summary=events_summary,
        period_filter=period_filter,
        selected_direction_id=requested_direction_id,
        stats_reset_url=stats_reset_url,
        stats_section_urls=stats_section_urls,
        stats_last_updated=datetime.utcnow(),
    )

@stats_bp.route("/students/summary")
@analytics_view_required
def students_summary(current_user):
    # Stats are kept in a separate SQLite DB, so aggregation is done in Python
    # instead of a cross-database SQL JOIN.
    stats_query = StudentQuotaStat.query
    if current_user.role == UserRole.STAFF.value:
        from services.staff_access import direction_ids as staff_direction_ids
        allowed_stats_ids = staff_direction_ids(current_user, 'statistics', 'view')
        stats_query = stats_query.filter(StudentQuotaStat.direction_id.in_(allowed_stats_ids)) if allowed_stats_ids else stats_query.filter(false())
    stats_rows = stats_query.order_by(StudentQuotaStat.student_id).all()
    student_ids = {row.student_id for row in stats_rows}
    students = {s.id: s for s in Student.query.filter(Student.id.in_(student_ids)).all()} if student_ids else {}

    grouped = {}
    for row in stats_rows:
        if row.student_id not in students:
            continue
        bucket = grouped.setdefault(row.student_id, {
            "id": row.student_id,
            "full_name": students[row.student_id].full_name,
            "group": students[row.student_id].group,
            "total_quotas": 0,
            "attended_count": 0,
        })
        bucket["total_quotas"] += row.total_quotas or 0
        bucket["attended_count"] += row.attended_count or 0

    summary = sorted(grouped.values(), key=lambda x: x["full_name"].lower())
    return render_template("students/summary.html", summary=summary)

@stats_bp.route("/students", methods=["GET", "POST"])
@login_required
def students_quota_stats(current_user):
    if current_user.role not in {UserRole.SUPER_ADMIN.value, UserRole.STAFF.value, UserRole.OBSERVER.value}:
        abort(403)
    from services.staff_access import direction_ids as staff_direction_ids
    staff_scope = set(staff_direction_ids(current_user, 'statistics', 'view')) if current_user.role == UserRole.STAFF.value else None
    stats_manage_scope = set(staff_direction_ids(current_user, 'statistics', 'manage')) if current_user.role == UserRole.STAFF.value else set()
    can_manage_stats = current_user.role == UserRole.SUPER_ADMIN.value or bool(stats_manage_scope)
    if current_user.role == UserRole.STAFF.value and not staff_scope:
        abort(403)
    if current_user.role == UserRole.OBSERVER.value and request.method != 'GET':
        abort(403)
    filter_did = request.args.get('direction_id', type=int)
    if current_user.role == UserRole.STAFF.value:
        if filter_did is not None and filter_did not in staff_scope:
            abort(403)
        # A direction employee gets its only assigned direction automatically;
        # the all-directions employee may choose a direction or view the aggregate.
        if getattr(current_user, 'staff_rank', 'employee') != 'employee_all' and filter_did is None:
            home_id = current_user.assigned_direction_id
            if home_id not in staff_scope:
                abort(403)
            filter_did = int(home_id)

    if request.method == "POST" and request.form.get("action") == "reset_stats":
        if not can_manage_stats:
            abort(403)
        sid = request.form.get("student_id", type=int)
        did = request.form.get("direction_id", type=int)
        reason = request.form.get("reset_reason", "").strip()[:500]
        if not sid or not did or not reason:
            abort(400)
        if current_user.role == UserRole.STAFF.value and did not in stats_manage_scope:
            abort(403)
        stat = StudentQuotaStat.query.filter_by(student_id=sid, direction_id=did).first()
        if not stat:
            abort(404)
        stat.total_quotas = 0
        stat.attended_count = 0
        db.session.commit()
        logger.info("Student quota stats reset for direction %s by user %s", did, current_user.id)
        flash(f"Статистика сброшена. Причина: {reason}", "success")
        return redirect(url_for("stats.students_quota_stats", direction_id=filter_did))

    stats_query = StudentQuotaStat.query
    if current_user.role == UserRole.STAFF.value:
        stats_query = stats_query.filter(StudentQuotaStat.direction_id.in_(staff_scope))
    if filter_did:
        stats_query = stats_query.filter(StudentQuotaStat.direction_id == filter_did)
    raw_stats = stats_query.order_by(StudentQuotaStat.student_id).all()

    student_ids = {row.student_id for row in raw_stats}
    direction_ids = {row.direction_id for row in raw_stats}
    students = {s.id: s for s in Student.query.filter(Student.id.in_(student_ids)).all()} if student_ids else {}
    directions_by_id = {d.id: d for d in Direction.query.filter(Direction.id.in_(direction_ids)).all()} if direction_ids else {}

    stats_list = []
    for row in raw_stats:
        student = students.get(row.student_id)
        direction = directions_by_id.get(row.direction_id)
        if not student or not direction:
            continue
        stats_list.append({
            "student": student,
            "direction": direction,
            "total_quotas": row.total_quotas or 0,
            "attended_count": row.attended_count or 0,
        })

    stats_list.sort(key=lambda x: x["student"].full_name.lower())
    direction_query = Direction.query
    if current_user.role == UserRole.STAFF.value:
        direction_query = direction_query.filter(Direction.id.in_(staff_scope))
    return render_template("students/quota_stats.html", stats_list=stats_list,
                           directions=direction_query.order_by(Direction.name).all(),
                           filter_did=filter_did, can_manage_stats=can_manage_stats,
                           stats_manage_scope=stats_manage_scope,
                           is_global_employee=(current_user.role == UserRole.STAFF.value and
                                               getattr(current_user, 'staff_rank', 'employee') == 'employee_all'),
                           is_read_only=(current_user.role == UserRole.OBSERVER.value))

@stats_bp.route("/<int:did>")
@analytics_view_required
def direction_statistics(did, current_user):
    """Безопасная статистика направления.

    В этой странице не используем ленивую цепочку q.days -> day.participations:
    на старых БД она может падать из-за повреждённых/неполных связей. Все значения
    собираются явными запросами и NULL нормализуются в Python.
    """
    direction = Direction.query.get_or_404(did)
    if current_user.role in {UserRole.STAFF.value, UserRole.SUPER_ADMIN.value} and did not in _staff_visible_direction_ids(current_user, ('statistics',)):
        abort(403)

    # Статусы заявок по направлению.
    link_rows = db.session.execute(
        student_directions.select().where(student_directions.c.direction_id == did)
    ).mappings().all()
    statuses = [row.get("status") or "" for row in link_rows]
    status_values = [getattr(status, "value", status) for status in statuses]
    total = len(status_values)
    pending = status_values.count("pending")
    active = status_values.count("active")
    rejected = status_values.count("rejected")

    # Квоты направления живут в events.sqlite3; используем явный helper.
    quota_ids = get_direction_quota_ids(did)
    total_quotas = len(set(quota_ids))

    # Считаем участия напрямую, не трогая lazy relationships.
    total_registered = 0
    total_attended = 0
    total_absent = 0
    if quota_ids:
        day_rows = db.session.execute(
            db.select(EventDay.id).where(EventDay.quota_id.in_(quota_ids))
        ).all()
        day_ids = [row[0] for row in day_rows if row[0] is not None]
        if day_ids:
            participation_rows = db.session.execute(
                db.select(DayParticipation.status).where(
                    DayParticipation.day_id.in_(day_ids)
                )
            ).all()
            for row in participation_rows:
                status = row[0] or ""
                if status == "registered":
                    total_registered += 1
                elif status == "attended":
                    total_attended += 1
                elif status == "absent":
                    total_absent += 1

    # Для старых записей без отдельного absent считаем остаток из зарегистрированных.
    if total_absent == 0 and total_registered >= total_attended:
        total_absent = max(0, total_registered - total_attended)

    return render_template(
        "directions/statistics.html",
        direction=direction,
        stats={
            "total": total,
            "pending": pending,
            "active": active,
            "rejected": rejected,
            "interview": status_values.count("interview"),
        },
        event_stats={
            "total_quotas": total_quotas,
            "registered": total_registered,
            "attended": total_attended,
            "absent": total_absent,
        },
    )

def _event_leaders_map(quota_ids):
    if not quota_ids:
        return {}
    # Load student rows in one additional query instead of one query per event.
    rows = EventLeader.query.options(selectinload(EventLeader.student)).filter(
        EventLeader.quota_id.in_(quota_ids)
    ).all()
    return {row.quota_id: row for row in rows}

@quotas_bp.route("/announcement", methods=["GET", "POST"], endpoint="competition_announcement")
@login_required
def competition_announcement(current_user):
    if current_user.role == UserRole.OBSERVER.value:
        flash("Настройки объявления доступны только для управления. Просмотрите уведомления в соответствующем разделе.", "info")
        return redirect(url_for("admin.notifications"))
    announcement = CompetitionAnnouncement.query.first()
    quotas = EventQuota.query.filter_by(is_closed=False).order_by(EventQuota.id.desc()).all()
    if request.method == "POST":
        if not announcement:
            announcement = CompetitionAnnouncement(title="", body="", is_active=True)
            db.session.add(announcement)
        announcement.title = request.form.get("title", "").strip() or settings.COMPETITION_TITLE
        announcement.body = request.form.get("body", "").strip() or settings.COMPETITION_BODY
        announcement.quota_id = request.form.get("quota_id", type=int) or None
        announcement.is_active = request.form.get("is_active") == "on"
        db.session.commit()
        flash("Объявление соревнований обновлено.", "success")
        return redirect(url_for("quotas.competition_announcement"))
    return render_template("events/announcement.html", announcement=announcement, quotas=quotas)

@quotas_bp.route("/announcement/publish", methods=["POST"], endpoint="publish_competition_announcement")
@login_required
def publish_competition_announcement(current_user):
    announcement = CompetitionAnnouncement.query.first()
    if not announcement or not announcement.is_active:
        flash("Сначала включите и сохраните объявление.", "warning")
        return redirect(url_for("quotas.competition_announcement"))
    lines = [f"🏆 <b>{html.escape(announcement.title)}</b>", "", html.escape(announcement.body)]
    if announcement.quota_id:
        quota = EventQuota.query.get(announcement.quota_id)
        if quota and not quota.is_closed:
            dates = ", ".join(d.date.strftime("%d.%m.%Y") for d in sorted(quota.days, key=lambda x: x.date))
            lines.extend(["", f"📅 Даты: {html.escape(dates)}", f"🕒 Время: {html.escape(quota.time_range or 'уточняется')}", f"📍 Место: {html.escape(quota.location or 'уточняется')}", f"👥 Квота: {quota.total_places} мест"])
            lines.append("📌 Запись открыта в разделе «Мероприятия».")
    text = "\n".join(lines)
    chats = DirectionChat.query.filter_by(is_active=True).all()
    seen, sent = set(), 0
    for chat in chats:
        stable, _ = _resolve_chat_id(chat.chat_id)
        if not stable or stable in seen:
            continue
        seen.add(stable)
        if _send_tg(stable, text):
            sent += 1
    # All active direction chats across all three transports, de-duplicated.
    queued = queue_social_chat_announcement(
        [direction.id for direction in Direction.query.all()],
        "🏆 " + (announcement.title or "Объявление") + "\n\n" + (announcement.body or "")
        + ("\n\nПодробнее: /events" if announcement.quota_id else ""),
    )
    flash(f"Telegram: {sent}/{len(seen)} чатов. VK/MAX: {queued} сообщений в очереди. "
          "Фактическая доставка зависит от прав ботов.",
          "success" if sent or queued else "warning")
    return redirect(url_for("quotas.competition_announcement"))

@quotas_bp.route("/<int:qid>/close", methods=["POST"])
@login_required
def close_quota(qid, current_user):
    quota = EventQuota.query.get_or_404(qid)
    reason = request.form.get("reason", "").strip()

    # Не допускаем повторного закрытия и двойного начисления статистики.
    if quota.is_closed:
        flash("Это мероприятие уже закрыто.", "warning")
        return redirect(url_for("quotas.quotas_list"))

    try:
        event_students = {}
        for day in quota.days:
            for participation in day.participations:
                if not participation.student_id:
                    continue
                # Aggregate all dates first: a multi-day event counts once per student.
                event_students.setdefault(participation.student_id, False)
                if participation.status == "attended":
                    event_students[participation.student_id] = True
        for student_id, attended in event_students.items():
            for direction in quota.directions:
                stat = StudentQuotaStat.query.filter_by(
                    student_id=student_id, direction_id=direction.id
                ).first()
                if not stat:
                    stat = StudentQuotaStat(student_id=student_id, direction_id=direction.id)
                    db.session.add(stat)
                stat.total_quotas = (stat.total_quotas or 0) + 1
                if attended:
                    stat.attended_count = (stat.attended_count or 0) + 1
        quota.is_closed = True
        quota.closing_reason = reason
        quota.closed_at = datetime.utcnow()
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("Не удалось закрыть квоту #%s", qid)
        flash("Не удалось закрыть мероприятие. Изменения отменены — повторите попытку.", "danger")
        return redirect(url_for("quotas.quota_participants", qid=qid))

    try:
        from services.activity_chats import close_activity_chat
        close_activity_chat('event', qid)
    except Exception:
        logger.exception('Не удалось поставить участников в очередь удаления из чата мероприятия #%s', qid)
    flash("Мероприятие закрыто. Статистика посещаемости обновлена.", "success")
    return redirect(url_for("quotas.quotas_list"))

def _can_manage_direction_chats(user, direction_id=None):
    """Only the chief administrator may discover, assign or configure chats."""
    return bool(
        user
        and getattr(user, "is_active", False)
        and user.role == UserRole.SUPER_ADMIN.value
    )


def _require_direction_chat_management(user, direction_id):
    # Do not treat a staff grant for sending messages as permission to bind or
    # alter a Telegram/VK/MAX chat. This is an administrator-only operation.
    if not _can_manage_direction_chats(user):
        abort(403)
    return Direction.query.get_or_404(direction_id)


@directions_bp.route("/<int:did>/chat/connect/<int:cid>", methods=["POST"], endpoint="connect_chat_candidate")
@login_required
def connect_chat_candidate(did, cid, current_user):
    direction = _require_direction_chat_management(current_user, did)
    candidate = TelegramChatCandidate.query.get_or_404(cid)
    cohort = request.form.get("education_type", "all")
    if cohort not in {"all", "college", "institute"}:
        abort(400)
    if current_user.role == UserRole.STAFF.value and DirectionChat.query.filter(
            DirectionChat.chat_id == str(candidate.chat_id), DirectionChat.direction_id != did).first():
        flash("Этот чат уже закреплён за другим направлением.", "danger")
        return redirect(url_for("directions.direction_detail", did=did) + "#direction-chats")
    chat_text = (
        "🔔 <b>Студенческий совет</b>\n\n"
        f"Подключение чата к направлению «{html.escape(direction.name)}» подтверждено.\n"
        "В данный чат будут направляться уведомления о новых занятиях и мероприятиях."
    )
    ok, error = _send_tg_detailed(candidate.chat_id, chat_text)
    if not ok:
        flash(f"Telegram не принял сообщение: {error}", "danger")
        return redirect(url_for("directions.direction_detail", did=did))
    existing = DirectionChat.query.filter_by(direction_id=did, chat_id=str(candidate.chat_id)).first()
    if existing:
        existing.title = candidate.title or existing.title
        existing.username = candidate.username or existing.username
        existing.is_active = True
        existing.education_type = cohort
        existing.last_test_at = datetime.utcnow()
    else:
        db.session.add(DirectionChat(
            direction_id=did, chat_id=str(candidate.chat_id),
            title=candidate.title or str(candidate.chat_id), username=candidate.username or "",
            education_type=cohort, is_active=True, last_test_at=datetime.utcnow()
        ))
    db.session.commit()
    flash(f"Чат «{candidate.title or candidate.chat_id}» подключён и проверен.", "success")
    return redirect(url_for("directions.direction_detail", did=did))

@directions_bp.route("/<int:did>/chat/social-connect", methods=["POST"], endpoint="connect_social_chat")
@login_required
def connect_social_chat(did, current_user):
    direction = _require_direction_chat_management(current_user, did)
    candidate = MessengerChatCandidate.query.get(request.form.get("candidate_id", type=int))
    education = request.form.get("education_type", "all")
    if not candidate or candidate.platform not in {"vk", "max"}:
        abort(400)
    if education not in {"all", "college", "institute"}:
        abort(400)
    if education != "all" and not direction.available_for(education):
        flash("Направление не относится к указанному учебному контуру.", "danger")
        return redirect(url_for("directions.direction_detail", did=did) + "#direction-chats")
    chat_id = str(candidate.chat_id).strip()
    if not chat_id.lstrip('-').isdigit() or len(chat_id) > 100:
        abort(400)
    if current_user.role == UserRole.STAFF.value and MessengerChat.query.filter(
            MessengerChat.platform == candidate.platform, MessengerChat.chat_id == chat_id,
            MessengerChat.direction_id != did).first():
        flash("Этот чат уже закреплён за другим направлением.", "danger")
        return redirect(url_for("directions.direction_detail", did=did) + "#direction-chats")
    chat = MessengerChat.query.filter_by(platform=candidate.platform, chat_id=chat_id,
                                         direction_id=did).first()
    if not chat:
        chat = MessengerChat(platform=candidate.platform, chat_id=chat_id,
                             direction_id=did, title=candidate.title[:255],
                             education_type=education)
        db.session.add(chat)
    else:
        chat.is_active = True
        chat.title = candidate.title[:255]
        chat.education_type = education
    db.session.commit()
    flash(f"{candidate.platform.upper()}: чат подтверждён и привязан к направлению.", "success")
    return redirect(url_for("directions.direction_detail", did=did) + "#direction-chats")


@directions_bp.route("/<int:did>/chat/social/<int:cid>/remove", methods=["POST"], endpoint="remove_social_chat")
@login_required
def remove_social_chat(did, cid, current_user):
    _require_direction_chat_management(current_user, did)
    chat = MessengerChat.query.filter_by(id=cid, direction_id=did).first_or_404()
    chat.is_active = False
    db.session.commit()
    flash("Чат VK/MAX отключён от рассылки.", "success")
    return redirect(url_for("directions.direction_detail", did=did) + "#direction-chats")


@directions_bp.route("/<int:did>/chat/add", methods=["POST"], endpoint="add_chat")
@login_required
def add_chat(did, current_user):
    direction = _require_direction_chat_management(current_user, did)
    chat_id = request.form.get("chat_id", "").strip()
    title = request.form.get("title", "").strip()
    username = request.form.get("username", "").strip()
    cohort = request.form.get("education_type", "all")
    if cohort not in {"all", "college", "institute"}:
        abort(400)
    if not chat_id:
        flash("Укажите username группы/канала или числовой Chat ID.", "danger")
        return redirect(url_for("directions.direction_detail", did=did))
    resolved_chat_id, chat_info = _resolve_chat_id(chat_id)
    if not resolved_chat_id:
        flash((chat_info or {}).get("error", "Не удалось найти чат через Telegram."), "danger")
        return redirect(url_for("directions.direction_detail", did=did))

    if chat_info:
        # Store canonical numeric ID; username/title remain display metadata.
        if not username:
            username = chat_info.get("username") or ""
        if not title:
            title = chat_info.get("title") or chat_info.get("first_name") or resolved_chat_id

    if current_user.role == UserRole.STAFF.value and DirectionChat.query.filter(
            DirectionChat.chat_id == resolved_chat_id, DirectionChat.direction_id != did).first():
        flash("Этот чат уже закреплён за другим направлением.", "danger")
        return redirect(url_for("directions.direction_detail", did=did) + "#direction-chats")
    existing = DirectionChat.query.filter_by(direction_id=did, chat_id=resolved_chat_id).first()
    if existing:
        existing.title = title
        existing.username = username
        existing.education_type = cohort
        existing.is_active = True
    else:
        db.session.add(DirectionChat(direction_id=did, chat_id=resolved_chat_id, title=title, username=username, education_type=cohort, is_active=True))
    db.session.commit()
    flash(f"Чат «{title}» подключён. Telegram ID: {resolved_chat_id}", "success")
    return redirect(url_for("directions.direction_detail", did=did))

@directions_bp.route("/<int:did>/chat/<int:cid>/audience", methods=["POST"], endpoint="chat_audience")
@login_required
def chat_audience(did, cid, current_user):
    _require_direction_chat_management(current_user, did)
    chat = DirectionChat.query.get_or_404(cid)
    if chat.direction_id != did:
        abort(404)
    cohort = request.form.get("education_type", "")
    if cohort not in {"all", "college", "institute"}:
        abort(400)
    chat.education_type = cohort
    db.session.commit()
    flash("Аудитория чата обновлена. Фильтры уведомлений будут учитывать этот выбор.", "success")
    return redirect(url_for("directions.direction_detail", did=did) + "#direction-chats")

@directions_bp.route("/<int:did>/chat/<int:cid>/delete", methods=["POST"], endpoint="delete_chat")
@login_required
def delete_chat(did, cid, current_user):
    _require_direction_chat_management(current_user, did)
    chat = DirectionChat.query.get_or_404(cid)
    if chat.direction_id != did:
        flash("Чат не относится к этому направлению.", "danger")
        return redirect(url_for("directions.direction_detail", did=did))
    name = chat.title
    chat_id = str(chat.chat_id)
    db.session.delete(chat)
    db.session.commit()
    try:
        from services.telegram import revoke_invites_for_chat
        revoke_invites_for_chat(chat_id, direction_id=did)
    except Exception:
        logger.exception("Could not revoke cached invites for disconnected chat %s", chat_id)
    flash(f"Чат «{name}» отключён, сохранённые ссылки-приглашения отозваны.", "success")
    return redirect(url_for("directions.direction_detail", did=did))

@directions_bp.route("/<int:did>/chat/<int:cid>/test", methods=["POST"], endpoint="test_chat")
@login_required
def test_chat(did, cid, current_user):
    _require_direction_chat_management(current_user, did)
    chat = DirectionChat.query.get_or_404(cid)
    if chat.direction_id != did:
        flash("Чат не относится к этому направлению.", "danger")
        return redirect(url_for("directions.direction_detail", did=did))
    ok, error = _send_tg_detailed(
        chat.chat_id,
        "🔔 <b>Студенческий совет</b>\n\n"
        f"Контрольное сообщение для направления «{html.escape(Direction.query.get(did).name)}».\n"
        "Статус подключения: подтверждён."
    )
    if ok:
        chat.last_test_at = datetime.utcnow()
        db.session.commit()
        flash(f"Тестовое сообщение отправлено в «{chat.title}».", "success")
    else:
        flash(f"Telegram не принял сообщение: {error}", "danger")
    return redirect(url_for("directions.direction_detail", did=did))

@directions_bp.route("/manage/create", methods=["POST"], endpoint="create_direction")
@super_admin_required
def create_direction(current_user):
    # Once the chief admin has selected an operational home, direction
    # lifecycle remains a system-level action outside that scoped workspace.
    name = ' '.join((request.form.get('name') or '').split())[:255]
    code = (request.form.get('code') or '').strip().upper()
    import re
    if not name or not re.fullmatch(r'[A-Z0-9_]{2,30}', code):
        flash('Укажите название и код из 2–30 латинских заглавных букв, цифр или _.', 'danger')
    elif Direction.query.filter(db.func.lower(Direction.name) == name.casefold()).first() or Direction.query.filter_by(code=code).first():
        flash('Такое направление или код уже существуют.', 'warning')
    else:
        scope = request.form.get('education_scope', 'both')
        if scope not in {'both', 'college', 'institute'}: scope = 'both'
        db.session.add(Direction(name=name, code=code, icon='✦', education_scope=scope, description=(request.form.get('description') or '')[:1000]))
        db.session.commit()
        flash('Направление создано.', 'success')
    return redirect(url_for('directions.directions_list'))

@directions_bp.route("/<int:did>/manage/archive", methods=["POST"], endpoint="archive_direction")
@super_admin_required
def archive_direction(did, current_user):
    direction = db.session.get(Direction, did)
    if not direction: abort(404)
    if request.form.get('confirm') != direction.code:
        flash('Для архивирования введите код направления точно.', 'danger')
    else:
        direction.is_archived = True
        db.session.commit()
        flash('Направление архивировано. История, участники и мероприятия сохранены.', 'success')
    return redirect(url_for('directions.directions_list'))

@directions_bp.route("/<int:did>/manage/restore", methods=["POST"], endpoint="restore_direction")
@super_admin_required
def restore_direction(did, current_user):
    direction = db.session.get(Direction, did)
    if not direction: abort(404)
    direction.is_archived = False
    db.session.commit()
    flash('Направление восстановлено.', 'success')
    return redirect(url_for('directions.directions_list'))

@directions_bp.route("/", endpoint="directions_list")
@login_required
def directions_list(current_user):
    direction_query = Direction.query.filter_by(is_archived=False)
    if current_user.role == UserRole.STAFF.value:
        visible_ids = _staff_visible_direction_ids(current_user)
        direction_query = direction_query.filter(Direction.id.in_(visible_ids)) if visible_ids else direction_query.filter(db.false())
    if current_user.role == UserRole.LEADER.value:
        allowed_ids = _lesson_access_scope(current_user)
        if allowed_ids is not None:
            direction_query = direction_query.filter(Direction.id.in_(allowed_ids))
    directions = direction_query.order_by(Direction.name).all()
    archived_directions = (Direction.query.filter_by(is_archived=True).order_by(Direction.name).all()
                           if current_user.role == UserRole.SUPER_ADMIN.value else [])
    direction_visit_counts = {}
    for direction in directions:
        event_ids = {q.id for q in direction.quotas}
        visited = set()
        for quota in direction.quotas:
            for day in quota.days:
                for participation in day.participations:
                    if participation.status == "attended":
                        visited.add((participation.student_id, quota.id))
        direction_visit_counts[direction.id] = {
            "events": len(event_ids),
            "visits": len(visited),
            "attenders": len({student_id for student_id, _ in visited}),
        }
    return render_template("directions/list.html", directions=directions, archived_directions=archived_directions,
                           is_admin=current_user.role == UserRole.SUPER_ADMIN.value,
                           is_staff=current_user.role == UserRole.STAFF.value,
                           direction_visit_counts=direction_visit_counts)

@directions_bp.route("/<int:did>/chat-message", methods=["GET", "POST"], endpoint="chat_message")
@login_required
def chat_message(did, current_user):
    direction = Direction.query.get_or_404(did)
    from services.staff_access import allowed as staff_allowed
    from services.applications import can_user_manage_direction
    if current_user.role == UserRole.SUPER_ADMIN.value:
        can_send = True
    elif current_user.role == UserRole.STAFF.value:
        can_send = staff_allowed(current_user, did, 'chats', 'manage')
    elif current_user.role == UserRole.LEADER.value:
        can_send = can_user_manage_direction(current_user.id, did, None)
    else:
        can_send = False
    if not can_send:
        abort(403)
    if current_user.role in {UserRole.STAFF.value, UserRole.OBSERVER.value} and getattr(direction, 'is_archived', False):
        abort(404)
    # Never accept target IDs from the browser; only the configured direction.
    tg_chats = telegram_targets_for_directions([did])
    social_chats = MessengerChat.query.filter_by(direction_id=did, is_active=True).all()
    if request.method == "POST":
        message_text = request.form.get("message", "").strip()
        if not message_text or len(message_text) > 4000:
            flash("Укажите текст объявления до 4000 символов.", "danger")
            return redirect(url_for("directions.chat_message", did=did))
        if not tg_chats and not social_chats:
            flash("У направления пока нет активных чатов ни в одном мессенджере.", "warning")
            return redirect(url_for("directions.chat_message", did=did))
        payload = "📡 <b>Объявление студенческого совета</b>\n\n" + html.escape(message_text)
        sent = sum(1 for _, chat_id in tg_chats if _send_tg(chat_id, payload))
        queued = queue_social_chat_announcement([did],
            "📡 Объявление студенческого совета\n\n" + message_text)
        flash(f"Telegram: доставлено в {sent}/{len(tg_chats)} чатов. "
              f"VK/MAX: поставлено в очередь {queued} сообщений. "
              "Для VK/MAX постановка в очередь не гарантирует доставку.",
              "success" if sent or queued else "warning")
        return redirect(url_for("directions.chat_message", did=did))
    return render_template("directions/chat.html", direction=direction,
                           telegram_count=len(tg_chats),
                           vk_count=sum(chat.platform == 'vk' for chat in social_chats),
                           max_count=sum(chat.platform == 'max' for chat in social_chats))

@directions_bp.route("/<int:did>")
@login_required
def direction_detail(did, current_user):
    direction = Direction.query.get_or_404(did)
    if current_user.role in {UserRole.OBSERVER.value, UserRole.STAFF.value} and getattr(direction, "is_archived", False):
        abort(404)
    from services.applications import can_user_manage_direction
    from services.staff_access import allowed as staff_allowed
    if current_user.role == UserRole.LEADER.value and not can_user_manage_direction(current_user.id, did, None):
        abort(403)

    # Scoped employees may open only a direction where they hold at least one
    # permission. The home direction is additionally enforced in staff_access.
    is_scoped_staff = current_user.role == UserRole.STAFF.value
    if is_scoped_staff:
        staff_rights = {section: (staff_allowed(current_user, did, section, 'view') or
                                  staff_allowed(current_user, did, section, 'manage'))
                        for section in ('students', 'applications', 'events', 'lessons', 'notifications', 'chats')}
        if not any(staff_rights.values()):
            abort(403)
    else:
        staff_rights = {section: True for section in ('students', 'applications', 'events', 'lessons', 'notifications', 'chats')}

    can_view_students = staff_rights['students']
    can_view_applications = staff_rights['applications']
    can_view_events = staff_rights['events']
    can_view_lessons = staff_rights['lessons']
    can_send_direction_chat = (
        current_user.role == UserRole.SUPER_ADMIN.value or
        (current_user.role == UserRole.STAFF.value and staff_allowed(current_user, did, 'chats', 'manage')) or
        (current_user.role == UserRole.LEADER.value and can_user_manage_direction(current_user.id, did, None))
    )
    can_view_questions = not is_scoped_staff
    can_manage_direction_chats = _can_manage_direction_chats(current_user, did)
    # Employees intentionally receive a send-only chat experience. They do
    # not see discovered candidates, chat IDs, assignments or configuration.
    can_view_direction_chats = current_user.role in {
        UserRole.SUPER_ADMIN.value, UserRole.OBSERVER.value, UserRole.LEADER.value
    }

    # All roles share the same direction page; staff receive only information
    # covered by their explicit grants. Student details/history require the
    # separate Students -> View permission.
    can_manage_direction = current_user.role == UserRole.SUPER_ADMIN.value or (
        current_user.role == UserRole.LEADER.value
        and can_user_manage_direction(current_user.id, did, None)
    )

    # Получаем состав направления только если разрешён просмотр участников
    # или заявлений; иные разрешения не раскрывают реестр студентов.
    links = db.session.execute(
        student_directions.select().where(student_directions.c.direction_id == did)
    ).fetchall() if (can_view_students or can_view_applications) else []
    link_by_student = {link.student_id: link for link in links}
    student_ids = list(link_by_student)
    student_query = Student.query
    if can_view_students:
        student_query = student_query.options(selectinload(Student.directions))
    students = (
        student_query.filter(Student.id.in_(student_ids))
        .order_by(Student.full_name.asc())
        .all()
        if student_ids else []
    )
    if current_user.role == UserRole.LEADER.value:
        students = [student for student in students if can_user_manage_direction(current_user.id, did, student.education_type)]
        student_ids = [student.id for student in students]
        link_by_student = {sid: link for sid, link in link_by_student.items() if sid in student_ids}
    for student in students:
        student.display_directions = (
            [item for item in student.directions if item.id == did]
            if current_user.role == UserRole.SUPER_ADMIN.value else list(student.directions)
        ) if can_view_students else []
    students_by_id = {student.id: student for student in students}
    students_with_status = []

    # Роли руководителей запрашиваются сразу для всего направления.
    leadership_by_student = {}
    if student_ids:
        leadership_rows = StudentLeadership.query.filter(
            StudentLeadership.direction_id == did,
            StudentLeadership.student_id.in_(student_ids),
        ).order_by(StudentLeadership.id.asc()).all()
        for leader in leadership_rows:
            leadership_by_student.setdefault(leader.student_id, leader.position_name or "Руководитель")

    # История посещений/отказов готовится пакетными запросами. Не загружаем в Python
    # все мероприятия и отметки института, если нужны только записи этих студентов.
    attendance_rows = []
    declines = []
    if student_ids and can_view_students:
        attendance_rows = db.session.query(
            DayParticipation.student_id, EventDay.quota_id
        ).join(
            EventDay, DayParticipation.day_id == EventDay.id
        ).filter(
            DayParticipation.student_id.in_(student_ids),
            DayParticipation.status == "attended",
        ).distinct().all()
        declines = EventQuotaDecline.query.filter(
            EventQuotaDecline.student_id.in_(student_ids)
        ).order_by(EventQuotaDecline.created_at.desc(), EventQuotaDecline.id.desc()).all()

    history_quota_ids = {quota_id for _, quota_id in attendance_rows}
    history_quota_ids.update(decline.quota_id for decline in declines)
    history_quotas = (
        EventQuota.query.filter(EventQuota.id.in_(history_quota_ids)).all()
        if history_quota_ids else []
    )
    quota_by_id = {quota.id: quota for quota in history_quotas}

    attended_by_student = {}
    for student_id, quota_id in attendance_rows:
        quota = quota_by_id.get(quota_id)
        if quota is not None:
            attended_by_student.setdefault(student_id, {})[quota_id] = quota

    declines_by_student = {}
    for decline in declines:
        event = quota_by_id.get(decline.quota_id)
        declines_by_student.setdefault(decline.student_id, []).append({
            "decline": decline,
            "event_title": event.event_title if event else f"Мероприятие #{decline.quota_id}",
        })

    for student in students:
        link = link_by_student[student.id]
        declined_events = declines_by_student.get(student.id, [])
        attended_events = list(attended_by_student.get(student.id, {}).values())
        attended_events.sort(key=lambda event: event.id, reverse=True)
        students_with_status.append({
            "student": student,
            "status": link.status,
            "link": link,
            "leadership_position": leadership_by_student.get(student.id),
            "attended_events": attended_events,
            "declined_events": declined_events,
            "decline_count": len(declined_events),
        })

    linked_ids = set(link_by_student)
    # Avoid querying chat candidates or returning their identifiers for non-superadmins.
    telegram_candidates = []
    social_candidates = []
    connected_social_chats = []
    if can_view_direction_chats:
        connected_social_chats = MessengerChat.query.filter_by(direction_id=did).order_by(
            MessengerChat.platform, MessengerChat.title).all()
    if can_manage_direction_chats:
        linked_chat_ids = {str(chat.chat_id) for chat in direction.chats}
        telegram_query = TelegramChatCandidate.query.order_by(
            TelegramChatCandidate.last_seen_at.desc()).limit(50).all()
        if current_user.role == UserRole.STAFF.value:
            used_telegram_ids = {str(value) for (value,) in DirectionChat.query.with_entities(
                DirectionChat.chat_id).filter(DirectionChat.direction_id != did).all()}
        else:
            used_telegram_ids = set()
        telegram_candidates = [
            candidate for candidate in telegram_query
            if str(candidate.chat_id) not in linked_chat_ids
            and str(candidate.chat_id) not in used_telegram_ids
            and candidate.chat_type in {"group", "supergroup", "channel"}
        ]
        social_query = MessengerChatCandidate.query.order_by(
            MessengerChatCandidate.last_seen_at.desc()).all()
        if current_user.role == UserRole.STAFF.value:
            used_social_ids = {(row.platform, str(row.chat_id)) for row in MessengerChat.query.filter(
                MessengerChat.direction_id != did).all()}
            social_candidates = [candidate for candidate in social_query
                                 if (candidate.platform, str(candidate.chat_id)) not in used_social_ids]
        else:
            social_candidates = social_query
    from services.student_contacts import public_student_contacts
    messenger_by_student = public_student_contacts(student_ids) if can_view_students else {}
    return render_template(
        "directions/detail.html",
        direction=direction,
        students_with_status=students_with_status,
        messenger_by_student=messenger_by_student,
        can_manage_direction=can_manage_direction,
        can_view_students=can_view_students,
        can_view_applications=can_view_applications,
        can_view_events=can_view_events,
        can_view_lessons=can_view_lessons,
        can_view_questions=can_view_questions,
        can_send_direction_chat=can_send_direction_chat,
        can_manage_direction_chats=can_manage_direction_chats,
        can_view_direction_chats=can_view_direction_chats,
        telegram_candidates=telegram_candidates,
        social_candidates=social_candidates,
        connected_social_chats=connected_social_chats,
        students_by_status={
            "pending": [item for item in students_with_status if item["status"] == "pending"],
            "interview": [item for item in students_with_status if item["status"] == "interview"],
            "active": [item for item in students_with_status if item["status"] == "active"],
            "rejected": [item for item in students_with_status if item["status"] == "rejected"],
        },
    )

@directions_bp.route("/<int:did>/questions", methods=["GET", "POST"], endpoint="manage_questions")
@login_required
def manage_questions(did, current_user):
    d = Direction.query.get_or_404(did)
    if current_user.role == UserRole.OBSERVER.value and getattr(d, "is_archived", False):
        abort(404)
    from services.applications import can_user_manage_direction
    if current_user.role == UserRole.LEADER.value and not can_user_manage_direction(current_user.id, did, None):
        abort(403)
    can_manage_questions = current_user.role in {UserRole.SUPER_ADMIN.value, UserRole.LEADER.value}

    if request.method == "POST":
        if not can_manage_questions:
            abort(403)
        action = request.form.get("action")
        
        if action == "add":
            text = request.form.get("question_text", "").strip()
            if text:
                max_order = db.session.query(func.max(DirectionQuestion.sort_order)).filter_by(direction_id=did).scalar() or 0
                q = DirectionQuestion(direction_id=did, question_text=text, sort_order=max_order + 1)
                db.session.add(q); db.session.commit(); flash("Вопрос добавлен", "success")
                
        elif action == "delete":
            qid = request.form.get("question_id", type=int)
            q = DirectionQuestion.query.get(qid)
            if q and q.direction_id == did:
                db.session.delete(q); db.session.commit(); flash("Вопрос удален", "success")
                
        return redirect(url_for("directions.manage_questions", did=did))
    
    questions = DirectionQuestion.query.filter_by(direction_id=did).order_by(DirectionQuestion.sort_order).all()
    return render_template("directions/questions.html", direction=d, questions=questions,
                           can_manage_questions=can_manage_questions)

@directions_bp.route("/<int:did>/add_student", methods=["POST"], endpoint="add_existing_student")
@login_required
def add_existing_student(did, current_user):
    from services.applications import can_user_manage_direction
    direction = Direction.query.get_or_404(did)
    sid = request.form.get("student_id", type=int)
    status = request.form.get("status", DirectionStatus.ACTIVE.value)
    if status not in {x.value for x in DirectionStatus}:
        status = DirectionStatus.ACTIVE.value
    if status == DirectionStatus.REJECTED.value:
        flash("Отклонять заявление нужно через форму с обязательной причиной отказа.", "danger")
        return redirect(url_for("directions.direction_detail", did=did))
    student = Student.query.get(sid) if sid else None
    if student and not can_user_manage_direction(current_user.id, did, student.education_type):
        abort(403)
    if not student:
        flash("Выберите существующего студента.", "danger")
        return redirect(url_for("directions.direction_detail", did=did))
    from services.applications import active_application_block
    active_block = active_application_block(student.id, direction.id)
    if active_block:
        flash(f"В этом направлении действует блокировка до {active_block.blocked_until.strftime('%d.%m.%Y %H:%M')}.", "danger")
        return redirect(url_for("directions.direction_detail", did=did))
    existing = db.session.execute(student_directions.select().where(
        (student_directions.c.student_id == sid) & (student_directions.c.direction_id == did)
    )).fetchone()
    if existing:
        flash(f"{student.full_name} уже состоит в этом направлении.", "warning")
        return redirect(url_for("directions.direction_detail", did=did))
    db.session.execute(student_directions.insert().values(
        student_id=sid, direction_id=did, status=status, joined_at=datetime.utcnow()
    ))
    record_activity("application_submitted", f'Студент вручную добавлен в направление «{direction.name}» со статусом «{status}».', student_id=student.id, direction_id=direction.id)
    db.session.commit()
    flash(f"{student.full_name} добавлен в «{direction.name}».", "success")
    return redirect(url_for("directions.direction_detail", did=did))

@directions_bp.route("/<int:did>/remove/<int:sid>", methods=["POST"])
@login_required
def remove_student(did, sid, current_user):
    from services.applications import can_user_manage_direction
    direction = Direction.query.get_or_404(did)
    student = Student.query.get_or_404(sid)
    if not can_user_manage_direction(current_user.id, did, student.education_type):
        abort(403)
    link = db.session.execute(student_directions.select().where(
        (student_directions.c.student_id == sid) & (student_directions.c.direction_id == did)
    )).fetchone()
    if not link:
        flash("Студент уже не состоит в направлении", "warning")
        return redirect(url_for("directions.direction_detail", did=did))
    from services.chair_membership import direction_required_by_current_role
    if direction_required_by_current_role(student.id, did):
        flash("Нельзя удалить членство, пока оно требуется действующей руководящей должностью. Сначала снимите должность.", "warning")
        return redirect(url_for("directions.direction_detail", did=did))
    db.session.execute(student_directions.delete().where(
        (student_directions.c.student_id == sid) & (student_directions.c.direction_id == did)
    ))
    record_activity("application_withdrawn", f'Студент удалён из направления «{direction.name}» администратором.', student_id=student.id, direction_id=direction.id)
    db.session.commit()
    removed_count = remove_student_from_direction_chats(student, direction)
    flash(f"{student.full_name} удалён из «{direction.name}». Удалено из чатов: {removed_count}", "success")
    return redirect(url_for("directions.direction_detail", did=did))

@directions_bp.route("/<int:did>/update_status/<int:sid>", methods=["POST"])
@login_required
def update_student_status(did, sid, current_user):
    from services.applications import can_user_manage_direction
    candidate = Student.query.get(sid)
    if not candidate or not can_user_manage_direction(current_user.id, did, candidate.education_type):
        abort(403)
    new_status = request.form.get("new_status")
    if new_status == DirectionStatus.REJECTED.value:
        from services.applications import set_application_status
        ok, message, _ = set_application_status(
            sid, did, DirectionStatus.REJECTED.value,
            reason=request.form.get("reason"), actor_user_id=current_user.id, source="web",
        )
        flash(message, "success" if ok else "danger")
        return redirect(url_for("directions.direction_detail", did=did))
    if new_status not in {DirectionStatus.PENDING.value, DirectionStatus.INTERVIEW.value, DirectionStatus.ACTIVE.value}:
        flash("Недопустимый статус заявки.", "danger")
        return redirect(url_for("directions.direction_detail", did=did))
    link = db.session.execute(student_directions.select().where(
        (student_directions.c.student_id == sid) & (student_directions.c.direction_id == did)
    )).fetchone()
    
    if link:
        old_status = link.status
        if old_status == DirectionStatus.REJECTED.value:
            flash("Отклонённую заявку нельзя изменить вручную. Студент должен подать новое заявление после окончания блокировки.", "danger")
            return redirect(url_for("directions.direction_detail", did=did))
        db.session.execute(student_directions.update().where(
            (student_directions.c.student_id == sid) & (student_directions.c.direction_id == did)
        ).values(status=new_status))
        student = Student.query.get(sid)
        direction = Direction.query.get(did)
        record_activity("application_status_changed", f'Статус изменён с «{old_status}» на «{new_status}».', student_id=sid, direction_id=did)
        db.session.commit()
        
        templates = {
            'rejected': 'direction_rejected', 'interview': 'interview_invite', 'active': 'activation'
        }
        if new_status == DirectionStatus.ACTIVE.value:
            from services.applications import notify_approval
            notify_approval(student, direction, send_invites=True, immediately_active=True)
        elif new_status in templates:
            send_notification_by_template(student, templates[new_status],
                {"direction": f"{direction.icon or '✦'} {direction.name}", "student_name": student.full_name,
                 "date": "уточняется", "location": "уточняется"})
        if new_status == DirectionStatus.REJECTED.value:
            remove_student_from_direction_chats(student, direction)
                
        flash(f"Статус изменен с {old_status} на {new_status}", "success")
    return redirect(url_for("directions.direction_detail", did=did))

@quotas_bp.route("/create", methods=["GET", "POST"], endpoint="create_quota")
@login_required
def create_quota(current_user):
    if current_user.role == UserRole.OBSERVER.value:
        flash("Мероприятия доступны только для просмотра.", "info")
        return redirect(url_for("admin.calendar", date=request.args.get("date", "")[:10] or None))
    if request.method == "GET":
        direction_query = Direction.query.filter_by(is_archived=False).order_by(Direction.name.asc())
        if current_user.role in {UserRole.STAFF.value, UserRole.SUPER_ADMIN.value}:
            from services.staff_access import direction_ids as staff_direction_ids
            permitted_event_ids = set(staff_direction_ids(current_user, 'events', 'manage'))
            direction_query = direction_query.filter(Direction.id.in_(permitted_event_ids)) if permitted_event_ids else direction_query.filter(db.false())
            if not permitted_event_ids:
                flash("Нет доступного направления для создания мероприятий. Проверьте назначение рабочего направления.", "warning")
                return redirect(url_for("admin.dashboard"))
        if current_user.role == UserRole.LEADER.value:
            allowed_direction_ids = _lesson_access_scope(current_user)
            if allowed_direction_ids is not None:
                direction_query = direction_query.filter(Direction.id.in_(allowed_direction_ids))
        directions = direction_query.all()
        if current_user.role == UserRole.LEADER.value and not directions:
            flash("У вас нет разрешения создавать мероприятия ни в одном направлении.", "warning")
            return redirect(url_for("admin.dashboard"))
        selected_date = request.args.get("date", "")[:10]
        try:
            datetime.strptime(selected_date, "%Y-%m-%d")
        except ValueError:
            selected_date = datetime.now().strftime("%Y-%m-%d")
        can_assign_event_chats = current_user.role == UserRole.SUPER_ADMIN.value
        return render_template("events/form.html", directions=directions,
                               chat_options=_event_chat_picker_options() if can_assign_event_chats else [],
                               can_assign_event_chats=can_assign_event_chats,
                               selected_date=selected_date,
                               return_to_calendar=request.args.get("return_to") == "calendar")

    t = request.form.get("title", "").strip()
    desc = request.form.get("description", "").strip()
    loc = request.form.get("location", "").strip()
    tr = request.form.get("time_range", "").strip()
    dc = request.form.get("dress_code", "").strip()
    func = request.form.get("functionality", "").strip()
    places = request.form.get("total_places", type=int)
    dids = request.form.getlist("direction_ids", type=int)

    # Даты мероприятия больше не ограничены фиксированным количеством полей.
    raw_day_indexes = []
    for key in request.form.keys():
        if key.startswith("day_date_"):
            try:
                raw_day_indexes.append(int(key.rsplit("_", 1)[1]))
            except (ValueError, IndexError):
                continue

    days = []
    invalid_days = []
    for i in sorted(set(raw_day_indexes)):
        ds = (request.form.get(f"day_date_{i}") or "").strip()
        pl = request.form.get(f"day_places_{i}", type=int)
        if not ds and not pl:
            continue
        if not ds or not pl or pl < 1:
            invalid_days.append(i + 1)
            continue
        try:
            parsed_date = datetime.strptime(ds, "%Y-%m-%d")
            days.append({"date": parsed_date, "places": pl})
        except ValueError:
            invalid_days.append(i + 1)

    days.sort(key=lambda item: item["date"])

    if invalid_days:
        flash("Проверьте даты мероприятия: заполните дату и количество мест для каждой добавленной даты.", "danger")
        return redirect(url_for("quotas.create_quota"))

    if not all([t, dids, days, places]) or places < 1:
        flash("Заполните название, направления, даты и количество мест!", "danger")
        return redirect(url_for("quotas.create_quota"))

    if len({day["date"].date() for day in days}) != len(days):
        flash("Одна и та же дата выбрана несколько раз. Укажите уникальные даты.", "danger")
        return redirect(url_for("quotas.create_quota"))

    valid_dids = [d.id for d in Direction.query.filter(
        Direction.id.in_(dids), Direction.is_archived.is_(False)
    ).all()]
    if not valid_dids:
        flash("Выберите хотя бы одно существующее активное направление.", "danger")
        return redirect(url_for("quotas.create_quota"))
    if current_user.role in {UserRole.STAFF.value, UserRole.SUPER_ADMIN.value}:
        from services.staff_access import allowed as staff_allowed
        # A forged direction id must not let an account create an event outside
        # its explicit operational direction and event-management scope.
        if set(valid_dids) != set(dids) or any(
            not staff_allowed(current_user, direction_id, 'events', 'manage')
            for direction_id in valid_dids
        ):
            abort(403)
    elif current_user.role == UserRole.LEADER.value:
        from services.applications import can_user_manage_direction
        # A forged direction id must not let a leader publish an event outside
        # their own appointed scope, even if the form is submitted manually.
        if set(valid_dids) != set(dids) or any(
            not can_user_manage_direction(current_user.id, direction_id, None)
            for direction_id in valid_dids
        ):
            abort(403)

    # Only the chief administrator may assign event-specific delivery chats.
    # Never trust hidden/forged form controls: ignore submitted chat IDs from every
    # other role even when they bypass the template and send a handcrafted POST.
    can_assign_event_chats = current_user.role == UserRole.SUPER_ADMIN.value
    if can_assign_event_chats:
        _chat_options, selected_targets, invalid_chat_keys = _resolve_event_chat_selection(
            valid_dids, request.form.getlist('event_chat_targets'))
        if invalid_chat_keys:
            flash("Список чатов изменился. Обновите форму и выберите актуальные чаты.", "danger")
            return redirect(url_for("quotas.create_quota", date=request.args.get("date", ""),
                                    return_to=request.args.get("return_to", "")))
    else:
        selected_targets = []
        if request.form.getlist('event_chat_targets'):
            logger.warning("Ignored forged event_chat_targets submitted by non-super-admin user_id=%s", current_user.id)
    publish_mode = request.form.get("publish_mode", "immediate")
    if publish_mode not in {"immediate", "scheduled", "manual"}:
        publish_mode = "immediate"
    publish_at = None
    if publish_mode == "scheduled":
        try:
            publish_at = datetime.strptime(request.form.get("publish_at", ""), "%Y-%m-%dT%H:%M")
            if publish_at <= datetime.now():
                raise ValueError
        except ValueError:
            flash("Для автопубликации укажите корректные дату и время в будущем.", "danger")
            return redirect(url_for("quotas.create_quota"))

    q = EventQuota(
        event_title=t, event_description=desc, location=loc, time_range=tr,
        dress_code=dc, functionality=func, total_places=places,
        publish_mode=publish_mode, publish_at=publish_at,
        is_published=(publish_mode == "immediate"), chat_selection_explicit=True
    )
    for dd in days:
        q.days.append(EventDay(date=dd["date"], daily_places=dd["places"]))

    db.session.add(q)
    db.session.flush()
    set_quota_directions(q.id, valid_dids)
    set_quota_chat_targets(q.id, selected_targets)
    record_activity("quota_created", f'Создано мероприятие «{t}».', quota_id=q.id)
    db.session.commit()

    invite_link_failures = 0
    if any(target[0] == 'telegram' for target in selected_targets):
        try:
            from services.activity_chats import prepare_event_chat_invites
            _, invite_link_failures = prepare_event_chat_invites(q.id)
        except Exception:
            logger.exception('Could not prepare event-specific Telegram invitations for quota #%s', q.id)
            invite_link_failures = sum(1 for target in selected_targets if target[0] == 'telegram')

    event_chat_text = _event_chat_announcement(q)
    queued = 0
    enqueue_error = False
    if publish_mode == "immediate":
        try:
            queued = queue_other_messenger_event(q, event_chat_text,
                                                  batch_key=f"quota:{q.id}:initial")
        except Exception:
            # Quota and its dates were already committed: do not turn a valid
            # event into an HTTP 500 just because a messenger is unavailable.
            logger.exception('Could not queue initial announcement for quota #%s', q.id)
            enqueue_error = True
    elif publish_mode == "scheduled":
        logger.info('Quota #%s scheduled for %s', q.id, publish_at)
    else:
        logger.info('Quota #%s saved as an unpublished draft', q.id)
    if publish_mode == 'immediate':
        try:
            from services.direction_publishing import publish_direction_announcement
            publish_direction_announcement(valid_dids, t,
                f'Мероприятие: {", ".join(day["date"].strftime("%d.%m.%Y") for day in days)}. {loc or "Место уточняется"}. {desc}',
                category='events', creator_user_id=current_user.id,
                channels={'site','dm','vk_dm','max_dm','staff_dm'},
                source_type='event', source_id=q.id, batch_key=f'event:{q.id}:personal')
        except Exception:
            logger.exception('Event #%s personal broadcast failed', q.id)
            db.session.rollback()
    if publish_mode == 'immediate':
        record_activity('quota_published',
                        f'Мероприятие «{t}»: сообщений в очереди TG/VK/MAX — {queued}.', quota_id=q.id)
        db.session.commit()

    # Personal Telegram/VK/MAX notifications are queued durably by
    # publish_direction_announcement; never fire untracked HTTP threads.

    if publish_mode == 'immediate':
        if enqueue_error:
            flash(f'«{t}» сохранено, но объявление не попало в очередь. Проверьте журнал и базу данных.', 'warning')
        else:
            flash(f'«{t}» опубликовано на сайте. Готовы к отправке: {queued}. Если в чатах пусто — откройте журнал доставок, проверьте чаты и токены.', 'success' if queued else 'warning')
    elif publish_mode == 'scheduled':
        flash(f'«{t}» создано. Автопубликация: {publish_at:%d.%m.%Y %H:%M}.', 'success')
    else:
        flash(f'«{t}» сохранено как черновик, публикация не запускалась.', 'success')
    if invite_link_failures:
        flash(f'Для {invite_link_failures} Telegram-чат(ов) не удалось создать ссылку вступления. Проверьте, что бот — администратор группы с правом приглашать участников.', 'warning')
    if not selected_targets:
        flash('У мероприятия пока нет выбранных чатов для рассылки. Оно останется в календаре, но сообщение в мессенджеры не отправится.', 'warning')
    if request.form.get("return_to") == "calendar":
        return redirect(url_for("admin.calendar", date=request.form.get("calendar_date") or (days[0]["date"].strftime("%Y-%m-%d") if days else None)))
    return redirect(url_for("admin.calendar", date=(days[0]["date"].strftime("%Y-%m-%d") if days else None)))

def publish_due_quotas():
    """Make scheduled events visible on the website and queue chat delivery.

    The scheduler runs even when bot tokens are not yet configured. A stable
    batch key prevents duplicate chat jobs on repeated scheduler iterations.
    """
    now = datetime.now()
    due = EventQuota.query.filter_by(
        publish_mode="scheduled", is_published=False, is_closed=False
    ).filter(EventQuota.publish_at <= now).all()
    for quota in due:
        text = _event_chat_announcement(quota)
        try:
            queued = queue_other_messenger_event(quota, text)
        except Exception:
            logger.exception('Scheduled quota #%s failed to enqueue; will retry', quota.id)
            continue
        try:
            from services.direction_publishing import publish_direction_announcement
            publish_direction_announcement([d.id for d in quota.directions], quota.event_title,
                f'Мероприятие: {", ".join(day.date.strftime("%d.%m.%Y") for day in quota.days)}. {quota.location or "Место уточняется"}. {quota.event_description or ""}',
                category='events', channels={'site','dm','vk_dm','max_dm','staff_dm'},
                source_type='event', source_id=quota.id, batch_key=f'event:{quota.id}:personal')
        except Exception:
            logger.exception('Scheduled event personal announcement failed #%s; scheduler will retry', quota.id)
            db.session.rollback()
            continue
        quota.is_published = True
        record_activity('quota_published',
                        f'Мероприятие «{quota.event_title}»: в очереди TG/VK/MAX — {queued}.', quota_id=quota.id)
        db.session.commit()


@quotas_bp.route("/<int:qid>/publish", methods=["POST"], endpoint="publish_quota")
@login_required
def publish_quota(qid, current_user):
    if current_user.role not in {UserRole.SUPER_ADMIN.value, UserRole.STAFF.value}:
        abort(403)
    quota = EventQuota.query.get_or_404(qid)
    event_chat_text = _event_chat_announcement(quota)
    try:
        queued = queue_other_messenger_event(quota, event_chat_text)
    except Exception:
        logger.exception('Could not enqueue quota #%s publication', quota.id)
        flash('Не удалось поставить объявление в очередь. Мероприятие сохранено. Проверьте журнал и базу.', 'danger')
        return redirect(url_for('admin.calendar', date=(quota.days[0].date.strftime('%Y-%m-%d') if quota.days else None)))
    quota.is_published = True
    try:
        from services.direction_publishing import publish_direction_announcement
        publish_direction_announcement([d.id for d in quota.directions], quota.event_title,
            f'Мероприятие: {", ".join(day.date.strftime("%d.%m.%Y") for day in quota.days)}. {quota.location or "Место уточняется"}. {quota.event_description or ""}',
            category='events', creator_user_id=current_user.id,
            channels={'site','dm','vk_dm','max_dm','staff_dm'},
            source_type='event', source_id=quota.id, batch_key=f'event:{quota.id}:personal')
    except Exception:
        logger.exception('Manual event personal announcement failed #%s', quota.id)
        db.session.rollback()
    record_activity('quota_published',
                    f'Мероприятие «{quota.event_title}»: в очереди TG/VK/MAX — {queued}.', quota_id=quota.id)
    db.session.commit()
    flash(f'Мероприятие опубликовано на сайте. К отправке готовы: {queued}. Проверяйте подтверждённую доставку в журнале TG/VK/MAX.', 'success' if queued else 'warning')
    if request.args.get("return_to") == "calendar":
        return redirect(url_for("admin.calendar", date=request.args.get("date") or
                                (quota.days[0].date.strftime("%Y-%m-%d") if quota.days else None)))
    return redirect(url_for('admin.calendar', date=(quota.days[0].date.strftime('%Y-%m-%d') if quota.days else None)))

@quotas_bp.route("/")
@login_required
def quotas_list(current_user):
    """Old event-list links now open the unified lesson/event calendar."""
    return redirect(url_for("admin.calendar"))

@quotas_bp.route("/participants/<int:qid>", endpoint="quota_participants")
@login_required
def quota_participants(qid, current_user):
    quota = EventQuota.query.get_or_404(qid)
    declines = EventQuotaDecline.query.filter_by(quota_id=qid).order_by(EventQuotaDecline.created_at.desc()).all()
    student_ids = {row.student_id for row in declines}
    students = {s.id: s for s in Student.query.filter(Student.id.in_(student_ids)).all()} if student_ids else {}
    decline_items = [{"decline": row, "student": students.get(row.student_id)} for row in declines]
    return render_template("events/participants.html", quota=quota, decline_items=decline_items)

@quotas_bp.route("/mark/<int:pid>/<st>", methods=["POST"], endpoint="mark_attendance")
@login_required
def mark_att(pid, st, current_user):
    if current_user.role == UserRole.OBSERVER.value:
        flash("Наблюдатель не может изменять посещаемость.", "warning")
        return redirect(request.referrer or url_for("admin.dashboard"))
    if st not in {"registered", "attended", "absent", "cancelled"}:
        flash("Неизвестный статус посещаемости.", "danger")
        return redirect(url_for("admin.dashboard"))
    p = DayParticipation.query.get_or_404(pid)
    previous_status = p.status
    p.status = st
    student = Student.query.get(p.student_id)
    event = p.day.quota if p.day else None
    event_date = p.day.date.strftime("%d.%m.%Y в %H:%M") if p.day and p.day.date else "дата уточняется"
    record_activity("attendance_updated", f'Изменён статус участия на «{st}» для даты {p.day.date.strftime("%d.%m.%Y")}.', student_id=p.student_id, quota_id=p.day.quota_id)
    db.session.commit()

    # Notify the student in a private Telegram chat when a leader records a final attendance result.
    # Do not send messages for intermediate/reset statuses or when the status did not change.
    if st in {"attended", "absent"} and previous_status != st and student and student.tg_id and student.tg_id > 0:
        try:
            from services.telegram import send_tg
            if st == "attended":
                message = (
                    "✅ <b>Посещаемость подтверждена</b>\n\n"
                    f"Мероприятие: <b>{html.escape(event.event_title if event else 'Мероприятие')}</b>\n"
                    f"Дата: {html.escape(event_date)}\n\n"
                    "Глава направления отметил, что вы были на мероприятии."
                )
            else:
                message = (
                    "⚠️ <b>Отмечено отсутствие</b>\n\n"
                    f"Мероприятие: <b>{html.escape(event.event_title if event else 'Мероприятие')}</b>\n"
                    f"Дата: {html.escape(event_date)}\n\n"
                    "Глава направления отметил, что вы не были на мероприятии. "
                    "Если это ошибка, свяжитесь с руководителем направления."
                )
            if not send_tg(student.tg_id, message):
                logger.warning("Attendance Telegram notification was not delivered for student_id=%s", student.id)
        except Exception:
            logger.exception("Failed to send attendance notification for student_id=%s", student.id)
    flash("Статус обновлен", "success")
    return redirect(url_for("quotas.quota_participants", qid=p.day.quota_id))

def validate_telegram_init_data(init_data: str, max_age=3600):
    """Validate Telegram's signed launch data and reject ambiguous/oversized payloads."""
    if not isinstance(init_data, str) or not init_data or len(init_data) > 8192 or not settings.BOT_TOKEN:
        return None
    try:
        pairs = urllib.parse.parse_qsl(
            init_data.lstrip("?"), keep_blank_values=True, strict_parsing=True, max_num_fields=64
        )
        names = [key for key, _value in pairs]
        if not pairs or len(names) != len(set(names)):
            return None
        values = dict(pairs)
        received_hash = values.pop("hash", None)
        if not received_hash or not re.fullmatch(r"[0-9a-fA-F]{64}", received_hash):
            return None
        data_check_string = "\n".join(f"{key}={values[key]}" for key in sorted(values))
        secret_key = hmac.new(b"WebAppData", settings.BOT_TOKEN.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calculated_hash, received_hash.lower()):
            return None
        auth_date = int(values.get("auth_date", "0"))
        now = time.time()
        if not auth_date or auth_date > now + 30 or now - auth_date > max_age:
            return None
        user = json.loads(values.get("user", "{}"))
        if not isinstance(user, dict) or int(user.get("id", 0)) <= 0:
            return None
        return user
    except (TypeError, ValueError, UnicodeError, json.JSONDecodeError):
        return None

def _student_overall_status(student):
    rows=db.session.execute(student_directions.select().where(student_directions.c.student_id==student.id)).fetchall()
    statuses=[r.status for r in rows]
    if any(x==DirectionStatus.ACTIVE.value for x in statuses): return "Активный участник","active"
    if any(x in {DirectionStatus.PENDING.value,DirectionStatus.INTERVIEW.value} for x in statuses): return "Заявки рассматриваются","review"
    if statuses and all(x==DirectionStatus.REJECTED.value for x in statuses): return "Нужна новая заявка","rejected"
    return "Не поданы заявки","empty"

@admin_bp.get("/api/visual-theme")
@login_required
def visual_theme_state(current_user):
    """Return only the current visual palette for live updates on internal pages."""
    key = current_student_app_season()
    config = STUDENT_APP_SEASONS[key]
    palette = config.get("palette", ["#FFB26B", "#EE637D", "#100D1A"])
    payload = {
        "theme": key,
        "label": config.get("label", key),
        "accent": palette[0],
        "secondary": palette[1],
        "depth": palette[2],
        "accent_rgb": _hex_rgb_triplet(palette[0]),
        "secondary_rgb": _hex_rgb_triplet(palette[1]),
        "build": ":".join((
            current_app.jinja_env.globals["asset_version"]("js/site.bundle.js"),
            current_app.jinja_env.globals["asset_version"]("css/site.bundle.css"),
        )),
    }
    response = jsonify(payload)
    response.headers["Cache-Control"] = "no-store"
    return response


@student_app_bp.route("/student-app")
def student_app():
    season_key = current_student_app_season()
    return render_template(
        "student/student_app.html",
        student_app_season=season_key,
        student_app_theme=STUDENT_APP_SEASONS[season_key],
    )

@student_app_bp.get("/student-app/api/sync-state")
def student_app_sync_state():
    """Lightweight cross-worker revision for Student App live updates.

    Only a one-way digest is returned (no IDs, actors, profiles or data).
    Web writes, bot activity recorded in the business journal and visual
    settings invalidate the token. The client fetches /api/me only when
    something actually changed.
    """
    tg_id, _ = _resolve_student_identity()
    if tg_id is None:
        return jsonify({"ok": False, "error": "Недействительные данные запуска приложения"}), 401
    parts = (
        db.session.query(func.max(HttpAuditLog.id)).scalar() or 0,
        db.session.query(func.max(StudentActivity.id)).scalar() or 0,
        db.session.query(func.max(ApplicationDecision.id)).scalar() or 0,
        db.session.query(func.max(PortalSetting.updated_at)).scalar(),
    )
    # Stable within this deployment; do not reveal record counts or identifiers.
    raw = '|'.join(str(value) for value in parts).encode('utf-8')
    revision = hmac.new(str(settings.SECRET_KEY).encode('utf-8'), raw,
                        hashlib.sha256).hexdigest()[:24]
    asset_version = current_app.jinja_env.globals['asset_version']
    build_version = ':'.join((asset_version('js/student-app.bundle.js'),
                              asset_version('css/student-app.bundle.css')))
    season_key = current_student_app_season()
    response = jsonify({"ok": True, "revision": revision,
                        "season": season_key,
                        "theme_vars": STUDENT_APP_SEASONS[season_key]["css_vars"],
                        "build": build_version})
    response.headers['Cache-Control'] = 'no-store'
    return response


@student_app_bp.route("/student-app/api/me")
def student_app_me():
    tg_id, is_local = _resolve_student_identity()
    if tg_id is None:
        return jsonify({"ok": False, "error": "Не удалось определить пользователя"}), 401
    student = Student.query.filter_by(tg_id=tg_id).first()
    if not student:
        return jsonify(_student_registration_payload(is_local))
    _sync_student_telegram_profile(student)
    student = Student.query.filter_by(tg_id=tg_id).first()
    if not student:
        return jsonify(_student_registration_payload(is_local))
    student_id = int(student.id)
    student_tg_id = int(student.tg_id)

    # Existing databases may contain global council roles created before the
    # automatic-membership update. Repair chair + cohort-deputy memberships before
    # returning the directions list, so Student App reflects active membership.
    from services.chair_membership import has_membership_role, sync_student_leadership_memberships
    if has_membership_role(student_id):
        changed_memberships = sync_student_leadership_memberships(student_id)
        if changed_memberships:
            db.session.commit()
            student = Student.query.filter_by(id=student_id, tg_id=student_tg_id).first()
            if not student:
                return jsonify(_student_registration_payload(is_local))

    rows = db.session.execute(
        student_directions.select().where(student_directions.c.student_id == student_id)
    ).fetchall()
    direction_ids = [r.direction_id for r in rows]
    directions = {d.id: d for d in Direction.query.filter(Direction.id.in_(direction_ids)).all()} if direction_ids else {}
    from services.telegram import sync_student_direction_invites
    from services.chair_membership import direction_required_by_current_role

    from services.applications import active_application_block, latest_application_decision
    dir_payload = []
    latest_decisions = {}
    active_blocks = {}
    for row in rows:
        latest_decisions[row.direction_id] = latest_application_decision(student_id, row.direction_id)
        active_blocks[row.direction_id] = active_application_block(student_id, row.direction_id)
    for row in rows:
        d = directions.get(row.direction_id)
        if not d:
            continue
        invites = []
        if row.status in {DirectionStatus.ACTIVE.value}:
            try:
                # Most page loads should be DB-only. Contact Telegram only when a
                # newly connected active chat does not yet have a cached invite.
                active_chats = DirectionChat.query.filter_by(
                    direction_id=d.id, is_active=True
                ).all()
                active_chat_ids = {str(chat.chat_id) for chat in active_chats}
                cached_links = StudentInviteLink.query.filter_by(
                    student_id=student_id, direction_id=d.id
                ).all()
                cached_by_chat = {str(link.chat_id): link for link in cached_links}

                if not active_chat_ids:
                    invites = []
                elif active_chat_ids.issubset(cached_by_chat):
                    invites = [
                        {"title": cached_by_chat[chat_id].title,
                         "link": cached_by_chat[chat_id].invite_link,
                         "chat_id": chat_id}
                        for chat_id in sorted(active_chat_ids)
                    ]
                elif not settings.BOT_TOKEN:
                    # In local-demo mode, never wait on Telegram; only show cached
                    # links for chats that remain active in the local database.
                    invites = [
                        {"title": link.title, "link": link.invite_link,
                         "chat_id": str(link.chat_id)}
                        for link in cached_links
                        if str(link.chat_id) in active_chat_ids
                    ]
                else:
                    invites = sync_student_direction_invites(student, d)
            except Exception:
                db.session.rollback()
                logger.exception("Could not sync chat invites for student #%s direction #%s", student_id, d.id)
                active_chat_ids = {
                    str(chat.chat_id)
                    for chat in DirectionChat.query.filter_by(direction_id=d.id, is_active=True).all()
                }
                invites = [
                    {"title": link.title, "link": link.invite_link}
                    for link in StudentInviteLink.query.filter_by(
                        student_id=student_id, direction_id=d.id
                    ).all()
                    if str(link.chat_id) in active_chat_ids
                ]
        dir_payload.append({
            "id": d.id,
            "name": d.name,
            "code": d.code,
            "icon": d.icon,
            "description": d.description,
            "status": row.status,
            "submitted_at": row.joined_at.isoformat() if row.joined_at else None,
            "last_decision_at": (latest_decisions[row.direction_id].created_at.isoformat()
                                  if latest_decisions.get(row.direction_id) and latest_decisions[row.direction_id].created_at else None),
            "education_scope": d.education_scope,
            "invites": invites,
            "removable": not direction_required_by_current_role(student_id, d.id),
            "rejection_reason": (latest_decisions[row.direction_id].reason if latest_decisions.get(row.direction_id) and latest_decisions[row.direction_id].decision == DirectionStatus.REJECTED.value else None),
            "blocked_until": (active_blocks[row.direction_id].blocked_until.isoformat() if active_blocks.get(row.direction_id) and active_blocks[row.direction_id].blocked_until else None),
        })

    student = Student.query.filter_by(id=student_id, tg_id=student_tg_id).first()
    if not student:
        return jsonify(_student_registration_payload(is_local))
    # Ignore orphaned application rows referencing directions that no longer exist.
    active_ids = {
        r.direction_id for r in rows
        if r.status == DirectionStatus.ACTIVE.value and r.direction_id in directions
    }
    quotas = EventQuota.query.options(selectinload(EventQuota.days)).filter_by(is_closed=False, is_published=True).all()
    quota_ids = [q.id for q in quotas]
    leaders = _event_leaders_map(quota_ids)

    # Batch-load event-to-direction mappings and participant counts. Calling the
    # model properties here used to issue multiple queries and load full attendee
    # collections just to calculate the remaining places.
    quota_direction_map = {}
    if quota_ids:
        for mapping in QuotaDirection.query.filter(QuotaDirection.quota_id.in_(quota_ids)).all():
            quota_direction_map.setdefault(mapping.quota_id, set()).add(mapping.direction_id)

    participation_counts = {}
    if quota_ids:
        count_rows = db.session.query(
            DayParticipation.day_id, func.count(DayParticipation.id)
        ).join(EventDay, DayParticipation.day_id == EventDay.id).filter(
            EventDay.quota_id.in_(quota_ids),
            or_(DayParticipation.status.is_(None), DayParticipation.status != "cancelled"),
        ).group_by(DayParticipation.day_id).all()
        participation_counts = {day_id: count for day_id, count in count_rows}

    registrations = DayParticipation.query.filter_by(student_id=student.id).all()
    reg_map = {r.day_id: r for r in registrations if r.status != "cancelled"}
    decline_map = {}
    if quota_ids:
        declines = EventQuotaDecline.query.filter(
            EventQuotaDecline.student_id == student.id,
            EventQuotaDecline.quota_id.in_(quota_ids),
        ).all()
        decline_map = {item.quota_id: item for item in declines}

    visible_events = []
    for q in quotas:
        if not (quota_direction_map.get(q.id, set()) & active_ids):
            continue
        lead = leaders.get(q.id)
        days_payload = []
        for x in q.days:
            if x.date.date() < datetime.utcnow().date():
                continue
            participation = reg_map.get(x.id)
            days_payload.append({
                "id": x.id,
                "date": x.date.strftime("%Y-%m-%d"),
                "date_label": x.date.strftime("%d.%m"),
                "weekday": x.date.strftime("%a").upper(),
                "places": max(0, (x.daily_places or 0) - participation_counts.get(x.id, 0)),
                "daily_places": x.daily_places,
                "registered": bool(participation and participation.status == "registered"),
                "participation_status": participation.status if participation else None,
                "participation_id": participation.id if participation else None,
            })
        decline_record = decline_map.get(q.id)
        # Keep a refused event visible even after its last date passes so the
        # student can still undo the refusal (unless the event was formally closed).
        if not days_payload and not decline_record:
            continue
        visible_events.append({
            "id": q.id,
            "title": q.event_title,
            "description": q.event_description,
            "location": q.location,
            "time": q.time_range,
            "dress_code": q.dress_code,
            "functionality": q.functionality,
            "total_places": q.total_places,
            "leader": ({"name": lead.student.full_name, "position": lead.position_name} if lead and lead.student else None),
            "direction_ids": [d.id for d in q.directions],
            "declined": bool(decline_record),
            "decline_reason": decline_record.reason if decline_record else None,
            "declined_at": decline_record.created_at.strftime("%d.%m.%Y %H:%M") if decline_record and decline_record.created_at else None,
            "days": days_payload,
        })

    visible_events.sort(key=lambda x: (x["days"][0]["date"] if x["days"] else "9999-99-99", x["time"] or "99:99", x["title"].lower()))

    # A separate, permanent history block for events the student actually attended.
    attended_rows = DayParticipation.query.options(
        selectinload(DayParticipation.day).selectinload(EventDay.quota)
    ).filter_by(student_id=student.id, status="attended").all()
    attended_by_event = {}
    for participation in attended_rows:
        day = participation.day
        quota = day.quota if day else None
        if not day or not quota:
            continue
        item = attended_by_event.setdefault(quota.id, {
            "id": quota.id,
            "title": quota.event_title,
            "description": quota.event_description or "",
            "location": quota.location or "",
            "dates": [],
        })
        if day.date:
            # Sort by ISO dates internally so the history remains chronological across months/years.
            item["dates"].append(day.date.strftime("%Y-%m-%d"))
    attended_events = sorted(
        attended_by_event.values(),
        key=lambda item: max(item["dates"] or [""]),
        reverse=True,
    )
    for item in attended_events:
        date_keys = sorted(set(item["dates"]), reverse=True)
        item["dates"] = [datetime.strptime(value, "%Y-%m-%d").strftime("%d.%m.%Y") for value in date_keys]
        item["last_visit"] = item["dates"][0] if item["dates"] else ""

    from database import Lesson
    student_lessons = []
    if active_ids:
        lesson_rows = Lesson.query.filter(
            Lesson.direction_id.in_(active_ids),
            Lesson.starts_at >= datetime.combine(datetime.now().date(), datetime.min.time()) - timedelta(days=62),
            Lesson.starts_at < datetime.combine(datetime.now().date(), datetime.min.time()) + timedelta(days=400),
        ).order_by(Lesson.starts_at.asc()).limit(600).all()
        for lesson in lesson_rows:
            direction = directions.get(lesson.direction_id)
            student_lessons.append({
                "id": lesson.id, "title": lesson.title, "description": lesson.description or "",
                "direction_id": lesson.direction_id, "direction_name": direction.name if direction else "",
                "date": lesson.starts_at.strftime("%d.%m.%Y"),
                "time": lesson.starts_at.strftime("%H:%M"), "end_time": lesson.end_at.strftime("%H:%M"),
                "room": lesson.room or "", "teacher": lesson.teacher or "",
                "duration_minutes": lesson.duration_minutes or 90,
            })
    # Month calendar includes earlier dates even when event registration has closed.
    # Its entries still come from published quotas in the student's ACTIVE directions.
    calendar_event_payloads = []
    calendar_floor = datetime.now().date() - timedelta(days=62)
    calendar_ceiling = datetime.now().date() + timedelta(days=400)
    for quota in quotas:
        if not (quota_direction_map.get(quota.id, set()) & active_ids):
            continue
        calendar_days = [
            {"id": day.id, "date": day.date.strftime("%Y-%m-%d"),
             "registered": bool(reg_map.get(day.id) and reg_map[day.id].status == "registered")}
            for day in quota.days
            if calendar_floor <= day.date.date() <= calendar_ceiling
        ]
        if calendar_days:
            calendar_event_payloads.append({
                "id": quota.id, "title": quota.event_title,
                "description": quota.event_description or "", "location": quota.location or "",
                "time": quota.time_range or "", "direction_ids": sorted(quota_direction_map.get(quota.id, set()) & active_ids),
                "days": calendar_days,
            })
    from services.student_calendar import combine_calendar_items
    calendar_items = combine_calendar_items(student_lessons, calendar_event_payloads)
    status_label, status_code = _student_overall_status(student)
    available_dirs = []
    selected = {r.direction_id: r for r in rows}
    from services.applications import active_application_block
    for d in Direction.query.order_by(Direction.name.asc()).all():
        old_link = selected.get(d.id)
        block = active_application_block(student.id, d.id)
        resubmittable_rejection = bool(old_link and old_link.status == DirectionStatus.REJECTED.value and not block)
        if d.available_for(student.education_type) and not block and (old_link is None or resubmittable_rejection):
            available_dirs.append({
                "id": d.id, "name": d.name, "icon": d.icon, "description": d.description,
                "resubmission": bool(old_link),
                "questions": [{"id": q.id, "question": q.question_text, "required": bool(q.is_required)}
                              for q in DirectionQuestion.query.filter_by(direction_id=d.id).order_by(DirectionQuestion.sort_order, DirectionQuestion.id).all()],
            })

    from services.permissions import leadership_payload
    leadership = leadership_payload(student.id)

    # Persisted announcements: only public audience + active student departments.
    # Staff-only/admin-only notifications never enter the public Mini App payload.
    updates = []
    scoped_updates = SiteNotification.query.filter_by(audience='all').filter(
        SiteNotification.created_at > datetime.utcnow() - timedelta(minutes=90)).filter(
        or_(SiteNotification.direction_id.is_(None),
            SiteNotification.direction_id.in_(active_ids if active_ids else [-1]))
    )
    for alert in scoped_updates.order_by(SiteNotification.id.desc()).limit(180).all():
        if alert.student_id and alert.student_id != student.id:
            continue
        if alert.direction_id and alert.direction_id not in active_ids:
            continue
        if alert.education_type and alert.education_type != student.education_type:
            continue
        updates.append({
            'id': alert.id, 'title': alert.title, 'body': alert.body,
            'category': alert.category, 'date': alert.created_at.strftime('%d.%m.%Y %H:%M'), 'expires_at': (alert.created_at+timedelta(minutes=90)).isoformat()+'Z',
        })
        if len(updates) >= 40:
            break

    return jsonify({
        "ok": True,
        "registered": True,
        "local": is_local,
        "mode": _student_app_platform() or "standalone",
        "bot_available": bool(settings.BOT_TOKEN),
        "student": {
            "id": student.id,
            "full_name": student.full_name,
            "telegram_username": student.telegram_username,
            "group": student.group,
            "phone": student.phone,
            "education_type": student.education_type,
            "education_label": "Колледж" if student.education_type == "college" else "Институт",
        },
        "overall": {"label": status_label, "code": status_code},
        "directions": dir_payload,
        "available_directions": available_dirs,
        "events": visible_events[:40],
        "attended_events": attended_events[:100],
        "lessons": student_lessons,
        "calendar": calendar_items,
        "announcements": updates,
        "leadership": leadership,
    })

_LOCAL_DEMO_ID_COOKIE = "student_app_local_actor"
_LOCAL_DEMO_ID_COOKIE_MAX_AGE = 365 * 24 * 60 * 60

def _local_demo_cookie_serializer():
    """Build a serializer with a stable key in local demo installs without SECRET_KEY."""
    if getattr(settings, "SECRET_KEY_CONFIGURED", False):
        secret = settings.SECRET_KEY
    else:
        key_path = settings.DATA_DIR / ".student-app-local-demo.key"
        try:
            secret = key_path.read_text(encoding="utf-8").strip()
            if len(secret) < 32:
                raise ValueError("Invalid local demo cookie key")
        except (OSError, ValueError):
            secret = secrets.token_urlsafe(48)
            try:
                # Exclusive creation avoids overwriting the key if requests race on startup.
                with key_path.open("x", encoding="utf-8") as key_file:
                    key_file.write(secret)
            except FileExistsError:
                secret = key_path.read_text(encoding="utf-8").strip()
    return URLSafeSerializer(secret, salt="student-app-local-demo-v1")

def _local_actor_tg_id():
    """Return a stable local-demo identity independent from the admin login session.

    The admin login/logout deliberately calls ``session.clear()``. Keeping the demo
    student ID only in that session made a registered profile disappear after an
    administrator signed in using the same browser. A separately signed, HttpOnly
    cookie keeps the local-demo identity stable without weakening Telegram auth.
    """
    if not settings.LOCAL_DEMO:
        return None

    serializer = _local_demo_cookie_serializer()
    actor_id = None
    cookie_value = request.cookies.get(_LOCAL_DEMO_ID_COOKIE, "")
    if cookie_value:
        try:
            candidate = serializer.loads(cookie_value)
            if isinstance(candidate, int) and candidate < 0:
                actor_id = candidate
        except Exception:
            # Expired/invalid signatures simply generate a fresh local demo identity.
            actor_id = None

    # Migrate identities created by earlier versions that kept the ID in Flask session.
    if actor_id is None:
        try:
            candidate = int(session.get("student_app_local_tg_id", 0))
            if candidate < 0:
                actor_id = candidate
        except (TypeError, ValueError):
            actor_id = None

    if actor_id is None:
        # Negative IDs cannot collide with real Telegram IDs.
        actor_id = -int(uuid.uuid4().int % 8_000_000_000_000_000_000)

    # Keep backward compatibility for the current session, while ensuring admin
    # session.clear() cannot erase the separately stored demo identity.
    session["student_app_local_tg_id"] = actor_id
    if _valid_local_demo_cookie_id(serializer, cookie_value) != actor_id:
        signed_value = serializer.dumps(actor_id)

        @after_this_request
        def _persist_local_demo_actor(response):
            response.set_cookie(
                _LOCAL_DEMO_ID_COOKIE,
                signed_value,
                max_age=_LOCAL_DEMO_ID_COOKIE_MAX_AGE,
                httponly=True,
                secure=request.is_secure,
                samesite="Lax",
                path="/",
            )
            return response

    return actor_id

def _valid_local_demo_cookie_id(serializer, cookie_value):
    """Validate a signed local-demo cookie without raising into the request path."""
    try:
        value = serializer.loads(cookie_value)
        return value if isinstance(value, int) and value < 0 else None
    except Exception:
        return None

def _validated_external_mini_app():
    """Resolve the external platform identity, never the unverified URL ID."""
    from services.student_app_auth import validate_vk_launch, validate_max_init
    vk = request.headers.get('X-VK-Launch-Params', '')
    mx = request.headers.get('X-Max-Init-Data', '')
    if vk and not mx:
        uid = validate_vk_launch(vk, app_id=settings.VK_MINI_APP_ID,
                                 secret=settings.VK_MINI_APP_SECRET)
        return ('vk', uid) if uid else None
    if mx and not vk:
        uid = validate_max_init(mx, bot_token=settings.MAX_BOT_TOKEN)
        return ('max', uid) if uid else None
    return None


def _student_app_platform():
    if validate_telegram_init_data(request.headers.get('X-Telegram-Init-Data', '')):
        return 'telegram'
    signed = _validated_external_mini_app()
    if signed:
        return signed[0]
    return 'standalone' if settings.LOCAL_DEMO else None


def _resolve_student_identity():
    user = validate_telegram_init_data(request.headers.get("X-Telegram-Init-Data", ""))
    if user:
        return int(user["id"]), False
    external = _validated_external_mini_app()
    if external:
        platform, uid = external
        link = MessengerIdentity.query.filter_by(platform=platform, external_user_id=uid).first()
        if link:
            student = Student.query.get(link.student_id)
            return (int(student.tg_id), False) if student else (None, False)
        from services.student_app_auth import virtual_telegram_id
        # Virtual IDs must never accidentally attach to an existing student.
        synthetic = virtual_telegram_id(platform, uid, settings.SECRET_KEY)
        if Student.query.filter_by(tg_id=synthetic).first():
            return None, False
        return synthetic, False
    local_id = _local_actor_tg_id()
    if local_id is not None:
        return local_id, True
    return None, False

def _sync_student_telegram_profile(student):
    """Refresh username from authenticated Telegram Mini App initData, never from user input."""
    if not student:
        return
    user = validate_telegram_init_data(request.headers.get("X-Telegram-Init-Data", ""))
    try:
        if not user or int(user.get("id", 0)) != int(student.tg_id):
            return
        username = (user.get("username") or "").strip().lstrip("@")[:255] or None
        if student.telegram_username != username:
            student.telegram_username = username
            db.session.commit()
    except Exception:
        db.session.rollback()
        logger.debug("Could not sync username from authenticated Telegram profile", exc_info=True)

def _student_registration_payload(is_local):
    return {
        "ok": True, "registered": False, "needs_registration": True, "local": is_local,
        "mode": _student_app_platform() or "standalone",
        "bot_available": bool(settings.BOT_TOKEN),
        "registration": {"education_types": [
            {"value": EducationType.COLLEGE.value, "label": "Колледж"},
            {"value": EducationType.INSTITUTE.value, "label": "Институт"}
        ]}
    }

def _student_from_init_request(require_registered=True):
    tg_id, is_local = _resolve_student_identity()
    if tg_id is None:
        return None, (jsonify({"ok": False, "error": "Недействительные данные запуска приложения"}), 401)
    student = Student.query.filter_by(tg_id=tg_id).first()
    if student:
        # Store an internal student ID rather than personal names or messenger IDs.
        g.audit_actor_user_id = None
        g.audit_actor_login = f"Студент #{student.id}"
        g.audit_actor_role = 'student_app'
        _sync_student_telegram_profile(student)
        student = Student.query.filter_by(tg_id=tg_id).first()
    if require_registered and (not student or not student.council_registered):
        return None, (jsonify({"ok": False, "error": "Сначала зарегистрируйтесь в студенческом совете", "needs_registration": True}), 403)
    return student, None

def _json_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _student_app_link_owner():
    """Account linking is available only from a signed, authenticated messenger Mini App."""
    actor = _student_app_platform()
    # In LOCAL_DEMO, the stable signed HttpOnly demo cookie is the local profile
    # credential. It is deliberately not accepted outside local/demo mode.
    local_demo_owner = bool(settings.LOCAL_DEMO and actor == "standalone")
    link_allowed = actor in {"telegram", "vk", "max"} or local_demo_owner
    if not link_allowed:
        return None, actor, (jsonify({
            "ok": False,
            "error": "Для безопасной привязки откройте Student App внутри Telegram, VK или MAX.",
            "link_allowed": False,
        }), 403)
    student, error = _student_from_init_request(require_registered=True)
    if error:
        return None, actor, error
    return student, actor, None


@student_app_bp.route("/student-app/api/accounts", methods=["GET"])
def student_app_accounts():
    """Read the authenticated student's linked accounts and pending approval requests."""
    student, actor, error = _student_app_link_owner()
    if error:
        return error
    from services.multi_messenger import linked_account_status, pending_link_requests
    return jsonify({
        "ok": True,
        "link_allowed": True,
        "current_platform": actor,
        "platforms_available": {
            "telegram": bool(settings.BOT_TOKEN),
            "vk": bool(settings.VK_BOT_TOKEN and settings.VK_GROUP_ID),
            "max": bool(settings.MAX_BOT_TOKEN),
        },
        "accounts": linked_account_status(student),
        "pending": pending_link_requests(student),
    })


@student_app_bp.route("/student-app/api/accounts/code", methods=["POST"])
def student_app_account_code():
    """Create a short-lived code; the target bot must present it and the owner approve."""
    student, actor, error = _student_app_link_owner()
    if error:
        return error
    data = _json_body()
    target = str(data.get("platform", "")).strip().lower()
    handle = str(data.get("handle", "")).strip() or None
    if target not in {"telegram", "vk", "max"}:
        return jsonify({"ok": False, "error": "Выберите Telegram, VK или MAX.", "link_allowed": True}), 400
    platform_available = {
        "telegram": bool(settings.BOT_TOKEN),
        "vk": bool(settings.VK_BOT_TOKEN and settings.VK_GROUP_ID),
        "max": bool(settings.MAX_BOT_TOKEN),
    }[target]
    if not platform_available:
        variable = {"telegram": "BOT_TOKEN", "vk": "VK_BOT_TOKEN и VK_GROUP_ID", "max": "MAX_BOT_TOKEN"}[target]
        return jsonify({
            "ok": False,
            "error": f"Бот {target.upper()} сейчас отключён. Настройте {variable} в .env и перезапустите run.py.",
            "link_allowed": True,
        }), 503
    try:
        from services.multi_messenger import generate_link_code
        code = generate_link_code(student, target, handle)
    except ValueError as exc:
        message = str(exc)
        conflict = any(word in message.lower() for word in ("уже подключ", "уже привязан", "уже связан"))
        return jsonify({"ok": False, "error": message, "link_allowed": True}), (409 if conflict else 400)
    return jsonify({
        "ok": True,
        "link_allowed": True,
        "current_platform": actor,
        "platform": target,
        "code": code,
        "expires_in_seconds": 600,
        "message": "Код создан на 10 минут. Откройте личный чат бота выбранной платформы и отправьте /link КОД. После этого подтвердите запрос здесь.",
    })


@student_app_bp.route("/student-app/api/accounts/<int:request_id>/review", methods=["POST"])
def student_app_review_link_request(request_id):
    """Approve/reject a pending identity claim from the authenticated profile owner."""
    student, actor, error = _student_app_link_owner()
    if error:
        return error
    data = _json_body()
    approve = data.get("approve")
    if not isinstance(approve, bool):
        return jsonify({"ok": False, "error": "Не удалось определить решение по запросу.", "link_allowed": True}), 400
    try:
        from services.multi_messenger import review_link_request, linked_account_status, pending_link_requests
        message = review_link_request(student, request_id, approve)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc), "link_allowed": True}), 409
    return jsonify({
        "ok": True, "message": message, "link_allowed": True,
        "current_platform": actor,
        "accounts": linked_account_status(student),
        "pending": pending_link_requests(student),
    })


@student_app_bp.route("/student-app/api/accounts/<platform>", methods=["DELETE"])
def student_app_unlink_account(platform):
    """Unlink VK/MAX only; preserve the profile, applications and direction memberships."""
    student, actor, error = _student_app_link_owner()
    if error:
        return error
    try:
        from services.multi_messenger import unlink_account, linked_account_status, pending_link_requests
        message = unlink_account(student, str(platform).strip().lower(), current_platform=actor)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc), "link_allowed": True}), 409
    return jsonify({
        "ok": True, "message": message, "link_allowed": True,
        "current_platform": actor,
        "accounts": linked_account_status(student),
        "pending": pending_link_requests(student),
    })


@student_app_bp.route("/student-app/api/register", methods=["POST"])
def student_app_register():
    tg_id, is_local = _resolve_student_identity()
    if tg_id is None:
        return jsonify({"ok": False, "error": "Недействительные данные запуска приложения"}), 401
    existing = Student.query.filter_by(tg_id=tg_id).first()
    if existing and existing.council_registered:
        g.audit_actor_user_id = None
        g.audit_actor_login = f"Студент #{existing.id}"
        g.audit_actor_role = 'student_app'
        return jsonify({
            "ok": True, "registered": True, "already_registered": True,
            "message": "Профиль уже зарегистрирован. Открываем ваш кабинет.",
        }), 200
    data = _json_body()
    education_type = str(data.get("education_type", "")).strip().lower()
    full_name = str(data.get("full_name", "")).strip()
    group = str(data.get("group", "")).strip()
    phone = str(data.get("phone", "")).strip()
    if education_type not in {EducationType.COLLEGE.value, EducationType.INSTITUTE.value}:
        return jsonify({"ok": False, "error": "Выберите учебный контур"}), 400
    if len(full_name) > 255:
        return jsonify({"ok": False, "error": "ФИО не должно превышать 255 символов"}), 400
    if len(group) > 50:
        return jsonify({"ok": False, "error": "Учебная группа не должна превышать 50 символов"}), 400
    if len(phone) > 30:
        return jsonify({"ok": False, "error": "Телефон не должен превышать 30 символов"}), 400
    if len(full_name.split()) < 2:
        return jsonify({"ok": False, "error": "Укажите минимум имя и фамилию"}), 400
    if len(group) < 2:
        return jsonify({"ok": False, "error": "Укажите учебную группу"}), 400
    if sum(ch.isdigit() for ch in phone) < 5:
        return jsonify({"ok": False, "error": "В номере должно быть не меньше 5 цифр"}), 400
    try:
        from services.applications import register_student_with_council
        telegram_user = validate_telegram_init_data(request.headers.get("X-Telegram-Init-Data", "")) or {}
        telegram_username = (telegram_user.get("username") or "").strip().lstrip("@") or None
        student, council, error_message = register_student_with_council(
            tg_id=tg_id, full_name=full_name, group=group, phone=phone,
            education_type=education_type, telegram_username=telegram_username, source="student_app"
        )
    except Exception:
        logger.exception("Mini App registration failed")
        return jsonify({"ok": False, "error": "Не удалось завершить регистрацию. Изменения отменены."}), 500
    if error_message:
        return jsonify({"ok": False, "error": error_message}), 409
    # New registration must be traceable to the new internal account, never a
    # Telegram/VK/MAX identifier or an administrator sharing this browser.
    if student:
        g.audit_actor_user_id = None
        g.audit_actor_login = f"Студент #{student.id}"
        g.audit_actor_role = 'student_app'
    signed = _validated_external_mini_app()
    if signed and student and not existing:
        platform, external_id = signed
        try:
            db.session.add(MessengerIdentity(platform=platform, external_user_id=external_id, student_id=student.id))
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            logger.error('Messenger identity already exists for newly registered student')
            return jsonify({"ok": False, "error": "Аккаунт уже зарегистрирован. Обратитесь к администратору."}), 409
    return jsonify({"ok": True, "registered": True, "message": "Профиль создан. Выберите любое доступное направление для подачи заявления."})


@student_app_bp.route("/student-app/api/profile", methods=["PATCH"])
def student_app_profile_update():
    student, error = _student_from_init_request()
    if error:
        return error
    data = _json_body()
    new_group = str(data.get("group", student.group or "")).strip()[:50] or None
    new_phone = str(data.get("phone", student.phone or "")).strip()[:30] or None
    from services.student_validation import normalize_phone, student_duplicate_message
    if normalize_phone(new_phone) != normalize_phone(student.phone):
        duplicate_error = student_duplicate_message(
            student.full_name, new_phone, exclude_id=student.id, check_name=False, check_phone=True
        )
        if duplicate_error:
            return jsonify({"ok": False, "error": duplicate_error}), 409
    student.group = new_group
    student.phone = new_phone
    db.session.commit()
    return jsonify({"ok": True, "message": "Профиль обновлён"})

@student_app_bp.route("/student-app/api/applications", methods=["POST"])
def student_app_apply():
    student, error = _student_from_init_request()
    if error:
        return error
    try:
        direction_id = int((_json_body().get("direction_id") or 0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Некорректный ID направления"}), 400
    body = _json_body()
    direction = Direction.query.get(direction_id)
    if not direction or not direction.available_for(student.education_type):
        return jsonify({"ok": False, "error": "Направление недоступно"}), 400
    from services.applications import submit_application
    submitted, message = submit_application(student, direction, source="student_app", answers=body.get("answers") or {})
    if not submitted:
        return jsonify({"ok": False, "error": message}), 409
    return jsonify({"ok": True, "message": message})

@student_app_bp.route("/student-app/api/applications/<int:direction_id>", methods=["DELETE"])
def student_app_remove_application(direction_id):
    student, error = _student_from_init_request()
    if error:
        return error
    link = db.session.execute(student_directions.select().where(
        (student_directions.c.student_id == student.id) & (student_directions.c.direction_id == direction_id)
    )).fetchone()
    if not link:
        return jsonify({"ok": False, "error": "Заявка не найдена"}), 404
    from services.chair_membership import direction_required_by_current_role
    if direction_required_by_current_role(student.id, direction_id):
        return jsonify({"ok": False, "error": "Это членство необходимо для вашей текущей руководящей должности. После снятия должности доступ пересчитается автоматически."}), 400
    direction = Direction.query.get(direction_id)
    db.session.execute(student_directions.delete().where(
        (student_directions.c.student_id == student.id) & (student_directions.c.direction_id == direction_id)
    ))
    record_activity('application_withdrawn', f'Участник самостоятельно покинул направление «{direction.name if direction else direction_id}».', student_id=student.id, direction_id=direction_id)
    db.session.commit()
    # Remove the student from the withdrawn direction's chats and revoke its
    # cached invite links; other chosen directions/shared chats are kept.
    removed_count = 0
    if direction:
        try:
            from services.telegram import remove_student_from_direction_chats
            removed_count = remove_student_from_direction_chats(student, direction)
        except Exception:
            logger.exception("Could not remove student from chats after withdrawing direction")
    message = "Вы покинули направление. Ссылки на его чаты отозваны."
    if removed_count:
        message += f" Удалено из чатов: {removed_count}."
    return jsonify({"ok": True, "message": message, "removed_from_chats": removed_count})

@student_app_bp.route("/student-app/api/events/<int:quota_id>/days/<int:day_id>", methods=["POST"])
def student_app_join_event(quota_id, day_id):
    student, error = _student_from_init_request()
    if error:
        return error
    quota = EventQuota.query.get(quota_id)
    day = EventDay.query.get(day_id)
    if not quota or not day or day.quota_id != quota.id or quota.is_closed:
        return jsonify({"ok": False, "error": "Дата мероприятия недоступна"}), 404
    active_ids = {r.direction_id for r in db.session.execute(student_directions.select().where(
        (student_directions.c.student_id == student.id) & (student_directions.c.status == DirectionStatus.ACTIVE.value)
    )).fetchall()}
    if not any(d.id in active_ids for d in quota.directions):
        return jsonify({"ok": False, "error": "Сначала нужно быть активным участником направления мероприятия"}), 403
    if EventQuotaDecline.query.filter_by(quota_id=quota.id, student_id=student.id).first():
        return jsonify({"ok": False, "error": "Сначала нажмите «Вернуться к мероприятию», чтобы удалить отказ."}), 409
    if day.date.date() < datetime.utcnow().date():
        return jsonify({"ok": False, "error": "Эта дата уже прошла"}), 400
    existing = DayParticipation.query.filter_by(student_id=student.id, day_id=day.id).first()
    if existing and existing.status != "cancelled":
        return jsonify({"ok": False, "error": "Вы уже записаны на эту дату"}), 409
    if day.available_places() <= 0:
        return jsonify({"ok": False, "error": "Свободных мест больше нет"}), 409
    if existing:
        existing.status = "registered"
    else:
        db.session.add(DayParticipation(student_id=student.id, day_id=day.id, status="registered"))
    record_activity('event_registered', f'Оформлена запись на «{quota.event_title}» ({day.date.strftime("%d.%m.%Y")}).', student_id=student.id, quota_id=quota.id)
    db.session.commit()
    try:
        from services.activity_chats import queue_student_invite
        queue_student_invite('event', quota_id, student)
    except Exception:
        logger.exception('Не удалось поставить приглашение в чат мероприятия в очередь')
    return jsonify({"ok": True, "message": "Регистрация на мероприятие подтверждена"})

@student_app_bp.route("/student-app/api/events/<int:quota_id>/days/<int:day_id>", methods=["DELETE"])
def student_app_leave_event(quota_id, day_id):
    student, error = _student_from_init_request()
    if error:
        return error
    day = EventDay.query.get(day_id)
    if not day or day.quota_id != quota_id:
        return jsonify({"ok": False, "error": "Запись не найдена"}), 404
    participation = DayParticipation.query.filter_by(student_id=student.id, day_id=day.id).first()
    if not participation or participation.status == "cancelled":
        return jsonify({"ok": False, "error": "Вы не записаны на эту дату"}), 404
    participation.status = "cancelled"
    record_activity('event_unregistered', f'Отменена запись на мероприятие #{quota_id} ({day.date.strftime("%d.%m.%Y")}).', student_id=student.id, quota_id=quota_id)
    db.session.commit()
    return jsonify({"ok": True, "message": "Регистрация на мероприятие отменена"})

@student_app_bp.route("/student-app/api/events/<int:quota_id>/decline", methods=["POST"])
def student_app_decline_event(quota_id):
    student, error = _student_from_init_request()
    if error:
        return error
    quota = EventQuota.query.get(quota_id)
    if not quota or quota.is_closed:
        return jsonify({"ok": False, "error": "Мероприятие недоступно."}), 404
    active_ids = {r.direction_id for r in db.session.execute(student_directions.select().where(
        (student_directions.c.student_id == student.id) &
        (student_directions.c.status == DirectionStatus.ACTIVE.value)
    )).fetchall()}
    if not any(d.id in active_ids for d in quota.directions):
        return jsonify({"ok": False, "error": "Мероприятие недоступно для выбранного профиля."}), 403
    registered_participation = None
    for day in quota.days:
        participation = DayParticipation.query.filter_by(student_id=student.id, day_id=day.id).first()
        if participation and participation.status == "registered":
            registered_participation = participation
            break
    if not registered_participation:
        return jsonify({"ok": False, "error": "Отказаться можно только от мероприятия, на которое вы уже записались."}), 409

    reason = str((_json_body().get("reason") or "")).strip()
    if len(reason) < 5:
        return jsonify({"ok": False, "error": "Укажите причину отказа (не менее пяти символов)."}), 400
    if len(reason) > 2000:
        return jsonify({"ok": False, "error": "Причина не должна превышать 2 000 символов."}), 400
    try:
        decline = EventQuotaDecline.query.filter_by(quota_id=quota.id, student_id=student.id).first()
        if decline:
            decline.reason = reason
            decline.created_at = datetime.utcnow()
        else:
            db.session.add(EventQuotaDecline(quota_id=quota.id, student_id=student.id, reason=reason))
        for day in quota.days:
            participation = DayParticipation.query.filter_by(student_id=student.id, day_id=day.id).first()
            if participation and participation.status == "registered":
                participation.status = "cancelled"
        record_activity("quota_declined", f'Отказ от мероприятия «{quota.event_title}». Причина: {reason}', student_id=student.id, quota_id=quota.id)
        db.session.commit()
        return jsonify({"ok": True, "message": "Отказ зарегистрирован. Причина сохранена в системе."})
    except Exception:
        db.session.rollback()
        logger.exception("Не удалось сохранить отказ студента от мероприятия")
        return jsonify({"ok": False, "error": "Не удалось сохранить отказ. Повторите попытку позднее."}), 500

@student_app_bp.route("/student-app/api/events/<int:quota_id>/return", methods=["POST"])
def student_app_return_to_event(quota_id):
    student, error = _student_from_init_request()
    if error:
        return error
    quota = EventQuota.query.get(quota_id)
    if not quota or quota.is_closed:
        return jsonify({"ok": False, "error": "Мероприятие больше недоступно."}), 404
    active_ids = {r.direction_id for r in db.session.execute(student_directions.select().where(
        (student_directions.c.student_id == student.id) &
        (student_directions.c.status == DirectionStatus.ACTIVE.value)
    )).fetchall()}
    if not any(direction.id in active_ids for direction in quota.directions):
        return jsonify({"ok": False, "error": "Мероприятие недоступно для выбранного профиля."}), 403

    decline = EventQuotaDecline.query.filter_by(quota_id=quota.id, student_id=student.id).first()
    if not decline:
        return jsonify({"ok": False, "error": "Активный отказ уже отсутствует."}), 409
    try:
        db.session.delete(decline)
        record_activity(
            "quota_decline_reversed",
            f'Студент вернулся к мероприятию «{quota.event_title}»; отказ удалён.',
            student_id=student.id,
            quota_id=quota.id,
        )
        db.session.commit()
        return jsonify({"ok": True, "message": "Отказ удалён. Теперь можно снова записаться на нужную дату мероприятия."})
    except Exception:
        db.session.rollback()
        logger.exception("Не удалось удалить отказ от мероприятия")
        return jsonify({"ok": False, "error": "Не удалось восстановить участие. Повторите попытку позднее."}), 500

@student_app_bp.route("/student-app/api/leadership", methods=["GET"])
def student_app_leadership():
    student, error = _student_from_init_request()
    if error:
        return error
    from services.permissions import allowed_direction_ids, leadership_payload
    leads = StudentLeadership.query.filter_by(student_id=student.id).all()
    if not leads:
        return jsonify({"ok": True, "authorized": False, "applications": []})
    direction_ids = allowed_direction_ids(student.id)
    if not direction_ids:
        return jsonify({"ok": True, "authorized": False, "applications": []})
    rows = db.session.execute(student_directions.select().where(
        (student_directions.c.direction_id.in_(direction_ids)) &
        (student_directions.c.status.in_([DirectionStatus.PENDING.value, DirectionStatus.INTERVIEW.value]))
    )).fetchall()
    result = []
    for row in rows:
        candidate = Student.query.get(row.student_id)
        direction = Direction.query.get(row.direction_id)
        if candidate and direction:
            from services.permissions import can_manage_direction
            if not can_manage_direction(student.tg_id, direction.id, candidate.education_type):
                continue
            try:
                extra = json.loads(row.extra_data or "{}")
            except (TypeError, ValueError):
                extra = {}
            answers = extra.get("answers") or []
            result.append({"student_id": candidate.id, "direction_id": direction.id, "direction": direction.name,
                           "full_name": candidate.full_name, "group": candidate.group, "education_type": candidate.education_type,
                           "status": row.status, "answers": answers})
    return jsonify({"ok": True, "authorized": True, "applications": result})

@student_app_bp.route("/student-app/api/leadership-directory", methods=["GET"])
def student_app_leadership_directory():
    """Read-only cards for the current student leadership roster."""
    student, error = _student_from_init_request()
    if error:
        return error
    # Telegram, VK, MAX, Student App and staff panel use one validated roster.
    from services.leadership_directory import leadership_cards
    return jsonify({"ok": True, "cards": leadership_cards()})


@student_app_bp.route("/student-app/api/leadership/<int:student_id>/<int:direction_id>", methods=["POST"])
def student_app_leadership_decision(student_id, direction_id):
    actor, error = _student_from_init_request()
    if error:
        return error
    from services.permissions import can_manage_direction
    candidate = Student.query.get(student_id)
    direction = Direction.query.get(direction_id)
    if not candidate or not direction or not can_manage_direction(actor.tg_id, direction_id, candidate.education_type):
        return jsonify({"ok": False, "error": "Нет прав руководителя для этого направления и учебного контура"}), 403
    action = str(_json_body().get("action") or "").strip().lower()
    from services.applications import set_application_status
    target_status = DirectionStatus.ACTIVE.value if action == "approve" else DirectionStatus.REJECTED.value if action == "reject" else None
    if not target_status:
        return jsonify({"ok": False, "error": "Неизвестное действие"}), 400
    reason = _json_body().get("reason") if target_status == DirectionStatus.REJECTED.value else None
    ok, message, invite_count = set_application_status(
        student_id, direction_id, target_status, actor_tg_id=actor.tg_id,
        reason=reason, source="student_app",
    )
    return jsonify({"ok": ok, "message": message, "invite_count": invite_count}), (200 if ok else 400)

# Operational journal routes share the existing super-admin gate.
from services.bot_journal_routes import register_journal_routes
register_journal_routes(admin_bp, super_admin_required)

def create_app():
    if not settings.LOCAL_DEMO and settings.ADMIN_PASSWORD.lower() in {'admin123', 'password', '12345678', 'changeme'}:
        raise RuntimeError('Небезопасный ADMIN_PASSWORD. Установите уникальный сложный пароль.')
    if not settings.LOCAL_DEMO and not settings.SECRET_KEY_CONFIGURED:
        raise RuntimeError("Рабочий запуск требует SECRET_KEY длиной не менее 32 символов в .env. Для тестирования используйте отдельную локальную конфигурацию.")
    if not settings.LOCAL_DEMO and settings.DEBUG:
        raise RuntimeError("DEBUG нельзя включать в рабочем режиме. Установите DEBUG=0 в .env.")
    if settings.LOCAL_DEMO and settings.WEB_HOST not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("LOCAL_DEMO=1 разрешён только на localhost. Для внутреннего сервера установите LOCAL_DEMO=0.")
    project_root = Path(__file__).resolve().parents[2]
    app = Flask(
        __name__,
        template_folder=str(project_root / "frontend" / "templates"),
        static_folder=str(project_root / "static"),
    )
    app.extensions["portal_runtime_started_epoch"] = time.time()
    app.extensions["portal_runtime_started_monotonic"] = time.monotonic()
    app.extensions["portal_runtime_started_at_utc"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    from services.operational_logging import configure_operational_logging
    configure_operational_logging(settings.DATA_DIR)

    # Content-fingerprinted asset URLs: rebuilding CSS/JS changes the URL even
    # when deployment tooling preserves a file's mtime. Flask can cache the
    # fingerprint by (path, mtime_ns, size); browsers/WebViews cache by URL.
    import hashlib
    from functools import lru_cache

    @lru_cache(maxsize=256)
    def _asset_digest(filename, modified, size):
        path = os.path.join(app.static_folder or "static", filename)
        h = hashlib.sha256()
        with open(path, "rb") as source:
            for chunk in iter(lambda: source.read(131072), b""):
                h.update(chunk)
        return h.hexdigest()[:16]

    def asset_version(filename):
        try:
            path = os.path.join(app.static_folder or "static", filename)
            st = os.stat(path)
            return _asset_digest(filename, st.st_mtime_ns, st.st_size)
        except OSError:
            return "1"

    app.jinja_env.globals["asset_version"] = asset_version

    # All template references include a file-version query parameter. Let the
    # browser cache these static files aggressively; when a file changes its URL
    # changes too. Dynamic pages and personal API responses remain no-store below.
    def serve_versioned_static(filename):
        # Only URLs explicitly fingerprinted by our templates get the year-long
        # immutable policy. Relative CSS assets without ?v= are cached for one hour.
        versioned = bool(request.args.get("v"))
        max_age = 31536000 if versioned else 3600
        response = send_from_directory(
            app.static_folder, filename, conditional=True, etag=True, max_age=max_age
        )
        response.headers["Cache-Control"] = (
            "public, max-age=31536000, immutable" if versioned
            else "public, max-age=3600"
        )
        return response

    # Replace only the standard static endpoint view; keep Flask's route and URL helper.
    app.view_functions["static"] = serve_versioned_static

    @app.get("/favicon.ico")
    def favicon():
        # Some browsers request this conventional root URL even when a <link rel=icon>
        # points to /static/favicon.ico. Serve the same local asset for both paths.
        return send_from_directory(
            app.static_folder, "favicon.ico", mimetype="image/vnd.microsoft.icon", max_age=86400
        )

    # The local test application has a web thread plus an optional bot thread.
    # Give SQLite a bounded lock wait; WAL lets readers proceed while a writer is
    # committing. Each bind remains a separate local SQLite file as before.
    sqlite_engine_options = {"connect_args": {"timeout": 15}}
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = sqlite_engine_options
    app.config["SQLALCHEMY_DATABASE_URI"] = settings.PEOPLE_DATABASE_URI
    app.config["SQLALCHEMY_BINDS"] = {
        "events": {"url": settings.EVENTS_DATABASE_URI, **sqlite_engine_options},
        "lessons": {"url": settings.LESSONS_DATABASE_URI, **sqlite_engine_options},
        "stats": {"url": settings.STATS_DATABASE_URI, **sqlite_engine_options},
        "system": {"url": settings.SYSTEM_DATABASE_URI, **sqlite_engine_options},
    }
    app.config["SECRET_KEY"] = settings.SECRET_KEY
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = settings.SESSION_COOKIE_SECURE
    app.config["SESSION_COOKIE_NAME"] = "__Host-student-council-session" if settings.SESSION_COOKIE_SECURE else "student-council-session"
    app.config["SESSION_COOKIE_PATH"] = "/"
    app.config["SESSION_COOKIE_DOMAIN"] = None
    app.config["SESSION_REFRESH_EACH_REQUEST"] = False
    app.config["MAX_CONTENT_LENGTH"] = 9 * 1024 * 1024  # Up to 8 MB private PDF/DOCX orders
    app.config["MAX_FORM_MEMORY_SIZE"] = 512 * 1024
    app.config["MAX_FORM_PARTS"] = 1000
    # Host allowlisting is checked per external endpoint below. Do not configure
    # Flask's global TRUSTED_HOSTS: that would also reject valid private aliases
    # used to access the internal admin panel.

    @app.get("/healthz")
    def healthz():
        """Liveness endpoint for local diagnostics and process supervisors."""
        return jsonify({"status": "ok", "service": "student-council-portal"}), 200

    @app.get("/readyz")
    def readyz():
        """Check that every configured SQLite bind can answer a simple query."""
        dependency_status = {}
        ready = True
        for bind_key, engine in db.engines.items():
            name = str(bind_key or "people")
            try:
                with engine.connect() as connection:
                    connection.execute(sql_text("SELECT 1"))
                dependency_status[name] = "ok"
            except Exception:
                ready = False
                dependency_status[name] = "unavailable"
                logger.exception("Database readiness check failed for bind=%s", name)
        return jsonify({"status": "ready" if ready else "not_ready", "dependencies": dependency_status}), (200 if ready else 503)

    @app.errorhandler(403)
    def handle_forbidden(error):
        return _render_http_error(403, "Доступ ограничен", "У вашей учётной записи нет прав для выполнения этого действия.", error)

    @app.errorhandler(404)
    def handle_not_found(error):
        return _render_http_error(404, "Страница не найдена", "Возможно, ссылка устарела или страница была перемещена.", error)

    @app.errorhandler(405)
    def handle_method_not_allowed(error):
        return _render_http_error(405, "Действие недоступно", "Эта страница не поддерживает указанный тип запроса.", error)

    @app.errorhandler(413)
    def handle_payload_too_large(error):
        return _render_http_error(413, "Слишком большой запрос", "Размер отправленных данных превышает допустимый лимит.", error)

    @app.errorhandler(500)
    def handle_internal_error(error):
        try:
            db.session.rollback()
        except Exception:
            pass
        # Flask wraps the real exception in InternalServerError: record its
        # original traceback with the same support code shown to the user.
        cause = getattr(error, 'original_exception', None) or error
        logger.error("Unhandled web error request_id=%s endpoint=%s path=%s",
                     getattr(g, "request_id", "unknown"), request.endpoint, request.path,
                     exc_info=(type(cause), cause, getattr(cause, "__traceback__", None)))
        return _render_http_error(500, "Внутренняя ошибка", "Не удалось выполнить запрос. Повторите попытку; если проблема повторяется, сообщите администратору код обращения.", error)

    def _render_http_error(code, title, description, error=None):
        if request.path.startswith("/student-app/api/") or request.is_json:
            message = getattr(error, "description", None) or title
            return jsonify({"ok": False, "error": message, "request_id": getattr(g, "request_id", None)}), code
        return render_template(
            "shared/http_error.html", code=code, title=title, description=description,
            request_id=getattr(g, "request_id", None),
        ), code

    @app.post('/hooks/max')
    def max_incoming_webhook():
        # MAX has a separate high-entropy secret, NOT a user's browser CSRF token.
        if (settings.MAX_MODE != 'webhook' or len(settings.WEBHOOK_SECRET) < 24
                or not settings.MAX_BOT_TOKEN):
            abort(503)
        supplied = request.headers.get('X-Max-Bot-Api-Secret', '')
        if not hmac.compare_digest(supplied, settings.WEBHOOK_SECRET):
            abort(403)
        if (not request.is_json or (request.content_length is not None and request.content_length > 128 * 1024)
                or len(request.get_data(cache=True)) > 128 * 1024):
            abort(400)
        update = request.get_json(silent=True)
        if not isinstance(update, dict):
            abort(400)
        from services.messenger_transports import handle_max_event
        handle_max_event(update, app)
        return jsonify({'ok': True})

    @app.before_request
    def enforce_internal_request_rules():
        path = request.path
        started_at = time.perf_counter()
        supplied_request_id = str(request.headers.get("X-Request-ID", "")).strip()
        if (1 <= len(supplied_request_id) <= 64 and
                all(char.isascii() and (char.isalnum() or char in "-_.") for char in supplied_request_id)):
            g.request_id = supplied_request_id
        else:
            g.request_id = uuid.uuid4().hex
        g.request_started_at = started_at
        g.audit_actor_user_id = session.get("user_id")
        g.audit_actor_login = session.get("user_login")
        g.audit_actor_role = session.get("user_role")

        if request.path == "/auth/login" and request.method == "POST":
            g.audit_attempted_login = str(request.form.get("username", "")).strip()[:255] or None

        # New employee accounts are deny-by-default outside their scoped workspace.
        if session.get('user_id'):
            actor = User.query.get(session['user_id'])
            if not actor or not actor.is_active or actor.role not in {r.value for r in UserRole} or session.get('auth_version') != (actor.auth_version or 0):
                # Do not attribute an expired/revoked session to a registered actor.
                g.audit_actor_user_id = None
                g.audit_actor_login = None
                g.audit_actor_role = None
                session.clear()
                return redirect(url_for('auth.login'))
            # Resolve the actor from the live account row, not stale cookie labels.
            g.audit_actor_user_id = actor.id
            g.audit_actor_login = actor.email
            g.audit_actor_role = actor.role
            if actor.must_change_password and not (
                path == '/auth/change-password' or path == '/auth/logout' or
                path.startswith('/static/') or path == '/favicon.ico'
            ):
                return redirect(url_for('auth.change_password'))
            if actor.role == UserRole.STAFF.value:
                # Explicit endpoint/method allow-list for the employee workspace.
                # Module handlers still enforce direction ownership and object-level
                # permissions (event/lesson/notification/order/chat/report scope).
                # Never use broad URL prefixes here: they would expose unrelated
                # admin endpoints that happen to share a blueprint prefix.
                staff_endpoint_methods = {
                    # Employee home and people directories.
                    'admin.dashboard': {'GET', 'HEAD', 'OPTIONS'},
                    'staff.workspace': {'GET', 'HEAD', 'OPTIONS'},
                    'staff.students': {'GET', 'HEAD', 'OPTIONS'},
                    # Internal staff messenger is a dedicated workspace. These
                    # endpoints are admitted here, while the messenger service
                    # enforces participant, role, observer, and message-level ACLs.
                    'staff_messenger.communications': {'GET', 'HEAD', 'OPTIONS'},
                    'staff_messenger.index': {'GET', 'HEAD', 'OPTIONS'},
                    'staff_messenger.notification_feed': {'GET', 'HEAD', 'OPTIONS'},
                    'staff_messenger.push_public_key': {'GET', 'HEAD', 'OPTIONS'},
                    'staff_messenger.save_push_subscription': {'POST'},
                    'staff_messenger.create_conversation': {'POST'},
                    'staff_messenger.poll_messages': {'GET', 'HEAD', 'OPTIONS'},
                    'staff_messenger.mark_read': {'POST'},
                    'staff_messenger.update_typing': {'POST'},
                    'staff_messenger.send_message': {'POST'},
                    'staff_messenger.delete_message': {'POST'},
                    'staff_messenger.toggle_reaction': {'POST'},
                    'staff_messenger.search_messages': {'GET', 'HEAD', 'OPTIONS'},
                    'staff_messenger.download_attachment': {'GET', 'HEAD', 'OPTIONS'},
                    # Workspace forms: every handler performs its own section,
                    # assigned-direction, and object-level grant checks.
                    'staff.application_decision': {'POST'},
                    'staff.create_lesson': {'POST'},
                    'staff.create_event': {'POST'},
                    'staff.close_event': {'POST'},
                    'staff.delete_event': {'POST'},
                    'staff.delete_lesson': {'POST'},
                    'staff.update_student_profile': {'POST'},
                    'admin.student_detail': {'GET', 'HEAD', 'OPTIONS'},
                    'admin.blocked_students': {'GET', 'HEAD', 'OPTIONS'},
                    'admin.leadership_public': {'GET', 'HEAD', 'OPTIONS'},
                    'admin.visual_theme_state': {'GET', 'HEAD', 'OPTIONS'},
                    # Personal notification inbox + direction-only announcements.
                    'admin.notifications': {'GET', 'HEAD', 'OPTIONS'},
                    'admin.notifications_unread': {'GET', 'HEAD', 'OPTIONS'},
                    'admin.notification_read': {'POST'},
                    'admin.notifications_read_all': {'POST'},
                    'admin.notifications_publish': {'POST'},
                    'directions.chat_message': {'GET', 'POST'},
                    # Direction-scoped calendar, events and lessons.
                    'admin.calendar': {'GET', 'HEAD', 'OPTIONS'},
                    'quotas.quotas_list': {'GET', 'HEAD', 'OPTIONS'},
                    'quotas.create_quota': {'GET', 'POST'},
                    'quotas.quota_participants': {'GET', 'HEAD', 'OPTIONS'},
                    'quotas.close_quota': {'POST'},
                    'quotas.publish_quota': {'POST'},
                    'quotas.mark_attendance': {'POST'},
                    'lessons.list_lessons': {'GET', 'HEAD', 'OPTIONS'},
                    'lessons.create_lesson': {'GET', 'POST'},
                    'lessons.edit_lesson': {'GET', 'POST'},
                    'lessons.publish_lesson': {'POST'},
                    'lessons.delete_lesson': {'POST'},
                    # Reports: only reports belonging to the employee's direction
                    # or the employee's own work journal are exposed by the handlers.
                    'admin.report_archive': {'GET', 'HEAD', 'OPTIONS'},
                    'admin.report_archive_download': {'GET', 'HEAD', 'OPTIONS'},
                    # Orders: route-level may_upload/may_view_order checks bind every
                    # document and action to a completed event in the assigned direction.
                    'orders.archive': {'GET', 'HEAD', 'OPTIONS'},
                    'orders.download_order': {'GET', 'HEAD', 'OPTIONS'},
                    # Direction chat administration is scoped by the blueprint guard
                    # and by each handler's explicit chats:manage check.
                    'activity_chats.index': {'GET', 'HEAD', 'OPTIONS'},
                    'directions.directions_list': {'GET', 'HEAD', 'OPTIONS'},
                    'directions.direction_detail': {'GET', 'HEAD', 'OPTIONS'},
                    'directions.connect_chat_candidate': {'POST'},
                    'directions.connect_social_chat': {'POST'},
                    'directions.remove_social_chat': {'POST'},
                    'directions.add_chat': {'POST'},
                    'directions.chat_audience': {'POST'},
                    'directions.delete_chat': {'POST'},
                    'directions.test_chat': {'POST'},
                    # Analytics are read-only and their view functions scope results
                    # to the employee's single assigned direction.
                    'stats.overview_statistics': {'GET', 'HEAD', 'OPTIONS'},
                    'stats.directions_statistics': {'GET', 'HEAD', 'OPTIONS'},
                    'stats.attendance_statistics': {'GET', 'HEAD', 'OPTIONS'},
                    'stats.events_statistics': {'GET', 'HEAD', 'OPTIONS'},
                    'stats.declines_statistics': {'GET', 'HEAD', 'OPTIONS'},
                    'stats.direction_statistics': {'GET', 'HEAD', 'OPTIONS'},
                    'stats.students_summary': {'GET', 'HEAD', 'OPTIONS'},
                    'stats.students_quota_stats': {'GET', 'HEAD', 'OPTIONS', 'POST'},
                    'admin.most_active_students': {'GET', 'HEAD', 'OPTIONS'},
                }
                staff_account_paths = {'/auth/change-password', '/auth/logout', '/favicon.ico'}
                is_staff_static = path.startswith('/static/')
                endpoint = request.endpoint or ''
                is_staff_module_action = request.method in staff_endpoint_methods.get(endpoint, set())
                is_staff_account_action = path in staff_account_paths
                if not (is_staff_module_action or is_staff_account_action or is_staff_static):
                    abort(403)

        # Apply external-facing host checks only to Student App/webhook endpoints;
        # legitimate internal hostnames for the admin panel are not blocked here.
        external_endpoint = (
            path == '/student-app' or path.startswith('/student-app/api/') or
            path == '/hooks/max'
        )
        if external_endpoint and settings.APP_TRUSTED_HOSTS:
            try:
                request_hostname = urllib.parse.urlsplit('//' + request.host).hostname
            except ValueError:
                request_hostname = None
            allowed_hosts = {host.strip().lower() for host in settings.APP_TRUSTED_HOSTS if host.strip()}
            if not request_hostname or request_hostname.lower() not in allowed_hosts:
                abort(400)

        # In local-demo mode, synthetic Student App identities and webhook hooks
        # must not be reachable through a LAN/public host. Internal panel routes
        # remain unaffected by this demo-only restriction.
        if settings.LOCAL_DEMO and external_endpoint:
            try:
                request_hostname = urllib.parse.urlsplit('//' + request.host).hostname
            except ValueError:
                request_hostname = None
            if (request_hostname or '').lower() not in {'localhost', '127.0.0.1', '::1'}:
                abort(403)

        # The site is intended for the institute's internal network/VPN. Network reachability
        # is controlled by the host firewall/VPN, not by a brittle public-IP allowlist.
        # Keep session-backed write requests protected against cross-site request forgery.
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and (
                path.startswith('/student-app/api/')):
            # Signed Mini App requests are authenticated by platform headers.
            # Validate Origin, falling back to Referer for embedded WebViews that omit Origin.
            origin = request.headers.get('Origin', '').strip()
            referer = request.headers.get('Referer', '').strip()
            source = origin or (referer.split('/', 3)[0] + '//' + referer.split('/', 3)[2] if referer.startswith(('http://', 'https://')) and len(referer.split('/', 3)) > 2 else '')
            expected_source = request.host_url.rstrip('/')
            if source and source.rstrip('/') != expected_source:
                return jsonify({'ok': False, 'error': 'Недопустимый источник запроса.'}), 403
            if not source and not (request.headers.get('X-Telegram-Init-Data') or request.headers.get('X-VK-Launch-Params') or request.headers.get('X-Max-Init-Data')):
                return jsonify({'ok': False, 'error': 'Не удалось проверить источник запроса.'}), 403
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and not (
                path.startswith('/student-app/api/')) and path != "/hooks/max":
            expected = session.get("_csrf_token", "")
            supplied = request.form.get("csrf_token", "") or request.headers.get("X-CSRF-Token", "")
            if not expected or not supplied or not hmac.compare_digest(str(expected), str(supplied)):
                # A stale password form can remain open in another browser tab.
                # Return the standalone form with a fresh token instead of raw JSON,
                # which otherwise looks like a dead modal or a non-working button.
                if path == "/auth/change-password":
                    # Password rotation is a full-page security flow, never an AJAX/modal
                    # fragment. A stale tab can carry an obsolete CSRF token; redirect the
                    # top-level browsing context to a fresh GET so the user gets a new form.
                    actor = User.query.get(session.get("user_id")) if session.get("user_id") else None
                    logger.warning("password_change_csrf_rejected user_id=%s session_present=%s",
                                   actor.id if actor else None, bool(session.get("user_id")))
                    if actor and actor.is_active:
                        flash("Форма смены пароля устарела. Мы обновили её — введите новый пароль ещё раз.", "warning")
                        response = redirect(url_for("auth.change_password", refresh="1"), code=303)
                    else:
                        session.clear()
                        flash("Сессия истекла. Войдите снова, чтобы завершить обязательную смену пароля.", "warning")
                        response = redirect(url_for("auth.login"), code=303)
                    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
                    response.headers["Pragma"] = "no-cache"
                    response.headers["Expires"] = "0"
                    return response
                return jsonify({"ok": False, "error": "CSRF-токен отсутствует или недействителен. Обновите страницу и повторите."}), 400

        # Keep a conservative per-process API limiter to reduce accidental bursts/abuse.
        if path.startswith(("/student-app/api/",)):
            is_write = request.method in {"POST", "PUT", "PATCH", "DELETE"}
            if _student_app_rate_limited(request.remote_addr, is_write, request.endpoint or request.path):
                return jsonify({"ok": False, "error": "Слишком много запросов. Повторите через минуту."}), 429
        # Keep a local safety net for bot ingress too: Flask-Limiter/Redis may be
        # unavailable, but a valid webhook secret must not be the only abuse barrier.
        if path == "/hooks/max" and request.method == "POST":
            if _student_app_rate_limited(request.remote_addr, True, "max-bot-webhook", cap_override=300):
                return jsonify({"ok": False, "error": "Слишком много запросов к webhook. Повторите через минуту."}), 429
        return None

    @app.after_request
    def add_security_headers(response):
        if request.path == "/auth/change-password":
            # Password forms contain a per-session CSRF token and must never be
            # replayed from browser/proxy caches or restored from a stale tab.
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            response.headers["X-Password-Flow-Version"] = "standalone-v2"
        response.headers.setdefault("X-Request-ID", getattr(g, "request_id", uuid.uuid4().hex))
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin-allow-popups")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-site")
        if request.path != "/student-app":
            # Defense-in-depth policy for server-rendered pages. Inline assets are
            # still needed by legacy templates; external scripts are allowlisted.
            csp = (
                "default-src 'self'; base-uri 'self'; object-src 'none'; form-action 'self'; frame-ancestors 'none'; "
                "script-src 'self' 'unsafe-inline' https://telegram.org https://st.max.ru; "
                "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; "
                "font-src 'self' data: https:; connect-src 'self' https://api.telegram.org https://st.max.ru https://api.vk.com https://max.ru;"
            )
            # Do not upgrade requests on the local/private HTTP server. On HTTP,
            # CSP upgrade-insecure-requests makes browsers attempt TLS on the plain
            # Werkzeug port and produces noisy `Bad request version` errors.
            # Enable it only when TLS is active in Flask or explicitly terminated
            # by the trusted internal HTTPS proxy (INTERNAL_HTTPS=1).
            if request.is_secure or settings.SESSION_COOKIE_SECURE:
                csp += " upgrade-insecure-requests;"
            response.headers.setdefault("Content-Security-Policy", csp)
        if request.path == "/student-app":
            # Telegram Web Apps may be embedded in Telegram's official web client.
            response.headers.pop("X-Frame-Options", None)
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; base-uri 'self'; object-src 'none'; form-action 'self'; "
                "frame-ancestors 'self' https://web.telegram.org https://*.telegram.org https://t.me https://vk.com https://*.vk.com https://max.ru https://*.max.ru; "
                "script-src 'self' https://telegram.org https://st.max.ru; style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: blob: https:; font-src 'self' data: https:; "
                "connect-src 'self' https://api.telegram.org"
            )
        # Dynamic pages and API responses contain per-user state; do not let the
        # browser/WebView revalidate cached HTML/JSON on the next navigation.
        if request.endpoint != "static":
            response.headers["Cache-Control"] = "no-store, max-age=0, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            response.headers.pop("ETag", None)
            response.headers.pop("Last-Modified", None)
        if request.is_secure:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")

        # Record requests made by authenticated, registered web accounts.
        # Every UserRole account is included; anonymous and bot events stay separate.
        # Query strings and request bodies are never stored.
        elapsed_ms = round((time.perf_counter() - getattr(g, "request_started_at", time.perf_counter())) * 1000, 1)
        request_id = getattr(g, "request_id", "unknown")
        endpoint = request.endpoint or "unmatched"
        status_code = int(response.status_code)

        audit_actor_user_id = getattr(g, "audit_actor_user_id", None)
        audit_actor_login = getattr(g, "audit_actor_login", None)
        audit_actor_role = getattr(g, "audit_actor_role", None)
        # Login and OTP handlers establish the session while handling this request;
        # capture the authenticated actor on the redirect response as well.
        if (endpoint in {"auth.login", "auth.verify_otp"}
                and status_code in {302, 303} and session.get("user_id")):
            audit_actor_user_id = session.get("user_id")
            audit_actor_login = session.get("user_login") or audit_actor_login
            audit_actor_role = session.get("user_role") or audit_actor_role

        registered_account_roles = set(REGISTERED_WEB_ACCOUNT_ROLES)
        is_registered_account_actor = bool(audit_actor_user_id) and audit_actor_role in registered_account_roles
        # Legacy variable name is retained for existing audit condition coverage.
        is_staff_actor = is_registered_account_actor
        background_get_paths = {
            "/api/visual-theme", "/notifications/api/unread",
            "/audit-log/check", "/system/runtime/status",
            "/bot-activity/live-summary",
        }
        is_background_read = request.method == "GET" and (
            request.path in background_get_paths
            or request.path.startswith("/notifications/api/")
            or request.path.startswith("/bot-activity/live/")
        )
        is_student_identity_request = request.path == '/student-app' or request.path.startswith('/student-app/')
        # Persist actual staff operations, failures and slow requests. A normal
        # successful GET page view is navigation noise and used to cause an
        # extra synchronous write/SQLite transaction on almost every page.
        is_staff_write_request = bool(
            is_staff_actor
            and not is_student_identity_request
            and request.endpoint != "static"
            and not request.path.startswith("/static/")
            and request.path != "/favicon.ico"
            and not is_background_read
            and request.method in {"POST", "PUT", "PATCH", "DELETE"}
        )

        if request.endpoint != "static" and (
                request.method != "GET" or status_code >= 400 or elapsed_ms >= 1500
                or is_staff_write_request):
            request_log_level = logging.ERROR if status_code >= 500 else (
                logging.WARNING if status_code >= 400 or elapsed_ms >= 1500 else logging.INFO
            )
            logger.log(
                request_log_level,
                "http_request request_id=%s method=%s path=%s endpoint=%s status=%s duration_ms=%s actor_role=%s",
                request_id, request.method, request.path, endpoint, status_code, elapsed_ms,
                str(audit_actor_role or "anonymous")[:40],
            )

            # Existing technical records remain available to system diagnostics,
            # but the staff journal below filters strictly to authenticated roles.
            try:
                is_login_attempt = endpoint == "auth.login" and request.method == "POST"
                if is_login_attempt:
                    if status_code == 429:
                        action = "auth.login.rate_limited"
                    elif status_code in {302, 303} and session.get("user_id"):
                        action = "auth.login.succeeded"
                    else:
                        action = "auth.login.failed"
                elif endpoint == "auth.logout":
                    action = "auth.logout"
                elif status_code >= 400:
                    action = f"{endpoint}.failed"[:80]
                elif request.method == "GET":
                    action = f"{endpoint}.view"[:80]
                else:
                    action = endpoint[:80]

                should_persist = (
                    request.method in {"POST", "PUT", "PATCH", "DELETE"}
                    or status_code >= 400 or elapsed_ms >= 1500
                )
                if should_persist:
                    stored_actor_login = (
                        audit_actor_login
                        or getattr(g, "audit_attempted_login", None)
                    )
                    audit_values = {
                        "request_id": str(request_id)[:64],
                        "actor_user_id": audit_actor_user_id,
                        "actor_login": str(stored_actor_login)[:255] if stored_actor_login else None,
                        "actor_role": str(audit_actor_role or "")[:40] or None,
                        "action": action,
                        "method": request.method[:10],
                        "path": request.path[:512],
                        "status_code": status_code,
                        "duration_ms": elapsed_ms,
                        "ip_address": (request.remote_addr or "")[:45] or None,
                    }
                    # Independent system-bind transaction: an audit failure must not
                    # commit or roll back the underlying application operation.
                    audit_engine = db.engines.get("system")
                    if audit_engine is None:
                        raise RuntimeError("The system database bind is not configured")
                    with audit_engine.begin() as audit_connection:
                        audit_connection.execute(HttpAuditLog.__table__.insert().values(**audit_values))
            except Exception:
                logger.warning("Could not persist HTTP audit entry request_id=%s", request_id, exc_info=True)
        return response
    db.init_app(app)
    from services.bot_journal import bind_journal_app
    bind_journal_app(app)

    def configure_sqlite_connection(dbapi_connection, _connection_record):
        """Keep local SQLite responsive when web and bot threads overlap."""
        cursor = None
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA busy_timeout = 15000")
            cursor.execute("PRAGMA journal_mode = WAL")
        except Exception:
            # WAL is a performance improvement, not a reason to prevent startup.
            logger.debug("Could not enable SQLite WAL on a connection", exc_info=True)
        finally:
            if cursor is not None:
                cursor.close()

    # Register the PRAGMAs for every SQLite database bind, including databases
    # opened later on demand. This remains entirely local and needs no extra service.
    with app.app_context():
        for engine in db.engines.values():
            if engine.dialect.name == "sqlite":
                event.listen(engine, "connect", configure_sqlite_connection)

    set_flask_app(app)

    @app.context_processor
    def inject_active_visual_theme():
        try:
            theme = current_student_app_season()
        except Exception:
            theme = DEFAULT_STUDENT_APP_SEASON
        staff_nav_access = {section: False for section in ('students', 'applications', 'events', 'lessons', 'notifications')}
        staff_nav_access.update({'analytics': False, 'orders': False, 'activity_chats': False, 'staff_messenger': False, 'report_archive': False, 'blocked_students': False, 'leadership_public': False, 'directions': False})
        try:
            nav_user = User.query.get(session.get('user_id')) if session.get('user_id') else None
            if nav_user and nav_user.is_active and nav_user.role == UserRole.STAFF.value:
                from services.staff_access import direction_ids as staff_direction_ids
                for section in ('students', 'applications', 'events', 'lessons', 'notifications'):
                    staff_nav_access[section] = bool(staff_direction_ids(nav_user, section, 'view'))
                has_student_scope = bool(staff_direction_ids(nav_user, 'students', 'view'))
                has_application_scope = bool(staff_direction_ids(nav_user, 'applications', 'view'))
                staff_nav_access['students'] = has_student_scope or has_application_scope
                staff_nav_access['blocked_students'] = has_student_scope
                staff_nav_access['leadership_public'] = has_student_scope
                staff_nav_access['analytics'] = bool(staff_direction_ids(nav_user, 'statistics', 'view'))
                staff_nav_access['orders'] = bool(staff_direction_ids(nav_user, 'orders', 'view'))
                staff_nav_access['activity_chats'] = bool(staff_direction_ids(nav_user, 'chats', 'view'))
                staff_nav_access['staff_messenger'] = True
                staff_nav_access['report_archive'] = bool(staff_direction_ids(nav_user, 'report_archive', 'view'))
                staff_nav_access['directions'] = any(bool(staff_direction_ids(nav_user, section, 'view')) for section in ('students', 'applications', 'events', 'lessons', 'notifications', 'statistics', 'chats', 'orders', 'report_archive'))
            elif nav_user and nav_user.is_active and nav_user.role == UserRole.SUPER_ADMIN.value:
                from services.staff_access import SECTIONS as STAFF_SECTIONS, direction_ids as staff_direction_ids
                for section in STAFF_SECTIONS:
                    staff_nav_access[section] = bool(staff_direction_ids(nav_user, section, 'view'))
                staff_nav_access['analytics'] = bool(staff_direction_ids(nav_user, 'statistics', 'view'))
                staff_nav_access['orders'] = bool(staff_direction_ids(nav_user, 'orders', 'view'))
                staff_nav_access['activity_chats'] = True
                staff_nav_access['staff_messenger'] = True
                staff_nav_access['report_archive'] = True
        except Exception:
            logger.debug("Unable to build staff navigation permissions", exc_info=True)
        staff_role_caption = "Сотрудник · направление не назначено"
        try:
            if nav_user and nav_user.is_active and nav_user.role == UserRole.STAFF.value:
                if getattr(nav_user, "staff_rank", "employee") == "employee_all":
                    staff_role_caption = "Сотрудник · все направления"
                else:
                    direction_name = getattr(getattr(nav_user, "assigned_direction", None), "name", None)
                    staff_role_caption = f"Сотрудник · {direction_name}" if direction_name else "Сотрудник · направление не назначено"
        except Exception:
            logger.debug("Unable to resolve staff role caption", exc_info=True)
        theme_config = STUDENT_APP_SEASONS[theme]
        palette = theme_config.get("palette", ["#FFB26B", "#EE637D", "#100D1A"])
        return {"active_visual_theme": theme,
                "active_visual_theme_config": theme_config,
                "active_visual_theme_accent_rgb": _hex_rgb_triplet(palette[0]),
                "active_visual_theme_secondary_rgb": _hex_rgb_triplet(palette[1]),
                "theme_change_animation": bool(request.args.get("theme_changed") == "1"),
                "staff_nav_access": staff_nav_access,
                "staff_role_caption": staff_role_caption,
                "csrf_token": csrf_token}

    app.register_blueprint(auth_bp); app.register_blueprint(admin_bp)
    app.register_blueprint(directions_bp); app.register_blueprint(quotas_bp)
    app.register_blueprint(lessons_bp)
    app.register_blueprint(stats_bp)
    app.register_blueprint(student_app_bp)
    from services.staff_routes import staff_bp
    app.register_blueprint(staff_bp)
    from services.orders import orders_bp
    app.register_blueprint(orders_bp)
    from services.activity_chats import activity_chat_bp
    app.register_blueprint(activity_chat_bp)
    from services.staff_messenger import staff_messenger_bp
    app.register_blueprint(staff_messenger_bp)
    # Extra route-level throttling; the built-in in-process guard remains as fallback.
    # Import from the project root for Windows deployments where the optional
    # backend/ package may be absent in an in-place update.
    from security import install_route_rate_limits
    install_route_rate_limits(app, logger)
    return app