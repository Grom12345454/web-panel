"""Pure presentation helper for legacy chair appointments.

A historic database may contain chair assignments for multiple students.
This function shows one chair in the main management list and returns every
unique candidate for an explicit super-admin resolution; it never modifies DB.
"""


def management_leadership_rows(rows, canonical_role_label):
    rows = list(rows)
    chair_rows = sorted(
        (row for row in rows if canonical_role_label(row.position_name) == 'Председатель студсовета'),
        key=lambda row: row.id,
    )
    # Keep the same primary chair as the public directory (oldest record).
    primary_id = chair_rows[0].id if chair_rows else None
    visible_rows = [
        row for row in rows
        if canonical_role_label(row.position_name) != 'Председатель студсовета'
        or row.id == primary_id
    ]
    candidate_students = []
    seen_student_ids = set()
    for row in chair_rows:
        if row.student_id not in seen_student_ids:
            seen_student_ids.add(row.student_id)
            if row.student is not None:
                candidate_students.append(row.student)
    return visible_rows, candidate_students, max(0, len(seen_student_ids) - 1)
