from pathlib import Path
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]


def test_restore_action_is_super_admin_post_and_uses_verified_restore_service():
    source = (ROOT / 'backend/app/web_app.py').read_text('utf-8')
    assert '@admin_bp.route("/system/restore", methods=["POST"])' in source
    assert '@super_admin_required' in source[source.index('@admin_bp.route("/system/restore"'):source.index('@admin_bp.route("/system/clear-events"')]
    assert 'restore_database_backup(archive_name, db)' in source


def test_restore_service_validates_manifest_integrity_and_creates_safety_backup():
    source = (ROOT / 'backend/app/services/maintenance.py').read_text('utf-8')
    for token in ('archive.testzip()', 'PRAGMA integrity_check', 'create_database_backup(automatic=False)', 'database_ext.session.remove()', 'os.replace('):
        assert token in source


def test_maintenance_page_has_explicit_restore_action_and_confirmation():
    source = (ROOT / 'frontend/templates/system/maintenance.html').read_text('utf-8')
    assert "url_for('admin.restore_database_backup_action')" in source
    assert 'data-confirm=' in source
    assert 'backup_name' in source


def test_statistics_overview_is_a_single_per_direction_table_not_a_visual_dashboard():
    source = (ROOT / 'frontend/templates/statistics/overview.html').read_text('utf-8')
    assert 'direction-statistics-table' in source
    assert 'Лидер по посещаемости' in source
    for removed in ('stats-insight-grid', 'stats-relationship-flow', 'stats-3d-stage', 'stats-trend-chart'):
        assert removed not in source


def test_federal_holiday_themes_have_complete_css_palettes():
    source = (ROOT / 'backend/app/web_app.py').read_text('utf-8')
    for key in ('christmas', 'spring_labour_day', 'victory_day'):
        assert f'"{key}":' in source
        assert f'"{key}": {{"season-accent"' in source


def test_theme_selection_saves_without_reload_with_csrf():
    template = (ROOT / 'frontend/templates/system/student_app_design.html').read_text('utf-8')
    script = (ROOT / 'frontend/assets/standalone/js/student-app-theme-designer.js').read_text('utf-8')
    assert 'data-live-url' in template
    assert "X-CSRF-Token" in script and "csrf" in script
    assert "method:'POST'" in script
    assert "credentials:'same-origin'" in script


def test_templates_compile_and_statistics_css_is_bundled():
    env = Environment(loader=FileSystemLoader(str(ROOT / 'frontend/templates')))
    env.get_template('statistics/overview.html')
    env.get_template('system/maintenance.html')
    env.get_template('system/student_app_design.html')
    css = (ROOT / 'static/css/site.bundle.css').read_text('utf-8')
    assert 'stats-table-toolbar' in css
