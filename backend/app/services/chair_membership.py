"""Reconcile Student App memberships with every active leadership assignment.

Council-wide roles grant memberships by education contour. Direction leaders also
need an active row for their own direction. Membership metadata distinguishes rows
created only for a role from rows the student had chosen themselves, so revoking a
role never removes a student's independent membership.
"""
from __future__ import annotations

import json

from database import db, Direction, StudentLeadership, student_directions, DirectionStatus
from services.permissions import normalize_role, role_scope, DIRECTION_ROLE_LABELS

SOURCE = "leadership_auto_membership"
LEGACY_SOURCES = {SOURCE, "chair_auto_membership", "leadership_assignment"}

def _metadata(raw: str | None) -> dict:
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}

def _desired_direction_ids(student_id: int) -> set[int]:
    """Return union of all directions justified by current roles."""
    roles = StudentLeadership.query.filter_by(student_id=student_id).all()
    scopes = {role_scope(row.position_name, row.education_type) for row in roles}
    scopes.discard(None)
    directions = Direction.query.order_by(Direction.id.asc()).all()
    desired = set()
    if "all" in scopes:
        desired.update(direction.id for direction in directions)
    else:
        for direction in directions:
            if any(direction.available_for(scope) for scope in scopes if scope in {"college", "institute"}):
                desired.add(direction.id)

    # A direction-specific head/deputy keeps access to that direction even when
    # a council-wide role is removed at the same time.
    for row in roles:
        if normalize_role(row.position_name) in DIRECTION_ROLE_LABELS and row.direction_id is not None:
            desired.add(int(row.direction_id))
    return desired

def _student_scopes(student_id: int) -> set[str]:
    scopes = set()
    for row in StudentLeadership.query.filter_by(student_id=student_id).all():
        scope = role_scope(row.position_name, row.education_type)
        if scope in {"all", "college", "institute"}:
            scopes.add(scope)
    return scopes

def is_council_chair(student_id: int) -> bool:
    return "all" in _student_scopes(student_id)

def has_scoped_council_role(student_id: int) -> bool:
    """Whether this student has a chair/deputy role."""
    return bool(_student_scopes(student_id))

def has_membership_role(student_id: int) -> bool:
    """Whether any current leadership assignment should create/maintain membership."""
    if has_scoped_council_role(student_id):
        return True
    return any(
        normalize_role(row.position_name) in DIRECTION_ROLE_LABELS
        for row in StudentLeadership.query.filter_by(student_id=student_id).all()
    )

def role_owned_memberships_lost_after_role_change(student_id: int) -> set[int]:
    """IDs of role-created memberships no longer warranted by remaining roles.

    Call after deleting the role row(s), but before membership synchronization.
    Rows that existed before a role was assigned are deliberately excluded: those
    represent a direction the student chose independently and must be preserved.
    """
    desired = _desired_direction_ids(student_id)
    rows = db.session.execute(
        student_directions.select().where(student_directions.c.student_id == student_id)
    ).mappings().all()
    lost = set()
    for row in rows:
        direction_id = int(row["direction_id"])
        if direction_id in desired:
            continue
        meta = _metadata(row.get("extra_data"))
        source = meta.get("source")
        created_by_role = meta.get("created_by_role") is True
        if source == "leadership_assignment" and "created_by_role" not in meta:
            # Older builds created this row only if no membership already existed.
            created_by_role = True
        if source == "chair_auto_membership" and "created_by_role" not in meta:
            created_by_role = bool(meta.get("created_by_chair", True))

        if source in LEGACY_SOURCES:
            # A membership that was active/approved before the role was assigned
            # remains a legitimate independent path into the chat. A pending,
            # rejected or interview-stage row was only temporarily activated by
            # the role; once the role disappears, any temporary chat access and
            # invites must also be revoked even though the original application
            # row is restored below.
            previous_status = meta.get("previous_status")
            previously_entitled = previous_status in {
                DirectionStatus.ACTIVE.value,
                "approved",  # legacy pre-migration state only
            }
            if created_by_role or (previous_status is not None and not previously_entitled):
                lost.add(direction_id)
    return lost

def direction_required_by_current_role(student_id: int, direction_id: int) -> bool:
    return int(direction_id) in _desired_direction_ids(student_id)

