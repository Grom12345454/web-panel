from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def test_each_direction_has_separate_chief_admin_html_and_signed_pdf_actions():
    source = (ROOT / 'backend/app/web_app.py').read_text('utf8')
    workspace = (ROOT / 'frontend/templates/events/reports.html').read_text('utf8')
    detail = (ROOT / 'frontend/templates/events/direction_report.html').read_text('utf8')
    assert "@admin_bp.get('/direction-reports/<int:direction_id>')" in source
    assert "def direction_report_html" in source
    assert "admin.direction_report_html" in workspace
    assert "admin.direction_report_pdf" in workspace
    assert 'Полная история действий направления' in detail

def test_report_workspace_uses_aggregates_and_does_not_eagerly_render_event_tree():
    source = (ROOT / 'backend/app/web_app.py').read_text('utf8')
    start = source.index("@admin_bp.route('/event-reports')")
    end = source.index("@admin_bp.get('/direction-reports/<int:direction_id>')", start)
    route = source[start:end]
    assert 'group_by(StudentActivity.direction_id, StudentActivity.quota_id)' in route
    assert 'group_by(student_directions.c.direction_id)' in route
    assert 'for quota in quotas' not in route
    assert 'selectinload(EventQuota.days)' not in route
