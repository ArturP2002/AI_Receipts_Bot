import secrets

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import LabeledPrice, Message, PreCheckoutQuery

from peewee import IntegrityError

from database import Recipe, StarPayment, UserPurchasedRecipe, UserSavedRecipe, db, ensure_user
import config
import texts
from services.effective_config import get_effective_config
from services.recipe_format import format_full_card
from services.subscription import format_subscription_date, grant_subscription
from services.recipe_media import send_recipe_with_optional_photo
import keyboards

router = Router()

# Для Telegram Stars provider_token должен быть пустой строкой (без стороннего провайдера).
_STARS_INVOICE_EXTRA = {"provider_token": "", "currency": config.TELEGRAM_STARS_CURRENCY}


def _log_star_payment(
    user_id: int,
    amount: int,
    payment_type: str,
    *,
    recipe_id: int | None = None,
    charge_id: str = "",
) -> None:
    try:
        StarPayment.create(
            user_id=user_id,
            amount=max(0, int(amount)),
            payment_type=payment_type,
            recipe_id=recipe_id,
            telegram_payment_charge_id=(charge_id or "")[:128],
        )
    except Exception:
        pass


async def send_recipe_invoice(message: Message, user_id: int, recipe_id: int) -> None:
    recipe = Recipe.get_by_id(recipe_id)
    ec = get_effective_config()
    payload = f"r:{user_id}:{recipe_id}:{secrets.token_hex(4)}"
    await message.bot.send_invoice(
        chat_id=user_id,
        title=recipe.title[:32],
        description="Полный рецепт",
        payload=payload,
        prices=[LabeledPrice(label="Рецепт", amount=ec.recipe_star_price)],
        **_STARS_INVOICE_EXTRA,
    )


async def send_subscription_invoice(message: Message, user_id: int) -> None:
    ec = get_effective_config()
    d = ec.subscription_default_days
    payload = f"s:{user_id}:{secrets.token_hex(8)}"
    await message.bot.send_invoice(
        chat_id=user_id,
        title="Подписка на сервис",
        description=f"Доступ к архиву и функциям тарифа, {d} дн.",
        payload=payload,
        prices=[LabeledPrice(label=f"Подписка {d} дн.", amount=ec.subscription_star_price)],
        **_STARS_INVOICE_EXTRA,
    )


async def send_show_more_invoice(message: Message, user_id: int, state: FSMContext) -> None:
    ec = get_effective_config()
    payload = f"m:{user_id}:{secrets.token_hex(6)}"
    await state.update_data(pending_more_payload=payload)
    await message.bot.send_invoice(
        chat_id=user_id,
        title="Показать ещё",
        description="Следующая порция рецептов в списке",
        payload=payload,
        prices=[LabeledPrice(label="Ещё рецепты", amount=ec.show_more_star_price)],
        **_STARS_INVOICE_EXTRA,
    )


@router.pre_checkout_query()
async def pre_checkout(pre: PreCheckoutQuery):
    if pre.currency != config.TELEGRAM_STARS_CURRENCY:
        await pre.answer(
            ok=False,
            error_message="Оплата только через Telegram Stars.",
        )
        return
    await pre.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment(message: Message, state: FSMContext):
    sp = message.successful_payment
    if not sp:
        return
    if sp.currency != config.TELEGRAM_STARS_CURRENCY:
        return
    pl = sp.invoice_payload or ""
    uid = message.from_user.id
    paid_amount = int(sp.total_amount or 0)
    charge = sp.telegram_payment_charge_id or ""
    if pl.startswith("r:"):
        parts = pl.split(":")
        if len(parts) >= 3 and int(parts[1]) == uid:
            rid = int(parts[2])
            _log_star_payment(
                uid, paid_amount, "recipe", recipe_id=rid, charge_id=charge
            )
            with db.atomic():
                try:
                    UserPurchasedRecipe.create(
                        user_id=uid,
                        recipe_id=rid,
                        telegram_payment_charge_id=sp.telegram_payment_charge_id or "",
                    )
                except IntegrityError:
                    pass
                try:
                    UserSavedRecipe.create(user_id=uid, recipe_id=rid)
                except IntegrityError:
                    pass
            recipe = Recipe.get_by_id(rid)
            data = await state.get_data()
            list_ctx = data.get("list_ctx", "products")
            await send_recipe_with_optional_photo(
                message.bot,
                message.chat.id,
                dish_image_path=recipe.dish_image_path,
                title=recipe.title,
                short_description=recipe.short_description or "",
                text=format_full_card(recipe),
                reply_markup=keyboards.recipe_card_full_kb(rid, list_ctx=list_ctx, in_archive=True),
            )
    elif pl.startswith("m:"):
        parts = pl.split(":")
        if len(parts) >= 2 and int(parts[1]) == uid:
            _log_star_payment(uid, paid_amount, "show_more", charge_id=charge)
            from handlers import cuisines, products

            data = await state.get_data()
            ids = data.get("result_ids") or []
            cur = int(data.get("list_offset") or 0)
            offset = cur + 3
            if offset >= len(ids):
                await message.answer("Список закончился.")
                return
            await state.update_data(list_offset=offset)
            user = ensure_user(uid)
            list_ctx = data.get("list_ctx", "products")
            ordered = [Recipe.get_by_id(i) for i in ids]
            if list_ctx == "products":
                method = data.get("cook_method", "")
                from enums import cook_method_label_ru

                label = cook_method_label_ru(method) if method else "подбор"
                await products._send_results_message(
                    message.bot,
                    message.chat.id,
                    ordered,
                    label,
                    offset=offset,
                    list_ctx="products",
                    more_cb="pr:more",
                )
            elif list_ctx == "cuisine":
                slug = data.get("cuisine_slug", "")
                lab = data.get("cuisine_display")
                await cuisines._send_cuisine_list(
                    message,
                    user,
                    ordered,
                    slug,
                    offset,
                    "cu:more",
                    hub_label=lab,
                )
    elif pl.startswith("s:"):
        parts = pl.split(":")
        if len(parts) >= 2 and int(parts[1]) == uid:
            _log_star_payment(uid, paid_amount, "subscription", charge_id=charge)
            u = ensure_user(uid)
            until = grant_subscription(u)
            until_s = format_subscription_date(until)
            await message.answer(texts.SUBSCRIPTION_PURCHASED_OK.format(until=until_s))
