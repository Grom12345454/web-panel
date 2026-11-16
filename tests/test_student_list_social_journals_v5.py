"""V5 regression checks independent of Flask and real bot tokens."""
import ast
from datetime import date, timedelta
from pathlib import Path
import json
import shutil
import subprocess
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]


def test_student_app_list_and_detailed_lesson_card():
    if not shutil.which('node'):
        return
    js = (ROOT / 'frontend/assets/scripts/student/student_app.js').read_text('utf-8')
    functions = js[js.index('function studentTimelineItems('):js.index('function saveLessonCalendar(')]
    when = (date.today()+timedelta(days=2)).isoformat()
    script = f'''const esc=v=>String(v??'').replace(/&/g,'&amp;');
const state={json.dumps({'calendar':[{'kind':'lesson','id':7,'date':when,'title':'Лекция по дизайну','teacher':'Педагог','room':'210','direction_name':'Медиа','description':'Практика, работа в группе','time':'14:00'}, {'kind':'event','id':32,'event_id':6,'date':when,'title':'Фестиваль','time':'18:00'}],'events':[],'lessons':[]},ensure_ascii=False)};
const schedulePeriod='week', calendarKind='all', lessonModalId=7;
const visitedEventsBlock=()=>'';
{functions}
const list=schedule();
if(!list.includes('Лекция по дизайну')||!list.includes('Фестиваль')||!list.includes('mission-list-feed')||!list.includes('Подробнее'))throw new Error('Both items absent from list');
const detail=lessonDetail();
for(const text of ['КАРТОЧКА ЗАНЯТИЯ','Педагог','Практика, работа в группе','210','download-lesson'])if(!detail.includes(text))throw new Error('Lesson detail missing '+text);
'''
    result = subprocess.run(['node','-e',script],capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def test_student_cards_only_use_verified_social_accounts():
    contacts = (ROOT/'backend/app/services/student_contacts.py').read_text('utf-8')
    assert 'MessengerIdentity.query' in contacts
    assert "'vk'" in contacts and "'max'" in contacts
    assert 'external_user_id' in contacts
    templates=[ROOT/'frontend/templates/students/list.html',ROOT/'frontend/templates/students/form.html',ROOT/'frontend/templates/directions/detail.html']
    for file in templates:
        src=file.read_text('utf-8')
        assert 'vk' in src and 'max' in src
    assert '<small>Email</small>' not in templates[-1].read_text('utf-8')
    app=(ROOT / 'backend/app/web_app.py').read_text('utf-8')
    assert 'public_student_contacts(student_ids)' in app
    assert 'messenger_by_student=messenger_by_student' in app


def test_audit_and_bot_operational_routes_are_protected():
    src=(ROOT/'backend/app/services/bot_journal_routes.py').read_text('utf-8')
    tree=ast.parse(src)
    factory=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='register_journal_routes')
    funcs={x.name:x for x in factory.body if isinstance(x,ast.FunctionDef)}
    for name in ('bot_journal','delivery_export','retry_single_delivery'):
        assert any(isinstance(d,ast.Name) and d.id=='super_admin_required' for d in funcs[name].decorator_list)
    retry=ast.get_source_segment(src,funcs['retry_single_delivery'])
    assert "('failed', 'blocked')" in retry and 'BotDeliveryJob.id == job_id' in retry
    assert 'delivered' in retry
    admin=(ROOT / 'backend/app/web_app.py').read_text('utf-8')
    webtree=ast.parse(admin)
    route=next(x for x in webtree.body if isinstance(x,ast.FunctionDef) and x.name=='admin_audit_export')
    assert any(isinstance(d,ast.Name) and d.id=='super_admin_required' for d in route.decorator_list)
    assert 'BotDeliveryJob.__table__.delete()' not in retry


def test_templates_and_built_assets_are_valid():
    env=Environment(loader=FileSystemLoader(str(ROOT / 'frontend/templates')))
    for file in (ROOT / 'frontend/templates').rglob('*.html'):
        env.get_template(file.relative_to(ROOT / 'frontend/templates').as_posix())
    assert 'mission-list-schedule' in (ROOT/'static/css/student-app.bundle.css').read_text('utf-8')
    assert 'journal-operations-v5.css' in (ROOT/'static/css/site.bundle.css').read_text('utf-8')
