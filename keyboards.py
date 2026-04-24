from urllib.parse import quote

from aiogram import types
from aiogram.utils.keyboard import InlineKeyboardBuilder

from data.cuisine_catalog import MORE_CUISINES, POPULAR_CUISINES
from database import Recipe
from enums import COOK_METHOD_LABEL_RU, DISH_TYPE_LABEL_RU, CookMethod, DishType

def start_kb():
    builder = InlineKeyboardBuilder()
    builder.add(
        types.InlineKeyboardButton(text="🥕 Внести продукты", callback_data="add_products"),
        types.InlineKeyboardButton(text="🌍 Кухни мира", callback_data="world_cuisines"),
        types.InlineKeyboardButton(text="👤 Кабинет", callback_data="cabinet"),
    )
    builder.adjust(1)
    return builder.as_markup()


def products_entry_kb(*, back_callback: str = "main_menu", back_text: str = "🔙 Назад"):
    b = InlineKeyboardBuilder()
    b.add(types.InlineKeyboardButton(text="⚙️ Настроить рецепт", callback_data="set_from:products"))
    b.add(types.InlineKeyboardButton(text=back_text, callback_data=back_callback))
    b.adjust(1)
    return b.as_markup()


def dish_query_clarify_kb():
    """После слишком общего запроса по названию блюда (ТЗ 3.7)."""
    b = InlineKeyboardBuilder()
    b.add(types.InlineKeyboardButton(text="⚙️ Настроить рецепт", callback_data="set_from:products"))
    b.add(types.InlineKeyboardButton(text="🌍 Кухни мира", callback_data="world_cuisines"))
    b.add(types.InlineKeyboardButton(text="🔍 Изменить запрос", callback_data="pr:retry"))
    b.adjust(1)
    return b.as_markup()


def products_kind_kb():
    b = InlineKeyboardBuilder()
    b.add(types.InlineKeyboardButton(text="🥕 Это продукты", callback_data="pr_kind:products"))
    b.add(types.InlineKeyboardButton(text="🍽 Это название блюда", callback_data="pr_kind:dish"))
    b.add(types.InlineKeyboardButton(text="🔙 Назад", callback_data="pr:retry"))
    b.adjust(1)
    return b.as_markup()


def allergy_conflict_kb():
    b = InlineKeyboardBuilder()
    b.add(types.InlineKeyboardButton(text="⚙️ Открыть настройки", callback_data="set_from:products"))
    b.add(types.InlineKeyboardButton(text="🔁 Ввести продукты заново", callback_data="pr:retry"))
    b.adjust(1)
    return b.as_markup()


def cook_method_main_kb():
    b = InlineKeyboardBuilder()
    mapping = [
        (CookMethod.BOIL, "🍲 Сварить"),
        (CookMethod.FRY, "🍳 Пожарить"),
        (CookMethod.BAKE, "🔥 Запечь"),
        (CookMethod.OTHER, "🍽 Другое"),
    ]
    for m, label in mapping:
        b.add(types.InlineKeyboardButton(text=label, callback_data=f"cm:{m.value}"))
    b.add(types.InlineKeyboardButton(text="🔙 Назад", callback_data="pr:back_input"))
    b.adjust(2, 2, 1)
    return b.as_markup()


def cook_method_extra_kb():
    b = InlineKeyboardBuilder()
    extras = [
        (CookMethod.STEW, "🥘 Тушить"),
        (CookMethod.STEAM, "🥟 На пару"),
        (CookMethod.GRILL, "🍢 На гриле"),
        (CookMethod.DEEP_FRY, "🍟 Во фритюре"),
        (CookMethod.BBQ, "🍖 На мангале"),
        (CookMethod.RAW, "🥗 Без термической обработки"),
    ]
    for m, label in extras:
        b.add(types.InlineKeyboardButton(text=label, callback_data=f"cm:{m.value}"))
    b.add(types.InlineKeyboardButton(text="🔙 Назад", callback_data="pr:back_method_main"))
    b.adjust(2, 2, 2, 1)
    return b.as_markup()


def recipe_list_kb(
    recipes: list[Recipe],
    *,
    settings_ctx: str,
    show_more: bool = False,
    more_callback: str = "list:more",
):
    b = InlineKeyboardBuilder()
    for r in recipes:
        label = f"{r.title} — {r.time_minutes} мин"
        if len(label) > 60:
            label = label[:57] + "…"
        b.add(types.InlineKeyboardButton(text=label, callback_data=f"open:{r.id}"))
    b.adjust(1)
    row2 = InlineKeyboardBuilder()
    if show_more:
        row2.add(types.InlineKeyboardButton(text="🔄 Показать ещё", callback_data=more_callback))
    row2.add(types.InlineKeyboardButton(text="⚙️ Настроить рецепт", callback_data=f"set_from:{settings_ctx}"))
    row2.add(types.InlineKeyboardButton(text="🔙 Назад", callback_data=f"list_back:{settings_ctx}"))
    row2.adjust(1)
    b.attach(row2)
    return b.as_markup()


