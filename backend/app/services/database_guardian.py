"""Continuous SQLite integrity guardian with safe, backup-based recovery.

The guardian is started as a supervised worker by run.py. It checks all application
SQLite databases, creates verified snapshots on a schedule, and restores only a
corrupted/missing database from a separately verified backup. The previous file and
SQLite WAL/SHM sidecars are preserved in data/backups/quarantine before replacement.

It intentionally does NOT replace a database when the check is merely busy/locked,
when the problem is likely permissions/storage access, or when no verified backup is
available. In those cases it reports an error instead of risking silent data loss.
"""
from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from config import settings
from services.maintenance import BACKUP_DIR, DATABASES, create_database_backup, list_database_backups, _BACKUP_LOCK

logger = logging.getLogger(__name__)
_STATE_LOCK = threading.RLock()
_RECOVERY_LOCK = threading.Lock()
_STATE: dict[str, Any] = {
    "running": False,
    "started_at": None,
    "last_check_at": None,
    "last_backup_at": None,
    "last_backup_name": None,
    "last_recovery": None,
    "last_error": None,
    "databases": [],
    "cycles": 0,
}

BIND_FOR_DATABASE = {
    "people.sqlite3": None,
    "events.sqlite3": "events",
    "lessons.sqlite3": "lessons",
    "stats.sqlite3": "stats",
    "system.sqlite3": "system",
}


