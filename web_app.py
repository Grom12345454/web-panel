from functools import wraps
import html
from datetime import datetime
import requests, threading, json, os, logging, queue, io, uuid
from flask import Blueprint, Flask, flash, redirect, render_template, request, session, url_for, jsonify, send_file
from sqlalchemy import func
from config import settings
from database import (
    db, verify_password, Student, User, Direction, EventQuota, EventDay, DayParticipation,
    DirectionQuestion, StudentLeadership, DirectionStatus, NotificationTemplate, DirectionChat, TelegramChatCandidate,
    student_directions, UserRole, StudentQuotaStat, Lesson,
    get_direction_quota_ids, get_quota_directions, set_quota_directions, get_quota_chat_targets, set_quota_chat_targets,
)
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors

logger = logging.getLogger(__name__)

notification_queue = queue.Queue()
_flask_app_instance = None

def set_flask_app(app):
    global _flask_app_instance
    _flask_app_instance = app

def notification_worker():
    while True:
        try:
            task = notification_queue.get(timeout=1)
            if task is None: break
            chat_id, text = task
            if not settings.BOT_TOKEN:
                logger.warning("Telegram notification skipped: BOT_TOKEN не задан")
                continue
            try:
                resp = requests.post(f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendMessage",
                    json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=10)
                if resp.status_code == 200: logger.info(f"Sent to {chat_id}")
            except Exception as e: logger.error(f"Send error: {e}")
        except queue.Empty: continue
        except Exception as e: logger.error(f"Worker error: {e}", exc_info=True)

worker_thread = threading.Thread(target=notification_worker, daemon=True, name="NotificationWorker")
worker_thread.start()

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
            last_error = str(exc)
            if attempt < attempts:
                import time
                time.sleep(attempt)
                continue
            logger.error("Telegram API %s network error: %s", method, exc)
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
    data = _telegram_api('sendMessage', payload, attempts=3, timeout=10)
    return bool(data)


def _send_tg_detailed(chat_id, text, reply_markup=None):
    if not chat_id or not settings.BOT_TOKEN:
        return False, "BOT_TOKEN не задан."
    payload = {"chat_id": str(chat_id), "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    data, error = _telegram_api_detailed("sendMessage", payload, attempts=3, timeout=10)
    return bool(data), error


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
            last_error = str(exc)
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
                logger.error("Cannot resolve direction chat id=%s (record #%s)", chat.chat_id, chat.id)
                continue
            if stable_chat_id != str(chat.chat_id):
                chat.chat_id = stable_chat_id
                db.session.commit()
            if _send_tg(stable_chat_id, text, reply_markup=reply_markup):
                sent += 1
            else:
                logger.error("Broadcast failed for direction %s, chat %s", direction_id, stable_chat_id)
    except Exception:
        logger.exception("Direction chat broadcast failed for direction %s", direction_id)
    logger.info("Broadcast result for direction %s: %s/%s delivered", direction_id, sent, len(chats) if 'chats' in locals() else 0)
    return sent

def is_student_council_direction(direction):
    """Student Council is a special broadcast direction: quota posts go to every active chat."""
    if not direction:
        return False
    value = f"{direction.name or ''} {direction.code or ''}".strip().lower().replace("ё", "е")
    return ("студенческий совет" in value or "студсовет" in value or
            "student council" in value or "student_council" in value or value.strip() in {"сс", "sc"})


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
                "name": f"University Control • {student_name or 'Студент'}"[:32],
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
    """Remove a student from every active Telegram chat of a direction without blocking them permanently."""
    if not student or not student.tg_id or student.tg_id <= 0:
        return 0
    removed = 0
    try:
        chats = DirectionChat.query.filter_by(direction_id=direction.id, is_active=True).all()
        for chat in chats:
            stable_chat_id, _ = _resolve_chat_id(chat.chat_id)
            if not stable_chat_id:
                continue
            ban = _telegram_api("banChatMember", {
                "chat_id": stable_chat_id,
                "user_id": int(student.tg_id),
                "revoke_messages": False,
            }, attempts=2, timeout=10)
            if ban:
                # Immediately unban so the student is removed but can use a new invite later.
                _telegram_api("unbanChatMember", {
                    "chat_id": stable_chat_id,
                    "user_id": int(student.tg_id),
                    "only_if_banned": True,
                }, attempts=2, timeout=10)
                removed += 1
    except Exception:
        logger.exception("Не удалось удалить студента %s из чатов направления %s", student.id, direction.id)
    return removed


def send_notification_by_template(student, template_key, variables):
    try:
        nt = NotificationTemplate.query.filter_by(key=template_key).first()
        if not nt: return False
        text = nt.template_text
        for var_name, var_value in variables.items():
            text = text.replace(f"{{{var_name}}}", html.escape(str(var_value)))
        if student.tg_id and student.tg_id > 0:
            notification_queue.put((student.tg_id, text)); return True
    except Exception as e: logger.error(f"Notification error: {e}")
    return False

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")
admin_bp = Blueprint("admin", __name__)
directions_bp = Blueprint("directions", __name__, url_prefix="/directions")
quotas_bp = Blueprint("quotas", __name__, url_prefix="/quotas")
stats_bp = Blueprint("stats", __name__, url_prefix="/stats")

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session: return redirect(url_for("auth.login"))
        user = User.query.get(session["user_id"])
        if not user: session.clear(); return redirect(url_for("auth.login"))
        return f(*args, current_user=user, **kwargs)
    return decorated

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = User.query.filter_by(email=request.form["email"]).first()
        if user and verify_password(request.form["password"], user.password_hash):
            session["user_id"] = user.id
            session["user_role"] = user.role
            session.permanent = False
            return redirect(url_for("admin.dashboard"))
        flash("Неверные данные", "danger")
    return render_template("login.html")

@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))

