"""Regressions for stale password tabs and cross-platform bot navigation."""
from pathlib import Path
import ast
import json
import re
import unittest
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


class PasswordTabSafety(unittest.TestCase):
    def test_password_page_is_not_cacheable_and_csrf_failure_reloads_page(self):
        source = (ROOT / 'backend/app/web_app.py').read_text(encoding='utf-8')
        self.assertIn('if request.path == "/auth/change-password":', source)
        self.assertIn('top-level browsing context to a fresh GET', source)
        self.assertIn('auth/change-password', source)
        self.assertIn('redirect(url_for("auth.change_password", refresh="1"), code=303)', source)
        self.assertIn('redirect(url_for("auth.login"), code=303)', source)
        self.assertIn('no-store, no-cache, must-revalidate, max-age=0', source)
        self.assertIn('auth/change_password', source)

    def test_password_form_is_standalone_and_posts_to_same_origin_route(self):
        template = (ROOT / 'frontend/templates/auth/change_password.html').read_text(encoding='utf-8')
        self.assertIn('<!doctype html>', template.lower())
        self.assertIn('action="{{ url_for(\'auth.change_password\') }}"', template)
        self.assertIn('name="csrf_token"', template)
        self.assertIn('target="_top"', template)
        self.assertNotIn('aria-modal', template)
        self.assertNotIn('position:fixed', template)


class SharedBotNavigation(unittest.TestCase):
    def test_three_platforms_share_home_and_context_navigation(self):
        import sys
        sys.path.insert(0, str(ROOT / 'backend/app'))
        from services.bot_ui import HOME_ROWS, rows_for_screen
        keys = [button.key for row in HOME_ROWS for button in row]
        for key in ('menu_apply', 'menu_status', 'menu_events', 'menu_profile',
                    'menu_app', 'menu_accounts', 'menu_leadership', 'menu_inbox'):
            self.assertIn(key, keys)
        self.assertTrue(any(button.key == 'menu_events' for row in rows_for_screen('status') for button in row))
        self.assertTrue(any(button.key == 'menu_accounts' for row in rows_for_screen('profile') for button in row))
        self.assertTrue(any(button.key == 'menu_home' for row in rows_for_screen('inbox') for button in row))
        self.assertEqual(__import__('services.bot_ui', fromlist=['action_to_command']).action_to_command('account_unlink_vk'), '/unlink vk')
        self.assertEqual(__import__('services.bot_ui', fromlist=['action_to_command']).action_to_command('unlink_confirm_max'), '/unlink_confirm max')
        confirm = rows_for_screen('unlink_confirm', target_platform='max')
        self.assertEqual(confirm[0][0].key, 'unlink_confirm_max')

    def test_max_app_link_uses_max_username_not_telegram_username(self):
        source = (ROOT / 'backend/app/services/messenger_transports.py').read_text(encoding='utf-8')
        self.assertIn("'https://max.ru/' + settings.MAX_BOT_USERNAME + '?startapp'", source)
        self.assertNotIn("'https://max.ru/' + settings.BOT_USERNAME", source)
        config = (ROOT / 'backend/app/config.py').read_text(encoding='utf-8')
        self.assertIn('MAX_BOT_USERNAME = os.getenv("MAX_BOT_USERNAME", "").strip().lstrip("@")', config)

    def test_vk_and_max_keep_student_app_action_without_public_url(self):
        source = ast.parse((ROOT / 'backend/app/services/messenger_transports.py').read_text(encoding='utf-8'))
        wanted = {'_vk_buttons', '_max_buttons'}
        nodes = [node for node in source.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
        sys_path = str(ROOT / 'backend/app')
        import sys
        sys.path.insert(0, sys_path)
        from services.bot_ui import HOME_ROWS
        context = {
            'json': json, 're': re,
            'settings': SimpleNamespace(MAX_BOT_USERNAME=''),
            'vk_app_url': lambda: None,
            'max_app_url': lambda: None,
        }
        exec(compile(ast.Module(body=nodes, type_ignores=[]), '<bot-buttons>', 'exec'), context)
        vk_markup = json.loads(context['_vk_buttons'](HOME_ROWS))
        self.assertFalse(vk_markup['inline'])
        vk = vk_markup['buttons']
        vk_payloads = [json.loads(button['action']['payload']).get('ui')
                       for row in vk for button in row if button['action'].get('payload')]
        self.assertIn('menu_app', vk_payloads)
        max_attachment = context['_max_buttons'](HOME_ROWS)[0]
        self.assertEqual(max_attachment['type'], 'reply_keyboard')
        max_rows = max_attachment['buttons']
        max_payloads = [button.get('payload') for row in max_rows for button in row]
        self.assertIn('ui:menu_app', max_payloads)


    def test_vk_message_allow_sends_the_same_start_menu(self):
        import sys
        from contextlib import nullcontext
        from types import SimpleNamespace
        sys.path.insert(0, str(ROOT / 'backend/app'))
        source = (ROOT / 'backend/app/services/messenger_transports.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                        and node.name == 'handle_vk_event')
        sent = []
        journal = []
        context = {
            '_deliver_private': lambda platform, user_id, text: ('Welcome', {'rows': (('home',),), 'app': False}),
            'send_message': lambda *args, **kwargs: sent.append((args, kwargs)) or True,
            'record_bot_event': lambda *args, **kwargs: journal.append((args, kwargs)),
            'logger': SimpleNamespace(exception=lambda *a, **k: None),
        }
        exec(compile(ast.Module(body=[function], type_ignores=[]), '<vk-event>', 'exec'), context)
        app = SimpleNamespace(app_context=lambda: nullcontext())
        context['handle_vk_event']({'type': 'message_allow', 'object': {'user_id': 12345}}, app)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][0][:3], ('vk', 12345, 'Welcome'))
        self.assertEqual(journal[0][0][:3], ('vk', 'incoming', 'bot_started'))

    def test_invalid_telegram_token_is_not_restarted_as_transient_error(self):
        source = (ROOT / 'backend/app/bot.py').read_text(encoding='utf-8')
        self.assertIn('await bot.get_me()', source)
        self.assertIn('except TelegramUnauthorizedError:', source)
        self.assertIn('telegram_disabled_invalid_token', source)
        supervisor = (ROOT / 'backend/app/services/runtime_supervisor.py').read_text(encoding='utf-8')
        self.assertIn('class PermanentWorkerExit', supervisor)
        self.assertIn('except PermanentWorkerExit as error:', supervisor)