def _now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _iso_from_stat(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds")
    except OSError:
        return None


def _uri_read_only(path: Path) -> str:
    return f"{path.resolve().as_uri()}?mode=ro"


def inspect_sqlite_database(path: Path, *, full: bool = False) -> dict[str, Any]:
    """Run quick_check/integrity_check, distinguishing corruption from transient access errors."""
    path = Path(path)
    checked_at = _now_text()
    if not path.is_file():
        return {"healthy": False, "recoverable": True, "state": "missing", "detail": "Файл базы отсутствует.", "checked_at": checked_at}

    connection = None
    try:
        connection = sqlite3.connect(_uri_read_only(path), uri=True, timeout=5)
        pragma = "integrity_check" if full else "quick_check"
        result = connection.execute(f"PRAGMA {pragma}").fetchall()
        if result == [("ok",)]:
            return {"healthy": True, "recoverable": False, "state": "ok", "detail": "Проверка целостности пройдена.", "checked_at": checked_at}
        detail = "; ".join(str(row[0]) for row in result[:4])[:500] or "SQLite сообщила о нарушении целостности."
        return {"healthy": False, "recoverable": True, "state": "corrupt", "detail": detail, "checked_at": checked_at}
    except sqlite3.DatabaseError as error:
        message = str(error)
        lowered = message.lower()
        if "locked" in lowered or "busy" in lowered:
            return {"healthy": None, "recoverable": False, "state": "busy", "detail": "База занята другим запросом; восстановление отложено.", "checked_at": checked_at}
        if any(token in lowered for token in ("malformed", "not a database", "disk image is malformed", "file is not a database")):
            return {"healthy": False, "recoverable": True, "state": "corrupt", "detail": message[:500], "checked_at": checked_at}
        return {"healthy": None, "recoverable": False, "state": "error", "detail": f"Ошибка доступа SQLite: {message[:300]}", "checked_at": checked_at}
    except OSError as error:
        return {"healthy": None, "recoverable": False, "state": "error", "detail": f"Ошибка файловой системы: {type(error).__name__}", "checked_at": checked_at}
    finally:
        if connection is not None:
            connection.close()


def _verified_archive_database(archive_path: Path, database_name: str, target_dir: Path) -> Path | None:
    """Copy one database member to a temp file and verify its complete SQLite integrity."""
    member = f"databases/{database_name}"
    candidate = None
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            infos = {item.filename: item for item in archive.infolist()}
            info = infos.get(member)
            if info is None or info.file_size <= 0:
                return None
            # A corrupt/unexpected archive must not be expanded using extract() paths.
            bad_member = archive.testzip()
            if bad_member:
                logger.warning("database_backup_zip_corrupt file=%s member=%s", archive_path.name, bad_member)
                return None
            fd, candidate_name = tempfile.mkstemp(prefix=f".{database_name}.verified-", suffix=".tmp", dir=str(target_dir))
            os.close(fd)
            candidate = Path(candidate_name)
            with archive.open(info, "r") as src, candidate.open("wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
        inspection = inspect_sqlite_database(candidate, full=True)
        if not inspection["healthy"]:
            logger.warning("database_backup_member_failed_integrity file=%s database=%s detail=%s",
                           archive_path.name, database_name, inspection["detail"])
            candidate.unlink(missing_ok=True)
            return None
        return candidate
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError, sqlite3.DatabaseError) as error:
        logger.warning("database_backup_candidate_rejected archive=%s database=%s error_type=%s",
                       archive_path.name, database_name, type(error).__name__)
        if candidate is not None:
            candidate.unlink(missing_ok=True)
        return None


def _dispose_database_engine(app, db_path: Path) -> None:
    """Dispose SQLAlchemy's pooled connections for the target SQLite bind.

    During startup preflight (before create_app/init_db), no SQLAlchemy engines are
    attached yet and the function is intentionally a no-op.
    """
    if app is None:
        return
    try:
        from database import db
        # Release this worker's scoped session before disposing its engine pool.
        try:
            db.session.remove()
        except Exception:
            pass
        for _bind, engine in db.engines.items():
            configured = engine.url.database
            if not configured:
                continue
            try:
                if Path(configured).resolve() == db_path.resolve():
                    engine.dispose()
                    return
            except (OSError, TypeError, ValueError):
                continue
    except Exception:
        logger.exception("database_guardian_engine_dispose_failed database=%s", db_path.name)
        raise


def restore_database_from_verified_backup(app, database_name: str, database_path: Path) -> dict[str, Any]:
    """Safely restore just one corrupted database from newest valid local backup.

    The damaged database and its sidecar files are moved to a timestamped quarantine
    directory. If atomic replacement or the post-restore integrity check fails, the
    original file is put back whenever possible. Returns a structured result.
    """
    if database_name not in DATABASES:
        raise ValueError("Неизвестная база данных для восстановления.")
    database_path = Path(database_path).resolve()
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    quarantine = BACKUP_DIR / "quarantine"
    quarantine.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")

    # Serialize file replacement against an admin-triggered or scheduled snapshot.
    with _RECOVERY_LOCK, _BACKUP_LOCK:
        candidate = None
        used_backup = None
        rows = list_database_backups(limit=10000)
        for row in rows:
            archive_path = BACKUP_DIR / row["name"]
            candidate = _verified_archive_database(archive_path, database_name, database_path.parent)
            if candidate is not None:
                used_backup = archive_path
                break
        if candidate is None or used_backup is None:
            return {"ok": False, "database": database_name, "reason": "no_valid_backup",
                    "detail": "Нет доступной проверенной резервной копии этой базы. Файл не изменён."}

        moved_originals: list[tuple[Path, Path]] = []
        installed_candidate = False
        try:
            _dispose_database_engine(app, database_path)
            # Preserve the main DB and its WAL/SHM together; never reuse a stale WAL on
            # top of a restored snapshot. All files remain recoverable for investigation.
            for suffix in ("", "-wal", "-shm"):
                source = Path(str(database_path) + suffix)
                if source.exists():
                    preserved = quarantine / f"{database_name}.{stamp}{suffix}.previous"
                    os.replace(source, preserved)
                    moved_originals.append((source, preserved))

            os.replace(candidate, database_path)
            installed_candidate = True
            final_check = inspect_sqlite_database(database_path, full=True)
            if not final_check["healthy"]:
                raise RuntimeError("Резервная копия не прошла проверку после восстановления.")

            result = {
                "ok": True,
                "database": database_name,
                "backup": used_backup.name,
                "recovered_at": _now_text(),
                "quarantined_files": [path.name for _, path in moved_originals],
                "detail": "База восстановлена из проверенной копии; прежний файл сохранён в quarantine.",
            }
            logger.error("database_auto_recovery_success database=%s backup=%s quarantined=%s",
                         database_name, used_backup.name, len(moved_originals))
            return result
        except Exception as error:
            logger.exception("database_auto_recovery_failed database=%s backup=%s", database_name,
                             used_backup.name if used_backup else "unknown")
            # Do not overwrite the only copy of the damaged DB. Roll back if the new
            # candidate could not be installed or verified; keep failed candidate too.
            if installed_candidate and database_path.exists():
                failed = quarantine / f"{database_name}.{stamp}.failed-restore"
                try:
                    os.replace(database_path, failed)
                except OSError:
                    pass
            for original_path, preserved_path in reversed(moved_originals):
                if preserved_path.exists() and not original_path.exists():
                    try:
                        os.replace(preserved_path, original_path)
                    except OSError:
                        logger.critical("database_recovery_rollback_failed preserved_file=%s", preserved_path)
            return {"ok": False, "database": database_name, "reason": type(error).__name__,
                    "detail": "Автовосстановление не завершено; проверьте журнал. Существующая копия сохранена."}
        finally:
            if candidate is not None:
                try:
                    candidate.unlink(missing_ok=True)
                except OSError:
                    pass


def preflight_database_recovery() -> dict[str, Any]:
    """Run before ORM initialization so a corrupt file cannot be recreated empty.

    An all-new installation (no configured DB files and no backups) is allowed to
    continue to init_db(). For an existing installation, every missing/corrupt file
    must be restored from a fully verified archive or startup is stopped safely.
    """
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    any_database_exists = any(Path(path).exists() for path in DATABASES.values())
    backups = list_database_backups(limit=1)
    if not any_database_exists and not backups:
        logger.info("database_preflight_fresh_install; schema initialization may proceed")
        return {"ok": True, "fresh_install": True, "recovered": []}

    recovered = []
    unresolved = []
    for database_name, database_path in DATABASES.items():
        result = inspect_sqlite_database(Path(database_path), full=False)
        if result["healthy"] is True:
            continue
        if result["recoverable"]:
            restoration = restore_database_from_verified_backup(None, database_name, Path(database_path))
            if restoration.get("ok"):
                verified = inspect_sqlite_database(Path(database_path), full=True)
                if verified["healthy"]:
                    recovered.append({"database": database_name, "backup": restoration.get("backup")})
                    continue
        unresolved.append({
            "database": database_name,
            "state": result["state"],
            "detail": result["detail"],
        })

    if unresolved:
        names = ", ".join(f"{item['database']} ({item['state']})" for item in unresolved)
        logger.critical("database_preflight_blocked_startup unresolved=%s", names)
        return {
            "ok": False,
            "fresh_install": False,
            "recovered": recovered,
            "unresolved": unresolved,
            "message": (
                "Запуск остановлен для защиты данных: не удалось проверить/восстановить "
                f"базы: {names}. Не удаляйте файлы вручную; проверьте data/backups и журнал сервера."
            ),
        }
    if recovered:
        logger.error("database_preflight_recovery_completed databases=%s", ",".join(row["database"] for row in recovered))
    return {"ok": True, "fresh_install": False, "recovered": recovered}


def _set_state(**updates) -> None:
    with _STATE_LOCK:
        _STATE.update(updates)


def guardian_status() -> dict[str, Any]:
    """Return a UI-safe copy of the last health snapshot; never expose database paths."""
    with _STATE_LOCK:
        snapshot = dict(_STATE)
        snapshot["databases"] = [dict(item) for item in _STATE.get("databases", [])]
        if isinstance(snapshot.get("last_recovery"), dict):
            snapshot["last_recovery"] = dict(snapshot["last_recovery"])
        snapshot["interval_seconds"] = settings.DATABASE_GUARDIAN_INTERVAL_SECONDS
        snapshot["backup_interval_hours"] = settings.DATABASE_BACKUP_INTERVAL_HOURS
        snapshot["retained_automatic_backups"] = settings.DATABASE_AUTO_BACKUP_RETENTION
        try:
            snapshot["backup_count"] = len(list_database_backups(limit=10000))
        except OSError as error:
            snapshot["backup_count"] = 0
            snapshot["last_error"] = snapshot.get("last_error") or f"Каталог резервных копий недоступен: {type(error).__name__}"
        return snapshot


def _latest_auto_backup() -> dict[str, Any] | None:
    backups = [row for row in list_database_backups(limit=10000) if row["automatic"]]
    return backups[0] if backups else None


def guardian_cycle(app, *, now: datetime | None = None) -> dict[str, Any]:
    """Run one full cycle; exposed separately so recovery behavior can be tested."""
    current = now or datetime.now()
    checks: list[dict[str, Any]] = []
    last_recovery = None
    all_ok = True

    for database_name, path in DATABASES.items():
        basic = inspect_sqlite_database(path, full=False)
        if basic["healthy"] is False and basic["recoverable"]:
            recovery = restore_database_from_verified_backup(app, database_name, Path(path))
            last_recovery = recovery
            if recovery.get("ok"):
                basic = inspect_sqlite_database(path, full=True)
                basic["restored_from_backup"] = recovery.get("backup")
            else:
                basic["recovery_error"] = recovery.get("detail")
        if basic["healthy"] is not True:
            all_ok = False
        checks.append({
            "database": database_name,
            "label": {
                "people.sqlite3": "Профили и сотрудники",
                "events.sqlite3": "Мероприятия и регистрации",
                "lessons.sqlite3": "Занятия",
                "stats.sqlite3": "Статистика",
                "system.sqlite3": "Системные данные",
            }.get(database_name, database_name),
            "state": basic["state"],
            "healthy": basic["healthy"] is True,
            "detail": basic["detail"],
            "checked_at": basic["checked_at"],
            "restored_from_backup": basic.get("restored_from_backup"),
            "recovery_error": basic.get("recovery_error"),
        })

    latest_auto = _latest_auto_backup()
    backup_due = latest_auto is None
    if latest_auto:
        age_seconds = max(0, (current - latest_auto["created"]).total_seconds())
        backup_due = age_seconds >= settings.DATABASE_BACKUP_INTERVAL_HOURS * 3600

    backup_error = None
    if all_ok and backup_due:
        try:
            new_backup = create_database_backup(automatic=True)
            latest_auto = {"name": new_backup.name, "created": datetime.fromtimestamp(new_backup.stat().st_mtime)}
            logger.info("database_auto_backup_created file=%s", new_backup.name)
        except Exception as error:
            backup_error = f"Создание резервной копии не удалось: {type(error).__name__}"
            logger.exception("database_auto_backup_failed")

    # A successful recovery also triggers an immediate fresh snapshot after verifying
    # all binds, even if the previous scheduled backup is not yet due.
    if last_recovery and last_recovery.get("ok") and all_ok and not backup_due:
        try:
            new_backup = create_database_backup(automatic=True)
            latest_auto = {"name": new_backup.name, "created": datetime.fromtimestamp(new_backup.stat().st_mtime)}
            logger.info("database_post_recovery_backup_created file=%s", new_backup.name)
        except Exception as error:
            backup_error = f"Создание резервной копии после восстановления не удалось: {type(error).__name__}"
            logger.exception("database_post_recovery_backup_failed")

    state = {
        "running": True,
        "started_at": None,
        "last_check_at": _now_text(),
        "last_backup_at": latest_auto["created"].astimezone().isoformat(timespec="seconds") if latest_auto else None,
        "last_backup_name": latest_auto["name"] if latest_auto else None,
        "last_recovery": last_recovery,
        "last_error": backup_error,
        "databases": checks,
        "healthy_count": sum(1 for item in checks if item["healthy"]),
        "database_count": len(checks),
        "cycles": int(_STATE.get("cycles", 0)) + 1,
        "next_backup_at": ((latest_auto["created"] + timedelta(hours=settings.DATABASE_BACKUP_INTERVAL_HOURS)).astimezone().isoformat(timespec="seconds") if latest_auto else None),
    }
    _set_state(**state)
    return guardian_status()


def run_database_guardian(app) -> None:
    """Run DB integrity checks and backups for the full life of the app process."""
    _set_state(running=True, started_at=_now_text())
    logger.info("database_guardian_started interval_s=%s backup_interval_h=%s retention=%s",
                settings.DATABASE_GUARDIAN_INTERVAL_SECONDS,
                settings.DATABASE_BACKUP_INTERVAL_HOURS,
                settings.DATABASE_AUTO_BACKUP_RETENTION)
    while True:
        try:
            with app.app_context():
                guardian_cycle(app)
        except Exception:
            logger.exception("database_guardian_cycle_failed")
            _set_state(last_error="Проверка базы завершилась исключением; подробности записаны в серверный журнал.")
        time.sleep(settings.DATABASE_GUARDIAN_INTERVAL_SECONDS)
