"""Safe SQLite snapshot and backup helpers for the internal university portal.

Backups contain only application databases. They never include .env, session keys,
Telegram tokens, or arbitrary files from the project directory.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
import tempfile
import threading
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from config import settings

BACKUP_DIR = settings.DATA_DIR / "backups"
DATABASES = {
    "people.sqlite3": settings.PEOPLE_DATABASE_PATH,
    "events.sqlite3": settings.EVENTS_DATABASE_PATH,
    "lessons.sqlite3": settings.LESSONS_DATABASE_PATH,
    "stats.sqlite3": settings.STATS_DATABASE_PATH,
    "system.sqlite3": settings.SYSTEM_DATABASE_PATH,
}
_BACKUP_LOCK = threading.RLock()


def list_database_backups(limit: int = 20) -> list[dict]:
    """Return newest local backup archives. Does not inspect/extract their contents."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for path in BACKUP_DIR.glob("university-backup-*.zip"):
        try:
            if path.name.endswith(".part.zip") or path.name.endswith(".zip.part"):
                continue
            stat = path.stat()
            rows.append({
                "name": path.name,
                "size": stat.st_size,
                "size_mb": round(stat.st_size / (1024 * 1024), 2),
                "created": datetime.fromtimestamp(stat.st_mtime),
                "automatic": path.name.startswith("university-backup-auto-"),
            })
        except OSError:
            continue
    rows.sort(key=lambda item: item["created"], reverse=True)
    return rows[:max(1, min(int(limit), 10000))]


def _prune_backup_history() -> None:
    """Keep automatic and manual backups independently; never let automatic rotation
    delete a recent manual backup just because the total archive count is high.
    """
    rows = list_database_backups(limit=10000)
    automatic = [row for row in rows if row["automatic"]]
    manual = [row for row in rows if not row["automatic"]]
    for group, keep in (
        (automatic, settings.DATABASE_AUTO_BACKUP_RETENTION),
        (manual, settings.DATABASE_MANUAL_BACKUP_RETENTION),
    ):
        for row in group[keep:]:
            try:
                (BACKUP_DIR / row["name"]).unlink(missing_ok=True)
            except OSError:
                # A locked file is retained; later rotations can retry.
                pass


def create_database_backup(*, automatic: bool = False) -> Path:
    """Create a consistent, integrity-checked ZIP snapshot of every SQLite bind.

    Requires every configured application database to exist. A partial archive is not
    presented as a successful full backup, since it could not restore every bind.
    """
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    prefix = "university-backup-auto" if automatic else "university-backup"
    output = BACKUP_DIR / f"{prefix}-{stamp}.zip"

    with _BACKUP_LOCK:
        included = []
        with tempfile.TemporaryDirectory(prefix="university-backup-") as temp_dir:
            temp_root = Path(temp_dir)
            for archive_name, source_path in DATABASES.items():
                source_path = Path(source_path)
                if not source_path.is_file():
                    raise RuntimeError(f"Полная резервная копия невозможна: база {archive_name} отсутствует.")
                destination = temp_root / archive_name
                # SQLite's online backup API handles active connections and WAL safely.
                # IMPORTANT: sqlite3.Connection.__exit__ commits/rolls back but does NOT
                # close the handle. Explicit closing is required on Windows before the
                # TemporaryDirectory removes the copied .sqlite3 files (WinError 32).
                with closing(sqlite3.connect(
                    f"{source_path.resolve().as_uri()}?mode=ro", uri=True, timeout=15
                )) as source:
                    with closing(sqlite3.connect(destination, timeout=15)) as target:
                        source.backup(target, pages=256, sleep=0.05)
                        target.commit()
                        integrity = target.execute("PRAGMA integrity_check").fetchall()
                        if integrity != [("ok",)]:
                            raise RuntimeError(f"Проверка целостности не пройдена: {archive_name}")
                included.append({"file": archive_name, "size": destination.stat().st_size})

            manifest = {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "application": "University Student App / internal portal",
                "backup_type": "automatic" if automatic else "manual",
                "databases": included,
                "note": "Архив содержит только снимки SQLite. .env, токены и ключи не включены.",
            }
            manifest_path = temp_root / "backup-manifest.json"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

            partial = output.with_suffix(".zip.part")
            try:
                with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                    for item in included:
                        archive.write(temp_root / item["file"], arcname=f"databases/{item['file']}")
                    archive.write(manifest_path, arcname="backup-manifest.json")
                # Read every ZIP member to catch a truncated/corrupt output before exposing it.
                with zipfile.ZipFile(partial, "r") as archive:
                    bad_member = archive.testzip()
                    if bad_member:
                        raise RuntimeError(f"Проверка ZIP не пройдена: {bad_member}")
                    names = set(archive.namelist())
                    missing = {f"databases/{item['file']}" for item in included} - names
                    if missing:
                        raise RuntimeError("В резервной копии отсутствуют базы: " + ", ".join(sorted(missing)))
                os.replace(partial, output)
            finally:
                try:
                    partial.unlink(missing_ok=True)
                except OSError:
                    pass

        _prune_backup_history()
    return output


