from aiogram import Dispatcher

from middlewares import UserGateMiddleware
from handlers import (
    admin_sub,
    cabinet,
    cuisines,
    nav_commands,
    payments,
    products,
    recipe_card,
    settings_handlers,
    welcome,
)


def register_all(dp: Dispatcher) -> None:
    dp.update.outer_middleware(UserGateMiddleware())
    dp.include_router(welcome.router)
    dp.include_router(nav_commands.router)
    dp.include_router(admin_sub.router)
    dp.include_router(products.router)
    dp.include_router(cuisines.router)
    dp.include_router(cabinet.router)
    dp.include_router(settings_handlers.router)
    dp.include_router(recipe_card.router)
    dp.include_router(payments.router)
