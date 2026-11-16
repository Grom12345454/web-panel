"""Static and Jinja checks for Galaxy Mission Control 2.0 without a Flask install."""
from pathlib import Path
import subprocess
from datetime import datetime
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_renders_real_numbers_and_chart():
    minimal_base = '<html><body>{% block content %}{% endblock %}</body></html>'
    env = Environment(loader=ChoiceLoader([
        DictLoader({'shared/base.html': minimal_base}),
        FileSystemLoader(str(ROOT / 'frontend/templates')),
    ]))
    env.globals['url_for'] = lambda *a, **k: '/test'
    template = env.get_template('dashboard/overview.html')
    rows = [{'day': '25.10', 'count': 4, 'height_pct': 80}, {'day': '26.10', 'count': 5, 'height_pct': 100}]
    context = dict(
        dashboard_mode='full',
        dashboard_hero={'kicker':'TEST','title':'Центр','accent':'управления','description':'Тестовая панель','caption':'','actions':[]},
        dashboard_metrics=[
            {'href':'/students','icon':'◎','label':'Всего студентов','value':123,'detail':'Профили'},
            {'href':'/applications','icon':'◷','label':'Ожидают решения','value':9,'detail':'Заявки'},
            {'href':'/directions','icon':'✧','label':'Активные участия','value':58,'detail':'Участия'},
            {'href':'/calendar','icon':'✦','label':'Свободные места','value':17,'detail':'Места'},
        ],
        dashboard_attention_items=[], dashboard_upcoming_items=[], dashboard_calendar_href='/calendar',
        dashboard_show_overview_panels=True, dashboard_show_analytics=True, dashboard_show_directions=True,
        dashboard_tools=[],
        stats=dict(total_students=123, pending_apps=9, active_members=58, free_places=17),
        period=7, activity_days=rows, activity_total=9, recent_students=3,
        direction_stats=[], direction_members=[], upcoming_events=[],
        attention_items=[], bot_health=[], pending_delivery_jobs=0,
        session={'user_role': 'observer'},
    )
    html = template.render(**context)
    assert '123' in html and '58' in html and '17' in html
    assert 'mission-bars' in html and 'height:80%' in html
    assert 'Нет срочных задач' in html
    assert 'mission-bot-grid' not in html  # Monitoring is private to the super admin.
    context['session'] = {'user_role': 'super_admin'}
    assert 'mission-bot-grid' not in template.render(**context)  # All monitoring is on dedicated tabs.


def test_source_and_built_styles_match():
    for source, bundle in (
        ('frontend/assets/styles/staff/galaxy-mission-control-20.css', 'static/css/site.bundle.css'),
        ('frontend/assets/styles/student/galaxy-mission-student-20.css', 'static/css/student-app.bundle.css'),
        ('frontend/assets/styles/shared/orbital-experience-v3.css', 'static/css/site.bundle.css'),
    ):
        assert (ROOT / source).read_text() in (ROOT / bundle).read_text()


def test_student_navigation_and_real_application_metadata():
    js = (ROOT / 'frontend/assets/scripts/student/student_app.js').read_text()
    python = (ROOT / 'backend/app/web_app.py').read_text()
    for key in ('mission-bottom-nav', 'open-home-section', 'schedule-period',
                'saveLessonCalendar', 'mission-student-disclosure'):
        assert key in js or key in (ROOT / 'frontend/assets/styles/student/galaxy-mission-student-20.css').read_text()
    assert 'mission-app-progress' not in js  # removed at the student's request
    assert 'applicationProgress(' not in js
    assert '"submitted_at": row.joined_at.isoformat()' in python
    assert '"last_decision_at":' in python
    assert 'BotJournalEvent.query' in python
    subprocess.run(['node', '--check', str(ROOT / 'static/js/student-app.bundle.js')], check=True)
    subprocess.run(['node', '--check', str(ROOT / 'static/js/site.bundle.js')], check=True)


def test_templates_compiled():
    env = Environment(loader=FileSystemLoader(str(ROOT / 'frontend/templates')))
    for path in (ROOT / 'frontend/templates').rglob('*.html'):
        env.get_template(path.relative_to(ROOT / 'frontend/templates').as_posix())
