from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "app"))


def test_direction_pdf_embeds_full_standalone_event_report_content():
    from services.report_pdfs import build_direction_report_pdf

    event = {
        "event_id": 91,
        "title": "Тестовое мероприятие: День науки",
        "description": "Подробное описание мероприятия",
        "location": "Большой зал",
        "time_range": "12:00–16:00",
        "dates": "03.11.2026",
        "capacity": 40,
        "publication_status": "Опубликовано",
        "directions": ["Наука"],
        "counts": {"registered": 2, "attended": 1, "absent": 1, "cancelled": 0, "declined": 1, "total": 2},
        "attendance": [{"date": "03.11.2026", "name": "Иван Иванов", "group": "10А", "status": "Был"}],
        "declines": [{"name": "Пётр Петров", "date": "02.11.2026 12:30"}],
        "actions": [{"created_at": "02.11.2026", "direction": "Наука", "action": "Создание", "description": "Создано мероприятие"}],
    }
    data = {
        "name": "Наука", "student_count": 12, "event_count": 1, "lesson_count": 3,
        "attendance_totals": {"registered": 2, "attended": 1, "absent": 1, "cancelled": 0, "declined": 1},
        "member_status_counts": {"Активные": 12}, "application_counts": {"Принято": 4},
        "lesson_status_counts": {"Проведено": 3},
        "events": [{"title": event["title"], "dates": event["dates"], "participants": 2,
                    "attended": 1, "absent": 1, "cancelled": 0, "declined": 1}],
        "event_reports": [event],
    }
    pdf = build_direction_report_pdf(data, signature={"signature_code": "PRIVATE-TEST"})
    assert pdf.startswith(b"%PDF-")
    pdftotext = shutil.which("pdftotext")
    if not pdftotext:
        import pytest
        pytest.skip("pdftotext is not installed")
    pdf_path = ROOT / "tests" / ".tmp-direction-event-appendix.pdf"
    text_path = ROOT / "tests" / ".tmp-direction-event-appendix.txt"
    try:
        pdf_path.write_bytes(pdf)
        subprocess.run([pdftotext, str(pdf_path), str(text_path)], check=True)
        text = " ".join(text_path.read_text("utf-8").split())
    finally:
        pdf_path.unlink(missing_ok=True)
        text_path.unlink(missing_ok=True)
    for expected in (
        "ПОДРОБНЫЙ ОТЧЁТ ПО МЕРОПРИЯТИЮ",
        "Тестовое мероприятие: День науки",
        "Подробное описание мероприятия",
        "Иван Иванов", "Пётр Петров",
        "Список участников и посещаемость",
        "Официальные отказы от участия",
        "Действия направлений и мероприятия из журнала базы данных",
    ):
        assert expected in text, expected
    assert "ID направления" not in text
