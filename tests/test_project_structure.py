"""Regression checks for the backend/frontend source separation."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def test_backend_and_frontend_have_single_canonical_source_locations():
    expected_backend = [
        "backend/app/web_app.py", "backend/app/config.py", "backend/app/security.py",
        "backend/app/database/__init__.py", "backend/app/services/__init__.py",
        "backend/app/handlers/__init__.py",
    ]
    expected_frontend = [
        "frontend/templates/shared/base.html",
        "frontend/templates/student/student_app.html",
        "frontend/assets/styles/shared/galaxy-tokens.css",
        "frontend/assets/styles/student/campus-space-background-v48.css",
        "frontend/assets/scripts/portal/app.js",
        "frontend/assets/scripts/student/student_app.js",
        "frontend/assets/standalone/css/admin-management.css",
        "frontend/assets/standalone/js/otp.js",
    ]
    for relative in expected_backend + expected_frontend:
        assert (ROOT / relative).is_file(), relative
    assert not (ROOT / "static/src").exists()
    assert not (ROOT / "templates").exists()
    assert not (ROOT / "backend/app/services.py").exists()


def test_flask_factory_points_to_frontend_templates_and_public_static_directory():
    source = (ROOT / "backend/app/web_app.py").read_text(encoding="utf-8")
    assert 'template_folder=str(project_root / "frontend" / "templates")' in source
    assert 'static_folder=str(project_root / "static")' in source


def test_compatibility_import_facades_remain_for_existing_launchers():
    for relative in (
        "run.py", "main.py", "web_app.py", "config.py", "bot.py", "bot_messages.py",
        "security.py", "database/__init__.py", "services/__init__.py", "handlers/__init__.py",
    ):
        assert (ROOT / relative).is_file(), relative
    env = {**__import__("os").environ, "PYTHONPATH": str(ROOT)}
    result = subprocess.run(
        [sys.executable, "-c", "import config; import services; import handlers; "
         "from services.runtime_supervisor import RestartPolicy; "
         "assert config.settings.BASE_DIR.is_dir(); assert RestartPolicy(max_restarts=1).next_delay(0)[0] > 0"],
        cwd=ROOT, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_asset_builder_uses_frontend_source_and_static_only_for_output():
    build = (ROOT / "scripts/build_assets.py").read_text(encoding="utf-8")
    assert 'ASSET_ROOT / "styles"' in build
    assert 'ASSET_ROOT / "scripts"' in build
    assert "GENERATED FILE" in build
    assert 'STANDALONE_CSS_SOURCE = ASSET_ROOT / "standalone" / "css"' in build
    assert 'STANDALONE_JS_SOURCE = ASSET_ROOT / "standalone" / "js"' in build
    assert "_copy_standalone(STANDALONE_CSS" in build
    assert "_copy_standalone(STANDALONE_JS" in build
    assert not (ROOT / "static/src").exists()
    for relative in (
        "static/css/site.bundle.css", "static/css/student-app.bundle.css",
        "static/js/site.bundle.js", "static/js/student-app.bundle.js",
    ):
        assert (ROOT / relative).is_file(), relative


def test_root_documentation_describes_the_two_development_areas():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "backend/" in readme and "frontend/" in readme
    assert "python scripts/build_assets.py" in readme
