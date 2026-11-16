from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_statistics_report_has_one_table_and_clear_workflow_sections():
    template = read("frontend/templates/statistics/overview.html")
    assert template.count("<table ") == 1
    assert "01" in template and "Параметры отчёта" in template
    assert "02" in template and "Рабочая таблица" in template
    assert 'id="stats-period-select"' in template
    assert 'id="stats-date-from"' in template
    assert 'id="stats-date-to"' in template
    assert 'name="direction_id"' in template


def test_local_table_controls_cover_search_filters_and_recovery():
    template = read("frontend/templates/statistics/overview.html")
    for control in (
        'id="direction-search"',
        'id="direction-filter"',
        'id="direction-local-reset"',
        'value="active"',
        'value="inactive"',
        'value="visits"',
        'value="no-visits"',
        'value="events"',
        'value="members"',
    ):
        assert control in template


def test_table_script_supports_sort_pagination_filtered_export_and_keyboard_search():
    script = read("frontend/assets/scripts/portal/statistics-workspace-v1913.js")
    assert "sortBy(index)" in script
    assert "pageRows = Number(pageSize.value) || 25" in script
    assert "filteredRows.forEach" in script
    assert "cell.textContent" in script
    assert "event.key === '/'" in script
    assert "event.key === 'Escape'" in script
    assert "mode === 'inactive'" in script


def test_statistics_ux_styles_are_built_and_mobile_adaptive():
    build = read("scripts/build_assets.py")
    css = read("frontend/assets/styles/portal/statistics-ux-v1919.css")
    assert "portal/statistics-ux-v1919.css" in build
    assert "@media (max-width:760px)" in css
    assert "stats-workflow-heading" in css
    assert "direction-table-footnote" in css
