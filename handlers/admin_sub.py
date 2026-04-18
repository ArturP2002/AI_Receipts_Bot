import html
import os

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

import config
from bot_secrets import ADMIN_USER_IDS, ADMIN_WEBAPP_PUBLIC_URL
from database import ensure_user
from logging_config import logger
from services.db_backup import create_sqlite_backup_file
from services.effective_config import get_effective_config
from services.subscription import format_subscription_date, grant_subscription

router = Router(name="admin")
router.message.filter(F.chat.type == "private")

# Максимум дней за одну выдачу (защита от опечаток в чате).
_GRANT_SUB_MAX_DAYS = 1825
# Лимит Telegram на документ (~50 МБ; берём с запасом).
_BACKUP_MAX_BYTES = 49 * 1024 * 1024


def _is_admin(user_id: int) -> bool:
    return bool(ADMIN_USER_IDS) and user_id in ADMIN_USER_IDS


def _admin_panel_text() -> str:
    ec = get_effective_config()
    return (
        "🔧 <b>Панель администратора</b>\n\n"
        "<b>Команды:</b>\n"
        "• /grant_sub — себе +" + str(ec.subscription_default_days) + " дн. (текущие настройки)\n"
        "• /grant_sub &lt;дней&gt; — себе на N дней (1…" + str(_GRANT_SUB_MAX_DAYS) + ")\n"
        "• /grant_sub &lt;user_id&gt; &lt;дней&gt; — другому пользователю\n"
        "• один аргумент &gt; " + str(_GRANT_SUB_MAX_DAYS) + " — как user_id, период из настроек\n"
        "• /backup_db — скачать снимок SQLite\n\n"
        "<b>Текущие параметры (бот + админка):</b>\n"
        f"• Бот: @{html.escape(config.BOT_USERNAME)}\n"
        f"• Бесплатных полных открытий (база): {ec.base_free_recipe_opens}\n"
        f"• Цена рецепта (Stars): {ec.recipe_star_price}\n"
        f"• Цена «ещё» (Stars): {ec.show_more_star_price}\n"
        f"• Цена подписки (Stars): {ec.subscription_star_price}\n"
        f"• Подписка по умолчанию (дн.): {ec.subscription_default_days}\n"
        f"• Бесплатно «показать ещё» (раз): {ec.free_show_more_count}\n"
        f"• Реф. бонус (открытий): {ec.referral_bonus_opens}\n"
        f"• Режим ИИ продуктов: {html.escape(config.PRODUCTS_AI_MODE)}\n"
        f"• Режим ИИ кухонь: {html.escape(config.CUISINES_AI_MODE)}\n"
        f"• Рецептов за запрос ИИ: {config.AI_RECIPES_PER_REQUEST}\n"
        f"• OpenAI чат: {html.escape(config.OPENAI_CHAT_MODEL)}\n"
        f"• OpenAI изображения: {html.escape(config.OPENAI_IMAGE_MODEL)}\n"
        f"• Ключ OpenAI: {'задан' if config.OPENAI_API_KEY else 'не задан'}"
    )


def _admin_webapp_markup() -> InlineKeyboardMarkup | None:
    base = (ADMIN_WEBAPP_PUBLIC_URL or "").strip().rstrip("/")
    if not base:
        return None
    url = f"{base}/admin/"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📱 Админ-панель (Mini App)", web_app=WebAppInfo(url=url))]
        ]
    )


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not _is_admin(message.from_user.id):
        return
    ensure_user(message.from_user.id)
    kb = _admin_webapp_markup()
    extra = ""
    if not kb:
        extra = (
            "\n\n<i>Mini App: задайте переменную окружения ADMIN_WEBAPP_PUBLIC_URL "
            "(https-ссылка на этот сервер, как в BotFather) и перезапустите бота.</i>"
        )
    await message.answer(
        _admin_panel_text() + extra,
        parse_mode="HTML",
        reply_markup=kb,
    )


def _parse_grant_sub_args(
    admin_id: int, raw: str | None
) -> tuple[int, int | None] | str:
    """
    Возвращает (target_user_id, days или None для значения из .env),
    либо строку с ошибкой для ответа админу.
    """
    parts = (raw or "").split()
    if len(parts) > 2:
        return (
            "Слишком много аргументов. Примеры:\n"
            "/grant_sub\n"
            "/grant_sub 14\n"
            "/grant_sub 1039942647\n"
            "/grant_sub 1039942647 30"
        )
    if not parts:
        return admin_id, None
    if len(parts) == 1:
        if not parts[0].isdigit():
            return "Укажите целые числа: дней для себя или user_id [дней]."
        n = int(parts[0])
        if 1 <= n <= _GRANT_SUB_MAX_DAYS:
            return admin_id, n
        if n > _GRANT_SUB_MAX_DAYS:
            return n, None
        return "Число дней должно быть от 1 до " + str(_GRANT_SUB_MAX_DAYS) + "."
    uid_s, days_s = parts
    if not uid_s.isdigit() or not days_s.isdigit():
        return "Оба аргумента должны быть целыми числами: user_id и дней."
    uid = int(uid_s)
    days = int(days_s)
    if uid <= 0:
        return "user_id должен быть положительным."
    if not (1 <= days <= _GRANT_SUB_MAX_DAYS):
        return "Дни должны быть от 1 до " + str(_GRANT_SUB_MAX_DAYS) + "."
    return uid, days


@router.message(Command("backup_db"))
async def cmd_backup_db(message: Message):
    if not _is_admin(message.from_user.id):
        return
    ensure_user(message.from_user.id)
    tmp_path: str | None = None
    try:
        tmp_path, filename = create_sqlite_backup_file()
        size = os.path.getsize(tmp_path)
        if size > _BACKUP_MAX_BYTES:
            await message.answer(
                f"Файл бэкапа слишком большой для Telegram ({size // (1024 * 1024)} МБ). "
                "Скопируйте БД с сервера вручную."
            )
            return
        await message.answer_document(
            FSInputFile(tmp_path, filename=filename),
            caption="Снимок базы SQLite (UTC в имени файла).",
        )
        logger.info(
            "backup_db: admin=%s size=%s file=%s",
            message.from_user.id,
            size,
            filename,
        )
    except FileNotFoundError as e:
        await message.answer(f"Не удалось найти файл базы: {e}")
    except Exception as e:
        logger.exception("backup_db failed: %s", e)
        await message.answer("Ошибка при создании бэкапа. Подробности в логе сервера.")
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


@router.message(Command("grant_sub"))
async def grant_sub_cmd(message: Message, command: CommandObject):
    if not _is_admin(message.from_user.id):
        return
    parsed = _parse_grant_sub_args(message.from_user.id, command.args)
    if isinstance(parsed, str):
        await message.answer(parsed)
        return
    target_id, days = parsed
    user = ensure_user(target_id)
    effective_days = days if days is not None else get_effective_config().subscription_default_days
    until = grant_subscription(user, days=days)
    until_s = format_subscription_date(until)
    logger.info(
        "grant_sub: admin=%s target=%s days_arg=%s effective_days=%s until=%s",
        message.from_user.id,
        target_id,
        days,
        effective_days,
        until.isoformat(),
    )
    who = "Ваша подписка" if target_id == message.from_user.id else f"Пользователь {target_id}"
    await message.answer(
        f"✅ {who} продлена на {effective_days} дн.\n"
        f"Дата окончания: {until_s}"
    )
