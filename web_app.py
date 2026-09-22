from functools import wraps
from datetime import datetime

from flask import Blueprint, Flask, flash, redirect, render_template, request, session, url_for

from config import settings
from database import (
    db, verify_password, Student, User, Direction, 
    StudentStatus, EventQuota, Participant
)

auth_bp = Blueprint("auth", __name__)
admin_bp = Blueprint("admin", __name__)
directions_bp = Blueprint("directions", __name__)
quotas_bp = Blueprint("quotas", __name__)

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
            session["role"] = user.role
            return redirect(url_for("admin.dashboard"))
        flash("Неверный email или пароль", "danger")
    return render_template("login.html")

@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))

# --- DASHBOARD & ASSIGN ---
@admin_bp.route("/")
@login_required
def dashboard():
    students = Student.query.order_by(Student.created_at.desc()).all()
    directions_list = Direction.query.all()
    stats = {
        "total": Student.query.count(),
        "pending": Student.query.filter_by(status="pending").count(),
        "enrolled": Student.query.filter_by(status="enrolled").count(),
        "active_quotas": EventQuota.query.filter(EventQuota.event_date > datetime.utcnow()).count(),
        "directions_count": Direction.query.count()
    }
    return render_template("dashboard.html", students=students, stats=stats, directions_list=directions_list)

@admin_bp.route("/approve/<int:student_id>/<new_status>")
@login_required
def update_status(student_id, new_status):
    student = Student.query.get_or_404(student_id)
    student.status = new_status
    db.session.commit()
    flash(f"Статус «{student.full_name}» изменён на: {new_status}", "success")
    return redirect(url_for("admin.dashboard"))

@admin_bp.route("/assign/<int:student_id>", methods=["POST"])
@login_required
def assign_direction(student_id):
    student = Student.query.get_or_404(student_id)
    direction_id = request.form.get("direction_id", type=int)
    if not direction_id:
        flash("Выберите направление!", "danger")
        return redirect(url_for("admin.dashboard"))
        
    student.direction_id = direction_id
    if student.status == StudentStatus.PENDING.value:
        student.status = StudentStatus.APPROVED.value
        
    db.session.commit()
    direction = Direction.query.get(direction_id)
    flash(f"«{student.full_name}» назначен на «{direction.name}»", "success")
    return redirect(url_for("admin.dashboard"))

# --- DIRECTIONS ---
@directions_bp.route("/directions")
@login_required
def directions_list():
    directions = Direction.query.all()
    return render_template("directions.html", directions=directions)

@directions_bp.route("/directions/create", methods=["POST"])
@login_required
def create_direction():
    name = request.form.get("name", "").strip()
    code = request.form.get("code", "").strip()
    if not name or not code:
        flash("Название и код обязательны!", "danger")
        return redirect(url_for("directions.directions_list"))
    if Direction.query.filter_by(code=code).first():
        flash("Код направления уже существует!", "danger")
        return redirect(url_for("directions.directions_list"))
        
    d = Direction(name=name, code=code)
    db.session.add(d)
    db.session.commit()
    flash("Направление создано!", "success")
    return redirect(url_for("directions.directions_list"))

@directions_bp.route("/directions/delete/<int:direction_id>")
@login_required
def delete_direction(direction_id):
    d = Direction.query.get_or_404(direction_id)
    if d.students:
        flash("Нельзя удалить направление со студентами!", "danger")
    else:
        db.session.delete(d)
        db.session.commit()
        flash("Направление удалено.", "success")
    return redirect(url_for("directions.directions_list"))

# --- QUOTAS ---
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
    category = request.form.get("category", "other")
    direction_id = request.form.get("direction_id", type=int)
    places = request.form.get("total_places", type=int)

    if not all([title, date_str, direction_id, places]):
        flash("Заполните все поля!", "danger")
        return redirect(url_for("quotas.quotas_list"))

    try:
        event_date = datetime.strptime(date_str, "%Y-%m-%dT%H:%M")
    except ValueError:
        flash("Неверный формат даты", "danger")
        return redirect(url_for("quotas.quotas_list"))

    quota = EventQuota(
        event_title=title, event_date=event_date, category=category,
        direction_id=direction_id, total_places=places,
        event_description=request.form.get("description", "")
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

def create_app():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = settings.DATABASE_URI
    app.config["SECRET_KEY"] = settings.SECRET_KEY
    db.init_app(app)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(directions_bp)
    app.register_blueprint(quotas_bp)
    return app