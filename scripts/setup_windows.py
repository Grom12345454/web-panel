"""First-run configuration for the local Windows demonstration build."""
from __future__ import annotations

import getpass
import re
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"


def password_error(password: str, login: str) -> str | None:
    if len(password) < 12:
        return "Нужно не менее 12 символов."
    if len(password) > 128 or len(password.encode("utf-8")) > 72:
        return "Максимум 72 байта (ограничение bcrypt)."
    if any(ch.isspace() for ch in password):
        return "Пробелы в пароле не допускаются."
    if not re.search(r"[A-Z]", password):
        return "Добавьте заглавную латинскую букву."
    if not re.search(r"[a-z]", password):
        return "Добавьте строчную латинскую букву."
    if not re.search(r"\d", password):
        return "Добавьте цифру."
    if not re.search(r"[!@%&*()_+=\[\]{}:,.?-]", password):
        return "Добавьте специальный символ из набора !@%&*()-_+=[]{}:,.?"
    if any(ch in password for ch in ("$", "#", '"', "\\")):
        return "Не используйте в пароле символы $, #, кавычки и обратную косую черту."
    if login.casefold() in password.casefold():
        return "Пароль не должен содержать логин."
    return None


def main() -> int:
    if ENV_FILE.exists():
        print("Файл .env уже существует — настройки не изменены.")
        return 0

    print("Первичная настройка локальной демо-версии Studsovet")
    print("База данных: SQLite (локальные файлы в папке data).")
    print("Веб-сервер будет доступен только на этом компьютере (127.0.0.1).")
    login = input("Логин главного администратора [admin]: ").strip() or "admin"
    if len(login) < 3 or len(login) > 64 or any(ch.isspace() for ch in login):
        print("Логин должен содержать 3–64 символа без пробелов.")
        return 2

    while True:
        password = getpass.getpass("Придумайте пароль администратора: ")
        error = password_error(password, login)
        if error:
            print(f"Слабый пароль: {error}")
            continue
        confirm = getpass.getpass("Повторите пароль: ")
        if password != confirm:
            print("Пароли не совпадают.")
            continue
        break

    secret = secrets.token_urlsafe(48)
    # Keep values on one line and avoid dotenv interpolation surprises.
    content = "\n".join([
        "# Локальная демонстрационная конфигурация. Не используйте на публичном сервере.",
        "LOCAL_DEMO=1",
        "DEBUG=0",
        "WEB_HOST=127.0.0.1",
        "WEB_PORT=5000",
        "DATABASE_DIR=./data",
        f"SECRET_KEY={secret}",
        f"ADMIN_USERNAME={login}",
        f"ADMIN_PASSWORD={password}",
        "BOT_TOKEN=",
        "BOT_USERNAME=",
        "VK_BOT_TOKEN=",
        "VK_GROUP_ID=",
        "MAX_BOT_TOKEN=",
        "MAX_MODE=poll",
        "WEBAPP_URL=",
        "INTERNAL_HTTPS=0",
        "",
    ])
    ENV_FILE.write_text(content, encoding="utf-8")
    print("Создан .env. Сохраните пароль в надёжном месте; повторно он не показывается.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
