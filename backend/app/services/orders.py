"""Role-restricted archive of scanned orders for completed activities."""
from datetime import datetime
from io import BytesIO
from pathlib import Path
from secrets import token_hex
import hashlib
import logging
import zipfile

from flask import (Blueprint, abort, current_app, flash, redirect, render_template,
                   request, send_file, url_for)

from database import (db, AdministrativeOrder, OrderDeliveryJob, EventQuota,
                      EventQuotaChat, UserRole)
from database.helpers import get_quota_direction_ids
from services.applications import can_user_manage_direction
from web_app import login_required

logger = logging.getLogger(__name__)
orders_bp = Blueprint('orders', __name__, url_prefix='/orders')
MAX_ORDER_BYTES = 8 * 1024 * 1024
ALLOWED_SUFFIXES = frozenset({'.pdf', '.docx'})


def _order_root():
    # App instance is NOT static. Never expose this directory with a web route.
    base = Path(current_app.instance_path).resolve() / 'private_orders'
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    return base


def _event_direction_ids(quota_id):
    """All directions attached directly or through event chat targets."""
    direction_ids = {int(value) for value in get_quota_direction_ids(quota_id) if value is not None}
    direction_ids.update(int(value) for (value,) in EventQuotaChat.query.with_entities(
        EventQuotaChat.direction_id
    ).filter(EventQuotaChat.quota_id == quota_id, EventQuotaChat.direction_id.is_not(None)).all())
    return direction_ids


def may_upload(user, kind, target):
    """Only the chief administrator and authorized direction leaders may act.

    Employees have strictly view/download-only access to this archive. EventLeader
    records designate student event hosts, not website staff. Being
    appointed to host an event must never grant access to the official orders
    archive or its upload, dispatch, retry, or download endpoints.
    """
    if not user or not user.is_active or target is None:
        return False
    if user.role == UserRole.SUPER_ADMIN.value:
        return kind == 'event'
    # Employees have view/download access only. Upload, dispatch and retry are
    # reserved for the chief administrator and explicitly authorized leaders.
    if user.role != UserRole.LEADER.value or kind != 'event':
        return False
    direction_ids = _event_direction_ids(target.id)
    return any(can_user_manage_direction(user.id, direction_id, None)
               for direction_id in direction_ids)


def _is_completed(kind, target):
    now = datetime.utcnow()
    if kind == 'event':
        # Closed or all scheduled days already in the past.
        return bool(target.is_closed or target.closed_at or
                    (target.days and max(day.date for day in target.days) < now))
    return False


def _get_target(kind, target_id):
    if kind == 'event':
        return EventQuota.query.get(target_id)
    return None


def _completed_events():
    return [event for event in EventQuota.query.order_by(EventQuota.id.desc()).limit(500).all()
            if _is_completed("event", event)]


def _available_targets(user):
    return [event for event in _completed_events() if may_upload(user, "event", event)]


def _staff_viewable_targets(user):
    # Completed events wholly contained in the employee's order-view scope.
    from services.staff_access import direction_ids as staff_direction_ids
    permitted_ids = set(staff_direction_ids(user, 'orders', 'view'))
    if not permitted_ids:
        return []
    return [event for event in _completed_events()
            if _event_direction_ids(event.id) and _event_direction_ids(event.id).issubset(permitted_ids)]


def may_view_order(user, kind, target):
    """View/download permission, deliberately separate from upload/dispatch permission."""
    if not user or not user.is_active or target is None or kind != "event":
        return False
    if user.role == UserRole.SUPER_ADMIN.value:
        return _is_completed(kind, target)
    if user.role == UserRole.STAFF.value:
        if not _is_completed(kind, target):
            return False
        direction_ids = _event_direction_ids(target.id)
        from services.staff_access import direction_ids as staff_direction_ids
        permitted_ids = set(staff_direction_ids(user, 'orders', 'view'))
        return bool(direction_ids) and direction_ids.issubset(permitted_ids)
    if user.role == UserRole.OBSERVER.value:
        return _is_completed(kind, target)
    return may_upload(user, kind, target)


