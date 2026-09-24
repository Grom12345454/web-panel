from functools import wraps
from datetime import datetime
import requests, threading, json, os, logging, queue
from flask import Blueprint, Flask, flash, redirect, render_template, request, session, url_for, jsonify
from config import settings
from database import db, verify_password, Student, User, Direction, EventQuota, EventDay, DayParticipation, DirectionQuestion, StudentLeadership, StudentStatus, NotificationTemplate, student_directions, quota_directions, UserRole

logger = logging.getLogger(__name__)

# ✅ ПОТОКОБЕЗОПАСНАЯ ОЧЕРЕДЬ ДЛЯ УВЕДОМЛЕНИЙ
notification_queue = queue.Queue()
_flask_app_instance = None

def set_flask_app(app):
    global _flask_app_instance
    _flask_app_instance = app

def notification_worker():
    """Фоновый поток ТОЛЬКО для отправки HTTP-запросов к Telegram"""
    while True:
        try:
            task = notification_queue.get(timeout=1)
            if task is None: break
            
            chat_id, text = task
            
            # ✅ НИКАКИХ ОБРАЩЕНИЙ К БАЗЕ ДАННЫХ В ФОНОВОМ ПОТОКЕ!
            try:
                resp = requests.post(
                    f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendMessage",
                    json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
                    timeout=10
                )
                if resp.status_code == 200:
                    logger.info(f"Sent notification to {chat_id}")
                else:
                    logger.error(f"TG API error: {resp.status_code}")
            except Exception as e:
                logger.error(f"Notification send error: {e}")
                
        except queue.Empty:
            continue
        except Exception as e:
            logger.error(f"Worker error: {e}", exc_info=True)

worker_thread = threading.Thread(target=notification_worker, daemon=True, name="NotificationWorker")
worker_thread.start()

def _send_tg(chat_id, text):
    if not chat_id or chat_id == 0: return
    try:
        requests.post(f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendMessage", 
                      json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=5)
    except: pass

def send_notification_by_template(student, template_key, variables):
    """Подготавливает текст в текущем потоке и кладет в очередь только готовое сообщение"""
    try:
        nt = NotificationTemplate.query.filter_by(key=template_key).first()
        if not nt:
            logger.error(f"Template {template_key} not found")
            return False
            
        text = nt.template_text
        for var_name, var_value in variables.items():
            text = text.replace(f"{{{var_name}}}", str(var_value))
            
        if student.tg_id and student.tg_id != 0:
            # ✅ В ОЧЕРЕДЬ ПОПАДАЕТ ТОЛЬКО ГОТОВЫЙ ТЕКСТ И ID
            notification_queue.put((student.tg_id, text))
            return True
        else:
            logger.warning(f"Student {student.id} has no TG ID")
            return False
    except Exception as e:
        logger.error(f"Error preparing notification: {e}")
        return False

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")
admin_bp = Blueprint("admin", __name__)
directions_bp = Blueprint("directions", __name__, url_prefix="/directions")
quotas_bp = Blueprint("quotas", __name__, url_prefix="/quotas")
api_bp = Blueprint("api", __name__, url_prefix="/api")

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session: 
            return redirect(url_for("auth.login"))
        user = User.query.get(session["user_id"])
        if not user: 
            session.clear()
            return redirect(url_for("auth.login"))
        return f(*args, current_user=user, **kwargs)
    return decorated

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = User.query.filter_by(email=request.form["email"]).first()
        if user and verify_password(request.form["password"], user.password_hash):
            session["user_id"] = user.id
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
        "total": Student.query.count(),
        "pending": Student.query.filter_by(status='pending').count(),
        "approved": Student.query.filter_by(status='approved').count(),
        "active": Student.query.filter_by(status='active').count(),
        "free": sum(d.available_places() for q in EventQuota.query.all() for d in q.days)
    }
    dirs = Direction.query.all()
    dir_stats = [{'id': d.id, 'name': d.name, 'icon': d.icon, 'color': d.color, 
                  'count': len(d.students), 'has_questions': len(d.questions) > 0} for d in dirs]
    return render_template("dashboard.html", stats=stats, directions=dirs, direction_stats=dir_stats)

@admin_bp.route("/leadership", methods=["GET", "POST"])
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
                # ✅ ЧИТАЕМ ДАННЫЕ ДО ЗАПИСИ, ЧТОБЫ НЕ БЛОКИРОВАТЬ БД
                direction = Direction.query.get(did)
                student = Student.query.get(sid)
                
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
                        extra_data=json.dumps({"source": "leadership_assignment"})
                    ))
                    
                db.session.commit()
                
                # ✅ ОТПРАВЛЯЕМ УЖЕ ПОДГОТОВЛЕННОЕ СООБЩЕНИЕ
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
                # ✅ ЧИТАЕМ ДАННЫЕ ДО УДАЛЕНИЯ
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
    students = Student.query.filter_by(status='active').all()
    directions = Direction.query.all()
    
    return render_template("leadership.html", 
                         leaders=leaders, 
                         students=students, 
                         directions=directions)