@admin_bp.route("/")
@login_required
def dashboard(current_user):
    stats = {
        "total_students": Student.query.count(),
        "pending_apps": db.session.query(student_directions).filter_by(status='pending').count(),
        "active_members": db.session.query(student_directions).filter_by(status='active').count(),
        "free_places": sum(d.available_places() for q in EventQuota.query.all() for d in q.days)
    }
    dirs = Direction.query.all()
    dir_stats = [{'id': d.id, 'name': d.name, 'icon': d.icon, 'color': d.color, 
                  'description': d.description,
                  'count': len(d.students), 'has_questions': len(d.questions) > 0} for d in dirs]
    
    return render_template("dashboard.html", 
                         stats=stats, 
                         directions=dirs, 
                         direction_stats=dir_stats,
                         current_user=current_user)

@admin_bp.route("/students/add", methods=["POST"], endpoint="add_student")
@login_required
def add_student(current_user):
    full_name = request.form.get("full_name", "").strip()
    group = request.form.get("group", "").strip()
    phone = request.form.get("phone", "").strip()
    email = request.form.get("email", "").strip()
    tg_raw = request.form.get("tg_id", "").strip()
    direction_ids = request.form.getlist("direction_ids", type=int)
    status = request.form.get("status", DirectionStatus.ACTIVE.value)
    if status not in {x.value for x in DirectionStatus}:
        status = DirectionStatus.ACTIVE.value
    if not full_name:
        flash("ФИО студента обязательно.", "danger")
        return redirect(url_for("admin.students_management"))
    try:
        tg_id = int(tg_raw) if tg_raw else -int(uuid.uuid4().int % 8_500_000_000_000_000_000)
        if Student.query.filter_by(tg_id=tg_id).first():
            flash("Такой Telegram ID уже привязан к другому студенту.", "danger")
            return redirect(url_for("admin.students_management"))
        student = Student(full_name=full_name, group=group, phone=phone, email=email, tg_id=tg_id)
        db.session.add(student)
        db.session.flush()
        clean_dids = []
        for did in direction_ids:
            if did not in clean_dids and Direction.query.get(did):
                clean_dids.append(did)
                db.session.execute(student_directions.insert().values(
                    student_id=student.id, direction_id=did, status=status
                ))
        db.session.commit()
        flash(f"Студент «{full_name}» добавлен.", "success")
    except Exception:
        db.session.rollback()
        logger.exception("Unable to add student")
        flash("Не удалось добавить студента.", "danger")
    return redirect(url_for("admin.students_management"))


@admin_bp.route("/students/<int:sid>/edit", methods=["GET", "POST"], endpoint="edit_student")
@login_required
def edit_student(sid, current_user):
    student = Student.query.get_or_404(sid)
    if request.method == "POST":
        student.full_name = request.form.get("full_name", "").strip()
        student.group = request.form.get("group", "").strip()
        student.phone = request.form.get("phone", "").strip()
        student.email = request.form.get("email", "").strip()
        tg_raw = request.form.get("tg_id", "").strip()
        if not student.full_name:
            flash("ФИО студента обязательно.", "danger")
            return redirect(url_for("admin.edit_student", sid=sid))
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
        db.session.commit()
        flash("Карточка студента обновлена.", "success")
        return redirect(url_for("admin.students_management"))
    return render_template("student_form.html", student=student)


@admin_bp.route("/students/<int:sid>/delete", methods=["POST"], endpoint="delete_student")
@login_required
def delete_student(sid, current_user):
    student = Student.query.get_or_404(sid)
    name = student.full_name
    try:
        # Удаляем зависимые записи во всех подсистемах. Внешние БД не имеют cross-db FK.
        DayParticipation.query.filter_by(student_id=sid).delete(synchronize_session=False)
        StudentQuotaStat.query.filter_by(student_id=sid).delete(synchronize_session=False)
        StudentLeadership.query.filter_by(student_id=sid).delete(synchronize_session=False)
        db.session.execute(student_directions.delete().where(student_directions.c.student_id == sid))
        db.session.delete(student)
        db.session.commit()
        flash(f"Студент «{name}» и его связанные записи удалены.", "success")
    except Exception:
        db.session.rollback()
        logger.exception("Unable to delete student %s", sid)
        flash("Не удалось удалить студента. Изменения отменены.", "danger")
    return redirect(url_for("admin.students_management"))


@admin_bp.route("/students")
@login_required
def students_management(current_user):
    status_filter = request.args.get("status", "all")
    links = db.session.execute(student_directions.select()).fetchall()
    by_student = {}
    for link in links:
        by_student.setdefault(link.student_id, []).append(link)

    students = []
    counts = {"total": 0, "pending": 0, "approved": 0, "active": 0, "rejected": 0, "interview": 0}
    for student in Student.query.order_by(Student.full_name).all():
        student_links = by_student.get(student.id, [])
        statuses = [getattr(link, "status", None) for link in student_links]
        primary = next((st for st in ["pending", "interview", "approved", "active", "rejected"] if st in statuses), None)
        if status_filter != "all" and primary != status_filter:
            continue
        student.status = primary or "—"
        students.append(student)

    # Counts считаем независимо от фильтра, чтобы фильтры оставались прозрачными.
    for student in Student.query.all():
        sts = [getattr(link, "status", None) for link in by_student.get(student.id, [])]
        primary = next((st for st in ["pending", "interview", "approved", "active", "rejected"] if st in sts), None)
        counts["total"] += 1 if primary else 0
        if primary in counts:
            counts[primary] += 1

    return render_template("students.html", students=students, stats=counts, status_filter=status_filter, directions=Direction.query.order_by(Direction.name).all())

