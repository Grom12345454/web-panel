from functools import wraps
from datetime import datetime
import requests, threading, json
from flask import Blueprint, Flask, flash, redirect, render_template, request, session, url_for, jsonify
from config import settings
from database import db, verify_password, Student, User, Direction, EventQuota, EventDay, DayParticipation, DirectionQuestion, StudentStatus, student_directions, quota_directions

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")
admin_bp = Blueprint("admin", __name__)
directions_bp = Blueprint("directions", __name__, url_prefix="/directions")
quotas_bp = Blueprint("quotas", __name__, url_prefix="/quotas")
api_bp = Blueprint("api", __name__, url_prefix="/api")

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session: return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated

def _send_tg(chat_id, text):
    try:
        requests.post(f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendMessage", 
                      json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=5)
    except: pass

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
def dashboard():
    stats = {
        "total": Student.query.count(),
        "pending": Student.query.filter_by(status='pending').count(),
        "approved": Student.query.filter_by(status='approved').count(),
        "active": Student.query.filter_by(status='active').count(),
        "free": sum(d.available_places() for q in EventQuota.query.all() for d in q.days)
    }
    dirs = Direction.query.all()
    dir_stats = []
    for d in dirs:
        dir_stats.append({
            'id': d.id, 'name': d.name, 'icon': d.icon, 'color': d.color, 
            'count': len(d.students),
            'has_questions': len(d.questions) > 0
        })
    return render_template("dashboard.html", stats=stats, directions=dirs, direction_stats=dir_stats)

@admin_bp.route("/students", endpoint="students_list")
@login_required
def students_list():
    f = request.args.get('status', 'all')
    q = Student.query.order_by(Student.created_at.desc())
    if f != 'all': q = q.filter_by(status=f)
    
    stats = {
        'total': Student.query.count(), 'pending': Student.query.filter_by(status='pending').count(),
        'approved': Student.query.filter_by(status='approved').count(), 
        'active': Student.query.filter_by(status='active').count(), 'rejected': Student.query.filter_by(status='rejected').count()
    }
    return render_template("students.html", students=q.all(), status_filter=f, stats=stats)

@admin_bp.route("/students/<int:sid>/approve", methods=["POST"], endpoint="approve_student")
@login_required
def approve_student(sid):
    s = Student.query.get_or_404(sid)
    s.status = 'approved'; db.session.commit()
    _send_tg(s.tg_id, f"✅ Заявка одобрена!\nНаправления:\n" + "\n".join([f"• {d.name}" for d in s.directions]))
    flash("Одобрено", "success"); return redirect(url_for("admin.students_list"))

@admin_bp.route("/students/<int:sid>/reject", methods=["POST"], endpoint="reject_student")
@login_required
def reject_student(sid):
    s = Student.query.get_or_404(sid)
    s.status = 'rejected'; db.session.commit()
    _send_tg(s.tg_id, "❌ Заявка отклонена.")
    flash("Отклонено", "warning"); return redirect(url_for("admin.students_list"))

@admin_bp.route("/students/<int:sid>/activate", methods=["POST"], endpoint="activate_student")
@login_required
def activate_student(sid):
    s = Student.query.get_or_404(sid)
    s.status = 'active'; db.session.commit()
    _send_tg(s.tg_id, f"🎉 Вы активны! Теперь вы можете записываться на мероприятия.")
    flash("Активирован", "success"); return redirect(url_for("admin.students_list"))

@directions_bp.route("/")
@login_required
def directions_list():
    return render_template("directions.html", directions=Direction.query.all())

@directions_bp.route("/<int:did>")
@login_required
def direction_detail(did):
    d = Direction.query.get_or_404(did)
    return render_template("direction_detail.html", direction=d, students=d.students, 
                           students_by_status={'all': d.students, 'active': [s for s in d.students if s.status=='active'],
                                               'approved': [s for s in d.students if s.status=='approved'],
                                               'pending': [s for s in d.students if s.status=='pending']})

@directions_bp.route("/<int:did>/questions", methods=["GET", "POST"], endpoint="manage_questions")
@login_required
def manage_questions(did):
    d = Direction.query.get_or_404(did)
    
    if request.method == "POST":
        action = request.form.get("action")
        
        if action == "add":
            text = request.form.get("question_text", "").strip()
            if text:
                max_order = db.session.query(db.func.max(DirectionQuestion.sort_order)).filter_by(direction_id=did).scalar() or 0
                q = DirectionQuestion(direction_id=did, question_text=text, sort_order=max_order + 1)
                db.session.add(q)
                db.session.commit()
                flash("Вопрос добавлен", "success")
                
        elif action == "delete":
            qid = request.form.get("question_id", type=int)
            q = DirectionQuestion.query.get(qid)
            if q and q.direction_id == did:
                db.session.delete(q)
                db.session.commit()
                flash("Вопрос удален", "success")
                
        return redirect(url_for("directions.manage_questions", did=did))
    
    return render_template("direction_questions.html", direction=d, questions=d.questions)

