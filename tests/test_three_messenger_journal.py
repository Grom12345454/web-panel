"""Operational journal regressions that run without Flask/Telegram dependencies."""
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
import ast
import hashlib
import hmac
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BotJournalTests(unittest.TestCase):
    def test_journal_template_and_36_templates_parse(self):
        env = Environment(loader=FileSystemLoader(ROOT / 'frontend/templates'))
        files = list((ROOT / 'frontend/templates').rglob('*.html'))
        self.assertGreaterEqual(len(files), 36)
        for file in files:
            with self.subTest(file=file.name):
                env.parse(file.read_text(encoding='utf-8'))

    def test_journal_routes_have_server_superadmin_gate(self):
        source = (ROOT / 'backend/app/services/bot_journal_routes.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        factory = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'register_journal_routes')
        routes = [node for node in factory.body if isinstance(node, ast.FunctionDef)]
        self.assertTrue({'bot_journal','bot_journal_check','bot_journal_export','retry_failed_deliveries', 'retry_single_delivery', 'delivery_export'}.issubset({node.name for node in routes}))
        for node in routes:
            self.assertTrue(any(isinstance(d, ast.Name) and d.id == 'super_admin_required' for d in node.decorator_list), node.name)
        base = (ROOT / 'frontend/templates/shared/base.html').read_text(encoding='utf-8')
        self.assertIn("session.user_role == 'super_admin'", base)
        self.assertIn("url_for('admin.user_activity_log')", base)
        self.assertNotIn('Центр событий', base)

    def test_three_bots_instrumented_without_storing_messages(self):
        tg = (ROOT / 'backend/app/bot.py').read_text(encoding='utf-8')
        transport = (ROOT / 'backend/app/services/messenger_transports.py').read_text(encoding='utf-8')
        self.assertIn('TelegramJournalMiddleware()', tg)
        self.assertIn("record_bot_event('vk', 'incoming'", transport)
        self.assertIn("record_bot_event('max', 'incoming'", transport)
        self.assertIn("'outgoing', 'message_sent'", transport)
        model = (ROOT / 'backend/app/database/system.py').read_text(encoding='utf-8')
        self.assertIn('class BotJournalEvent', model)
        self.assertNotIn('raw_message =', model)
        self.assertNotIn('message_body =', model)

    def test_sensitive_command_arguments_are_dropped(self):
        src = (ROOT / 'backend/app/services/bot_journal.py').read_text(encoding='utf-8')
        tree = ast.parse(src)
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'command_category')
        safe = next(node for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'SAFE_COMMANDS' for t in node.targets))
        namespace = {}
        exec(compile(ast.Module(body=[safe, function], type_ignores=[]), '<safe-journal>', 'exec'), namespace)
        classify = namespace['command_category']
        self.assertEqual(classify('/link 123456-secret'), '/link')
        self.assertEqual(classify('/code confidential'), '/code')
        self.assertEqual(classify('/start@SomeBot hello'), '/start')
        self.assertEqual(classify('Secret message contents'), 'text_message')
        self.assertEqual(classify('/password 123'), 'other_command')

    def test_account_alias_is_stable_across_events_but_not_raw_id(self):
        src = (ROOT / 'backend/app/services/bot_journal.py').read_text(encoding='utf-8')
        tree = ast.parse(src)
        fun = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'actor_alias')
        class FakeSettings:
            SECRET_KEY = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
        scope = {'hmac':hmac, 'hashlib':hashlib, 'settings': FakeSettings()}
        exec(compile(ast.Module(body=[fun], type_ignores=[]), '<alias>', 'exec'), scope)
        f = scope['actor_alias']
        self.assertEqual(f('telegram', 123), f('telegram', 123))
        self.assertNotEqual(f('telegram', 123), f('vk', 123))
        self.assertEqual(len(f('max', 321)), 12)
        self.assertNotIn('123', f('telegram', 123))

    def test_export_privacy_and_capped_records(self):
        routes = (ROOT / 'backend/app/services/bot_journal_routes.py').read_text(encoding='utf-8')
        self.assertIn('.limit(5000)', routes)
        self.assertIn('text/csv', routes)
        css = (ROOT / 'static/css/bot-journal.css').read_text(encoding='utf-8')
        self.assertIn('@media(max-width:660px)', css)
        self.assertIn('prefers-reduced-motion:reduce', css)


if __name__ == '__main__':
    unittest.main()
