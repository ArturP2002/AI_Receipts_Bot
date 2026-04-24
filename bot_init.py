
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from bot_secrets import BOT_TOKEN
from aiogram.fsm.storage.memory import MemoryStorage

storage = MemoryStorage()
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
)
dp = Dispatcher(storage=storage)  # Создаем переменную диспетчера tg-бота
