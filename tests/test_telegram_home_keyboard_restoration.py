"""Regression coverage for post-registration menu restoration across messengers."""
import ast
import json
import re
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


class TelegramIdentityResolution(unittest.TestCase):
    def test_student_for_resolves_native_and_legacy_telegram_profiles(self):
        source = (ROOT / 'backend/app/services/multi_messenger.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                        and node.name == 'student_for')

        direct = SimpleNamespace(id=10, tg_id=12345, council_registered=True)
        legacy = SimpleNamespace(id=20, tg_id=-777, council_registered=True)
        rows_by_tg = {12345: direct}
        rows_by_id = {10: direct, 20: legacy}
        identities = {('telegram', '777'): SimpleNamespace(student_id=20),
                      ('vk', '1001'): SimpleNamespace(student_id=20),
                      ('max', 'max-user'): SimpleNamespace(student_id=20)}

        class Query:
            def filter_by(self, **kwargs):
                return SimpleNamespace(first=lambda: rows_by_tg.get(kwargs.get('tg_id')))
            def get(self, value):
                return rows_by_id.get(value)

        context = {
            'Student': SimpleNamespace(query=Query()),
            'identity': lambda platform, user_id: identities.get((platform, str(user_id))),
        }
        exec(compile(ast.Module(body=[function], type_ignores=[]), '<student-for>', 'exec'), context)
        resolve = context['student_for']
        self.assertIs(resolve('telegram', 12345), direct)
        self.assertIs(resolve('telegram', 777), legacy)
        self.assertIs(resolve('vk', 1001), legacy)
        self.assertIs(resolve('max', 'max-user'), legacy)

    def test_new_telegram_registration_stores_real_sender_id(self):
        source = (ROOT / 'backend/app/services/multi_messenger.py').read_text(encoding='utf-8')
        self.assertIn("int(user_id) if platform == 'telegram' and not existing", source)
        self.assertIn("if not existing and platform != 'telegram':", source)


class SharedKeyboardRestoration(unittest.TestCase):
    def test_home_menu_restores_chat_and_help_actions(self):
        import sys
        sys.path.insert(0, str(ROOT / 'backend/app'))
        from services.bot_ui import HOME_ROWS, action_to_command
        keys = [button.key for row in HOME_ROWS for button in row]
        self.assertEqual(len(keys), 10)
        self.assertIn('menu_chats', keys)
        self.assertIn('menu_help', keys)
        self.assertEqual(action_to_command('menu_chats'), '/my_chats')
        self.assertEqual(action_to_command('menu_help'), '/help')

    def test_vk_and_max_reply_keyboards_keep_all_ten_menu_actions(self):
        import sys
        sys.path.insert(0, str(ROOT / 'backend/app'))
        from services.bot_ui import HOME_ROWS
        source = ast.parse((ROOT / 'backend/app/services/messenger_transports.py').read_text(encoding='utf-8'))
        nodes = [node for node in source.body if isinstance(node, ast.FunctionDef)
                 and node.name in {'_vk_buttons', '_max_buttons'}]
        context = {'json': json, 're': re,
                   'settings': SimpleNamespace(MAX_BOT_USERNAME='staffbot'),
                   'vk_app_url': lambda: None, 'max_app_url': lambda: None}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), '<transport-keyboards>', 'exec'), context)
        vk = json.loads(context['_vk_buttons'](HOME_ROWS))
        vk_buttons = [button for row in vk['buttons'] for button in row]
        self.assertFalse(vk['inline'])
        self.assertEqual(len(vk_buttons), 10)
        max_markup = context['_max_buttons'](HOME_ROWS)[0]
        max_buttons = [button for row in max_markup['buttons'] for button in row]
        self.assertEqual(max_markup['type'], 'reply_keyboard')
        self.assertEqual(len(max_buttons), 10)
        self.assertTrue(any(button.get('payload') == 'ui:menu_chats' for button in max_buttons))
        self.assertTrue(any(button.get('payload') == 'ui:menu_help' for button in max_buttons))

    def test_all_telegram_user_lookups_use_shared_identity_resolver(self):
        for name in ('menu.py', 'registration.py'):
            source = (ROOT / 'backend/app/handlers' / name).read_text(encoding='utf-8')
            self.assertIn('def telegram_student_for(user_id):', source)
            self.assertNotIn('Student.query.filter_by(tg_id=', source)
        multi = (ROOT / 'backend/app/services/multi_messenger.py').read_text(encoding='utf-8')
        self.assertIn("if command in {'/my_chats', '/chats'}:", multi)
        self.assertIn("'/my_chats':'home'", multi)

    def test_chat_and_help_labels_resolve_on_all_three_platforms(self):
        import sys
        from unittest.mock import patch
        sys.path.insert(0, str(ROOT / 'backend/app'))
        from types import ModuleType
        from services.bot_ui import HOME_ROWS
        transport = ast.parse((ROOT / 'backend/app/services/messenger_transports.py').read_text(encoding='utf-8'))
        function = next(node for node in transport.body if isinstance(node, ast.FunctionDef)
                        and node.name == '_action_from_button_text')
        fake_multi = ModuleType('services.multi_messenger')
        fake_multi.student_for = lambda *args, **kwargs: None
        fake_multi.linked_account_status = lambda *args, **kwargs: {}
        fake_multi.pending_link_requests = lambda *args, **kwargs: []
        fake_multi._get_flow = lambda *args, **kwargs: None
        fake_apps = ModuleType('services.applications')
        fake_apps.available_application_directions = lambda *args, **kwargs: []
        context = {'logger': SimpleNamespace(debug=lambda *args, **kwargs: None)}
        exec(compile(ast.Module(body=[function], type_ignores=[]), '<button-resolver>', 'exec'), context)
        with patch.dict(sys.modules, {'services.multi_messenger': fake_multi,
                                      'services.applications': fake_apps}):
            for platform in ('telegram', 'vk', 'max'):
                self.assertEqual(context['_action_from_button_text'](platform, '💬 Мои чаты', 777), 'menu_chats')
                self.assertEqual(context['_action_from_button_text'](platform, '❔ Помощь', 777), 'menu_help')


if __name__ == '__main__':
    unittest.main()
