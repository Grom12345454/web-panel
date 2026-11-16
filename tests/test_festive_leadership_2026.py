"""Regressions for single public chair, verified contact cards, common themes, and staff permissions."""
from pathlib import Path
import ast
import re
import unittest
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


class Query:
    def __init__(self, rows): self.rows = rows
    def order_by(self, *args): return self
    def filter(self, *args): return self
    def all(self): return self.rows


class Field:
    def asc(self): return self
    def in_(self, values): return self


class FestiveLeadershipTests(unittest.TestCase):
    def test_only_one_public_chair_even_with_distinct_legacy_holders(self):
        first = SimpleNamespace(id=1, tg_id=123, telegram_username='First_Chair', full_name='Первый председатель', group='ИК-1')
        duplicate = SimpleNamespace(id=2, tg_id=None, telegram_username=None, full_name='Второй председатель', group='ИК-2')
        direction = SimpleNamespace(name='Волонтёры')
        rows = [SimpleNamespace(id=1, student=first, student_id=1, position_name='Председатель студсовета', education_type='all', direction_id=1, direction=direction),
                SimpleNamespace(id=2, student=duplicate, student_id=2, position_name='Председатель студсовета', education_type='all', direction_id=1, direction=direction)]
        class Leadership:
            id = Field()
            query = Query(rows)
        class Identity:
            student_id = Field()
            query = Query([SimpleNamespace(platform='vk', student_id=1, external_user_id='12345', public_username=None)])
        tree = ast.parse((ROOT/'backend/app/services/leadership_directory.py').read_text('utf-8'))
        funcs = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
        ns = {'StudentLeadership':Leadership, 'MessengerIdentity':Identity, 're':re,
              'role_label':lambda v:v, 'role_scope':lambda v,e:'all',
              'VISIBLE_POSITIONS':{'Председатель студсовета'}}
        exec(compile(ast.Module(body=funcs, type_ignores=[]), '<dir>', 'exec'), ns)
        cards = ns['leadership_cards']()
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]['full_name'], 'Первый председатель')
        self.assertEqual(cards[0]['links'][0]['handle'], '@First_Chair')
        self.assertEqual(cards[0]['links'][1]['handle'], 'ID 12345')

    def test_same_directory_served_to_student_site_and_bots(self):
        app = (ROOT / 'backend/app/web_app.py').read_text('utf-8')
        route = app.split('def student_app_leadership_directory():', 1)[1].split('@student_app_bp.route', 1)[0]
        self.assertIn('leadership_cards()', route)
        self.assertNotIn('raw_rows =', route)
        self.assertIn('leadership_cards()', app.split('def leadership_public(',1)[1])
        self.assertIn('leadership_cards()', (ROOT/'backend/app/handlers/menu.py').read_text('utf-8'))
        self.assertIn('leadership_plain_text', (ROOT/'backend/app/services/multi_messenger.py').read_text('utf-8'))

    def test_staff_can_read_but_only_super_admin_can_manage(self):
        panel = (ROOT/'frontend/templates/shared/base.html').read_text('utf-8')
        self.assertIn("url_for('admin.leadership_public')", panel)
        # The public navigation is before the super-admin-only group.
        self.assertLess(panel.index("url_for('admin.leadership_public')"), panel.index("{% if session.user_role == 'super_admin' %}"))
        app = (ROOT / 'backend/app/web_app.py').read_text('utf-8')
        self.assertIn('if current_user.role != UserRole.SUPER_ADMIN.value:', app.split('def manage_leadership(',1)[1].split('role_labels =',1)[0])
        self.assertIn('can_manage=current_user.role == UserRole.SUPER_ADMIN.value',app)
        self.assertIn('action == "resolve_chair"',app)
        self.assertIn('retained_student_id not in chair_ids',app)

    def test_theme_is_shared_by_both_products(self):
        app = (ROOT / 'backend/app/web_app.py').read_text('utf-8')
        panel = (ROOT/'frontend/templates/shared/base.html').read_text('utf-8')
        student = (ROOT/'frontend/templates/student/student_app.html').read_text('utf-8')
        self.assertIn('active_visual_theme', panel)
        self.assertIn('student_app_theme.css_vars', student)
        self.assertIn('current_student_app_season()', app)
        self.assertIn('festive-atmosphere', panel)
        self.assertIn('student-active-theme', student)
        self.assertNotIn('student-festive-glyph', student)
        self.assertIn('active-theme-indicator', panel)
        build = (ROOT/'scripts/build_assets.py').read_text('utf-8')
        self.assertIn("'staff/holiday-motion-2026.css'", build)
        self.assertIn("'student/holiday-motion-2026.css'", build)
        self.assertIn('prefers-reduced-motion:reduce', (ROOT/'frontend/assets/styles/staff/holiday-motion-2026.css').read_text('utf-8'))
        self.assertIn('prefers-reduced-motion: reduce', (ROOT/'frontend/assets/styles/shared/holiday-visual-v40.css').read_text('utf-8'))


if __name__ == '__main__':
    unittest.main()
