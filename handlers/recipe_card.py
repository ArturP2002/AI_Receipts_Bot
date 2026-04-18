import logging
from pathlib import Path

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from database import (
    Recipe,
    UserSavedRecipe,
    db,
    ensure_user,
    get_user,
    user_has_recipe_in_archive,
)
import keyboards
from services import limits
from services.effective_config import get_effective_config
from services.subscription import is_subscription_active
from tg_safe_edit import safe_delete_message
from services.recipe_format import format_full_card, format_teaser_card
from services.recipe_media import send_recipe_with_optional_photo
from services.recipe_openai import ensure_dish_image
import texts

logger = logging.getLogger(__name__)

router = Router()


@router.callback_query(F.data.startswith("open:"))
async def open_recipe(call: CallbackQuery, state: FSMContext):
    await call.answer()
    rid = int(call.data.split(":")[1])
    user = ensure_user(call.from_user.id)
    recipe = Recipe.get_by_id(rid)
    if recipe.ai_chat_model and not (
        recipe.dish_image_path and Path(recipe.dish_image_path).is_file()
    ):
        await ensure_dish_image(recipe)
        recipe = Recipe.get_by_id(rid)
    show_full, is_first = limits.register_recipe_view(user, rid)
    if is_first:
        referrer_id = limits.try_grant_referral_bonus_on_first_recipe_open(user.user_id)
        if referrer_id is not None:
            try:
                await call.bot.send_message(
                    referrer_id,
                    texts.REFERRAL_BONUS_GRANTED.format(
                        bonus=get_effective_config().referral_bonus_opens
                    ),
                )
            except Exception as exc:
                logger.warning(
                    "referral bonus notify failed referrer_id=%s: %s",
                    referrer_id,
                    exc,
                )

    data = await state.get_data()
    list_ctx = data.get("list_ctx", "products")

    uid = call.from_user.id
    in_archive = user_has_recipe_in_archive(uid, rid)
    if show_full:
        text = format_full_card(recipe)
        kb = keyboards.recipe_card_full_kb(rid, list_ctx=list_ctx, in_archive=in_archive)
    else:
        text = format_teaser_card(recipe) + "\n\n" + texts.PAYWALL_FOOTER
        kb = keyboards.recipe_card_kb(
            rid,
            list_ctx=list_ctx,
            show_save=False,
            show_buy=not is_subscription_active(user),
        )

    await safe_delete_message(call.message)
    await send_recipe_with_optional_photo(
        call.bot,
        call.from_user.id,
        dish_image_path=recipe.dish_image_path,
        title=recipe.title,
        short_description=recipe.short_description or "",
        text=text,
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("save:"))
async def save_recipe(call: CallbackQuery, state: FSMContext):
    rid = int(call.data.split(":")[1])
    uid = call.from_user.id
    with db.atomic():
        UserSavedRecipe.insert(user_id=uid, recipe_id=rid).on_conflict_ignore().execute()
    await call.answer("Сохранено в архив")
    data = await state.get_data()
    list_ctx = data.get("list_ctx", "products")
    recipe = Recipe.get_by_id(rid)
    u = get_user(uid) or ensure_user(uid)
    show_full = limits.user_can_see_full_recipe(u, rid)
    if show_full:
        text = format_full_card(recipe)
        kb = keyboards.recipe_card_full_kb(rid, list_ctx=list_ctx, in_archive=True)
    else:
        text = format_teaser_card(recipe) + "\n\n" + texts.PAYWALL_FOOTER
        kb = keyboards.recipe_card_kb(
            rid,
            list_ctx=list_ctx,
            show_save=False,
            show_buy=not is_subscription_active(u),
        )
    try:
        await call.message.edit_text(text, reply_markup=kb)
    except Exception:
        pass


@router.callback_query(F.data.startswith("unsave:"))
async def unsave_recipe(call: CallbackQuery, state: FSMContext):
    rid = int(call.data.split(":")[1])
    uid = call.from_user.id
    UserSavedRecipe.delete().where(
        (UserSavedRecipe.user_id == uid) & (UserSavedRecipe.recipe_id == rid)
    ).execute()
    await call.answer("Удалено из архива")
    data = await state.get_data()
    list_ctx = data.get("list_ctx", "products")
    recipe = Recipe.get_by_id(rid)
    u = get_user(uid) or ensure_user(uid)
    show_full = limits.user_can_see_full_recipe(u, rid)
    if show_full:
        text = format_full_card(recipe)
        kb = keyboards.recipe_card_full_kb(rid, list_ctx=list_ctx, in_archive=False)
    else:
        text = format_teaser_card(recipe) + "\n\n" + texts.PAYWALL_FOOTER
        kb = keyboards.recipe_card_kb(
            rid,
            list_ctx=list_ctx,
            show_save=False,
            show_buy=not is_subscription_active(u),
        )
    try:
        await call.message.edit_text(text, reply_markup=kb)
    except Exception:
        pass


