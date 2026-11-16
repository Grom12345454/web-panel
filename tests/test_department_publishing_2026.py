"""Department scoping and cross-channel durable dispatch without Flask dependencies.

These tests deliberately execute the project's unmodified function bodies through
AST to isolate authorisation and dispatch policy in the minimal build environment.
"""
import ast
import hashlib
import html
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]


def source_functions(path, names):
    tree = ast.parse((ROOT / path).read_text(encoding='utf8'))
    return [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]


class DepartmentAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ns = {'UserRole': SimpleNamespace(SUPER_ADMIN=SimpleNamespace(value='super_admin'),
                                          STAFF=SimpleNamespace(value='staff'),
                                          OBSERVER=SimpleNamespace(value='observer')),
              'SECTIONS': ('science', 'students', 'applications', 'events', 'lessons', 'notifications')}
        exec(compile(ast.Module(body=source_functions('backend/app/services/staff_access.py', {'allowed','direction_ids'}), type_ignores=[]),
                     'staff_access.py','exec'), ns)
        cls.allowed, cls.direction_ids = staticmethod(ns['allowed']), staticmethod(ns['direction_ids'])

    def user(self, rank='employee', direction=5, grants=(), active=True):
        return SimpleNamespace(role='staff', is_active=active, staff_rank=rank,
                               assigned_direction_id=direction, grants=list(grants))

    def test_legacy_head_rank_no_longer_grants_implicit_permissions(self):
        head = self.user('head')
        for section in ('science', 'students', 'applications', 'events', 'lessons', 'notifications'):
            self.assertFalse(self.allowed(head, 5, section, 'manage'))
            self.assertFalse(self.allowed(head, 6, section, 'view'))
            self.assertEqual(self.direction_ids(head, section, 'manage'), set())

    def test_employee_deputy_remain_explicitly_scoped(self):
        view = SimpleNamespace(direction_id=5, section='notifications', access='view')
        deputy = self.user('deputy', grants=[view])
        self.assertTrue(self.allowed(deputy, 5, 'notifications'))
        self.assertFalse(self.allowed(deputy, 5, 'notifications', 'manage'))
        self.assertFalse(self.allowed(deputy, 5, 'events'))
        self.assertFalse(self.allowed(deputy, 6, 'notifications'))
        self.assertEqual(self.direction_ids(deputy, 'notifications'), {5})

    def test_revoked_or_invalid_accounts_have_no_access(self):
        self.assertFalse(self.allowed(self.user('employee', active=False), 5, 'notifications', 'manage'))
        self.assertFalse(self.allowed(self.user('employee'), None, 'events', 'manage'))
        self.assertFalse(self.allowed(self.user('employee'), 5, 'unknown'))
        user = self.user('head'); user.role = 'operator'
        self.assertFalse(self.allowed(user, 5, 'notifications', 'manage'))


class StubField:
    def in_(self, values):
        return values


class StubModel:
    id = StubField()
    __table__ = object()
    def __init__(self, **kw):
        self.__dict__.update(kw)


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.notes = []
        self.jobs = {}
        suite = self

        class NoteQuery:
            def filter_by(self, **filters):
                self.filters = filters
                return self
            def first(self):
                return next((n for n in suite.notes if all(getattr(n,k,None)==v for k,v in self.filters.items())),None)
        class StubNote(StubModel):
            query = NoteQuery()
        class DirectionQuery:
            def filter(self, ids):
                self.ids = ids
                return self
            def all(self):
                return [SimpleNamespace(id=i) for i in self.ids if i in {5,6}]
        class StubDirection:
            id = StubField()
            query = DirectionQuery()
        class FakeInsert:
            def __init__(self, rows): self.rows = rows
            def on_conflict_do_nothing(self, index_elements):
                return self
        class Engine:
            def begin(self): return self
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def execute(self, query):
                for row in query.rows:
                    suite.jobs.setdefault(row['delivery_key'], row)
        class Session:
            def add(self, item): suite.notes.append(item)
            def commit(self): pass
        ns = {
            'ALL_CHANNELS': frozenset({'site','chats','dm','vk_chats','vk_dm','max_chats','max_dm','staff_dm'}),
            'Direction': StubDirection, 'SiteNotification': StubNote, 'BotDeliveryJob': StubModel,
            'TOKEN': {'telegram':lambda:'tg', 'vk':lambda:'vk', 'max':lambda:''},
            'db': SimpleNamespace(session=Session(),engines={'system':Engine()}),
            'recipients': lambda cohort, direction, channels: {'chats':['-100'], 'dm':['234']},
            'social_recipients': lambda cohort, direction, channels: {
                'vk_chats':['vkshared'], 'vk_dm':['user88'], 'max_chats':['maxchat'], 'max_dm':['maxuser']},
            '_staff_private_recipients': lambda ids, category:{'234','789'},
            'sha256': hashlib.sha256, 'html': html, 'datetime': datetime,
            'sqlite_insert': lambda table: SimpleNamespace(values=lambda rows: FakeInsert(rows)),
            'secrets': __import__('secrets'),
            'logger': SimpleNamespace(info=lambda *args: None),
        }
        exec(compile(ast.Module(body=source_functions('backend/app/services/direction_publishing.py', {'publish_direction_announcement'}),type_ignores=[]),
                     'direction_publishing.py','exec'),ns)
        self.publish = ns['publish_direction_announcement']

    def test_all_channels_and_repeated_publication_deduplicated(self):
        result = self.publish([5,6], 'Совещание', 'Дата и важные детали',
                              category='system', batch_key='announcement:1', source_type='event', source_id=7)
        self.assertEqual(len(self.notes),2)
        self.assertEqual(result['targets'],7)  # tg chat, tg private 234+789, vk chat+dm, max chat+dm
        self.assertEqual(result['queued'],5)
        self.assertEqual(result['blocked'],2)
        self.assertEqual(len(self.jobs),7)
        self.assertEqual(sum(1 for j in self.jobs.values() if j['recipient_id']=='234'), 1)
        self.publish([5,6], 'Совещание', 'Дата и важные детали',
                     category='system', batch_key='announcement:1')
        self.assertEqual(len(self.notes),2)
        self.assertEqual(len(self.jobs),7)

    def test_never_publish_without_valid_direction(self):
        for ids in ([], [999], [5,999]):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                self.publish(ids,'Title','Content')
        self.assertFalse(self.jobs)

    def test_global_superadmin_notice_is_unscoped_in_site_and_deduplicated_in_outbox(self):
        result = self.publish([], 'Общая рассылка', 'Информация всем участникам',
                              category='system', global_broadcast=True,
                              batch_key='admin:global:1',
                              channels={'site','chats','dm','vk_chats','vk_dm','max_chats','max_dm','staff_dm'})
        self.assertEqual(len(self.notes), 1)
        self.assertIsNone(self.notes[0].direction_id)
        self.assertEqual(result['targets'], 7)
        self.assertEqual(len(self.jobs), 7)
        self.publish([], 'Общая рассылка', 'Информация всем участникам',
                     global_broadcast=True, batch_key='admin:global:1')
        self.assertEqual(len(self.notes), 1)
        self.assertEqual(len(self.jobs), 7)

    def test_without_site_no_public_notification_created(self):
        result = self.publish([5], 'Title','Message',category='events',
                              channels={'dm','staff_dm'}, batch_key='dm-only')
        self.assertFalse(result['site'])
        self.assertFalse(self.notes)
        self.assertEqual(len(self.jobs),2)


if __name__ == '__main__':
    unittest.main()