def recipe_card_kb(
    recipe_id: int,
    *,
    list_ctx: str,
    show_save: bool = True,
    in_archive: bool = False,
    show_buy: bool = True,
):
    b = InlineKeyboardBuilder()
    if show_save:
        if in_archive:
            b.add(types.InlineKeyboardButton(text="🗑 Удалить из архива", callback_data=f"unsave:{recipe_id}"))
        else:
            b.add(types.InlineKeyboardButton(text="📌 Сохранить в архив", callback_data=f"save:{recipe_id}"))
    if show_buy:
        b.add(types.InlineKeyboardButton(text="⭐ Купить за звёзды", callback_data=f"buy:{recipe_id}"))
    b.add(types.InlineKeyboardButton(text="⚙️ Настроить рецепт", callback_data=f"set_from:{list_ctx}"))
    b.add(types.InlineKeyboardButton(text="🔙 Назад к списку", callback_data=f"back_list:{list_ctx}"))
    b.adjust(1)
    return b.as_markup()


def recipe_card_full_kb(recipe_id: int, *, list_ctx: str, in_archive: bool = False):
    b = InlineKeyboardBuilder()
    if in_archive:
        b.add(types.InlineKeyboardButton(text="🗑 Удалить из архива", callback_data=f"unsave:{recipe_id}"))
    else:
        b.add(types.InlineKeyboardButton(text="📌 Сохранить в архив", callback_data=f"save:{recipe_id}"))
    b.add(types.InlineKeyboardButton(text="⚙️ Настроить рецепт", callback_data=f"set_from:{list_ctx}"))
    b.add(types.InlineKeyboardButton(text="🔙 Назад к списку", callback_data=f"back_list:{list_ctx}"))
    b.adjust(1)
    return b.as_markup()


