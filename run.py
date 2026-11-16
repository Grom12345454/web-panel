"""One-process application entrypoint with supervised background transports.

Use scripts/watchdog.py as the parent process for whole-process recovery.
"""
from __future__ import annotations

import asyncio
import logging
import time
import os
import sys
from pathlib import Path


def _resolve_project_root() -> Path:
    """Find the project root even when an old folder contains a nested extracted ZIP."""
    script_dir = Path(__file__).resolve().parent
    candidates = [script_dir]
    try:
        candidates.extend(sorted(
            (item for item in script_dir.iterdir() if item.is_dir() and not item.name.startswith((".", "__"))),
            key=lambda item: (0 if (item / "START_HERE_WINDOWS.md").is_file() else 1, item.name.lower()),
        ))
    except OSError:
        pass
    for candidate in candidates:
        if (candidate / "config.py").is_file() and (candidate / "web_app.py").is_file() and (candidate / "database").is_dir():
            return candidate.resolve()
    raise SystemExit(
        "Не найдена конфигурация проекта: рядом с run.py должны находиться config.py, web_app.py и папка database. "
        "Распакуйте архив полностью и запускайте run.py из папки проекта."
    )


PROJECT_ROOT = _resolve_project_root()
# Put the actual project directory first, rather than relying on PowerShell's current directory.
if str(PROJECT_ROOT) in sys.path:
    sys.path.remove(str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from config import settings
from database import init_db, User, UserRole
from services.runtime_supervisor import start_worker
from services.database_guardian import run_database_guardian
from web_app import create_app, notification_worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
# Werkzeug emits one INFO line per successful HTTP request; keep 4xx/5xx diagnostics.
logging.getLogger("werkzeug").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def run_bot_in_thread(app):
    from bot import run_bot
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        with app.app_context():
            logger.info("telegram_polling_session_started")
            loop.run_until_complete(run_bot(app))
    finally:
        # Keep polling objects scoped to one loop; the next restart makes a new loop.
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        finally:
            asyncio.set_event_loop(None)
            loop.close()


def run_event_scheduler(app):
    from web_app import publish_due_quotas
    while True:
        try:
            with app.app_context():
                publish_due_quotas()
        except Exception:
            logger.exception("event_scheduler_iteration_failed")
        time.sleep(20)


def run_application_block_scheduler(app):
    from web_app import process_expired_application_blocks
    while True:
        try:
            with app.app_context():
                process_expired_application_blocks()
        except Exception:
            logger.exception("application_expiry_iteration_failed")
        time.sleep(20)


def run_delivery_scheduler(app):
    from services.delivery_outbox import process_delivery_jobs
    while True:
        try:
            with app.app_context():
                process_delivery_jobs(limit=20)
        except Exception:
            logger.exception("delivery_queue_iteration_failed")
        time.sleep(5)


def run_order_delivery_scheduler(app):
    from services.order_delivery import process_order_deliveries
    while True:
        try:
            with app.app_context():
                process_order_deliveries(limit=10)
        except Exception:
            logger.exception('order_delivery_iteration_failed')
        time.sleep(10)


def run_chat_removals(app):
    from services.activity_chats import process_chat_removals
    while True:
        try:
            with app.app_context():
                process_chat_removals(limit=15)
        except Exception:
            logger.exception('telegram_chat_removal_iteration_failed')
        time.sleep(10)


def run_alert_cleanup(app):
    from services.site_notifications import delete_expired_notifications
    while True:
        try:
            with app.app_context():
                delete_expired_notifications()
        except Exception:
            logger.exception('notification_cleanup_iteration_failed')
        time.sleep(60)


def main():
    logger.info("project_root=%s", PROJECT_ROOT)
    # Preflight before SQLAlchemy's create_all/migrations: if a previously existing
    # SQLite database is corrupted, restore it from a verified snapshot first instead
    # of allowing an ORM connection to create/reinitialize a replacement file.
    from services.database_guardian import preflight_database_recovery
    database_preflight = preflight_database_recovery()
    if not database_preflight.get("ok"):
        raise SystemExit(database_preflight.get("message", "Проверка баз данных не пройдена; запуск остановлен."))
    app = create_app()
    with app.app_context():
        init_db(app)
        logger.info("database_initialized")
        if not User.query.filter_by(role=UserRole.SUPER_ADMIN.value).first():
            raise SystemExit(
                "Не найден аккаунт главного администратора. Укажите уникальные "
                "ADMIN_USERNAME и ADMIN_PASSWORD в .env и запустите повторно."
            )

    # Keep the in-memory notification dispatcher under the same lifecycle monitor
    # as the other background services; importing the Flask app starts no threads.
    start_worker("web-notifications", notification_worker)

    # Legacy EventPublishScheduler and ChatDeliveryScheduler are now supervised.
    # Website remains independent of optional messenger connectivity.
    start_worker("application-blocks", lambda: run_application_block_scheduler(app))
    start_worker("event-publishing", lambda: run_event_scheduler(app))
    # Former ChatDeliveryScheduler; retained the delivery worker with supervision.
    start_worker("delivery-outbox", lambda: run_delivery_scheduler(app))
    start_worker("alert-retention", lambda: run_alert_cleanup(app))
    start_worker("order-documents", lambda: run_order_delivery_scheduler(app))
    start_worker("activity-chat-removals", lambda: run_chat_removals(app))
    # Continuously verify all SQLite binds, keep checked backups, and restore
    # a damaged/missing database only from a verified snapshot.
    start_worker("database-guardian", lambda: run_database_guardian(app))

    if settings.BOT_TOKEN:
        start_worker("telegram-polling", lambda: run_bot_in_thread(app))
    else:
        logger.info("telegram_disabled_no_token")

    if settings.VK_BOT_TOKEN and settings.VK_GROUP_ID:
        from services.messenger_transports import run_vk_polling
        start_worker("vk-polling", lambda: run_vk_polling(app))
    else:
        logger.info("vk_disabled_no_credentials")

    if settings.MAX_BOT_TOKEN and settings.MAX_MODE == "poll":
        from services.messenger_transports import run_max_dev_polling
        start_worker("max-polling", lambda: run_max_dev_polling(app))
    elif settings.MAX_BOT_TOKEN and settings.MAX_MODE == "webhook":
        logger.info("max_webhook_enabled")
    elif settings.MAX_BOT_TOKEN:
        logger.error("max_invalid_mode expected=poll_or_webhook")
    else:
        logger.info("max_disabled_no_token")

    browser_host = "127.0.0.1" if settings.WEB_HOST == "0.0.0.0" else settings.WEB_HOST
    logger.info("site_start url=http://%s:%s/auth/login student_app=http://%s:%s/student-app?standalone=1",
                browser_host, settings.WEB_PORT, browser_host, settings.WEB_PORT)

    # Werkzeug development server is only for localhost development. Waitress
    # runs one process/worker registry on the internal network; HTTPS must be
    # terminated by a trusted reverse proxy (see deployment guide).
    if settings.LOCAL_DEMO or settings.DEBUG:
        app.run(debug=settings.DEBUG, host=settings.WEB_HOST, port=settings.WEB_PORT, use_reloader=False)
    else:
        from waitress import serve
        serve(app, host=settings.WEB_HOST, port=settings.WEB_PORT, threads=8)


if __name__ == "__main__":
    main()
