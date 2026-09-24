import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")
    DATABASE_URI = os.getenv("DATABASE_URI", "sqlite:///university.db")
    SECRET_KEY = os.getenv("SECRET_KEY", "super-secret-key-change-me-in-production")
    DEBUG = os.getenv("DEBUG", "True").lower() in ("true", "1", "yes")

# Состояния для FSM (в продакшене лучше использовать Aiogram FSM Storage)
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