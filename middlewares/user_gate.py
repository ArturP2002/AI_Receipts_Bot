from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, PreCheckoutQuery, TelegramObject

from bot_secrets import ADMIN_USER_IDS
from database import get_user, sync_telegram_profile


class UserGateMiddleware(BaseMiddleware):
    """Синхронизация профиля Telegram и блокировка пользователей."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user:
            sync_telegram_profile(user.id, user.username, user.first_name)
            row = get_user(user.id)
            if (
                row
                and row.is_blocked
                and user.id not in ADMIN_USER_IDS
            ):
                if isinstance(event, Message):
                    await event.answer("⛔ Доступ к боту ограничен администратором.")
                elif isinstance(event, CallbackQuery):
                    await event.answer("Доступ ограничен.", show_alert=True)
                elif isinstance(event, PreCheckoutQuery):
                    await event.answer(
                        ok=False,
                        error_message="Доступ к оплате ограничен.",
                    )
                return None
        return await handler(event, data)
