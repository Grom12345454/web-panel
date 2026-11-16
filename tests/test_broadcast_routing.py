"""Telegram broadcast routing with in-memory SQLite, no Flask/server dependencies."""
from __future__ import annotations
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

from sqlalchemy import Column, ForeignKey, Integer, String, Boolean, Table, create_engine
from sqlalchemy.orm import declarative_base, relationship, Session

ROOT = Path(__file__).resolve().parents[1]
CODE = ast.parse((ROOT / 'backend/app/services/system_broadcasts.py').read_text('utf-8'))
Base = declarative_base()
association = Table('student_directions', Base.metadata,
    Column('student_id', Integer, ForeignKey('students.id')),
    Column('direction_id', Integer, ForeignKey('directions.id')),
    Column('status', String(20)),
)

class Direction(Base):
    __tablename__ = 'directions'
    id = Column(Integer, primary_key=True)
    education_scope = Column(String(20), default='both')

class DirectionChat(Base):
    __tablename__ = 'direction_chats'
    id = Column(Integer, primary_key=True)
    direction_id = Column(Integer, ForeignKey('directions.id'))
    chat_id = Column(String(100))
    education_type = Column(String(20), default='all')
    is_active = Column(Boolean, default=True)
    direction = relationship('Direction')

class Student(Base):
    __tablename__ = 'students'
    id = Column(Integer, primary_key=True)
    tg_id = Column(Integer)
    education_type = Column(String(20))

class BroadcastRoutingTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.session.add_all([
            Direction(id=1, education_scope='both'),
            Direction(id=2, education_scope='college'),
            Direction(id=3, education_scope='institute'),
            DirectionChat(id=1, direction_id=1, chat_id='-1001', education_type='all', is_active=True),
            DirectionChat(id=2, direction_id=1, chat_id='-1002', education_type='college', is_active=True),
            DirectionChat(id=3, direction_id=1, chat_id='-1003', education_type='institute', is_active=True),
            DirectionChat(id=4, direction_id=2, chat_id='-1004', education_type='all', is_active=True),
            DirectionChat(id=5, direction_id=3, chat_id='-1005', education_type='all', is_active=True),
            DirectionChat(id=6, direction_id=3, chat_id='-1006', education_type='institute', is_active=False),
            Student(id=1, tg_id=101, education_type='college'),
            Student(id=2, tg_id=102, education_type='institute'),
            Student(id=3, tg_id=103, education_type='college'),
        ])
        self.session.flush()
        self.session.execute(association.insert(), [
            {'student_id':1,'direction_id':1,'status':'active'},
            {'student_id':2,'direction_id':1,'status':'active'},
            {'student_id':3,'direction_id':1,'status':'pending'},
            {'student_id':3,'direction_id':2,'status':'active'},
        ])
        self.session.commit()
        DirectionChat.query = self.session.query(DirectionChat)
        Student.query = self.session.query(Student)
        funcs = [node for node in CODE.body if isinstance(node, ast.FunctionDef)]
        self.fn = {'html': __import__('html'), 'DirectionChat': DirectionChat,
                   'Student': Student, 'student_directions': association,
                   'DirectionStatus': SimpleNamespace(ACTIVE=SimpleNamespace(value='active'))}
        exec(compile(ast.Module(body=funcs, type_ignores=[]), '<system_broadcasts>', 'exec'), self.fn)

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_all_chats_are_deduplicated_and_inactive_excluded(self):
        result = self.fn['recipients'](channels={'chats'})
        self.assertEqual(result['chats'], ['-1001','-1002','-1003','-1004','-1005'])

    def test_cohort_never_uses_untagged_mixed_chat(self):
        college = self.fn['recipients']('college', channels={'chats'})['chats']
        institute = self.fn['recipients']('institute', channels={'chats'})['chats']
        self.assertEqual(college, ['-1002', '-1004'])
        self.assertEqual(institute, ['-1003', '-1005'])
        self.assertNotIn('-1001', college + institute)

    def test_direction_scope_and_education_are_both_applied(self):
        self.assertEqual(self.fn['recipients']('college', 1, {'chats','dm'}),
                         {'chats': ['-1002'], 'dm': ['101']})
        self.assertEqual(self.fn['recipients']('institute', 2, {'chats','dm'}),
                         {'chats': [], 'dm': []})
        self.assertEqual(self.fn['recipients']('college', 2, {'dm'})['dm'], ['103'])

    def test_shared_chat_with_conflicting_cohort_is_excluded(self):
        self.session.add(DirectionChat(id=7, direction_id=3, chat_id='-1002', education_type='institute', is_active=True))
        self.session.commit()
        college = self.fn['recipients']('college', channels={'chats'})['chats']
        institute = self.fn['recipients']('institute', channels={'chats'})['chats']
        self.assertNotIn('-1002', college)
        self.assertNotIn('-1002', institute)
        self.assertNotIn('-1002', self.fn['recipients']('college', 1, {'chats'})['chats'])

    def test_global_dms_respect_cohort(self):
        self.assertEqual(self.fn['recipients']('college', channels={'dm'})['dm'], ['101','103'])
        self.assertEqual(self.fn['recipients']('institute', channels={'dm'})['dm'], ['102'])

    def test_message_is_escaped_for_telegram_html(self):
        msg = self.fn['telegram_message']('<b>A & B</b>', 'Hello <script>')
        self.assertIn('&lt;b&gt;A &amp; B&lt;/b&gt;', msg)
        self.assertNotIn('<script>', msg)
        self.assertIn('Системное уведомление', msg)

    def test_modal_menu_and_migration_present(self):
        ui = (ROOT/'frontend/templates/system/notifications.html').read_text('utf8')
        self.assertIn('<dialog id="broadcast-dialog"', ui)
        for value in ['site', 'chats', 'dm']:
            self.assertIn(f'name="channels" value="{value}"', ui)
        self.assertNotIn('<details class="card card-pad alerts-compose">', ui)
        self.assertNotIn('menu_guide', (ROOT/'backend/app/handlers/menu.py').read_text('utf8'))
        # New requirement: operators/observers may read the roster, not edit it.
        self.assertIn("url_for('admin.leadership_public')", (ROOT/'frontend/templates/shared/base.html').read_text('utf8'))
        active_direction_page = (ROOT/'frontend/templates/directions/detail.html').read_text('utf8')
        self.assertIn("url_for('directions.chat_audience'", active_direction_page)
        self.assertIn('name="education_type"', active_direction_page)
        migration = (ROOT/'backend/app/database/helpers.py').read_text('utf8')
        self.assertIn('"direction_chats","education_type"', migration)

if __name__ == '__main__':
    unittest.main()
