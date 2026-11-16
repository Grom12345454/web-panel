"""Local process watchdog: restart a crashed/unhealthy portal with circuit breaker.

Run: python scripts/watchdog.py. For real 24/7 hosting use a system service
(systemd/Windows service/container restart policy) around this command.
"""
from __future__ import annotations

import collections
import logging
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib import request as url_request

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
# Support a common Windows extraction mistake: a new project folder placed inside
# an older project folder that still contains the old run.py/scripts directory.
_candidates = [SCRIPT_ROOT]
try:
    _candidates.extend(sorted(
        (item for item in SCRIPT_ROOT.iterdir() if item.is_dir() and not item.name.startswith((".", "__"))),
        key=lambda item: item.name.lower(),
    ))
except OSError:
    pass
ROOT = next((candidate.resolve() for candidate in _candidates
             if (candidate / "config.py").is_file()
             and (candidate / "web_app.py").is_file()
             and (candidate / "run.py").is_file()), None)
if ROOT is None:
    raise SystemExit(
        "Не найдена папка проекта с config.py, web_app.py и run.py. "
        "Распакуйте архив полностью, затем запустите start.bat."
    )
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from config import settings  # noqa: E402
from services.operational_logging import configure_operational_logging  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
configure_operational_logging(settings.DATA_DIR)
logger = logging.getLogger("services.watchdog")
_SHUTDOWN = False
_CHILD: subprocess.Popen | None = None


def _shutdown(signum, _frame):
    global _SHUTDOWN
    _SHUTDOWN = True
    logger.info("watchdog_signal signal=%s", signum)
    if _CHILD is not None and _CHILD.poll() is None:
        _CHILD.terminate()


def _ready() -> bool:
    # Loopback only: never probe a hostname from a request or user input.
    host = "[::1]" if settings.WEB_HOST == "::1" else "127.0.0.1"
    url = f"http://{host}:{settings.WEB_PORT}/readyz"
    try:
        with url_request.urlopen(url, timeout=3) as response:
            return response.status == 200
    except Exception:
        return False


def main() -> int:
    global _CHILD
    if settings.WEB_HOST not in {"0.0.0.0", "127.0.0.1", "localhost", "::1"}:
        logger.error("watchdog_probe_requires_loopback_binding_or_all_interfaces")
        return 2
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, _shutdown)
    recent = collections.deque()
    restarts = 0
    while not _SHUTDOWN:
        now = time.monotonic()
        while recent and now - recent[0] > 900:
            recent.popleft()
        if len(recent) >= 6:
            logger.critical("watchdog_circuit_open max_restarts=6 window_s=900 action=manual_investigation")
            return 1
        recent.append(now)
        logger.info("watchdog_child_start restart_count=%s", restarts)
        _CHILD = subprocess.Popen([sys.executable, "-u", "run.py"], cwd=str(ROOT))
        started = time.monotonic()
        unhealthy_checks = 0
        while not _SHUTDOWN and _CHILD.poll() is None:
            time.sleep(5)
            if _SHUTDOWN or _CHILD.poll() is not None:
                break
            if time.monotonic() - started < 40:
                continue  # Database initialization & cold starts.
            if _ready():
                unhealthy_checks = 0
            else:
                unhealthy_checks += 1
                logger.warning("watchdog_readiness_failed consecutive=%s", unhealthy_checks)
                if unhealthy_checks >= 4:
                    logger.error("watchdog_restarting_unhealthy_child")
                    _CHILD.terminate()
                    break
        if _CHILD.poll() is None:
            try:
                _CHILD.wait(timeout=12)
            except subprocess.TimeoutExpired:
                logger.error("watchdog_force_kill_timeout")
                _CHILD.kill()
                _CHILD.wait()
        code = _CHILD.returncode
        if _SHUTDOWN:
            logger.info("watchdog_exit requested=true")
            return 0
        restarts += 1
        delay = min(60, 2 ** min(6, restarts))
        logger.error("watchdog_child_exited exit_code=%s restart_in_s=%s", code, delay)
        time.sleep(delay)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
