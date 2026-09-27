import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import MenuButtonDefault

from config import settings
from database import db, Student, TelegramChatCandidate

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("bot.log", encoding="utf-8"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

app_instance = None
bot_instance = None


async def configure_bot(bot: Bot):
    # User-facing navigation is intentionally card-based; no command menu is exposed.
    await bot.delete_my_commands()
    await bot.set_chat_menu_button(menu_button=MenuButtonDefault())
    await bot.set_my_description(
        "University Control — заявки, общий статус, профиль и мероприятия в одном профессиональном Telegram-интерфейсе."
    )


async def remember_telegram_chat(chat):
    """Remember chats where the bot appears so the web panel can connect them by one click."""
    if not app_instance or not chat:
        return
    try:
        with app_instance.app_context():
            chat_id = str(chat.id)
            item = TelegramChatCandidate.query.filter_by(chat_id=chat_id).first()
            title = getattr(chat, "title", None) or getattr(chat, "full_name", None) or getattr(chat, "first_name", None) or chat_id
            username = getattr(chat, "username", None)
            chat_type = getattr(chat, "type", None)
            if item is None:
                item = TelegramChatCandidate(chat_id=chat_id, title=title, username=username, chat_type=chat_type)
                db.session.add(item)
            else:
                item.title = title
                item.username = username
                item.chat_type = chat_type
                item.last_seen_at = __import__("datetime").datetime.utcnow()
            db.session.commit()
            logger.info("Telegram chat discovered: %s (%s, %s)", chat_id, title, chat_type)
    except Exception:
        logger.exception("Не удалось сохранить обнаруженный Telegram-чат")



async def run_bot(app):
    global app_instance, bot_instance
    app_instance = app

    with app.app_context():
        count = db.session.query(db.func.count(Student.id)).scalar()
        logger.info("БД подключена. Студентов: %s", count)

    token = settings.BOT_TOKEN
    if not token:
        logger.error("❌ BOT_TOKEN не задан. Веб-панель продолжит работать, но Telegram-бот не будет запущен.")
        logger.error("Добавьте реальный токен от @BotFather в файл .env: BOT_TOKEN=123456789:AA...")
        return

    try:
        bot_instance = Bot(token=token)
    except Exception as exc:
        logger.error("❌ Некорректный BOT_TOKEN: %s", exc)
        logger.error("Проверьте строку BOT_TOKEN в .env. Нужен полный токен, выданный @BotFather, без BOT_TOKEN= внутри значения.")
        return
    dp = Dispatcher()

    try:
        from handlers.registration import router as reg_router
        from handlers.menu import router as menu_router
        from handlers.telegram_discovery import router as discovery_router
        dp.include_router(reg_router)
        dp.include_router(menu_router)
        dp.include_router(discovery_router)
    except ImportError:
        logger.exception("Ошибка загрузки роутеров handlers")
        await bot_instance.session.close()
        return

    await configure_bot(bot_instance)
    logger.info("🤖 Telegram Bot запущен: card-based UI")
    try:
        await dp.start_polling(bot_instance)
    except Exception as exc:
        logger.exception("❌ Telegram polling завершился с ошибкой: %s", exc)
        logger.error("Если ошибка связана с токеном, получите новый токен у @BotFather и обновите .env.")
    finally:
        await bot_instance.session.close()
