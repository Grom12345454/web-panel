from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class StudentCampusSpaceBackgroundV48Tests(unittest.TestCase):
    def test_campus_space_image_is_shipped(self):
        image = ROOT / "static" / "images" / "campus-space.webp"
        self.assertTrue(image.is_file())
        self.assertGreater(image.stat().st_size, 10_000)

    def test_background_layer_is_last_in_student_css_bundle(self):
        build_script = (ROOT / "scripts" / "build_assets.py").read_text(encoding="utf-8")
        self.assertIn("'student/campus-space-background-v48.css'", build_script)
        bundle = (ROOT / "static" / "css" / "student-app.bundle.css").read_text(encoding="utf-8")
        self.assertIn("BEGIN frontend/assets/styles/student/campus-space-background-v48.css", bundle)
        self.assertGreater(
            bundle.rfind("BEGIN frontend/assets/styles/student/campus-space-background-v48.css"),
            bundle.rfind("BEGIN frontend/assets/styles/shared/holiday-visual-v40.css"),
        )

    def test_background_image_and_theme_tints_are_layered(self):
        css = (ROOT / "frontend" / "assets" / "styles" / "student" / "campus-space-background-v48.css").read_text(encoding="utf-8")
        self.assertIn('url("/static/images/campus-space.webp?v=48")', css)
        self.assertIn("var(--season-secondary-rgb", css)
        self.assertIn("var(--season-accent-rgb", css)
        self.assertIn("background-size: cover, cover, cover, cover", css)
        self.assertIn("body.student-app-body > .cosmos-field", css)

    def test_ambient_animation_respects_reduced_motion_and_no_cursor_lamp(self):
        css = (ROOT / "frontend" / "assets" / "styles" / "student" / "campus-space-background-v48.css").read_text(encoding="utf-8")
        self.assertIn("prefers-reduced-motion: no-preference", css)
        self.assertIn("prefers-reduced-motion: reduce", css)
        self.assertIn("body.student-app-body .student-festive-atmosphere", css)
        self.assertIn("display: none !important", css)
        self.assertIn("cosmos-field__comet", css)
        self.assertIn("animation: none !important", css)


if __name__ == "__main__":
    unittest.main()
