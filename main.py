import asyncio
import logging

from config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


if __name__ == "__main__":
    try:
        from web_app import create_app, set_flask_app
        from database import init_db
        from bot import run_bot

        app = create_app()
        set_flask_app(app)
        init_db(app)
        asyncio.run(run_bot(app))
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
    except Exception:
        logger.exception("Критическая ошибка запуска")
