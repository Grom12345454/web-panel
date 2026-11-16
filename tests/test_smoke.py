"""Isolated smoke tests for the internal portal.

Run with: python -m unittest discover -s tests -v
The test suite sets a temporary DATABASE_DIR before importing the app and never
opens or modifies the project's normal data directory.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
import uuid

_TEST_DATA = tempfile.TemporaryDirectory(prefix="university-portal-tests-")
_TEST_ROOT = Path(_TEST_DATA.name)
os.environ["DATABASE_DIR"] = str(_TEST_ROOT / "data")
os.environ["LEGACY_DATABASE_PATH"] = str(_TEST_ROOT / "no-legacy-database.sqlite3")
os.environ["LOCAL_DEMO"] = "1"
os.environ["WEB_HOST"] = "127.0.0.1"
os.environ["SECRET_KEY"] = "smoke-test-secret-key-keep-out-of-production-0001"
os.environ["BOT_TOKEN"] = ""
os.environ["ADMIN_USERNAME"] = "smoke-admin"
os.environ["ADMIN_PASSWORD"] = "smoke-admin-password-only-for-tests"
os.environ["OPERATOR_PASSWORD"] = ""
os.environ["OBSERVER_PASSWORD"] = ""

from web_app import create_app  # noqa: E402
from database import db, init_db, Direction, HttpAuditLog, User, UserRole  # noqa: E402

class InternalPortalSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config.update(TESTING=True)
        with cls.app.app_context():
            init_db(cls.app)

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            db.session.remove()
        _TEST_DATA.cleanup()

    def test_login_page_loads(self):
        response = self.app.test_client().get("/auth/login")
        self.assertEqual(response.status_code, 200)
        self.assertIn("С возвращением".encode(), response.data)

    def test_favicon_is_available(self):
        response = self.app.test_client().get("/favicon.ico")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/vnd.microsoft.icon")

    def test_liveness_returns_request_id_without_leaking_configuration(self):
        response = self.app.test_client().get(
            "/healthz", headers={"X-Request-ID": "smoke-request-123"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("X-Request-ID"), "smoke-request-123")
        self.assertEqual(response.get_json().get("status"), "ok")
        self.assertNotIn("DATABASE_URI", response.get_data(as_text=True))

    def test_readiness_checks_all_configured_sqlite_binds(self):
        response = self.app.test_client().get("/readyz")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload.get("status"), "ready")
        self.assertTrue({"people", "events", "lessons", "stats", "system"}.issubset(
            set(payload.get("dependencies", {}).keys())
        ))

    def test_login_page_loads_the_v9_design_system(self):
        response = self.app.test_client().get("/auth/login")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"css/site.bundle.css?v=", response.data)

    def test_guest_404_renders_the_human_friendly_error_page(self):
        response = self.app.test_client().get("/route-that-does-not-exist")
        self.assertEqual(response.status_code, 404)
        self.assertIn("Страница не найдена".encode(), response.data)

    def test_versioned_static_files_are_cacheable_and_support_etag(self):
        client = self.app.test_client()
        response = client.get("/static/css/app.css?v=test-version")
        self.assertEqual(response.status_code, 200)
        self.assertIn("max-age=31536000", response.headers.get("Cache-Control", ""))
        self.assertIn("immutable", response.headers.get("Cache-Control", ""))
        self.assertTrue(response.headers.get("ETag"))
        conditional = client.get(
            "/static/css/app.css?v=test-version",
            headers={"If-None-Match": response.headers["ETag"]},
        )
        self.assertEqual(conditional.status_code, 304)

    def test_v9_ui_stylesheet_is_versioned_and_cacheable(self):
        response = self.app.test_client().get("/static/css/ui-polish-v9.css?v=test-v9")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Student Council Portal", response.data)
        self.assertIn("immutable", response.headers.get("Cache-Control", ""))

    def test_student_app_page_loads(self):
        response = self.app.test_client().get("/student-app?standalone=1")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"STUDENT APP", response.data)

    def test_admin_write_rejects_missing_csrf_token(self):
        response = self.app.test_client().post("/system/backup")
        self.assertEqual(response.status_code, 400)
        self.assertIn("CSRF", response.get_data(as_text=True))

    def test_http_audit_log_persists_failures_and_is_admin_only(self):
        with self.app.app_context():
            admin = User.query.filter_by(role=UserRole.SUPER_ADMIN.value).first()
            self.assertIsNotNone(admin, "Smoke-test initialization should seed a super admin")
            admin_id = admin.id
            admin_version = admin.auth_version or 0

        client = self.app.test_client()
        with client.session_transaction() as panel_session:
            panel_session["user_id"] = admin_id
            panel_session["user_role"] = UserRole.SUPER_ADMIN.value
            panel_session["user_login"] = os.environ["ADMIN_USERNAME"]
            panel_session["auth_version"] = admin_version

        failed = client.get("/missing-route-for-audit-test")
        self.assertEqual(failed.status_code, 404)
        with self.app.app_context():
            entry = HttpAuditLog.query.filter_by(path="/missing-route-for-audit-test").order_by(
                HttpAuditLog.id.desc()
            ).first()
            self.assertIsNotNone(entry, "Failed requests should be persisted in the audit log")
            self.assertEqual(entry.status_code, 404)
            self.assertTrue(entry.request_id)

        audit_page = client.get("/audit-log")
        self.assertEqual(audit_page.status_code, 200)
        self.assertIn("Журнал действий".encode(), audit_page.data)

        with self.app.app_context():
            staff = User(email=f"smoke-staff-{uuid.uuid4().hex[:10]}",
                         password_hash="not-used", role=UserRole.STAFF.value, is_active=True)
            db.session.add(staff)
            db.session.commit()
            staff_id, staff_version = staff.id, staff.auth_version or 0
        with client.session_transaction() as panel_session:
            panel_session["user_id"] = staff_id
            panel_session["user_role"] = UserRole.STAFF.value
            panel_session["user_login"] = "smoke-staff"
            panel_session["auth_version"] = staff_version
        denied = client.get("/audit-log")
        self.assertEqual(denied.status_code, 403)

    def test_direction_leader_cannot_open_global_student_registry(self):
        with self.app.app_context():
            direction = Direction.query.first()
            self.assertIsNotNone(direction)
            login = f"smoke-leader-{uuid.uuid4().hex[:12]}"
            user = User(
                email=login,
                password_hash="not-used-by-this-session-test",
                role=UserRole.LEADER.value,
                assigned_direction_id=direction.id,
            )
            db.session.add(user)
            db.session.commit()
            user_id = user.id

        client = self.app.test_client()
        with client.session_transaction() as panel_session:
            panel_session["user_id"] = user_id
            panel_session["user_role"] = UserRole.LEADER.value
            panel_session["user_login"] = login
            panel_session["auth_version"] = 0
        response = client.get("/students")
        self.assertEqual(response.status_code, 403)

if __name__ == "__main__":
    unittest.main(verbosity=2)
