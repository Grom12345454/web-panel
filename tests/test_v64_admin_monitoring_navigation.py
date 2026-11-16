from pathlib import Path
import ast
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]


def test_monitoring_is_removed_from_sidebar_but_internal_logs_remain_guarded():
    base = (ROOT / 'frontend/templates/shared/base.html').read_text('utf-8')
    tabs = (ROOT / 'frontend/templates/activity/_admin_monitor_tabs.html').read_text('utf-8')
    activity = (ROOT / 'frontend/templates/activity/user_activity.html').read_text('utf-8')
    assert 'nav-monitoring-group' not in base
    assert 'nav-section-monitoring' not in base
    assert "url_for('admin.user_activity_log')" not in base
    assert "url_for('admin.messenger_monitoring')" not in base
    # Existing audit/monitor pages are retained as guarded internal routes for
    # diagnosis and security review, but are no longer exposed in navigation.
    assert all(label in tabs for label in ('Сотрудники', 'Сводка по ботам'))
    assert '_admin_monitor_tabs.html' in activity


def test_messenger_monitoring_and_bot_journal_are_super_admin_guarded():
    source = (ROOT / 'backend/app/web_app.py').read_text('utf-8')
    tree = ast.parse(source)
    nodes = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    for name in ('messenger_monitoring', 'messenger_monitoring_snapshot'):
        fn = nodes[name]
        decorators = [ast.unparse(d) for d in fn.decorator_list]
        assert 'super_admin_required' in decorators
    journal = (ROOT / 'backend/app/services/bot_journal_routes.py').read_text('utf-8')
    assert journal.count('@super_admin_required') >= 4


def test_overview_does_not_embed_messenger_monitoring_or_user_audit():
    dashboard = (ROOT / 'frontend/templates/dashboard/overview.html').read_text('utf-8')
    assert 'galaxy-ops-hub' not in dashboard
    assert 'mission-bot-hub' not in dashboard
    assert 'pending_delivery_jobs' not in dashboard
    assert 'user_activity' not in dashboard.lower()


def test_v64_background_canvas_fills_document_and_dashboard_uses_full_width():
    css = (ROOT / 'frontend/assets/styles/staff/admin-shell-v64.css').read_text('utf-8')
    build = (ROOT / 'scripts/build_assets.py').read_text('utf-8')
    assert 'staff/admin-shell-v64.css' in build
    assert 'html body.uc-body:has(.app-shell)' in css
    assert 'background:' in css and 'background-attachment: scroll' in css and 'html:has(body.uc-body)' in css
    assert '.app-shell > .main > .page' in css and 'max-width: none !important' in css
    assert '.uc-body.is-dashboard-page .galaxy-dashboard' in css
    assert '@media (prefers-reduced-motion: reduce)' in css


def test_all_templates_compile_after_navigation_split():
    env = Environment(loader=FileSystemLoader(str(ROOT / 'frontend/templates')))
    for template in (ROOT / 'frontend/templates').rglob('*.html'):
        env.get_template(template.relative_to(ROOT / 'frontend/templates').as_posix())
