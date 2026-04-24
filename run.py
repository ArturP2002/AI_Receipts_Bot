import asyncio

from logging_config import logger
from bot_init import dp, bot
from bot_menu import setup_bot_menu
from bot_secrets import validate_config
from aiogram import Dispatcher
from database import init_database
from handlers import register_all as _register_all
from services.subscription import process_subscription_tick
from services.daily_recipe import process_daily_recipe_tick
from admin_app import start_admin_http_server, stop_admin_http_server


async def _subscription_worker() -> None:
    while True:
        try:
            await asyncio.sleep(3600)
            await process_subscription_tick(bot)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("subscription_worker: %s", exc, exc_info=True)


async def _daily_recipe_worker() -> None:
    while True:
        try:
            await process_daily_recipe_tick(bot)
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("daily_recipe_worker: %s", exc, exc_info=True)


async def run_bot() -> None:
    logger.info("Старт: проверка BOT_TOKEN…")
    validate_config()
    logger.info("Старт: SQLite и таблицы…")
    init_database()
    setup_routers(dp)
    logger.info("Подключено роутеров: %s", len(dp.sub_routers))
    await setup_bot_menu(bot)
    logger.info("Меню команд и кнопка «Меню» настроены")

    asyncio.create_task(_subscription_worker())
    asyncio.create_task(_daily_recipe_worker())

    try:
        await start_admin_http_server(bot)
    except Exception as exc:
        logger.warning("Админ mini app HTTP не поднят: %s", exc, exc_info=True)

    try:
        logger.info("Polling, allowed_updates=%s", dp.resolve_used_update_types())
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            skip_updates=True,
        )
    except Exception as exc:
        logger.info("Ошибка запуска бота: %s", exc)
    finally:
        try:
            await stop_admin_http_server()
        except Exception as exc:
            logger.warning("Остановка admin HTTP: %s", exc)


def setup_routers(dp: Dispatcher) -> None:
    _register_all(dp)