class BottomKeyboardAndTelegramRetry(unittest.TestCase):
    def test_telegram_home_keyboard_is_persistent_and_docked(self):
        source = (ROOT / 'backend/app/handlers/menu.py').read_text(encoding='utf-8')
        self.assertIn('ReplyKeyboardMarkup(', source)
        self.assertIn('is_persistent=True', source)
        self.assertIn('resize_keyboard=True', source)
        self.assertIn('home_reply_keyboard', source)
        self.assertIn('_action_from_button_text', source)

    def test_telegram_proxy_is_optional_and_secret_is_not_logged(self):
        source = (ROOT / 'backend/app/bot.py').read_text(encoding='utf-8')
        config = (ROOT / 'backend/app/config.py').read_text(encoding='utf-8')
        env_example = (ROOT / '.env.example').read_text(encoding='utf-8')
        self.assertIn('def _create_telegram_bot(token):', source)
        self.assertIn('AiohttpSession(proxy=proxy)', source)
        self.assertIn('TELEGRAM_PROXY', config)
        self.assertIn('TELEGRAM_PROXY=', env_example)
        self.assertIn('aiohttp-socks', (ROOT / 'requirements.txt').read_text(encoding='utf-8'))
        self.assertIn("parsed.scheme, parsed.hostname", source)
        self.assertNotIn('logger.info("telegram_proxy_configured proxy=%s", proxy)', source)

    def test_telegram_network_errors_are_retried_inside_worker(self):
        source = (ROOT / 'backend/app/bot.py').read_text(encoding='utf-8')
        self.assertIn('async def _ensure_telegram_ready', source)
        self.assertIn('async def _poll_telegram_with_retry', source)
        self.assertIn('TelegramNetworkError', source)
        self.assertIn('await asyncio.sleep(wait_for)', source)
        self.assertIn('close_bot_session=False', source)

    def test_max_and_vk_use_bottom_reply_keyboards_not_inline_message_buttons(self):
        source = (ROOT / 'backend/app/services/messenger_transports.py').read_text(encoding='utf-8')
        self.assertIn("'inline': False", source)
        self.assertIn("'type': 'reply_keyboard'", source)
        self.assertIn("_action_from_button_text('max', text, user_id)", source)


if __name__ == '__main__':
    unittest.main()
