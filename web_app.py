from functools import wraps
from datetime import datetime
import requests
import threading
from flask import Blueprint, Flask, flash, redirect, render_template, request, session, url_for, jsonify
from config import settings
from database import db, verify_password, Student, User, Direction, EventQuota, EventDay, DayParticipation, VolunteerGroup, StudentStatus, student_directions, quota_directions

auth_bp = Blueprint("auth", __name__)
admin_bp = Blueprint("admin", __name__)
directions_bp = Blueprint("directions", __name__)
quotas_bp = Blueprint("quotas", __name__)
api_bp = Blueprint("api", __name__)

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated

# Вспомогательная функция для синхронной отправки
def _send_tg_message(chat_id: int, text: str):
    try:
        url = f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML"
        }, timeout=5)
    except Exception as e:
        print(f"⚠️ Ошибка отправки уведомления: {e}")

# --- AUTH ROUTES ---
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

# --- DASHBOARD ---
@admin_bp.route("/")
@login_required
def dashboard():
    stats = {
        "total_students": Student.query.count(),
        "active_participants": Student.query.filter_by(status=StudentStatus.ACTIVE.value).count(),
        "free_places": sum(d.available_places() for q in EventQuota.query.all() for d in q.days),
        "pending_apps": Student.query.filter_by(status=StudentStatus.PENDING.value).count(),
        "approved_apps": Student.query.filter_by(status=StudentStatus.APPROVED.value).count()
    }
    directions = Direction.query.all()
    direction_stats = []
    for d in directions:
        direction_stats.append({
            'id': d.id, 'name': d.name, 'code': d.code, 'icon': d.icon or '',
            'color': d.color or 'blue', 
            'students_count': len(d.students),
            'active_count': len([s for s in d.students if s.status == StudentStatus.ACTIVE.value]),
            'quotas_count': len(d.quotas)
        })
    return render_template("dashboard.html", stats=stats, directions=directions, direction_stats=direction_stats)

# --- STUDENTS MANAGEMENT ---
@admin_bp.route("/students")
@login_required
def students_list():
    status_filter = request.args.get('status', 'all')
    query = Student.query.order_by(Student.created_at.desc())
    if status_filter != 'all':
        query = query.filter_by(status=status_filter)
    students = query.all()
    
    stats = {
        'total': Student.query.count(),
        'pending': Student.query.filter_by(status='pending').count(),
        'approved': Student.query.filter_by(status='approved').count(),
        'active': Student.query.filter_by(status='active').count(),
        'rejected': Student.query.filter_by(status='rejected').count()
    }
    return render_template("students.html", students=students, status_filter=status_filter, stats=stats)

@admin_bp.route("/students/<int:student_id>/approve", methods=["POST"])
@login_required
def approve_student(student_id):
    student = Student.query.get_or_404(student_id)
    student.status = StudentStatus.APPROVED.value
    db.session.commit()
    
    dirs = "\n".join([f"• {d.name}" for d in student.directions])
    _send_tg_message(student.tg_id, f"✅ Заявка одобрена!\nНаправления:\n{dirs}")
    
    flash("Студент одобрен", "success")
    return redirect(url_for("admin.students_list"))

@admin_bp.route("/students/<int:student_id>/reject", methods=["POST"])
@login_required
def reject_student(student_id):
    student = Student.query.get_or_404(student_id)
    student.status = StudentStatus.REJECTED.value
    db.session.commit()
    
    _send_tg_message(student.tg_id, "❌ Заявка отклонена.")
    
    flash("Заявка отклонена", "warning")
    return redirect(url_for("admin.students_list"))

@admin_bp.route("/students/<int:student_id>/activate", methods=["POST"])
@login_required
def activate_student(student_id):
    student = Student.query.get_or_404(student_id)
    student.status = StudentStatus.ACTIVE.value
    db.session.commit()
    
    grp = student.volunteer_group.name if student.volunteer_group else "отряд"
    _send_tg_message(student.tg_id, f"🎉 Вы активны! Зачислены в {grp}.")
    
    flash("Студент активирован", "success")
    return redirect(url_for("admin.students_list"))

# --- DIRECTIONS ---
@directions_bp.route("/directions")
@login_required
def directions_list():
    return render_template("directions.html", directions=Direction.query.all())

@directions_bp.route("/directions/<int:direction_id>")
@login_required
def direction_detail(direction_id):
    direction = Direction.query.get_or_404(direction_id)
    students = direction.students
    students_by_status = {
        'all': students,
        'active': [s for s in students if s.status == 'active'],
        'approved': [s for s in students if s.status == 'approved'],
        'pending': [s for s in students if s.status == 'pending']
    }
    return render_template("direction_detail.html", direction=direction, students=students, students_by_status=students_by_status)