# ✅ ИСПРАВЛЕННОЕ ОДОБРЕНИЕ ЗАЯВКИ (работает со связью student_directions)
@directions_bp.route("/<int:did>/approve/<int:sid>", methods=["POST"])
@login_required
def approve_student(did, sid, current_user):
    link = db.session.execute(student_directions.select().where(
        (student_directions.c.student_id == sid) & (student_directions.c.direction_id == did)
    )).fetchone()
    
    if link:
        db.session.execute(student_directions.update().where(
            (student_directions.c.student_id == sid) & (student_directions.c.direction_id == did)
        ).values(status=DirectionStatus.APPROVED.value))
        db.session.commit()
        
        student = Student.query.get(sid)
        direction = Direction.query.get(did)
        send_notification_by_template(student, "direction_approved", 
            {"direction": f"{direction.icon} {direction.name}"})
        invite_count = send_direction_invites(student, direction)
        if invite_count:
            logger.info("Отправлено %s invite-ссылок студенту %s для направления %s", invite_count, student.id, direction.id)
        
        flash(f"Заявка {student.full_name} одобрена. Invite-ссылки отправлены: {invite_count}", "success")
    else:
        flash("Связь студента с направлением не найдена", "danger")
        
    return redirect(url_for("directions.direction_detail", did=did))

# ✅ ИСПРАВЛЕННАЯ АКТИВАЦИЯ СТУДЕНТА (переводит в ACTIVE)
@directions_bp.route("/<int:did>/activate/<int:sid>", methods=["POST"])
@login_required
def activate_student(did, sid, current_user):
    link = db.session.execute(student_directions.select().where(
        (student_directions.c.student_id == sid) & (student_directions.c.direction_id == did)
    )).fetchone()
    
    if link:
        db.session.execute(student_directions.update().where(
            (student_directions.c.student_id == sid) & (student_directions.c.direction_id == did)
        ).values(status=DirectionStatus.ACTIVE.value))
        db.session.commit()
        
        student = Student.query.get(sid)
        direction = Direction.query.get(did)
        send_notification_by_template(student, "activation", 
            {"student_name": student.full_name, "direction": f"{direction.icon} {direction.name}"})
            
        flash(f"Студент {student.full_name} активирован", "success")
    else:
        flash("Связь студента с направлением не найдена", "danger")
        
    return redirect(url_for("directions.direction_detail", did=did))

# ✅ ОТКЛОНЕНИЕ ЗАЯВКИ
@directions_bp.route("/<int:did>/reject/<int:sid>", methods=["POST"])
@login_required
def reject_student(did, sid, current_user):
    link = db.session.execute(student_directions.select().where(
        (student_directions.c.student_id == sid) & (student_directions.c.direction_id == did)
    )).fetchone()
    
    if link:
        db.session.execute(student_directions.update().where(
            (student_directions.c.student_id == sid) & (student_directions.c.direction_id == did)
        ).values(status=DirectionStatus.REJECTED.value))
        db.session.commit()
        
        student = Student.query.get(sid)
        direction = Direction.query.get(did)
        send_notification_by_template(student, "direction_rejected", 
            {"direction": f"{direction.icon} {direction.name}"})
        removed_count = remove_student_from_direction_chats(student, direction)
        
        flash(f"Заявка {student.full_name} отклонена. Удалено из чатов: {removed_count}", "warning")
    else:
        flash("Связь студента с направлением не найдена", "danger")
        
    return redirect(url_for("directions.direction_detail", did=did))

@admin_bp.route("/leadership", methods=["GET", "POST"], endpoint="manage_leadership")
@login_required
def manage_leadership(current_user):
    if current_user.role != UserRole.SUPER_ADMIN.value:
        flash("Доступ запрещен", "danger")
        return redirect(url_for("admin.dashboard"))
        
    if request.method == "POST":
        action = request.form.get("action")
        
        if action == "assign":
            sid = request.form.get("student_id", type=int)
            did = request.form.get("direction_id", type=int)
            pos = request.form.get("position_name", "").strip()
            
            if sid and did and pos:
                existing = StudentLeadership.query.filter_by(student_id=sid, direction_id=did).first()
                if existing:
                    existing.position_name = pos
                else:
                    db.session.add(StudentLeadership(student_id=sid, direction_id=did, position_name=pos))
                
                link_exists = db.session.execute(
                    student_directions.select().where(
                        (student_directions.c.student_id == sid) & 
                        (student_directions.c.direction_id == did)
                    )
                ).fetchone()
                
                if not link_exists:
                    db.session.execute(student_directions.insert().values(
                        student_id=sid,
                        direction_id=did,
                        status=DirectionStatus.ACTIVE.value,
                        extra_data=json.dumps({"source": "leadership_assignment"})
                    ))
                    
                db.session.commit()
                
                direction = Direction.query.get(did)
                student = Student.query.get(sid)
                send_notification_by_template(
                    student, 
                    "leadership_assign", 
                    {"position": pos, "direction": f"{direction.icon} {direction.name}"}
                )
                
                logger.info(f"Admin {current_user.id} assigned leader: Student {sid}, Dir {did}, Pos '{pos}'")
                flash(f"Руководитель назначен: {pos}. Студент добавлен в направление.", "success")
                
        elif action == "remove":
            lid = request.form.get("leadership_id", type=int)
            reason = request.form.get("removal_reason", "").strip()
            
            leader = StudentLeadership.query.get(lid)
            if leader:
                student = leader.student
                direction = leader.direction
                position = leader.position_name
                
                send_notification_by_template(
                    student,
                    "leadership_remove",
                    {"position": position, "direction": f"{direction.icon} {direction.name}", "reason": reason}
                )
                
                db.session.delete(leader)
                db.session.commit()
                flash("Руководитель снят с должности", "success")
    
    leaders = StudentLeadership.query.all()
    students = Student.query.all()
    directions = Direction.query.all()
    
    return render_template("leadership.html", 
                         leaders=leaders, 
                         students=students, 
                         directions=directions)

