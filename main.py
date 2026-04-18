
import asyncio
from logging_config import logger
from run import run_bot


async def main():
    """Главная функция запуска бота"""
    try:
        logger.info("Процесс запущен, поднимаем бота…")
        await run_bot()
    except asyncio.CancelledError:
        logger.info("Работа бота отменена")
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем (Ctrl+C)")
    except Exception as e:
        logger.error(
            "Критическая ошибка при работе бота: %s",
            e,
            exc_info=True,
        )
        raise


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
    except Exception as e:
        logger.error("Непредвиденная ошибка: %s", e, exc_info=True)
