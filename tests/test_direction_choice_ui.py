"""Regression coverage for the event and lesson direction selectors."""
from pathlib import Path
import json
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DirectionChoiceUITests(unittest.TestCase):
    def test_event_form_uses_separated_multi_select_cards(self):
        source = (ROOT / "frontend/templates/events/form.html").read_text(encoding="utf-8")
        self.assertIn('direction-choice-grid--multiple', source)
        self.assertIn('name="direction_ids"', source)
        self.assertIn('class="direction-toggle direction-choice-input"', source)
        self.assertIn('id="event-chat-options"', source)
        self.assertIn('event => {\n    if (!validateDirections()) event.preventDefault();', source)

    def test_lesson_form_uses_single_select_radios_and_preserves_edit_value(self):
        source = (ROOT / "frontend/templates/lessons/form.html").read_text(encoding="utf-8")
        self.assertIn('direction-choice-grid--single', source)
        self.assertIn('type="radio"', source)
        self.assertIn('name="direction_id"', source)
        self.assertIn('lesson.direction_id if editing else selected_direction', source)
        self.assertNotIn('<select class="select" id="direction-id" name="direction_id"', source)

    def test_picker_css_is_loaded_last_in_site_bundle_and_manifest(self):
        builder = (ROOT / "scripts/build_assets.py").read_text(encoding="utf-8")
        manifest = json.loads((ROOT / "frontend/asset-manifest.json").read_text(encoding="utf-8"))
        source = ROOT / "frontend/assets/styles/shared/direction-choice-ui.css"
        bundle = (ROOT / "static/css/site.bundle.css").read_text(encoding="utf-8")
        css = source.read_text(encoding="utf-8")
        self.assertTrue(source.is_file())
        self.assertIn("shared/direction-choice-ui.css", builder)
        self.assertEqual(manifest["bundles"]["site_css"]["files"][-1], "shared/direction-choice-ui.css")
        self.assertIn("direction-choice-card:has(.direction-choice-input:checked)", css)
        self.assertIn("@media (max-width: 480px)", css)
        self.assertIn("prefers-reduced-motion: reduce", css)
        self.assertIn(css.strip(), bundle)

    def test_picker_does_not_change_backend_form_contract(self):
        source = (ROOT / "backend/app/web_app.py").read_text(encoding="utf-8")
        self.assertIn('request.form.getlist("direction_ids", type=int)', source)
        self.assertIn('request.form.get("direction_id", type=int)', source)
        self.assertIn('direction_id": direction.id', source)


if __name__ == "__main__":
    unittest.main()