@router.callback_query(F.data.startswith("buy:"))
async def buy_recipe(call: CallbackQuery, state: FSMContext):
    from handlers.payments import send_recipe_invoice

    uid = call.from_user.id
    u = ensure_user(uid)
    if is_subscription_active(u):
        await call.answer("У тебя активна подписка — полные рецепты уже доступны.", show_alert=True)
        return
    rid = int(call.data.split(":")[1])
    await send_recipe_invoice(call.message, call.from_user.id, rid)
    await call.answer()


@router.callback_query(F.data.startswith("back_list:"))
async def back_to_list(call: CallbackQuery, state: FSMContext):
    ctx = call.data.split(":", 1)[1]
    data = await state.get_data()
    ids = data.get("result_ids") or []
    offset = int(data.get("list_offset") or 0)
    if not ids:
        await call.answer()
        return
    ordered = [Recipe.get_by_id(i) for i in ids]
    chunk = ordered[offset : offset + 3]

    if ctx == "products":
        from enums import cook_method_label_ru

        method = data.get("cook_method", "")
        label = cook_method_label_ru(method) if method else "подбор"
        head = f"🍳 Вот что можно приготовить способом: {label}\n\n"
        lines = [f"{i + 1 + offset}. {r.title} — {r.time_minutes} мин" for i, r in enumerate(chunk)]
        body = head + "\n".join(lines) + "\n\nНажми на рецепт, чтобы открыть карточку."
        more_cb = "pr:more"
        list_ctx = "products"
    elif ctx == "cuisine":
        from data.cuisine_catalog import label_for_slug

        slug = data.get("cuisine_slug", "")
        lab = data.get("cuisine_display") or label_for_slug(slug)
        lines = [f"• {r.title} — {r.time_minutes} мин" for r in chunk]
        body = f"🍝 Подходящие рецепты ({lab}):\n\n" + "\n".join(lines)
        more_cb = "cu:more"
        list_ctx = "cuisine"
    elif ctx == "archive":
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        from aiogram.types import InlineKeyboardButton
        from database import UserSavedRecipe

        uid = call.from_user.id
        q = (
            UserSavedRecipe.select(UserSavedRecipe, Recipe)
            .join(Recipe, on=(UserSavedRecipe.recipe_id == Recipe.id))
            .where(UserSavedRecipe.user_id == uid)
            .order_by(UserSavedRecipe.saved_at.desc())
        )
        rows = list(q)
        lines = "\n".join(f"• {ur.recipe.title}" for ur in rows[:15])
        body = f"📂 Сохранённые рецепты:\n{lines}\n\nНажми на рецепт, чтобы открыть."
        b = InlineKeyboardBuilder()
        for ur in rows[:20]:
            r = ur.recipe
            b.add(InlineKeyboardButton(text=r.title[:60], callback_data=f"open:{r.id}"))
        b.add(InlineKeyboardButton(text="🗑 Очистить архив", callback_data="archive:clear"))
        b.add(InlineKeyboardButton(text="⚙️ Настроить рецепт", callback_data="set_from:cabinet"))
        b.add(InlineKeyboardButton(text="🔙 Назад в кабинет", callback_data="cabinet"))
        b.adjust(1)
        await state.update_data(list_ctx="archive")
        await safe_delete_message(call.message)
        await call.message.answer(body, reply_markup=b.as_markup())
        await call.answer()
        return
    else:
        await call.answer()
        return

    show_more = offset + 3 < len(ordered)
    await state.update_data(list_ctx=list_ctx)
    await safe_delete_message(call.message)
    await call.message.answer(
        body,
        reply_markup=keyboards.recipe_list_kb(
            chunk,
            settings_ctx=list_ctx,
            show_more=show_more,
            more_callback=more_cb,
        ),
    )
    await call.answer()


@router.callback_query(F.data.startswith("set_from:"))
async def settings_from_context(call: CallbackQuery, state: FSMContext):
    from handlers.settings_handlers import enter_settings
    from states import SettingsFlow

    ctx = call.data.split(":", 1)[1]
    await state.update_data(settings_back_ctx=ctx, list_ctx=(await state.get_data()).get("list_ctx", ctx))
    await enter_settings(call.message, state, edit=True)
    await call.answer()
