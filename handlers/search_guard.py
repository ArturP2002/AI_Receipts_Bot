"""Защита от параллельных долгих подборов и повторных нажатий inline-кнопок."""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

import texts

_in_progress: set[int] = set()
_last_open_recipe: dict[tuple[int, int], float] = {}
OPEN_RECIPE_DEBOUNCE_SEC = 2.5


def is_user_search_busy(user_id: int) -> bool:
    return user_id in _in_progress


@asynccontextmanager
async def user_search_slot(user_id: int) -> AsyncIterator[bool]:
    """True — слот занят этим обработчиком; False — уже идёт другой подбор."""
    if user_id in _in_progress:
        yield False
        return
    _in_progress.add(user_id)
    try:
        yield True
    finally:
        _in_progress.discard(user_id)


async def answer_callback_safe(
    call: CallbackQuery,
    text: str | None = None,
    *,
    show_alert: bool = False,
) -> None:
    try:
        if text:
            await call.answer(text, show_alert=show_alert)
        else:
            await call.answer()
    except TelegramBadRequest as exc:
        low = str(exc).lower()
        if "query is too old" in low or "query id is invalid" in low:
            return
        raise


async def answer_busy(call: CallbackQuery) -> None:
    await answer_callback_safe(call, texts.SEARCH_IN_PROGRESS, show_alert=True)


async def strip_inline_keyboard(message: Message | None) -> None:
    if message is None:
        return
    try:
        await message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass


def should_debounce_open_recipe(user_id: int, recipe_id: int) -> bool:
    key = (user_id, recipe_id)
    now = time.monotonic()
    prev = _last_open_recipe.get(key, 0.0)
    if now - prev < OPEN_RECIPE_DEBOUNCE_SEC:
        return True
    _last_open_recipe[key] = now
    return False
