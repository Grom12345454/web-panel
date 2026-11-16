"""Exercise the actual Student App calendar renderer without Flask or DOM."""
import json
from datetime import date, timedelta
from pathlib import Path
import shutil
import subprocess
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'frontend/assets/scripts/student/student_app.js'


class StudentCalendarUiTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node required for JavaScript UI regression')
    def test_future_lesson_and_event_render_together(self):
        source = SOURCE.read_text('utf-8')
        parser = source[source.index('function studentTimelineItems('):source.index('function saveLessonCalendar(')]
        renderer = ''  # list and card renderer are included in parser
        upcoming = date.today() + timedelta(days=2)
        lesson_date = upcoming.strftime('%d.%m.%Y')
        event_date = upcoming.isoformat()
        script = (
            "const state = " + json.dumps({
                'lessons': [{'id': 10, 'title': 'Тестовое занятие',
                             'date': lesson_date, 'time': '12:30', 'end_time': '14:00',
                             'direction_name': 'Волонтёрка', 'description': '',
                             'room': '10', 'teacher': 'Педагог'}],
                'events': [{'id': 55, 'title': 'Тестовое мероприятие',
                            'days': [{'date': event_date, 'date_label': upcoming.strftime('%d.%m')}],
                            'location': 'Холл', 'time': '18:00'}],
            }, ensure_ascii=False) + ';\n'
            "const schedulePeriod='week',calendarKind='all',lessonModalId=10; const esc=x=>String(x||'');\n"
            + parser + renderer + "\nconst output=schedule();\n"
            "if(!output.includes('Тестовое занятие')||!output.includes('Тестовое мероприятие'))"
            "throw new Error('Student schedule omitted a calendar entry');\n"
            "if(!output.includes('data-action=\"open-event\"')||!output.includes('data-action=\"open-lesson\"'))"
            "throw new Error('Student schedule calendar actions missing');\n"
        )
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
