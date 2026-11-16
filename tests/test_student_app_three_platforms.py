"""Signed Student App integration checks without live messenger API tokens."""
import base64
import hashlib
import hmac
import json
import time
import unittest
from pathlib import Path
from urllib.parse import urlencode

from services.student_app_auth import validate_vk_launch, validate_max_init, virtual_telegram_id
from services.messenger_transports import vk_app_url, max_app_url, _public_url

ROOT = Path(__file__).resolve().parents[1]


class StudentAppPlatformTests(unittest.TestCase):
    def test_vk_signature_and_expiry(self):
        payload = {'vk_app_id': '123456', 'vk_user_id': '87654', 'vk_ts': '2000000000', 'vk_platform': 'mobile_web'}
        secret = 'VK_APP_SIGNING_SECRET_FOR_TEST'
        signed = urlencode(sorted(payload.items()))
        sig = base64.urlsafe_b64encode(hmac.new(secret.encode(), signed.encode(), hashlib.sha256).digest()).decode().rstrip('=')
        signed += '&sign=' + sig
        self.assertEqual(validate_vk_launch(signed, app_id='123456', secret=secret, now=2000000010), '87654')
        self.assertIsNone(validate_vk_launch(signed.replace('87654', '87655'), app_id='123456', secret=secret, now=2000000010))
        self.assertIsNone(validate_vk_launch(signed, app_id='123457', secret=secret, now=2000000010))
        self.assertIsNone(validate_vk_launch(signed, app_id='123456', secret=secret, now=2000010000))
        self.assertIsNone(validate_vk_launch(signed+'&vk_user_id=1', app_id='123456', secret=secret, now=2000000010))

    def test_max_signature_and_replay_window(self):
        token = 'MAX-BOT-TEST-TOKEN'
        fields = {'user': json.dumps({'id': 333444, 'first_name': 'Test'}, ensure_ascii=False, separators=(',', ':')),
                  'auth_date': '2000000000', 'query_id': 'test-qs'}
        key = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
        canonical = '\n'.join(f'{k}={v}' for k, v in sorted(fields.items()))
        fields['hash'] = hmac.new(key, canonical.encode(), hashlib.sha256).hexdigest()
        signed = urlencode(fields)
        self.assertEqual(validate_max_init(signed, bot_token=token, now=2000000010), '333444')
        self.assertIsNone(validate_max_init(signed.replace('333444', '333445'), bot_token=token, now=2000000010))
        self.assertIsNone(validate_max_init(signed, bot_token=token, now=2000010000))
        self.assertIsNone(validate_max_init(signed+'&hash=bad', bot_token=token, now=2000000010))

    def test_virtual_ids_are_platform_separated(self):
        k = 'test-virtual-id-secret'
        vk = virtual_telegram_id('vk', '123', k)
        self.assertLess(vk, 0)
        self.assertNotEqual(vk, virtual_telegram_id('max', '123', k))
        self.assertEqual(vk, virtual_telegram_id('vk', '123', k))

    def test_public_https_url_validation(self):
        self.assertIsNone(_public_url('http://example.com/student-app'))
        self.assertIsNone(_public_url('https://127.0.0.1/student-app'))
        self.assertIsNone(_public_url('https://localhost/student-app'))
        self.assertEqual(_public_url('https://example.com/student-app'), 'https://example.com/student-app')

    def test_single_canonical_student_app_template_and_js_bridges(self):
        templates = list((ROOT / 'frontend/templates').rglob('*.html'))
        self.assertFalse(list((ROOT / 'frontend/templates').glob('*.html')))
        self.assertEqual(len([t for t in templates if t.name=='student_app.html']), 1)
        html = (ROOT/'frontend/templates/student/student_app.html').read_text('utf8')
        self.assertIn('telegram-web-app.js', html)
        self.assertIn('max-web-app.js', html)
        self.assertIn('student-app.bundle.js', html)
        js = (ROOT/'static/js/student-app.bundle.js').read_text('utf8')
        for platform in ('X-Telegram-Init-Data','X-Max-Init-Data','X-VK-Launch-Params'):
            self.assertIn(platform, js)
        backend = (ROOT / 'backend/app/web_app.py').read_text('utf8')
        for auth in ('validate_telegram_init_data', 'validate_vk_launch', 'validate_max_init'):
            self.assertIn(auth, backend)
        self.assertIn('MessengerIdentity.query.filter_by', backend)

    def test_bots_send_student_app_buttons(self):
        src = (ROOT/'backend/app/services/messenger_transports.py').read_text('utf8')
        self.assertNotIn("'type': 'open_link'", src)
        self.assertIn("'inline': False", src)
        self.assertIn("'type': 'reply_keyboard'", src)
        self.assertIn('with_app=with_app', src)
        self.assertIn('https://vk.com/app', src)
        self.assertIn('https://max.ru/', src)
        doc = (ROOT/'.env.example').read_text('utf8')
        for setting in ('WEBAPP_URL', 'VK_MINI_APP_ID', 'VK_MINI_APP_SECRET', 'BOT_USERNAME', 'MAX_BOT_USERNAME'):
            self.assertIn(setting+'=', doc)
        for removed in ('VK_WEBAPP_URL=', 'MAX_WEBAPP_URL=', 'MAX_WEBHOOK_URL=', 'MAX_WEBHOOK_SECRET=', 'TELEGRAM_BOT_USERNAME='):
            self.assertNotIn(removed, doc)


if __name__=='__main__':
    unittest.main()
