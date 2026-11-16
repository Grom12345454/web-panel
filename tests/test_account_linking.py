"""Account-pairing behavior tests with a local SQLite DB and no real API tokens."""
import ast
from datetime import datetime, timedelta
import hashlib
from pathlib import Path
import re
import secrets
from types import SimpleNamespace
import unittest

from sqlalchemy import Column, DateTime, Integer, String, create_engine, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import declarative_base, Session

ROOT = Path(__file__).resolve().parents[1]
Base = declarative_base()

class Student(Base):
    __tablename__ = 'students'
    id = Column(Integer, primary_key=True)
    tg_id = Column(Integer, unique=True)
    telegram_username = Column(String(100))

class MessengerIdentity(Base):
    __tablename__ = 'messenger_identities'
    id = Column(Integer, primary_key=True)
    platform = Column(String(15))
    external_user_id = Column(String(100))
    student_id = Column(Integer)
    public_username = Column(String(100))

class MessengerLinkCode(Base):
    __tablename__ = 'messenger_link_codes'
    id = Column(Integer, primary_key=True)
    code_hash = Column(String(64), unique=True)
    student_id = Column(Integer)
    target_platform = Column(String(15))
    expected_handle = Column(String(100))
    expires_at = Column(DateTime)
    used_at = Column(DateTime)
    pending_external_user_id = Column(String(100))
    pending_public_username = Column(String(100))
    requested_at = Column(DateTime)
    rejected_at = Column(DateTime)

NAMES = ('identity', 'student_for', 'linked_account_status', 'normalize_public_handle', 'verified_sender_handle', 'generate_link_code',
         'redeem_link_code', 'unlink_account', 'review_link_request', 'pending_link_requests')
SRC = ast.parse((ROOT/'backend/app/services/multi_messenger.py').read_text(encoding='utf8'))
FUNCS = [node for node in SRC.body if isinstance(node, ast.FunctionDef) and node.name in NAMES]

class AccountLinkingTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        for model in (Student, MessengerIdentity, MessengerLinkCode):
            model.query = self.session.query(model)
        self.session.add_all([Student(id=1, tg_id=1001), Student(id=2, tg_id=2002), Student(id=3, tg_id=-999)])
        self.session.commit()
        self.ctx = dict(Student=Student, MessengerIdentity=MessengerIdentity, MessengerLinkCode=MessengerLinkCode,
                        db=SimpleNamespace(session=self.session), datetime=datetime, timedelta=timedelta,
                        update=update, IntegrityError=IntegrityError, re=re, secrets=secrets,
                        LINK_TARGETS=frozenset({'telegram', 'vk', 'max'}),
                        _digest=lambda value: hashlib.sha256(('test-key|'+value.upper()).encode()).hexdigest())
        exec(compile(ast.Module(body=FUNCS, type_ignores=[]), '<account-linking>', 'exec'), self.ctx)

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_code_is_scoped_hashed_single_use(self):
        code = self.ctx['generate_link_code'](Student.query.get(1), 'vk')
        row = MessengerLinkCode.query.first()
        self.assertNotEqual(code, row.code_hash)
        self.assertEqual(row.target_platform, 'vk')
        self.assertIn('другой платформы', self.ctx['redeem_link_code']('max', '555', code))
        self.assertIn('Код принят', self.ctx['redeem_link_code']('vk', '555', code))
        self.assertIsNone(self.ctx['student_for']('vk', '555'))
        pending = self.ctx['pending_link_requests'](Student.query.get(1))
        self.assertEqual(len(pending), 1)
        self.assertIn('привязан', self.ctx['review_link_request'](Student.query.get(1), row.id, True))
        self.assertEqual(self.ctx['student_for']('vk', '555').id, 1)
        self.assertIn('недействителен', self.ctx['redeem_link_code']('vk', '555', code))

    def test_new_code_revokes_previous_code(self):
        student = Student.query.get(1)
        old = self.ctx['generate_link_code'](student, 'vk')
        new = self.ctx['generate_link_code'](student, 'max')
        self.assertIn('недействителен', self.ctx['redeem_link_code']('vk', '21', old))
        self.assertIn('Код принят', self.ctx['redeem_link_code']('max', '22', new))
        self.ctx['review_link_request'](student, MessengerLinkCode.query.filter_by(used_at=None).first().id, True)
        self.assertEqual(self.ctx['student_for']('max', '22').id, 1)

    def test_conflict_does_not_merge_students(self):
        student = Student.query.get(1)
        self.session.add(MessengerIdentity(platform='vk', external_user_id='777', student_id=2))
        self.session.commit()
        code = self.ctx['generate_link_code'](student, 'vk')
        self.assertIn('другому профилю', self.ctx['redeem_link_code']('vk', '777', code))
        self.assertEqual(MessengerIdentity.query.filter_by(external_user_id='777').first().student_id, 2)

    def test_cannot_override_different_existing_vk(self):
        self.session.add(MessengerIdentity(platform='vk', external_user_id='888', student_id=1))
        self.session.commit()
        with self.assertRaises(ValueError):
            self.ctx['generate_link_code'](Student.query.get(1), 'vk')
        # A legacy unscoped code must also not replace an existing VK ID.
        code = self.ctx['generate_link_code'](Student.query.get(1))
        self.assertIn('другой аккаунт', self.ctx['redeem_link_code']('vk', '999', code))

    def test_unlink_preserves_student_and_revokes_codes(self):
        student = Student.query.get(1)
        self.session.add(MessengerIdentity(platform='vk', external_user_id='55', student_id=1))
        self.session.commit()
        code = self.ctx['generate_link_code'](student, 'max')
        with self.assertRaises(ValueError):
            self.ctx['unlink_account'](student, 'vk', current_platform='vk')
        result = self.ctx['unlink_account'](student, 'vk', current_platform='telegram')
        self.assertIn('отвязан', result)
        self.assertIsNone(self.ctx['student_for']('vk', '55'))
        self.assertIsNotNone(Student.query.get(1))
        self.assertIn('недействителен', self.ctx['redeem_link_code']('max', '44', code))

    def test_cannot_unlink_final_identity(self):
        student = Student.query.get(3)
        self.session.add(MessengerIdentity(platform='max', external_user_id='3999', student_id=3))
        self.session.commit()
        with self.assertRaisesRegex(ValueError, 'последний'):
            self.ctx['unlink_account'](student, 'max', current_platform='vk')

    def test_vk_first_can_link_telegram(self):
        student = Student.query.get(3)
        self.session.add(MessengerIdentity(platform='vk', external_user_id='323', student_id=3))
        self.session.commit()
        code = self.ctx['generate_link_code'](student, 'telegram')
        self.assertIn('Код принят', self.ctx['redeem_link_code']('telegram', '3333', code))
        self.assertEqual(Student.query.get(3).tg_id, -999)
        self.ctx['review_link_request'](student, MessengerLinkCode.query.filter_by(used_at=None).first().id, True)
        self.assertEqual(Student.query.get(3).tg_id, 3333)
        self.assertEqual(self.ctx['student_for']('vk', '323').id, 3)

    def test_code_expiry(self):
        code = self.ctx['generate_link_code'](Student.query.get(1), 'vk')
        MessengerLinkCode.query.first().expires_at = datetime.utcnow() - timedelta(seconds=1)
        self.session.commit()
        self.assertIn('истёк', self.ctx['redeem_link_code']('vk', '556', code))

    def test_vk_id_must_match_confirmed_sender(self):
        code = self.ctx['generate_link_code'](Student.query.get(1), 'vk', 'id12345')
        self.assertEqual(MessengerLinkCode.query.first().expected_handle, '12345')
        self.assertIn('не совпадает', self.ctx['redeem_link_code']('vk', 54321, code))
        self.assertIn('Код принят', self.ctx['redeem_link_code']('vk', 12345, code))
        self.ctx['review_link_request'](Student.query.get(1), MessengerLinkCode.query.filter_by(used_at=None).first().id, True)

    def test_telegram_username_must_be_verified(self):
        code = self.ctx['generate_link_code'](Student.query.get(3), 'telegram', '@OfficialUser')
        self.assertIn('не совпадает', self.ctx['redeem_link_code']('telegram', 77, code, username='othername'))
        self.assertIn('Код принят', self.ctx['redeem_link_code']('telegram', 77, code, username='officialuser'))
        self.assertIsNone(Student.query.get(3).telegram_username)
        self.ctx['review_link_request'](Student.query.get(3), MessengerLinkCode.query.filter_by(used_at=None).first().id, True)
        self.assertEqual(Student.query.get(3).telegram_username, 'officialuser')

    def test_max_username_and_immutable_sender_id(self):
        code = self.ctx['generate_link_code'](Student.query.get(1), 'max', '@alex_user')
        self.assertIn('не совпадает', self.ctx['redeem_link_code']('max', 50, code, username=None))
        self.assertIn('Код принят', self.ctx['redeem_link_code']('max', 50, code, username='Alex_User'))
        self.assertIsNone(self.ctx['student_for']('max', 50))
        self.ctx['review_link_request'](Student.query.get(1), MessengerLinkCode.query.filter_by(used_at=None).first().id, True)
        row = MessengerIdentity.query.filter_by(platform='max').first()
        self.assertEqual(row.public_username, 'alex_user')
        self.assertEqual(row.external_user_id, '50')

    def test_reject_claim_from_other_person(self):
        student = Student.query.get(1)
        code = self.ctx['generate_link_code'](student, 'vk')
        self.assertIn('Код принят', self.ctx['redeem_link_code']('vk', 450, code))
        claim = MessengerLinkCode.query.filter_by(used_at=None).first()
        with self.assertRaises(ValueError):
            self.ctx['review_link_request'](Student.query.get(2), claim.id, True)
        self.assertIsNone(self.ctx['student_for']('vk', 450))
        self.assertIn('отклонён', self.ctx['review_link_request'](student, claim.id, False))
        self.assertIsNone(self.ctx['student_for']('vk', 450))
        self.assertIn('недействителен', self.ctx['redeem_link_code']('vk', 450, code))
        with self.assertRaises(ValueError):
            self.ctx['review_link_request'](student, claim.id, True)

    def test_stolen_code_never_grants_immediate_access(self):
        code = self.ctx['generate_link_code'](Student.query.get(1), 'vk')
        self.ctx['redeem_link_code']('vk', 321, code)
        self.assertIsNone(self.ctx['student_for']('vk', 321))
        self.assertIn('предъявлен другим', self.ctx['redeem_link_code']('vk', 543, code))
        self.assertIsNone(self.ctx['student_for']('vk', 543))

    def test_invalid_handles_rejected(self):
        for platform, handle in [('vk', 'name_without_id'), ('telegram', 'short'), ('max', 'a/b')]:
            with self.subTest(platform=platform):
                with self.assertRaises(ValueError):
                    self.ctx['generate_link_code'](Student.query.get(1), platform, handle)

    def test_ui_hooks_and_migration(self):
        backend = (ROOT / 'backend/app/web_app.py').read_text(encoding='utf8')
        for path in ('/student-app/api/accounts', '/student-app/api/accounts/code', '/student-app/api/accounts/<platform>'):
            self.assertIn(path, backend)
        self.assertIn('current_platform=actor', backend)
        self.assertIn('student_app_review_link_request', backend)
        self.assertIn('link_allowed', backend)
        self.assertIn('messenger_link_codes", "target_platform"', (ROOT/'backend/app/database/helpers.py').read_text('utf8'))
        js = (ROOT/'static/js/student-app.bundle.js').read_text('utf8')
        for fragment in ('Привязанные аккаунты', 'account-generate', 'account-confirm-unlink', 'account-review', 'ОТВЯЗАТЬ'):
            self.assertIn(fragment, js)
        bot = (ROOT/'backend/app/handlers/messenger_link.py').read_text('utf8')
        for fragment in ('account_code_vk', 'account_code_max', 'account_status', 'account_confirm_vk'):
            self.assertIn(fragment, bot)

if __name__ == '__main__':
    unittest.main()
