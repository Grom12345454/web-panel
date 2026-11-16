"""Regression tests: scientific disciplines, scoped senders, durable outbound fanout.

Use isolated policy bodies because the deployment-only Flask dependencies are
not available in the packaging environment.
"""
import ast
import hashlib
import html
import json
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def read_nodes(path, names):
    tree = ast.parse((ROOT / path).read_text(encoding='utf8'))
    return [x for x in tree.body if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef)) and x.name in names]


class StaffBroadcastScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        scope = {}
        scope['UserRole'] = SimpleNamespace(SUPER_ADMIN=SimpleNamespace(value='super_admin'),
                                            STAFF=SimpleNamespace(value='staff'))
        exec(compile(ast.Module(body=read_nodes('backend/app/services/broadcast_policy.py',
             {'broadcast_direction_ids', 'authorize_broadcast'}),type_ignores=[]), 'policy', 'exec'), scope)
        cls.rights = staticmethod(scope['broadcast_direction_ids'])
        cls.check = staticmethod(scope['authorize_broadcast'])

    def employee(self, role='staff', active=True, home=None, grants=()):
        return SimpleNamespace(role=role, is_active=active, assigned_direction_id=home,
                               staff_rank='employee', grants=[SimpleNamespace(direction_id=d, access=a, section='notifications')
                                                              for d,a in grants])

    def test_home_direction_only_broadcast_and_foreign_or_readonly_blocked(self):
        actor = self.employee(home=7, grants=[(3,'manage'),(7,'manage')])
        self.assertEqual(self.rights(actor), {7})
        self.assertEqual(self.check(actor,[7]),[7])
        with self.assertRaises(PermissionError):
            self.check(actor,[3])
        with self.assertRaises(PermissionError):
            self.check(actor,[],global_broadcast=True)
        readonly = self.employee(home=7, grants=[(7,'view')])
        self.assertEqual(self.rights(readonly), {7})
        with self.assertRaises(PermissionError):
            self.check(readonly,[7])
        with self.assertRaises(ValueError):
            self.check(actor,[])

    def test_global_superadmin_and_blocked_employee(self):
        admin = self.employee(role='super_admin')
        self.assertIsNone(self.check(admin,[],global_broadcast=True))
        self.assertEqual(self.check(admin,[1,5]),[1,5])
        disabled = self.employee(active=False, home=3)
        self.assertEqual(self.rights(disabled),set())
        with self.assertRaises(PermissionError):
            self.check(disabled,[3])


class ScientificDirectionModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse((ROOT / 'backend/app/database/science.py').read_text('utf8'))
        model = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name=='ScienceReading')
        methods = [n for n in model.body if isinstance(n, ast.FunctionDef) and n.name in
                   {'science_directions','set_science_directions'}]
        class Model:
            category = ''
            science_directions_json = None
        namespace = {'json': json, 'Model':Model}
        # Compile property and setter inside the plain test class body.
        fresh = ast.ClassDef(name='Reading', bases=[ast.Name(id='Model',ctx=ast.Load())],
                 keywords=[],decorator_list=[],body=methods)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[fresh],type_ignores=[])),'science', 'exec'), namespace)
        cls.Reading = namespace['Reading']

    def test_old_single_direction_is_readable(self):
        row=self.Reading();row.category='Химия'
        self.assertEqual(row.science_directions,['Химия'])

    def test_multi_choice_normalized_and_deduplicated(self):
        row=self.Reading()
        row.set_science_directions(['Химия',' Биология  ','химия'])
        self.assertEqual(row.science_directions,['Химия','Биология'])
        self.assertEqual(row.category,'Химия')
        for invalid in ([],['а'], ['Х']*13):
            if len(invalid)>1: invalid=[str(i)+'Наука' for i in range(13)]
            with self.assertRaises(ValueError): row.set_science_directions(invalid)


class SourceWiringTests(unittest.TestCase):
    def test_public_filters_and_student_app_represent_multiple_directions(self):
        public=(ROOT/'frontend/templates/science/public.html').read_text('utf8')
        student=(ROOT/'frontend/assets/scripts/student/student_app.js').read_text('utf8')
        science=(ROOT/'backend/app/services/science_routes.py').read_text('utf8')
        self.assertIn("card.dataset.scienceDirection===selected",public)
        self.assertIn('science_directions',student)
        self.assertIn("request.form.getlist('science_direction_options')",science)
        self.assertIn("'science_directions': row.science_directions",science)
        self.assertIn("'science_readings', 'science_directions_json'",(ROOT/'backend/app/database/helpers.py').read_text('utf8'))

    def test_scoped_admin_route_uses_persistent_outbox(self):
        app=(ROOT / 'backend/app/web_app.py').read_text('utf8')
        source=app[app.index('def notifications_publish('):app.index('@admin_bp.route("/notifications/messenger-chats/add"')]
        self.assertIn('authorize_broadcast(',source)
        self.assertIn('publish_direction_announcement(',source)
        self.assertNotIn('notification_queue.put_nowait',source)
        ui=(ROOT/'frontend/templates/system/notifications.html').read_text('utf8')
        self.assertNotIn('Чаты VK и MAX для уведомлений',ui)
        self.assertIn('data-broadcast-global',ui)
        self.assertIn('name="direction_ids"',ui)


if __name__ == '__main__':
    unittest.main()
