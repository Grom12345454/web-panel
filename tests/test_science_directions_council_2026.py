"""Regression checks for two independent definitions of direction.

No Flask, bot credentials or production databases are required.
"""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]


class ScientificDirectionTests(unittest.TestCase):
    def test_council_science_direction_is_seeded_as_an_ordinary_direction(self):
        source = (ROOT / 'backend/app/database/helpers.py').read_text('utf-8')
        tree = ast.parse(source)
        initializer = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'init_db')
        seed = next(node for node in ast.walk(initializer)
                    if isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == 'base' for t in node.targets))
        base = ast.literal_eval(seed.value)
        self.assertTrue(all('icon' not in entry for entry in base))
        entries = [entry for entry in base if entry['code'] == 'SCIENCE']
        self.assertEqual(1, len(entries))
        self.assertEqual('Научная деятельность', entries[0]['name'])
        self.assertNotIn('icon', entries[0])
        self.assertIn("Direction.query.filter_by(code=item['code'])", source)
        self.assertIn('existing_direction.icon = None', source)
        self.assertIn("Direction(**item, education_scope='both')", source)

    def test_science_reading_subject_area_is_separate_from_council_membership(self):
        source = (ROOT / 'backend/app/database/science.py').read_text('utf-8')
        tree = ast.parse(source)
        reading = next(c for c in tree.body if isinstance(c, ast.ClassDef) and c.name == 'ScienceReading')
        prop = next(x for x in reading.body if isinstance(x, ast.FunctionDef) and x.name == 'science_direction'
                    and isinstance(x.decorator_list[0], ast.Name))
        setter = next(x for x in reading.body if isinstance(x, ast.FunctionDef) and x.name == 'science_direction'
                      and isinstance(x.decorator_list[0], ast.Attribute))
        namespace = {}
        exec(compile(ast.Module(body=[prop, setter], type_ignores=[]), '<reading-property>', 'exec'), namespace)
        # An existing legacy category is displayed under the new heading and
        # an edit writes to the same persisted field without a destructive migration.
        model = SimpleNamespace(category='Информатика')
        self.assertEqual('Информатика', namespace['science_direction'].fget(model))
        namespace['science_direction'].fset(model, 'Биология')
        self.assertEqual('Биология', model.category)
        routes = (ROOT / 'backend/app/services/science_routes.py').read_text('utf-8')
        self.assertIn('direction_id=None', routes)  # never forces council membership
        self.assertIn('row.set_science_directions(direction_names)', routes)
        self.assertIn('science_direction_option', routes)
        self.assertIn('science_direction_custom', routes)
        self.assertIn("'science_direction': row.science_direction", routes)
        self.assertIn("'science_direction': r.science_direction", routes)

    def test_panel_public_catalogue_telegram_and_student_app_show_new_label(self):
        admin = (ROOT / 'frontend/templates/science/index.html').read_text('utf-8')
        public = (ROOT / 'frontend/templates/science/public.html').read_text('utf-8')
        bot = (ROOT / 'backend/app/handlers/science.py').read_text('utf-8')
        client = (ROOT / 'frontend/assets/scripts/student/student_app.js').read_text('utf-8')
        bundle = (ROOT / 'static/js/student-app.bundle.js').read_text('utf-8')
        for template in (admin, public):
            Environment().parse(template)
            self.assertIn('Научное направление', template)
            self.assertIn('group.name', template)
        self.assertIn('reading-direction', public)
        self.assertIn('data-science-direction=', public)
        self.assertIn('reading.science_directions', bot)
        self.assertIn('reading.science_direction||reading.category', client)
        self.assertIn('reading.science_direction||reading.category', bundle)
        self.assertNotIn('name="direction_id"', admin)

    def test_author_registration_is_independent_of_council_enrollment(self):
        science = (ROOT / 'backend/app/services/science_logic.py').read_text('utf-8')
        register = (ROOT / 'backend/app/services/applications.py').read_text('utf-8')
        api = (ROOT / 'backend/app/services/science_routes.py').read_text('utf-8')
        self.assertNotIn('council_registered', science)
        self.assertIn('council_registered=False', register)
        self.assertIn('allow_science=True', api)
        self.assertIn("@science_bp.get('/public')", api)
        self.assertIn('science_allowed(current_user', api)


if __name__ == '__main__':
    unittest.main()
