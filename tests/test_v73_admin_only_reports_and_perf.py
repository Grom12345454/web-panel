from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def read(path):
    return (ROOT / path).read_text(encoding="utf-8")

def test_reports_are_in_administration_and_not_analytics():
    nav = read("frontend/templates/shared/base.html")
    assert "Создание отчётов и статистика" in nav
    assert "admin.event_reports" in nav
    assert "{% if session.user_role == 'super_admin' %}" in nav
    assert "Отчёты направлений и мероприятий" not in nav
    admin_block = nav[nav.index("Администрирование"):nav.index("Мониторинг")]
    assert "Создание отчётов и статистика" in admin_block

def test_analytics_routes_allow_observer_read_only_and_keep_exports_super_admin_only():
    source = read("backend/app/web_app.py")
    for name in ("overview_statistics", "direction_statistics", "most_active_students"):
        assert f"@analytics_view_required\ndef {name}" in source
    assert "if current_user.role == UserRole.OBSERVER.value and request.method not in" in source
    for name in ("analytics_report_pdf", "user_activity_pdf", "bot_actions_report_pdf"):
        section = source[source.index(f"def {name}(") - 100:source.index(f"def {name}(")]
        assert "@super_admin_required" in section


def test_dashboard_uses_aggregates_and_does_not_load_event_object_graph():
    source = read("backend/app/web_app.py")
    start = source.index('def dashboard(current_user):')
    end = source.index('\nBOT_MONITOR_ACTION_LABELS', start)
    dashboard = source[start:end]
    assert "selectinload(EventQuota.days).selectinload(EventDay.participations)" not in dashboard
    assert "EventQuota.query.count()" in dashboard
    assert "EventDay.daily_places" in dashboard and "group_by(" in dashboard
    assert ".limit(4)" in dashboard
    assert "d.questions" not in dashboard

def test_statistics_view_loads_only_the_selected_tab():
    source = read("backend/app/web_app.py")
    start = source.index('def overview_statistics(current_user):')
    end = source.index('\n@stats_bp.route("/students/summary")', start)
    view = source[start:end]
    for section in ("overview", "directions", "attendance", "events", "declines"):
        assert f'active_section == "{section}"' in view
    assert "students=[]" in view
    template = read("frontend/templates/statistics/overview.html")
    assert "{{ attendance_count }}" in template

def test_theme_polling_and_low_power_budget_are_less_aggressive():
    theme = read("frontend/assets/scripts/portal/theme-live-sync.js")
    budget = read("frontend/assets/scripts/shared/performance-budget-2026.js")
    assert "const POLL_INTERVAL = 30000" in theme
    assert "cores <= 4" in budget and "memory <= 4" in budget
    assert "perf-balanced" in budget
    assert "body.perf-balanced .holiday-smoke" in read("frontend/assets/styles/shared/performance-budget-2026.css")
