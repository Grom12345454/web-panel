from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding='utf-8')


def test_statistics_navigation_has_one_canonical_entry_for_both_roles():
    base = read('frontend/templates/shared/base.html')
    assert base.count('Общая таблица') == 2
    assert "url_for('stats.overview_statistics')" in base
    assert 'По направлениям</span>' not in base
    assert 'Посещаемость</span>' not in base
    assert 'Отказы</span>' not in base


def test_daily_shortcuts_are_connected_to_real_table_filters():
    template = read('frontend/templates/statistics/overview.html')
    script = read('frontend/assets/scripts/portal/statistics-workspace-v1913.js')
    for mode in ('all', 'active', 'no-visits', 'inactive'):
        assert f'data-direction-preset="{mode}"' in template
    assert 'button.dataset.directionPreset' in script
    assert "directionMode.value = button.dataset.directionPreset || 'all'" in script
    assert 'syncDirectionPresets();' in script


def test_statistics_bottom_layout_override_is_last_in_bundle_sources():
    build = read('scripts/build_assets.py')
    css = read('frontend/assets/styles/portal/statistics-daily-ux-v1920.css')
    manifest = read('frontend/asset-manifest.json')
    assert "'portal/statistics-daily-ux-v1920.css',\n]" in build
    assert 'statistics-daily-ux-v1920.css' in manifest
    assert '.app-shell > .main {\n  display:flex !important; flex:1 1 auto !important;' in css
    assert 'min-height:0 !important; height:auto !important;' in css
