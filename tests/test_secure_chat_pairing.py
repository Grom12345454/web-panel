"""Regression guards for explicit administrative chat binding and two-step pairing."""
from pathlib import Path
import ast
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SecureChatAndPairingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.web = (ROOT / 'backend/app/web_app.py').read_text(encoding='utf-8')
        cls.transport = (ROOT / 'backend/app/services/messenger_transports.py').read_text(encoding='utf-8')
        cls.pair = (ROOT / 'backend/app/services/multi_messenger.py').read_text(encoding='utf-8')
        cls.template = (ROOT / 'frontend/templates/system/notifications.html').read_text(encoding='utf-8')

    def test_chat_mutations_only_allow_super_admin(self):
        tree = ast.parse(self.web)
        for name in ('messenger_chat_create', 'messenger_chat_remove'):
            action = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
            decorators = [n.id for n in action.decorator_list if isinstance(n, ast.Name)]
            self.assertIn('super_admin_required', decorators)
        self.assertIn("{% if current_user.role == 'super_admin' %}", self.template)

    def test_chat_must_be_observed_and_never_connected_automatically(self):
        self.assertIn('MessengerChatCandidate.query.get', self.web)
        self.assertIn('candidate.platform != platform', self.web)
        self.assertIn("if text.lower() in {'/chatid', '/chat_id'}:", self.transport)
        self.assertIn("discover_chat('max', target", self.transport)
        self.assertIn("discover_chat('vk', peer_id", self.transport)
        self.assertNotIn('MessengerChat(', self.transport)
        self.assertIn('candidate_id', self.template)

    def test_link_code_never_immediately_links_sender(self):
        tree = ast.parse(self.pair)
        redeem = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'redeem_link_code')
        rendered = ast.get_source_segment(self.pair, redeem)
        self.assertNotIn('MessengerIdentity(', rendered)
        self.assertNotIn('student.tg_id =', rendered)
        self.assertIn('pending_external_user_id', rendered)
        self.assertIn('notify_link_request', rendered)
        self.assertIn('review_link_request', self.pair)

    def test_review_restricted_to_profile_owner_and_available_everywhere(self):
        self.assertIn('student_id=student.id', self.pair)
        self.assertIn('student_app_review_link_request', self.web)
        self.assertIn('account-review', (ROOT / 'static/js/student-app.bundle.js').read_text('utf-8'))
        tg = (ROOT / 'backend/app/handlers/messenger_link.py').read_text('utf-8')
        self.assertIn("F.data.startswith('pair:')", tg)
        self.assertIn("ForceReply(selective=True", tg)
        self.assertIn('message_callback', self.transport)
        self.assertIn("'payload': f'pair:approve:{request_id}'", self.transport)

    def test_database_migration_adds_existing_table_columns(self):
        db_helpers = (ROOT / 'backend/app/database/helpers.py').read_text('utf-8')
        for column in ('pending_external_user_id', 'pending_public_username', 'requested_at', 'rejected_at'):
            self.assertIn('"messenger_link_codes", "' + column + '"', db_helpers)


if __name__ == '__main__':
    unittest.main()
