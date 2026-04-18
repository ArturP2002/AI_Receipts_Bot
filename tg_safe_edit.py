"""Безопасное редактирование и удаление (Telegram часто отказывает: уже удалено, нет прав и т.д.)."""

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message


async def safe_edit_text(message: Message, text: str, *, reply_markup=None) -> None:
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise


async def safe_delete_message(message: Message | None) -> bool:
    """
    Удалить сообщение. Игнорирует типичные ответы Telegram (сообщение уже удалено,
    нельзя удалить чужое и т.п.) — дальнейшая логика обработчика всё равно выполняется.
    Возвращает True, если delete прошёл без исключения.
    """
    if message is None:
        return False
    try:
        await message.delete()
        return True
    except TelegramBadRequest:
        return False
