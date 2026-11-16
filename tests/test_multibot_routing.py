"""Test cohort isolation and channel filtering in VK/MAX without Flask/real tokens."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Table, create_engine
from sqlalchemy.orm import declarative_base, Session

ROOT = Path(__file__).resolve().parents[1]
Base = declarative_base()
student_directions = Table('student_directions', Base.metadata,
    Column('student_id', Integer, ForeignKey('students.id')),
    Column('direction_id', Integer, ForeignKey('directions.id')),
    Column('status', String(20)))

class Direction(Base):
    __tablename__ = 'directions'
    id = Column(Integer, primary_key=True)
    education_scope = Column(String(20))

class Student(Base):
    __tablename__ = 'students'
    id = Column(Integer, primary_key=True)
    education_type = Column(String(20))

class MessengerChat(Base):
    __tablename__ = 'messenger_chats'
    id = Column(Integer, primary_key=True)
    direction_id = Column(Integer)
    chat_id = Column(String(100))
    platform = Column(String(15))
    education_type = Column(String(20))
    is_active = Column(Boolean)

class MessengerIdentity(Base):
    __tablename__ = 'messenger_identities'
    id = Column(Integer, primary_key=True)
    student_id = Column(Integer)
    platform = Column(String(15))
    external_user_id = Column(String(100))

class MultibotRoutingTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite:///:memory:')
        Base.metadata.create_all(engine)
        self.engine = engine
        self.session = Session(engine)
        self.session.add_all([
            Direction(id=1, education_scope='both'),
            Direction(id=2, education_scope='college'),
            Direction(id=3, education_scope='institute'),
            Student(id=1, education_type='college'), Student(id=2, education_type='institute'),
            MessengerChat(id=1, platform='vk', direction_id=1, chat_id='20001', education_type='all', is_active=True),
            MessengerChat(id=2, platform='vk', direction_id=1, chat_id='20002', education_type='college', is_active=True),
            MessengerChat(id=3, platform='vk', direction_id=2, chat_id='20003', education_type='all', is_active=True),
            MessengerChat(id=4, platform='max', direction_id=1, chat_id='30001', education_type='institute', is_active=True),
            MessengerChat(id=5, platform='max', direction_id=1, chat_id='30002', education_type='all', is_active=True),
            MessengerIdentity(id=1, student_id=1, platform='vk', external_user_id='101'),
            MessengerIdentity(id=2, student_id=1, platform='max', external_user_id='201'),
            MessengerIdentity(id=3, student_id=2, platform='vk', external_user_id='102'),
            MessengerIdentity(id=4, student_id=2, platform='max', external_user_id='202'),
        ])
        self.session.flush()
        self.session.execute(student_directions.insert(), [
            {'student_id': 1, 'direction_id': 1, 'status': 'active'},
            {'student_id': 2, 'direction_id': 1, 'status': 'pending'},
        ])
        self.session.commit()
        for model in (Direction, Student, MessengerChat, MessengerIdentity):
            model.query = self.session.query(model)
        code = ast.parse((ROOT/'backend/app/services/system_broadcasts.py').read_text('utf8'))
        functions = [f for f in code.body if isinstance(f, ast.FunctionDef)]
        namespace = {'MessengerChat': MessengerChat, 'MessengerIdentity': MessengerIdentity,
                     'Direction': Direction, 'Student': Student, 'student_directions': student_directions,
                     'DirectionStatus': SimpleNamespace(ACTIVE=SimpleNamespace(value='active'))}
        exec(compile(ast.Module(body=functions, type_ignores=[]), '<source>', 'exec'), namespace)
        self.route = namespace['social_recipients']

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_only_one_contour_for_chats(self):
        result = self.route('college', channels={'vk_chats', 'max_chats'})
        self.assertEqual(result['vk_chats'], ['20002', '20003'])
        self.assertEqual(result['max_chats'], [])
        result = self.route('institute', channels={'vk_chats', 'max_chats'})
        self.assertEqual(result['vk_chats'], [])
        self.assertEqual(result['max_chats'], ['30001'])

    def test_linked_direct_messages_reuse_same_student_data(self):
        result = self.route('college', 1, {'vk_dm', 'max_dm'})
        self.assertEqual(result['vk_dm'], ['101'])
        self.assertEqual(result['max_dm'], ['201'])
        result = self.route('institute', 1, {'vk_dm', 'max_dm'})
        self.assertEqual(result['vk_dm'], [])
        self.assertEqual(result['max_dm'], [])

    def test_general_announcement_allows_unspecific_chats(self):
        result = self.route(channels={'vk_chats', 'max_chats'})
        self.assertEqual(result['vk_chats'], ['20001', '20002', '20003'])
        self.assertEqual(result['max_chats'], ['30001', '30002'])

    def test_env_and_webhook_security_wired(self):
        sample = (ROOT/'.env.example').read_text('utf8')
        for var in ('BOT_TOKEN=', 'BOT_USERNAME=', 'WEBAPP_URL=', 'VK_BOT_TOKEN=', 'VK_GROUP_ID=', 'MAX_BOT_TOKEN=', 'MAX_BOT_USERNAME=', 'MAX_MODE=', 'WEBHOOK_SECRET='):
            self.assertIn(var, sample)
        self.assertNotIn('MAX_WEBHOOK_URL=', sample)
        src = (ROOT / 'backend/app/web_app.py').read_text('utf8')
        self.assertIn("@app.post('/hooks/max')", src)
        self.assertIn('X-Max-Bot-Api-Secret', src)
        self.assertIn('hmac.compare_digest(supplied, settings.WEBHOOK_SECRET)', src)

if __name__ == '__main__':
    unittest.main()
