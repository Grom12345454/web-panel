"""Regression tests for 24/7 SQLite guardian and backup-based recovery."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import zipfile
from pathlib import Path

import services.database_guardian as guardian
import services.maintenance as maintenance


def _database(path: Path, value: str = "preserved") -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS sample (value TEXT NOT NULL)")
        connection.execute("DELETE FROM sample")
        connection.execute("INSERT INTO sample(value) VALUES (?)", (value,))
        connection.commit()


def _backup_zip(path: Path, database_path: Path, database_name: str = "people.sqlite3") -> None:
    manifest = {
        "created_at": "2026-10-29T00:00:00+00:00",
        "databases": [{"file": database_name, "size": database_path.stat().st_size}],
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(database_path, arcname=f"databases/{database_name}")
        archive.writestr("backup-manifest.json", json.dumps(manifest))


def test_integrity_inspector_accepts_healthy_sqlite_and_flags_corruption(tmp_path):
    healthy = tmp_path / "healthy.sqlite3"
    _database(healthy)
    result = guardian.inspect_sqlite_database(healthy)
    assert result["healthy"] is True
    assert result["state"] == "ok"

    corrupt = tmp_path / "corrupt.sqlite3"
    corrupt.write_bytes(b"this is not a sqlite database")
    result = guardian.inspect_sqlite_database(corrupt)
    assert result["healthy"] is False
    assert result["recoverable"] is True
    assert result["state"] == "corrupt"


def test_integrity_inspector_reports_missing_database_as_recoverable(tmp_path):
    result = guardian.inspect_sqlite_database(tmp_path / "missing.sqlite3")
    assert result["healthy"] is False
    assert result["recoverable"] is True
    assert result["state"] == "missing"


def test_restore_uses_verified_backup_and_preserves_bad_file(tmp_path, monkeypatch):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    target_dir = tmp_path / "data"
    target_dir.mkdir()
    target = target_dir / "people.sqlite3"
    target.write_bytes(b"damaged database payload")

    healthy_source = tmp_path / "snapshot.sqlite3"
    _database(healthy_source, "restore-me")
    backup_path = backup_dir / "university-backup-auto-20261029-100000.zip"
    _backup_zip(backup_path, healthy_source)

    monkeypatch.setattr(guardian, "BACKUP_DIR", backup_dir)
    monkeypatch.setattr(guardian, "DATABASES", {"people.sqlite3": target})
    monkeypatch.setattr(guardian, "list_database_backups", lambda limit=20: [{
        "name": backup_path.name,
        "size": backup_path.stat().st_size,
        "size_mb": 0.01,
        "created": __import__("datetime").datetime.fromtimestamp(backup_path.stat().st_mtime),
        "automatic": True,
    }])
    monkeypatch.setattr(guardian, "_dispose_database_engine", lambda app, db_path: None)

    result = guardian.restore_database_from_verified_backup(object(), "people.sqlite3", target)
    assert result["ok"] is True
    assert result["backup"] == backup_path.name
    assert guardian.inspect_sqlite_database(target, full=True)["healthy"] is True
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT value FROM sample").fetchone()[0] == "restore-me"
    quarantine_files = list((backup_dir / "quarantine").glob("*.previous"))
    assert quarantine_files, "damaged original must be preserved, not deleted"


def test_restore_does_not_replace_database_without_valid_backup(tmp_path, monkeypatch):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    target_dir = tmp_path / "data"
    target_dir.mkdir()
    target = target_dir / "people.sqlite3"
    target.write_bytes(b"original-corrupt-bytes")

    monkeypatch.setattr(guardian, "BACKUP_DIR", backup_dir)
    monkeypatch.setattr(guardian, "DATABASES", {"people.sqlite3": target})
    monkeypatch.setattr(guardian, "list_database_backups", lambda limit=20: [])
    result = guardian.restore_database_from_verified_backup(object(), "people.sqlite3", target)
    assert result["ok"] is False
    assert result["reason"] == "no_valid_backup"
    assert target.read_bytes() == b"original-corrupt-bytes"


def test_database_cleanup_page_has_backup_controls_but_no_journal_wipe(tmp_path):
    # Assert the admin-facing cleanup page no longer contains the destructive journal
    # section and now exposes backup/guardian controls instead.
    root = Path(__file__).resolve().parents[1]
    template = (root / "frontend/templates/system/maintenance.html").read_text(encoding="utf-8")
    assert "Журналы и диагностика" not in template
    assert "url_for('admin.clear_logs')" not in template
    assert "url_for('admin.create_manual_database_backup')" in template
    assert "Автоматическая защита баз данных" in template


def test_run_registers_guardian_as_a_supervised_always_on_worker():
    root = Path(__file__).resolve().parents[1]
    source = (root / "run.py").read_text(encoding="utf-8")
    assert "from services.database_guardian import run_database_guardian" in source
    assert 'start_worker("database-guardian", lambda: run_database_guardian(app))' in source


def test_full_backup_contains_all_five_database_binds_and_manifest(tmp_path, monkeypatch):
    backup_dir = tmp_path / "backup-output"
    backup_dir.mkdir()
    db_paths = {}
    for name in ("people.sqlite3", "events.sqlite3", "lessons.sqlite3", "stats.sqlite3", "system.sqlite3"):
        path = tmp_path / name
        _database(path, name)
        db_paths[name] = path
    monkeypatch.setattr(maintenance, "BACKUP_DIR", backup_dir)
    monkeypatch.setattr(maintenance, "DATABASES", db_paths)

    result = maintenance.create_database_backup(automatic=True)
    assert result.is_file()
    assert result.name.startswith("university-backup-auto-")
    with zipfile.ZipFile(result) as archive:
        assert archive.testzip() is None
        names = set(archive.namelist())
        assert {f"databases/{name}" for name in db_paths} <= names
        manifest = json.loads(archive.read("backup-manifest.json"))
        assert len(manifest["databases"]) == 5
        assert manifest["backup_type"] == "automatic"


def test_full_backup_closes_sqlite_handles_before_temp_directory_cleanup(tmp_path, monkeypatch):
    """Windows refuses to remove SQLite files while backup connections remain open."""
    backup_dir = tmp_path / "backup-output"
    backup_dir.mkdir()
    db_paths = {}
    for name in ("people.sqlite3", "events.sqlite3", "lessons.sqlite3", "stats.sqlite3", "system.sqlite3"):
        path = tmp_path / name
        _database(path, name)
        db_paths[name] = path
    monkeypatch.setattr(maintenance, "BACKUP_DIR", backup_dir)
    monkeypatch.setattr(maintenance, "DATABASES", db_paths)

    real_connect = sqlite3.connect
    real_temp_directory = tempfile.TemporaryDirectory
    tracked_connections = []

    class TrackingConnection(sqlite3.Connection):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.closed_for_test = False

        def close(self):
            self.closed_for_test = True
            return super().close()

    def tracking_connect(*args, **kwargs):
        kwargs.setdefault("factory", TrackingConnection)
        connection = real_connect(*args, **kwargs)
        tracked_connections.append(connection)
        return connection

    class AssertClosedTemporaryDirectory:
        def __init__(self, *args, **kwargs):
            self.inner = real_temp_directory(*args, **kwargs)

        def __enter__(self):
            return self.inner.__enter__()

        def __exit__(self, exc_type, exc, tb):
            cleanup_result = self.inner.__exit__(exc_type, exc, tb)
            assert all(connection.closed_for_test for connection in tracked_connections), (
                "all SQLite backup connections must be closed before temp cleanup on Windows"
            )
            return cleanup_result

    monkeypatch.setattr(maintenance.sqlite3, "connect", tracking_connect)
    monkeypatch.setattr(maintenance.tempfile, "TemporaryDirectory", AssertClosedTemporaryDirectory)

    result = maintenance.create_database_backup(automatic=True)
    assert result.is_file()
    assert len(tracked_connections) == 10
    assert all(connection.closed_for_test for connection in tracked_connections)


def test_backup_fails_closed_if_a_required_database_is_missing(tmp_path, monkeypatch):
    backup_dir = tmp_path / "backup-output"
    db_paths = {}
    for name in ("people.sqlite3", "events.sqlite3", "lessons.sqlite3", "stats.sqlite3", "system.sqlite3"):
        path = tmp_path / name
        if name != "system.sqlite3":
            _database(path, name)
        db_paths[name] = path
    monkeypatch.setattr(maintenance, "BACKUP_DIR", backup_dir)
    monkeypatch.setattr(maintenance, "DATABASES", db_paths)
    try:
        maintenance.create_database_backup(automatic=True)
    except RuntimeError as error:
        assert "system.sqlite3" in str(error)
    else:
        raise AssertionError("a partial backup must not be reported as successful")
    assert not list(backup_dir.glob("*.zip"))


def test_startup_preflight_allows_fresh_install_without_existing_databases(tmp_path, monkeypatch):
    db_dir = tmp_path / "data"
    db_dir.mkdir()
    backup_dir = tmp_path / "backups"
    monkeypatch.setattr(guardian, "BACKUP_DIR", backup_dir)
    monkeypatch.setattr(guardian, "DATABASES", {"people.sqlite3": db_dir / "people.sqlite3"})
    monkeypatch.setattr(guardian, "list_database_backups", lambda limit=1: [])
    result = guardian.preflight_database_recovery()
    assert result["ok"] is True
    assert result["fresh_install"] is True


def test_startup_preflight_stops_before_empty_recreation_when_backup_is_missing(tmp_path, monkeypatch):
    db_dir = tmp_path / "data"
    db_dir.mkdir()
    healthy = db_dir / "people.sqlite3"
    _database(healthy, "keep")
    missing = db_dir / "events.sqlite3"
    monkeypatch.setattr(guardian, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(guardian, "DATABASES", {"people.sqlite3": healthy, "events.sqlite3": missing})
    monkeypatch.setattr(guardian, "list_database_backups", lambda limit=1: [])
    result = guardian.preflight_database_recovery()
    assert result["ok"] is False
    assert "events.sqlite3" in result["message"]
    assert not missing.exists(), "preflight must not create an empty database"


def test_startup_preflight_recovers_corruption_before_database_initialization(tmp_path, monkeypatch):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    target = data_dir / "people.sqlite3"
    target.write_bytes(b"bad db")
    source = tmp_path / "healthy.sqlite3"
    _database(source, "preflight-recovered")
    backup_path = backup_dir / "university-backup-auto-20261029-120000.zip"
    _backup_zip(backup_path, source)
    row = {
        "name": backup_path.name, "size": backup_path.stat().st_size,
        "size_mb": 0.01, "created": __import__("datetime").datetime.fromtimestamp(backup_path.stat().st_mtime),
        "automatic": True,
    }
    monkeypatch.setattr(guardian, "BACKUP_DIR", backup_dir)
    monkeypatch.setattr(guardian, "DATABASES", {"people.sqlite3": target})
    monkeypatch.setattr(guardian, "list_database_backups", lambda limit=20: [row])

    result = guardian.preflight_database_recovery()
    assert result["ok"] is True
    assert result["recovered"][0]["database"] == "people.sqlite3"
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT value FROM sample").fetchone()[0] == "preflight-recovered"
