"""Regression tests: employee Telegram username is not an account identifier."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_private_start_never_binds_employee_accounts_by_username():
    source = (ROOT / 'backend/app/bot.py').read_text(encoding='utf-8')
    assert 'Student.query.filter_by(tg_id=user_id).first()' in source
    assert 'student.telegram_username = username' in source
    assert 'User.telegram_username' not in source
    assert 'UserRole' not in source
    assert 'candidate.tg_id = user_id' not in source


def test_existing_numeric_telegram_binding_is_still_supported_for_otp():
    source = (ROOT / 'backend/app/web_app.py').read_text(encoding='utf-8')
    assert "if not user.tg_id or int(user.tg_id) <= 0 or not settings.BOT_TOKEN:" in source
    assert "'chat_id': int(user.tg_id)" in source
    assert 'user.tg_id and' in source
