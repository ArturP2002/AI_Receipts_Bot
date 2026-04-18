"""Быстрые команды из бокового меню Telegram (список команд)."""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from database import ensure_user
import keyboards
import states
import texts

router = Router(name="nav_commands")
router.message.filter(F.chat.type == "private")


@router.message(Command("products"))
async def cmd_products(message: Message, state: FSMContext):
    ensure_user(message.from_user.id)
    await state.set_state(states.ProductsFlow.waiting_input)
    from handlers.products import render_products_waiting_screen

    await render_products_waiting_screen(message, edit=False)


@router.message(Command("cuisines"))
async def cmd_cuisines(message: Message, state: FSMContext):
    ensure_user(message.from_user.id)
    await state.set_state(states.CuisinesFlow.pick_cuisine)
    await message.answer(texts.CUISINES_CHOOSE, reply_markup=keyboards.cuisines_popular_kb())


@router.message(Command("cabinet"))
async def cmd_cabinet(message: Message, state: FSMContext):
    ensure_user(message.from_user.id)
    from handlers.cabinet import show_cabinet

    await show_cabinet(message, state, edit=False)


@router.message(Command("settings"))
async def cmd_settings(message: Message, state: FSMContext):
    ensure_user(message.from_user.id)
    await state.update_data(settings_back_ctx="cabinet", list_ctx="cabinet")
    from handlers.settings_handlers import enter_settings

    await enter_settings(message, state, edit=False)