@admin_bp.route("/bot_logs")
@login_required
def bot_logs(current_user):
    if current_user.role != UserRole.SUPER_ADMIN.value:
        flash("Доступ запрещен", "danger")
        return redirect(url_for("admin.dashboard"))
    
    logs = []
    log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.log")
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            logs = f.readlines()[-100:]
    except FileNotFoundError:
        logs = ["Файл логов не найден."]
    
    return render_template("bot_logs.html", logs=logs)

@admin_bp.route("/students", endpoint="students_list")
@login_required
def students_list(current_user):
    f = request.args.get('status', 'all')
    q = Student.query.order_by(Student.created_at.desc())
    if f != 'all': q = q.filter_by(status=f)
    
    stats = {'total': q.count()}
    return render_template("students.html", students=q.all(), status_filter=request.args.get('status', 'all'), stats=stats)

@admin_bp.route("/students/<int:sid>/approve", methods=["POST"], endpoint="approve_student")
@login_required
def approve_student(sid, current_user):
    s = Student.query.get_or_404(sid)
    s.status = 'approved'; db.session.commit()
    _send_tg(s.tg_id, f"✅ Заявка одобрена!\nНаправления:\n" + "\n".join([f"• {d.name}" for d in s.directions]))
    flash("Одобрено", "success"); return redirect(url_for("admin.students_list"))

@admin_bp.route("/students/<int:sid>/reject", methods=["POST"], endpoint="reject_student")
@login_required
def reject_student(sid, current_user):
    s = Student.query.get_or_404(sid)
    s.status = 'rejected'; db.session.commit()
    _send_tg(s.tg_id, "❌ Заявка отклонена.")
    flash("Отклонено", "warning"); return redirect(url_for("admin.students_list"))

@admin_bp.route("/students/<int:sid>/activate", methods=["POST"], endpoint="activate_student")
@login_required
def activate_student(sid, current_user):
    s = Student.query.get_or_404(sid)
    if s.status == 'active':
        flash("Студент уже активен", "info")
        return redirect(url_for("admin.students_list"))
        
    s.status = 'active'
    db.session.commit()
    
    dirs_list = "\n".join([f"• {d.icon} {d.name}" for d in s.directions])
    
    send_notification_by_template(
        s,
        "activation",
        {"student_name": s.full_name, "directions": dirs_list}
    )
    
    flash(f"Студент {s.full_name} активирован", "success")
    return redirect(url_for("admin.students_list"))

@directions_bp.route("/", endpoint="directions_list")
@login_required
def directions_list(current_user):
    return render_template("directions.html", directions=Direction.query.all())

@directions_bp.route("/<int:did>")
@login_required
def direction_detail(did, current_user):
    d = Direction.query.get_or_404(did)
    return render_template("direction_detail.html", direction=d, students=d.students, 
                           students_by_status={'all': d.students, 'active': [s for s in d.students if s.status=='active'],
                                               'approved': [s for s in d.students if s.status=='approved'],
                                               'pending': [s for s in d.students if s.status=='pending']})

@directions_bp.route("/<int:did>/schedule_interview", methods=["POST"], endpoint="schedule_direction_interview")
@login_required
def schedule_direction_interview(did, current_user):
    d = Direction.query.get_or_404(did)
    sid = request.form.get("student_id", type=int)
    
    if not sid:
        flash("Ошибка: не указан студент", "danger")
        return redirect(url_for("directions.direction_detail", did=did))

    s = Student.query.get_or_404(sid)
    
    if s.status != 'pending':
        flash("Собеседование можно назначить только для ожидающих заявок!", "warning")
        return redirect(url_for("directions.direction_detail", did=did))

    int_date_str = request.form.get("interview_date") 
    int_loc = request.form.get("interview_location", "").strip()
    
    if not int_date_str or not int_loc:
        flash("Заполните дату/время и место собеседования!", "danger")
        return redirect(url_for("directions.direction_detail", did=did))
        
    try:
        s.interview_date = datetime.fromisoformat(int_date_str)
        s.interview_location = int_loc
        db.session.commit()
        
        date_fmt = s.interview_date.strftime("%d.%m.%Y в %H:%M")
        
        send_notification_by_template(
            s,
            "interview_invite",
            {
                "student_name": s.full_name,
                "direction": d.name,
                "date": date_fmt,
                "location": s.interview_location
            }
        )
        
        flash(f"Собеседование назначено на {date_fmt}", "success")
        
    except Exception as e:
        flash(f"Ошибка при сохранении: {e}", "danger")
        
    return redirect(url_for("directions.direction_detail", did=did))

