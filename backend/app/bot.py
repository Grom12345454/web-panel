import asyncio
import logging

from aiogram import Bot, Dispatcher, BaseMiddleware
from aiogram.types import MenuButtonDefault, MenuButtonWebApp, WebAppInfo, Update
from aiogram.exceptions import (TelegramUnauthorizedError, TelegramNetworkError,
                                TelegramServerError, TelegramRetryAfter)

from config import settings
from bot_messages import BOT_DESCRIPTION, BOT_SHORT_DESCRIPTION
from database import db, Student, TelegramChatCandidate

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

app_instance = None
bot_instance = None
# Router objects have a single owner in aiogram. Keep the same Dispatcher across
# polling retries instead of attaching module-level routers a second time.
_dispatcher = None
_bot_configured = False
_username_cache = {}

class TelegramJournalMiddleware(BaseMiddleware):
    """Log metadata for Telegram updates after handler completion, never message text."""
    async def __call__(self, handler, event, data):
        import time
        from services.bot_journal import command_category, record_bot_event
        update = event
        nested = None
        if isinstance(update, Update):
            for key in ('message', 'callback_query', 'edited_message', 'my_chat_member'):
                nested = getattr(update, key, None)
                if nested is not None:
                    break
        else:
            nested = update
        sender = getattr(nested, 'from_user', None)
        actor_id = getattr(sender, 'id', None)
        if isinstance(update, Update) and getattr(update, 'callback_query', None) is not None:
            action, kind, summary = 'button', 'incoming', 'Нажатие кнопки'
        elif nested is not None and getattr(nested, 'text', None) is not None:
            action = command_category(nested.text)
            chat = getattr(nested, 'chat', None)
            if getattr(chat, 'type', '') in {'group', 'supergroup', 'channel'}:
                if action not in {'/chatid', '/chat_id'}:
                    return await handler(event, data)
                kind, summary = 'chat', 'Команда обнаружения чата'
            else:
                kind, summary = 'incoming', 'Команда или сообщение (без текста)'
        elif isinstance(update, Update) and getattr(update, 'my_chat_member', None) is not None:
            action, kind, summary = 'chat_detected', 'chat', 'Изменилось членство бота в чате'
        else:
            return await handler(event, data)
        start = time.perf_counter()
        try:
            result = await handler(event, data)
        except Exception:
            if app_instance is not None:
                with app_instance.app_context():
                    record_bot_event('telegram', kind, action, 'error', actor_id=actor_id,
                                     summary=summary, duration_ms=(time.perf_counter() - start)*1000)
            raise
        if app_instance is not None:
            with app_instance.app_context():
                record_bot_event('telegram', kind, action, 'success', actor_id=actor_id,
                                 summary=summary, duration_ms=(time.perf_counter() - start)*1000)
        return result


class PersistTelegramUsernameMiddleware(BaseMiddleware):
    """Keep a student's public Telegram username in the student profile only."""
    async def __call__(self, handler, event, data):
        telegram_user = getattr(event, "from_user", None)
        if telegram_user is None and isinstance(event, Update):
            for attr in ("message", "edited_message", "callback_query", "inline_query", "chat_join_request"):
                nested = getattr(event, attr, None)
                telegram_user = getattr(nested, "from_user", None) if nested else None
                if telegram_user is not None:
                    break
        username = (getattr(telegram_user, "username", None) or "").strip().lstrip("@")[:255] or None
        if app_instance is not None and telegram_user is not None:
            # Most updates do not change a username. Avoid a database read/write
            # on every callback/message during registration bursts.
            user_id = telegram_user.id
            if user_id not in _username_cache or _username_cache[user_id] != username:
                try:
                    with app_instance.app_context():
                        student = Student.query.filter_by(tg_id=user_id).first()
                        if student and student.telegram_username != username:
                            student.telegram_username = username
                        db.session.commit()
                        _username_cache[user_id] = username
                except Exception:
                    db.session.rollback()
                    logger.warning("Could not refresh Telegram username for a student profile", exc_info=True)
                finally:
                    db.session.remove()
        return await handler(event, data)

async def configure_bot(bot: Bot):
    # User-facing navigation is intentionally card-based; no command menu is exposed.
    await bot.delete_my_commands()
    # Telegram rejects localhost/private/self-signed URLs for Web Apps.
    # Keep the bot fully operational locally; a Web App menu button is enabled
    # only when WEBAPP_URL is a real public HTTPS URL.
    webapp_url = settings.WEBAPP_URL
    local_hosts = ("localhost", "127.0.0.1", "0.0.0.0", "::1")
    is_local = any(h in webapp_url.lower() for h in local_hosts)
    if webapp_url.startswith("https://") and not is_local:
        try:
            await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="Кабинет", web_app=WebAppInfo(url=webapp_url)))
        except Exception:
            logger.exception("Не удалось установить кнопку Web App; бот продолжит работу без неё")
            await bot.set_chat_menu_button(menu_button=MenuButtonDefault())
    else:
        await bot.set_chat_menu_button(menu_button=MenuButtonDefault())
    # The display name is managed via @BotFather. Avoid calling setMyName on
    # every restart because Telegram rate-limits this method for many hours.
    await bot.set_my_description(BOT_DESCRIPTION)
    try:
        await bot.set_my_short_description(BOT_SHORT_DESCRIPTION)
    except Exception:
        logger.debug("Не удалось обновить краткое описание бота", exc_info=True)

async def remember_telegram_chat(chat):
    """Remember chats where the bot appears so the web panel can connect them by one click."""
    if not app_instance or not chat:
        return
    chat_type = getattr(chat, "type", None)
    if chat_type not in {"group", "supergroup", "channel"}:
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
            logger.info("Telegram group/channel discovered or refreshed (type=%s)", chat_type)
    except Exception:
        logger.exception("Не удалось сохранить обнаруженный Telegram-чат")

