"""Offline regressions for responsive account links and VK/MAX native transports."""
from pathlib import Path
import asyncio
import sys
import types
from unittest.mock import patch
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services import messenger_transports as transport


class AccountUIAndSDKTests(unittest.TestCase):
    def test_responsive_account_button_has_own_column(self):
        source = (ROOT / 'frontend/assets/scripts/student/student_app.js').read_text()
        stylesheet = (ROOT / 'frontend/assets/styles/student/account-links-fix.css').read_text()
        self.assertIn('class="account-connect-form"', source)
        self.assertIn('account-connect-button', source)
        self.assertIn('grid-template-columns:minmax(0,1fr)', stylesheet)
        self.assertIn('writing-mode:horizontal-tb', stylesheet)
        self.assertIn('prefers-reduced-motion:reduce', stylesheet)

    def test_vk_api_calls_native_sdk(self):
        sessions = []
        class FakeVK:
            def __init__(self, token, api_version):
                sessions.append((token, api_version))
            def method(self, method, params):
                return {'method': method, 'params': params}
        with patch.dict(sys.modules, {'vk_api': types.SimpleNamespace(VkApi=FakeVK)}), \
             patch.object(transport.settings, 'VK_BOT_TOKEN', 'fake-token'):
            result = transport.vk_request('messages.send', peer_id=123, random_id=999)
        self.assertEqual(sessions[0][0], 'fake-token')
        self.assertEqual(result['params']['peer_id'], 123)
        self.assertEqual(result['method'], 'messages.send')

    def test_max_plain_message_calls_sdk(self):
        calls = []
        class FakeBot:
            def __init__(self, token):
                calls.append(('token',token))
            async def send_message(self, **kw):
                calls.append(('send',kw))
                return {'ok':True}
        with patch.dict(sys.modules, {'maxapi': types.SimpleNamespace(Bot=FakeBot)}), \
             patch.object(transport.settings, 'MAX_BOT_TOKEN', 'fake-token'):
            transport.send_max(456, 'Hello', is_chat=False)
            transport.send_max(777, 'Announcement', is_chat=True)
        self.assertEqual(calls[1], ('send', {'text':'Hello', 'user_id':456}))
        self.assertEqual(calls[3], ('send', {'text':'Announcement','chat_id':777}))

    def test_max_buttons_preserved_as_api_keyboard_payload(self):
        from services.bot_ui import Action
        calls = []
        with patch.object(transport.settings,'MAX_BOT_TOKEN','fake-token'), \
             patch.object(transport, 'max_request', lambda *a,**kw: calls.append((a,kw)) or {'ok':True}):
            transport.send_max(125, 'Select', keyboard_rows=((Action('Профиль','menu_profile'),),))
        self.assertEqual(calls[0][0][0], 'POST')
        self.assertEqual(calls[0][1]['payload']['attachments'][0]['type'], 'reply_keyboard')

    def test_failure_does_not_break_broadcast(self):
        with patch.object(transport, 'send_max', side_effect=RuntimeError('sdk error')):
            self.assertFalse(transport.send_message('max', 4, 'hello'))

if __name__ == '__main__':
    unittest.main()
