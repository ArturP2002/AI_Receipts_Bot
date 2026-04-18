"""Отправка карточки рецепта с опциональным фото блюда."""

from __future__ import annotations

from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile, InlineKeyboardMarkup


async def send_recipe_with_optional_photo(
    bot: Bot,
    chat_id: int,
    *,
    dish_image_path: str | None,
    title: str,
    short_description: str,
    text: str,
    reply_markup: InlineKeyboardMarkup | None,
) -> None:
    path = (dish_image_path or "").strip()
    if path and Path(path).is_file():
        cap = f"{title}\n\n{(short_description or '')}".strip()[:1024]
        await bot.send_photo(chat_id, photo=FSInputFile(path), caption=cap or None)
    await bot.send_message(chat_id, text, reply_markup=reply_markup)
