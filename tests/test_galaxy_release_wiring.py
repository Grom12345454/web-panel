"""Regression tests: visible templates and generated assets must stay in sync."""
from pathlib import Path
import hashlib
from jinja2 import Environment, FileSystemLoader
ROOT = Path(__file__).resolve().parents[1]


def test_visible_portal_v14_is_in_shared_html():
    base = (ROOT / 'frontend/templates/shared/base.html').read_text(encoding='utf-8')
    assert 'data-ui-version="14"' in base
    assert 'Центр управления <span class="top-title-accent">студсоветом</span>' in base
    assert 'Действия пользователей' not in base and 'Центр событий' not in base
    assert 'nav-monitoring-group' not in base
    assert 'admin.user_activity_log' not in base


def test_dashboard_keeps_messenger_monitoring_out_of_overview():
    dashboard = (ROOT / 'frontend/templates/dashboard/overview.html').read_text(encoding='utf-8')
    base = (ROOT / 'frontend/templates/shared/base.html').read_text(encoding='utf-8')
    monitor = (ROOT / 'frontend/templates/system/messenger_monitoring.html').read_text(encoding='utf-8')
    assert 'galaxy-ops-hub' not in dashboard
    assert 'bot_health' not in dashboard and 'pending_delivery_jobs' not in dashboard
    assert "url_for('admin.messenger_monitoring')" not in base
    assert 'data-messenger-monitoring' in monitor
    assert 'nav-monitoring-group' not in base


def test_bundles_include_release_styles_and_match_source():
    build = (ROOT / 'scripts/build_assets.py').read_text(encoding='utf-8')
    for label in ('staff/galaxy-ui-release.css', 'student/galaxy-ui-release.css'):
        assert label in build
    for source, bundle in (
        ('frontend/assets/styles/staff/galaxy-ui-release.css', 'static/css/site.bundle.css'),
        ('frontend/assets/styles/student/galaxy-ui-release.css', 'static/css/student-app.bundle.css'),
    ):
        payload = (ROOT / source).read_text(encoding='utf-8')
        assert payload in (ROOT / bundle).read_text(encoding='utf-8')


def test_templates_really_load_built_bundles():
    base = (ROOT / 'frontend/templates/shared/base.html').read_text(encoding='utf-8')
    student = (ROOT / 'frontend/templates/student/student_app.html').read_text(encoding='utf-8')
    assert "filename='css/site.bundle.css'" in base
    assert "filename='css/student-app.bundle.css'" in student
    assert 'galaxy-loading-planet' in student
    assert 'asset_version' in base and 'asset_version' in student


def test_asset_version_is_content_fingerprint():
    app_code = (ROOT / 'backend/app/web_app.py').read_text(encoding='utf-8')
    assert 'hashlib.sha256()' in app_code
    assert '_asset_digest(filename, st.st_mtime_ns, st.st_size)' in app_code


def test_all_templates_compile():
    env = Environment(loader=FileSystemLoader(str(ROOT / 'frontend/templates')))
    for f in (ROOT / 'frontend/templates').rglob('*.html'):
        env.get_template(f.relative_to(ROOT / 'frontend/templates').as_posix())
