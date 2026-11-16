"""Authoritative announcement scope; never derive it from browser-supplied choices."""
from database import UserRole


def broadcast_direction_ids(user):
    """Return the employee's readable direction scope for notices and staff DMs.

    This is a visibility scope, not permission to publish. Publishing is checked
    separately by authorize_broadcast and requires notifications -> manage.
    """
    if not user or not user.is_active:
        return set()
    if user.role == UserRole.SUPER_ADMIN.value:
        # None means institution-wide scope; never narrow a superadmin by a
        # preferred/home direction saved for dashboard navigation.
        return None
    if user.role != UserRole.STAFF.value:
        return set()
    from services.staff_access import direction_ids as staff_direction_ids
    return set(staff_direction_ids(user, 'notifications', 'view'))


def authorize_broadcast(user, selected_ids, *, global_broadcast=False):
    """Reject foreign departments and global sends from non-superadmins."""
    scope = broadcast_direction_ids(user)
    if scope is not None and global_broadcast:
        raise PermissionError('Общую рассылку может отправить только главный администратор.')
    if global_broadcast:
        return None
    ids = set(selected_ids)
    if not ids:
        raise ValueError('Выберите хотя бы одно направление.')
    if scope is not None and not ids.issubset(scope):
        raise PermissionError('Нельзя отправлять уведомления в чужие направления.')
    if user.role == UserRole.STAFF.value:
        from services.staff_access import allowed
        if any(not allowed(user, direction_id, 'notifications', 'manage') for direction_id in ids):
            raise PermissionError('Для отправки уведомлений требуется право «Уведомления — Управление».')
    return sorted(ids)
