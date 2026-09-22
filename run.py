import threading
import asyncio
from database import init_db
from web_app import create_app
from bot import run_bot

def main():
    app = create_app()
    init_db(app)
    bot_thread = threading.Thread(target=lambda: asyncio.run(run_bot()), daemon=True)
    bot_thread.start()
    print("🌐 Сайт запущен: http://localhost:5000")
    app.run(debug=True, port=5000, use_reloader=False)

if __name__ == "__main__":
    main()