def sync_student_leadership_memberships(student_id: int) -> int:
    """Activate all role-justified memberships and restore independent state on removal.

    Idempotent; does not commit. Returns the number of association rows changed.
    """
    desired_ids = _desired_direction_ids(student_id)
    directions = Direction.query.order_by(Direction.id.asc()).all()
    rows = db.session.execute(
        student_directions.select().where(student_directions.c.student_id == student_id)
    ).mappings().all()
    by_direction = {int(row["direction_id"]): dict(row) for row in rows}
    changed = 0

    for direction in directions:
        if direction.id not in desired_ids:
            continue
        existing = by_direction.get(direction.id)
        if existing is None:
            result = db.session.execute(
                student_directions.insert().values(
                    student_id=student_id,
                    direction_id=direction.id,
                    status=DirectionStatus.ACTIVE.value,
                    extra_data=json.dumps({
                        "source": SOURCE,
                        "created_by_role": True,
                        "previous_status": None,
                        "previous_extra_data": None,
                    }, ensure_ascii=False),
                ).prefix_with("OR IGNORE")
            )
            changed += max(int(result.rowcount or 0), 0)
            continue

        metadata = _metadata(existing.get("extra_data"))
        source = metadata.get("source")
        if source in LEGACY_SOURCES:
            old_metadata = dict(metadata)
            metadata["source"] = SOURCE
            if "created_by_role" not in metadata:
                if source == "leadership_assignment":
                    metadata["created_by_role"] = True
                elif source == "chair_auto_membership":
                    metadata["created_by_role"] = bool(metadata.get("created_by_chair", True))
                else:
                    metadata["created_by_role"] = bool(metadata.get("created_by_chair", False))
            metadata.setdefault("previous_status", None)
            metadata.setdefault("previous_extra_data", None)
            if existing.get("status") != DirectionStatus.ACTIVE.value or metadata != old_metadata:
                db.session.execute(
                    student_directions.update().where(
                        (student_directions.c.student_id == student_id)
                        & (student_directions.c.direction_id == direction.id)
                    ).values(status=DirectionStatus.ACTIVE.value,
                             extra_data=json.dumps(metadata, ensure_ascii=False))
                )
                changed += 1
            continue

        # Existing active membership is independent from the role. If the student
        # already had a pending/rejected application, preserve its previous status.
        if existing.get("status") == DirectionStatus.ACTIVE.value:
            continue
        db.session.execute(
            student_directions.update().where(
                (student_directions.c.student_id == student_id)
                & (student_directions.c.direction_id == direction.id)
            ).values(
                status=DirectionStatus.ACTIVE.value,
                extra_data=json.dumps({
                    "source": SOURCE,
                    "created_by_role": False,
                    "previous_status": existing.get("status"),
                    "previous_extra_data": existing.get("extra_data"),
                }, ensure_ascii=False),
            )
        )
        changed += 1

    # Remove only role-managed memberships no longer supported by any remaining
    # role. Previously selected memberships are restored to their former status.
    for direction_id, existing in by_direction.items():
        if direction_id in desired_ids:
            continue
        metadata = _metadata(existing.get("extra_data"))
        source = metadata.get("source")
        if source not in LEGACY_SOURCES:
            continue
        created_by_role = metadata.get("created_by_role") is True
        if source == "leadership_assignment" and "created_by_role" not in metadata:
            created_by_role = True
        if source == "chair_auto_membership" and "created_by_role" not in metadata:
            created_by_role = bool(metadata.get("created_by_chair", True))
        condition = (
            (student_directions.c.student_id == student_id)
            & (student_directions.c.direction_id == direction_id)
        )
        if created_by_role:
            db.session.execute(student_directions.delete().where(condition))
        else:
            db.session.execute(student_directions.update().where(condition).values(
                status=metadata.get("previous_status") or DirectionStatus.PENDING.value,
                extra_data=metadata.get("previous_extra_data"),
            ))
        changed += 1
    return changed

def activate_all_direction_memberships(student_id: int) -> int:
    return sync_student_leadership_memberships(student_id)

def restore_memberships_after_chair_removal(student_id: int) -> int:
    return sync_student_leadership_memberships(student_id)

def sync_existing_chairs() -> int:
    """Startup repair for all legacy leadership assignments."""
    from services.permissions import role_scope

    student_ids = {
        row.student_id for row in StudentLeadership.query.all()
        if role_scope(row.position_name, row.education_type) in {"all", "college", "institute"}
        or normalize_role(row.position_name) in DIRECTION_ROLE_LABELS
    }
    changed = 0
    for student_id in sorted(student_ids):
        changed += sync_student_leadership_memberships(student_id)
    if changed:
        db.session.commit()
    return changed