@directions_bp.route("/directions/<int:direction_id>/remove_student/<int:student_id>", methods=["POST"])
@login_required
def remove_student_from_direction(direction_id, student_id):
    stmt = student_directions.delete().where(
        (student_directions.c.student_id == student_id) &
        (student_directions.c.direction_id == direction_id)
    )
    db.session.execute(stmt)
    db.session.commit()
    flash("Студент удален из направления", "success")
    return redirect(url_for("directions.direction_detail", direction_id=direction_id))

# --- QUOTAS ---
@quotas_bp.route("/quotas")
@login_required
def quotas_list():
    quotas = EventQuota.query.all()
    return render_template("quotas.html", quotas=quotas, directions=Direction.query.all())

@quotas_bp.route("/quotas/create", methods=["POST"])
@login_required
def create_quota():
    title = request.form.get("title", "").strip()
    desc = request.form.get("description", "").strip()
    location = request.form.get("location", "").strip()
    time_range = request.form.get("time_range", "").strip()
    dress_code = request.form.get("dress_code", "").strip()
    functionality = request.form.get("functionality", "").strip()
    direction_ids = request.form.getlist("direction_ids", type=int)
    
    days_data = []
    i = 0
    while True:
        date_str = request.form.get(f"day_date_{i}")
        places = request.form.get(f"day_places_{i}", type=int)
        if not date_str or not places: break
        
        try:
            day_date = datetime.strptime(date_str, "%Y-%m-%d")
            days_data.append({"date": day_date, "places": places})
        except ValueError:
            pass
        i += 1
        
    if not all([title, direction_ids, days_data]):
        flash("Заполните название, направления и добавьте хотя бы один день!", "danger")
        return redirect(url_for("quotas.quotas_list"))
    
    quota = EventQuota(
        event_title=title, event_description=desc, location=location,
        time_range=time_range, dress_code=dress_code, functionality=functionality
    )
    
    for dir_id in direction_ids:
        dir_obj = Direction.query.get(dir_id)
        if dir_obj: quota.directions.append(dir_obj)
    
    for d in days_data:
        day = EventDay(date=d["date"], daily_places=d["places"])
        quota.days.append(day)
    
    db.session.add(quota)
    db.session.commit()
    
    # РАССЫЛКА ЧЕРЕЗ REQUESTS В ПОТОКЕ
    try:
        target_students_set = set()
        for dir_obj in quota.directions:
            for s in dir_obj.students: target_students_set.add(s)
        
        tg_ids = [s.tg_id for s in target_students_set]
        if tg_ids:
            dates_block = "\n".join([f"📍 {d['date'].strftime('%d.%m.%Y')}" for d in sorted(days_data, key=lambda x: x['date'])])
            func_lines = functionality.split('\n')
            formatted_func = "\n".join([f"📍 {line.strip()}" for line in func_lines if line.strip()])

            text = (
                f"📌 <b>{title}</b>\n\n"
                f"<b>Даты:</b>\n{dates_block}\n"
                f"🗓 <b>Время:</b> {time_range}\n"
                f"📍 <b>Место:</b> {location}\n\n"
                f"🛠 <b>Функционал:</b>\n{formatted_func}\n\n"
                f"👕 <b>Форма одежды:</b> {dress_code}\n\n"
                f"Записывайтесь через меню бота ' Мероприятия'!"
            )
            
            api_url = f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendMessage"
            def send_in_thread(ids, msg):
                for uid in ids:
                    try: requests.post(api_url, json={"chat_id": uid, "text": msg, "parse_mode": "HTML"}, timeout=10)
                    except: pass
            
            t = threading.Thread(target=send_in_thread, args=(tg_ids, text))
            t.daemon = True; t.start()
    except Exception as e: print(f"Ошибка рассылки: {e}")

    flash(f"Мероприятие «{title}» создано!", "success")
    return redirect(url_for("quotas.quotas_list"))

@quotas_bp.route("/quotas/participants/<int:quota_id>")
@login_required
def quota_participants(quota_id):
    quota = EventQuota.query.get_or_404(quota_id)
    return render_template("quota_participants.html", quota=quota)

@quotas_bp.route("/quotas/mark_day/<int:participation_id>/<new_status>")
@login_required
def mark_day_attendance(participation_id, new_status):
    p = DayParticipation.query.get_or_404(participation_id)
    p.status = new_status
    db.session.commit()
    flash("Статус обновлен", "success")
    return redirect(url_for("quotas.quota_participants", quota_id=p.day.quota_id))

# --- APP FACTORY ---
def create_app():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = settings.DATABASE_URI
    app.config["SECRET_KEY"] = settings.SECRET_KEY
    db.init_app(app)
    
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(directions_bp)
    app.register_blueprint(quotas_bp)
    app.register_blueprint(api_bp, url_prefix="/api")
    
    return app