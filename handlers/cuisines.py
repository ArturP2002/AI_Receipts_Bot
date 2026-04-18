import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import config
from data.cuisine_catalog import (
    description_for_slug,
    label_for_slug,
    resolve_cuisine_from_text,
)
from database import Recipe, ensure_user, get_user
import keyboards
from services import limits, recipe_openai
import states
import texts
from tg_safe_edit import safe_delete_message

router = Router()
PAGE = 3

logger = logging.getLogger(__name__)


async def _present_cuisine_results(
    call: CallbackQuery,
    state: FSMContext,
    user,
    slug: str,
    lab: str,
    *,
    dish_type: str | None = None,
    time_bucket: str | None = None,
    popular_only: bool = False,
) -> None:
    await call.answer()
    has_key = bool(config.OPENAI_API_KEY)
    if not has_key:
        await safe_delete_message(call.message)
        await call.bot.send_message(call.from_user.id, texts.AI_NO_KEY)
        return

    thinking_msg = await call.message.answer(texts.AI_THINKING)
    await safe_delete_message(call.message)
    try:

        async def _progress(stage: str) -> None:
            if thinking_msg and stage == "images":
                try:
                    await thinking_msg.edit_text(texts.AI_THINKING_IMAGES)
                except Exception:
                    pass

        found = await recipe_openai.generate_recipes_for_cuisine(
            user,
            cuisine_slug=slug,
            cuisine_theme=lab,
            dish_type=dish_type,
            time_bucket=time_bucket,
            popular_only=popular_only,
            progress=_progress,
        )
    except Exception as exc:
        logger.warning("cuisine AI: %s", exc, exc_info=True)
        if thinking_msg:
            try:
                await thinking_msg.edit_text(texts.AI_FAILED)
            except Exception:
                pass
        await call.bot.send_message(
            call.from_user.id,
            texts.NO_RESULTS,
            reply_markup=keyboards.no_results_kb("cuisine"),
        )
        return
    if thinking_msg:
        await safe_delete_message(thinking_msg)

    if not found:
        await call.bot.send_message(
            call.from_user.id,
            texts.NO_RESULTS,
            reply_markup=keyboards.no_results_kb("cuisine"),
        )
        return

    await state.update_data(
        cuisine_slug=slug,
        cuisine_display=lab,
        result_ids=[r.id for r in found],
        list_offset=0,
        list_ctx="cuisine",
    )
    await state.set_state(states.CuisinesFlow.browsing)
    await _send_cuisine_list(
        call.message,
        user,
        found,
        slug,
        offset=0,
        more_cb="cu:more",
        hub_label=lab,
    )


@router.callback_query(F.data == "cu:typed")
async def cuisine_open_text_input(call: CallbackQuery, state: FSMContext):
    await state.set_state(states.CuisinesFlow.search_cuisine)
    await call.message.edit_text(
        texts.CUISINES_SEARCH,
        reply_markup=keyboards.cuisines_search_back_kb(),
    )
    await call.answer()


@router.callback_query(F.data == "world_cuisines")
async def world_cuisines(call: CallbackQuery, state: FSMContext):
    await state.set_state(states.CuisinesFlow.pick_cuisine)
    await call.message.edit_text(texts.CUISINES_CHOOSE, reply_markup=keyboards.cuisines_popular_kb())
    await call.answer()


@router.callback_query(F.data == "cu:find")
async def cuisine_find(call: CallbackQuery, state: FSMContext):
    await state.set_state(states.CuisinesFlow.search_cuisine)
    await call.message.edit_text(texts.CUISINES_SEARCH, reply_markup=keyboards.cuisines_more_kb())
    await call.answer()


@router.callback_query(F.data == "cu:back_popular")
async def cuisine_back_pop(call: CallbackQuery, state: FSMContext):
    await state.set_state(states.CuisinesFlow.pick_cuisine)
    await call.message.edit_text(texts.CUISINES_CHOOSE, reply_markup=keyboards.cuisines_popular_kb())
    await call.answer()


@router.callback_query(F.data.startswith("cu:"))
async def cuisine_picked(call: CallbackQuery, state: FSMContext):
    slug = call.data.split(":", 1)[1]
    if slug in ("find", "back_popular"):
        return
    lab = label_for_slug(slug)
    await state.update_data(cuisine_slug=slug, cuisine_display=lab)
    await state.set_state(states.CuisinesFlow.cuisine_hub)
    desc = description_for_slug(slug, custom_fallback=texts.CUISINE_CUSTOM_FALLBACK)
    await call.message.edit_text(
        f"{lab}\n{desc}\n\nЧто будем готовить?",
        reply_markup=keyboards.cuisine_hub_kb(slug),
    )
    await call.answer()


@router.callback_query(F.data.startswith("cu_add_products:"))
async def cuisine_add_products(call: CallbackQuery, state: FSMContext):
    slug = call.data.split(":", 1)[1]
    data = await state.get_data()
    lab = data.get("cuisine_display") or label_for_slug(slug)
    await state.update_data(
        cuisine_slug=slug,
        cuisine_display=lab,
        products_cuisine_slug=slug,
        products_cuisine_display=lab,
        products_back_callback=f"cu:{slug}",
        products_back_text="🔙 Назад к кухне",
    )
    await state.set_state(states.ProductsFlow.waiting_input)
    await call.message.edit_text(
        f"{texts.ADD_PRODUCTS_PROMPT}\n\n🌍 Выбрана кухня: {lab}\nПодберу рецепты по продуктам в стиле этой кухни.",
        reply_markup=keyboards.products_entry_kb(
            back_callback=f"cu:{slug}",
            back_text="🔙 Назад к кухне",
        ),
    )
    await call.answer()


