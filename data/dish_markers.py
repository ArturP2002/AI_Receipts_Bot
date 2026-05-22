"""Единые эвристики «название блюда» для подбора рецептов."""

from __future__ import annotations

import re

# Известные однословные названия блюд (не продукты в списке).
DISH_NAME_SINGLE_WORD = frozenset(
    {
        "сациви",
        "чахохбили",
        "хачапури",
        "хинкали",
        "харчо",
        "борщ",
        "щи",
        "солянка",
        "окрошка",
        "гуляш",
        "гуляшь",
        "плов",
        "лазанья",
        "карбонара",
        "рататуй",
        "тапас",
        "паэлья",
        "ризотто",
        "гаспачо",
        "тартар",
        "тирамису",
        "наполеон",
        "профитроли",
        "оливье",
        "винегрет",
        "блины",
        "блинчики",
        "пельмени",
        "вареники",
        "голубцы",
        "котлеты",
        "бефстроганов",
        "стейк",
        "шашлык",
        "шаурма",
        "пицца",
        "бургер",
        "чизбургер",
        "фо",
        "рамен",
        "суши",
        "роллы",
        "мохито",
        "кимчи",
        "таджин",
        "фалафель",
        "хумус",
        "гуляш",
    }
)

# Один токен чаще продукт, а не название готового блюда.
SINGLE_INGREDIENT_HINT = frozenset(
    {
        "курица",
        "курицу",
        "говядина",
        "свинина",
        "индейка",
        "утка",
        "баранина",
        "рыба",
        "лосось",
        "треска",
        "яйца",
        "яйцо",
        "рис",
        "гречка",
        "макароны",
        "паста",
        "картошка",
        "картофель",
        "помидоры",
        "помидор",
        "огурцы",
        "лук",
        "чеснок",
        "сыр",
        "творог",
        "молоко",
        "сливки",
        "сметана",
        "грибы",
        "кабачок",
        "баклажан",
        "перец",
        "морковь",
        "капуста",
        "фарш",
        "тофу",
    }
)


def is_known_dish_token(word: str) -> bool:
    w = (word or "").strip().lower()
    return bool(w) and w in DISH_NAME_SINGLE_WORD


def looks_like_dish_query_text(text: str) -> bool:
    """Текст похож на название блюда, а не на список продуктов."""
    t = (text or "").strip().lower()
    if not t:
        return False
    if re.search(r"\bпо[-\s]", t):
        return True
    for w in re.split(r"[\s,]+", t):
        w = w.strip().lower()
        if is_known_dish_token(w):
            return True
    return False


def terms_look_like_dish_name_only(terms: list[str]) -> bool:
    if len(terms) != 1:
        return False
    w = terms[0].strip().lower()
    if len(w) < 4:
        return False
    if w in SINGLE_INGREDIENT_HINT:
        return False
    if w in DISH_NAME_SINGLE_WORD:
        return True
    if len(w) >= 10:
        return True
    return False
