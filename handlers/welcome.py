import asyncio
import re

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from database import ensure_user
from keyboards import start_kb
from services.limits import remaining_full_free_opens
from services.referrals import link_referral_on_start
import texts

router = Router()


def _parse_ref(start_arg: str | None) -> int | None:
    if not start_arg:
        return None
    m = re.match(r"ref_(\d+)", start_arg.strip())
    if m:
        return int(m.group(1))
    return None


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    arg = message.text.split(maxsplit=1)[1] if message.text and " " in message.text else None
    ref = _parse_ref(arg)
    uid = message.from_user.id
    user = ensure_user(uid, ref)
    if ref:
        link_referral_on_start(uid, ref)
    if not user.onboarding_shown:
        await message.answer(texts.get_start_onboarding_text())
        user.onboarding_shown = True
        user.save()
        await asyncio.sleep(5)
    await message.answer(
        texts.get_welcome_text(remaining_full_free_opens(user)),
        reply_markup=start_kb(),
    )


@router.callback_query(F.data == "main_menu")
async def main_menu_cb(call: CallbackQuery, state: FSMContext):
    await state.clear()
    user = ensure_user(call.from_user.id)
    await call.message.edit_text(
        texts.get_welcome_text(remaining_full_free_opens(user)),
        reply_markup=start_kb(),
    )
    await call.answer()
