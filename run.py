import threading
import asyncio
from web_app import create_app
from database import init_db
from bot import run_bot as start_bot

if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        init_db(app)

    print("🚀 Запуск веб-панели и бота...")
    print("📍 Сайт: http://127.0.0.1:5000/login")
    
    def run_bot_thread():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(start_bot(app))
        finally:
            loop.close()

    bot_thread = threading.Thread(target=run_bot_thread, daemon=True)
    bot_thread.start()
    
    app.run(debug=True, host="127.0.0.1", port=5000, use_reloader=False)