def backup_directory() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    return BACKUP_DIR


def create_daily_backup_if_needed(now: datetime | None = None) -> Path | None:
    """Backward-compatible helper: create at most one automatic snapshot per day."""
    current = now or datetime.now()
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    daily_pattern = f"university-backup-auto-{current.strftime('%Y%m%d')}-*.zip"
    if any(BACKUP_DIR.glob(daily_pattern)):
        return None
    return create_database_backup(automatic=True)



def verify_database_backup(archive_name: str) -> dict:
    """Validate a complete backup without changing live databases.

    Only the five expected SQLite members are copied to a private temporary
    directory. No archive member is extracted using its stored path.
    """
    import re
    import shutil

    if not re.fullmatch(r"university-backup-(?:auto-)?[0-9]{8}-[0-9]{6}-[0-9]{6}\.zip", str(archive_name or "")):
        raise ValueError("Недопустимое имя резервной копии.")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = BACKUP_DIR / archive_name
    if not archive_path.is_file() or archive_path.is_symlink():
        raise FileNotFoundError("Резервная копия не найдена.")

    expected = set(DATABASES)
    checked = []
    with _BACKUP_LOCK:
        with zipfile.ZipFile(archive_path, "r") as archive:
            names_list = archive.namelist()
            if len(names_list) != len(set(names_list)):
                raise RuntimeError("Архив содержит повторяющиеся элементы.")
            bad_member = archive.testzip()
            if bad_member:
                raise RuntimeError(f"Проверка ZIP не пройдена: {bad_member}")
            names = set(names_list)
            required = {f"databases/{name}" for name in expected}
            if not required.issubset(names) or "backup-manifest.json" not in names:
                raise RuntimeError("В архиве отсутствуют обязательные базы или манифест.")
            manifest_info = archive.getinfo("backup-manifest.json")
            if manifest_info.file_size > 1024 * 1024:
                raise RuntimeError("Манифест резервной копии имеет недопустимый размер.")
            try:
                manifest = json.loads(archive.read("backup-manifest.json").decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise RuntimeError("Манифест резервной копии повреждён.") from error
            declared = {str(item.get("file")) for item in manifest.get("databases", []) if isinstance(item, dict)}
            if declared != expected:
                raise RuntimeError("Состав архива не соответствует текущей конфигурации баз.")

            with tempfile.TemporaryDirectory(prefix="university-backup-check-", dir=BACKUP_DIR) as temp_dir:
                stage = Path(temp_dir)
                for name in sorted(expected):
                    target = stage / name
                    info = archive.getinfo(f"databases/{name}")
                    if info.file_size <= 0:
                        raise RuntimeError(f"Пустой файл базы в архиве: {name}")
                    with archive.open(f"databases/{name}") as source, target.open("wb") as output:
                        shutil.copyfileobj(source, output, length=1024 * 1024)
                    with closing(sqlite3.connect(target, timeout=10)) as connection:
                        result = connection.execute("PRAGMA integrity_check").fetchall()
                        if result != [("ok",)]:
                            raise RuntimeError(f"Проверка SQLite не пройдена: {name}")
                    checked.append({"file": name, "size_bytes": target.stat().st_size})
    return {
        "name": archive_name,
        "database_count": len(checked),
        "databases": checked,
        "created_at": manifest.get("created_at"),
        "backup_type": manifest.get("backup_type", "unknown"),
        "size_bytes": archive_path.stat().st_size,
    }

def restore_database_backup(archive_name: str, database_ext) -> Path:
    """Restore a complete, verified five-database snapshot with rollback protection.

    The archive name is treated as an opaque identifier and never as a path. A fresh
    full backup is created before touching live databases. Every SQLite file is staged
    and integrity-checked before the SQLAlchemy engines are disposed and files swapped.
    """
    import shutil
    import re

    if not re.fullmatch(r"university-backup-(?:auto-)?[0-9]{8}-[0-9]{6}-[0-9]{6}\.zip", str(archive_name or "")):
        raise ValueError("Недопустимое имя резервной копии.")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = BACKUP_DIR / archive_name
    if not archive_path.is_file() or archive_path.is_symlink():
        raise FileNotFoundError("Резервная копия не найдена.")

    expected = set(DATABASES)
    with _BACKUP_LOCK:
        with zipfile.ZipFile(archive_path, "r") as archive:
            if archive.testzip():
                raise RuntimeError("Архив повреждён: проверка ZIP не пройдена.")
            names = set(archive.namelist())
            required = {f"databases/{name}" for name in expected}
            if not required.issubset(names) or "backup-manifest.json" not in names:
                raise RuntimeError("В архиве отсутствуют обязательные базы или манифест.")
            manifest = json.loads(archive.read("backup-manifest.json").decode("utf-8"))
            declared = {str(item.get("file")) for item in manifest.get("databases", []) if isinstance(item, dict)}
            if declared != expected:
                raise RuntimeError("Состав архива не соответствует текущей конфигурации баз.")

            with tempfile.TemporaryDirectory(prefix="university-restore-", dir=BACKUP_DIR) as temp_dir:
                stage = Path(temp_dir)
                staged = {}
                for name, live_path in DATABASES.items():
                    target = stage / name
                    # Read only known members; no archive paths are ever extracted.
                    with archive.open(f"databases/{name}") as source, target.open("wb") as output:
                        shutil.copyfileobj(source, output)
                    with closing(sqlite3.connect(target)) as connection:
                        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                            raise RuntimeError(f"Проверка SQLite не пройдена: {name}")
                    staged[name] = (target, Path(live_path))

                # A full safety snapshot gives the operator a one-step way back.
                create_database_backup(automatic=False)
                originals = {}
                replaced = []
                try:
                    database_ext.session.remove()
                    for engine in database_ext.engines.values():
                        engine.dispose()
                    for name, (staged_path, live_path) in staged.items():
                        live_path.parent.mkdir(parents=True, exist_ok=True)
                        rollback_path = stage / f"rollback-{name}"
                        if live_path.exists():
                            shutil.copy2(live_path, rollback_path)
                            originals[name] = rollback_path
                        os.replace(staged_path, live_path)
                        replaced.append(name)
                except Exception:
                    for name in reversed(replaced):
                        live_path = staged[name][1]
                        old_path = originals.get(name)
                        if old_path and old_path.exists():
                            os.replace(old_path, live_path)
                    for engine in database_ext.engines.values():
                        engine.dispose()
                    raise
    return archive_path
