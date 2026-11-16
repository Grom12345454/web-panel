"""Role admission matrix against the actual pure policy functions (no DB writes)."""
from __future__ import annotations
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ast.parse((ROOT / 'backend/app/services' / 'permissions.py').read_text(encoding='utf-8'))


class DirectionLookup:
    @staticmethod
    def get(direction_id):
        return SimpleNamespace(id=direction_id) if direction_id in {1, 2} else None


class LeadershipPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        functions = {'normalize_role', 'role_scope', 'application_review_scope', 'can_manage_direction'}
        assignments = [node for node in SOURCE.body if isinstance(node, ast.Assign)]
        definitions = [node for node in SOURCE.body if isinstance(node, ast.FunctionDef) and node.name in functions]
        namespace = {'re': __import__('re'), 'Direction': SimpleNamespace(query=DirectionLookup())}
        exec(compile(ast.Module(body=assignments + definitions, type_ignores=[]), '<permissions>', 'exec'), namespace)
        cls.namespace = namespace

    def assert_role(self, title, direction, education, expected, assigned_direction=1):
        row = SimpleNamespace(position_name=title, education_type='institute', direction_id=assigned_direction)
        self.namespace['leadership_rows_for_tg'] = lambda _: (SimpleNamespace(id=1), [row])
        result = self.namespace['can_manage_direction'](100, direction, education)
        self.assertEqual(result, expected, f'{title} / direction={direction} / cohort={education}')

    def test_representative_and_chair_accept_all_students(self):
        for title in ['Представитель студсовета', 'Председатель студсовета']:
            for direction in [1, 2]:
                for education in ['college', 'institute']:
                    self.assert_role(title, direction, education, True)

    def test_college_deputy_accepts_only_college_across_directions(self):
        for direction in [1, 2]:
            self.assert_role('Заместитель председателя студсовета по колледжу', direction, 'college', True)
            self.assert_role('Заместитель председателя студсовета по колледжу', direction, 'institute', False)

    def test_institute_deputy_follows_explicit_college_cohort_requirement(self):
        for direction in [1, 2]:
            self.assert_role('Заместитель председателя студсовета по институту', direction, 'college', True)
            self.assert_role('Заместитель председателя студсовета по институту', direction, 'institute', False)

    def test_direction_leader_and_deputy_have_own_direction_only(self):
        for title in ['Глава направления', 'Заместитель главы направления']:
            self.assert_role(title, 1, 'college', True)
            self.assert_role(title, 1, 'institute', True)
            self.assert_role(title, 2, 'college', False)
            self.assert_role(title, 2, 'institute', False)

    def test_unappointed_titles_do_not_gain_authority(self):
        self.assert_role('Участник', 1, 'college', False)

    def test_unknown_direction_never_allowed(self):
        self.assert_role('Представитель студсовета', 999, 'college', False)


if __name__ == '__main__':
    unittest.main()
