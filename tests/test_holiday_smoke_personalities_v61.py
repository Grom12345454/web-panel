from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
THEMES = (
    "spring", "summer", "autumn", "winter", "march_8", "russia_day",
    "cosmonautics_day", "defender_day", "unity_day", "new_year",
    "flag_day", "constitution_day", "student_day",
)


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_each_builtin_theme_has_its_own_smoke_palette_and_motion():
    css = read("frontend/assets/styles/shared/holiday-smoke-personalities-v61.css")
    for theme in THEMES:
        assert f'data-theme="{theme}"' in css
        assert f'data-season="{theme}"' in css
        assert f'--theme-smoke-motion: smoke-drift-{theme.split("_")[0]}' in css
    for cloud in ("white", "blue", "red"):
        assert f".holiday-smoke.holiday-smoke--{cloud}" in css


def test_individual_smoke_styles_are_in_both_runtime_bundles():
    for bundle in ("static/css/site.bundle.css", "static/css/student-app.bundle.css"):
        css = read(bundle)
        assert "holiday-smoke-personalities-v61.css" in css
        for animation in (
            "smoke-drift-spring-v61", "smoke-drift-summer-v61",
            "smoke-drift-autumn-v61", "smoke-drift-winter-v61",
            "smoke-drift-march-v61", "smoke-drift-russia-v61",
            "smoke-drift-flag-v61", "smoke-drift-unity-v61",
            "smoke-drift-constitution-v61", "smoke-drift-cosmonautics-v61",
            "smoke-drift-defender-v61", "smoke-drift-newyear-v61",
            "smoke-drift-student-v61",
        ):
            assert animation in css
        assert "prefers-reduced-motion: reduce" in css


def test_manifest_and_builder_include_the_shared_smoke_layer_for_both_apps():
    manifest = json.loads(read("frontend/asset-manifest.json"))
    for key in ("site_css", "student_css"):
        files = manifest["bundles"][key]["files"]
        assert files.count("shared/holiday-smoke-personalities-v61.css") == 1
        assert files.index("shared/holiday-smoke-personalities-v61.css") > files.index("shared/theme-smoke-v60.css")
    builder = read("scripts/build_assets.py")
    assert builder.count("'shared/holiday-smoke-personalities-v61.css'") == 2
