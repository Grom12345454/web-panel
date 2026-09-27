import threading
import asyncio
import logging
from web_app import create_app
from database import init_db
from config import settings

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def run_bot_in_thread(app):
    bot_func = None
    
    try:
        from bot import run_bot
        bot_func = run_bot
        logger.info("📂 Найден модуль бота: bot.py (функция run_bot)")
    except ImportError as e:
        logger.warning(f"Не удалось импортировать из bot.py: {e}")
    
    # 2. Если не нашли, пробуем main.py
    if not bot_func:
        try:
            from main import run_bot
            bot_func = run_bot
            logger.info("📂 Найден модуль бота: main.py (функция run_bot)")
        except ImportError as e:
            logger.warning(f"Не удалось импортировать из main.py: {e}")

    # 3. Если всё еще не нашли, выводим ошибку
    if not bot_func:
        logger.error("❌ Не удалось найти функцию run_bot ни в bot.py, ни в main.py")
        return

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    with app.app_context():
        logger.info("🤖 Запуск Telegram бота в фоновом потоке...")
        try:
            loop.run_until_complete(bot_func(app))
        except Exception as e:
            logger.error(f"Ошибка при работе бота: {e}", exc_info=True)
        finally:
            loop.close()

if __name__ == "__main__":
    app = create_app()
    
    with app.app_context():
        init_db(app)
        logger.info("✅ База данных инициализирована")

    print("\n" + "="*50)
    print(" ЗАПУСК СИСТЕМЫ УПРАВЛЕНИЯ ВУЗОМ")
    print("="*50)
    print(f"📍 Веб-панель: http://{settings.WEB_HOST}:{settings.WEB_PORT}/auth/login")
    if settings.BOT_TOKEN:
        print("🤖 Telegram-бот: токен найден, запуск выполняется в фоне")
    else:
        print("⚠️ Telegram-бот: BOT_TOKEN не задан — веб-панель запустится без бота")
    print("="*50 + "\n")
    
    bot_thread = threading.Thread(
        target=run_bot_in_thread, 
        args=(app,), 
        daemon=True,
        name="TelegramBotThread"
    )
    bot_thread.start()
    
    import time
    time.sleep(2)
    
    app.run(
        debug=settings.DEBUG,
        host=settings.WEB_HOST,
        port=settings.WEB_PORT,
        use_reloader=False
    )