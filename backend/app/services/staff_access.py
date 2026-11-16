"""Deny-by-default, server-side authorization for employee workspaces."""
from database import Direction, StaffGrant, UserRole

# The all-directions employee receives the default employee profile in every
# active direction; saved per-direction grants can narrow or change that profile.
# Each direction employee remains bound to one assigned direction.
SECTIONS = (
    'students', 'applications', 'events', 'lessons', 'notifications',
    'report_archive', 'statistics', 'chats', 'orders',
)
NOTIFICATION_OPTIONS = ('applications', 'events', 'lessons', 'system')
DEFAULT_EMPLOYEE_GRANTS = {
    'students': 'manage', 'applications': 'manage', 'events': 'manage',
    'lessons': 'manage', 'notifications': 'manage',
    'report_archive': 'view', 'statistics': 'manage',
    'chats': 'manage', 'orders': 'view',
}

# These sections are intentionally read/download-only for employees. The
# superadministrator bypasses grants and retains global management rights.
EMPLOYEE_READ_ONLY_SECTIONS = frozenset({'report_archive', 'orders'})


def _active_direction(direction_id):
    if not direction_id:
        return None
    try:
        direction_id = int(direction_id)
    except (TypeError, ValueError):
        return None
    direction = Direction.query.get(direction_id)
    return direction if direction and not getattr(direction, 'is_archived', False) else None


def _grant_access(user, direction_id, section):
    grant = StaffGrant.query.filter_by(
        user_id=user.id, direction_id=direction_id, section=section
    ).first()
    return grant.access if grant else None


def allowed(user, direction_id, section, level='view'):
    """Check one section action in one active direction.

    Main administrators are global. Observers can view every active direction.
    The global employee receives the default profile in every active direction
    unless a saved per-direction grant overrides it; a scoped employee needs an
    explicit grant for their one assigned direction.
    """
    if not user or not user.is_active or section not in SECTIONS or level not in {'view', 'manage'}:
        return False
    direction = _active_direction(direction_id)
    if not direction:
        return False
    if user.role == UserRole.SUPER_ADMIN.value:
        return True
    if user.role == UserRole.OBSERVER.value:
        return level == 'view'
    if user.role != UserRole.STAFF.value:
        return False
    # The all-directions employee has no home direction. Their scope is the
    # explicit per-direction grants issued by the chief administrator.
    rank = getattr(user, 'staff_rank', 'employee') or 'employee'
    if rank == 'employee_all':
        if level == 'manage' and section in EMPLOYEE_READ_ONLY_SECTIONS:
            return False
        access = _grant_access(user, direction.id, section)
        if access is None:
            access = DEFAULT_EMPLOYEE_GRANTS.get(section, 'none')
        return access == 'manage' if level == 'manage' else access in {'view', 'manage'}
    try:
        home_id = int(user.assigned_direction_id) if user.assigned_direction_id else None
    except (TypeError, ValueError):
        return False
    if home_id != direction.id:
        return False
    if level == 'manage' and section in EMPLOYEE_READ_ONLY_SECTIONS:
        return False
    access = _grant_access(user, direction.id, section) or 'none'
    return access == 'manage' if level == 'manage' else access in {'view', 'manage'}


def direction_ids(user, section, level='view'):
    """Return every direction the user may access for a section and level."""
    if not user or not user.is_active or section not in SECTIONS or level not in {'view', 'manage'}:
        return set()
    active = {direction.id for direction in Direction.query.filter_by(is_archived=False).all()}
    if user.role == UserRole.SUPER_ADMIN.value:
        return active
    if user.role == UserRole.OBSERVER.value:
        return active if level == 'view' else set()
    if user.role != UserRole.STAFF.value:
        return set()
    if level == 'manage' and section in EMPLOYEE_READ_ONLY_SECTIONS:
        return set()
    rank = getattr(user, 'staff_rank', 'employee') or 'employee'
    if rank == 'employee_all':
        result = set()
        for direction_id in active:
            access = _grant_access(user, direction_id, section)
            if access is None:
                access = DEFAULT_EMPLOYEE_GRANTS.get(section, 'none')
            if (access == 'manage' if level == 'manage' else access in {'view', 'manage'}):
                result.add(direction_id)
        return result
    try:
        home_id = int(user.assigned_direction_id) if user.assigned_direction_id else None
    except (TypeError, ValueError):
        return set()
    if home_id not in active:
        return set()
    access = _grant_access(user, home_id, section) or 'none'
    allowed_level = access == 'manage' if level == 'manage' else access in {'view', 'manage'}
    return {home_id} if allowed_level else set()
