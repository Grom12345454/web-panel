"""Canonical readable positions for the student management table."""
from services.permissions import role_label, role_scope


def student_leadership_labels(rows):
    roles = {}
    for row in rows:
        role = role_label(row.position_name)
        if role_scope(row.position_name, getattr(row, 'education_type', None)) is None:
            direction = getattr(row, 'direction', None)
            if direction and getattr(direction, 'name', ''):
                role += ' · ' + direction.name
        labels = roles.setdefault(row.student_id, [])
        if role not in labels:
            labels.append(role)
    return roles
