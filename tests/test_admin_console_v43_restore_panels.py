"""Regressions for the focused super-admin console and runtime diagnostics."""
from pathlib import Path
import ast
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]


def test_super_admin_keeps_general_panels_and_admin_group_has_only_five_items():
    base = (ROOT / "frontend/templates/shared/base.html").read_text("utf-8")
    assert 'aria-label="Главная навигация"' in base
    for panel in ("Работа совета", "Студенты и участники", "Аналитика", "Администрирование"):
        assert panel in base

    start = base.index('<section class="nav-group nav-section nav-admin-group')
    end = base.index('</section>', start) + len('</section>')
    admin_nav = base[start:end]
    expected = [
        "url_for('staff.accounts')",
        "url_for('admin.manage_leadership')",
        "url_for('admin.student_app_design')",
        "url_for('admin.system_runtime')",
        "url_for('admin.system_maintenance')",
    ]
    assert [value for value in expected if value in admin_nav] == expected
    assert admin_nav.count('class="nav-link') == 5
    for forbidden in ("admin.admin_audit_log", "admin.bot_activity", "admin.bot_journal", "admin.dashboard"):
        assert forbidden not in admin_nav
    for label in (
        "Сотрудники и доступы", "Руководство студенческого совета", "Дизайн и оформление",
        "Здоровье системы и восстановление", "Очистка баз данных",
    ):
        assert label in admin_nav


def test_super_admin_dashboard_keeps_work_panels_without_private_monitoring_widgets():
    page = (ROOT / "frontend/templates/dashboard/overview.html").read_text("utf-8")
    monitor_page = (ROOT / "frontend/templates/system/messenger_monitoring.html").read_text("utf-8")
    assert "galaxy-dashboard" in page
    assert "admin-home-v42-grid" not in page
    assert "Мониторинг" in monitor_page and "Telegram" in monitor_page and "VK" in monitor_page and "MAX" in monitor_page
    assert "galaxy-ops-hub" not in page and "mission-bot-hub" not in page


def test_super_admin_dashboard_loads_the_same_context_as_other_roles():
    source = (ROOT / "backend/app/web_app.py").read_text("utf-8")
    tree = ast.parse(source)
    dashboard = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "dashboard")
    body = ast.get_source_segment(source, dashboard)
    assert 'return render_template("dashboard/overview.html")' not in body
    for context_key in ("stats=stats", "directions=dirs", "activity_days=activity_days", "upcoming_events=upcoming_events"):
        assert context_key in body
    assert "bot_health=bot_health" not in body
    assert "pending_delivery_jobs" not in body


def test_runtime_health_includes_db_workers_queue_http_logs_and_bot_config():
    source = (ROOT / "backend/app/web_app.py").read_text("utf-8")
    tree = ast.parse(source)
    diagnostics = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_runtime_health_snapshot")
    body = ast.get_source_segment(source, diagnostics)
    for required in (
        'sql_text("SELECT 1")', "worker_snapshots()", "HttpAuditLog", "BotDeliveryJob",
        "database_checks", "integrations", "server_errors_24h", "free_gb", "log_metrics",
        "SECRET_KEY_CONFIGURED", "settings.BOT_TOKEN", "settings.VK_BOT_TOKEN", "settings.MAX_BOT_TOKEN",
    ):
        assert required in body
    assert '"secret_key": settings.SECRET_KEY' not in body and '"SECRET_KEY": settings.SECRET_KEY' not in body


def test_runtime_template_and_bundle_have_detailed_health_sections():
    template = (ROOT / "frontend/templates/system/runtime.html").read_text("utf-8")
    css_input = (ROOT / "scripts/build_assets.py").read_text("utf-8")
    css_bundle = (ROOT / "static/css/site.bundle.css").read_text("utf-8")
    for label in ("Базы данных", "Процесс и окружение", "Конфигурация интеграций", "HTTP и действия за 24 часа", "Очередь доставки", "Фоновые задачи"):
        assert label in template
    assert "admin.admin_audit_log" not in template and "admin.bot_journal" not in template
    assert "staff/admin-restricted-console-v42.css" in css_input
    assert "admin-home-v42-grid" in css_bundle and "pro-runtime-health-banner" in css_bundle
    env = Environment(loader=FileSystemLoader(str(ROOT / "frontend/templates")))
    for path in (ROOT / "frontend/templates").rglob("*.html"):
        env.get_template(path.relative_to(ROOT / "frontend/templates").as_posix())
