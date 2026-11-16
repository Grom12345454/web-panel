from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel):
    return (ROOT / rel).read_text(encoding='utf-8')


def test_employee_identity_includes_assigned_direction_in_shared_account_and_dashboard():
    base = read('frontend/templates/shared/base.html')
    app = read('backend/app/web_app.py')
    assert 'staff_role_caption|default' in base
    assert 'Сотрудник · {direction_name}' in app
    assert 'СОТРУДНИК · {home_name.upper()}' in app
    assert 'Сотрудник · все направления' in app


def test_chief_admin_monitoring_section_is_removed_from_sidebar():
    base = read('frontend/templates/shared/base.html')
    assert 'nav-section-monitoring' not in base
    assert 'nav-monitoring-group' not in base
    assert 'Мониторинг</span>' not in base


def test_main_admin_home_direction_card_and_setter_are_removed():
    accounts = read('frontend/templates/staff/accounts.html')
    routes = read('backend/app/services/staff_routes.py')
    assert 'staff-admin-home-direction' not in accounts
    assert 'Начальное направление панели главного администратора' not in accounts
    assert "@staff_bp.post('/admin-direction')" not in routes
    assert 'set_admin_home_direction' not in routes
    assert 'admin_home_direction=' not in routes


def test_statistics_navigation_is_a_single_sidebar_list_without_top_tabs_or_summary_card():
    base = read('frontend/templates/shared/base.html')
    stats = read('frontend/templates/statistics/overview.html')
    assert 'nav-link-group' not in base
    assert 'nav-submenu' not in base
    assert 'statistics-tabs' not in stats
    assert 'Разделы статистики' not in stats
    assert 'Персональная посещаемость каждого студента' not in stats
    for endpoint in (
        'stats.overview_statistics', 'stats.directions_statistics',
        'stats.attendance_statistics', 'stats.events_statistics',
        'stats.declines_statistics',
    ):
        assert f"url_for('{endpoint}')" in base


def test_statistics_template_uses_one_dynamic_page_heading_and_no_repeated_inner_headings():
    stats = read('frontend/templates/statistics/overview.html')
    assert 'statistics-page-heading' in stats
    assert 'Список подтверждённых посещений с разбивкой по студентам.' in stats
    assert 'Данные появятся после первых подтверждённых посещений.' in stats
    assert '<div class="section-title"><div><h1>' not in stats
