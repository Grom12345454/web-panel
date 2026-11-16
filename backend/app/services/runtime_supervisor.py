"""Supervise independent in-process jobs without losing the web server.

A worker returning (or raising) is a failure unless shutdown was requested.
Restarts have exponential delay and a fixed rolling budget. The supervisor
never claims to repair corrupted databases or invalid external credentials.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import logging
import threading
import time
from typing import Callable

logger = logging.getLogger(__name__)


class PermanentWorkerExit(Exception):
    """Stop an optional worker without exponential restart (e.g. invalid API token)."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RestartPolicy:
    def __init__(self, max_restarts: int = 5, window_seconds: float = 300,
                 cooldown_seconds: float = 300, base_delay: float = 2,
                 max_delay: float = 60):
        self.max_restarts = max_restarts
        self.window_seconds = window_seconds
        self.cooldown_seconds = cooldown_seconds
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.attempts: deque[float] = deque()

    def next_delay(self, now: float) -> tuple[float, bool]:
        """Return (delay, circuit_open); monotonic clock injected for testing."""
        while self.attempts and now - self.attempts[0] >= self.window_seconds:
            self.attempts.popleft()
        if len(self.attempts) >= self.max_restarts:
            remaining = self.window_seconds - (now - self.attempts[0])
            return max(self.cooldown_seconds, remaining), True
        self.attempts.append(now)
        return min(self.max_delay, self.base_delay * 2 ** (len(self.attempts) - 1)), False


class SupervisedWorker:
    def __init__(self, name: str, target: Callable[[], None], *, policy: RestartPolicy | None = None):
        self.name = name
        self.target = target
        self.policy = policy or RestartPolicy()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, name=f"Supervisor-{name}", daemon=True)
        self._state = "pending"
        self._started = None
        self._last_failure = None
        self._restart_count = 0
        self._last_error_type = None

    def start(self) -> "SupervisedWorker":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "name": self.name,
                "state": self._state,
                "started_at": self._started,
                "last_failure_at": self._last_failure,
                "restarts": self._restart_count,
                "last_error_type": self._last_error_type,
                "thread_alive": self._thread.is_alive(),
            }

    def _update(self, **changes):
        with self._lock:
            for key, value in changes.items():
                setattr(self, f"_{key}", value)

    def _run(self):
        while not self._stop.is_set():
            self._update(state="running", started=utc_now())
            logger.info("worker_started component=%s", self.name)
            try:
                self.target()
                if self._stop.is_set():
                    break
                logger.warning("worker_exited component=%s", self.name)
                failure_type = "UnexpectedExit"
            except PermanentWorkerExit as error:
                self._update(last_error_type=type(error).__name__, state="stopped")
                logger.error("worker_disabled component=%s reason=%s", self.name, str(error)[:240])
                break
            except Exception as error:
                failure_type = type(error).__name__
                logger.exception("worker_crashed component=%s error_type=%s", self.name, failure_type)
            self._update(last_failure=utc_now(), last_error_type=failure_type)
            delay, limited = self.policy.next_delay(time.monotonic())
            with self._lock:
                self._restart_count += 1
            self._update(state="cooldown" if limited else "restarting")
            logger.warning("worker_restart_scheduled component=%s delay_s=%.1f circuit_open=%s",
                           self.name, delay, limited)
            self._stop.wait(delay)
        self._update(state="stopped")
        logger.info("worker_stopped component=%s", self.name)


_WORKERS: dict[str, SupervisedWorker] = {}
_REGISTRY_LOCK = threading.Lock()


def start_worker(name: str, target: Callable[[], None], *, policy: RestartPolicy | None = None) -> SupervisedWorker:
    """Idempotent registration: never double-run the same polling service."""
    with _REGISTRY_LOCK:
        if name in _WORKERS:
            return _WORKERS[name]
        worker = SupervisedWorker(name, target, policy=policy)
        _WORKERS[name] = worker
        try:
            worker.start()
        except Exception:
            del _WORKERS[name]
            raise
        return worker


def worker_snapshots() -> list[dict]:
    with _REGISTRY_LOCK:
        workers = list(_WORKERS.values())
    return [worker.snapshot() for worker in workers]
