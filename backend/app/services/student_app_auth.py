"""Validate platform-signed Mini App launch data before resolving a student.

NEVER trust vk_user_id/MAX user.id from client JSON or URL without verifying
that platform's signature. Standalone access is allowed only in local demo mode.
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl, urlencode


def _pairs(raw: str, limit=8192):
    if not raw or len(raw) > limit:
        return None
    try:
        pairs = parse_qsl(raw.lstrip('?'), keep_blank_values=True, strict_parsing=True, max_num_fields=64)
    except (ValueError, UnicodeError):
        return None
    names = [k for k, _ in pairs]
    if len(names) != len(set(names)):
        return None
    return dict(pairs)


def validate_vk_launch(raw: str, *, app_id: str, secret: str, max_age=3600, now=None):
    """VK Mini Apps launch signature (base64url(HMAC-SHA256(vk_* query, secret)))."""
    if not app_id or not secret:
        return None
    values = _pairs(raw)
    if not values or 'sign' not in values or values.get('vk_app_id') != str(app_id):
        return None
    try:
        stamp = int(values['vk_ts'])
        user_id = int(values['vk_user_id'])
    except (ValueError, KeyError, TypeError):
        return None
    age = (time.time() if now is None else now) - stamp
    if user_id <= 0 or age < -30 or age > max_age:
        return None
    check = urlencode(sorted((k, v) for k, v in values.items() if k.startswith('vk_')))
    digest = hmac.new(secret.encode(), check.encode(), hashlib.sha256).digest()
    expected = base64.urlsafe_b64encode(digest).decode().rstrip('=')
    return str(user_id) if hmac.compare_digest(expected, values['sign']) else None


def validate_max_init(raw: str, *, bot_token: str, max_age=3600, now=None):
    """MAX WebAppData signature per dev.max.ru/docs/webapps/validation."""
    if not bot_token:
        return None
    values = _pairs(raw)
    if not values or not values.get('hash'):
        return None
    provided = values.pop('hash')
    if len(provided) != 64:
        return None
    check = '\n'.join(f'{key}={value}' for key, value in sorted(values.items()))
    key = hmac.new(b'WebAppData', bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(key, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(provided, expected):
        return None
    try:
        stamp = int(values['auth_date'])
        user_id = int(json.loads(values['user'])['id'])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None
    age = (time.time() if now is None else now) - stamp
    return str(user_id) if user_id > 0 and -30 <= age <= max_age else None


def virtual_telegram_id(platform: str, external_id: str, secret: str):
    """Stable negative ID for users who registered first via VK or MAX.

    Telegram real IDs are positive; opaque deterministic negative IDs are only a
    DB compatibility placeholder. The signed identity is still required on each
    request. A linked account is always resolved via MessengerIdentity first.
    """
    payload = f'student-app-v1:{platform}:{external_id}'.encode()
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).digest()
    return -(int.from_bytes(digest[:8], 'big') % (2**60 - 1) + 1)
