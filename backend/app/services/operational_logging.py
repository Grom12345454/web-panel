"""Privacy-minded rotating JSONL diagnostics for the Flask portal.

The database-backed audit journals remain the source of truth for the UI.
The on-disk log is an additional incident-diagnostics channel (no HTTP body,
query string, cookies, authentication headers, or chat message payloads).
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re

from flask import g, has_request_context

from config import settings

_ALLOWED_LOGGERS = frozenset({"web_app", "services", "database", "handlers", "bot", "run", "main", "__main__"})
_SENSITIVE_VALUE = re.compile(
    r"(?i)\b(password|passwd|secret|access_token|refresh_token|bot_token|"
    r"authorization|csrf_token|initdata|api[_-]?key|webhook_secret)\b"
    r"(\s*[=:]\s*|[\"']\s*:\s*[\"']?)([^\s,;\"'&}]+)"
)
_BEARER = re.compile(r"(?i)\bBearer\s+[^\s,;]+")
_QUERY = re.compile(r"(?i)(https?://[^\s?]+)\?[^\s]+")


def redact(value: object) -> str:
    """Defensively scrub common credentials from error strings and tracebacks."""
    text = str(value)
    text = _QUERY.sub(r"\1?[REDACTED]", text)
    text = _BEARER.sub("Bearer [REDACTED]", text)
    text = _SENSITIVE_VALUE.sub(lambda match: match.group(1) + match.group(2) + "[REDACTED]", text)
    return text


class SecureRotatingFileHandler(RotatingFileHandler):
    """Open each log file with owner-only permissions, including after rollover."""
    def _open(self):
        descriptor = os.open(self.baseFilename, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        return os.fdopen(descriptor, "a", encoding=self.encoding, errors=self.errors)


class _ProjectOnly(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.name.split(".", 1)[0] in _ALLOWED_LOGGERS


class JsonEventFormatter(logging.Formatter):
    """One compact JSON object per line; timestamps are explicitly UTC."""
    def format(self, record: logging.LogRecord) -> str:
        event = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
            "component": record.name.split(".", 1)[0],
            "process_id": record.process,
            "thread": record.threadName,
        }
        # Structured event labels make JSONL searchable in journal collectors.
        first_token = str(record.msg).split(" ", 1)[0]
        if re.fullmatch(r"[a-z][a-z0-9_]{2,64}", first_token):
            event["event"] = first_token
        if has_request_context():
            request_id = getattr(g, "request_id", None)
            if request_id:
                event["request_id"] = request_id
        if record.exc_info:
            event["exception"] = redact(self.formatException(record.exc_info))[:12000]
        return json.dumps(event, ensure_ascii=False, separators=(",", ":"))


def _bounded_int(env_key: str, default: int, minimum: int, maximum: int) -> int:
    try:
        return min(max(int(os.getenv(env_key, str(default))), minimum), maximum)
    except (TypeError, ValueError):
        return default


def configure_operational_logging(data_dir: Path) -> Path | None:
    """Configure once per target directory; do not duplicate handlers on app reload.

    If a filesystem is read-only, keep the application alive with the existing
    console logging and report the configuration failure there.
    """
    log_dir = Path(os.getenv("SITE_LOG_DIR") or (Path(data_dir) / "logs")).expanduser().resolve()
    # JSON diagnostics may contain internal identifiers, so a misconfigured
    # path must never put them under Flask's public static files.
    public_static = (settings.BASE_DIR / "static").resolve()
    if log_dir == public_static or log_dir.is_relative_to(public_static):
        logging.getLogger(__name__).error("Refusing to write server logs under public static directory")
        return None
    log_path = log_dir / "portal.jsonl"
    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(handler, RotatingFileHandler) and Path(handler.baseFilename) == log_path:
            return log_path
    try:
        log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        handler = SecureRotatingFileHandler(
            log_path,
            maxBytes=_bounded_int("SITE_LOG_MAX_BYTES", 5_000_000, 100_000, 100_000_000),
            backupCount=_bounded_int("SITE_LOG_BACKUPS", 5, 1, 30),
            encoding="utf-8",
        )
        try:
            os.chmod(log_path, 0o600)
        except OSError:
            pass
        handler.setFormatter(JsonEventFormatter())
        handler.addFilter(_ProjectOnly())
        level = os.getenv("SITE_LOG_LEVEL", "INFO").upper()
        handler.setLevel(getattr(logging, level, logging.INFO) if level in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"} else logging.INFO)
        root.addHandler(handler)
        # Enable project diagnostics without lowering the global logging level
        # for third-party SDKs that may emit sensitive messages to console.
        for name in _ALLOWED_LOGGERS:
            project_logger = logging.getLogger(name)
            if project_logger.level == logging.NOTSET and project_logger.getEffectiveLevel() > handler.level:
                project_logger.setLevel(handler.level)
        return log_path
    except OSError as error:
        logging.getLogger(__name__).warning("Unable to configure on-disk diagnostics: %s", error)
        return None
