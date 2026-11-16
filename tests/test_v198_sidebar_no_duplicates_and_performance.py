from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_leader_has_a_single_directions_destination_in_one_sidebar_section():
    base = read("frontend/templates/shared/base.html")
    assert base.count("Мои направления и участники") == 1
    assert "{% if session.user_role != 'leader' %}" in base
    assert "id=\"nav-section-people\"" in base
    # Leader's former second section is removed; its only directions link is in council nav.
    assert "Участники направлений</span>" not in base
    assert base.count("url_for('directions.directions_list')") == 2  # staff/non-staff role branches


def test_reports_entry_does_not_duplicate_analytics_naming():
    base = read("frontend/templates/shared/base.html")
    assert "Конструктор отчётов" in base
    assert "Создание отчётов и статистика" not in base


def test_sidebar_does_not_write_storage_on_every_scroll_or_force_layout_on_click():
    js = read("frontend/assets/scripts/portal/app.js")
    assert "sidebar.addEventListener('scroll'" not in js
    assert "window.addEventListener('pagehide', saveSidebarScroll)" in js
    assert "void element.offsetWidth" not in js
    assert "const pressableSelector = '.page .btn" in js
    assert ".sidebar .nav-link" not in js[js.index("const pressableSelector"):js.index("const reduceMotionQuery")]


def test_sidebar_hover_uses_lightweight_transitions():
    css = read("frontend/assets/styles/shared/sidebar-performance-v197.css")
    assert "transition: color .12s ease, background-color .12s ease, border-color .12s ease" in css
    assert "transform: none !important" in css
    assert "prefers-reduced-motion: reduce" in css


def test_sidebar_performance_styles_are_built_into_site_bundle():
    manifest = read("frontend/asset-manifest.json")
    bundle = read("static/css/site.bundle.css")
    assert "shared/sidebar-performance-v197.css" in manifest
    assert "v1.9.8 — keep sidebar interactions responsive" in bundle
