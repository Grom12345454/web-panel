from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text('utf-8')


def test_report_workspace_has_analytics_staff_bot_and_per_event_exports():
    page = read('frontend/templates/events/reports.html')
    direction = read('frontend/templates/events/direction_report.html')
    for endpoint in ('admin.analytics_report_pdf', 'admin.user_activity_pdf', 'admin.bot_actions_report_pdf'):
        assert endpoint in page
    assert "url_for('admin.event_report_pdf', event_id=item.id)" in direction
    assert "url_for('admin.event_report_html', event_id=item.id)" in direction
    assert 'Посещений' in direction and 'Отказов по мероприятиям' in direction


def test_expanded_report_routes_are_chief_admin_only_and_separate_sources():
    source = read('backend/app/web_app.py')
    for route in ("@admin_bp.get('/analytics-report.pdf')", "@admin_bp.get('/bot-actions-report.pdf')",
                  "@admin_bp.get('/user-activity/export.pdf')", "@admin_bp.get('/event-reports/<int:event_id>.pdf')"):
        block = source[source.index(route):]
        assert '@super_admin_required' in block[:160]
    assert 'business_action_total' in source or "action_keys = tuple(BOT_MONITOR_ACTION_LABELS.keys())" in source
    assert 'system_event_total' in source or 'journal_rows' in source


def test_direction_report_includes_all_site_metrics_and_separate_event_totals():
    source = read('backend/app/web_app.py')
    start = source.index('def _direction_report_data(')
    end = source.index('\n\ndef _create_signed_report_response', start)
    function = source[start:end]
    for field in ('attendance_totals', 'member_status_counts', 'application_counts',
                  'lesson_status_counts', 'declined', 'attended', 'absent', 'cancelled',
                  'action_count', 'bot_action_count'):
        assert field in function


def test_successful_staff_get_does_not_write_synchronous_audit_row():
    source = read('backend/app/web_app.py')
    start = source.index('is_staff_write_request = bool(')
    end = source.index('return response', start)
    middleware = source[start:end]
    assert 'request.method in {"POST", "PUT", "PATCH", "DELETE"}' in middleware
    assert 'or is_staff_write_request' in middleware
    assert 'should_persist' in middleware
    assert 'or is_staff_action_request' not in middleware


def test_composite_indexes_cover_report_and_journal_queries():
    source = read('backend/app/database/helpers.py')
    for name in ('ix_student_activity_direction_created_id', 'ix_student_activity_quota_created_id',
                 'ix_http_audit_actor_created_id', 'ix_bot_journal_created_id',
                 'ix_participations_day_status_report', 'ix_event_declines_quota_created'):
        assert name in source


def test_new_pdf_builders_render_cyrillic_data(tmp_path):
    import sys
    sys.path.insert(0, str(ROOT / 'backend/app'))
    from services.report_pdfs import build_analytics_report_pdf, build_bot_journal_pdf
    signature = {'signature_code': 'ADM-20261102-12345678', 'signer_name': 'Главный администратор',
                 'signed_at': '02.11.2026 12:00 UTC', 'content_sha256': 'a' * 64}
    analytics = {'generated_at': '02.11.2026', 'totals': {'directions': 1, 'students': 10, 'events': 2,
                 'lessons': 3, 'activities': 5, 'staff_actions': 2, 'bot_business_actions': 4,
                 'bot_system_events': 7, 'declines': 1, 'signed_reports': 8},
                 'attendance': {'attended': 3, 'absent': 1},
                 'directions': [{'name': 'Медиа', 'students': 10, 'events': 2, 'actions': 5,
                                 'visits': 3, 'declines': 1}]}
    bots = {'total': 1, 'business_actions': 1, 'system_events': 0,
            'filter_summary': 'Сводка', 'entries': [{'created_at': '02.11.2026',
            'source': 'Бизнес-действие бота', 'platform': 'Telegram', 'actor': 'Бот',
            'action': 'Запись', 'object': 'Фестиваль', 'status': 'Зафиксировано', 'duration_ms': '—'}]}
    for filename, data, builder in [('analytics.pdf', analytics, build_analytics_report_pdf),
                                    ('bots.pdf', bots, build_bot_journal_pdf)]:
        payload = builder(data, signature)
        (tmp_path / filename).write_bytes(payload)
        assert payload.startswith(b'%PDF-') and len(payload) > 5000


def test_report_navigation_keeps_admin_section_active_for_all_report_files():
    template = read('frontend/templates/shared/base.html')
    for endpoint in ('admin.event_report_html', 'admin.analytics_report_pdf',
                     'admin.bot_actions_report_pdf', 'admin.user_activity_pdf'):
        assert endpoint in template
    assert "session.user_role == 'super_admin'" in template


def test_staff_and_bot_metrics_use_separate_actor_filters():
    source = read('backend/app/web_app.py')
    assert "HttpAuditLog.actor_user_id.isnot(None)" in source
    assert "HttpAuditLog.actor_role.in_(STAFF_AUDIT_ROLES)" in source
    assert "StudentActivity.action.in_(tuple(BOT_MONITOR_ACTION_LABELS.keys()))" in source
    # Do not use SQL LIKE here: underscores in bot action names are wildcards.
    assert "StudentActivity.action.like('bot_%')" not in source
