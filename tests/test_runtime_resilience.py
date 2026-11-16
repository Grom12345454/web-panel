"""Regression checks for predictable background and browser request lifecycles."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_student_api_times_out_safe_reads_but_does_not_abort_mutations():
    source = read("frontend/assets/scripts/student/student_app.js")
    assert "method === 'GET' || method === 'HEAD' ? 15000 : 0" in source
    assert "new AbortController()" in source
    assert "Never auto-abort writes" in source
    assert "Сервер не ответил за отведённое время" in source
    standalone = read("frontend/assets/standalone/js/student_app.js")
    assert standalone == source


def test_notification_polling_is_single_flight_and_stops_in_hidden_tabs():
    source = read("frontend/assets/scripts/portal/notifications.js")
    assert "let updateInFlight = false" in source
    assert "if (document.visibilityState === 'hidden' || navigator.onLine === false || updateInFlight) return" in source
    assert "activeController?.abort()" in source
    assert "window.addEventListener('offline', stopPolling)" in source
    assert "navigator.onLine === false) return" in source
    assert "window.clearInterval(pollingTimer)" in source
    assert "window.setInterval(update, 45000)" in source


def test_notification_worker_is_supervised_not_started_on_module_import():
    source = read("backend/app/web_app.py")
    run = read("run.py")
    wsgi = read("backend/wsgi.py")
    assert "def notification_worker():" in source
    assert "worker_thread.start()" not in source
    assert 'start_worker("web-notifications", notification_worker)' in run
    assert 'start_worker("web-notifications", notification_worker)' in wsgi


def test_wsgi_factory_documentation_matches_the_actual_callable():
    source = read("backend/wsgi.py")
    assert "backend.wsgi:create_application" in source
    assert "def create_application():" in source
    assert "def create_app():" in source
    assert "return create_application()" in source
