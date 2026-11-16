from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_monitoring_module_keeps_header_cards_and_note_in_one_column_flow():
    source = (ROOT / 'frontend/assets/styles/staff/monitoring-layout-v30.css').read_text(encoding='utf-8')
    bundle = (ROOT / 'static/css/site.bundle.css').read_text(encoding='utf-8')
    assert 'monitoring-layout-v30.css' in (ROOT / 'scripts/build_assets.py').read_text(encoding='utf-8')
    assert 'display: flex !important' in source
    assert '.uc-body[data-ui-version=\"11\"]' not in source
    assert '.uc-body .galaxy-dashboard > section.galaxy-ops-hub.mission-bot-hub' in source
    assert 'grid-template-columns: repeat(3, minmax(0, 1fr)) !important' in source
    assert 'grid-template-columns: repeat(2, minmax(0, 1fr)) !important' in source
    assert 'grid-template-columns: minmax(0, 1fr) !important' in source
    assert source in bundle


def test_messenger_monitoring_is_a_dedicated_super_admin_page():
    dashboard = (ROOT / 'frontend/templates/dashboard/overview.html').read_text(encoding='utf-8')
    template = (ROOT / 'frontend/templates/system/messenger_monitoring.html').read_text(encoding='utf-8')
    route = (ROOT / 'backend/app/web_app.py').read_text(encoding='utf-8')
    assert 'Мониторинг' in template and 'Telegram' in template and 'VK' in template and 'MAX' in template
    assert 'bot_health' not in dashboard and 'pending_delivery_jobs' not in dashboard
    start = route.index('@admin_bp.get("/messenger-monitoring")')
    end = route.index('@admin_bp.route("/calendar")', start)
    assert route[start:end].count('@super_admin_required') == 2
    assert "url_for('admin.messenger_monitoring')" in (ROOT / 'frontend/templates/shared/base.html').read_text(encoding='utf-8')
