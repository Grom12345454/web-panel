"""Regression tests for on-site notification integration without requiring DB."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NotificationIntegrationTests(unittest.TestCase):
    def test_persistent_records_and_read_receipts(self):
        models = (ROOT / 'backend/app/database/system.py').read_text(encoding='utf-8')
        self.assertIn('class SiteNotification(db.Model)', models)
        self.assertIn('class SiteNotificationRead(db.Model)', models)
        self.assertIn('uq_notification_read_user', models)
        self.assertIn('_activity_notification(action, description, student_id, direction_id, quota_id)', models)

    def test_dashboard_has_read_filters_and_audience_targeting(self):
        html = (ROOT / 'frontend/templates/system/notifications.html').read_text(encoding='utf-8')
        for field in ('category', 'state', 'direction', 'audience', 'education_type'):
            self.assertIn(f'name="{field}"', html)
        for name in ('notification_read', 'notifications_read_all', 'notifications_publish'):
            self.assertIn(name, html)
        shell = (ROOT / 'frontend/templates/shared/base.html').read_text(encoding='utf-8')
        self.assertIn("url_for('admin.notifications')", shell)
        self.assertIn('data-notification-count', shell)

    def test_filters_are_applied_server_side(self):
        source = (ROOT / 'backend/app/services/site_notifications.py').read_text(encoding='utf-8')
        self.assertIn('def can_view(user, alert):', source)
        self.assertIn('can_user_manage_direction(user.id, alert.direction_id, education)', source)
        self.assertIn('def visible_notifications(', source)
        self.assertIn('def mark_read(', source)

    def test_bundles_include_the_notification_ui(self):
        css = (ROOT / 'static/css/site.bundle.css').read_text(encoding='utf-8')
        js = (ROOT / 'static/js/site.bundle.js').read_text(encoding='utf-8')
        self.assertIn('notification center', css)
        self.assertIn('system notification toast', js)


if __name__ == '__main__':
    unittest.main()