def _validate_order(upload):
    if not upload or not upload.filename:
        raise ValueError('Выберите PDF или DOCX с приказом.')
    from werkzeug.utils import secure_filename
    filename = secure_filename(upload.filename)
    # secure_filename() drops Cyrillic-only filenames: keep a safe display name.
    shown = Path(upload.filename.replace('\\', '/').split('/')[-1]).name[:180]
    suffix = Path(shown).suffix.lower()
    if not filename and suffix in ALLOWED_SUFFIXES:
        filename = 'order' + suffix
    if suffix not in ALLOWED_SUFFIXES or not filename:
        raise ValueError('Разрешены только PDF и DOCX.')
    data = upload.stream.read(MAX_ORDER_BYTES + 1)
    if not data or len(data) > MAX_ORDER_BYTES:
        raise ValueError('Размер приказа должен быть от 1 байта до 8 МБ.')
    if suffix == '.pdf':
        if not data.startswith(b'%PDF-'):
            raise ValueError('Файл не является корректным PDF.')
        mime = 'application/pdf'
    else:
        if not zipfile.is_zipfile(BytesIO(data)):
            raise ValueError('Файл не является корректным DOCX.')
        try:
            with zipfile.ZipFile(BytesIO(data)) as archive:
                names = set(archive.namelist())
                if 'word/document.xml' not in names or '[Content_Types].xml' not in names:
                    raise ValueError('DOCX не содержит документа Word.')
                if len(names) > 3000 or sum(info.file_size for info in archive.infolist()) > 32 * 1024 * 1024:
                    raise ValueError('Слишком большой распакованный документ.')
        except (ValueError, zipfile.BadZipFile):
            raise ValueError('Файл DOCX повреждён или слишком велик.')
        mime = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    return shown, data, mime, suffix


def delete_order_files(orders):
    """Best-effort removal of stored files after a DB delete, for maintenance."""
    root = _order_root()
    for item in orders:
        try:
            (root / item.stored_name).unlink(missing_ok=True)
        except OSError:
            logger.exception('Cannot remove archived order file id=%s', item.id)


@orders_bp.get('/')
@login_required
def archive(current_user):
    if not current_user.is_active or current_user.role not in {
        UserRole.SUPER_ADMIN.value, UserRole.STAFF.value, UserRole.LEADER.value, UserRole.OBSERVER.value
    }:
        abort(403)
    # Observers see the archive across all completed events, but upload and
    # delivery endpoints still use may_upload() and remain inaccessible.
    if current_user.role == UserRole.OBSERVER.value:
        events = _completed_events()
    elif current_user.role == UserRole.STAFF.value:
        events = _staff_viewable_targets(current_user)
    else:
        events = _available_targets(current_user)
    event_ids = {e.id for e in events}
    orders = AdministrativeOrder.query.order_by(AdministrativeOrder.uploaded_at.desc()).all()
    visible = [o for o in orders if o.target_kind == "event" and o.target_id in event_ids]
    names = {("event", e.id): e.event_title for e in events}
    totals = {}
    for order in visible:
        jobs = OrderDeliveryJob.query.filter_by(order_id=order.id).all()
        totals[order.id] = {state: sum(job.status == state for job in jobs)
                            for state in ("pending", "retry", "blocked", "sending", "delivered", "failed")}
    can_upload_orders = (current_user.role == UserRole.SUPER_ADMIN.value or
                         any(may_upload(current_user, 'event', event) for event in events))
    return render_template("orders/archive.html", events=events, orders=visible, names=names,
                           delivery_totals=totals, can_upload_orders=can_upload_orders)


