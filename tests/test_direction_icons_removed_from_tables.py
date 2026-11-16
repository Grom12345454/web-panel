"""Built-in direction labels stay clean and never repeat icon glyphs in tables."""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]

def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")

def test_all_default_direction_seeds_are_icon_free_and_legacy_rows_are_cleared():
    source = read("backend/app/database/helpers.py")
    tree = ast.parse(source)
    init_db = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "init_db")
    seed = next(node for node in ast.walk(init_db) if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "base" for target in node.targets))
    base = ast.literal_eval(seed.value)
    assert len(base) == 8
    assert all("icon" not in item for item in base)
    assert "existing_direction.icon = None" in source
    assert "volunteer_direction.icon = None" in source

def test_direction_icons_are_not_rendered_in_data_tables():
    checks = {
        "frontend/templates/statistics/overview.html": ("item.direction.icon", "direction-table-icon"),
        "frontend/templates/students/list.html": ("direction.icon",),
        "frontend/templates/students/most_active.html": ("row.direction.icon",),
        "frontend/templates/students/quota_stats.html": ("s.direction.icon",),
        "frontend/templates/students/blocked.html": ("item.direction.icon",),
        "frontend/templates/activity/bot_activity_table.html": ("item.direction.icon",),
    }
    for filename, forbidden in checks.items():
        template = read(filename)
        for fragment in forbidden:
            assert fragment not in template, f"{fragment} still appears in {filename}"

def test_direction_table_styles_no_longer_reserve_an_icon_column():
    css = read("frontend/assets/styles/portal/page-components-v9.css")
    assert ".direction-table-icon" not in css
    legacy_css = read("frontend/assets/standalone/css/page-components-v9.css")
    assert ".direction-table-icon" not in legacy_css
    activity_template = read("frontend/templates/activity/bot_activity_table.html")
    assert "event.direction_icon" not in activity_template
