from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_archive_routes_are_classified_under_work_area_for_non_staff_roles():
    base = read("frontend/templates/shared/base.html")
    work_assignment = "{% set work_active = ep == 'admin.dashboard' or ep.startswith('admin.report_archive') %}"
    assert work_assignment in base
    system_start = base.index("{% set system_active =")
    system_end = base.index("%}", system_start)
    system_expression = base[system_start:system_end]
    assert "admin.report_archive" not in system_expression


def test_archive_link_is_present_once_in_each_role_navigation_branch():
    base = read("frontend/templates/shared/base.html")
    staff_start = base.index("{% if session.user_role == 'staff' %}")
    nonstaff_start = base.index("{% else %}", staff_start)
    staff_nav = base[staff_start:nonstaff_start]
    nonstaff_nav = base[nonstaff_start:base.index("</aside>", nonstaff_start)]
    assert staff_nav.count("url_for('admin.report_archive')") == 1
    assert nonstaff_nav.count("url_for('admin.report_archive')") == 1
    assert "ep.startswith('admin.report_archive')" in staff_nav
    assert "ep.startswith('admin.report_archive')" in nonstaff_nav


def test_active_route_section_overrides_stale_server_section_hint():
    source = read("frontend/assets/scripts/portal/app.js")
    assert "const currentRouteSection = currentNavLink?.closest('.nav-section')" in source
    assert "const preferredOpenSection = currentRouteSection || serverMarkedSection || null" in source
    assert "section === preferredOpenSection" in source
    assert "content.hidden = !value" in source


def test_sidebar_scroll_memory_is_scoped_to_role_and_current_navigation_section():
    source = read("frontend/assets/scripts/portal/app.js")
    assert "student-council:admin-sidebar-scroll:${roleKey}:${sectionKey}" in source
    assert "student-council:admin-sidebar-scroll';" not in source
    assert "window.addEventListener('pagehide', saveSidebarScroll)" in source
    assert "sidebar.addEventListener('scroll'" not in source


def test_archive_page_keeps_its_own_template_and_archive_actions():
    source = read("backend/app/web_app.py")
    template = read("frontend/templates/events/report_archive.html")
    route = source[source.index("@admin_bp.get('/report-archive')"):source.index("@admin_bp.get('/report-archive/<int:document_id>/download')")]
    assert "def report_archive(current_user):" in route
    assert "'events/report_archive.html'" in route
    assert "render_template(" in route
    assert "Архив отчётов" in template
    assert "Доступные документы" in template
    assert "url_for('admin.report_archive_download'" in template
    assert "url_for('admin.dashboard')" not in route


def test_system_admin_routes_still_map_to_the_administration_section():
    base = read("frontend/templates/shared/base.html")
    system_start = base.index("{% set system_active =")
    system_end = base.index("%}", system_start)
    system_expression = base[system_start:system_end]
    for endpoint in ("staff.accounts", "admin.manage_leadership", "admin.student_app_design", "admin.system_maintenance", "admin.system_runtime"):
        assert endpoint in system_expression
