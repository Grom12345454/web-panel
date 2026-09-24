import asyncio
import logging
from aiogram import Bot, Dispatcher
from config import settings
from database import db, Student

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app_instance = None
bot_instance = None

async def run_bot(app):
    """Точка входа для запуска бота"""
    global app_instance, bot_instance
    
    # Сохраняем ссылку на приложение для доступа к БД из хендлеров
    app_instance = app
    
    with app.app_context():
        count = db.session.query(db.func.count(Student.id)).scalar()
        logger.info(f"️ БД подключена. Студентов: {count}")
    
    # Создание бота и диспетчера
    bot_instance = Bot(token=settings.BOT_TOKEN)
    dp = Dispatcher()
    
    # Регистрируем роутеры из модульной структуры
    try:
        from handlers.registration import router as reg_router
        from handlers.menu import router as menu_router
        
        dp.include_router(reg_router)
        dp.include_router(menu_router)
        logger.info("✅ Роутеры handlers загружены")
    except ImportError as e:
        logger.error(f"❌ Ошибка загрузки роутеров: {e}")
        return
    
    logger.info("🤖 Telegram Bot запущен...")
    await dp.start_polling(bot_instance)

if __name__ == "__main__":
    try:
        from web_app import create_app, set_flask_app
        app = create_app()
        set_flask_app(app)
        
        with app.app_context():
            from database import init_db
            init_db(app)
            
        asyncio.run(run_bot(app))
    except KeyboardInterrupt:
        logger.info("🛑 Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"💥 Критическая ошибка: {e}", exc_info=True)