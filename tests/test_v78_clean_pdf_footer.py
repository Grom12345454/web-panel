"""Regression tests for the clean PDF footer and single watermark asset."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_all_report_builders_use_decorative_seal_and_single_brighter_watermark():
    import sys
    sys.path.insert(0, str(ROOT / "backend/app"))
    from services.report_pdfs import (
        build_analytics_report_pdf, build_bot_journal_pdf,
        build_direction_report_pdf, build_event_report_pdf,
        build_staff_journal_pdf,
    )

    signature = {
        "signature_code": "ADM-20261102-FOOTERTEST",
        "signer_name": "admin",
        "signed_at": "02.11.2026 10:47:30 UTC",
        "content_sha256": "d3883473482307e2" + "a" * 48,
    }
    event = {"event_id": 1, "title": "Тестовое мероприятие", "directions": [],
             "counts": {}, "attendance": [], "declines": [], "actions": []}
    direction = {"direction_id": 1, "name": "Тестовое направление", "events": [], "actions": []}
    staff = {"total": 0, "entries": []}
    analytics = {"generated_at": "02.11.2026", "totals": {}, "attendance": {},
                 "application_decisions": {}, "directions": []}
    bots = {"total": 0, "business_actions": 0, "system_events": 0, "entries": []}

    generated = [
        build_event_report_pdf(event, signature),
        build_direction_report_pdf(direction, signature),
        build_staff_journal_pdf(staff, signature),
        build_analytics_report_pdf(analytics, signature),
        build_bot_journal_pdf(bots, signature),
    ]

    source = (ROOT / "backend/app/services/report_pdfs.py").read_text("utf8")
    for removed in (
        "ПОДТВЕРЖДЕНО ГЛАВНЫМ АДМИНИСТРАТОРОМ",
        "Подпись администратора", "signature_code", "signer_name",
        "ВНУТРЕННЕЕ ПОДТВЕРЖДЕНИЕ", "pdf-watermark.png",
    ):
        assert removed not in source
    assert "class DocumentSeal" in source
    assert "СТУДЕНЧЕСКИЙ СОВЕТ" in source
    assert "ОТЧЁТ" in source
    assert "_append_document_seal" in source

    watermark = ROOT / "static" / "favicon-watermark.png"
    watermark_bytes = watermark.read_bytes()
    assert watermark_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    assert watermark_bytes[25] == 6
    assert not (ROOT / "static" / "pdf-watermark.png").exists()
    watermark_files = list((ROOT / "static").glob("*watermark*.png"))
    assert watermark_files == [watermark]

    from PIL import Image
    alpha = Image.open(watermark).getchannel("A")
    assert alpha.getextrema()[1] == 49

    for payload in generated:
        assert payload.startswith(b"%PDF-")
        assert len(payload) > 1_000
        assert b"/Subtype /Image" in payload
