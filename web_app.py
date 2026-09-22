from functools import wraps
from datetime import datetime
from flask import Blueprint, Flask, flash, redirect, render_template, request, session, url_for, jsonify
from config import settings
from database import db, verify_password, Student, User, Direction, EventQuota, VolunteerGroup, StudentStatus, Participant

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

# --- AUTH ---
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
        "free_places": sum(q.available_places() for q in EventQuota.query.all()),
        "active_groups": VolunteerGroup.query.count()
    }
    directions = Direction.query.all()
    return render_template("dashboard.html", stats=stats, directions=directions)

# --- НАПРАВЛЕНИЯ ---
@directions_bp.route("/directions")
@login_required
def directions_list():
    directions = Direction.query.all()
    return render_template("directions.html", directions=directions)

# --- КВОТЫ И МЕРОПРИЯТИЯ ---
@quotas_bp.route("/quotas")
@login_required
def quotas_list():
    quotas = EventQuota.query.order_by(EventQuota.event_date.desc()).all()
    directions = Direction.query.all()
    return render_template("quotas.html", quotas=quotas, directions=directions)

@quotas_bp.route("/quotas/create", methods=["POST"])
@login_required
def create_quota():
    title = request.form.get("title", "").strip()
    date_str = request.form.get("event_date")
    direction_id = request.form.get("direction_id", type=int)
    places = request.form.get("total_places", type=int)
    category = request.form.get("category", "other")
    desc = request.form.get("description", "")

    if not all([title, date_str, direction_id, places]):
        flash("Заполните все обязательные поля!", "danger")
        return redirect(url_for("quotas.quotas_list"))

    try:
        event_date = datetime.strptime(date_str, "%Y-%m-%dT%H:%M")
    except ValueError:
        flash("Неверный формат даты", "danger")
        return redirect(url_for("quotas.quotas_list"))

    quota = EventQuota(
        event_title=title, event_description=desc, event_date=event_date,
        category=category, direction_id=direction_id, total_places=places
    )
    db.session.add(quota)
    db.session.commit()
    flash(f"Квота «{title}» создана!", "success")
    return redirect(url_for("quotas.quotas_list"))

@quotas_bp.route("/quotas/participants/<int:quota_id>")
@login_required
def quota_participants(quota_id):
    quota = EventQuota.query.get_or_404(quota_id)
    return render_template("quota_participants.html", quota=quota)

@quotas_bp.route("/quotas/mark/<int:participant_id>/<new_status>")
@login_required
def mark_attendance(participant_id, new_status):
    p = Participant.query.get_or_404(participant_id)
    p.status = new_status
    db.session.commit()
    flash("Статус обновлен", "success")
    return redirect(url_for("quotas.quota_participants", quota_id=p.quota_id))

# --- УМНОЕ РАСПРЕДЕЛЕНИЕ В ОТРЯДЫ ---
@api_bp.route("/distribute", methods=["POST"])
@login_required
def smart_distribute():
    from bot import send_notification
    
    pending_students = Student.query.filter(
        Student.status == StudentStatus.APPROVED.value,
        Student.group_id.is_(None),
        Student.direction_id.isnot(None)
    ).all()

    distributed_count = 0
    notifications = []

    for student in pending_students:
        group = VolunteerGroup.query.filter_by(direction_id=student.direction_id).first()

        if not group or group.current_size() >= 30:
            last_group = VolunteerGroup.query.filter_by(direction_id=student.direction_id).order_by(VolunteerGroup.name.desc()).first()
            num = int(last_group.name.split('-')[-1]) + 1 if last_group and '-' in last_group.name else 1
            
            new_name = f"{student.direction.code}-{num}"
            group = VolunteerGroup(name=new_name, direction_id=student.direction_id, curator_name="Куратор")
            db.session.add(group)
            db.session.flush()

        student.group_id = group.id
        student.status = StudentStatus.ACTIVE.value
        distributed_count += 1
        
        notifications.append({
            "tg_id": student.tg_id,
            "text": f"✅ Вы зачислены в отряд!\n\nГруппа: {group.name}\nНаправление: {student.direction.name}"
        })

    db.session.commit()
    for note in notifications:
        send_notification(note["tg_id"], note["text"])

    return jsonify({"message": f"Распределено {distributed_count} студентов"})

# --- APP FACTORY ---
def create_app():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = settings.DATABASE_URI
    app.config["SECRET_KEY"] = settings.SECRET_KEY
    db.init_app(app)
    
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(directions_bp)
    app.register_blueprint(quotas_bp) # <-- ДОБАВЛЕНО
    app.register_blueprint(api_bp, url_prefix="/api")
    
    return app