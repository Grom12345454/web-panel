"""Regression checks for observer read receipts without optional Flask dependencies."""
from __future__ import annotations

import ast
from datetime import datetime
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_function(path, name, values):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    node.decorator_list = []  # Route is exercised with pre-authorized user passed explicitly.
    namespace = dict(values)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), namespace)
    return namespace[name]


class Column:
    def __init__(self, name):
        self.name = name

    def __eq__(self, value):
        return lambda row: getattr(row, self.name) == value

    def in_(self, values):
        return lambda row: getattr(row, self.name) in values


class ReadRows:
    user_id = Column('user_id')
    notification_id = Column('notification_id')
    data = []

    @classmethod
    def filter(cls, *predicates):
        return SimpleNamespace(all=lambda: [row for row in cls.data if all(predicate(row) for predicate in predicates)])


class ObserverReceiptBehaviorTests(unittest.TestCase):
    def setUp(self):
        ReadRows.data = []
        self.observer = SimpleNamespace(id=23, role='observer')
        self.operator = SimpleNamespace(id=24, role='operator')
        self.alert = SimpleNamespace(id=7, audience='staff')
        self.private_alert = SimpleNamespace(id=8, audience='admins')
        self.session = SimpleNamespace(
            add=lambda row: ReadRows.data.append(row), commit=lambda: None,
        )
        class ReceiptModel:
            query = ReadRows
            user_id = ReadRows.user_id
            notification_id = ReadRows.notification_id

            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        self.mark_read = load_function(ROOT / 'backend/app/services/site_notifications.py', 'mark_read', {
            'SiteNotificationRead': ReceiptModel,
            'can_view': lambda user, alert: alert.audience == 'staff',
            'db': SimpleNamespace(session=self.session), 'datetime': datetime,
        })

    def test_observer_receipt_is_saved_per_account_and_idempotent(self):
        self.assertEqual(self.mark_read(self.observer, [self.alert]), 1)
        self.assertEqual([(row.user_id, row.notification_id) for row in ReadRows.data], [(23, 7)])
        self.assertEqual(self.mark_read(self.observer, [self.alert]), 0)
        self.assertEqual(self.mark_read(self.operator, [self.alert]), 1)
        self.assertEqual(len(ReadRows.data), 2)
        self.assertEqual({row.user_id for row in ReadRows.data}, {23, 24})

    def test_observer_cannot_mark_private_notification(self):
        self.assertEqual(self.mark_read(self.observer, [self.private_alert]), 0)
        self.assertFalse(ReadRows.data)


class ObserverReceiptRoutesTests(unittest.TestCase):
    def setUp(self):
        self.role = SimpleNamespace(id=23, role='observer')
        self.alert = SimpleNamespace(id=7)
        self.marked = []
        mock_service = ModuleType('services.site_notifications')
        mock_service.mark_read = lambda user, alerts: self.marked.append((user.id, [a.id for a in alerts])) or len(alerts)
        mock_service.can_view = lambda user, alert: alert.id == 7
        mock_service.visible_notifications = lambda user, *args, **kwargs: ([(self.alert, False)], 2)
        mock_service.CATEGORIES = {'system': 'System'}
        self.patcher = patch.dict(sys.modules, {'services.site_notifications': mock_service})
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        class Form(dict):
            def get(self, key, default=None, type=None):
                value = super().get(key, default)
                if type is not None:
                    try:
                        return type(value)
                    except (ValueError, TypeError):
                        return default
                return value
        self.request = SimpleNamespace(
            headers={'Accept': 'application/json'},
            form=Form(category='', state='all', direction=''),
        )
        def load(name, values=None):
            return load_function(ROOT / 'backend/app/web_app.py', name, {
                'request': self.request,
                'SiteNotification': SimpleNamespace(query=SimpleNamespace(
                    get_or_404=lambda identifier: SimpleNamespace(id=identifier),
                )),
                'jsonify': lambda data: data,
                'redirect': lambda _: 'redirect',
                'url_for': lambda *args, **kwargs: 'url',
                'abort': lambda code: (_ for _ in ()).throw(PermissionError(code)),
                'flash': lambda *args: None,
                **(values or {}),
            })
        self.single = load('notification_read')
        self.bulk = load('notifications_read_all')

    def test_observer_single_receipt_returns_fresh_count(self):
        result = self.single(7, self.role)
        self.assertEqual(result, {'ok': True, 'marked': 1, 'unread': 2})
        self.assertEqual(self.marked, [(23, [7])])

    def test_observer_bulk_receipt_returns_fresh_count(self):
        result = self.bulk(self.role)
        self.assertEqual(result, {'ok': True, 'marked': 1, 'unread': 2})
        self.assertEqual(self.marked, [(23, [7])])

    def test_hidden_notice_rejected_before_writing(self):
        with self.assertRaises(PermissionError):
            self.single(19, self.role)
        self.assertEqual(self.marked, [])


class ObserverReceiptUiTests(unittest.TestCase):
    def test_read_controls_visible_without_role_check(self):
        template = (ROOT / 'frontend/templates/system/notifications.html').read_text(encoding='utf-8')
        self.assertIn('data-notification-read', template)
        self.assertIn('data-notification-read-all', template)
        self.assertIn('data-notification-status', template)
        self.assertIn('Отметить прочитанным', template)
        # Read buttons aren't inside the super-admin-only compose panel.
        self.assertLess(template.index('data-notification-read'), template.index("current_user.role == 'super_admin' %}\n<section"))

    def test_ajax_updates_after_server_confirmation_and_fallback_remains(self):
        js = (ROOT / 'static/js/site.bundle.js').read_text(encoding='utf-8')
        self.assertIn("Accept: 'application/json'", js)
        self.assertIn("if (!response.ok || response.redirected)", js)
        self.assertIn("notifications:read", js)
        self.assertIn("if (!center || !window.fetch || !window.FormData) return", js)


if __name__ == '__main__':
    unittest.main()
