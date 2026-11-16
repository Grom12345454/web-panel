"""Independent scheduler for production WSGI installations (run ONE instance).

python scripts/run_calendar_worker.py

When using python run.py, do not launch this script as a second scheduler.
"""
from pathlib import Path
import sys
import time
import logging
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from web_app import create_app, publish_due_quotas
from database import init_db
from services.delivery_outbox import process_delivery_jobs

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = create_app()
with app.app_context():
    init_db(app)
while True:
    try:
        with app.app_context():
            publish_due_quotas()
            process_delivery_jobs(limit=20)
    except Exception:
        logger.exception('Calendar scheduler encountered an error')
    time.sleep(5)
