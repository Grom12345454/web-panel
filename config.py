import os
import secrets
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class Settings:
    BASE_DIR = Path(__file__).resolve().parent
    DATA_DIR = Path(os.getenv("DATABASE_DIR", str(BASE_DIR / "data"))).resolve()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip().strip('"').strip("'")
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

    SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_urlsafe(32)
    DEBUG = os.getenv("DEBUG", "False").lower() in ("true", "1", "yes")
    WEB_HOST = os.getenv("WEB_HOST", "127.0.0.1")
    WEB_PORT = int(os.getenv("WEB_PORT", "5000"))


class RegState:
    NAME = "reg_name"
    GROUP = "reg_group"
    PHONE = "reg_phone"
    DIR_SELECT = "reg_dir_select"


class AddState:
    NAME = "add_name"
    GROUP = "add_group"
    PHONE = "add_phone"


settings = Settings()
