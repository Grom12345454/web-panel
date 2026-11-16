from pathlib import Path
import json
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_statistics_interface_is_table_only_and_has_no_visual_schemes():
    template = read("frontend/templates/statistics/overview.html")
    for removed in ("stats-3d", "stats-event-scheme", "stats-direction-scheme", "stats-trend-chart", "stats-insight-grid", "stats-detail-summary", "stats-attendance-ranking"):
        assert removed not in template
    for table_id in ("direction-statistics-table", "attendance-statistics-table", "event-statistics-table", "decline-statistics-table"):
        assert f'id="{table_id}" data-statistics-table' in template


def test_overview_and_directions_share_one_real_per_direction_table():
    template = read("frontend/templates/statistics/overview.html")
    backend = read("backend/app/web_app.py")
    assert "active_section == 'overview' or active_section == 'directions'" in template
    assert 'direction_stats|length' in template
    assert 'item.members' in template and 'item.attenders' in template
    assert 'item.event_count' in template and 'item.visit_count' in template
    assert 'if active_section in ("overview", "directions")' in backend


def test_3d_statistics_assets_are_removed_from_production_build():
    build = read("scripts/build_assets.py")
    manifest = json.loads(read("frontend/asset-manifest.json"))
    all_assets = manifest["bundles"]["site_css"]["files"] + manifest["bundles"]["site_js"]["files"]
    assert "portal/statistics-3d-professional-v1914.css" not in all_assets
    assert "portal/statistics-3d-workspace-v1914.js" not in all_assets
    assert "statistics-3d-professional-v1914.css" not in build
    assert "statistics-3d-workspace-v1914.js" not in build


def test_statistics_template_compiles():
    env = Environment(loader=FileSystemLoader(str(ROOT / "frontend/templates")))
    env.get_template("statistics/overview.html")