@stats_bp.route("/students/summary")
@login_required
def students_summary(current_user):
    # Stats are kept in a separate SQLite DB, so aggregation is done in Python
    # instead of a cross-database SQL JOIN.
    stats_rows = StudentQuotaStat.query.order_by(StudentQuotaStat.student_id).all()
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
    return render_template("students_summary.html", summary=summary)


@stats_bp.route("/students", methods=["GET", "POST"])
@login_required
def students_quota_stats(current_user):
    filter_did = request.args.get('direction_id', type=int)

    if request.method == "POST" and request.form.get("action") == "reset_stats":
        sid = request.form.get("student_id", type=int)
        did = request.form.get("direction_id", type=int)
        reason = request.form.get("reset_reason", "").strip()

        stat = StudentQuotaStat.query.filter_by(student_id=sid, direction_id=did).first()
        if stat:
            stat.total_quotas = 0
            stat.attended_count = 0
            db.session.commit()
            logger.info("Stats reset for student %s, dir %s. Reason: %s", sid, did, reason)
            flash(f"Статистика сброшена. Причина: {reason or 'Не указана'}", "success")
        return redirect(url_for("stats.students_quota_stats", direction_id=filter_did))

    stats_query = StudentQuotaStat.query
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
    return render_template("students_quota_stats.html", stats_list=stats_list, directions=Direction.query.order_by(Direction.name).all(), filter_did=filter_did)

@stats_bp.route("/<int:did>")
@login_required
def direction_statistics(did, current_user):
    """Безопасная статистика направления.

    В этой странице не используем ленивую цепочку q.days -> day.participations:
    на старых БД она может падать из-за повреждённых/неполных связей. Все значения
    собираются явными запросами и NULL нормализуются в Python.
    """
    direction = Direction.query.get_or_404(did)

    # Статусы заявок по направлению.
    link_rows = db.session.execute(
        student_directions.select().where(student_directions.c.direction_id == did)
    ).mappings().all()
    statuses = [row.get("status") or "" for row in link_rows]
    status_values = [getattr(status, "value", status) for status in statuses]
    total = len(status_values)
    pending = status_values.count("pending")
    approved = status_values.count("approved")
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
        "direction_stats.html",
        direction=direction,
        stats={
            "total": total,
            "pending": pending,
            "approved": approved,
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

@quotas_bp.route("/<int:qid>/close", methods=["POST"])
@login_required
def close_quota(qid, current_user):
    quota = EventQuota.query.get_or_404(qid)
    reason = request.form.get("reason", "").strip()

    # Не допускаем повторного закрытия и двойного начисления статистики.
    if quota.is_closed:
        flash("Это мероприятие уже закрыто.", "warning")
        return redirect(url_for("quotas.quotas_list"))

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph(f"<b>ПРИКАЗ №{qid}/{datetime.now().year}</b>", styles["Title"]))
    elements.append(Spacer(1, 20))
    elements.append(Paragraph(f"О закрытии мероприятия: {quota.event_title}", styles["Heading2"]))
    elements.append(Paragraph(f"Дата закрытия: {datetime.now().strftime('%d.%m.%Y %H:%M')}", styles["Normal"]))
    elements.append(Paragraph(f"Причина: {reason or 'Завершение набора'}", styles["Normal"]))
    elements.append(Spacer(1, 20))

    data = [["№", "ФИО", "Группа", "Направление", "Статус"]]
    idx = 1

    for day in quota.days:
        for p in sorted(day.participations, key=lambda x: x.student.full_name):
            status_ru = {
                "registered": "Записан",
                "attended": "Присутствовал",
                "absent": "Отсутствовал",
                "cancelled": "Отменен",
            }.get(p.status, p.status)

            for d in quota.directions:
                stat = StudentQuotaStat.query.filter_by(
                    student_id=p.student_id, direction_id=d.id
                ).first()

                if not stat:
                    stat = StudentQuotaStat(student_id=p.student_id, direction_id=d.id)
                    db.session.add(stat)

                # В старой БД эти поля могли быть сохранены как NULL.
                stat.total_quotas = (stat.total_quotas or 0) + 1
                stat.attended_count = (stat.attended_count or 0)
                if p.status == "attended":
                    stat.attended_count += 1

            data.append([
                str(idx), p.student.full_name, p.student.group,
                quota.directions[0].name if quota.directions else "-", status_ru
            ])
            idx += 1

    table = Table(data, colWidths=[30, 150, 60, 100, 80])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 1, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#ecf0f1")]),
    ]))
    elements.append(table)

    try:
        doc.build(elements)
        buffer.seek(0)

        quota.is_closed = True
        quota.closing_reason = reason
        quota.closed_at = datetime.utcnow()
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("Не удалось закрыть квоту #%s", qid)
        flash("Не удалось закрыть мероприятие. Изменения отменены — повторите попытку.", "danger")
        return redirect(url_for("quotas.quota_participants", qid=qid))

    return send_file(
        buffer,
        download_name=f"приказ_{quota.event_title}_{qid}.pdf",
        mimetype="application/pdf",
    )

