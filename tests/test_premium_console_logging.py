"""Focused regressions for 2026 polish and privacy-safe diagnostics."""
import json
import logging
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_one_calendar_navigation_and_professional_assets():
    student = (ROOT / "frontend/assets/scripts/student/student_app.js").read_text("utf-8")
    nav = student[student.index("function shell(){"):student.index("function missionHighlights(){")]
    assert "['calendar','Календарь']" in nav
    assert "['events','Мероприятия']" not in nav
    assert 'mission-today-tile--calendar' in student
    assert "const rows=[['leadership'" in student
    dashboard = (ROOT / "frontend/templates/dashboard/overview.html").read_text("utf-8")
    assert "<h3>Единый календарь</h3>" in dashboard
    assert "url_for('admin.calendar')" in dashboard
    source = (ROOT / "scripts/build_assets.py").read_text("utf-8")
    for name in ("premium-console-2026.css", "premium-student-2026.css", "journal-ux.js"):
        assert name in source
    assert 'prefers-reduced-motion:reduce' in (ROOT / "frontend/assets/styles/staff/premium-console-2026.css").read_text("utf-8")


def test_audit_view_has_resilient_stats_and_copy_actions():
    web = (ROOT / "backend/app/web_app.py").read_text("utf-8")
    audit = (ROOT / "frontend/templates/activity/user_activity.html").read_text("utf-8")
    assert 'STAFF_AUDIT_ROLES' in web
    assert '_staff_audit_base_query()' in web
    assert 'is_staff_write_request' in web
    assert 'or status_code >= 400 or elapsed_ms >= 1500' in web
    assert 'Экспорт CSV' in audit and 'Подписанный PDF' in audit
    assert 'admin.user_activity_export' in audit
    assert 'request_id' in web
    assert 'RotatingFileHandler' in (ROOT / "backend/app/services/operational_logging.py").read_text("utf-8")


def test_json_logging_masks_secrets_and_is_bounded(tmp_path, monkeypatch):
    pytest.importorskip("flask")
    from services.operational_logging import JsonEventFormatter, configure_operational_logging
    record = logging.LogRecord("web_app", logging.WARNING, __file__, 1,
                               "failed access_token=abcdef1234 password:secret2", (), None)
    data = json.loads(JsonEventFormatter().format(record))
    assert data["level"] == "WARNING" and data["logger"] == "web_app"
    assert "abcdef1234" not in data["message"]
    assert "secret2" not in data["message"]
    assert "REDACTED" in data["message"]
    monkeypatch.setenv("SITE_LOG_DIR", str(tmp_path))
    before = list(logging.getLogger().handlers)
    try:
        path = configure_operational_logging(tmp_path)
        assert path == tmp_path / "portal.jsonl"
        assert configure_operational_logging(tmp_path) == path
        logging.getLogger("web_app").warning("private secret=abc123")
        for handler in logging.getLogger().handlers:
            handler.flush()
        lines = path.read_text("utf-8").splitlines()
        assert lines and "abc123" not in lines[-1]
        assert len([x for x in logging.getLogger().handlers if x not in before]) == 1
    finally:
        root = logging.getLogger()
        for handler in list(root.handlers):
            if handler not in before:
                root.removeHandler(handler)
                handler.close()