@router.callback_query(F.data.startswith("cu_pop:"))
async def cuisine_popular(call: CallbackQuery, state: FSMContext):
    slug = call.data.split(":", 1)[1]
    user = ensure_user(call.from_user.id)
    data = await state.get_data()
    lab = data.get("cuisine_display") or label_for_slug(slug)
    await _present_cuisine_results(
        call, state, user, slug, lab, popular_only=True
    )


@router.callback_query(F.data.startswith("cu_type:"))
async def cuisine_type_menu(call: CallbackQuery, state: FSMContext):
    slug = call.data.split(":", 1)[1]
    await state.update_data(cuisine_slug=slug, cuisine_display=label_for_slug(slug))
    await state.set_state(states.CuisinesFlow.pick_meal_type)
    await call.message.edit_text("🍽 Выбери тип блюда:", reply_markup=keyboards.dish_type_kb(slug))
    await call.answer()


@router.callback_query(F.data.startswith("cu_dt:"))
async def cuisine_type_chosen(call: CallbackQuery, state: FSMContext):
    _, slug, dt = call.data.split(":", 2)
    user = ensure_user(call.from_user.id)
    data = await state.get_data()
    lab = data.get("cuisine_display") or label_for_slug(slug)
    await _present_cuisine_results(
        call, state, user, slug, lab, dish_type=dt
    )


@router.callback_query(F.data.startswith("cu_time:"))
async def cuisine_time_menu(call: CallbackQuery, state: FSMContext):
    slug = call.data.split(":", 1)[1]
    await call.message.edit_text("⏱ Выбери время:", reply_markup=keyboards.time_bucket_kb(slug))
    await call.answer()


@router.callback_query(F.data.startswith("cu_tb:"))
async def cuisine_time_chosen(call: CallbackQuery, state: FSMContext):
    parts = call.data.split(":")
    slug, bucket = parts[1], parts[2]
    user = ensure_user(call.from_user.id)
    data = await state.get_data()
    lab = data.get("cuisine_display") or label_for_slug(slug)
    await _present_cuisine_results(
        call, state, user, slug, lab, time_bucket=bucket
    )


async def _send_cuisine_list(
    message,
    user,
    found: list,
    slug: str,
    offset: int,
    more_cb: str,
    *,
    hub_label: str | None = None,
):
    if not found:
        await message.answer(texts.NO_RESULTS, reply_markup=keyboards.no_results_kb("cuisine"))
        return
    lab = hub_label or label_for_slug(slug)
    chunk_ids = [r.id for r in found][offset : offset + PAGE]
    chunk = [Recipe.get_by_id(i) for i in chunk_ids]
    lines = [f"• {r.title} — {r.time_minutes} мин" for r in chunk]
    body = f"🍝 Подходящие рецепты ({lab}):\n\n" + "\n".join(lines)
    if len(lines) < len(found):
        body += "\n\nЕсли хочешь уточнить предпочтения, нажми «Настроить рецепт»."
    show_more = offset + PAGE < len(found)
    await message.answer(
        body,
        reply_markup=keyboards.recipe_list_kb(
            chunk,
            settings_ctx="cuisine",
            show_more=show_more,
            more_callback=more_cb,
        ),
    )


@router.callback_query(F.data == "list_back:cuisine")
async def list_back_cuisine(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    slug = data.get("cuisine_slug", "italian")
    await state.set_state(states.CuisinesFlow.cuisine_hub)
    lab = data.get("cuisine_display") or label_for_slug(slug)
    desc = description_for_slug(slug, custom_fallback=texts.CUISINE_CUSTOM_FALLBACK)
    await call.message.edit_text(
        f"{lab}\n{desc}\n\nЧто будем готовить?",
        reply_markup=keyboards.cuisine_hub_kb(slug),
    )
    await call.answer()


@router.callback_query(F.data == "cu:more")
async def cuisine_more(call: CallbackQuery, state: FSMContext):
    user = get_user(call.from_user.id)
    data = await state.get_data()
    ids = data.get("result_ids") or []
    slug = data.get("cuisine_slug", "")
    offset = int(data.get("list_offset") or 0) + PAGE
    if offset >= len(ids):
        await call.answer("Больше нет")
        return
    if user and not limits.can_use_free_show_more(user):
        from handlers.payments import send_show_more_invoice

        await send_show_more_invoice(call.message, call.from_user.id, state)
        await call.answer()
        return
    if user:
        limits.increment_free_show_more(user)
    await state.update_data(list_offset=offset)
    ordered = [Recipe.get_by_id(i) for i in ids]
    await safe_delete_message(call.message)
    lab = data.get("cuisine_display") or label_for_slug(slug)
    await _send_cuisine_list(
        call.message,
        user or ensure_user(call.from_user.id),
        ordered,
        slug,
        offset,
        "cu:more",
        hub_label=lab,
    )
    await call.answer()


@router.message(states.CuisinesFlow.search_cuisine, F.text)
async def cuisine_search_text(message: Message, state: FSMContext):
    raw = message.text.strip()
    if not raw:
        await message.answer("Напиши страну, регион или тип кухни — любой, не только из списка.")
        return
    slug, lab = resolve_cuisine_from_text(raw)
    desc = description_for_slug(slug, custom_fallback=texts.CUISINE_CUSTOM_FALLBACK)
    await state.update_data(cuisine_slug=slug, cuisine_display=lab)
    await state.set_state(states.CuisinesFlow.cuisine_hub)
    await message.answer(
        f"{lab}\n{desc}\n\nЧто будем готовить?",
        reply_markup=keyboards.cuisine_hub_kb(slug),
    )
