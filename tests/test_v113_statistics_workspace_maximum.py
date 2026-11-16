from pathlib import Path
import json
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding='utf-8')


def test_statistics_workspace_has_shared_period_and_direction_filters():
    template = read('frontend/templates/statistics/overview.html')
    backend = read('backend/app/web_app.py')
    for token in ('stats-period-select', 'stats-date-from', 'stats-date-to', 'name="direction_id"', 'Применить', 'Сбросить'):
        assert token in template
    for token in ('_statistics_period_window', '_apply_statistics_day_window', 'selected_direction_id', 'period_filter'):
        assert token in backend
    assert 'EventDay.date >=' in backend and 'EventDay.date <' in backend


def test_statistics_interface_keeps_only_per_direction_and_detail_tables():
    template = read('frontend/templates/statistics/overview.html')
    backend = read('backend/app/web_app.py')
    for token in ('direction-statistics-table', 'attendance-statistics-table', 'event-statistics-table', 'decline-statistics-table'):
        assert token in template
    for removed in ('stats-trend-chart', 'attendance_trend', 'stats-insight-grid', 'stats-3d-stage'):
        assert removed not in template
    assert 'if active_section in ("overview", "directions")' in backend


def test_analytics_tables_have_search_sort_pagination_and_csv_export():
    template = read('frontend/templates/statistics/overview.html')
    script = read('frontend/assets/scripts/portal/statistics-workspace-v1913.js')
    for table_id in ('direction-statistics-table', 'attendance-statistics-table', 'event-statistics-table', 'decline-statistics-table'):
        assert f'id="{table_id}" data-statistics-table' in template
    for token in ('stats-table-toolbar', 'Строк на странице', 'sortBy', 'stats-table-pagination', 'Экспорт CSV', 'spreadsheet formula injection'):
        assert token in script


def test_statistics_asset_is_in_canonical_build_and_public_manifest():
    build = read('scripts/build_assets.py')
    manifest = json.loads(read('frontend/asset-manifest.json'))
    assert 'portal/statistics-workspace-v1913.css' in build
    assert 'portal/statistics-workspace-v1913.js' in build
    assert 'portal/statistics-workspace-v1913.css' in manifest['bundles']['site_css']['files']
    assert 'portal/statistics-workspace-v1913.js' in manifest['bundles']['site_js']['files']
    assert 'stats-filter-workspace' in read('static/css/site.bundle.css')
    assert 'spreadsheet formula injection' in read('static/js/site.bundle.js')


def test_statistics_template_compiles():
    env = Environment(loader=FileSystemLoader(str(ROOT / 'frontend/templates')))
    env.get_template('statistics/overview.html')


def _load_statistics_period_helper():
    import ast
    from datetime import datetime, timedelta

    source = read('backend/app/web_app.py')
    tree = ast.parse(source)
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_statistics_period_window')
    namespace = {'datetime': datetime, 'timedelta': timedelta}
    module = ast.Module(body=[function], type_ignores=[])
    exec(compile(module, 'web_app.py::_statistics_period_window', 'exec'), namespace)
    return namespace['_statistics_period_window']


def test_statistics_period_helper_handles_presets_inclusive_bounds_and_invalid_custom_ranges():
    from datetime import datetime, timedelta

    helper = _load_statistics_period_helper()
    today = datetime.utcnow().date()

    last_week = helper('7d')
    assert last_week['period'] == '7d'
    assert last_week['start_dt'].date() == today - timedelta(days=6)
    assert last_week['end_exclusive'].date() == today + timedelta(days=1)

    current_month = helper('month')
    assert current_month['start_dt'].date() == today.replace(day=1)
    previous_month = helper('prev_month')
    last_day_previous_month = today.replace(day=1) - timedelta(days=1)
    assert previous_month['start_dt'].date() == last_day_previous_month.replace(day=1)
    assert previous_month['end_exclusive'].date() == today.replace(day=1)

    reversed_range = helper('custom', '2026-11-15', '2026-11-01')
    assert reversed_range['date_from'] == '2026-11-01'
    assert reversed_range['date_to'] == '2026-11-15'
    one_sided = helper('custom', '2026-11-01', '')
    assert one_sided['is_filtered'] and one_sided['date_from'] == '2026-11-01'
    invalid = helper('custom', 'bad-date', '')
    assert invalid['period'] == 'all' and not invalid['is_filtered']


def test_statistics_drilldowns_preserve_filters_and_period_days_are_displayed_consistently():
    backend = read('backend/app/web_app.py')
    template = read('frontend/templates/statistics/overview.html')
    assert 'stats_section_urls=stats_section_urls' in backend
    assert "stats_query_args['direction_id'] = requested_direction_id" in backend
    assert 'days_in_scope' in backend
    assert 'row.days_in_scope' in template
    assert 'Период мероприятий' in template
    assert 'Данные ограничены выбранным периодом' not in template


def test_statistics_quick_period_presets_are_accessible_and_submit_real_filters():
    template = read('frontend/templates/statistics/overview.html')
    script = read('frontend/assets/scripts/portal/statistics-workspace-v1913.js')
    backend = read('backend/app/web_app.py')
    for period in ('7d', '30d', 'month', 'prev_month', '90d', 'year'):
        assert f"('{period}'," in template or f"('{period}','" in template
        assert f"period == '{period}'" in backend
    assert 'filterForm.requestSubmit()' in script
    assert 'Период мероприятий' in template


def test_statistics_navigation_and_shared_direction_table_remain_available():
    template = read('frontend/templates/statistics/overview.html')
    for section in ('overview', 'directions', 'attendance', 'events', 'declines'):
        assert f"stats_section_urls['{section}']" in template
    assert "active_section == 'overview' or active_section == 'directions'" in template
    assert 'Лидер по посещаемости' in template


def test_statistics_does_not_run_unrendered_monthly_chart_query():
    template = read('frontend/templates/statistics/overview.html')
    backend = read('backend/app/web_app.py')
    assert 'stats-trend-chart' not in template
    assert 'attendance_trend' not in backend
