from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    BOT_TOKEN: str
    SECRET_KEY: str = "secret"
    DATABASE_URI: str = "sqlite:///university.db"

    class Config:
        env_file = ".env"

settings = Settings()