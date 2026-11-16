from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding='utf-8')


def test_statistics_template_contains_exactly_one_table_and_no_visual_schemes():
    template = read('frontend/templates/statistics/overview.html')
    assert template.count('<table ') == 1
    assert 'direction-statistics-table' in template
    for forbidden in ('stats-3d', 'canvas', 'stats-event-scheme', 'stats-direction-scheme', 'stats-trend-chart', 'attendance-statistics-table', 'event-statistics-table', 'decline-statistics-table'):
        assert forbidden not in template
    for column in ('Активные участники', 'Студенты с явкой', 'Мероприятия', 'Уникальные посещения', 'Лидер по посещаемости'):
        assert column in template


def test_all_legacy_statistics_urls_use_the_same_per_direction_report():
    backend = read('backend/app/web_app.py')
    assert 'active_section = "overview"' in backend
    assert 'if active_section in ("overview", "directions"):' in backend


def test_statistics_layout_does_not_reserve_viewport_height():
    css = read('frontend/assets/styles/portal/statistics-tables-v1917.css')
    assert 'height: auto !important' in css
    assert 'min-height: 0 !important' in css
