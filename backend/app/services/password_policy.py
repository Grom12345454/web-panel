"""Strong, human-manageable passwords for the web panel."""
import re

_COMMON = {
    'password123!', 'qwerty12345!', 'admin123456!', 'welcome12345!',
    'changeme123!', 'studentcouncil1!', 'парольпароль1!', 'qwerty123456',
}


def validate_new_password(password, login='', old_hash=None, verify=None):
    """Return an error string or None. bcrypt's 72-byte limit is enforced."""
    if not isinstance(password, str):
        return 'Введите новый пароль.'
    if len(password) < 12:
        return 'Нужно не менее 12 символов.'
    if len(password) > 128 or len(password.encode('utf-8')) > 72:
        return 'Пароль слишком длинный для безопасного хеширования (лимит 72 байта).'
    if any(ch.isspace() for ch in password):
        return 'Не используйте пробелы и управляющие символы в пароле.'
    if not re.search(r'[A-Z]', password):
        return 'Добавьте хотя бы одну заглавную латинскую букву.'
    if not re.search(r'[a-z]', password):
        return 'Добавьте хотя бы одну строчную латинскую букву.'
    if not re.search(r'\d', password):
        return 'Добавьте хотя бы одну цифру.'
    if not re.search(r'[^A-Za-z0-9]', password):
        return 'Добавьте специальный символ, например !, # или _.'
    lowered = password.casefold()
    normalized_login = (login or '').strip().casefold()
    if normalized_login and len(normalized_login) >= 3 and normalized_login in lowered:
        return 'Пароль не должен содержать ваш логин.'
    if lowered in _COMMON:
        return 'Этот пароль слишком распространён. Выберите уникальный вариант.'
    if old_hash and verify:
        try:
            if verify(password, old_hash):
                return 'Новый пароль должен отличаться от текущего.'
        except Exception:
            pass
    return None
