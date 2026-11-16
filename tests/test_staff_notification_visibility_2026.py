"""Real access-policy tests with light fakes, runnable without Flask dependencies."""
from __future__ import annotations

import ast
from functools import wraps
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
NOTIFICATIONS = ROOT / 'backend/app/services/site_notifications.py'
APP = ROOT / 'backend/app/web_app.py'


class Query:
    def __init__(self, rows):
        self.rows = rows

    def get(self, row_id):
        return self.rows.get(row_id)

    def filter_by(self, **kwargs):
        return SimpleNamespace(first=lambda: next((row for row in self.rows.values() if all(getattr(row, k, None) == v for k, v in kwargs.items())), None))


class NotificationRoleAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = ast.parse(NOTIFICATIONS.read_text(encoding='utf-8'))
        wanted = [n for n in root.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in {'AUDIENCES', 'STAFF_ROLES'} for t in n.targets)]
        wanted += [n for n in root.body if isinstance(n, ast.FunctionDef) and n.name == 'can_view']
        roles = SimpleNamespace(**{key: SimpleNamespace(value=value) for key, value in {
            'SUPER_ADMIN': 'super_admin', 'OPERATOR': 'operator', 'OBSERVER': 'observer', 'LEADER': 'leader'
        }.items()})
        cls.student_db = Query({1: SimpleNamespace(id=1, tg_id=100, education_type='college')})
        cls.namespace = {'UserRole': roles, 'Student': SimpleNamespace(query=cls.student_db),
                         'can_user_manage_direction': lambda uid, direction, education: uid == 4 and direction == 8}
        exec(compile(ast.Module(body=wanted, type_ignores=[]), '<access-policy>', 'exec'), cls.namespace)

    def show(self, role, audience='managers', student_id=1, direction_id=8, education='college', uid=None):
        user = SimpleNamespace(id=uid or {'super_admin': 1, 'operator': 2, 'observer': 3, 'leader': 4}.get(role, 5),
                               role=role, assigned_education_type='college' if role == 'leader' else 'all', tg_id=None)
        alert = SimpleNamespace(audience=audience, student_id=student_id,
                                direction_id=direction_id, education_type=education)
        return self.namespace['can_view'](user, alert)

    def test_three_staff_roles_see_activity_notifications_including_students(self):
        for role in ('super_admin', 'operator', 'observer'):
            with self.subTest(role=role):
                self.assertTrue(self.show(role, audience='managers'))
                self.assertTrue(self.show(role, audience='all'))
                self.assertTrue(self.show(role, audience='staff'))
                self.assertTrue(self.show(role, student_id=999))  # deleted student, audit record preserved
                self.assertTrue(self.show(role, student_id=None, education='institute'))

    def test_staff_targeting_excludes_direction_leaders(self):
        self.assertFalse(self.show('leader', audience='staff'))
        self.assertTrue(self.show('leader', audience='managers', uid=4))
        self.assertFalse(self.show('leader', audience='managers', direction_id=9, uid=4))
        self.assertFalse(self.show('leader', audience='managers', education='institute', uid=4))

    def test_explicitly_private_audiences_remain_private(self):
        self.assertTrue(self.show('super_admin', audience='admins'))
        self.assertFalse(self.show('operator', audience='admins'))
        self.assertFalse(self.show('observer', audience='admins'))
        self.assertTrue(self.show('operator', audience='operators'))
        self.assertFalse(self.show('observer', audience='operators'))
        self.assertFalse(self.show('observer', audience='leaders'))
        self.assertFalse(self.show('other', audience='staff'))
        self.assertFalse(self.show('observer', audience='invalid-audience'))

    def test_default_broadcast_includes_all_three_staff_roles(self):
        template = (ROOT / 'frontend/templates/system/notifications.html').read_text(encoding='utf8')
        self.assertIn('<option value="staff" selected>', template)
        self.assertIn("current_user.role == 'super_admin'", template)
        source = APP.read_text(encoding='utf8')
        self.assertIn('audience not in AUDIENCES', source)
        self.assertIn('@super_admin_required\ndef notifications_publish(', source)
        self.assertIn('@super_admin_required\ndef messenger_chat_create(', source)


class ObserverReadReceiptsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse(APP.read_text(encoding='utf-8'))
        nodes = [node for node in tree.body if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == 'OBSERVER_READ_RECEIPT_ENDPOINTS' for t in node.targets)]
        nodes.extend(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'login_required')
        user = SimpleNamespace(id=3, role='observer', email='observer@example.invalid')
        cls.request_mock = SimpleNamespace(method='GET', endpoint='admin.notifications', referrer=None)
        cls.session_mock = {'user_id': 3}
        cls.namespace = {
            'wraps': wraps,
            'request': cls.request_mock,
            'session': cls.session_mock,
            'User': SimpleNamespace(query=SimpleNamespace(get=lambda _: user)),
            'UserRole': SimpleNamespace(OBSERVER=SimpleNamespace(value='observer')),
            'g': SimpleNamespace(),
            'flash': lambda *args: None,
            'redirect': lambda url: f'REDIRECT:{url}',
            'url_for': lambda endpoint: endpoint,
        }
        exec(compile(ast.Module(body=nodes, type_ignores=[]), '<login-policy>', 'exec'), cls.namespace)

    def test_observer_can_read_and_acknowledge_notifications(self):
        called = []
        guarded = self.namespace['login_required'](lambda *, current_user: called.append(current_user.id) or 'OK')
        for method, endpoint in [('GET', 'admin.notifications'),
                                 ('POST', 'admin.notification_read'),
                                 ('POST', 'admin.notifications_read_all')]:
            with self.subTest(method=method, endpoint=endpoint):
                self.request_mock.method, self.request_mock.endpoint = method, endpoint
                self.assertEqual(guarded(), 'OK')
        self.assertEqual(called, [3, 3, 3])

    def test_observer_cannot_mutate_anything_else(self):
        called = []
        guarded = self.namespace['login_required'](lambda *, current_user: called.append(True) or 'OK')
        for endpoint in ('admin.notifications_publish', 'admin.messenger_chat_create',
                         'admin.messenger_chat_remove', 'admin.dashboard'):
            with self.subTest(endpoint=endpoint):
                self.request_mock.method, self.request_mock.endpoint = 'POST', endpoint
                self.assertEqual(guarded(), 'REDIRECT:admin.dashboard')
        self.assertFalse(called)
        source = APP.read_text(encoding='utf8')
        self.assertIn('supplied = request.form.get("csrf_token"', source)
        self.assertIn('hmac.compare_digest(str(expected), str(supplied))', source)


if __name__ == '__main__':
    unittest.main()
