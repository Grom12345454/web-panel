"""Dependency-light checks for the 2026 workspace and self-healing layer."""
import logging
from pathlib import Path
import subprocess
import sys

from services.runtime_supervisor import RestartPolicy, SupervisedWorker

ROOT = Path(__file__).resolve().parents[1]


def test_bounded_restart_policy_and_reset_after_window():
    policy = RestartPolicy(max_restarts=2, window_seconds=30, cooldown_seconds=45,
                           base_delay=1, max_delay=8)
    assert policy.next_delay(0) == (1, False)
    assert policy.next_delay(1) == (2, False)
    delay, open_circuit = policy.next_delay(2)
    assert open_circuit and delay >= 45
    assert policy.next_delay(31) == (1, False)


def test_supervised_worker_status_and_no_sensitive_error_text():
    worker = SupervisedWorker('sample', lambda: None)
    snap = worker.snapshot()
    assert snap['state'] == 'pending'
    assert snap['last_error_type'] is None
    assert snap['restarts'] == 0
    assert 'thread_alive' in snap


def test_asset_bundle_and_operational_screen_are_linked():
    builder = (ROOT / 'scripts/build_assets.py').read_text('utf-8')
    site = (ROOT / 'frontend/templates/shared/base.html').read_text('utf-8')
    student = (ROOT / 'frontend/templates/student/student_app.html').read_text('utf-8')
    runtime = (ROOT / 'frontend/templates/system/runtime.html').read_text('utf-8')
    for name in ('pro-workspace-2026.css', 'pro-workspace.js',
                 'pro-student-experience.js', 'runtime-observability-2026.css'):
        assert name in builder
    assert 'data-pro-mode-toggle' not in site and 'data-pro-mode-toggle' not in student
    assert '3D-эффекты' not in site and '3D-эффекты' not in student
    assert 'shared/galaxy-depth-2026.css' in builder
    assert 'admin.system_runtime' in site
    assert 'data-runtime-grid' in runtime
    assert 'prefers-reduced-motion' in (ROOT / 'frontend/assets/styles/shared/pro-workspace-2026.css').read_text('utf-8')


def test_watchdog_and_wsgi_single_process_mode_are_wired():
    server = (ROOT / 'run.py').read_text('utf-8')
    watchdog = (ROOT / 'scripts/watchdog.py').read_text('utf-8')
    assert 'start_worker("telegram-polling"' in server
    assert 'serve(app, host=settings.WEB_HOST' in server
    assert 'max_restarts=6' in watchdog
    assert 'scripts/watchdog.py' in (ROOT / 'start.sh').read_text('utf-8')
    assert 'scripts/watchdog.py' in (ROOT / 'start.bat').read_text('utf-8')


def test_js_bundle_is_reproducible_without_node_dependencies():
    before = [(ROOT / f).read_bytes() for f in (
        'static/css/site.bundle.css', 'static/css/student-app.bundle.css',
        'static/js/site.bundle.js', 'static/js/student-app.bundle.js')]
    subprocess.run([sys.executable, 'scripts/build_assets.py'], cwd=ROOT, check=True,
                   stdout=subprocess.DEVNULL)
    after = [(ROOT / f).read_bytes() for f in (
        'static/css/site.bundle.css', 'static/css/student-app.bundle.css',
        'static/js/site.bundle.js', 'static/js/student-app.bundle.js')]
    assert before == after
