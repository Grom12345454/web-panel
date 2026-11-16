"""Registered on the existing Flask admin blueprint in web_app.py."""
import csv
import io
from datetime import datetime, timedelta

from flask import Response, jsonify, render_template, request, url_for, flash, redirect
from sqlalchemy import func, or_, update
from database import BotJournalEvent, BotDeliveryJob, PortalSetting, db
from services.bot_journal import safe_summary
from services.bot_journal_views import (
    PLATFORM_NAMES, KIND_NAMES, STATUS_NAMES, ACTION_NAMES,
    validated_filters, filtered_events,
)


def spreadsheet_safe(value):
    """Neutralize spreadsheet formulas in exported database text cells."""
    result = str(value if value is not None else '')
    return "'" + result if result.lstrip().startswith(('=', '+', '-', '@')) else result


def register_journal_routes(admin_bp, super_admin_required):
    @admin_bp.get('/bot-journal')
    @super_admin_required
    def bot_journal(current_user):
        # Legacy URL: the new SOC workspace replaces the separate technical log page.
        return redirect(url_for('admin.messenger_monitoring') + '#bot-actions')
        filters = validated_filters(request.args)
        focus = (request.args.get('focus') or '').strip()
        if focus not in ('deliveries', 'events'):
            focus = ('events' if any(request.args.get(field) for field in
                                     ('q', 'platform', 'kind', 'status', 'start', 'end', 'page'))
                     else 'deliveries')
        query = filtered_events(filters)
        try:
            page = min(max(int(request.args.get('page', 1)), 1), 100000)
        except (ValueError, TypeError):
            page = 1
        per_page = 30
        total = query.count()
        pages = max(1, (total + per_page - 1) // per_page)
        page = min(page, pages)
        rows = (query.order_by(BotJournalEvent.id.desc())
                .offset((page - 1) * per_page).limit(per_page).all())
        since = datetime.utcnow() - timedelta(hours=24)
        daily = BotJournalEvent.query.filter(BotJournalEvent.created_at >= since)
        daily_totals = dict(
            total=daily.count(),
            success=daily.filter_by(status='success').count(),
            error=daily.filter_by(status='error').count(),
            telegram=daily.filter_by(platform='telegram').count(),
            vk=daily.filter_by(platform='vk').count(),
            max=daily.filter_by(platform='max').count(),
        )
        # Terminal receipts older than the last log clear are no longer visible.
        # Pending/retry/blocked/failed rows remain as operational jobs, NOT logs.
        record = PortalSetting.query.filter_by(key='bot_delivery_history_visible_since').first()
        try:
            cutoff = datetime.fromisoformat(record.value) if record else None
        except (TypeError, ValueError):
            cutoff = None
        active_statuses = ('pending', 'retry', 'sending', 'blocked', 'failed')
        visibility = (or_(BotDeliveryJob.status.in_(active_statuses), BotDeliveryJob.created_at >= cutoff)
                      if cutoff else None)
        def delivery_scope():
            query = BotDeliveryJob.query
            return query.filter(visibility) if visibility is not None else query
        delivery_counts = {status: delivery_scope().filter_by(status=status).count()
                           for status in ('pending', 'retry', 'sending', 'blocked', 'delivered', 'failed')}
        platform_diagnostics = []
        for key, title in PLATFORM_NAMES.items():
            daily_platform = daily.filter_by(platform=key)
            latest_platform_error = daily_platform.filter_by(status='error').order_by(BotJournalEvent.id.desc()).first()
            platform_diagnostics.append(dict(
                key=key,
                name=title,
                total=daily_platform.count(),
                success_count=daily_platform.filter_by(status='success').count(),
                error_count=daily_platform.filter_by(status='error').count(),
                active_queue=delivery_scope().filter(
                    BotDeliveryJob.platform == key,
                    BotDeliveryJob.status.in_(('pending', 'retry', 'sending', 'blocked', 'failed')),
                ).count(),
                avg_duration_ms=int(round(daily_platform.with_entities(func.avg(BotJournalEvent.duration_ms)).scalar() or 0)),
                latest_error_label=(ACTION_NAMES.get(latest_platform_error.action, latest_platform_error.action.replace('_', ' '))
                                    if latest_platform_error else None),
            ))
        latest_error = daily.filter_by(status='error').order_by(BotJournalEvent.id.desc()).first()
        bot_scene = dict(
            active_queue=delivery_counts['pending'] + delivery_counts['retry'] + delivery_counts['sending'],
            retry_jobs=delivery_counts['retry'],
            sending_jobs=delivery_counts['sending'],
            blocked_jobs=delivery_counts['blocked'],
            failed_jobs=delivery_counts['failed'],
            delivered_jobs=delivery_counts['delivered'],
            total_events=daily_totals['total'],
            success_events=daily_totals['success'],
            error_events=daily_totals['error'],
            avg_duration_ms=int(round(daily.with_entities(func.avg(BotJournalEvent.duration_ms)).scalar() or 0)),
            latest_error_label=(f"{PLATFORM_NAMES.get(latest_error.platform, latest_error.platform)} · "
                                f"{ACTION_NAMES.get(latest_error.action, latest_error.action.replace('_', ' '))}"
                                if latest_error else None),
            best_platform=(max(platform_diagnostics, key=lambda item: (item['success_count'] - item['error_count'], item['total']))['name']
                           if platform_diagnostics else None),
            platforms=platform_diagnostics,
        )
        # Latest durable delivery jobs; never include message text or chat IDs.
        delivery_query = delivery_scope()
        delivery_platform = request.args.get('delivery_platform', '').strip().lower()
        delivery_status = request.args.get('delivery_status', '').strip().lower()
        delivery_source = request.args.get('delivery_source', '').strip().lower()
        delivery_number = request.args.get('delivery_id', '').strip()[:20]
        if delivery_platform in ('telegram', 'vk', 'max'):
            delivery_query = delivery_query.filter_by(platform=delivery_platform)
        else:
            delivery_platform = ''
        if delivery_status in ('pending', 'retry', 'sending', 'blocked', 'delivered', 'failed'):
            delivery_query = delivery_query.filter_by(status=delivery_status)
        else:
            delivery_status = ''
        if delivery_source in ('lesson', 'event'):
            delivery_query = delivery_query.filter_by(source_type=delivery_source)
        else:
            delivery_source = ''
        if delivery_number.isdecimal():
            delivery_query = delivery_query.filter_by(id=int(delivery_number))
        else:
            delivery_number = ''
        try:
            delivery_page = min(max(int(request.args.get('delivery_page', 1)), 1), 100000)
        except (ValueError, TypeError):
            delivery_page = 1
        delivery_total = delivery_query.count()
        delivery_pages = max(1, (delivery_total + 29) // 30)
        delivery_page = min(delivery_page, delivery_pages)
        delivery_items = (delivery_query.order_by(BotDeliveryJob.id.desc())
                          .offset((delivery_page-1)*30).limit(30).all())
        latest = (query.with_entities(func.max(BotJournalEvent.id)).scalar() or 0)
        values = {k: filters[k] for k in ('platform', 'kind', 'status', 'start', 'end', 'q')}
        return render_template('activity/bot_journal.html', focus=focus, rows=rows, filters=values,
                               totals=daily_totals, delivery_counts=delivery_counts,
                               delivery_items=delivery_items,
                               delivery_platform=delivery_platform, delivery_status=delivery_status,
                               delivery_source=delivery_source, delivery_number=delivery_number,
                               delivery_page=delivery_page, delivery_pages=delivery_pages,
                               delivery_total=delivery_total,
                               total=total, page=page, pages=pages,
                               per_page=per_page, latest_id=latest,
                               platform_names=PLATFORM_NAMES, kind_names=KIND_NAMES,
                               status_names=STATUS_NAMES, action_names=ACTION_NAMES,
                               safe_summary=safe_summary, bot_scene=bot_scene)

    @admin_bp.post('/bot-journal/retry-deliveries')
    @super_admin_required
    def retry_failed_deliveries(current_user):
        from datetime import datetime
        from flask import flash, redirect
        from sqlalchemy import update, select
        ids = (BotDeliveryJob.query.filter_by(status='failed')
               .order_by(BotDeliveryJob.id.asc()).with_entities(BotDeliveryJob.id).limit(100).all())
        if ids:
            with db.engines['system'].begin() as connection:
                connection.execute(update(BotDeliveryJob.__table__).where(
                    BotDeliveryJob.id.in_([item[0] for item in ids])
                ).values(status='retry', attempts=0, next_attempt_at=datetime.utcnow(),
                         last_error=None, locked_until=None))
        flash(f'На повторную доставку поставлено: {len(ids)} сообщений.', 'success' if ids else 'warning')
        return redirect(url_for('admin.bot_journal'))

    @admin_bp.post('/bot-journal/delivery/<int:job_id>/retry')
    @super_admin_required
    def retry_single_delivery(job_id, current_user):
        """Retry only a non-terminal failure. Never replay a delivered message."""
        from config import settings
        token_settings = {'telegram': settings.BOT_TOKEN,
                          'vk': settings.VK_BOT_TOKEN,
                          'max': settings.MAX_BOT_TOKEN}
        job = BotDeliveryJob.query.filter_by(id=job_id).first()
        if not job:
            flash('Задание доставки не найдено.', 'warning')
        elif job.status not in ('failed', 'blocked'):
            flash('Повтор доступен только для ошибки или отсутствующего токена. Доставленные сообщения повторно не отправляются.', 'warning')
        elif not token_settings.get(job.platform):
            flash('Нельзя повторить отправку: сначала настройте токен соответствующего бота.', 'warning')
        else:
            with db.engines['system'].begin() as connection:
                changed = connection.execute(update(BotDeliveryJob.__table__).where(
                    BotDeliveryJob.id == job_id,
                    BotDeliveryJob.status.in_(('failed', 'blocked'))
                ).values(status='retry', attempts=0, next_attempt_at=datetime.utcnow(),
                         locked_until=None, last_error=None)).rowcount
            flash('Задание повторно поставлено в очередь.' if changed else 'Статус задания уже изменился.',
                  'success' if changed else 'warning')
        return redirect(url_for('admin.bot_journal', delivery_id=job_id))

    @admin_bp.get('/bot-journal/deliveries.csv')
    @super_admin_required
    def delivery_export(current_user):
        """Export operational metadata, never recipients, tokens or message texts."""
        platform = request.args.get('delivery_platform', '').strip().lower()
        status = request.args.get('delivery_status', '').strip().lower()
        source = request.args.get('delivery_source', '').strip().lower()
        number = request.args.get('delivery_id', '').strip()
        query = BotDeliveryJob.query
        if platform in ('telegram', 'vk', 'max'):
            query = query.filter_by(platform=platform)
        if status in ('pending', 'retry', 'sending', 'blocked', 'delivered', 'failed'):
            query = query.filter_by(status=status)
        if source in ('lesson', 'event'):
            query = query.filter_by(source_type=source)
        if number.isdecimal():
            query = query.filter_by(id=int(number))
        rows = query.order_by(BotDeliveryJob.id.desc()).limit(5000).all()
        output = io.StringIO(newline='')
        writer = csv.writer(output)
        writer.writerow(('ID', 'Тип', 'ID записи', 'Платформа', 'Статус', 'Попыток',
                         'Создано UTC', 'Следующая попытка UTC', 'Последняя попытка UTC', 'Доставлено UTC', 'Код ошибки'))
        safe_error_labels = {
            'provider_rejected': 'Отказ провайдера',
            'recipient_ineligible': 'Получатель недоступен',
        }
        for job in rows:
            stamp = lambda dt: dt.strftime('%Y-%m-%d %H:%M:%S') if dt else ''
            error_label = safe_error_labels.get(job.last_error, 'Техническая ошибка' if job.last_error else '')
            writer.writerow(map(spreadsheet_safe, (
                job.id, job.source_type or '', job.source_id or '', job.platform,
                job.status, job.attempts, stamp(job.created_at), stamp(job.next_attempt_at),
                stamp(job.last_attempt_at), stamp(job.delivered_at), error_label,
            )))
        response = Response('\ufeff'+output.getvalue(), mimetype='text/csv; charset=utf-8')
        response.headers['Content-Disposition'] = 'attachment; filename="bot-deliveries.csv"'
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @admin_bp.get('/bot-journal/check')
    @super_admin_required
    def bot_journal_check(current_user):
        filters = validated_filters(request.args)
        query = filtered_events(filters)
        latest = query.with_entities(func.max(BotJournalEvent.id)).scalar() or 0
        response = jsonify({'ok': True, 'latest_id': latest})
        response.headers['Cache-Control'] = 'no-store'
        return response

    @admin_bp.get('/bot-journal/export.csv')
    @super_admin_required
    def bot_journal_export(current_user):
        filters = validated_filters(request.args)
        rows = (filtered_events(filters).order_by(BotJournalEvent.id.desc()).limit(5000).all())
        out = io.StringIO(newline='')
        writer = csv.writer(out)
        writer.writerow(('UTC', 'Платформа', 'Тип', 'Событие', 'Результат',
                         'Псевдоним аккаунта', 'Описание', 'Время, мс'))
        for row in rows:
            writer.writerow(map(spreadsheet_safe, (
                row.created_at.strftime('%Y-%m-%d %H:%M:%S') if row.created_at else '',
                PLATFORM_NAMES.get(row.platform, row.platform),
                KIND_NAMES.get(row.kind, row.kind),
                ACTION_NAMES.get(row.action, row.action),
                STATUS_NAMES.get(row.status, row.status),
                row.actor_alias or '', safe_summary(row.summary), row.duration_ms or '',
            )))
        response = Response('\ufeff' + out.getvalue(), mimetype='text/csv; charset=utf-8')
        response.headers['Content-Disposition'] = 'attachment; filename="bot-journal.csv"'
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response
