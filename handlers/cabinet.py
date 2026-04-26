from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

import config
from database import Recipe, UserSavedRecipe, ensure_user
from services.effective_config import get_effective_config
import keyboards
from services.subscription import format_subscription_date, is_subscription_active
import states
import texts
from tg_safe_edit import safe_delete_message, safe_edit_text

router = Router()


def _cabinet_body(user_id: int) -> str:
    u = ensure_user(user_id)
    if is_subscription_active(u) and u.subscription_expires_at:
        sub = f"⭐ Подписка активна до {format_subscription_date(u.subscription_expires_at)}."
    else:
        sub = "⭐ Подписка не активна — открой «Подписка», чтобы продлить за звёзды."
    return f"{texts.CABINET_MAIN}\n\n{sub}"


async def show_cabinet(message: Message, state: FSMContext, *, edit: bool = False) -> None:
    await state.set_state(states.CabinetFlow.main)
    body = _cabinet_body(message.from_user.id)
    if edit:
        await safe_edit_text(message, body, reply_markup=keyboards.cabinet_main_kb())
    else:
        await message.answer(body, reply_markup=keyboards.cabinet_main_kb())


@router.callback_query(F.data == "cabinet")
async def cabinet_entry(call: CallbackQuery, state: FSMContext):
    # Вход из главного меню может быть из фото-сообщения, его нельзя редактировать как text.
    await safe_delete_message(call.message)
    await show_cabinet(call.message, state, edit=False)
    await call.answer()


@router.callback_query(F.data == "sub:info")
async def subscription_info(call: CallbackQuery):
    user = ensure_user(call.from_user.id)
    if is_subscription_active(user) and user.subscription_expires_at:
        st = f"Сейчас активна до {format_subscription_date(user.subscription_expires_at)}."
    else:
        st = "Сейчас нет активной подписки."
    ec = get_effective_config()
    text = texts.SUBSCRIPTION_OFFER_PAGE.format(
        days=ec.subscription_default_days,
        price=ec.subscription_star_price,
        status=st,
    )
    await safe_edit_text(call.message, text, reply_markup=keyboards.cabinet_subscription_kb())
    await call.answer()


@router.callback_query(F.data == "sub:pay")
async def subscription_pay(call: CallbackQuery):
    from handlers.payments import send_subscription_invoice

    await send_subscription_invoice(call.message, call.from_user.id)
    await call.answer()


async def _render_archive(call: CallbackQuery, state: FSMContext) -> None:
    uid = call.from_user.id
    q = (
        UserSavedRecipe.select(UserSavedRecipe, Recipe)
        .join(Recipe, on=(UserSavedRecipe.recipe_id == Recipe.id))
        .where(UserSavedRecipe.user_id == uid)
        .order_by(UserSavedRecipe.saved_at.desc())
    )
    rows = list(q)
    if not rows:
        await safe_edit_text(
            call.message,
            texts.ARCHIVE_EMPTY,
            reply_markup=keyboards.cabinet_main_kb(),
        )
        return
    ids = [r.recipe_id for r in rows]
    await state.update_data(result_ids=ids, list_offset=0, list_ctx="archive")
    b = InlineKeyboardBuilder()
    for ur in rows[:20]:
        r = ur.recipe
        b.add(InlineKeyboardButton(text=r.title[:60], callback_data=f"open:{r.id}"))
    b.add(InlineKeyboardButton(text="🗑 Очистить архив", callback_data="archive:clear"))
    b.add(InlineKeyboardButton(text="⚙️ Настроить рецепт", callback_data="set_from:cabinet"))
    b.add(InlineKeyboardButton(text="🔙 Назад в кабинет", callback_data="cabinet"))
    b.adjust(1)
    lines = "\n".join(f"• {ur.recipe.title}" for ur in rows[:15])
    await safe_edit_text(
        call.message,
        f"📂 Сохранённые рецепты:\n{lines}\n\nНажми на рецепт, чтобы открыть.",
        reply_markup=b.as_markup(),
    )


@router.callback_query(F.data == "archive")
async def cabinet_archive(call: CallbackQuery, state: FSMContext):
    await _render_archive(call, state)
    await call.answer()


@router.callback_query(F.data == "archive:clear")
async def archive_clear(call: CallbackQuery, state: FSMContext):
    UserSavedRecipe.delete().where(UserSavedRecipe.user_id == call.from_user.id).execute()
    await _render_archive(call, state)
    await call.answer("Архив очищен")


@router.callback_query(F.data == "invite")
async def cabinet_invite(call: CallbackQuery, state: FSMContext):
    uid = call.from_user.id
    link = f"https://t.me/{config.BOT_USERNAME}?start=ref_{uid}"
    await call.message.edit_text(
        texts.INVITE_TEXT.format(link=link),
        reply_markup=keyboards.invite_kb(link, texts.INVITE_SHARE_TEXT),
    )
    await call.answer()
