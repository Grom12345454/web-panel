"""Regression tests for chief-admin signed PDF reports and action ledgers."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_signed_report_model_is_on_the_system_database_bind():
    system = (ROOT / "backend/app/database/system.py").read_text("utf8")
    database_init = (ROOT / "backend/app/database/__init__.py").read_text("utf8")
    for field in ("signature_code", "report_type", "report_key", "signer_user_id",
                  "signer_name", "signer_login", "content_sha256", "document_sha256", "signed_at"):
        assert field in system
    assert "__bind_key__ = \"system\"" in system
    assert "AdminReportSignature" in database_init


def test_pdf_routes_are_chief_admin_only_and_signature_is_persisted():
    source = (ROOT / "backend/app/web_app.py").read_text("utf8")
    for route in ("/event-reports/<int:event_id>.pdf",
                  "/direction-reports/<int:direction_id>.pdf",
                  "/user-activity/export.pdf"):
        assert route in source
    assert source.count("@super_admin_required") >= 3
    assert "db.session.add(signature_row)" in source
    assert "signature_row.document_sha256 = hashlib.sha256(pdf_bytes).hexdigest()" in source
    assert "source_hash = hashlib.sha256(canonical).hexdigest()" in source


def test_event_and_direction_reports_pull_business_actions_from_student_activity():
    source = (ROOT / "backend/app/web_app.py").read_text("utf8")
    assert "StudentActivity.quota_id == quota.id" in source
    assert "StudentActivity.direction_id.in_(direction_ids)" in source
    assert "StudentActivity.direction_id == direction.id" in source
    assert "EventQuotaDecline.query.filter_by(quota_id=quota.id)" in source
    # Free-text refusal explanations must not be placed in reports.
    assert "Причина" in source and "_report_safe_activity_description" in source


def test_admin_html_and_staff_journal_link_to_signed_pdfs():
    reports = (ROOT / "frontend/templates/events/reports.html").read_text("utf8")
    journal = (ROOT / "frontend/templates/activity/user_activity.html").read_text("utf8")
    nav = (ROOT / "frontend/templates/shared/base.html").read_text("utf8")
    assert "admin.direction_report_pdf" in reports
    assert "admin.direction_report_html" in reports or "admin.direction_report_html" in (ROOT / "frontend/templates/events/direction_report.html").read_text("utf8")
    assert "Последние выпущенные отчёты" in reports
    assert "admin.user_activity_pdf" in journal
    assert "Создание отчётов и статистика" in nav


def test_reportlab_generates_cyrillic_event_direction_and_staff_pdfs(tmp_path):
    import sys
    sys.path.insert(0, str(ROOT / "backend/app"))
    from services.report_pdfs import (
        build_event_report_pdf,
        build_direction_report_pdf,
        build_staff_journal_pdf,
    )

    signature = {
        "id": 7,
        "signature_code": "ADM-20261102-A1B2C3D4",
        "signer_name": "Главный администратор",
        "signer_login": "admin",
        "signed_at": "02.11.2026 10:15:00 UTC",
        "content_sha256": "a" * 64,
    }
    event_data = {
        "event_id": 9, "title": "Фестиваль студенческого совета",
        "description": "Официальное мероприятие", "location": "Главный корпус",
        "time_range": "10:00–18:00", "dates": "02.11.2026", "capacity": 80,
        "publication_status": "Опубликовано", "directions": ["Медиа"],
        "counts": {"registered": 4, "attended": 3, "absent": 1,
                   "cancelled": 0, "declined": 1, "total": 4},
        "attendance": [{"date": "02.11.2026", "name": "Иван Иванов",
                        "group": "ИС-21", "status": "Был"}],
        "declines": [{"name": "Мария Петрова", "date": "02.11.2026 09:00:00"}],
        "actions": [{"created_at": "02.11.2026 10:00:00", "direction": "Медиа",
                     "action": "Мероприятие опубликовано", "description": "Объявление отправлено."}],
    }
    direction_data = {
        "direction_id": 2, "name": "Медиа", "code": "MEDIA", "status": "Активное",
        "student_count": 12, "event_count": 1, "lesson_count": 3, "action_count": 1,
        "events": [{"title": "Фестиваль", "dates": "02.11.2026", "participants": 4, "attended": 3}],
        "actions": [{"created_at": "02.11.2026 10:00:00", "action": "Публикация",
                     "object": "Фестиваль", "description": "Отправлено объявление."}],
    }
    staff_data = {
        "total": 1, "filter_summary": "Операции за день",
        "entries": [{"created_at": "02.11.2026 10:00:00", "account": "Иван Иванов\nadmin",
                      "action": "Изменил данные", "section": "Администрирование / Мероприятия"}],
    }

    builders = [
        ("event.pdf", build_event_report_pdf, event_data),
        ("direction.pdf", build_direction_report_pdf, direction_data),
        ("staff.pdf", build_staff_journal_pdf, staff_data),
    ]
    for filename, builder, data in builders:
        output = tmp_path / filename
        pdf = builder(data, signature)
        output.write_bytes(pdf)
        assert pdf.startswith(b"%PDF-")
        assert len(pdf) > 10_000
