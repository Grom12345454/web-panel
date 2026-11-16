"""Regression tests for unified messenger environment variable names."""
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class UnifiedMessengerEnvTests(unittest.TestCase):
    def test_env_template_has_shared_keys_and_no_removed_keys(self):
        sample = (ROOT / '.env.example').read_text('utf-8')
        for name in ('BOT_TOKEN=', 'BOT_USERNAME=', 'WEBAPP_URL=', 'VK_BOT_TOKEN=',
                     'VK_GROUP_ID=', 'MAX_BOT_TOKEN=', 'MAX_BOT_USERNAME=', 'WEBHOOK_SECRET='):
            self.assertIn(name, sample)
        for name in ('VK_GROUP_TOKEN=', 'VK_WEBAPP_URL=', 'MAX_WEBAPP_URL=',
                     'MAX_WEBHOOK_URL=', 'MAX_WEBHOOK_SECRET=',
                     'TELEGRAM_BOT_USERNAME='):
            self.assertNotIn(name, sample)

    def test_max_webhook_url_is_derived_from_webapp_origin(self):
        env = os.environ.copy()
        env['WEBAPP_URL'] = 'https://campus.example/student-app'
        env['LOCAL_DEMO'] = '0'
        snippet = (
            'import config; '
            'assert config.settings.MAX_WEBHOOK_ENDPOINT == '
            "'https://campus.example/hooks/max', config.settings.MAX_WEBHOOK_ENDPOINT; "
            'assert config.settings.WEBAPP_URL == '
            "'https://campus.example/student-app'"
        )
        subprocess.run([sys.executable, '-c', snippet], cwd=ROOT, env=env,
                       check=True, capture_output=True, text=True)

    def test_local_app_url_does_not_create_public_webhook(self):
        env = os.environ.copy()
        env['WEBAPP_URL'] = 'https://127.0.0.1/student-app'
        env['LOCAL_DEMO'] = '0'
        snippet = 'import config; assert config.settings.MAX_WEBHOOK_ENDPOINT == ""'
        subprocess.run([sys.executable, '-c', snippet], cwd=ROOT, env=env,
                       check=True, capture_output=True, text=True)


if __name__ == '__main__':
    unittest.main()
