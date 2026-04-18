import logging
import os
import sys


def setup_logging():
    """Настройка логгирования для всего проекта"""

    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, OSError):
        pass

    # Создаем форматтер
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # LOG_LEVEL=DEBUG для подробного вывода
    level_name = os.getenv('LOG_LEVEL', 'INFO').upper()
    level = getattr(logging, level_name, logging.INFO)

    # Настраиваем root-логгер, чтобы в терминал попадали логи всех модулей
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers.clear()

    # Консольный обработчик
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)

    root_logger.addHandler(console_handler)
    try:
        file_handler = logging.FileHandler("bot.log", encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    except OSError:
        pass

    logging.captureWarnings(True)

    logger = logging.getLogger('order_bot')
    logger.setLevel(level)
    logger.propagate = True

    return logger


# Инициализируем логгер
logger = setup_logging()
