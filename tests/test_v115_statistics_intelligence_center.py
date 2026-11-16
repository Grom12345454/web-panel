from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_statistics_intelligence_center_navigation_preserves_existing_sections():
    template = (ROOT / 'frontend/templates/statistics/overview.html').read_text(encoding='utf-8')
    for section in ('overview', 'directions', 'attendance', 'events', 'declines'):
        assert f"stats_section_urls['{section}']" in template
        assert f"active_section == '{section}'" in template
    assert 'stats-command-header' in template
    assert 'stats-module-nav' in template


def test_statistics_workspace_uses_natural_height_and_bottom_fill():
    css = (ROOT / 'frontend/assets/styles/portal/statistics-tables-v1917.css').read_text(encoding='utf-8')
    assert 'height: auto !important' in css
    assert 'flex: 0 0 auto !important' in css
    assert 'min-height: 0 !important' in css
    final_css = (ROOT / 'frontend/assets/styles/portal/statistics-analytics-v1916.css').read_text(encoding='utf-8')
    assert '.page:has(.stats-command-header) > *' in final_css
    assert 'flex: 0 0 auto !important' in final_css


def test_statistics_asset_sources_are_in_the_manifest():
    manifest = (ROOT / 'frontend/asset-manifest.json').read_text(encoding='utf-8')
    assert 'portal/statistics-3d-professional-v1914.css' not in manifest
    assert 'portal/statistics-analytics-v1916.css' in manifest
    assert 'portal/statistics-3d-workspace-v1914.js' not in manifest


def test_statistics_tables_match_the_active_students_table_pattern():
    template = (ROOT / 'frontend/templates/statistics/overview.html').read_text(encoding='utf-8')
    script = (ROOT / 'frontend/assets/scripts/portal/statistics-workspace-v1913.js').read_text(encoding='utf-8')
    css = (ROOT / 'frontend/assets/styles/portal/statistics-tables-v1917.css').read_text(encoding='utf-8')
    for table_id in ('direction-statistics-table', 'attendance-statistics-table', 'event-statistics-table', 'decline-statistics-table'):
        table_pos = template.index(f'id="{table_id}"')
        wrapper_pos = template.rfind('stats-data-table-card', 0, table_pos)
        assert wrapper_pos >= 0, f'{table_id} must use the shared Active Students table card'
    assert 'stats-data-bar-cell' not in script
    assert 'font-variant-numeric: tabular-nums' in css or 'tabular-nums' in css
    assert 'stats-table-toolbar' in css and 'stats-table-pagination' in css


def test_statistics_parent_main_no_longer_forces_a_viewport_height():
    css = (ROOT / 'frontend/assets/styles/portal/statistics-analytics-v1916.css').read_text(encoding='utf-8')
    assert 'align-items: flex-start !important' in css
    assert 'min-height: 0 !important' in css
    assert 'height: auto !important' in css