@directions_bp.route("/<int:did>/questions", methods=["GET", "POST"], endpoint="manage_questions")
@login_required
def manage_questions(did, current_user):
    d = Direction.query.get_or_404(did)
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            text = request.form.get("question_text", "").strip()
            if text:
                max_order = db.session.query(db.func.max(DirectionQuestion.sort_order)).filter_by(direction_id=did).scalar() or 0
                q = DirectionQuestion(direction_id=did, question_text=text, sort_order=max_order + 1)
                db.session.add(q); db.session.commit(); flash("Вопрос добавлен", "success")
        elif action == "delete":
            qid = request.form.get("question_id", type=int)
            q = DirectionQuestion.query.get(qid)
            if q and q.direction_id == did:
                db.session.delete(q); db.session.commit(); flash("Вопрос удален", "success")
        return redirect(url_for("directions.manage_questions", did=did))
    return render_template("direction_questions.html", direction=d, questions=d.questions)

@directions_bp.route("/<int:did>/remove_student/<int:sid>", methods=["POST"], endpoint="remove_student")
@login_required
def remove_student(did, sid, current_user):
    db.session.execute(student_directions.delete().where((student_directions.c.student_id==sid)&(student_directions.c.direction_id==did)))
    db.session.commit(); flash("Удален", "success"); return redirect(url_for("directions.direction_detail", did=did))

@quotas_bp.route("/create", methods=["GET", "POST"], endpoint="create_quota")
@login_required
def create_quota(current_user):
    if request.method == "GET":
        return render_template("quotas_create.html", directions=Direction.query.all())
        
    t = request.form.get("title","").strip(); desc = request.form.get("description","").strip()
    loc = request.form.get("location","").strip(); tr = request.form.get("time_range","").strip()
    dc = request.form.get("dress_code","").strip(); func = request.form.get("functionality","").strip()
    places = request.form.get("total_places", type=int); dids = request.form.getlist("direction_ids", type=int)
    
    days = []; i=0
    while True:
        ds = request.form.get(f"day_date_{i}"); pl = request.form.get(f"day_places_{i}", type=int)
        if not ds or not pl: break
        try: days.append({"date": datetime.strptime(ds, "%Y-%m-%d"), "places": pl})
        except: pass
        i+=1
        
    if not all([t, dids, days, places]): 
        flash("Заполните название, направления, даты и количество мест!", "danger")
        return redirect(url_for("quotas.quotas_list"))
    
    q = EventQuota(event_title=t, event_description=desc, location=loc, time_range=tr, dress_code=dc, functionality=func, total_places=places)
    for did in dids:
        d = Direction.query.get(did)
        if d: q.directions.append(d)
    for dd in days: q.days.append(EventDay(date=dd["date"], daily_places=dd["places"]))
    
    db.session.add(q); db.session.commit()
    
    try:
        targets = set()
        for d in q.directions:
            for s in d.students: targets.add(s)
        ids = [s.tg_id for s in targets]
        if ids:
            db_str = "\n".join([f"📍 {d['date'].strftime('%d.%m.%Y')}" for d in sorted(days, key=lambda x:x['date'])])
            fl = "\n".join([f" {l.strip()}" for l in func.split('\n') if l.strip()])
            msg = (f"🔥 <b>{t}</b>\n\n<b>Даты:</b>\n{db_str}\n🗓 <b>Время:</b> {tr}\n"
                   f"📍 <b>Место:</b> {loc}\n\n🛠 <b>Функционал:</b>\n{fl}\n\n"
                   f"👕 <b>Одежда:</b> {dc}\n\nВыберите удобную дату:")
            
            keyboard_rows = []
            for day_data in sorted(days, key=lambda x: x['date']):
                date_str = day_data['date'].strftime('%d.%m')
                callback_data = f"join_day_{q.id}_{day_data['date'].strftime('%Y-%m-%d')}"
                keyboard_rows.append([{"text": f" {date_str}", "callback_data": callback_data}])
            
            keyboard_json = json.dumps({"inline_keyboard": keyboard_rows})
            def send(ids, msg, kb_json):
                for uid in ids:
                    try: requests.post(f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendMessage", 
                                      json={"chat_id":uid,"text":msg,"parse_mode":"HTML","reply_markup":json.loads(kb_json)}, timeout=10)
                    except: pass
            threading.Thread(target=send, args=(ids, msg, keyboard_json), daemon=True).start()
    except Exception as e: print(f"Ошибка рассылки: {e}")
    
    flash(f"«{t}» создано!", "success"); return redirect(url_for("quotas.quotas_list"))

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
    app.config["SQLALCHEMY_DATABASE_URI"] = settings.DATABASE_URI
    app.config["SECRET_KEY"] = settings.SECRET_KEY
    db.init_app(app)
    
    set_flask_app(app)
    
    app.register_blueprint(auth_bp); app.register_blueprint(admin_bp)
    app.register_blueprint(directions_bp); app.register_blueprint(quotas_bp)
    app.register_blueprint(api_bp)
    return app