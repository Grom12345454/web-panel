from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def read(path):
    return (ROOT / path).read_text(encoding="utf-8")

def test_direction_pdf_no_longer_prints_internal_direction_id_and_embeds_full_event_reports():
    pdf = read("backend/app/services/report_pdfs.py")
    direction = pdf[pdf.index("def build_direction_report_pdf"):pdf.index("def build_staff_journal_pdf")]
    assert "ID направления:" not in direction
    assert "data.get(\"event_reports\")" in direction
    assert "_event_report_story(event_report)" in direction
    assert "ПОДРОБНЫЙ ОТЧЁТ ПО МЕРОПРИЯТИЮ" in direction

def test_direction_pdf_uses_bulk_event_report_data_and_does_not_load_unused_direction_journal_rows():
    source = read("backend/app/web_app.py")
    direction = source[source.index("def _direction_report_data("):source.index("def _report_archive_root(")]
    assert "include_event_reports=False" in direction
    assert "_direction_event_report_details(event_ids) if include_event_reports else []" in direction
    assert "if action_page is not None:" in direction
    assert "action_query.all()" in direction
    route = source[source.index("def direction_report_pdf("):source.index("@admin_bp.get('/report-archive')")]
    assert "include_event_reports=True" in route

def test_direction_html_does_not_print_direction_database_id_as_heading():
    template = read("frontend/templates/events/direction_report.html")
    assert "ОТЧЁТ НАПРАВЛЕНИЯ</div>" in template
    assert "ОТЧЁТ НАПРАВЛЕНИЯ / #{{ report.direction_id }}" not in template

def test_canvas_starfield_uses_lower_animation_budget_for_economy_devices():
    for path in ("frontend/assets/scripts/portal/space.js", "frontend/assets/standalone/js/space.js"):
        source = read(path)
        assert "const economyMode = document.body.classList.contains('perf-economy')" in source
        assert "const frameInterval = economyMode ? 88 : 55" in source
        assert "if (reduceMotion || economyMode || width < 360" in source
        assert "economyMode ? 1" in source


def test_reports_workspace_exposes_each_event_pdf_and_html_under_its_direction():
    source = read("backend/app/web_app.py")
    route = source[source.index("def event_reports("):source.index("@admin_bp.get('/direction-reports/")]
    template = read("frontend/templates/events/reports.html")
    assert "EventQuota.event_title" in route
    assert "events_by_direction" in route
    assert "'events': sorted(events_by_direction" in route
    assert "item.events|length" in template
    assert "admin.event_report_html" in template
    assert "admin.event_report_pdf" in template
    assert "подробные отчёты по каждому мероприятию" in template


def test_standalone_starfield_obeys_frame_budget_and_reduces_work_on_economy_devices():
    source = read("frontend/assets/standalone/js/space.js")
    assert "const frameInterval = economyMode ? 88 : 55" in source
    assert "now - lastDrawAt < frameInterval" in source
    assert "economyMode ? 1" in source
    assert "width < 700 ? 15000 : 13500" in source
    assert "if (!economyMode && s.radius > 1.05)" in source
    assert "if (!economyMode) {" in source
