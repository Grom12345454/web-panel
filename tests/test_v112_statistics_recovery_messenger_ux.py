from pathlib import Path
import json
import sqlite3
import zipfile

from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]


def read(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


def test_statistics_sections_are_table_only_and_show_real_direction_leaders():
    template = read("frontend/templates/statistics/overview.html")
    backend = read("backend/app/web_app.py")
    for table in ("direction-statistics-table", "attendance-statistics-table", "event-statistics-table", "decline-statistics-table"):
        assert table in template
    for visual in ("stats-relationship-flow", "stats-3d-stage", "stats-direction-scheme", "stats-trend-chart"):
        assert visual not in template
    assert "leader.student.full_name" in template
    assert "if active_section in (\"overview\", \"directions\")" in backend


def test_system_health_has_super_admin_backup_check_and_restore_actions():
    runtime = read("frontend/templates/system/runtime.html")
    maintenance = read("frontend/templates/system/maintenance.html")
    backend = read("backend/app/web_app.py")
    service = read("backend/app/services/maintenance.py")
    assert "Проверить систему сейчас" in runtime
    assert "Проверить архив" in runtime and "Восстановить" in runtime
    assert "url_for('admin.check_database_backup_action')" in maintenance
    assert "url_for('admin.restore_database_backup_action')" in maintenance
    assert '@super_admin_required' in backend[backend.index('@admin_bp.route("/system/backup/check"'):backend.index('@admin_bp.route("/system/restore"')]
    assert "verify_database_backup" in service and "PRAGMA integrity_check" in service


def test_messenger_topbar_is_removed_and_composer_has_emoji_counter_and_keyboard():
    template = read("frontend/templates/messenger/staff_messenger.html")
    script = read("static/js/staff-messenger.js")
    css = read("static/css/messenger-workspace.css")
    assert "messenger-workspace-topbar-center" not in template
    assert 'id="messenger-emoji-toggle"' in template
    assert 'id="messenger-char-count"' in template
    assert "selectionStart" in script and "messenger-char-count" in script
    assert "messenger-composer-foot" in css


def test_new_css_is_in_build_manifest_and_bundled():
    manifest = json.loads(read("frontend/asset-manifest.json"))
    files = manifest["bundles"]["site_css"]["files"]
    assert "portal/statistics-professional-v1912.css" not in files
    assert "portal/statistics-tables-v1917.css" in files
    assert "staff/runtime-recovery-actions-v112.css" in files
    bundle = read("static/css/site.bundle.css")
    assert "stats-relationship-flow" not in bundle
    assert "stats-table-toolbar" in bundle
    assert "pro-runtime-actions" in bundle


def test_critical_templates_compile():
    env = Environment(loader=FileSystemLoader(str(ROOT / "frontend/templates")))
    for name in ("statistics/overview.html", "system/runtime.html", "system/maintenance.html", "messenger/staff_messenger.html"):
        env.get_template(name)


def test_backup_verifier_rejects_path_traversal_names_before_file_access():
    # Import through the project's backend application path.
    import sys
    sys.path.insert(0, str(ROOT / "backend/app"))
    from services.maintenance import verify_database_backup
    try:
        verify_database_backup("../outside.zip")
    except ValueError as error:
        assert "Недопустимое имя" in str(error)
    else:
        raise AssertionError("unsafe backup identifier was accepted")


def test_backup_verifier_accepts_a_complete_sqlite_snapshot(tmp_path, monkeypatch):
    import sys
    import zipfile
    from unittest.mock import patch

    sys.path.insert(0, str(ROOT / "backend/app"))
    from services import maintenance

    database_paths = {}
    for filename in maintenance.DATABASES:
        path = tmp_path / filename
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE health_probe (id INTEGER PRIMARY KEY, value TEXT)")
            connection.execute("INSERT INTO health_probe(value) VALUES ('ok')")
        database_paths[filename] = path

    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    archive_name = "university-backup-20261115-120000-000001.zip"
    manifest = {
        "created_at": "2026-11-15T12:00:00+00:00",
        "backup_type": "manual",
        "databases": [{"file": filename} for filename in database_paths],
    }
    archive_path = backup_dir / archive_name
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename, path in database_paths.items():
            archive.write(path, f"databases/{filename}")
        archive.writestr("backup-manifest.json", json.dumps(manifest))

    with patch.object(maintenance, "BACKUP_DIR", backup_dir), patch.object(maintenance, "DATABASES", database_paths):
        result = maintenance.verify_database_backup(archive_name)

    assert result["database_count"] == 5
    assert {item["file"] for item in result["databases"]} == set(database_paths)
    assert result["backup_type"] == "manual"
