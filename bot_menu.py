"""Меню команд (боковая кнопка «Меню» / список быстрых команд)."""

from aiogram import Bot
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
    MenuButtonCommands,
)

from bot_secrets import ADMIN_USER_IDS
from logging_config import logger

USER_BOT_COMMANDS: list[BotCommand] = [
    BotCommand(command="start", description="👋 Приветствие и главное меню"),
    BotCommand(command="products", description="🥬 Подобрать рецепт по продуктам"),
    BotCommand(command="cuisines", description="🌍 Кухни мира"),
    BotCommand(command="cabinet", description="📂 Кабинет и архив"),
    BotCommand(command="settings", description="⚙️ Настройки подбора рецептов"),
]


async def setup_bot_menu(bot: Bot) -> None:
    try:
        await bot.set_my_commands(USER_BOT_COMMANDS, scope=BotCommandScopeAllPrivateChats())
    except Exception as exc:
        logger.warning("Не удалось установить общий список команд: %s", exc)
    # Сброс ранее выданного меню с /admin и /grant_sub (scope «чат» перекрывает общий список).
    for uid in ADMIN_USER_IDS:
        try:
            await bot.set_my_commands(
                USER_BOT_COMMANDS,
                scope=BotCommandScopeChat(chat_id=uid),
            )
        except Exception as exc:
            logger.warning(
                "Не удалось сбросить меню для админа %s: %s",
                uid,
                exc,
            )
    try:
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    except Exception as exc:
        logger.warning("Не удалось установить кнопку «Меню»: %s", exc)
