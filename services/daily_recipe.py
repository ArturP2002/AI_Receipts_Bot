from __future__ import annotations

import asyncio
import random
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.types import BufferedInputFile

import config
from data.cuisine_catalog import ALL_CUISINE_SLUGS, CUISINE_DESCRIPTION, label_for_slug
from database import BotRuntimeSettings, UsersData
from logging_config import logger
from services import openai_ai

_MSK_TZ = ZoneInfo("Europe/Moscow")


def _today_msk_iso() -> str:
    return datetime.now(_MSK_TZ).date().isoformat()


def _already_sent_today() -> bool:
    row = BotRuntimeSettings.get_or_none(BotRuntimeSettings.id == 1)
    if not row:
        return False
    return (row.daily_recipe_last_sent_date or "") == _today_msk_iso()


def _mark_sent_today() -> None:
    row = BotRuntimeSettings.get_or_none(BotRuntimeSettings.id == 1)
    if not row:
        return
    row.daily_recipe_last_sent_date = _today_msk_iso()
    row.save()


def _pick_cuisine() -> tuple[str, str]:
    slug = random.choice(ALL_CUISINE_SLUGS)
    return slug, label_for_slug(slug)


async def _generate_daily_recipe_payload() -> dict:
    cuisine_slug, cuisine_label = _pick_cuisine()
    cuisine_note = CUISINE_DESCRIPTION.get(cuisine_slug, "Аутентичная кухня с ярким характером.")

    recipe_obj = await openai_ai.chat_json_object(
        (
            "Ты шеф-повар и редактор кулинарного журнала. "
            "Верни строго JSON-объект с полями: "
            "title (str), short_description (str), ingredients (list[str]), "
            "steps (list[str]), time_minutes (int). "
            "Пиши только на русском, без markdown."
        ),
        (
            f"Сгенерируй 1 «рецепт дня» кухни: {cuisine_label} ({cuisine_slug}). "
            f"Контекст кухни: {cuisine_note} "
            "Ограничения: 7-12 ингредиентов, 5-8 шагов, время 15-90 минут, "
            "понятные домашние формулировки."
        ),
        max_tokens=800,
    )

    story = await openai_ai.complete_text(
        (
            "Ты гастрономический журналист. "
            "Напиши короткую живую заметку на русском про происхождение блюда "
            "или интересный факт вокруг его культуры. 2-4 предложения, без markdown."
        ),
        (
            f"Кухня: {cuisine_label}. "
            f"Блюдо: {str(recipe_obj.get('title') or '').strip() or 'Рецепт дня'}."
        ),
        max_tokens=220,
    )

    title = str(recipe_obj.get("title") or "Рецепт дня").strip()
    short_description = str(recipe_obj.get("short_description") or "").strip()
    ingredients = recipe_obj.get("ingredients") if isinstance(recipe_obj.get("ingredients"), list) else []
    steps = recipe_obj.get("steps") if isinstance(recipe_obj.get("steps"), list) else []
    time_minutes_raw = recipe_obj.get("time_minutes")
    try:
        time_minutes = int(time_minutes_raw)
    except (TypeError, ValueError):
        time_minutes = 35
    time_minutes = max(10, min(120, time_minutes))

    # Защита от пустых ответов модели.
    if not ingredients:
        ingredients = ["Основные продукты по вкусу", "Соль", "Специи", "Немного растительного масла"]
    if not steps:
        steps = [
            "Подготовь ингредиенты и разогрей сковороду или духовку.",
            "Соедини основные ингредиенты и доведи до готовности.",
            "Попробуй на вкус, добавь специи и подай горячим.",
        ]

    return {
        "cuisine_label": cuisine_label,
        "title": title[:120],
        "short_description": short_description[:400],
        "ingredients": [str(x).strip()[:120] for x in ingredients[:12] if str(x).strip()],
        "steps": [str(x).strip()[:260] for x in steps[:8] if str(x).strip()],
        "time_minutes": time_minutes,
        "story": (story or "").strip()[:700],
    }


def _build_daily_text(payload: dict) -> str:
    ingredients = payload.get("ingredients") or []
    steps = payload.get("steps") or []
    story = str(payload.get("story") or "").strip()
    short = str(payload.get("short_description") or "").strip()
    ing_block = "\n".join(f"• {x}" for x in ingredients) or "• По вкусу"
    steps_block = "\n".join(f"{i}. {x}" for i, x in enumerate(steps, start=1)) or "1. Приготовь по вкусу."
    story_block = f"\n\n📚 История и факт дня\n{story}" if story else ""
    short_block = f"\n{short}" if short else ""
    return (
        f"🍽 Рецепт дня\n"
        f"🌍 Кухня: {payload.get('cuisine_label')}\n"
        f"🥘 Блюдо: {payload.get('title')}\n"
        f"⏱ Время: ~{payload.get('time_minutes')} мин\n"
        f"{short_block}\n\n"
        f"🛒 Ингредиенты:\n{ing_block}\n\n"
        f"👨‍🍳 Как готовить:\n{steps_block}"
        f"{story_block}"
    )


async def _render_image_bytes(payload: dict) -> bytes | None:
    try:
        prompt = await openai_ai.complete_text(
            (
                "Write one concise English prompt for a photorealistic food image generator. "
                "No text, logos or watermarks in image."
            ),
            (
                f"Dish title: {payload.get('title')}\n"
                f"Cuisine: {payload.get('cuisine_label')}\n"
                f"Short description: {payload.get('short_description')}\n"
                f"Ingredients: {', '.join(payload.get('ingredients') or [])}"
            ),
            max_tokens=180,
        )
        if not prompt.strip():
            return None
        return await openai_ai.generate_image_png_bytes(prompt)
    except Exception as exc:
        logger.warning("daily_recipe image generation failed: %s", exc)
        return None


async def send_daily_recipe_broadcast(bot: Bot) -> None:
    if not config.DAILY_RECIPE_ENABLED:
        return
    if not config.OPENAI_API_KEY:
        logger.warning("daily_recipe: skipped, OPENAI_API_KEY is empty")
        return
    if _already_sent_today():
        return

    payload = await _generate_daily_recipe_payload()
    text = _build_daily_text(payload)
    image = await _render_image_bytes(payload)

    ok = 0
    failed = 0
    users = UsersData.select().where(UsersData.is_blocked == False)  # noqa: E712
    for u in users:
        try:
            if image:
                cap = (
                    f"🍽 Рецепт дня\n"
                    f"🌍 {payload.get('cuisine_label')}\n"
                    f"🥘 {payload.get('title')}\n"
                    f"⏱ ~{payload.get('time_minutes')} мин"
                )[:1024]
                await bot.send_photo(
                    u.user_id,
                    photo=BufferedInputFile(image, filename="daily_recipe.png"),
                    caption=cap,
                )
            await bot.send_message(u.user_id, text)
            ok += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.12)

    _mark_sent_today()
    logger.info("daily_recipe: sent_ok=%s failed=%s", ok, failed)


async def process_daily_recipe_tick(bot: Bot) -> None:
    if not config.DAILY_RECIPE_ENABLED:
        return
    now = datetime.now(_MSK_TZ)
    if now.hour != config.DAILY_RECIPE_HOUR_MSK:
        return
    if now.minute < config.DAILY_RECIPE_MINUTE_MSK:
        return
    if now.minute >= config.DAILY_RECIPE_MINUTE_MSK + config.DAILY_RECIPE_SEND_WINDOW_MINUTES:
        return
    await send_daily_recipe_broadcast(bot)

