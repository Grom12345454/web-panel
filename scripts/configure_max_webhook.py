"""Register MAX production webhook after public HTTPS reverse proxy is configured."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import os
import requests
from config import settings

url = settings.MAX_WEBHOOK_ENDPOINT
if not url:
    sys.exit('Set WEBAPP_URL=https://your-domain.example/student-app; the MAX webhook URL is derived from its origin.')
if not settings.MAX_BOT_TOKEN or not settings.WEBHOOK_SECRET or len(settings.WEBHOOK_SECRET) < 24:
    sys.exit('Set MAX_BOT_TOKEN and a random WEBHOOK_SECRET (at least 24 characters).')
response = requests.post(
    'https://platform-api2.max.ru/subscriptions',
    headers={'Authorization': settings.MAX_BOT_TOKEN},
    json={'url': url, 'secret': settings.WEBHOOK_SECRET,
          'update_types': ['message_created', 'bot_started']}, timeout=20,
)
response.raise_for_status()
result = response.json()
if result.get('success') is False:
    sys.exit('MAX refused webhook registration. Check tokens, URL and TLS certificate.')
print('MAX webhook registered:', url)