def cuisines_popular_kb():
    b = InlineKeyboardBuilder()
    for slug, label in POPULAR_CUISINES:
        b.add(types.InlineKeyboardButton(text=label, callback_data=f"cu:{slug}"))
    b.add(types.InlineKeyboardButton(text="✍️ Написать кухню", callback_data="cu:typed"))
    b.add(types.InlineKeyboardButton(text="🔍 Найти другую", callback_data="cu:find"))
    b.add(types.InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu"))
    b.adjust(2, 2, 2, 2, 1, 1, 1)
    return b.as_markup()


def cuisines_search_back_kb():
    b = InlineKeyboardBuilder()
    b.add(types.InlineKeyboardButton(text="🔙 К списку кухонь", callback_data="cu:back_popular"))
    b.adjust(1)
    return b.as_markup()


def cuisines_more_kb():
    b = InlineKeyboardBuilder()
    for slug, label in MORE_CUISINES:
        b.add(types.InlineKeyboardButton(text=label, callback_data=f"cu:{slug}"))
    b.add(types.InlineKeyboardButton(text="🔙 Назад", callback_data="cu:back_popular"))
    b.adjust(2, 2, 2, 2, 2, 1, 1)
    return b.as_markup()


def cuisine_hub_kb(slug: str):
    b = InlineKeyboardBuilder()
    b.add(types.InlineKeyboardButton(text="📋 Популярные рецепты", callback_data=f"cu_pop:{slug}"))
    b.add(types.InlineKeyboardButton(text="🥕 Внести продукты", callback_data=f"cu_add_products:{slug}"))
    b.add(types.InlineKeyboardButton(text="⚙️ Настроить рецепт", callback_data="set_from:cuisine_hub"))
    b.add(types.InlineKeyboardButton(text="🔙 Назад к кухням", callback_data="world_cuisines"))
    b.adjust(1)
    return b.as_markup()


def dish_type_kb(slug: str):
    b = InlineKeyboardBuilder()
    for dt in DishType:
        b.add(
            types.InlineKeyboardButton(
                text=f"🍽 {DISH_TYPE_LABEL_RU[dt]}",
                callback_data=f"cu_dt:{slug}:{dt.value}",
            )
        )
    b.add(types.InlineKeyboardButton(text="🔙 Назад", callback_data=f"cu:{slug}"))
    b.adjust(1)
    return b.as_markup()


def time_bucket_kb(slug: str):
    b = InlineKeyboardBuilder()
    b.add(types.InlineKeyboardButton(text="⚡ Быстро: 5–15 минут", callback_data=f"cu_tb:{slug}:fast"))
    b.add(types.InlineKeyboardButton(text="🕒 Средне: 15–45 минут", callback_data=f"cu_tb:{slug}:medium"))
    b.add(types.InlineKeyboardButton(text="🔥 Долго: 45+ минут", callback_data=f"cu_tb:{slug}:long"))
    b.add(types.InlineKeyboardButton(text="🔙 Назад", callback_data=f"cu:{slug}"))
    b.adjust(1)
    return b.as_markup()


def cabinet_main_kb():
    b = InlineKeyboardBuilder()
    b.add(types.InlineKeyboardButton(text="⚙️ Настроить рецепт", callback_data="set_from:cabinet"))
    b.add(types.InlineKeyboardButton(text="📂 Архив рецептов", callback_data="archive"))
    b.add(types.InlineKeyboardButton(text="⭐ Подписка", callback_data="sub:info"))
    b.add(types.InlineKeyboardButton(text="👥 Пригласить друга", callback_data="invite"))
    b.add(types.InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu"))
    b.adjust(1)
    return b.as_markup()


def cabinet_subscription_kb():
    b = InlineKeyboardBuilder()
    b.add(types.InlineKeyboardButton(text="⭐ Купить / продлить", callback_data="sub:pay"))
    b.add(types.InlineKeyboardButton(text="🔙 Назад в кабинет", callback_data="cabinet"))
    b.adjust(1)
    return b.as_markup()


def settings_root_kb():
    b = InlineKeyboardBuilder()
    b.add(types.InlineKeyboardButton(text="1. 🍽 Кухни мира", callback_data="st:cuisines"))
    b.add(types.InlineKeyboardButton(text="2. 🌿 Вегетарианство и веганство", callback_data="st:diet_veg"))
    b.add(types.InlineKeyboardButton(text="3. 🥩 Халяль", callback_data="st:halal"))
    b.add(types.InlineKeyboardButton(text="4. ⚠️ Диетические столы", callback_data="st:dietetic"))
    b.add(types.InlineKeyboardButton(text="5. 🚫 Аллергии", callback_data="st:allergies"))
    b.add(types.InlineKeyboardButton(text="6. 🏋️ ЗОЖ и фитнес", callback_data="st:fitness"))
    b.add(types.InlineKeyboardButton(text="7. ⏱ Макс. время", callback_data="st:time"))
    b.add(types.InlineKeyboardButton(text="8. 🍳 Тип блюда", callback_data="st:dishtype"))
    b.add(types.InlineKeyboardButton(text="9. 🍲 Способ приготовления", callback_data="st:cookpref"))
    b.add(types.InlineKeyboardButton(text="10. 💰 Сложность и бюджет", callback_data="st:diffbud"))
    b.add(types.InlineKeyboardButton(text="🔙 Назад", callback_data="st:done"))
    b.adjust(1)
    return b.as_markup()


def settings_done_kb():
    b = InlineKeyboardBuilder()
    b.add(types.InlineKeyboardButton(text="🥕 Внести продукты", callback_data="add_products"))
    b.add(types.InlineKeyboardButton(text="🔙 Вернуться к настройкам", callback_data="st:root"))
    b.add(types.InlineKeyboardButton(text="🏠 В главное меню", callback_data="main_menu"))
    b.adjust(1)
    return b.as_markup()


def no_results_kb(ctx: str):
    b = InlineKeyboardBuilder()
    b.add(types.InlineKeyboardButton(text="➕ Добавить продукты", callback_data="add_products"))
    b.add(types.InlineKeyboardButton(text="🔍 Изменить запрос", callback_data="pr:retry"))
    b.add(types.InlineKeyboardButton(text="⚙️ Настроить рецепт", callback_data=f"set_from:{ctx}"))
    b.add(types.InlineKeyboardButton(text="🔙 Назад в меню", callback_data="main_menu"))
    b.adjust(1)
    return b.as_markup()


def invite_kb(referral_deep_link: str, share_text: str = "") -> types.InlineKeyboardMarkup:
    """Кнопка открывает t.me/share/url — нативный выбор чата для отправки ссылки."""
    q_url = quote(referral_deep_link, safe="")
    if share_text.strip():
        share_url = f"https://t.me/share/url?url={q_url}&text={quote(share_text.strip(), safe='')}"
    else:
        share_url = f"https://t.me/share/url?url={q_url}"
    b = InlineKeyboardBuilder()
    b.add(types.InlineKeyboardButton(text="Поделиться ссылкой", url=share_url))
    b.add(types.InlineKeyboardButton(text="🔙 Назад в кабинет", callback_data="cabinet"))
    b.adjust(1)
    return b.as_markup()