def get_dispatcher():
    """Build one dispatcher for the process lifetime: router attachment is one-shot."""
    global _dispatcher
    if _dispatcher is not None:
        return _dispatcher
    dp = Dispatcher()
    dp.update.outer_middleware(PersistTelegramUsernameMiddleware())
    dp.update.outer_middleware(TelegramJournalMiddleware())
    from handlers.messenger_link import router as link_router
    from handlers.registration import router as reg_router
    from handlers.menu import router as menu_router
    from handlers.telegram_discovery import router as discovery_router
    for router in (link_router, reg_router, menu_router, discovery_router):
        dp.include_router(router)
    _dispatcher = dp
    return dp


def _create_telegram_bot(token):
    """Create the Telegram client, optionally routed through a locally managed proxy."""
    proxy = (getattr(settings, 'TELEGRAM_PROXY', '') or '').strip()
    if not proxy:
        return Bot(token=token)
    from urllib.parse import urlsplit
    parsed = urlsplit(proxy)
    if parsed.scheme not in {'http', 'socks4', 'socks4a', 'socks5'} or not parsed.hostname:
        raise ValueError('TELEGRAM_PROXY must be a valid http:// or socks5:// proxy URL')
    from aiogram.client.session.aiohttp import AiohttpSession
    logger.info('telegram_proxy_configured scheme=%s host=%s', parsed.scheme, parsed.hostname)
    return Bot(token=token, session=AiohttpSession(proxy=proxy))


async def _ensure_telegram_ready(bot):
    """Wait for Telegram API recovery instead of crashing the whole polling worker."""
    global _bot_configured
    delay = 5.0
    while True:
        try:
            await bot.get_me()
            if not _bot_configured:
                await configure_bot(bot)
                _bot_configured = True
            return
        except TelegramUnauthorizedError:
            raise
        except (TelegramNetworkError, TelegramServerError, TelegramRetryAfter,
                asyncio.TimeoutError, OSError) as exc:
            retry_after = getattr(exc, 'retry_after', None)
            wait_for = max(float(retry_after or 0), delay)
            logger.warning(
                "telegram_api_unavailable error_type=%s retry_in_s=%.1f; web app remains online",
                type(exc).__name__, wait_for,
            )
            await asyncio.sleep(wait_for)
            delay = min(delay * 2, 60.0)


async def _poll_telegram_with_retry(dp, bot):
    """Keep polling in this worker through transient API/network interruptions."""
    delay = 5.0
    while True:
        try:
            await dp.start_polling(
                bot, tasks_concurrency_limit=32, handle_signals=False,
                close_bot_session=False,
            )
            return
        except TelegramUnauthorizedError as exc:
            from services.runtime_supervisor import PermanentWorkerExit
            logger.error("telegram_disabled_invalid_token_during_polling")
            raise PermanentWorkerExit("Telegram rejected BOT_TOKEN during polling") from exc
        except (TelegramNetworkError, TelegramServerError, TelegramRetryAfter,
                asyncio.TimeoutError, OSError) as exc:
            retry_after = getattr(exc, 'retry_after', None)
            wait_for = max(float(retry_after or 0), delay)
            logger.warning(
                "telegram_polling_network_interruption error_type=%s retry_in_s=%.1f",
                type(exc).__name__, wait_for,
            )
            await asyncio.sleep(wait_for)
            delay = min(delay * 2, 60.0)


async def run_bot(app):
    global app_instance, bot_instance, _bot_configured
    app_instance = app

    with app.app_context():
        count = db.session.query(db.func.count(Student.id)).scalar()
        logger.info("БД подключена. Студентов: %s", count)

    token = settings.BOT_TOKEN
    if not token:
        logger.error("BOT_TOKEN не задан. Веб-панель продолжит работу без Telegram.")
        return

    # Obtain the dispatcher before opening network sessions. If a handler import
    # fails, we do not leak aiohttp ClientSession objects.
    dp = get_dispatcher()
    bot = _create_telegram_bot(token)
    bot_instance = bot
    try:
        # A revoked token is permanent; temporary DNS/connection timeouts are
        # retried inside this worker so Telegram outages do not restart the app.
        try:
            await _ensure_telegram_ready(bot)
        except TelegramUnauthorizedError:
            logger.error("telegram_disabled_invalid_token; check BOT_TOKEN in .env")
            try:
                from services.bot_journal import record_bot_event
                with app.app_context():
                    record_bot_event('telegram', 'system', 'invalid_credentials', 'error',
                                     summary='Telegram отключён: токен отклонён API')
            except Exception:
                logger.debug("Could not write Telegram credential diagnostic", exc_info=True)
            from services.runtime_supervisor import PermanentWorkerExit
            raise PermanentWorkerExit("Telegram rejected BOT_TOKEN; update .env and restart")
        logger.info("telegram_polling_started")
        from services.bot_journal import record_bot_event
        with app.app_context():
            record_bot_event('telegram', 'system', 'bot_started', summary='Telegram polling запущен')
        await _poll_telegram_with_retry(dp, bot)
    except Exception as exc:
        logger.warning("telegram_polling_interrupted error_type=%s", type(exc).__name__)
        try:
            with app.app_context():
                from services.bot_journal import record_bot_event
                record_bot_event('telegram', 'system', 'polling_error', 'error', summary='Telegram polling остановлен')
        except Exception:
            logger.exception("telegram_polling_error_journal_failed")
        raise
    finally:
        try:
            await bot.session.close()
        finally:
            if bot_instance is bot:
                bot_instance = None
