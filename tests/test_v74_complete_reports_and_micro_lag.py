from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def read(path):
    return (ROOT / path).read_text(encoding="utf-8")

def test_direction_report_has_aggregated_status_and_event_metrics():
    source = read("backend/app/web_app.py")
    block = source[source.index("def _direction_report_data("):source.index("def _create_signed_report_response(")]
    for field in ("attendance_totals", "member_status_counts", "application_counts", "lesson_status_counts"):
        assert field in block
    for metric in ("attended", "absent", "cancelled", "declined"):
        assert metric in block
    assert "group_by(EventDay.id)" in block

def test_every_event_has_dedicated_super_admin_html_and_signed_pdf():
    source = read("backend/app/web_app.py")
    assert "@admin_bp.get('/event-reports/<int:event_id>')" in source
    assert "def event_report_html" in source
    assert "def event_report_pdf" in source
    assert "@super_admin_required\ndef event_report_html" in source
    assert "@super_admin_required\ndef event_report_pdf" in source
    direction = read("frontend/templates/events/direction_report.html")
    assert "admin.event_report_html" in direction and "admin.event_report_pdf" in direction
    event = read("frontend/templates/events/event_report.html")
    assert "report.attendance" in event and "report.declines" in event and "report.actions" in event

def test_analytics_staff_and_bot_exports_are_real_signed_super_admin_routes():
    source = read("backend/app/web_app.py")
    for name in ("analytics_report_pdf", "user_activity_pdf", "bot_actions_report_pdf"):
        assert f"def {name}" in source
        assert f"@super_admin_required\ndef {name}" in source
    workspace = read("frontend/templates/events/reports.html")
    assert "admin.analytics_report_pdf" in workspace
    assert "admin.user_activity_pdf" in workspace
    assert "admin.bot_actions_report_pdf" in workspace
    assert "admin.user_activity_log" in workspace and "admin.messenger_monitoring" in workspace

def test_pdf_builders_include_site_analytics_and_bot_journal():
    source = read("backend/app/services/report_pdfs.py")
    assert "def build_analytics_report_pdf" in source
    assert "def build_bot_journal_pdf" in source
    assert "Заявления и решения по направлениям" in source
    direction = source[source.index("def build_direction_report_pdf"):source.index("def build_staff_journal_pdf")]
    for label in ("Посещений", "Пропусков", "Отмен участия", "Официальных отказов", "История заявок и решений"):
        assert label in direction

def test_bot_polling_is_less_aggressive_to_reduce_periodic_load():
    source = read("frontend/assets/standalone/js/bot-activity-live.js")
    assert "const visibleInterval = 30_000" in source
    assert "const hiddenInterval = 90_000" in source
    bundled = read("frontend/assets/scripts/portal/bot-activity-live.js")
    assert "const visibleInterval = 45_000" in bundled
    assert "const hiddenInterval = 120_000" in bundled
    messenger = read("frontend/assets/scripts/portal/messenger-monitoring-v63.js")
    assert "}, 45000);" in messenger


def test_whole_site_analytics_uses_aggregates_not_one_full_direction_report_per_direction():
    source = read("backend/app/web_app.py")
    start = source.index("def analytics_report_pdf(")
    end = source.index("@admin_bp.get('/bot-actions-report.pdf')", start)
    section = source[start:end]
    assert "group_by(QuotaDirection.direction_id)" in section
    assert "group_by(StudentActivity.direction_id, StudentActivity.quota_id)" in section
    assert "_direction_report_data(" not in section
