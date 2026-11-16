"""The direction PDF omits internal identifiers and action-ledger details."""
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def test_direction_pdf_hides_requested_fields_and_action_history(tmp_path):
    if not shutil.which("pdftotext"):
        return
    sys.path.insert(0, str(ROOT / "backend/app"))
    from services.report_pdfs import build_direction_report_pdf

    payload = build_direction_report_pdf({
        "direction_id": 17,
        "name": "Тестовое направление",
        "code": "SECRET-CODE-7788",
        "status": "Секретный статус",
        "student_count": 10,
        "event_count": 2,
        "lesson_count": 3,
        "action_count": 99,
        "bot_action_count": 33,
        "attendance_totals": {"registered": 8, "attended": 6},
        "events": [],
        "actions": [{
            "created_at": "02.11.2026 12:00:00",
            "action": "СЕКРЕТНОЕ ДЕЙСТВИЕ",
            "object": "СЕКРЕТНЫЙ ОБЪЕКТ",
            "description": "СЕКРЕТНОЕ ОПИСАНИЕ",
        }],
        "member_status_counts": {},
        "application_counts": {},
        "lesson_status_counts": {},
    }, signature={"signature_code": "PRIVATE-SIGNATURE"})

    pdf_path = tmp_path / "direction.pdf"
    text_path = tmp_path / "direction.txt"
    pdf_path.write_bytes(payload)
    subprocess.run(["pdftotext", str(pdf_path), str(text_path)], check=True)
    text = text_path.read_text("utf8")

    for forbidden in (
        "Полная история действий направления",
        "Код направления", "SECRET-CODE-7788",
        "Статус\n", "Секретный статус",
        "Записей в журнале бизнес-действий",
        "Из них бизнес-действий ботов",
        "99", "33", "СЕКРЕТНОЕ ДЕЙСТВИЕ",
        "СЕКРЕТНЫЙ ОБЪЕКТ", "СЕКРЕТНОЕ ОПИСАНИЕ",
    ):
        assert forbidden not in text

    for retained in ("Тестовое направление", "Участники", "Мероприятия", "Занятия", "Посещений"):
        assert retained in text