@directions_bp.route("/<int:did>/remove_student/<int:sid>", methods=["POST"], endpoint="remove_student")
@login_required
def remove_student(did, sid):
    db.session.execute(student_directions.delete().where((student_directions.c.student_id==sid)&(student_directions.c.direction_id==did)))
    db.session.commit(); flash("Удален", "success"); return redirect(url_for("directions.direction_detail", did=did))

# ✅ КВОТЫ С ВЫБОРОМ ДАТЫ В РАССЫЛКЕ
@quotas_bp.route("/")
@login_required
def quotas_list():
    return render_template("quotas.html", quotas=EventQuota.query.all(), directions=Direction.query.all())

@quotas_bp.route("/create", methods=["POST"], endpoint="create_quota")
@login_required
def create_quota():
    t = request.form.get("title","").strip()
    desc = request.form.get("description","").strip()
    loc = request.form.get("location","").strip()
    tr = request.form.get("time_range","").strip()
    dc = request.form.get("dress_code","").strip()
    func = request.form.get("functionality","").strip()
    
    places = request.form.get("total_places", type=int)
    dids = request.form.getlist("direction_ids", type=int)
    
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
    
    q = EventQuota(
        event_title=t, event_description=desc, location=loc, time_range=tr, 
        dress_code=dc, functionality=func, total_places=places
    )
    
    for did in dids:
        d = Direction.query.get(did)
        if d: q.directions.append(d)
    for dd in days: q.days.append(EventDay(date=dd["date"], daily_places=dd["places"]))
    
    db.session.add(q); db.session.commit()
    
    # ✅ РАССЫЛКА С КНОПКАМИ ДЛЯ КАЖДОЙ ДАТЫ
    try:
        targets = set()
        for d in q.directions:
            for s in d.students: targets.add(s)
        ids = [s.tg_id for s in targets]
        
        if ids:
            db_str = "\n".join([f"📍 {d['date'].strftime('%d.%m.%Y')}" for d in sorted(days, key=lambda x:x['date'])])
            fl = "\n".join([f"📍 {l.strip()}" for l in func.split('\n') if l.strip()])
            
            msg = (f"🔥 <b>{t}</b>\n\n<b>Даты:</b>\n{db_str}\n🗓 <b>Время:</b> {tr}\n"
                   f" <b>Место:</b> {loc}\n\n🛠 <b>Функционал:</b>\n{fl}\n\n"
                   f"👕 <b>Одежда:</b> {dc}\n\nВыберите удобную дату:")
            
            # Генерируем кнопки для каждого дня
            keyboard_rows = []
            for day_data in sorted(days, key=lambda x: x['date']):
                date_str = day_data['date'].strftime('%d.%m')
                callback_data = f"join_day_{q.id}_{day_data['date'].strftime('%Y-%m-%d')}"
                keyboard_rows.append([{"text": f"📅 {date_str}", "callback_data": callback_data}])
            
            keyboard_json = json.dumps({"inline_keyboard": keyboard_rows})
            
            def send(ids, msg, kb_json):
                for uid in ids:
                    try: 
                        requests.post(f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendMessage", 
                                      json={"chat_id":uid,"text":msg,"parse_mode":"HTML","reply_markup":json.loads(kb_json)}, 
                                      timeout=10)
                    except Exception as e: print(f"Ошибка отправки {uid}: {e}")
            
            threading.Thread(target=send, args=(ids, msg, keyboard_json), daemon=True).start()
    except Exception as e: print(f"Ошибка рассылки: {e}")
    
    flash(f"«{t}» создано!", "success"); return redirect(url_for("quotas.quotas_list"))

@quotas_bp.route("/participants/<int:qid>", endpoint="quota_participants")
@login_required
def quota_participants(qid):
    return render_template("quota_participants.html", quota=EventQuota.query.get_or_404(qid))

# ✅ ИСПРАВЛЕННЫЙ МАРШРУТ ОТМЕТКИ ЯВКИ
@quotas_bp.route("/mark/<int:pid>/<st>", endpoint="mark_attendance")
@login_required
def mark_att(pid, st):
    p = DayParticipation.query.get_or_404(pid)
    p.status = st; db.session.commit()
    flash("Статус обновлен", "success")
    return redirect(url_for("quotas.quota_participants", qid=p.day.quota_id))

def create_app():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = settings.DATABASE_URI
    app.config["SECRET_KEY"] = settings.SECRET_KEY
    db.init_app(app)
    app.register_blueprint(auth_bp); app.register_blueprint(admin_bp)
    app.register_blueprint(directions_bp); app.register_blueprint(quotas_bp)
    app.register_blueprint(api_bp)
    return app