@directions_bp.route("/<int:did>/chat/connect/<int:cid>", methods=["POST"], endpoint="connect_chat_candidate")
@login_required
def connect_chat_candidate(did, cid, current_user):
    direction = Direction.query.get_or_404(did)
    candidate = TelegramChatCandidate.query.get_or_404(cid)
    chat_text = (
        f"🔔 <b>University Control</b>\n\n"
        f"Тестовое подключение чата к направлению «{html.escape(direction.name)}».\n"
        "После этого сюда будут дублироваться новые занятия и мероприятия."
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
        existing.last_test_at = datetime.utcnow()
    else:
        db.session.add(DirectionChat(
            direction_id=did, chat_id=str(candidate.chat_id),
            title=candidate.title or str(candidate.chat_id), username=candidate.username or "",
            is_active=True, last_test_at=datetime.utcnow()
        ))
    db.session.commit()
    flash(f"Чат «{candidate.title or candidate.chat_id}» подключён и проверен.", "success")
    return redirect(url_for("directions.direction_detail", did=did))


@directions_bp.route("/<int:did>/chat/add", methods=["POST"], endpoint="add_chat")
@login_required
def add_chat(did, current_user):
    direction = Direction.query.get_or_404(did)
    chat_id = request.form.get("chat_id", "").strip()
    title = request.form.get("title", "").strip()
    username = request.form.get("username", "").strip()
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

    existing = DirectionChat.query.filter_by(direction_id=did, chat_id=resolved_chat_id).first()
    if existing:
        existing.title = title
        existing.username = username
        existing.is_active = True
    else:
        db.session.add(DirectionChat(direction_id=did, chat_id=resolved_chat_id, title=title, username=username, is_active=True))
    db.session.commit()
    flash(f"Чат «{title}» подключён. Telegram ID: {resolved_chat_id}", "success")
    return redirect(url_for("directions.direction_detail", did=did))


@directions_bp.route("/<int:did>/chat/<int:cid>/delete", methods=["POST"], endpoint="delete_chat")
@login_required
def delete_chat(did, cid, current_user):
    chat = DirectionChat.query.get_or_404(cid)
    if chat.direction_id != did:
        flash("Чат не относится к этому направлению.", "danger")
        return redirect(url_for("directions.direction_detail", did=did))
    name = chat.title
    db.session.delete(chat)
    db.session.commit()
    flash(f"Чат «{name}» отключён.", "success")
    return redirect(url_for("directions.direction_detail", did=did))


@directions_bp.route("/<int:did>/chat/<int:cid>/test", methods=["POST"], endpoint="test_chat")
@login_required
def test_chat(did, cid, current_user):
    chat = DirectionChat.query.get_or_404(cid)
    if chat.direction_id != did:
        flash("Чат не относится к этому направлению.", "danger")
        return redirect(url_for("directions.direction_detail", did=did))
    ok, error = _send_tg_detailed(chat.chat_id, f"🔔 <b>University Control</b>\n\nТестовое сообщение для направления «{html.escape(Direction.query.get(did).name)}».\nЧат подключён корректно.")
    if ok:
        chat.last_test_at = datetime.utcnow()
        db.session.commit()
        flash(f"Тестовое сообщение отправлено в «{chat.title}».", "success")
    else:
        flash(f"Telegram не принял сообщение: {error}", "danger")
    return redirect(url_for("directions.direction_detail", did=did))


@directions_bp.route("/", endpoint="directions_list")
@login_required
def directions_list(current_user):
    return render_template("directions.html", directions=Direction.query.all())

@directions_bp.route("/<int:did>")
@login_required
def direction_detail(did, current_user):
    d = Direction.query.get_or_404(did)
    students_with_status = []
    links = db.session.execute(student_directions.select().where(student_directions.c.direction_id == did)).fetchall()
    for link in links:
        s = Student.query.get(link.student_id)
        if s: students_with_status.append({'student': s, 'status': link.status, 'link': link})
        
    linked_ids = {item["student"].id for item in students_with_status}
    available_students = Student.query.filter(~Student.id.in_(linked_ids)).order_by(Student.full_name).all() if linked_ids else Student.query.order_by(Student.full_name).all()
    linked_chat_ids = {str(chat.chat_id) for chat in d.chats}
    telegram_candidates = [c for c in TelegramChatCandidate.query.order_by(TelegramChatCandidate.last_seen_at.desc()).limit(50).all() if str(c.chat_id) not in linked_chat_ids and c.chat_type in {"group", "supergroup", "channel"}]
    return render_template("direction_detail.html", direction=d, 
                         students_with_status=students_with_status,
                         available_students=available_students,
                         telegram_candidates=telegram_candidates,
                         students_by_status={
                             'pending': [x for x in students_with_status if x['status']=='pending'],
                             'interview': [x for x in students_with_status if x['status']=='interview'],
                             'approved': [x for x in students_with_status if x['status']=='approved'],
                             'active': [x for x in students_with_status if x['status']=='active'],
                             'rejected': [x for x in students_with_status if x['status']=='rejected']
                         })

@directions_bp.route("/<int:did>/lessons", endpoint="lessons")
@login_required
def lessons(did, current_user):
    direction = Direction.query.get_or_404(did)
    lessons_list = Lesson.query.filter_by(direction_id=did).order_by(Lesson.starts_at.asc()).all()
    return render_template("direction_lessons.html", direction=direction, lessons=lessons_list)


@directions_bp.route("/<int:did>/lessons/create", methods=["POST"], endpoint="create_lesson")
@login_required
def create_lesson(did, current_user):
    direction = Direction.query.get_or_404(did)
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    teacher = request.form.get("teacher", "").strip()
    room = request.form.get("room", "").strip()
    starts_at_raw = request.form.get("starts_at", "").strip()
    duration = request.form.get("duration_minutes", type=int) or 90
    capacity = request.form.get("capacity", type=int) or 0

    try:
        starts_at = datetime.strptime(starts_at_raw, "%Y-%m-%dT%H:%M")
    except ValueError:
        flash("Укажите корректные дату и время занятия.", "danger")
        return redirect(url_for("directions.lessons", did=did))

    if not title:
        flash("Название занятия обязательно.", "danger")
        return redirect(url_for("directions.lessons", did=did))
    if duration < 15:
        flash("Продолжительность должна быть не менее 15 минут.", "danger")
        return redirect(url_for("directions.lessons", did=did))
    if capacity < 0:
        flash("Вместимость не может быть отрицательной.", "danger")
        return redirect(url_for("directions.lessons", did=did))

    lesson = Lesson(
        direction_id=direction.id, title=title, description=description, teacher=teacher, room=room,
        starts_at=starts_at, duration_minutes=duration, capacity=capacity, status="scheduled"
    )
    db.session.add(lesson)
    db.session.commit()
    chat_text = (
        f"📚 <b>Новое занятие</b>\n\n<b>{html.escape(title)}</b>\n"
        f"📅 {starts_at.strftime('%d.%m.%Y')} · 🕒 {starts_at.strftime('%H:%M')} · {duration} мин.\n"
        f"📍 {html.escape(room or 'Место не указано')}\n"
        f"👤 {html.escape(teacher or 'Руководитель не указан')}\n\n"
        f"{html.escape(description) if description else 'Без дополнительного описания.'}"
    )
    send_direction_chat(direction.id, chat_text)
    flash(f"Занятие «{title}» добавлено в «{direction.name}».", "success")
    return redirect(url_for("directions.lessons", did=did))


@directions_bp.route("/<int:did>/lessons/<int:lid>/edit", methods=["GET", "POST"], endpoint="edit_lesson")
@login_required
def edit_lesson(did, lid, current_user):
    direction = Direction.query.get_or_404(did)
    lesson = Lesson.query.get_or_404(lid)
    if lesson.direction_id != did:
        flash("Занятие не относится к выбранному направлению.", "danger")
        return redirect(url_for("directions.lessons", did=did))

    if request.method == "POST":
        lesson.title = request.form.get("title", "").strip()
        lesson.description = request.form.get("description", "").strip()
        lesson.teacher = request.form.get("teacher", "").strip()
        lesson.room = request.form.get("room", "").strip()
        try:
            lesson.starts_at = datetime.strptime(request.form.get("starts_at", ""), "%Y-%m-%dT%H:%M")
        except ValueError:
            flash("Укажите корректные дату и время занятия.", "danger")
            return redirect(url_for("directions.edit_lesson", did=did, lid=lid))
        lesson.duration_minutes = request.form.get("duration_minutes", type=int) or 90
        lesson.capacity = request.form.get("capacity", type=int) or 0
        lesson.status = request.form.get("status", "scheduled")
        if lesson.status not in {"scheduled", "completed", "cancelled"}:
            lesson.status = "scheduled"
        if not lesson.title or lesson.duration_minutes < 15 or lesson.capacity < 0:
            flash("Проверьте название, длительность и вместимость занятия.", "danger")
            return redirect(url_for("directions.edit_lesson", did=did, lid=lid))
        db.session.commit()
        chat_text = (
            f"📝 <b>Занятие обновлено</b>\n\n<b>{html.escape(lesson.title)}</b>\n"
            f"📅 {lesson.starts_at.strftime('%d.%m.%Y')} · 🕒 {lesson.starts_at.strftime('%H:%M')} · {lesson.duration_minutes} мин.\n"
            f"📍 {html.escape(lesson.room or 'Место не указано')}\n"
            f"👤 {html.escape(lesson.teacher or 'Руководитель не указан')}\n"
            f"📌 Статус: {html.escape(lesson.status)}"
        )
        send_direction_chat(direction.id, chat_text)
        flash("Занятие обновлено.", "success")
        return redirect(url_for("directions.lessons", did=did))

    return render_template("lesson_form.html", direction=direction, lesson=lesson)


@directions_bp.route("/<int:did>/lessons/<int:lid>/delete", methods=["POST"], endpoint="delete_lesson")
@login_required
def delete_lesson(did, lid, current_user):
    lesson = Lesson.query.get_or_404(lid)
    if lesson.direction_id != did:
        flash("Занятие не относится к выбранному направлению.", "danger")
        return redirect(url_for("directions.lessons", did=did))
    title = lesson.title
    db.session.delete(lesson)
    db.session.commit()
    send_direction_chat(did, f"🗑 <b>Занятие удалено</b>\n\n<b>{html.escape(title)}</b> больше не стоит в расписании направления.")
    flash(f"Занятие «{title}» удалено.", "success")
    return redirect(url_for("directions.lessons", did=did))


@directions_bp.route("/<int:did>/questions", methods=["GET", "POST"], endpoint="manage_questions")
@login_required
def manage_questions(did, current_user):
    d = Direction.query.get_or_404(did)
    
    if request.method == "POST":
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
    return render_template("direction_questions.html", direction=d, questions=questions)

@directions_bp.route("/<int:did>/add_student", methods=["POST"], endpoint="add_existing_student")
@login_required
def add_existing_student(did, current_user):
    direction = Direction.query.get_or_404(did)
    sid = request.form.get("student_id", type=int)
    status = request.form.get("status", DirectionStatus.ACTIVE.value)
    if status not in {x.value for x in DirectionStatus}:
        status = DirectionStatus.ACTIVE.value
    student = Student.query.get(sid) if sid else None
    if not student:
        flash("Выберите существующего студента.", "danger")
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
    db.session.commit()
    flash(f"{student.full_name} добавлен в «{direction.name}».", "success")
    return redirect(url_for("directions.direction_detail", did=did))


@directions_bp.route("/<int:did>/remove/<int:sid>", methods=["POST"])
@login_required
def remove_student(did, sid, current_user):
    direction = Direction.query.get_or_404(did)
    student = Student.query.get_or_404(sid)
    link = db.session.execute(student_directions.select().where(
        (student_directions.c.student_id == sid) & (student_directions.c.direction_id == did)
    )).fetchone()
    if not link:
        flash("Студент уже не состоит в направлении", "warning")
        return redirect(url_for("directions.direction_detail", did=did))
    db.session.execute(student_directions.delete().where(
        (student_directions.c.student_id == sid) & (student_directions.c.direction_id == did)
    ))
    db.session.commit()
    removed_count = remove_student_from_direction_chats(student, direction)
    flash(f"{student.full_name} удалён из «{direction.name}». Удалено из чатов: {removed_count}", "success")
    return redirect(url_for("directions.direction_detail", did=did))

@directions_bp.route("/<int:did>/update_status/<int:sid>", methods=["POST"])
@login_required
def update_student_status(did, sid, current_user):
    new_status = request.form.get("new_status")
    link = db.session.execute(student_directions.select().where(
        (student_directions.c.student_id == sid) & (student_directions.c.direction_id == did)
    )).fetchone()
    
    if link:
        old_status = link.status
        db.session.execute(student_directions.update().where(
            (student_directions.c.student_id == sid) & (student_directions.c.direction_id == did)
        ).values(status=new_status))
        db.session.commit()
        
        student = Student.query.get(sid)
        direction = Direction.query.get(did)
        
        templates = {
            'approved': 'direction_approved', 'rejected': 'direction_rejected',
            'interview': 'interview_invite', 'active': 'activation'
        }
        if new_status in templates:
            send_notification_by_template(student, templates[new_status], 
                {"direction": f"{direction.icon or '✦'} {direction.name}", "student_name": student.full_name,
                 "date": "уточняется", "location": "уточняется"})
        if new_status == DirectionStatus.APPROVED.value:
            send_direction_invites(student, direction)
        elif new_status == DirectionStatus.REJECTED.value:
            remove_student_from_direction_chats(student, direction)
                
        flash(f"Статус изменен с {old_status} на {new_status}", "success")
    return redirect(url_for("directions.direction_detail", did=did))


@directions_bp.route("/<int:did>/lessons/<int:lid>/publish", methods=["POST"], endpoint="publish_lesson")
@login_required
def publish_lesson(did, lid, current_user):
    direction = Direction.query.get_or_404(did)
    lesson = Lesson.query.get_or_404(lid)
    if lesson.direction_id != did:
        flash("Занятие не относится к выбранному направлению.", "danger")
        return redirect(url_for("directions.lessons", did=did))
    chat_text = (
        f"📚 <b>Занятие</b>\n\n<b>{html.escape(lesson.title)}</b>\n"
        f"📅 {lesson.starts_at.strftime('%d.%m.%Y')} · 🕒 {lesson.starts_at.strftime('%H:%M')} · {lesson.duration_minutes} мин.\n"
        f"📍 {html.escape(lesson.room or 'Место не указано')}\n"
        f"👤 {html.escape(lesson.teacher or 'Руководитель не указан')}\n\n"
        f"{html.escape(lesson.description) if lesson.description else 'Без дополнительного описания.'}"
    )
    sent = send_direction_chat(direction.id, chat_text)
    if sent:
        flash(f"Занятие опубликовано в {sent} чат(ах) направления.", "success")
    else:
        flash("Не удалось отправить занятие. Нажмите «Тест» у чата и проверьте права бота в Telegram.", "danger")
    return redirect(url_for("directions.lessons", did=did))

@quotas_bp.route("/create", methods=["GET", "POST"], endpoint="create_quota")
@login_required
def create_quota(current_user):
    if request.method == "GET":
        directions = Direction.query.order_by(Direction.name.asc()).all()
        return render_template("quotas_create.html", directions=directions)

    t = request.form.get("title", "").strip()
    desc = request.form.get("description", "").strip()
    loc = request.form.get("location", "").strip()
    tr = request.form.get("time_range", "").strip()
    dc = request.form.get("dress_code", "").strip()
    func = request.form.get("functionality", "").strip()
    places = request.form.get("total_places", type=int)
    dids = request.form.getlist("direction_ids", type=int)
    raw_chat_targets = request.form.getlist("chat_targets")

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

    valid_dids = [d.id for d in Direction.query.filter(Direction.id.in_(dids)).all()]
    if not valid_dids:
        flash("Выберите хотя бы одно существующее направление.", "danger")
        return redirect(url_for("quotas.create_quota"))

    selected_targets = []
    selected_by_direction = {}
    for raw in raw_chat_targets:
        try:
            did_s, cid_s = raw.split(":", 1)
            did = int(did_s)
        except (ValueError, TypeError):
            continue
        if did in valid_dids and cid_s.strip():
            selected_targets.append((did, cid_s.strip()))
            selected_by_direction.setdefault(did, set()).add(cid_s.strip())

    # Special rule: any quota assigned to Student Council is broadcast to ALL
    # active Student Council chats, regardless of individual chat checkboxes.
    for direction in Direction.query.filter(Direction.id.in_(valid_dids)).all():
        if is_student_council_direction(direction):
            for chat in DirectionChat.query.filter_by(direction_id=direction.id, is_active=True).all():
                selected_targets.append((direction.id, str(chat.chat_id)))

    # Deduplicate targets while preserving order.
    selected_targets = list(dict.fromkeys(selected_targets))

    if not selected_targets:
        flash("Выберите хотя бы один Telegram-чат для публикации.", "danger")
        return redirect(url_for("quotas.create_quota"))

    q = EventQuota(
        event_title=t, event_description=desc, location=loc, time_range=tr,
        dress_code=dc, functionality=func, total_places=places
    )
    for dd in days:
        q.days.append(EventDay(date=dd["date"], daily_places=dd["places"]))

    db.session.add(q)
    db.session.flush()
    set_quota_directions(q.id, valid_dids)
    set_quota_chat_targets(q.id, selected_targets)
    db.session.commit()

    event_chat_text = (
        f"🔥 <b>{html.escape(t)}</b>\n\n"
        f"📅 <b>Даты:</b> {', '.join(d['date'].strftime('%d.%m.%Y') for d in sorted(days, key=lambda x: x['date']))}\n"
        f"🕒 <b>Время:</b> {html.escape(tr or 'уточняется')}\n"
        f"📍 <b>Место:</b> {html.escape(loc or 'уточняется')}\n"
        f"👥 <b>Мест:</b> {places}\n\n"
        f"{html.escape(desc) if desc else 'Без дополнительного описания.'}"
    )
    delivered = 0
    for _did, _chat_id in selected_targets:
        if _send_tg(_chat_id, event_chat_text):
            delivered += 1
    logger.info("Quota #%s publication: %s/%s selected chat(s) delivered", q.id, delivered, len(selected_targets))

    try:
        targets = set()
        for d in q.directions:
            for s in d.students:
                targets.add(s)
        ids = [s.tg_id for s in targets if s.tg_id and s.tg_id > 0]
        if ids:
            db_str = "\n".join([f"📍 {d['date'].strftime('%d.%m.%Y')}" for d in sorted(days, key=lambda x: x["date"])])
            fl = "\n".join([f"📍 {l.strip()}" for l in func.split("\n") if l.strip()])
            msg = (
                f"🔥 <b>{t}</b>\n\n<b>Даты:</b>\n{db_str}\n🗓 <b>Время:</b> {tr}\n"
                f"📍 <b>Место:</b> {loc}\n\n🛠 <b>Функционал:</b>\n{fl or '—'}\n\n"
                f"👕 <b>Одежда:</b> {dc or '—'}\n\nВыберите удобную дату:"
            )

            keyboard_rows = []
            for day_data in sorted(days, key=lambda x: x["date"]):
                date_str = day_data["date"].strftime("%d.%m")
                callback_data = f"join_day_{q.id}_{day_data['date'].strftime('%Y-%m-%d')}"
                keyboard_rows.append([{"text": f"📅 {date_str}", "callback_data": callback_data}])

            keyboard_json = json.dumps({"inline_keyboard": keyboard_rows})

            def send(ids, msg, kb_json):
                for uid in ids:
                    try:
                        requests.post(
                            f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendMessage",
                            json={
                                "chat_id": uid, "text": msg, "parse_mode": "HTML",
                                "reply_markup": json.loads(kb_json)
                            },
                            timeout=10,
                        )
                    except Exception:
                        logger.exception("Ошибка отправки уведомления о квоте пользователю %s", uid)

            threading.Thread(target=send, args=(ids, msg, keyboard_json), daemon=True).start()
    except Exception:
        logger.exception("Ошибка рассылки о созданной квоте #%s", q.id)

    flash(f"«{t}» создано!", "success")
    return redirect(url_for("quotas.quotas_list"))

@quotas_bp.route("/<int:qid>/publish", methods=["POST"], endpoint="publish_quota")
@login_required
def publish_quota(qid, current_user):
    quota = EventQuota.query.get_or_404(qid)
    event_chat_text = (
        f"🔥 <b>{html.escape(quota.event_title)}</b>\n\n"
        f"📅 <b>Даты:</b> {', '.join(day.date.strftime('%d.%m.%Y') for day in sorted(quota.days, key=lambda x: x.date))}\n"
        f"🕒 <b>Время:</b> {html.escape(quota.time_range or 'уточняется')}\n"
        f"📍 <b>Место:</b> {html.escape(quota.location or 'уточняется')}\n"
        f"👥 <b>Мест:</b> {quota.total_places}\n\n"
        f"{html.escape(quota.event_description) if quota.event_description else 'Без дополнительного описания.'}"
    )
    sent = 0
    targets = get_quota_chat_targets(qid)
    for target in targets:
        if _send_tg(target.chat_id, event_chat_text):
            sent += 1
    if sent:
        flash(f"Мероприятие опубликовано в {sent} чат(ах) направлений.", "success")
    else:
        flash("Не удалось отправить мероприятие в чаты. Проверьте подключённые чаты и кнопку «Тест».", "danger")
    return redirect(url_for("quotas.quotas_list"))

@quotas_bp.route("/")
@login_required
def quotas_list(current_user):
    return render_template("quotas.html", quotas=EventQuota.query.all(), directions=Direction.query.all())

@quotas_bp.route("/participants/<int:qid>", endpoint="quota_participants")
@login_required
def quota_participants(qid, current_user):
    return render_template("quota_participants.html", quota=EventQuota.query.get_or_404(qid))

@quotas_bp.route("/mark/<int:pid>/<st>", endpoint="mark_attendance")
@login_required
def mark_att(pid, st, current_user):
    p = DayParticipation.query.get_or_404(pid); p.status = st; db.session.commit()
    flash("Статус обновлен", "success"); return redirect(url_for("quotas.quota_participants", qid=p.day.quota_id))

def create_app():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = settings.PEOPLE_DATABASE_URI
    app.config["SQLALCHEMY_BINDS"] = {
        "events": settings.EVENTS_DATABASE_URI,
        "lessons": settings.LESSONS_DATABASE_URI,
        "stats": settings.STATS_DATABASE_URI,
        "system": settings.SYSTEM_DATABASE_URI,
    }
    app.config["SECRET_KEY"] = settings.SECRET_KEY
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = False
    db.init_app(app)
    set_flask_app(app)
    app.register_blueprint(auth_bp); app.register_blueprint(admin_bp)
    app.register_blueprint(directions_bp); app.register_blueprint(quotas_bp)
    app.register_blueprint(stats_bp)
    return app