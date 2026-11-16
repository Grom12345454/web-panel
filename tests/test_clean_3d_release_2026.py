"""Static release checks for clean labels, removed victory theme and enhanced depth."""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]


def content(name):
    return (ROOT / name).read_text(encoding="utf-8")


def test_removed_labels_not_in_app_template_or_generated_scripts():
    for path in ["frontend/templates/student/student_app.html", "frontend/templates/shared/base.html",
                 "frontend/templates/dashboard/overview.html", "frontend/templates/system/student_app_design.html",
                 "static/js/student-app.bundle.js", "static/js/site.bundle.js"]:
        data = content(path)
        for token in ["STUDENT SPACE · 2026", "LIVE · СИНХРОНИЗАЦИЯ", "День Победы",
                      "MISSION CONTROL <", "SPECIAL EDITION", "SEASONAL SERIES"]:
            assert token not in data, (path, token)


def test_removed_holiday_and_cosmos_theme_removed_from_catalog_and_styles():
    tree = ast.parse(content("backend/app/web_app.py"))
    theme_maps = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in {"STUDENT_APP_SEASONS", "STUDENT_APP_THEME_CSS"}:
                theme_maps[node.targets[0].id] = ast.literal_eval(node.value)
    assert len(theme_maps) == 2
    for entry in theme_maps.values():
        assert "victory_day" not in entry
        assert "cosmos" not in entry
        assert "march_8" in entry
    for asset in ["static/css/site.bundle.css", "static/css/student-app.bundle.css",
                  "static/css/student-app-theme-designer.css"]:
        assert "victory_day" not in content(asset)


def test_sync_engine_remains_but_badge_is_gone():
    js = content("static/js/student-app.bundle.js")
    assert "syncStudentApp" in js and "sync-state" in js
    assert "student-live-signal" not in js
    assert "student-festival-badge" not in content("frontend/templates/student/student_app.html")
    assert "holiday-active-chip" not in content("frontend/templates/shared/base.html")


def test_shared_final_visual_layer_built_once_and_accessible():
    style = content("frontend/assets/styles/shared/galaxy-clarity-2026.css")
    assert "prefers-reduced-motion:reduce" in style
    assert "pointer-events:none" in style
    assert "clarity-orbit" in style
    for bundle in ["static/css/site.bundle.css", "static/css/student-app.bundle.css"]:
        assert content(bundle).count("BEGIN frontend/assets/styles/shared/galaxy-clarity-2026.css") == 1
