"""Real SQLite queue tests without Flask or real messenger credentials."""
import ast
from datetime import datetime, timedelta
from hashlib import sha256
from html import unescape
from pathlib import Path
from types import SimpleNamespace
import re
import sys
from types import ModuleType
from unittest.mock import patch
import unittest
import uuid

from sqlalchemy import create_engine, Boolean, Column, DateTime, Integer, String, Text, update, select
from sqlalchemy.orm import Session, declarative_base

ROOT = Path(__file__).resolve().parents[1]
Base = declarative_base()


class DirectionChat(Base):
    __tablename__ = 'direction_chats'
    id = Column(Integer, primary_key=True)
    direction_id = Column(Integer)
    chat_id = Column(String(100))
    is_active = Column(Boolean, default=True)


class MessengerChat(Base):
    __tablename__ = 'messenger_chats'
    id = Column(Integer, primary_key=True)
    platform = Column(String(16))
    direction_id = Column(Integer)
    chat_id = Column(String(100))
    is_active = Column(Boolean, default=True)


class BotDeliveryJob(Base):
    __tablename__ = 'bot_delivery_jobs'
    id = Column(Integer, primary_key=True)
    delivery_key = Column(String(64), unique=True)
    source_type = Column(String(20))
    source_id = Column(Integer)
    last_attempt_at = Column(DateTime)
    platform = Column(String(16))
    recipient_id = Column(String(100))
    is_chat = Column(Boolean)
    message = Column(Text)
    status = Column(String(16))
    attempts = Column(Integer)
    last_error = Column(String(80))
    created_at = Column(DateTime)
    next_attempt_at = Column(DateTime)
    locked_until = Column(DateTime)
    delivered_at = Column(DateTime)


class CalendarDeliveryOutboxTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.session.add_all([
            DirectionChat(id=1, direction_id=10, chat_id='-1001', is_active=True),
            DirectionChat(id=2, direction_id=20, chat_id='-1001', is_active=True),
            DirectionChat(id=3, direction_id=10, chat_id='-1002', is_active=False),
            MessengerChat(id=1, platform='vk', direction_id=10, chat_id='2000000001', is_active=True),
            MessengerChat(id=2, platform='max', direction_id=20, chat_id='555', is_active=True),
            MessengerChat(id=3, platform='max', direction_id=20, chat_id='777', is_active=False),
        ])
        self.session.commit()
        DirectionChat.query = self.session.query(DirectionChat)
        MessengerChat.query = self.session.query(MessengerChat)
        source = (ROOT / 'backend/app/services/delivery_outbox.py').read_text('utf8')
        syntax = ast.parse(source)
        functions = [n for n in syntax.body if isinstance(n, ast.FunctionDef)]
        self.settings = SimpleNamespace(BOT_TOKEN='TEST', VK_BOT_TOKEN='TEST', MAX_BOT_TOKEN='TEST')
        scope = dict(datetime=datetime, timedelta=timedelta, sha256=sha256,
                     unescape=unescape, re=re, uuid=uuid,
                     db=SimpleNamespace(engines={'system': self.engine}),
                     DirectionChat=DirectionChat, MessengerChat=MessengerChat,
                     BotDeliveryJob=BotDeliveryJob, update=update, select=select,
                     PLATFORM_TOKENS={
                         'telegram': lambda: self.settings.BOT_TOKEN,
                         'vk': lambda: self.settings.VK_BOT_TOKEN,
                         'max': lambda: self.settings.MAX_BOT_TOKEN,
                     }, logger=SimpleNamespace(warning=lambda *args: None,info=lambda *args: None))
        exec(compile(ast.Module(body=functions, type_ignores=[]), '<outbox>', 'exec'), scope)
        self.scope = scope

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_only_approved_live_chats_without_duplicates(self):
        self.assertEqual(self.scope['chat_targets']([10, 20]), [
            ('telegram', '-1001'), ('vk', '2000000001'), ('max', '555')
        ])

    def test_scoped_lesson_never_leaks_to_shared_chat_of_other_direction(self):
        # Telegram -1001 is bound to directions 10 and 20, whereas the lesson
        # targets direction 10 only. Sending there would expose it to 20.
        self.assertEqual(self.scope['chat_targets']([10]), [('vk', '2000000001')])

    def test_queued_all_platforms_and_dedupe_scheduled_retry(self):
        first = self.scope['enqueue_calendar_announcement'](
            [10, 20], '<b>Занятие</b> &amp; встреча', batch_key='event:44:scheduled')
        second = self.scope['enqueue_calendar_announcement'](
            [10, 20], '<b>Занятие</b> &amp; встреча', batch_key='event:44:scheduled')
        self.assertEqual(first['queued'], 3)
        self.assertEqual(second['queued'], 3)
        jobs = self.session.query(BotDeliveryJob).order_by(BotDeliveryJob.platform).all()
        self.assertEqual(len(jobs), 3, 'Idempotent batch must not double-send')
        self.assertEqual(jobs[0].message, 'Занятие & встреча')
        self.assertIn('<b>Занятие</b>', next(j.message for j in jobs if j.platform == 'telegram'))

    def test_no_token_skips_provider_without_losing_other_chats(self):
        self.settings.VK_BOT_TOKEN = ''
        result = self.scope['enqueue_calendar_announcement']([10, 20], 'Тест', batch_key='event:45')
        self.assertEqual(result['queued'], 2)
        self.assertEqual(result['missing_token']['vk'], 1)
        self.assertEqual(self.session.query(BotDeliveryJob).filter_by(platform='vk').one().status, 'blocked')

    def test_worker_retries_and_records_real_outcome(self):
        self.scope['enqueue_calendar_announcement']([10, 20], 'Расписание', batch_key='event:46')
        sent = []
        def fake_sender(platform, chat, message, is_chat):
            sent.append((platform, chat))
            return platform != 'max'
        fake_journal = ModuleType('services.bot_journal')
        fake_journal.record_bot_event = lambda *args, **kw: True
        with patch.dict(sys.modules, {'services.bot_journal': fake_journal}):
            count = self.scope['process_delivery_jobs'](sender=fake_sender)
        self.assertEqual(count, 3)
        jobs = {job.platform:job for job in self.session.query(BotDeliveryJob).all()}
        self.assertEqual(jobs['telegram'].status, 'delivered')
        self.assertEqual(jobs['vk'].status, 'delivered')
        self.assertEqual(jobs['max'].status, 'retry')
        self.assertEqual(jobs['max'].attempts, 1)

    def test_protection_against_missing_calendar_publishing(self):
        source = (ROOT / 'backend/app/web_app.py').read_text('utf8')
        run = (ROOT/'run.py').read_text('utf8')
        self.assertIn("Lesson.direction_id.in_(active_ids)", source)
        self.assertIn("is_closed=False, is_published=True", source)
        self.assertIn("queue_other_messenger_event(quota, text)", source)
        self.assertIn('ChatDeliveryScheduler', run)
        self.assertIn('EventPublishScheduler', run)
        self.assertIn('process_delivery_jobs', run)
        self.assertIn('BotDeliveryJob', (ROOT/'backend/app/database/system.py').read_text())


if __name__ == '__main__':
    unittest.main()