@orders_bp.post('/upload')
@login_required
def upload_order(current_user):
    kind = request.form.get('target_kind', '').strip()
    target_id = request.form.get('target_id', type=int)
    if kind != 'event' or not target_id:
        abort(400)
    target = _get_target(kind, target_id)
    if not target:
        abort(404)
    if not may_upload(current_user, kind, target):
        abort(403)
    if not _is_completed(kind, target):
        flash('Приказ можно прикрепить только к прошедшему мероприятию.', 'warning')
        return redirect(url_for('orders.archive'))
    try:
        shown, data, mime, suffix = _validate_order(request.files.get('document'))
    except ValueError as exc:
        flash(str(exc), 'danger')
        return redirect(url_for('orders.archive'))
    stored_name = token_hex(24) + suffix
    path = _order_root() / stored_name
    try:
        with path.open('xb') as file:
            file.write(data)
        item = AdministrativeOrder(target_kind=kind, target_id=target_id,
                                   original_name=shown, stored_name=stored_name,
                                   mime_type=mime, file_size=len(data),
                                   sha256=hashlib.sha256(data).hexdigest(),
                                   uploaded_by=current_user.id,
                                   uploaded_by_name=current_user.full_name or current_user.email)
        db.session.add(item)
        db.session.commit()
    except Exception:
        db.session.rollback()
        path.unlink(missing_ok=True)
        logger.exception('Order upload failed')
        flash('Не удалось сохранить приказ.', 'danger')
        return redirect(url_for('orders.archive'))
    try:
        from services.order_delivery import queue_order_documents
        result = queue_order_documents(item)
        flash('Приказ сохранён. Новых задач отправки в Telegram: '
              + str(result['queued']) + '; без Telegram: ' + str(result['without_telegram']) + '.', 'success')
    except Exception:
        logger.exception('Could not queue order id=%s; manual dispatch is available', item.id)
        flash('Приказ сохранён, но задачи отправки не созданы. Используйте кнопку «Поставить в очередь».', 'warning')
    return redirect(url_for('orders.archive'))


@orders_bp.post('/<int:order_id>/retry')
@login_required
def retry_order(current_user, order_id):
    item = db.get_or_404(AdministrativeOrder, order_id)
    target = _get_target(item.target_kind, item.target_id)
    if not target or not may_upload(current_user, item.target_kind, target):
        abort(403)
    if not _is_completed(item.target_kind, target):
        abort(400)
    from datetime import datetime
    from config import settings
    count = OrderDeliveryJob.query.filter_by(order_id=item.id, status='failed').update({
        'status': 'pending' if settings.BOT_TOKEN else 'blocked', 'attempts': 0, 'next_attempt_at': datetime.utcnow(),
        'last_error': None, 'locked_until': None,
    }, synchronize_session=False)
    db.session.commit()
    flash(f'Возвращено в очередь: {count} неудачных отправок.', 'success')
    return redirect(url_for('orders.archive'))


@orders_bp.get('/<int:order_id>/download')
@login_required
def download_order(current_user, order_id):
    item = db.get_or_404(AdministrativeOrder, order_id)
    target = _get_target(item.target_kind, item.target_id)
    if not target:
        abort(404)
    if not may_view_order(current_user, item.target_kind, target):
        abort(403)
    path = _order_root() / item.stored_name
    if not path.is_file():
        abort(404)
    response = send_file(path, mimetype=item.mime_type, as_attachment=True,
                         download_name=item.original_name, max_age=0,
                         conditional=False)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@orders_bp.post('/<int:order_id>/dispatch')
@login_required
def dispatch_order(current_user, order_id):
    item = db.get_or_404(AdministrativeOrder, order_id)
    target = _get_target(item.target_kind, item.target_id)
    if not target or not may_upload(current_user, item.target_kind, target):
        abort(403)
    if not _is_completed(item.target_kind, target):
        abort(400)
    from services.order_delivery import queue_order_documents
    try:
        result = queue_order_documents(item)
        flash(f"Добавлено задач: {result['queued']}. Не найдена привязка Telegram у {result['without_telegram']} участников.", 'success')
    except Exception:
        logger.exception('Manual enqueue failed order=%s', item.id)
        flash('Не удалось поставить приказ в очередь отправки.', 'danger')
    return redirect(url_for('orders.archive'))
