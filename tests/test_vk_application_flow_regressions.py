"""Regression tests for the VK application picker and transport recovery."""
from pathlib import Path
import ast
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class VKApplicationParity(unittest.TestCase):
    def test_vk_and_telegram_use_the_same_available_directions_policy(self):
        applications = (ROOT / 'backend/app/services/applications.py').read_text('utf-8')
        menu = (ROOT / 'backend/app/handlers/menu.py').read_text('utf-8')
        multi = (ROOT / 'backend/app/services/multi_messenger.py').read_text('utf-8')
        self.assertIn('def available_application_directions(student):', applications)
        self.assertIn('if active_application_block(student.id, direction.id):', applications)
        self.assertIn("link.status == DirectionStatus.REJECTED.value", applications)
        self.assertIn('return get_available(student)', menu)
        self.assertIn('dirs = available_application_directions(student)', multi)
        self.assertIn('for d in available_application_directions(user)', multi)

    def test_vk_visible_button_text_fallback_resolves_apply_action(self):
        sys.path.insert(0, str(ROOT / 'backend/app'))
        source = (ROOT / 'backend/app/services/messenger_transports.py').read_text('utf-8')
        tree = ast.parse(source)
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                        and node.name == '_vk_action_from_text')

        fake_multi = types.ModuleType('services.multi_messenger')
        fake_multi.student_for = lambda platform, user_id: None
        fake_apps = types.ModuleType('services.applications')
        fake_apps.available_application_directions = lambda student: []
        context = {'logger': types.SimpleNamespace(debug=lambda *a, **k: None)}
        with patch.dict(sys.modules, {
            'services.multi_messenger': fake_multi,
            'services.applications': fake_apps,
        }):
            exec(compile(ast.Module(body=[function], type_ignores=[]), '<vk-label>', 'exec'), context)
            self.assertEqual(context['_vk_action_from_text']('📝 Подать заявление', 12345), 'menu_apply')
            self.assertEqual(context['_vk_action_from_text']('‹ В главное меню', 12345), 'menu_home')

    def test_vk_handler_uses_payload_then_text_fallback_inside_app_context(self):
        source = (ROOT / 'backend/app/services/messenger_transports.py').read_text('utf-8')
        tree = ast.parse(source)
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                        and node.name == 'handle_vk_event')
        body = ast.get_source_segment(source, function)
        self.assertIn("parsed.get('ui')", body)
        self.assertIn("action = _vk_action_from_text(text, user_id)", body)
        self.assertIn('with app.app_context():\n                action = _vk_action_from_text', body)

    def test_vk_message_new_without_payload_routes_visible_apply_button(self):
        from contextlib import nullcontext
        source = (ROOT / 'backend/app/services/messenger_transports.py').read_text('utf-8')
        tree = ast.parse(source)
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                        and node.name == 'handle_vk_event')
        sent = []
        resolved = []
        context = {
            'json': __import__('json'),
            'record_bot_event': lambda *a, **k: None,
            'command_category': lambda value: 'message',
            'logger': types.SimpleNamespace(exception=lambda *a, **k: None),
            '_vk_action_from_text': lambda text, user_id: resolved.append((text, user_id)) or 'menu_apply',
            '_deliver_private': lambda platform, user_id, text, **kw: (
                'Choose a direction', {'rows': (('direction_1',),), 'app': False}),
            'send_message': lambda *a, **k: sent.append((a, k)) or True,
        }
        exec(compile(ast.Module(body=[function], type_ignores=[]), '<vk-message>', 'exec'), context)
        app = types.SimpleNamespace(app_context=lambda: nullcontext())
        event = {'type': 'message_new', 'object': {'message': {
            'from_id': 12345, 'peer_id': 12345, 'text': '📝 Подать заявление', 'out': 0,
        }}}
        context['handle_vk_event'](event, app)
        self.assertEqual(resolved, [('📝 Подать заявление', 12345)])
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][0][:3], ('vk', 12345, 'Choose a direction'))

    def test_vk_longpoll_has_bounded_backoff_and_clears_failed_session(self):
        source = (ROOT / 'backend/app/services/messenger_transports.py').read_text('utf-8')
        tree = ast.parse(source)
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                        and node.name == 'run_vk_polling')
        body = ast.get_source_segment(source, function)
        self.assertIn('reconnect_delay = 5', body)
        self.assertIn('min(reconnect_delay * 2, 60)', body)
        self.assertIn('_cached_vk_session.cache_clear()', body)
        self.assertIn('requests.exceptions.RequestException', body)

    def test_required_vk_application_questions_do_not_accept_empty_or_dash(self):
        source = (ROOT / 'backend/app/services/multi_messenger.py').read_text('utf-8')
        self.assertIn("if flow['required'][flow['index']] and value in {'', '-'}:", source)
        self.assertIn('На этот вопрос нужно ответить текстом.', source)


if __name__ == '__main__':
    unittest.main()
