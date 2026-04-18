import json
import re
from typing import Any

from data.cuisine_catalog import favorite_entries_match_norms
from database import Recipe, UsersData
from enums import CookMethod, DishType
from settings_catalog import ALLERGY_CATALOG_KEYS, ALLERGY_CUSTOM_TYPE, DEFAULT_DIET_PROFILE


def _norm(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _parse_json_list(raw: str) -> list[str]:
    try:
        v = json.loads(raw or "[]")
        return v if isinstance(v, list) else []
    except json.JSONDecodeError:
        return []


def _allergies_mixed_list(raw: str) -> list:
    try:
        v = json.loads(raw or "[]")
        return v if isinstance(v, list) else []
    except json.JSONDecodeError:
        return []


def _diet_profile_dict(user: UsersData) -> dict[str, Any]:
    try:
        d = json.loads(getattr(user, "diet_profile_json", None) or "{}")
    except json.JSONDecodeError:
        d = {}
    if not isinstance(d, dict):
        d = {}
    out = {**DEFAULT_DIET_PROFILE, **d}
    mode = out.get("mode", "omnivore")
    zoj = _parse_json_list(user.zoj_prefs_json)
    if mode == "omnivore":
        if "vegan" in zoj:
            mode = "vegan"
        elif "vegetarian" in zoj:
            mode = "vegetarian"
        out["mode"] = mode
    if mode == "vegan":
        out["no_eggs"] = True
        out["no_dairy"] = True
    return out


def recipe_ingredients_list(r: Recipe) -> list[str]:
    return [_norm(x) for x in _parse_json_list(r.ingredients_json)]


def _ingredient_matches_any_term(ingredient: str, terms: list[str]) -> bool:
    ing = _norm(ingredient)
    if not ing:
        return False
    for term in terms:
        t = _norm(term)
        if not t:
            continue
        if t in ing or ing in t:
            return True
    return False


def _ingredients_within_terms(ingredients: list[str], terms: list[str]) -> bool:
    if not ingredients or not terms:
        return False
    return all(_ingredient_matches_any_term(ing, terms) for ing in ingredients)


def recipe_restrictions(r: Recipe) -> set[str]:
    return set(_norm(x) for x in _parse_json_list(r.restrictions_json))


def recipe_tags(r: Recipe) -> set[str]:
    return set(_norm(x) for x in _parse_json_list(r.tags_json))


def _recipe_blob(r: Recipe) -> str:
    ing_text = " ".join(recipe_ingredients_list(r))
    tags = " ".join(recipe_tags(r))
    rest_text = " ".join(_parse_json_list(r.restrictions_json)).lower()
    title = _norm(r.title)
    return f"{ing_text} {tags} {rest_text} {title}"


def _recipe_method_blob(r: Recipe) -> str:
    steps = " ".join(_norm(str(x)) for x in _parse_json_list(r.steps_json))
    desc = _norm(r.short_description or "")
    title = _norm(r.title or "")
    return f"{title} {desc} {steps}"


_METHOD_REQUIRED_TOKENS: dict[str, list[str]] = {
    CookMethod.BOIL.value: ["вар", "кипят"],
    CookMethod.FRY.value: ["жар", "обжар", "сковород"],
    CookMethod.BAKE.value: ["духов", "запек", "противн"],
    CookMethod.STEW.value: ["туш"],
    CookMethod.STEAM.value: ["пар"],
    CookMethod.GRILL.value: ["грил"],
    CookMethod.DEEP_FRY.value: ["фритюр"],
    CookMethod.BBQ.value: ["мангал", "угл"],
    CookMethod.RAW.value: ["без термич", "сыро"],
}

_METHOD_CONFLICT_TOKENS: dict[str, list[str]] = {
    CookMethod.BOIL.value: ["жар", "сковород", "духов", "запек", "туш", "грил", "фритюр", "мангал"],
    CookMethod.FRY.value: ["духов", "запек", "туш", "вар", "кипят", "пар", "грил", "фритюр", "мангал"],
    CookMethod.BAKE.value: ["жар", "сковород", "туш", "вар", "кипят", "пар", "грил", "фритюр", "мангал"],
    CookMethod.STEW.value: ["жар", "сковород", "духов", "запек", "вар", "кипят", "пар", "грил", "фритюр", "мангал"],
    CookMethod.STEAM.value: ["жар", "сковород", "духов", "запек", "туш", "вар", "кипят", "грил", "фритюр", "мангал"],
    CookMethod.GRILL.value: ["жар", "сковород", "духов", "запек", "туш", "вар", "кипят", "пар", "фритюр", "мангал"],
    CookMethod.DEEP_FRY.value: ["жар", "сковород", "духов", "запек", "туш", "вар", "кипят", "пар", "грил", "мангал"],
    CookMethod.BBQ.value: ["жар", "сковород", "духов", "запек", "туш", "вар", "кипят", "пар", "грил", "фритюр"],
    CookMethod.RAW.value: ["жар", "сковород", "духов", "запек", "туш", "вар", "кипят", "пар", "грил", "фритюр", "мангал"],
}


def _method_matches_requested(r: Recipe, cook_method: str | None) -> bool:
    if not cook_method or cook_method == CookMethod.OTHER.value:
        return True
    text = _recipe_method_blob(r)
    required = _METHOD_REQUIRED_TOKENS.get(cook_method, [])
    conflicts = _METHOD_CONFLICT_TOKENS.get(cook_method, [])
    if required and not any(t in text for t in required):
        return False
    if any(t in text for t in conflicts):
        return False
    return True


def passes_hard_filters(r: Recipe, user: UsersData) -> bool:
    blob = _recipe_blob(r)
    tags = recipe_tags(r)

    allergy_needles = {
        "nuts": {"nuts", "орех"},
        "seafood": {"seafood", "морепродукт", "креветк", "кальмар", "миди", "устриц"},
        "eggs": {"egg", "яйц"},
        "gluten": {"gluten", "глютен", "пшениц", "мук", "ржан"},
        "lactose": {"lactose", "молок", "сыр", "сливк", "творог", "йогурт"},
        "citrus": {"цитрус", "лимон", "лайм", "апельсин", "грейпфрут"},
        "tomatoes": {"томат", "помидор"},
        "spicy": {"остр", "чили", "перец чили", "кайенн"},
        "mushrooms": {"гриб", "шампиньон", "белы гриб"},
        "sour": {"кисл"},  # legacy ключ
        "орехи": {"nuts", "орех"},
        "морепродукты": {"seafood", "морепродукт"},
    }

    allergy_items = _allergies_mixed_list(user.allergies_strict_json)
    fitness = set(_parse_json_list(getattr(user, "fitness_prefs_json", None)))
    catalog_allergies = [
        x
        for x in allergy_items
        if isinstance(x, str) and x != "other" and x in ALLERGY_CATALOG_KEYS
    ]
    if "gluten_free" in fitness:
        catalog_allergies = list(dict.fromkeys(catalog_allergies + ["gluten"]))

    for al in catalog_allergies:
        key = _norm(al)
        needles = allergy_needles.get(key)
        if needles is None:
            for needles2 in allergy_needles.values():
                if key in needles2:
                    needles = needles2
                    break
        if not needles:
            continue
        for n in needles:
            if n in blob:
                return False

    for item in allergy_items:
        if not isinstance(item, dict) or item.get("type") != ALLERGY_CUSTOM_TYPE:
            continue
        lab = (item.get("l") or "").strip()
        if not lab:
            continue
        custom_needles = [_norm(lab)]
        for w in re.split(r"[\s,;]+", lab):
            wn = _norm(w)
            if len(wn) >= 2:
                custom_needles.append(wn)
        for n in dict.fromkeys(custom_needles):
            if n and n in blob:
                return False

    dp = _diet_profile_dict(user)
    mode = dp.get("mode", "omnivore")
    no_eggs = dp.get("no_eggs", False)
    no_dairy = dp.get("no_dairy", False)

    if mode == "vegan":
        if not ("vegan" in tags or "веган" in blob):
            if any(x in blob for x in ["мясо", "куриц", "говядин", "свинин", "индейк", "утк", "рыба", "лосос", "треск", "кревет", "молок", "сыр", "сливк", "яйц", "творог", "мёд"]):
                return False
    elif mode == "vegetarian":
        if any(x in blob for x in ["мясо", "куриц", "говядин", "свинин", "индейк", "утк", "рыба", "лосос", "треск", "кревет", "кальмар"]):
            return False
    elif mode == "pescatarian":
        if any(x in blob for x in ["мясо", "куриц", "говядин", "свинин", "индейк", "утк"]):
            return False
    if no_eggs and any(x in blob for x in ["яйц", "омлет", "айоли"]):
        return False
    if no_dairy and any(x in blob for x in ["молок", "сыр", "сливк", "творог", "йогурт", "сметан", "масло слив"]):
        return False

    if getattr(user, "halal_only", False):
        haram = (
            "свинин",
            "бекон",
            "ветчин",
            "шпик",
            "сало",
            "колбас",
            "пиво",
            "вино",
            "коньяк",
            "ром ",
            "водка",
            "шампанск",
            "ликёр",
        )
        if any(h in blob for h in haram):
            return False

    allowed_diff = _parse_json_list(getattr(user, "allowed_difficulties_json", None))
    if allowed_diff and r.difficulty not in allowed_diff:
        return False

    if "no_fried" in fitness:
        if r.cook_method in (CookMethod.FRY.value, CookMethod.DEEP_FRY.value):
            return False

    if user.max_time_minutes and user.time_strict:
        if r.time_minutes > user.max_time_minutes:
            return False

    return True


def soft_score(r: Recipe, user: UsersData) -> int:
    fav_tokens = favorite_entries_match_norms(user.favorite_cuisines_json)
    dish_pref = set(_norm(x) for x in _parse_json_list(user.dish_types_pref_json))
    fitness = set(_parse_json_list(getattr(user, "fitness_prefs_json", None)))
    zoj_legacy = _parse_json_list(user.zoj_prefs_json)
    for z in zoj_legacy:
        fitness.add(z)

    score = r.popularity
    c = _norm(r.cuisine)
    if fav_tokens and any(f in c or c in f for f in fav_tokens):
        score += 50
    if user.max_time_minutes and not user.time_strict:
        if r.time_minutes <= user.max_time_minutes:
            score += 20
    if dish_pref and r.dish_type in dish_pref:
        score += 15

    tags = recipe_tags(r)
    blob = _recipe_blob(r)

    pref_methods = _parse_json_list(getattr(user, "preferred_cook_methods_json", None))
    if pref_methods and r.cook_method in pref_methods:
        score += 25

    for key in ("low_cal", "high_protein", "no_sugar", "keto", "paleo"):
        if key in fitness and key in tags:
            score += 12

    tables = _parse_json_list(getattr(user, "dietetic_tables_json", None))
    for t in tables:
        tn = _norm(t)
        if f"table_{tn}" in tags or f"dt_{tn}" in tags or tn in tags:
            score += 18

    bt = getattr(user, "budget_tier", None) or ""
    if bt and bt != "any":
        if f"budget_{bt}" in tags:
            score += 15

    return score


# Слишком общие односложные запросы — просим уточнить кухню/время/тип (ТЗ 3.7).
_GENERIC_DISH_WORDS = frozenset(
    {
        "мясо",
        "рыба",
        "курица",
        "суп",
        "салат",
        "гарнир",
        "закуска",
        "десерт",
        "еда",
        "блюдо",
        "рис",
        "крупа",
        "овощи",
        "овощ",
        "фрукт",
        "фрукты",
        "напиток",
        "второе",
    }
)


def is_query_too_vague_for_dish_search(text: str) -> bool:
    """Один короткий токен без конкретики — лучше уточнить в настройках."""
    t = _norm(text)
    if not t:
        return True
    words = [w for w in re.split(r"[\s,.;:!?]+", t) if w]
    if len(words) >= 2:
        return False
    w = words[0]
    if len(w) <= 3:
        return True
    if w in _GENERIC_DISH_WORDS:
        return True
    return False


def search_by_dish_query(user: UsersData, query: str) -> list[Recipe]:
    """Подбор по названию/описанию блюда (без списка продуктов и способа приготовления)."""
    qn = _norm(query)
    if not qn:
        return []
    q_words = [w for w in qn.split() if len(w) >= 2]
    if not q_words:
        return []
    q = Recipe.select().where(Recipe.is_published == True)  # noqa: E712
    out: list[tuple[int, Recipe]] = []
    for r in q:
        if not passes_hard_filters(r, user):
            continue
        title = _norm(r.title or "")
        desc = _norm(r.short_description or "")
        score = 0
        if qn in title:
            score += 600
        elif all(w in title for w in q_words if len(w) >= 3):
            score += 450
        else:
            matched = 0
            for w in q_words:
                if len(w) < 3:
                    continue
                if w in title or w in desc:
                    matched += 1
            if matched == 0:
                continue
            score += matched * 120
            if matched >= len([w for w in q_words if len(w) >= 3]):
                score += 80
        score += soft_score(r, user)
        out.append((score, r))
    out.sort(key=lambda x: -x[0])
    return [r for _, r in out]


def search_by_products_and_method(
    user: UsersData,
    product_terms: list[str],
    cook_method: str | None,
    *,
    cuisine_key: str | None = None,
) -> list[Recipe]:
    terms = [_norm(t) for t in product_terms if t.strip()]
    q = Recipe.select().where(Recipe.is_published == True)  # noqa: E712
    if cook_method:
        q = q.where(Recipe.cook_method == cook_method)
    if cuisine_key:
        q = q.where(Recipe.cuisine == cuisine_key)
    candidates = list(q)
    out: list[tuple[int, Recipe]] = []
    for r in candidates:
        if not passes_hard_filters(r, user):
            continue
        if not _method_matches_requested(r, cook_method):
            continue
        ings = recipe_ingredients_list(r)
        if not _ingredients_within_terms(ings, terms):
            continue
        rank = len(terms) * 100 + soft_score(r, user)
        out.append((rank, r))
    out.sort(key=lambda x: -x[0])
    return [r for _, r in out]


def search_by_cuisine(
    user: UsersData,
    cuisine_key: str,
    *,
    dish_type: str | None = None,
    time_bucket: str | None = None,
    popular_only: bool = False,
) -> list[Recipe]:
    q = Recipe.select().where(
        (Recipe.is_published == True) & (Recipe.cuisine == cuisine_key)  # noqa: E712
    )
    if dish_type:
        q = q.where(Recipe.dish_type == dish_type)
    if time_bucket == "fast":
        q = q.where(Recipe.time_minutes <= 15)
    elif time_bucket == "medium":
        q = q.where((Recipe.time_minutes > 15) & (Recipe.time_minutes <= 45))
    elif time_bucket == "long":
        q = q.where(Recipe.time_minutes > 45)
    candidates = list(q)
    out: list[tuple[int, Recipe]] = []
    for r in candidates:
        if not passes_hard_filters(r, user):
            continue
        sc = soft_score(r, user)
        if popular_only:
            sc += r.popularity * 2
        out.append((sc, r))
    out.sort(key=lambda x: -x[0])
    return [r for _, r in out]


def suggest_similar_if_empty(
    user: UsersData,
    cuisine_key: str | None,
) -> list[Recipe]:
    q = Recipe.select().where(Recipe.is_published == True)  # noqa: E712
    if cuisine_key:
        q = q.where(Recipe.cuisine == cuisine_key)
    out = []
    for r in q:
        if passes_hard_filters(r, user):
            out.append((soft_score(r, user), r))
    out.sort(key=lambda x: -x[0])
    return [r for _, r in out[:12]]
