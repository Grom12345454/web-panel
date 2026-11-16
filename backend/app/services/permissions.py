"""One server-side authorization policy for reviewing student applications.

Roles are attached to StudentLeadership; never infer a privilege from a role
shown in the browser or from a student's own education type.
"""
import re
from database import Student, StudentLeadership, Direction

CHAIR_TITLES = {"председатель волонтерки", "председатель студсовета", "представитель", "представитель студсовета"}
COLLEGE_DEPUTIES = {"заместитель председателя волонтерки по колледжу", "заместитель председателя студсовета по колледжу"}
INSTITUTE_DEPUTIES = {"заместитель председателя волонтерки по институту", "заместитель председателя студсовета по институту"}
LEGACY_DEPUTIES = {"заместитель председателя студсовета", "заместитель студсовета", "зампред студсовета"}
DIRECTION_ROLE_LABELS = {
    "глава направления", "заместитель главы направления", "зам главы направления",
    "заместитель руководителя направления",
}
GLOBAL_ROLE_LABELS = CHAIR_TITLES | COLLEGE_DEPUTIES | INSTITUTE_DEPUTIES | LEGACY_DEPUTIES


def normalize_role(value):
    return re.sub(r"\s+", " ", str(value or "").strip().casefold().replace("ё", "е"))


def is_global_role_name(value):
    return normalize_role(value) in GLOBAL_ROLE_LABELS


def role_scope(position_name, education_type=None):
    """Leadership organizational scope, distinct from review eligibility."""
    role = normalize_role(position_name)
    if role in CHAIR_TITLES:
        return "all"
    if role in COLLEGE_DEPUTIES:
        return "college"
    if role in INSTITUTE_DEPUTIES:
        return "institute"
    if role in LEGACY_DEPUTIES:
        return education_type if education_type in {"college", "institute"} else None
    return None


def application_review_scope(position_name, education_type=None):
    """For admissions, institute deputy also reviews college students as requested."""
    role = normalize_role(position_name)
    if role in INSTITUTE_DEPUTIES:
        return "college"
    return role_scope(position_name, education_type)


def role_label(value):
    key = normalize_role(value)
    if key in {"представитель", "представитель студсовета"}:
        return "Представитель студсовета"
    if key in CHAIR_TITLES:
        return "Председатель студсовета"
    if key in COLLEGE_DEPUTIES:
        return "Заместитель председателя студсовета по колледжу"
    if key in INSTITUTE_DEPUTIES:
        return "Заместитель председателя студсовета по институту"
    if key in LEGACY_DEPUTIES:
        return "Заместитель председателя студсовета"
    if key in DIRECTION_ROLE_LABELS:
        return "Заместитель главы направления" if "зам" in key else "Глава направления"
    return str(value or "Руководитель направления")


def leadership_rows_for_tg(tg_id):
    student = Student.query.filter_by(tg_id=tg_id).first()
    if not student:
        return None, []
    return student, StudentLeadership.query.filter_by(student_id=student.id).all()


def is_council_chair(tg_id=None, student_id=None):
    student = Student.query.filter_by(id=student_id).first() if student_id else Student.query.filter_by(tg_id=tg_id).first()
    return bool(student and any(role_scope(row.position_name, row.education_type) == "all"
                                for row in StudentLeadership.query.filter_by(student_id=student.id).all()))


def has_global_council_access(tg_id=None, student_id=None, education_type=None):
    student = Student.query.filter_by(id=student_id).first() if student_id else Student.query.filter_by(tg_id=tg_id).first()
    if not student:
        return False
    for row in StudentLeadership.query.filter_by(student_id=student.id).all():
        scope = application_review_scope(row.position_name, row.education_type)
        if scope == "all" or (education_type in {"college", "institute"} and scope == education_type):
            return True
    return False


def allowed_direction_ids(student_id):
    """Any council deputy can review eligible students in every direction."""
    rows = StudentLeadership.query.filter_by(student_id=student_id).all()
    if any(role_scope(row.position_name, row.education_type) in {"all", "college", "institute"} for row in rows):
        return {direction.id for direction in Direction.query.all()}
    return {row.direction_id for row in rows if row.direction_id is not None
            and normalize_role(row.position_name) in DIRECTION_ROLE_LABELS}


def can_manage_direction(tg_id, direction_id, target_education_type=None):
    """Used for listing AND deciding: check candidate education on every write."""
    student, rows = leadership_rows_for_tg(tg_id)
    if not student or not Direction.query.get(direction_id):
        return False
    for row in rows:
        scope = application_review_scope(row.position_name, row.education_type)
        if scope == "all":
            return True
        if scope in {"college", "institute"}:
            if target_education_type is None or target_education_type == scope:
                return True
        elif normalize_role(row.position_name) in DIRECTION_ROLE_LABELS and row.direction_id == direction_id:
            return True
    return False


def leadership_payload(student_id):
    rows = StudentLeadership.query.filter_by(student_id=student_id).all()
    payload, seen = [], set()
    for row in rows:
        scope = role_scope(row.position_name, row.education_type)
        position = role_label(row.position_name)
        if scope == "all":
            direction_name, scope_label = "Все направления и чаты", "all"
            key = (position, scope_label, None)
        elif scope in {"college", "institute"}:
            direction_name = "Направления колледжа" if scope == "college" else "Направления института"
            scope_label = scope
            key = (position, scope_label, None)
        else:
            direction_name, scope_label = (row.direction.name if row.direction else ""), "direction"
            key = (position, scope_label, row.direction_id)
        if key in seen:
            continue
        seen.add(key)
        payload.append({"direction_id": row.direction_id, "direction_name": direction_name,
                        "position": position, "scope": scope_label})
    return payload
