"""Regression: only five assignable leadership positions, enforced by server."""
import ast
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LeadershipRoleSelectTests(unittest.TestCase):
    def test_dropdown_has_five_unique_positions_and_no_representative(self):
        html = (ROOT / 'frontend/templates/leadership/manage.html').read_text(encoding='utf-8')
        select = re.search(r'<select[^>]*id="role-code"[^>]*>(.*?)</select>', html, re.S)
        self.assertIsNotNone(select)
        options = re.findall(r'<option value="([^"]+)"[^>]*>([^<]+)</option>', select.group(1))
        self.assertEqual([code for code, _ in options], [
            'council_chair', 'council_deputy_college',
            'council_deputy_institute', 'direction_head', 'direction_deputy'
        ])
        self.assertEqual(len({label for _, label in options}), 5)
        self.assertNotIn('Представитель студсовета', select.group(1))

    def test_server_rejects_removed_position(self):
        source = (ROOT / 'backend/app/web_app.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        node = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == 'manage_leadership')
        mapping = next(n.value for n in ast.walk(node)
                       if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'role_labels' for t in n.targets))
        allowed = ast.literal_eval(mapping)
        self.assertEqual(len(allowed), 5)
        self.assertNotIn('council_representative', allowed)
        self.assertEqual(allowed['council_chair'], 'Председатель студсовета')
        self.assertIn('role_name = role_labels.get(role_key)', source)
        self.assertIn('not role_name', source)

    def test_js_preview_no_longer_offers_removed_role(self):
        html = (ROOT / 'frontend/templates/leadership/manage.html').read_text(encoding='utf-8')
        self.assertNotIn('council_representative', html)
        self.assertIn("role.value==='council_chair'", html)

    def test_legacy_permission_definitions_still_preserved(self):
        source = (ROOT / 'backend/app/services/permissions.py').read_text(encoding='utf-8')
        self.assertIn('представитель студсовета', source)


if __name__ == '__main__':
    unittest.main()
