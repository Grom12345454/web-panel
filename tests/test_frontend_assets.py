"""Template and asset integrity checks that do not start the web server."""
from __future__ import annotations

import re
import unittest
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = PROJECT_ROOT / "frontend/templates"
STATIC_DIR = PROJECT_ROOT / "static"


class FrontendAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
        cls.templates = sorted(TEMPLATES_DIR.rglob("*.html"))

    def test_all_jinja_templates_compile(self):
        for template_path in self.templates:
            with self.subTest(template=template_path.name):
                self.env.get_template(template_path.relative_to(TEMPLATES_DIR).as_posix())

    def test_template_static_asset_references_exist(self):
        pattern = re.compile(r"filename\s*=\s*['\"]([^'\"]+)['\"]")
        missing = []
        for template_path in self.templates:
            text = template_path.read_text(encoding="utf-8")
            for filename in pattern.findall(text):
                if "{{" in filename or filename.startswith(("http://", "https://")):
                    continue
                if not (STATIC_DIR / filename).is_file():
                    missing.append(f"{template_path.name}: {filename}")
        self.assertEqual(missing, [], "Missing static assets:\n" + "\n".join(missing))

    def test_shared_layout_has_one_maintained_stylesheet(self):
        base = (TEMPLATES_DIR / "dashboard/overview.html").read_text(encoding="utf-8")
        shared = (TEMPLATES_DIR / "shared/base.html").read_text(encoding="utf-8")
        self.assertIn('{% extends "shared/base.html" %}', base)
        self.assertNotRegex(shared, re.compile(r"<style\b", re.IGNORECASE))
        self.assertIn('css/site.bundle.css', shared)

    def test_student_app_uses_its_own_v9_design_layer(self):
        student_app = (TEMPLATES_DIR / "student/student_app.html").read_text(encoding="utf-8")
        self.assertIn("css/student-app.bundle.css", student_app)
        self.assertIn('class="student-app-body"', student_app)


if __name__ == "__main__":
    unittest.main(verbosity=2)
