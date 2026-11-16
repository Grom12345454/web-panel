import os
import secrets
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

class Settings:
    BASE_DIR = Path(__file__).resolve().parents[2]
    DATA_DIR = Path(os.getenv("DATABASE_DIR", str(BASE_DIR / "data"))).resolve()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip().strip('"').strip("'")
    BOT_USERNAME = os.getenv("BOT_USERNAME", "").strip().lstrip("@")  # Telegram public username
    TELEGRAM_PROXY = os.getenv("TELEGRAM_PROXY", "").strip()  # Optional trusted HTTP/SOCKS proxy for Telegram Bot API
    MAX_BOT_USERNAME = os.getenv("MAX_BOT_USERNAME", "").strip().lstrip("@")  # MAX public username
    VK_BOT_TOKEN = os.getenv("VK_BOT_TOKEN", "").strip()
    VK_GROUP_ID = os.getenv("VK_GROUP_ID", "").strip()
    VK_API_VERSION = os.getenv("VK_API_VERSION", "5.199").strip()
    MAX_BOT_TOKEN = os.getenv("MAX_BOT_TOKEN", "").strip()
    MAX_MODE = os.getenv("MAX_MODE", "webhook").strip().lower()
    WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
    # Remove operational event metadata after 90 days by default (0 disables cleanup).
    try:
        BOT_JOURNAL_RETENTION_DAYS = max(0, min(int(os.getenv("BOT_JOURNAL_RETENTION_DAYS", "90")), 3650))
    except ValueError:
        BOT_JOURNAL_RETENTION_DAYS = 90
    VK_MINI_APP_ID = os.getenv("VK_MINI_APP_ID", "").strip()
    VK_MINI_APP_SECRET = os.getenv("VK_MINI_APP_SECRET", "").strip()

    # Legacy single DB kept only as a migration source for existing installations.
    LEGACY_DATABASE_URI = os.getenv("DATABASE_URI", "sqlite:///university.db")
    _legacy_env_path = os.getenv("LEGACY_DATABASE_PATH")
    if _legacy_env_path:
        LEGACY_DATABASE_PATH = Path(_legacy_env_path)
        if not LEGACY_DATABASE_PATH.is_absolute():
            LEGACY_DATABASE_PATH = BASE_DIR / LEGACY_DATABASE_PATH
    elif LEGACY_DATABASE_URI.startswith("sqlite:///"):
        _legacy_uri_path = LEGACY_DATABASE_URI.replace("sqlite:///", "", 1)
        LEGACY_DATABASE_PATH = Path(_legacy_uri_path)
        if not LEGACY_DATABASE_PATH.is_absolute():
            LEGACY_DATABASE_PATH = BASE_DIR / LEGACY_DATABASE_PATH
    else:
        LEGACY_DATABASE_PATH = BASE_DIR / "university.db"
    LEGACY_DATABASE_PATH = LEGACY_DATABASE_PATH.resolve()

    PEOPLE_DATABASE_PATH = DATA_DIR / "people.sqlite3"
    EVENTS_DATABASE_PATH = DATA_DIR / "events.sqlite3"
    LESSONS_DATABASE_PATH = DATA_DIR / "lessons.sqlite3"
    STATS_DATABASE_PATH = DATA_DIR / "stats.sqlite3"
    SYSTEM_DATABASE_PATH = DATA_DIR / "system.sqlite3"

    PEOPLE_DATABASE_URI = f"sqlite:///{PEOPLE_DATABASE_PATH.as_posix()}"
    EVENTS_DATABASE_URI = f"sqlite:///{EVENTS_DATABASE_PATH.as_posix()}"
    LESSONS_DATABASE_URI = f"sqlite:///{LESSONS_DATABASE_PATH.as_posix()}"
    STATS_DATABASE_URI = f"sqlite:///{STATS_DATABASE_PATH.as_posix()}"
    SYSTEM_DATABASE_URI = f"sqlite:///{SYSTEM_DATABASE_PATH.as_posix()}"

    # Continuous SQLite integrity monitoring and recoverable snapshots.
    # The database guardian is started as a supervised background worker by run.py.
    try:
        DATABASE_GUARDIAN_INTERVAL_SECONDS = max(30, min(int(os.getenv("DATABASE_GUARDIAN_INTERVAL_SECONDS", "60")), 3600))
    except ValueError:
        DATABASE_GUARDIAN_INTERVAL_SECONDS = 60
    try:
        DATABASE_BACKUP_INTERVAL_HOURS = max(1, min(int(os.getenv("DATABASE_BACKUP_INTERVAL_HOURS", "6")), 168))
    except ValueError:
        DATABASE_BACKUP_INTERVAL_HOURS = 6
    try:
        DATABASE_AUTO_BACKUP_RETENTION = max(3, min(int(os.getenv("DATABASE_AUTO_BACKUP_RETENTION", "48")), 500))
    except ValueError:
        DATABASE_AUTO_BACKUP_RETENTION = 48
    try:
        DATABASE_MANUAL_BACKUP_RETENTION = max(1, min(int(os.getenv("DATABASE_MANUAL_BACKUP_RETENTION", "20")), 200))
    except ValueError:
        DATABASE_MANUAL_BACKUP_RETENTION = 20

    _secret_key_value = os.getenv("SECRET_KEY", "").strip()
    SECRET_KEY_CONFIGURED = bool(
        len(_secret_key_value) >= 32 and
        not _secret_key_value.lower().startswith(('replace-', 'paste_', 'change_', 'example')) and
        _secret_key_value.lower() not in {'a' * 32, '0' * 32}
    )
    SECRET_KEY = _secret_key_value or secrets.token_urlsafe(32)
    DEBUG = os.getenv("DEBUG", "False").lower() in ("true", "1", "yes")
    WEB_PORT = int(os.getenv("WEB_PORT", "5000"))
    # Optional Flask 3.1 Host-header allowlist; comma-separated hostnames, no schemes/paths.
    APP_TRUSTED_HOSTS = [host.strip().lower() for host in os.getenv("APP_TRUSTED_HOSTS", "").split(",") if host.strip()]
    # Optional independent allow-list for the internal login and staff/admin panel.
    # LOCAL_DEMO is only for a synthetic browser preview. A configured public app URL
    # signals deployment intent; set LOCAL_DEMO=1 only for local testing without it.
    # One public Student App URL is shared across Telegram, VK and MAX.
    # MAX's webhook endpoint is derived from the same origin at /hooks/max,
    # because a webhook URL is a route, not the same URL as the web app itself.
    WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip()
    from urllib.parse import urlsplit
    from ipaddress import ip_address
    _webapp_parts = urlsplit(WEBAPP_URL)
    _webapp_host = (_webapp_parts.hostname or "").lower()
    _public_webapp_host = bool(_webapp_host) and _webapp_host not in {
        "localhost", "127.0.0.1", "0.0.0.0", "::1"
    }
    try:
        _public_webapp_host = bool(_webapp_host) and ip_address(_webapp_host).is_global
    except ValueError:
        pass  # DNS names are allowed; the deployment proxy must point them publicly.
    MAX_WEBHOOK_ENDPOINT = (
        f"{_webapp_parts.scheme}://{_webapp_parts.netloc}/hooks/max"
        if _webapp_parts.scheme == "https" and _webapp_parts.netloc
        and not _webapp_parts.username and not _webapp_parts.password
        and _public_webapp_host else ""
    )
    _local_demo_requested = os.getenv("LOCAL_DEMO", "1").lower() in ("1", "true", "yes", "on")
    _live_mini_app_configured = bool(WEBAPP_URL)
    LOCAL_DEMO = _local_demo_requested and not _live_mini_app_configured
    # Keep the WSGI server on loopback by default; expose only through a configured
    # reverse proxy/VPN. Demo mode is also loopback-only.
    WEB_HOST = "127.0.0.1" if LOCAL_DEMO else os.getenv("WEB_HOST", "127.0.0.1")
    # The local development server always runs over HTTP. Legacy USE_HTTPS and
    # HTTPS_PORT variables in older .env files are intentionally ignored.

    # Internal deployment defaults to HTTP on the private LAN. If HTTPS terminates at a
    # trusted internal reverse proxy, set INTERNAL_HTTPS=1 to mark session cookies Secure.
    SESSION_COOKIE_SECURE = os.getenv("INTERNAL_HTTPS", "0").lower() in ("1", "true", "yes", "on")

    # Initial main-administrator account. Staff accounts are provisioned in the panel.
    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", os.getenv("ADMIN_EMAIL", "admin")).strip()
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
    ADMIN_TG_ID = os.getenv("ADMIN_TG_ID", "").strip()
    COMPETITION_TITLE = os.getenv("COMPETITION_TITLE", "🏆 Наша команда участвует в соревнованиях")
    COMPETITION_BODY = os.getenv("COMPETITION_BODY", "Ищем желающих присоединиться к составу или группе поддержки. Количество мест ограничено — регистрация идёт по квоте.")

class RegState:
    EDUCATION_TYPE = "reg_education_type"
    NAME = "reg_name"
    GROUP = "reg_group"
    PHONE = "reg_phone"
    DIR_SELECT = "reg_dir_select"


settings = Settings()
