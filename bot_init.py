
from aiogram import Bot, Dispatcher
from bot_secrets import BOT_TOKEN
from aiogram.fsm.storage.memory import MemoryStorage

storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=storage)  # Создаем переменную диспетчера tg-бота
