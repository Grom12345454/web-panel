"""Independent regression tests for public leadership roster."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
import re

ROOT=Path(__file__).resolve().parents[1]

class Query:
    def __init__(self, records): self.records=records
    def order_by(self,*args):return self
    def filter(self,*args):return self
    def all(self):return self.records

class LeadershipDirectoryTests(unittest.TestCase):
    def setUp(self):
        chair = SimpleNamespace(id=1, tg_id=100, telegram_username='chairuser', full_name='Chair Person', group='A-1')
        another = SimpleNamespace(id=2, tg_id=200, telegram_username=None, full_name='Deputy Person', group='B-1')
        rows=[SimpleNamespace(id=1,student_id=1,student=chair,position_name='Председатель студсовета',education_type='all',direction_id=1,direction=SimpleNamespace(name='Study')),
              SimpleNamespace(id=2,student_id=1,student=chair,position_name='Председатель студсовета',education_type='all',direction_id=2,direction=SimpleNamespace(name='Sport')),
              SimpleNamespace(id=3,student_id=2,student=another,position_name='Заместитель председателя студсовета по колледжу',education_type='college',direction_id=1,direction=None)]
        class Field:
            def asc(self):return self
            def in_(self, values):return self
        class StudentLeadership: id=Field();query=Query(rows)
        identities=[SimpleNamespace(platform='vk',student_id=1,external_user_id='12345',public_username=None),
                    SimpleNamespace(platform='max',student_id=2,external_user_id='6000',public_username='maxdeputy')]
        class MessengerIdentity: student_id=Field();query=Query(identities)
        module=ast.parse((ROOT/'backend/app/services/leadership_directory.py').read_text('utf-8'))
        funcs=[x for x in module.body if isinstance(x,ast.FunctionDef)]
        self.ctx={'StudentLeadership':StudentLeadership,'MessengerIdentity':MessengerIdentity,
                  'role_label':lambda v:v,
                  'role_scope':lambda v,e: 'all' if v.startswith('Председатель ') else 'college',
                  're':re,'VISIBLE_POSITIONS':frozenset({'Председатель студсовета','Заместитель председателя студсовета по колледжу'})}
        exec(compile(ast.Module(body=funcs,type_ignores=[]),'<leadership>','exec'),self.ctx)
    def test_one_chair_and_confirmed_contacts(self):
        result=self.ctx['leadership_cards']()
        self.assertEqual(len(result),2)
        self.assertEqual(sum(x['position']=='Председатель студсовета' for x in result),1)
        links={i['platform']:i['url'] for i in result[0]['links']}
        self.assertEqual(links['telegram'],'https://t.me/chairuser')
        self.assertEqual(links['vk'],'https://vk.com/id12345')
        self.assertEqual(result[1]['links'][0]['url'],'https://max.ru/maxdeputy')
    def test_no_fake_contacts(self):
        person=SimpleNamespace(tg_id=-100,telegram_username='fakeuser')
        self.assertEqual(self.ctx['profile_links'](person,[]),[])
    def test_vkmx_have_roster_command(self):
        bot=(ROOT/'backend/app/services/multi_messenger.py').read_text('utf8')
        self.assertIn("'/leadership'",bot)
        app=(ROOT / 'backend/app/web_app.py').read_text('utf8')
        self.assertIn('leadership_cards()',app)
if __name__=='__main__':unittest.main()
