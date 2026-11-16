"""Static regression checks for the merged staff calendar."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class UnifiedCalendarTests(unittest.TestCase):
    def test_calendar_route_combines_lessons_and_event_occurrences(self):
        source = (ROOT / "backend/app/web_app.py").read_text(encoding="utf-8")
        route = source[source.index('@admin_bp.route("/calendar")'):source.index('@admin_bp.route("/student-app/design"', source.index('@admin_bp.route("/calendar")'))]
        self.assertIn("Lesson.query", route)
        self.assertIn("EventQuota.query", route)
        self.assertIn("for day in quota.days", route)
        self.assertIn('"type": "lesson"', route)
        self.assertIn('"type": "event"', route)
        self.assertIn('render_template(\n        "calendar/index.html"', route)

    def test_navigation_has_one_calendar_entry_for_both_kinds(self):
        base = (ROOT / "frontend/templates/shared/base.html").read_text(encoding="utf-8")
        self.assertIn("href=\"{{ url_for('admin.calendar') }}\"", base)
        self.assertIn("<span>Календарь</span>", base)
        self.assertIn("ep.startswith('quotas.') or ep.startswith('lessons.')", base)
        self.assertNotIn("<span>Мероприятия</span>", base)
        self.assertNotIn("<span>Занятия</span>", base)

    def test_calendar_template_has_month_agenda_filters_and_context_panel(self):
        template = (ROOT / "frontend/templates/calendar/index.html").read_text(encoding="utf-8")
        for expected in (
            'id="calendar-month-grid"', 'id="calendar-agenda-view"',
            'id="calendar-type-filter"', 'id="calendar-direction-filter"',
            'id="calendar-day-events"', 'id="calendar-event-detail"',
            "url_for('lessons.create_lesson'", "url_for('quotas.create_quota'", "calendar_events|tojson",
        ):
            self.assertIn(expected, template)

    def test_calendar_assets_are_part_of_production_bundles(self):
        builder = (ROOT / "scripts/build_assets.py").read_text(encoding="utf-8")
        site_css = (ROOT / "static/css/site.bundle.css").read_text(encoding="utf-8")
        site_js = (ROOT / "static/js/site.bundle.js").read_text(encoding="utf-8")
        self.assertIn("portal/calendar.css", builder)
        self.assertIn("portal/calendar.js", builder)
        self.assertIn("Unified staff calendar", site_css)
        self.assertIn("Unified calendar UI", site_js)

    def test_calendar_creation_preserves_selected_date_and_returns_to_calendar(self):
        event_form = (ROOT / "frontend/templates/events/form.html").read_text(encoding="utf-8")
        lesson_form = (ROOT / "frontend/templates/lessons/form.html").read_text(encoding="utf-8")
        source = (ROOT / "backend/app/web_app.py").read_text(encoding="utf-8")
        self.assertIn('data-initial-date="{{ selected_date', event_form)
        self.assertIn('name="calendar_date"', event_form)
        self.assertIn('name="return_to" value="calendar"', event_form)
        self.assertIn("selected_datetime=selected_datetime", source)
        self.assertIn("request.form.get(\"return_to\") == \"calendar\"", source)
        self.assertIn("selected_datetime or ''", lesson_form)

    def test_selected_date_survives_calendar_actions_and_return_navigation(self):
        template = (ROOT / "frontend/templates/calendar/index.html").read_text(encoding="utf-8")
        script = (ROOT / "frontend/assets/scripts/portal/calendar.js").read_text(encoding="utf-8")
        lesson_form = (ROOT / "frontend/templates/lessons/form.html").read_text(encoding="utf-8")
        participant_form = (ROOT / "frontend/templates/events/participants.html").read_text(encoding="utf-8")
        self.assertIn('data-initial-date="{{ selected_date }}"', template)
        self.assertIn("const requestedDate =", script)
        self.assertIn("calendarDate.name = 'calendar_date'", script)
        self.assertIn("withCalendarDate(href)", script)
        self.assertIn('name="calendar_date"', lesson_form)
        self.assertIn("date=request.args.get('date')", participant_form)

    def test_quota_form_uses_calendar_date_for_initial_day(self):
        js = (ROOT / "frontend/assets/scripts/portal/app.js").read_text(encoding="utf-8")
        self.assertIn("addDay(form.dataset.initialDate || '')", js)


if __name__ == "__main__":
    unittest.main()
