"""Генерация рецептов и иллюстраций через OpenAI (заменяемый слой над services/openai_ai.py)."""

from __future__ import annotations

import asyncio
import html
import json
import logging
import re
from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx
from data.cuisine_catalog import (
    cuisine_display_ru_for_recipe,
    first_favorite_cuisine_slug,
    parse_favorite_cuisines_list,
    summary_labels_favorites,
)
from database import Recipe, UsersData, db
from enums import DISH_TYPE_LABEL_RU, CookMethod, Difficulty, DishType, cook_method_label_ru
import config
from services import openai_ai
from settings_catalog import (
    ALLERGY_CATALOG_KEYS,
    ALLERGY_CUSTOM_TYPE,
    ALLERGY_OPTIONS,
    BUDGET_OPTIONS,
    DEFAULT_DIET_PROFILE,
    DIETETIC_TABLES,
    FITNESS_OPTIONS,
)

logger = logging.getLogger(__name__)

RECIPE_IMAGES_DIR = Path(__file__).resolve().parent.parent / "data" / "recipe_images"

_CYRILLIC = re.compile(r"[А-Яа-яЁё]")


def _has_cyrillic(s: str) -> bool:
    return bool(_CYRILLIC.search(s))


async def _ensure_russian_line(text: str, *, what: str) -> str:
    t = (text or "").strip()
    if not t or _has_cyrillic(t):
        return t[:500]
    out = await openai_ai.complete_text(
        f"Переведи на русский ({what}). Только перевод, без кавычек и пояснений, не длиннее 200 символов.",
        t,
        max_tokens=100,
    )
    cleaned = (out or t).strip()
    return (cleaned if _has_cyrillic(cleaned) else t)[:500]


def _json_list(raw: str) -> list:
    try:
        v = json.loads(raw or "[]")
        return v if isinstance(v, list) else []
    except json.JSONDecodeError:
        return []


def _json_list_strs(raw: str) -> list[str]:
    return [str(x).strip() for x in _json_list(raw) if isinstance(x, str) and str(x).strip()]


_DIETETIC_LABEL_RU = dict(DIETETIC_TABLES)
_FITNESS_LABEL_RU = dict(FITNESS_OPTIONS)
_BUDGET_LABEL_RU = dict(BUDGET_OPTIONS)
_VALID_DISH_TYPES = {d.value for d in DishType}
_VALID_COOK_METHODS = {m.value for m in CookMethod}
_VALID_DIFFICULTIES = {d.value for d in Difficulty}


def _diet_profile_merged(user: UsersData) -> dict:
    try:
        d = json.loads(getattr(user, "diet_profile_json", None) or "{}")
    except json.JSONDecodeError:
        d = {}
    if not isinstance(d, dict):
        d = {}
    out = {**DEFAULT_DIET_PROFILE, **d}
    mode = out.get("mode", "omnivore")
    zoj = _json_list_strs(user.zoj_prefs_json)
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


def _catalog_allergy_keys(raw: str) -> set[str]:
    keys: set[str] = set()
    for x in _json_list(raw):
        if isinstance(x, str) and x in ALLERGY_CATALOG_KEYS:
            keys.add(x)
    return keys


def _norm_difficulty(raw: str) -> str:
    x = (raw or "").strip().lower()
    if x in (d.value for d in Difficulty):
        return x
    return Difficulty.MEDIUM.value


def _norm_dish_type(raw: str) -> str:
    x = (raw or "").strip().lower()
    if x in (d.value for d in DishType):
        return x
    return DishType.LUNCH.value


def _norm_cook_method(raw: str | None) -> str:
    x = (raw or "").strip().lower()
    if x in (m.value for m in CookMethod):
        return x
    return CookMethod.FRY.value


def _safe_calories(v) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _cuisine_slug(user: UsersData) -> str:
    return first_favorite_cuisine_slug(user.favorite_cuisines_json)


def _allergy_labels_for_prompt(raw: str) -> list[str]:
    label_by_key = dict(ALLERGY_OPTIONS)
    out: list[str] = []
    for x in _json_list(raw):
        if isinstance(x, str) and x != "other" and x in ALLERGY_CATALOG_KEYS:
            out.append(label_by_key.get(x, x))
        elif isinstance(x, dict) and x.get("type") == ALLERGY_CUSTOM_TYPE:
            lab = x.get("l")
            if isinstance(lab, str) and lab.strip():
                out.append(lab.strip())
    return out


def _norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _allergy_needles_map() -> dict[str, set[str]]:
    return {
        "nuts": {"nuts", "орех", "грец", "фундук", "арахис", "миндал"},
        "seafood": {"seafood", "морепродукт", "креветк", "кальмар", "миди", "устриц"},
        "eggs": {"egg", "яйц", "омлет"},
        "gluten": {"gluten", "глютен", "пшениц", "мук", "ржан", "ячмен"},
        "lactose": {"lactose", "молок", "сыр", "сливк", "творог", "йогурт", "сметан"},
        "citrus": {"цитрус", "лимон", "лайм", "апельсин", "грейпфрут"},
        "tomatoes": {"томат", "помидор"},
        "spicy": {"остр", "чили", "кайенн", "халапеньо"},
        "mushrooms": {"гриб", "шампиньон", "вешенк", "лисич"},
    }


def _item_blob(item: dict) -> str:
    parts: list[str] = []
    for k in ("title", "short_description"):
        v = item.get(k)
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())
    for k in ("ingredients", "tags", "restrictions"):
        v = item.get(k)
        if isinstance(v, list):
            parts.extend(str(x) for x in v if str(x).strip())
    return _norm_text(" ".join(parts))


def _catalog_allergy_keys_from_user(user: UsersData) -> set[str]:
    keys: set[str] = set()
    for x in _json_list(user.allergies_strict_json):
        if isinstance(x, str) and x in ALLERGY_CATALOG_KEYS:
            keys.add(x)
    return keys


def _custom_allergy_labels_from_user(user: UsersData) -> list[str]:
    out: list[str] = []
    for x in _json_list(user.allergies_strict_json):
        if isinstance(x, dict) and x.get("type") == ALLERGY_CUSTOM_TYPE:
            lab = str(x.get("l") or "").strip()
            if lab:
                out.append(lab)
    return out


def _item_passes_user_hard_constraints(
    item: dict,
    user: UsersData,
    *,
    force_cook_method: str | None = None,
    force_dish_type: str | None = None,
    force_time_bucket: str | None = None,
) -> tuple[bool, str]:
    blob = _item_blob(item)
    needles_map = _allergy_needles_map()
    allergy_keys = _catalog_allergy_keys_from_user(user)
    fitness = set(_json_list_strs(user.fitness_prefs_json))
    if "gluten_free" in fitness:
        allergy_keys.add("gluten")

    for key in allergy_keys:
        for n in needles_map.get(key, set()):
            if n in blob:
                return False, f"allergy:{key}"

    for lab in _custom_allergy_labels_from_user(user):
        checks = [_norm_text(lab)]
        checks.extend(_norm_text(w) for w in re.split(r"[\s,;]+", lab) if len(_norm_text(w)) >= 2)
        for n in dict.fromkeys(checks):
            if n and n in blob:
                return False, f"custom_allergy:{lab}"

    dp = _diet_profile_merged(user)
    mode = dp.get("mode", "omnivore")
    if mode == "vegan" and any(
        x in blob
        for x in (
            "мясо",
            "куриц",
            "говядин",
            "свинин",
            "индейк",
            "утк",
            "рыба",
            "лосос",
            "треск",
            "кревет",
            "молок",
            "сыр",
            "сливк",
            "яйц",
            "творог",
            "мёд",
        )
    ):
        return False, "diet:vegan"
    if mode == "vegetarian" and any(
        x in blob for x in ("мясо", "куриц", "говядин", "свинин", "индейк", "утк", "рыба", "лосос", "треск", "кревет")
    ):
        return False, "diet:vegetarian"
    if mode == "pescatarian" and any(x in blob for x in ("мясо", "куриц", "говядин", "свинин", "индейк", "утк")):
        return False, "diet:pescatarian"
    if dp.get("no_eggs") and any(x in blob for x in ("яйц", "омлет", "айоли")):
        return False, "diet:no_eggs"
    if dp.get("no_dairy") and any(x in blob for x in ("молок", "сыр", "сливк", "творог", "йогурт", "сметан", "масло слив")):
        return False, "diet:no_dairy"

    if getattr(user, "halal_only", False) and any(
        x in blob
        for x in ("свинин", "бекон", "ветчин", "шпик", "сало", "колбас", "пиво", "вино", "коньяк", "ром ", "водка")
    ):
        return False, "halal"

    cm = _norm_cook_method(str(item.get("cook_method") or force_cook_method or CookMethod.FRY.value))
    if force_cook_method and cm != force_cook_method:
        return False, "forced_method"
    if "no_fried" in fitness and cm in (CookMethod.FRY.value, CookMethod.DEEP_FRY.value):
        return False, "fitness:no_fried"
    if force_cook_method and not _matches_cook_method(item, force_cook_method):
        return False, "method_conflict"

    allowed_diff = [x for x in _json_list_strs(user.allowed_difficulties_json) if x in _VALID_DIFFICULTIES]
    diff = _norm_difficulty(str(item.get("difficulty") or ""))
    if allowed_diff and diff not in allowed_diff:
        return False, "difficulty"

    dish_type = _norm_dish_type(str(item.get("dish_type") or ""))
    if force_dish_type and dish_type != force_dish_type:
        return False, "forced_dish_type"
    if force_time_bucket == "fast":
        if int(item.get("time_minutes") or 0) > 15:
            return False, "time_bucket"
    elif force_time_bucket == "medium":
        tm = int(item.get("time_minutes") or 0)
        if tm <= 15 or tm > 45:
            return False, "time_bucket"
    elif force_time_bucket == "long":
        if int(item.get("time_minutes") or 0) <= 45:
            return False, "time_bucket"

    if user.max_time_minutes and user.time_strict:
        if int(item.get("time_minutes") or 0) > user.max_time_minutes:
            return False, "max_time_strict"

    return True, ""


def _apply_user_constraints_filter(
    items: list[dict],
    user: UsersData,
    *,
    force_cook_method: str | None = None,
    force_dish_type: str | None = None,
    force_time_bucket: str | None = None,
) -> tuple[list[dict], list[str]]:
    ok: list[dict] = []
    violations: list[str] = []
    for idx, item in enumerate(items, start=1):
        passed, reason = _item_passes_user_hard_constraints(
            item,
            user,
            force_cook_method=force_cook_method,
            force_dish_type=force_dish_type,
            force_time_bucket=force_time_bucket,
        )
        if passed:
            ok.append(item)
        else:
            violations.append(f"recipe#{idx}:{reason}")
    return ok, violations


def _user_constraints_block(
    user: UsersData,
    *,
    omit_dish_type_prefs: bool = False,
    omit_preferred_cook_methods: bool = False,
    force_cook_method: str | None = None,
) -> str:
    """Все детальные настройки пользователя для промпта (согласовано с логикой services/search.py)."""
    must: list[str] = []
    pref: list[str] = []

    allergies = _allergy_labels_for_prompt(user.allergies_strict_json)
    if allergies:
        must.append("Не использовать и не предлагать блюда с: " + ", ".join(allergies) + ".")

    if getattr(user, "halal_only", False):
        must.append("Только халяль: без свинины и без алкоголя в блюде и соусах.")

    dp = _diet_profile_merged(user)
    mode = dp.get("mode", "omnivore")
    if mode == "vegan":
        must.append(
            "Только веганские рецепты: без мяса, рыбы, морепродуктов, яиц, мёда, молочных продуктов."
        )
    elif mode == "vegetarian":
        must.append("Только вегетарианские рецепты: без мяса, рыбы и морепродуктов.")
    elif mode == "pescatarian":
        must.append("Пескетарианство: рыба и морепродукты допустимы; без мяса птицы и млекопитающих.")
    if dp.get("no_eggs"):
        must.append("Без яиц и яичных продуктов.")
    if dp.get("no_dairy"):
        must.append("Без молока, сыра, сливок, творога, йогурта, сметаны и сливочного масла.")

    allergy_keys = _catalog_allergy_keys(user.allergies_strict_json)
    fitness = set(_json_list_strs(user.fitness_prefs_json))
    for z in _json_list_strs(user.zoj_prefs_json):
        fitness.add(z)

    if "gluten_free" in fitness and "gluten" not in allergy_keys:
        must.append(
            "Без глютена: не использовать пшеницу, рожь, ячмень как основу; в restrictions при необходимости укажи gluten."
        )
    if "no_fried" in fitness:
        fcm = (force_cook_method or "").strip().lower()
        if fcm not in (CookMethod.FRY.value, CookMethod.DEEP_FRY.value):
            must.append(
                "Без сильной жарки: не используй обжарку в большом количестве масла; "
                "cook_method не fry и не deep_fry."
            )

    if user.max_time_minutes:
        if user.time_strict:
            must.append(
                f"Время приготовления каждого рецепта (time_minutes) строго не больше {user.max_time_minutes}."
            )
        else:
            must.append(
                f"Желательно уложиться в {user.max_time_minutes} минут (time_minutes); "
                "больше — только если без этого нельзя приготовить блюдо."
            )

    allowed_diff = [x for x in _json_list_strs(user.allowed_difficulties_json) if x in _VALID_DIFFICULTIES]
    if allowed_diff:
        must.append(
            f"Поле difficulty у каждого рецепта только одно из: {', '.join(allowed_diff)}."
        )

    fav_raw = parse_favorite_cuisines_list(user.favorite_cuisines_json)
    fav_line = summary_labels_favorites(fav_raw)
    if fav_line and fav_line != "—":
        pref.append(f"Любимые кухни (ориентир по вкусу): {fav_line}.")

    if not omit_dish_type_prefs:
        dish_pref = [d for d in _json_list_strs(user.dish_types_pref_json) if d in _VALID_DISH_TYPES]
        if dish_pref:
            try:
                ru = [DISH_TYPE_LABEL_RU[DishType(d)] for d in dish_pref]
            except ValueError:
                ru = dish_pref
            pref.append(
                f"Предпочтительные типы блюд — поле dish_type только из: {', '.join(dish_pref)} "
                f"({', '.join(ru)})."
            )

    if not omit_preferred_cook_methods:
        pcm = [x for x in _json_list_strs(user.preferred_cook_methods_json) if x in _VALID_COOK_METHODS]
        if pcm:
            ru_m = [cook_method_label_ru(x) for x in pcm]
            pref.append(
                "Предпочитаемые способы приготовления (ориентир для cook_method): "
                f"{', '.join(ru_m)} (коды: {', '.join(pcm)})."
            )

    dietetic = _json_list_strs(user.dietetic_tables_json)
    if dietetic:
        labs = [_DIETETIC_LABEL_RU.get(k, k) for k in dietetic]
        pref.append(
            "Диетические столы (щадящий рацион): "
            + "; ".join(labs)
            + ". Если блюдо подходит под стол, добавь в tags метку table_<ключ> или dt_<ключ> "
            "(например table_t1 для ключа t1)."
        )

    fit_keys = [k for k in sorted(fitness) if k in _FITNESS_LABEL_RU]
    if fit_keys:
        labs = [_FITNESS_LABEL_RU[k] for k in fit_keys]
        pref.append(
            "ЗОЖ/фитнес: "
            + ", ".join(labs)
            + ". Отрази в массиве tags соответствующими англ. ключами: "
            + ", ".join(fit_keys)
            + "."
        )

    zoj_extra = [z for z in _json_list_strs(user.zoj_prefs_json) if z not in ("vegan", "vegetarian")]
    if zoj_extra:
        pref.append("Доп. пожелания по питанию: " + ", ".join(zoj_extra) + ".")

    bt = getattr(user, "budget_tier", None) or ""
    if bt and bt != "any":
        pref.append(
            f"Ориентир по бюджету продуктов: {_BUDGET_LABEL_RU.get(bt, bt)}. "
            f"Добавь в tags метку budget_{bt}."
        )

    parts: list[str] = []
    if must:
        parts.append("Обязательно:\n" + "\n".join(f"- {m}" for m in must))
    if pref:
        parts.append("Желательно учитывать:\n" + "\n".join(f"- {p}" for p in pref))

    if not parts:
        return "(особых ограничений нет)"
    return "\n\n".join(parts)


_CANONICAL_TITLE_RULES = """Название блюда (title) — обязательно каноничное и привычное для русскоязычного читателя:
- Если это узнаваемое блюдо — используй устоявшееся имя (например «Спагетти карбонара» или «Паста карбонара», а не «макароны с беконом и сыром»).
- Для классики национальных кухонь — принятое русское название («Сациви из курицы», «Харчо», «Борщ»), а не нейтральное «суп с мясом».
- Не заменяй каноническое имя обобщённым описанием состава или способа, если в культуре закреплено именно это название.
- Кратко, по-русски, без кальки и без английских слов в title."""


async def _refine_recipe_titles_with_llm(items: list[dict]) -> None:
    """Один вызов ИИ: унифицировать названия по всему списку (каноничность, любая кухня/тип блюда)."""
    if not getattr(config, "OPENAI_CANONICALIZE_TITLES", True) or not config.OPENAI_API_KEY:
        return
    clean: list[dict] = [x for x in items if isinstance(x, dict)]
    if not clean:
        return
    lines: list[str] = []
    for i, it in enumerate(clean, start=1):
        t = str(it.get("title") or "").strip()
        d = str(it.get("short_description") or "").strip()[:180]
        ing = it.get("ingredients") or []
        if isinstance(ing, list):
            ing_s = ", ".join(str(x) for x in ing[:12])[:240]
        else:
            ing_s = ""
        lines.append(f"{i}. title: «{t}»\n   кратко: {d}\n   ингредиенты: {ing_s}")
    user_block = "Приведи title каждого пункта к каноничному названию (см. правила в system).\n\n" + "\n\n".join(lines)
    sys_p = (
        "Ты редактор названий блюд. Верни строго JSON-объект с ключом \"titles\": массив строк — "
        "ровно столько элементов, сколько пронумерованных пунктов в запросе пользователя, порядок тот же.\n"
        "Каждая строка — одно финальное название блюда на русском (кириллица), до 80 символов, без кавычек.\n"
        f"{_CANONICAL_TITLE_RULES}"
    )
    try:
        data = await openai_ai.chat_json_object(
            sys_p,
            user_block,
            max_tokens=700,
            temperature=0.2,
        )
    except Exception as exc:
        logger.warning("canonical title refine: %s", exc)
        return
    raw_titles = data.get("titles")
    if not isinstance(raw_titles, list) or len(raw_titles) != len(clean):
        return
    for it, new_t in zip(clean, raw_titles):
        if isinstance(new_t, str) and new_t.strip():
            it["title"] = new_t.strip()[:255]


def _system_prompt(n: int) -> str:
    return f"""Ты помощник по кулинарии. Пользователь пишет по-русски.
Верни строго один JSON-объект с ключом "recipes": массив от 1 до {n} рецептов.
Если по ограничениям пользователя и списку продуктов рецепты собрать нельзя — верни пустой массив.
Каждый элемент массива — объект с полями:
- title (string) — название блюда ТОЛЬКО на русском, кириллица; без английских слов; формулировка естественная и грамматически согласованная
- ingredients (array of string, русский, конкретные количества по возможности)
- steps (array of string, русский, 7–12 подробных шагов)
- time_minutes (integer)
- difficulty: "easy" | "medium" | "hard"
- dish_type: "breakfast" | "lunch" | "dinner" | "snack" | "dessert" | "beverage"
- short_description (string, 1–2 предложения, только русский)
- tags (array of string) — русские метки по смыслу и при необходимости англ. ключи из настроек: low_cal, high_protein, budget_economy, table_t1, …
- restrictions (array of string, технические теги аллергенов если есть: nuts, seafood, eggs, gluten, lactose, и т.д.)
- calories (integer или null)
Требования к steps (обязательно):
- Пиши максимально подробно, как технологическую карту.
- Указывай, что и с чем смешивать, в какой последовательности.
- Для термообработки указывай температуру/мощность (например: духовка 180°C, средний огонь).
- Для каждого этапа указывай примерное время шага/диапазон.
- Добавляй признаки готовности (по цвету, текстуре, консистенции).
Правило качества и каноничности:
- Если входные данные неоднозначны, но есть узнаваемый кулинарный паттерн (кухня + набор продуктов + типичное сочетание),
  выбирай наиболее каноничное и распространённое название блюда для русскоязычной аудитории.
- Не подменяй каноничное блюдо общими названиями вроде «курица с орехами», если корректнее «Сациви из курицы».
- Не выдумывай новые блюда и «авторские» названия; опирайся на общеизвестные рецептурные традиции.
{_CANONICAL_TITLE_RULES}
Блюда реалистичные, домашние. Без вымышленных ингредиентов. Не дублируй английские названия вроде Pasta Carbonara — пиши по-русски (например «Паста карбонара»)."""


def _user_prompt(
    terms: list[str],
    cook_method: str,
    user: UsersData,
    *,
    cuisine_slug: str | None = None,
    cuisine_theme: str | None = None,
) -> str:
    mlabel = cook_method_label_ru(cook_method)
    cuisine = cuisine_slug or _cuisine_slug(user)
    cuisine_hint = cuisine_theme or cuisine
    cuisine_extra = _cuisine_products_hint(cuisine_slug, cuisine_theme, terms)
    extra_block = f"\n{cuisine_extra}\n" if cuisine_extra else ""
    return (
        f"Продукты (это ЖЁСТКОЕ ограничение, добавлять другие нельзя): {', '.join(terms)}\n"
        f"Способ приготовления (основной для всех рецептов): {mlabel}.\n"
        f"Стиль кухни (slug для поля cuisine в ответе не нужен — кухня задаётся отдельно): ориентир {cuisine_hint}\n"
        f"{extra_block}\n"
        "Верни только валидный JSON-объект формата из system prompt, без лишних ключей и без комментариев.\n"
        "Важно: каждый ингредиент в recipes[].ingredients должен быть только из списка продуктов пользователя "
        "(можно менять форму слова и указывать количество, но нельзя добавлять новые продукты).\n\n"
        "Важно: title должен быть естественным русским названием блюда (согласованные слова, без кальки вроде "
        "«курица отварные»).\n\n"
        f"{_CANONICAL_TITLE_RULES}\n\n"
        "Важно: шаги приготовления должны строго соответствовать выбранному способу приготовления. "
        "Не смешивай методы. Например, при «Пожарить» нельзя использовать духовку или запекание.\n\n"
        "Важно: steps должны быть максимально подробными, с поэтапным временем, температурами/огнем и "
        "четкими действиями по смешиванию и последовательности.\n\n"
        "Ограничения и настройки пользователя:\n"
        f"{_user_constraints_block(user, omit_preferred_cook_methods=True, force_cook_method=cook_method)}"
    )


def _normalize_ingredient_text(s: str) -> str:
    return re.sub(r"[^a-zа-яё0-9\s-]", " ", (s or "").lower()).strip()


def _is_ingredient_allowed(ingredient: str, terms: list[str]) -> bool:
    if _is_common_staple_ingredient(ingredient):
        return True
    ing = _normalize_ingredient_text(ingredient)
    if not ing:
        return False
    ing_stem = _ingredient_stem_key(ing)
    for term in terms:
        t = _normalize_ingredient_text(term)
        if not t:
            continue
        if t in ing or ing in t:
            return True
        t_stem = _ingredient_stem_key(t) or t
        # Сопоставляем по "корню", чтобы схватывать падежи:
        # "курица" <-> "курицы", "орехи" <-> "орехов", и т.п.
        if t_stem and t_stem in ing:
            return True
        if ing_stem and ing_stem in t:
            return True
    return False


def _ingredient_stem_key(norm_text: str) -> str:
    """Эвристические "корни" для сопоставления ингредиентов с учетом падежей/форм."""
    t = (norm_text or "").lower()
    if not t:
        return ""

    # Приоритетно для орехов: грецкий (в т.ч. "грецких")
    if "грец" in t:
        return "грец"
    if "орех" in t:
        return "орех"

    if "куриц" in t:
        return "куриц"
    if "говядин" in t:
        return "говядин"
    if "свинин" in t:
        return "свинин"
    if "индейк" in t:
        return "индейк"

    if "лук" in t:
        return "лук"
    if "чеснок" in t:
        return "чеснок"
    if "сыр" in t:
        return "сыр"
    if "творог" in t:
        return "творог"

    if "рис" in t:
        return "рис"
    if "гречк" in t:
        return "гречк"

    if "помидор" in t or "томат" in t:
        return "помидор"
    if "огурц" in t:
        return "огурц"

    # Фолбэк: сам нормализованный текст
    # (но это уже обработано на уровне substring-матчинга выше)
    return ""


def _is_common_staple_ingredient(ingredient: str) -> bool:
    """Базовые продукты, которые обычно есть на кухне и не должны "ломать" подбор."""
    norm = _normalize_ingredient_text(ingredient)
    if not norm:
        return False

    if "соль" in norm:
        return True
    if "сахар" in norm:
        return True

    # Ароматика, почти всегда используемая как база для соусов/маринадов
    # (чтобы рецепт не отклонялся как "не хватает продуктов").
    if "лук" in norm and "лук" == norm.strip():
        # точный вариант маловероятен, но оставляем как защиту
        return True
    if "лук" in norm:
        return True
    if "чеснок" in norm:
        return True

    # Масло (как базовый жир для жарки/запекания). Не принимаем сливочное.
    if "масло" in norm and "сливоч" not in norm:
        return True

    # Только чёрный перец как приправа.
    # (Обычный "перец" овощной типа болгарского не считаем базовой приправой.)
    if "перец" in norm and "болгар" not in norm and (
        norm in {"перец"}
        or "черн" in norm
        or "молот" in norm
        or "горош" in norm
        or ("по" in norm and "вкусу" in norm)
    ):
        return True
    if "перец" in norm and "болгар" in norm:
        return False

    return False


def _filter_recipes_by_terms(raw_list: list, terms: list[str]) -> list[dict]:
    out: list[dict] = []
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        ingredients = item.get("ingredients") or []
        if not isinstance(ingredients, list) or not ingredients:
            continue
        if all(_is_ingredient_allowed(str(ing), terms) for ing in ingredients):
            out.append(item)
    return out


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


def _matches_cook_method(item: dict, cook_method: str) -> bool:
    if cook_method == CookMethod.OTHER.value:
        return True
    chunks: list[str] = []
    for field in ("title", "short_description"):
        val = item.get(field)
        if isinstance(val, str) and val.strip():
            chunks.append(val.strip().lower())
    steps = item.get("steps") or []
    if isinstance(steps, list):
        chunks.extend(str(x).strip().lower() for x in steps if str(x).strip())
    text = " ".join(chunks)
    required = _METHOD_REQUIRED_TOKENS.get(cook_method, [])
    conflicts = _METHOD_CONFLICT_TOKENS.get(cook_method, [])
    if required and not any(t in text for t in required):
        return False
    if any(t in text for t in conflicts):
        return False
    return True


def _validate_recipe_item_schema(item: dict) -> list[str]:
    """Жесткая JSON-схема одного recipe item."""
    errors: list[str] = []
    required_keys = (
        "title",
        "ingredients",
        "steps",
        "time_minutes",
        "difficulty",
        "dish_type",
        "short_description",
        "tags",
        "restrictions",
        "calories",
    )
    for key in required_keys:
        if key not in item:
            errors.append(f"missing:{key}")
    if errors:
        return errors
    if not isinstance(item.get("title"), str) or not item["title"].strip():
        errors.append("bad:title")
    if not isinstance(item.get("short_description"), str) or not item["short_description"].strip():
        errors.append("bad:short_description")
    ingredients = item.get("ingredients")
    if not isinstance(ingredients, list) or not ingredients or any(not isinstance(x, str) or not x.strip() for x in ingredients):
        errors.append("bad:ingredients")
    steps = item.get("steps")
    if not isinstance(steps, list) or len(steps) < 6 or any(not isinstance(x, str) or not x.strip() for x in steps):
        errors.append("bad:steps")
    tm = item.get("time_minutes")
    if not isinstance(tm, int) or tm < 5 or tm > 240:
        errors.append("bad:time_minutes")
    diff = item.get("difficulty")
    if not isinstance(diff, str) or diff not in _VALID_DIFFICULTIES:
        errors.append("bad:difficulty")
    dish_type = item.get("dish_type")
    if not isinstance(dish_type, str) or dish_type not in _VALID_DISH_TYPES:
        errors.append("bad:dish_type")
    tags = item.get("tags")
    if not isinstance(tags, list) or any(not isinstance(x, str) for x in tags):
        errors.append("bad:tags")
    restrictions = item.get("restrictions")
    if not isinstance(restrictions, list) or any(not isinstance(x, str) for x in restrictions):
        errors.append("bad:restrictions")
    calories = item.get("calories")
    if calories is not None and not isinstance(calories, int):
        errors.append("bad:calories")
    return errors


def _self_check_items(raw_list: list, terms: list[str], cook_method: str) -> tuple[list[dict], list[str]]:
    ok: list[dict] = []
    violations: list[str] = []
    for idx, item in enumerate(raw_list, start=1):
        if not isinstance(item, dict):
            violations.append(f"recipe#{idx}:not_object")
            continue
        schema_errors = _validate_recipe_item_schema(item)
        if schema_errors:
            violations.append(f"recipe#{idx}:" + ",".join(schema_errors))
            continue
        ingredients = item.get("ingredients") or []
        if not all(_is_ingredient_allowed(str(ing), terms) for ing in ingredients):
            violations.append(f"recipe#{idx}:outside_terms")
            continue
        if not _matches_cook_method(item, cook_method):
            violations.append(f"recipe#{idx}:method_conflict")
            continue
        ok.append(item)
    return ok, violations


def _self_check_items_relaxed(raw_list: list, cook_method: str) -> tuple[list[dict], list[str]]:
    """Проверка для режима, где разрешены дополнительные ингредиенты."""
    ok: list[dict] = []
    violations: list[str] = []
    for idx, item in enumerate(raw_list, start=1):
        if not isinstance(item, dict):
            violations.append(f"recipe#{idx}:not_object")
            continue
        schema_errors = _validate_recipe_item_schema(item)
        if schema_errors:
            violations.append(f"recipe#{idx}:" + ",".join(schema_errors))
            continue
        if not _matches_cook_method(item, cook_method):
            violations.append(f"recipe#{idx}:method_conflict")
            continue
        ok.append(item)
    return ok, violations


def _added_ingredients_for_item(item: dict, terms: list[str]) -> list[str]:
    ingredients = item.get("ingredients") or []
    if not isinstance(ingredients, list):
        return []
    added: list[str] = []
    seen: set[str] = set()
    for ing in ingredients:
        text = str(ing).strip()
        if not text:
            continue
        if _is_ingredient_allowed(text, terms):
            continue
        key = _normalize_ingredient_text(text)
        if key and key not in seen:
            seen.add(key)
            added.append(text)
    return added


def _attach_added_ingredients_note(item: dict, added: list[str]) -> None:
    if not added:
        return
    note = (
        "⚠️ Чтобы рецепт получился вкусным, добавлены недостающие продукты: "
        + ", ".join(added[:6])
        + "."
    )
    existing = str(item.get("short_description") or "").strip()
    item["short_description"] = f"{note}\n{existing}".strip()[:2000]
    tags = item.get("tags")
    if not isinstance(tags, list):
        tags = []
    if "extra_ingredients" not in tags:
        tags.append("extra_ingredients")
    item["tags"] = tags


async def _generate_relaxed_items_for_shortage(
    *,
    need_count: int,
    terms: list[str],
    cook_method: str,
    user: UsersData,
    cuisine_slug: str | None,
    cuisine_theme: str | None,
) -> list[dict]:
    if need_count <= 0:
        return []
    relaxed_user_prompt = (
        f"У пользователя есть продукты: {', '.join(terms)}.\n"
        f"Нужно сгенерировать ровно {need_count} дополнительных рецепта(ов) способом {cook_method_label_ru(cook_method)}.\n"
        "Можно добавить недостающие ингредиенты, но минимум возможного: обычно 1-5 позиций на рецепт.\n"
        "Обязательно используй продукты пользователя как основу каждого рецепта.\n"
        "В short_description начни с фразы «⚠️ Чтобы рецепт получился вкусным, добавлены недостающие продукты: ...» и перечисли, что было добавлено.\n"
        "Нельзя писать общие слова вроде «специи по вкусу» в этом списке — только конкретные продукты.\n\n"
        "Ограничения и настройки пользователя:\n"
        f"{_user_constraints_block(user, omit_preferred_cook_methods=True, force_cook_method=cook_method)}\n"
    )
    if cuisine_slug or cuisine_theme:
        relaxed_user_prompt += (
            f"\nКухня/стиль: {cuisine_theme or cuisine_slug}. "
            "Соблюдай характер блюда для этой кухни."
        )

    data = await openai_ai.chat_json_object(
        _system_prompt(need_count),
        relaxed_user_prompt,
        max_tokens=config.OPENAI_RECIPE_MAX_TOKENS,
    )
    raw = data.get("recipes")
    if not isinstance(raw, list) or not raw:
        return []
    checked, _ = _self_check_items_relaxed(raw, cook_method)
    out: list[dict] = []
    for item in checked[:need_count]:
        added = _added_ingredients_for_item(item, terms)
        if not added:
            continue
        _attach_added_ingredients_note(item, added)
        out.append(item)
    return out


def _first_term_label(terms: list[str]) -> str:
    return (terms[0] if terms else "продукт").strip().capitalize()


_DISH_NAME_SINGLE_WORD = frozenset(
    {
        "сациви",
        "чахохбили",
        "хачапури",
        "хинкали",
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
    }
)

_SINGLE_INGREDIENT_HINT = frozenset(
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


def _terms_look_like_dish_name_only(terms: list[str]) -> bool:
    """Один токен похож на название блюда, а не на продукт в списке."""
    if len(terms) != 1:
        return False
    w = terms[0].strip().lower()
    if len(w) < 4:
        return False
    if w in _SINGLE_INGREDIENT_HINT:
        return False
    if w in _DISH_NAME_SINGLE_WORD:
        return True
    # Длинное слово вне списка типичных продуктов — чаще название блюда, чем ингредиент
    if len(w) >= 10:
        return True
    return False


def _polish_recipe_title(title: str, cook_method: str) -> str:
    """Правки частых грамматических ошибок в названии (без тяжёлого морфологического анализа)."""
    t = (title or "").strip()
    if not t:
        return t
    fixes = [
        (re.compile(r"^курица\s+отварные\b", re.IGNORECASE), "Отварная курица"),
        (re.compile(r"^курица\s+тушёные\b", re.IGNORECASE), "Тушёная курица"),
        (re.compile(r"^курица\s+тушеные\b", re.IGNORECASE), "Тушёная курица"),
        (re.compile(r"^курица\s+запечённые\b", re.IGNORECASE), "Запечённая курица"),
        (re.compile(r"^курица\s+запеченные\b", re.IGNORECASE), "Запечённая курица"),
        (re.compile(r"^курица\s+жареные\b", re.IGNORECASE), "Жареная курица"),
        (re.compile(r"^говядина\s+отварные\b", re.IGNORECASE), "Отварная говядина"),
        (re.compile(r"^свинина\s+отварные\b", re.IGNORECASE), "Отварная свинина"),
        (re.compile(r"^индейка\s+отварные\b", re.IGNORECASE), "Отварная индейка"),
    ]
    for pat, repl in fixes:
        if pat.search(t):
            t = pat.sub(repl, t)
            break
    if cook_method == CookMethod.BOIL.value and re.search(r"\bотварные\b", t, re.IGNORECASE):
        t = re.sub(r"\bотварные\b", "отварное", t, flags=re.IGNORECASE)
    if cook_method == CookMethod.BAKE.value and re.search(r"\bзапечённые\b", t, re.IGNORECASE):
        t = re.sub(r"\bзапечённые\b", "запечённое", t, flags=re.IGNORECASE)
    return t[:255]


def _fallback_title(terms: list[str], cook_method: str) -> str:
    """Корректное по-русски название для fallback без склейки «существительное + не согласованное прилагательное»."""
    if not terms:
        return "Блюдо"
    parts = [x.strip() for x in terms if x.strip()]
    joined = ", ".join(parts)
    low = joined.lower()
    if len(parts) == 1:
        w = parts[0].lower()
        if "куриц" in w:
            return {
                CookMethod.BOIL.value: "Отварная курица",
                CookMethod.FRY.value: "Жареная курица на сковороде",
                CookMethod.BAKE.value: "Запечённая курица",
                CookMethod.STEW.value: "Тушёная курица",
                CookMethod.STEAM.value: "Курица на пару",
                CookMethod.GRILL.value: "Курица на гриле",
                CookMethod.DEEP_FRY.value: "Курица во фритюре",
                CookMethod.BBQ.value: "Курица на мангале",
                CookMethod.RAW.value: "Курица без термообработки",
                CookMethod.OTHER.value: "Курица",
            }.get(cook_method, f"Блюдо из курицы ({joined})")
        if "свинин" in w:
            return {
                CookMethod.BOIL.value: "Отварная свинина",
                CookMethod.FRY.value: "Жареная свинина на сковороде",
                CookMethod.BAKE.value: "Запечённая свинина",
                CookMethod.STEW.value: "Тушёная свинина",
                CookMethod.STEAM.value: "Свинина на пару",
                CookMethod.GRILL.value: "Свинина на гриле",
                CookMethod.DEEP_FRY.value: "Свинина во фритюре",
                CookMethod.BBQ.value: "Свинина на мангале",
                CookMethod.RAW.value: "Свинина без термообработки",
                CookMethod.OTHER.value: "Свинина",
            }.get(cook_method, f"Блюдо из свинины ({joined})")
        if "говядин" in w:
            return {
                CookMethod.BOIL.value: "Отварная говядина",
                CookMethod.FRY.value: "Жареная говядина на сковороде",
                CookMethod.BAKE.value: "Запечённая говядина",
                CookMethod.STEW.value: "Тушёная говядина",
                CookMethod.STEAM.value: "Говядина на пару",
                CookMethod.GRILL.value: "Говядина на гриле",
                CookMethod.DEEP_FRY.value: "Говядина во фритюре",
                CookMethod.BBQ.value: "Говядина на мангале",
                CookMethod.RAW.value: "Говядина без термообработки",
                CookMethod.OTHER.value: "Говядина",
            }.get(cook_method, f"Блюдо из говядины ({joined})")
        if "яйц" in w:
            return {
                CookMethod.FRY.value: "Жареные яйца на сковороде",
                CookMethod.BOIL.value: "Варёные яйца",
                CookMethod.BAKE.value: "Запечённые яйца",
                CookMethod.STEAM.value: "Яйца на пару",
                CookMethod.OTHER.value: "Яйца",
            }.get(cook_method, f"Блюдо из яиц ({joined})")
    method_word = {
        CookMethod.FRY.value: "жареное",
        CookMethod.BOIL.value: "отварное",
        CookMethod.BAKE.value: "запечённое",
        CookMethod.STEW.value: "тушёное",
        CookMethod.STEAM.value: "на пару",
        CookMethod.GRILL.value: "на гриле",
        CookMethod.DEEP_FRY.value: "во фритюре",
        CookMethod.BBQ.value: "на мангале",
        CookMethod.RAW.value: "без термообработки",
        CookMethod.OTHER.value: "домашнее",
    }.get(cook_method, "домашнее")
    return f"{method_word.capitalize()} блюдо: {joined}"[:255]


def _cuisine_products_hint(cuisine_slug: str | None, cuisine_theme: str | None, terms: list[str]) -> str:
    blob = " ".join(t.lower() for t in terms)
    slug = (cuisine_slug or "").lower()
    theme = (cuisine_theme or "").lower()
    if slug == "georgian" or "грузин" in theme:
        if "куриц" in blob and ("орех" in blob or "грец" in blob):
            return (
                "Кухня Грузия: из курицы с грецким орехом чаще всего готовят сациви — курица в густом ореховом соусе "
                "с луком и специями. Старайся выбрать узнаваемый вариант этого блюда, а не обобщённое «курица с орехами»."
            )
    if slug == "italian" or "итал" in theme:
        if "паст" in blob or "макарон" in blob or "спагетти" in blob:
            return "Кухня Италия: ориентируйся на типичные итальянские приёмы и названия блюд из переданных продуктов."
    return ""


def _canonical_title_by_context(
    title: str,
    *,
    cuisine_slug: str | None = None,
    cuisine_theme: str | None = None,
    terms: list[str] | None = None,
    ingredients: list[str] | None = None,
) -> str:
    """Контекстный пост-процессинг названия: фиксируем частые канонические блюда."""
    base = (title or "").strip()
    if not base:
        return base

    low_title = base.lower()
    if "сацив" in low_title:
        return base

    slug = (cuisine_slug or "").strip().lower()
    theme = (cuisine_theme or "").strip().lower()
    is_georgian = slug == "georgian" or "грузин" in theme
    if not is_georgian:
        return base

    blob = " ".join(
        x.lower()
        for x in [*(terms or []), *(ingredients or [])]
        if isinstance(x, str) and x.strip()
    )
    has_chicken = ("куриц" in blob) or ("куриц" in low_title)
    has_nuts = any(tok in blob for tok in ("орех", "грец")) or any(tok in low_title for tok in ("орех", "грец"))

    if has_chicken and has_nuts:
        generic = any(
            p in low_title
            for p in (
                "курица с орех",
                "куриное блюдо с орех",
                "блюдо из курицы и орех",
                "курица в орехов",
            )
        )
        if generic:
            return "Сациви из курицы"

    return base


def _is_generic_dish_title(title: str) -> bool:
    t = (title or "").strip().lower()
    if not t:
        return True
    generic_patterns = (
        r"^блюдо\b",
        r"^домашн\w+\s+блюдо\b",
        r"^куриц[аы]?\s+с\b",
        r"^мясо\s+с\b",
        r"^рыба\s+с\b",
        r"^салат\s+из\b",
        r"^суп\s+из\b",
    )
    return any(re.search(p, t) for p in generic_patterns)


def _wiki_search_query(
    title: str,
    *,
    cuisine_slug: str | None,
    cuisine_theme: str | None,
    terms: list[str] | None,
    ingredients: list[str] | None,
) -> str:
    parts: list[str] = []
    if cuisine_theme:
        parts.append(cuisine_theme.strip())
    if cuisine_slug == "georgian":
        parts.append("грузинская кухня")

    if _is_generic_dish_title(title):
        src = [*(terms or []), *(ingredients or [])]
        uniq = []
        for x in src:
            x2 = str(x).strip()
            if x2 and x2.lower() not in {u.lower() for u in uniq}:
                uniq.append(x2)
        parts.extend(uniq[:4])
    else:
        parts.append(title.strip())
    parts.append("блюдо")
    return " ".join(p for p in parts if p)


def _score_wiki_candidate(
    candidate_title: str,
    snippet: str,
    *,
    cuisine_slug: str | None,
    cuisine_theme: str | None,
) -> int:
    t = candidate_title.strip().lower()
    s = snippet.strip().lower()
    score = 0
    if _has_cyrillic(candidate_title):
        score += 3
    if not _is_generic_dish_title(candidate_title):
        score += 4
    if 1 <= len(t.split()) <= 4:
        score += 2
    if "значения" in t:
        score -= 6
    if "может означать" in s:
        score -= 4
    if cuisine_slug == "georgian" or (cuisine_theme and "грузин" in cuisine_theme.lower()):
        if "грузин" in s:
            score += 3
        if "сациви" in t:
            score += 6
    if "блюдо" in s:
        score += 2
    return score


async def _canonical_title_by_free_api(
    title: str,
    *,
    cuisine_slug: str | None = None,
    cuisine_theme: str | None = None,
    terms: list[str] | None = None,
    ingredients: list[str] | None = None,
) -> str:
    """Бесплатный fallback: пробуем взять более каноничное название из Wikipedia API."""
    base = (title or "").strip()
    if not base:
        return base
    if not config.FREE_TITLE_API_ENABLED:
        return base
    if not _is_generic_dish_title(base):
        return base

    query = _wiki_search_query(
        base,
        cuisine_slug=cuisine_slug,
        cuisine_theme=cuisine_theme,
        terms=terms,
        ingredients=ingredients,
    )
    if not query:
        return base

    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "format": "json",
        "utf8": "1",
        "srlimit": "6",
    }
    timeout = httpx.Timeout(config.FREE_TITLE_API_TIMEOUT_SEC)
    try:
        async with httpx.AsyncClient(timeout=timeout) as http:
            resp = await http.get("https://ru.wikipedia.org/w/api.php", params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.debug("free title api failed: %s", exc)
        return base

    hits = (data.get("query") or {}).get("search") or []
    best_title = base
    best_score = -10**9
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        cand = str(hit.get("title") or "").strip()
        if not cand:
            continue
        snippet = html.unescape(str(hit.get("snippet") or ""))
        score = _score_wiki_candidate(
            cand,
            snippet,
            cuisine_slug=cuisine_slug,
            cuisine_theme=cuisine_theme,
        )
        if score > best_score:
            best_score = score
            best_title = cand

    if best_score >= 6:
        return best_title[:255]
    return base


def _estimate_fallback_time(terms: list[str], cook_method: str) -> int:
    joined = " ".join(t.lower() for t in terms)
    has_meat = any(x in joined for x in ("свинин", "говядин", "куриц", "индейк", "мяс"))
    has_potato = "карто" in joined
    if cook_method == CookMethod.BAKE.value:
        base = 45
        if has_meat:
            base += 15
        if has_potato:
            base += 10
        return min(base, 120)
    if cook_method == CookMethod.FRY.value:
        return 20 if has_meat else 12
    if cook_method == CookMethod.BOIL.value:
        return 30 if has_meat else 18
    if cook_method == CookMethod.STEW.value:
        return 50 if has_meat else 30
    if cook_method == CookMethod.STEAM.value:
        return 25 if has_meat else 15
    if cook_method in (CookMethod.GRILL.value, CookMethod.BBQ.value):
        return 35 if has_meat else 20
    if cook_method == CookMethod.DEEP_FRY.value:
        return 18
    if cook_method == CookMethod.RAW.value:
        return 10
    return 25


def _build_simple_fallback_item(terms: list[str], cook_method: str) -> dict | None:
    """Последний шанс: детальный валидный рецепт строго из введённых продуктов."""
    if not terms:
        return None
    if _terms_look_like_dish_name_only(terms):
        return None
    title = _fallback_title(terms, cook_method)
    ingredients = [t.strip() for t in terms if t.strip()]
    time_total = _estimate_fallback_time(ingredients, cook_method)
    prep_open = {
        CookMethod.FRY.value: "Разогрей сковороду 1-2 минуты на среднем огне и при необходимости добавь тонкий слой масла.",
        CookMethod.BOIL.value: "Доведи воду до активного кипения на среднем огне.",
        CookMethod.BAKE.value: "Разогрей духовку до 185-190°C (верх-низ) в течение 8-10 минут.",
        CookMethod.STEW.value: "Разогрей сотейник с толстым дном на среднем огне 1-2 минуты.",
        CookMethod.STEAM.value: "Подготовь пароварку и доведи воду до кипения.",
        CookMethod.GRILL.value: "Разогрей гриль до средней температуры 5-7 минут.",
        CookMethod.DEEP_FRY.value: "Разогрей масло до 170-175°C.",
        CookMethod.BBQ.value: "Подготовь мангал и стабильный жар без открытого пламени.",
        CookMethod.RAW.value: "Тщательно промой и обсуши продукты.",
        CookMethod.OTHER.value: "Подготовь рабочую зону и продукты.",
    }.get(cook_method, "Подготовь рабочую зону и продукты.")
    main_stage = {
        CookMethod.FRY.value: "Выложи основные продукты на сковороду и готовь 6-10 минут, периодически помешивая или переворачивая.",
        CookMethod.BOIL.value: "Добавь продукты в кипящую воду и вари 10-25 минут до мягкости.",
        CookMethod.BAKE.value: "Переложи смесь в форму и запекай 30-45 минут до румяной корочки и полной готовности.",
        CookMethod.STEW.value: "Добавь продукты и туши под крышкой 25-40 минут на слабом огне.",
        CookMethod.STEAM.value: "Разложи продукты в пароварке и готовь 10-20 минут до мягкости.",
        CookMethod.GRILL.value: "Готовь на гриле 8-15 минут, переворачивая для равномерной прожарки.",
        CookMethod.DEEP_FRY.value: "Жарь небольшими порциями 3-5 минут до золотистого цвета.",
        CookMethod.BBQ.value: "Готовь на решетке 12-20 минут, регулярно переворачивая.",
        CookMethod.RAW.value: "Смешай продукты в миске и дай им объединиться по вкусу 5-7 минут.",
        CookMethod.OTHER.value: "Готовь выбранным способом до нужной текстуры и вкуса.",
    }.get(cook_method, "Готовь выбранным способом до нужной текстуры и вкуса.")
    return {
        "title": title,
        "ingredients": ingredients,
        "steps": [
            f"Подготовь продукты: {', '.join(ingredients)}. Крупные куски нарежь одинаково, чтобы они приготовились равномерно (этап 5-8 минут).",
            "Смешай в миске продукты, которые должны готовиться вместе, и оставь на 3-5 минут для распределения вкуса и влаги.",
            prep_open,
            "Если используется форма или противень, смажь поверхность тонким слоем масла и уложи продукты в один слой без плотного наложения.",
            main_stage,
            "Проверь готовность: внутри не должно быть сырого участка, а поверхность должна быть слегка румяной/упругой. При необходимости продли еще на 5-10 минут.",
            "Дай блюду отдохнуть 2-3 минуты перед подачей, затем подавай горячим.",
        ],
        "time_minutes": time_total,
        "difficulty": Difficulty.EASY.value,
        "dish_type": DishType.BREAKFAST.value if any("яйц" in t.lower() for t in ingredients) else DishType.SNACK.value,
        "short_description": "Сытное домашнее блюдо с понятной пошаговой инструкцией.",
        "tags": ["базовый", "подробный"],
        "restrictions": [],
        "calories": None,
    }


def _system_prompt_cuisine(n: int) -> str:
    return f"""Ты помощник по кулинарии. Нужно ровно {n} рецепта в духе указанной кухни/страны/региона.
Верни строго один JSON-объект с ключом "recipes": массив из {n} объектов.
Каждый элемент:
- title — только русский, кириллица; название естественное, слова согласованы (не «курица отварные»)
- ingredients (array of string, русский)
- steps (array of string, русский, 7–12 подробных шагов)
- time_minutes (integer)
- difficulty: "easy" | "medium" | "hard"
- dish_type: "breakfast" | "lunch" | "dinner" | "snack" | "dessert" | "beverage"
- cook_method: один из boil,fry,bake,other,stew,steam,grill,deep_fry,bbq,raw — по смыслу блюда
- short_description (русский, 1–2 предложения)
- tags — по-русски и при необходимости англ. ключи (low_cal, budget_medium, table_t4, …)
- restrictions (аллергены при необходимости: nuts, seafood, eggs, gluten, lactose…)
- calories (integer или null)
Требования к steps (обязательно):
- Подробная, развёрнутая инструкция по этапам.
- Указывай температуры/нагрев и длительность этапов.
- Прописывай последовательность: что смешать, когда добавить, как довести до готовности.
- Добавляй признаки готовности.
Правило выбора блюда:
- Если запрос звучит как описание/намёк, а не точное название, выбери наиболее вероятное классическое блюдо этой кухни.
- При прочих равных отдавай приоритет узнаваемой классике, а не абстрактным «блюдам из X».
{_CANONICAL_TITLE_RULES}
Блюда должны быть правдоподобными для выбранной кухни (типичные продукты и названия)."""


def _user_prompt_cuisine(
    user: UsersData,
    cuisine_theme: str,
    *,
    dish_type: str | None,
    time_bucket: str | None,
    popular_only: bool,
) -> str:
    parts = [
        f"Кухня / страна / тема: {cuisine_theme}",
        "Сделай рецепты, характерные именно для этой кухни.",
    ]
    if popular_only:
        parts.append("Выбери узнаваемые классические блюда, которые чаще всего ассоциируют с этой кухнёй.")
    if dish_type:
        parts.append(f"Все рецепты с dish_type = {dish_type} (строго).")
    if time_bucket == "fast":
        parts.append("Каждый рецепт: 5–15 минут (time_minutes в этом диапазоне).")
    elif time_bucket == "medium":
        parts.append("Каждый рецепт: 16–45 минут.")
    elif time_bucket == "long":
        parts.append("Каждый рецепт: 46–120 минут (неспешное приготовление).")
    parts.append(_CANONICAL_TITLE_RULES)
    parts.append(
        "\nОграничения и настройки пользователя:\n"
        + _user_constraints_block(user, omit_dish_type_prefs=bool(dish_type))
    )
    return "\n".join(parts)


def _user_prompt_dish_name(
    user: UsersData,
    dish_query: str,
    *,
    forced_cook_method: str | None = None,
    cuisine_theme: str | None = None,
) -> str:
    extra = ""
    if forced_cook_method:
        mlab = cook_method_label_ru(forced_cook_method)
        extra = (
            f"\n\nСпособ приготовления, который выбрал пользователь: {mlab}.\n"
            "Поле cook_method в каждом рецепте должно соответствовать этому способу, "
            "а шаги приготовления — только этому способу (не смешивай духовку и сковороду).\n"
        )
    cuisine_block = ""
    if cuisine_theme and cuisine_theme.strip():
        cuisine_block = (
            f"\n\nКонтекст кухни (важно): пользователь выбрал направление «{cuisine_theme.strip()}». "
            "Сделай рецепт и название в духе этой кухни, с типичными ингредиентами и подачей.\n"
        )
    return (
        f"Пользователь ищет блюдо по названию или описанию: «{dish_query}».\n"
        "Сгенерируй несколько разумных вариантов рецептов, которые соответствуют запросу "
        "(разные варианты или популярные интерпретации блюда, если уместно).\n\n"
        "Критически важно: если запрос описательный (например кухня + главный продукт + характерный ингредиент), "
        "сначала определи наиболее вероятное каноничное блюдо, затем строй рецепт именно вокруг него.\n"
        "Пример логики: грузинская кухня + курица + грецкий орех -> в приоритете сациви.\n\n"
        "Важно: в recipes[].ingredients перечисли реальные продукты и специи для приготовления блюда "
        "(курица, лук, орехи, масло, соль…). Нельзя указывать одно только название блюда как ингредиент.\n"
        "Важно: не давай общих или расплывчатых названий. Нужны конкретные, общеупотребимые названия блюд.\n"
        f"{_CANONICAL_TITLE_RULES}\n"
        f"{cuisine_block}{extra}"
        "Ограничения и настройки пользователя:\n"
        + _user_constraints_block(
            user,
            omit_preferred_cook_methods=True,
            **({"force_cook_method": forced_cook_method} if forced_cook_method else {}),
        )
    )


async def _schedule_recipe_images(
    created: list[Recipe],
    progress: Callable[[str], Awaitable[None]] | None,
) -> None:
    mode = getattr(config, "RECIPE_IMAGES_MODE", "sync")
    if mode == "off":
        return
    if mode == "async":
        for r in created:
            asyncio.create_task(ensure_dish_image(r))
        return
    if progress:
        await progress("images")
    await asyncio.gather(*(ensure_dish_image(r) for r in created))


async def generate_recipes_for_cuisine(
    user: UsersData,
    *,
    cuisine_slug: str,
    cuisine_theme: str,
    dish_type: str | None = None,
    time_bucket: str | None = None,
    popular_only: bool = False,
    progress: Callable[[str], Awaitable[None]] | None = None,
) -> list[Recipe]:
    n = config.AI_RECIPES_PER_REQUEST
    data = await openai_ai.chat_json_object(
        _system_prompt_cuisine(n),
        _user_prompt_cuisine(
            user,
            cuisine_theme,
            dish_type=dish_type,
            time_bucket=time_bucket,
            popular_only=popular_only,
        ),
        max_tokens=config.OPENAI_RECIPE_MAX_TOKENS,
    )
    raw_list = data.get("recipes")
    if not isinstance(raw_list, list) or not raw_list:
        raise ValueError("пустой ответ recipes")
    checked, violations = _self_check_items_relaxed(raw_list, CookMethod.OTHER.value)
    filtered, hard_violations = _apply_user_constraints_filter(
        checked,
        user,
        force_dish_type=dish_type,
        force_time_bucket=time_bucket,
    )
    raw_list = filtered[:n]
    if not raw_list:
        raise ValueError("все recipes нарушают ограничения: " + "; ".join((violations + hard_violations)[:8]))
    await _refine_recipe_titles_with_llm([x for x in raw_list[:n] if isinstance(x, dict)])
    model_tag = config.OPENAI_CHAT_MODEL
    default_cm = CookMethod.FRY.value
    rows: list[dict] = []
    for item in raw_list[:n]:
        if not isinstance(item, dict):
            continue
        if dish_type:
            item["dish_type"] = dish_type
        title = str(item.get("title") or "").strip()
        if title and not _has_cyrillic(title):
            item["title"] = await _ensure_russian_line(title, what="название блюда")
        cm_use = _norm_cook_method(str(item.get("cook_method") or default_cm))
        item["title"] = _polish_recipe_title(str(item.get("title") or ""), cm_use)
        item["title"] = _canonical_title_by_context(
            str(item.get("title") or ""),
            cuisine_slug=cuisine_slug,
            cuisine_theme=cuisine_theme,
            ingredients=[str(x) for x in (item.get("ingredients") or []) if isinstance(x, str)],
        )
        item["title"] = await _canonical_title_by_free_api(
            str(item.get("title") or ""),
            cuisine_slug=cuisine_slug,
            cuisine_theme=cuisine_theme,
            ingredients=[str(x) for x in (item.get("ingredients") or []) if isinstance(x, str)],
        )
        desc = str(item.get("short_description") or "").strip()
        if desc and not _has_cyrillic(desc):
            item["short_description"] = await _ensure_russian_line(desc, what="краткое описание")
        rows.append(
            _row_from_item(
                item,
                cuisine=cuisine_slug,
                cook_method=cm_use,
                model_name=model_tag,
                cuisine_theme=cuisine_theme,
            )
        )
    if not rows:
        raise ValueError("не удалось разобрать рецепты")
    with db.atomic():
        created = [Recipe.create(**r) for r in rows]
    await _schedule_recipe_images(created, progress)
    return created


async def generate_and_persist_by_dish_name(
    user: UsersData,
    dish_query: str,
    *,
    progress: Callable[[str], Awaitable[None]] | None = None,
    forced_cook_method: str | None = None,
    cuisine_slug: str | None = None,
    cuisine_theme: str | None = None,
) -> list[Recipe]:
    """ИИ-рецепты по запросу «название блюда» (cook_method задаётся для каждого рецепта в JSON)."""
    max_n = 5
    min_n = 3
    n = max_n

    raw_list: list | None = None
    last_exc: Exception | None = None
    for _attempt in range(3):
        try:
            data = await openai_ai.chat_json_object(
                _system_prompt_cuisine(n),
                _user_prompt_dish_name(
                    user,
                    dish_query,
                    forced_cook_method=forced_cook_method,
                    cuisine_theme=cuisine_theme,
                ),
                max_tokens=config.OPENAI_RECIPE_MAX_TOKENS,
            )
            rl = data.get("recipes")
            if isinstance(rl, list):
                dict_cnt = sum(1 for x in rl[:n] if isinstance(x, dict))
                if dict_cnt >= min_n:
                    raw_list = rl
                    break
        except Exception as exc:
            last_exc = exc

    if not isinstance(raw_list, list) or not raw_list:
        raise ValueError("пустой/недостаточный ответ recipes") from last_exc

    checked, violations = _self_check_items_relaxed(raw_list, forced_cook_method or CookMethod.OTHER.value)
    filtered, hard_violations = _apply_user_constraints_filter(
        checked,
        user,
        force_cook_method=forced_cook_method,
    )
    if len(filtered) < min_n:
        raise ValueError(
            "недостаточно recipes после фильтрации: "
            + "; ".join((violations + hard_violations)[:10])
        )
    raw_list = filtered
    await _refine_recipe_titles_with_llm([x for x in raw_list[:n] if isinstance(x, dict)])
    cuisine = cuisine_slug or _cuisine_slug(user)
    model_tag = config.OPENAI_CHAT_MODEL
    default_cm = forced_cook_method or CookMethod.FRY.value
    rows: list[dict] = []
    for item in raw_list[:n]:
        if not isinstance(item, dict):
            continue
        if forced_cook_method:
            item["cook_method"] = forced_cook_method
        title = str(item.get("title") or "").strip()
        if title and not _has_cyrillic(title):
            item["title"] = await _ensure_russian_line(title, what="название блюда")
        cm_row = forced_cook_method or str(item.get("cook_method") or default_cm)
        item["title"] = _polish_recipe_title(str(item.get("title") or ""), _norm_cook_method(cm_row))
        item["title"] = _canonical_title_by_context(
            str(item.get("title") or ""),
            cuisine_slug=cuisine,
            cuisine_theme=cuisine_theme,
            ingredients=[str(x) for x in (item.get("ingredients") or []) if isinstance(x, str)],
        )
        item["title"] = await _canonical_title_by_free_api(
            str(item.get("title") or ""),
            cuisine_slug=cuisine,
            cuisine_theme=cuisine_theme,
            terms=[dish_query],
            ingredients=[str(x) for x in (item.get("ingredients") or []) if isinstance(x, str)],
        )
        desc = str(item.get("short_description") or "").strip()
        if desc and not _has_cyrillic(desc):
            item["short_description"] = await _ensure_russian_line(desc, what="краткое описание")
        rows.append(
            _row_from_item(
                item,
                cuisine=cuisine,
                cook_method=_norm_cook_method(str(item.get("cook_method") or default_cm)),
                model_name=model_tag,
                cuisine_theme=cuisine_theme,
            )
        )
    if not rows:
        raise ValueError("не удалось разобрать рецепты")
    if len(rows) < min_n:
        raise ValueError(f"слишком мало рецептов: {len(rows)}")
    with db.atomic():
        created = [Recipe.create(**r) for r in rows]
    await _schedule_recipe_images(created, progress)
    return created


def _row_from_item(
    item: dict,
    *,
    cuisine: str,
    cook_method: str,
    model_name: str,
    cuisine_theme: str | None = None,
) -> dict:
    ingredients = item.get("ingredients") or []
    steps = item.get("steps") or []
    if not isinstance(ingredients, list):
        ingredients = []
    if not isinstance(steps, list):
        steps = []
    tags = item.get("tags") or []
    restrictions = item.get("restrictions") or []
    if not isinstance(tags, list):
        tags = []
    if not isinstance(restrictions, list):
        restrictions = []
    title = str(item.get("title") or "Блюдо").strip()[:255]
    cm = item.get("cook_method")
    if isinstance(cm, str) and cm.strip():
        cook_method = _norm_cook_method(cm.strip())
    disp_ru = cuisine_display_ru_for_recipe(cuisine, cuisine_theme)
    return {
        "title": title,
        "cuisine": cuisine,
        "cuisine_display_ru": disp_ru,
        "ingredients_json": json.dumps([str(x) for x in ingredients], ensure_ascii=False),
        "steps_json": json.dumps([str(x) for x in steps], ensure_ascii=False),
        "time_minutes": max(5, min(int(item.get("time_minutes") or 30), 240)),
        "difficulty": _norm_difficulty(str(item.get("difficulty") or "")),
        "dish_type": _norm_dish_type(str(item.get("dish_type") or "")),
        "cook_method": cook_method,
        "tags_json": json.dumps([str(x) for x in tags], ensure_ascii=False),
        "restrictions_json": json.dumps([str(x) for x in restrictions], ensure_ascii=False),
        "calories": _safe_calories(item.get("calories")),
        "short_description": str(item.get("short_description") or "")[:2000],
        "is_published": True,
        "popularity": 0,
        "ai_chat_model": model_name[:64],
    }


async def ensure_dish_image(recipe: Recipe) -> None:
    if recipe.dish_image_path:
        p = Path(recipe.dish_image_path)
        if p.is_file():
            return
    try:
        ing_preview = ", ".join(_json_list(recipe.ingredients_json)[:12])
        method = (recipe.cook_method or "").strip().lower()
        dish_type = (recipe.dish_type or "").strip().lower()
        cuisine = (recipe.cuisine or "").strip().lower()
        method_visual_hint = {
            "boil": (
                "The final dish must look cohesive and fully cooked by boiling/simmering: "
                "ingredients are integrated together in one unified composition, not separated into distinct piles."
            ),
            "stew": (
                "Show a cohesive stewed texture: ingredients are tender and combined in one unified dish, "
                "with visible sauce/body, not separated."
            ),
            "fry": (
                "Show a realistic fried finish with integrated components plated as one dish, not as separate raw-like parts."
            ),
            "bake": (
                "Show a baked, cohesive final result (light crust/caramelization where relevant), plated as one complete dish."
            ),
            "steam": (
                "Show a steamed finished dish with soft texture and unified plating; ingredients should not look raw or isolated."
            ),
            "grill": (
                "Show grilled doneness marks where appropriate, but plated as one coherent finished dish."
            ),
            "deep_fry": (
                "Show crisp deep-fried texture where appropriate, served as a coherent final plate."
            ),
            "bbq": (
                "Show barbecue-style doneness and serving, but as one completed dish with cohesive composition."
            ),
            "raw": (
                "Show a cohesive ready-to-serve raw dish (salad/tartar/carpaccio style), neatly composed as one dish."
            ),
        }.get(
            method,
            "Show a cohesive ready-to-serve final dish, not separate ingredient piles.",
        )
        dish_type_visual_hint = {
            "breakfast": (
                "Serving context: breakfast dish. Use morning-friendly plating and portioning, "
                "clean and comforting presentation."
            ),
            "lunch": (
                "Serving context: lunch main. Balanced portion, practical plated meal, realistic everyday serving."
            ),
            "dinner": (
                "Serving context: dinner main. Richer, heartier plating with complete meal feel."
            ),
            "snack": (
                "Serving context: snack/appetizer. Smaller portion, compact plating, easy-to-eat presentation."
            ),
            "dessert": (
                "Serving context: dessert. Refined sweet-course styling, tidy garnish, elegant plating."
            ),
            "beverage": (
                "Serving context: beverage. Focus on drink vessel, liquid texture, garnish and condensation/steam as relevant."
            ),
        }.get(
            dish_type,
            "Serving context: complete ready-to-serve dish with realistic portion and plating.",
        )
        cuisine_visual_hint = {
            "georgian": (
                "Cuisine style: Georgian. Prefer rustic, hearty Caucasian serving aesthetics and authentic color palette."
            ),
            "italian": (
                "Cuisine style: Italian. Keep Mediterranean warmth, simple elegant plating, authentic bistro/home trattoria mood."
            ),
            "french": (
                "Cuisine style: French. Slightly refined plating with classic European elegance, but still realistic."
            ),
            "japanese": (
                "Cuisine style: Japanese. Minimalist composition, clean lines, restrained garnish, authentic serving vessels."
            ),
            "chinese": (
                "Cuisine style: Chinese. Family-style realism or plated wok-style serving with authentic texture and gloss."
            ),
            "indian": (
                "Cuisine style: Indian. Rich spice tones, authentic serving context, realistic traditional presentation."
            ),
            "mexican": (
                "Cuisine style: Mexican. Vibrant colors, rustic handmade feel, authentic garnish and serving style."
            ),
            "thai": (
                "Cuisine style: Thai. Bright fresh accents, balanced composition, authentic Southeast Asian plating cues."
            ),
            "russian": (
                "Cuisine style: Russian/Eastern European. Home-style realistic serving, comforting and traditional presentation."
            ),
        }.get(
            cuisine,
            f"Cuisine style: {cuisine or 'generic'}; keep plating culturally plausible for this cuisine.",
        )
        # Детерминированная вариативность по id: картинки выглядят живее между рецептами.
        presentation_variants = (
            "Plating style: modern rustic ceramic plate, 3/4 angle.",
            "Plating style: minimalist restaurant plating, top-down view.",
            "Plating style: cozy homemade serving in a shallow bowl, 45-degree angle.",
            "Plating style: contemporary bistro style on matte stoneware, close-up framing.",
            "Plating style: elegant family-style portion, slight overhead angle with negative space.",
        )
        dish_type_presentation_variants = {
            "dessert": (
                "Dessert styling: refined plating with small garnish accents and clean negative space.",
                "Dessert styling: cafe patisserie look, elegant plate composition, close-up hero shot.",
            ),
            "beverage": (
                "Drink styling: focus on glass/cup, realistic liquid texture, natural highlights and garnish.",
                "Drink styling: tabletop beverage scene with vessel-centric framing and subtle props.",
            ),
            "snack": (
                "Snack styling: compact plated portion, finger-food friendliness, clear texture emphasis.",
                "Snack styling: small-share serving board or side plate, casual but appetizing presentation.",
            ),
        }
        light_variants = (
            "Lighting: soft natural daylight from side window.",
            "Lighting: warm evening ambient light with gentle shadows.",
            "Lighting: bright diffused daylight, clean and fresh mood.",
            "Lighting: cinematic side light, subtle contrast, realistic colors.",
            "Lighting: neutral studio-like daylight, soft highlights, no harsh reflections.",
        )
        presentation_pool = dish_type_presentation_variants.get(dish_type, presentation_variants)
        composition_variant = presentation_pool[recipe.id % len(presentation_pool)]
        light_variant = light_variants[recipe.id % len(light_variants)]
        sys_p = (
            "Write a single English paragraph: DALL·E prompt for professional food photography "
            "of the finished dish. "
            "The output must depict a real cooked final serving, not ingredient staging. "
            "No text, letters, watermarks, logos, split-screen, collages, or recipe cards in the image."
        )
        usr_p = (
            f"Dish title (Russian): {recipe.title}\n"
            f"Cook method code: {method or 'unknown'}\n"
            f"Dish type code: {dish_type or 'unknown'}\n"
            f"Cuisine code: {cuisine or 'unknown'}\n"
            f"Ingredients: {ing_preview}\n"
            f"Summary: {recipe.short_description}\n"
            f"{method_visual_hint}\n"
            f"{dish_type_visual_hint}\n"
            f"{cuisine_visual_hint}\n"
            "Important: represent the dish in its final edible state with integrated components. "
            "Avoid visual separation of ingredients into isolated zones.\n"
            f"{composition_variant}\n"
            f"{light_variant}\n"
            "Style: photorealistic food photography, high detail, realistic textures and colors."
        )
        prompt = await openai_ai.complete_text(sys_p, usr_p, max_tokens=200)
        if len(prompt) < 20:
            raise RuntimeError("пустой промпт для картинки")
        png = await openai_ai.generate_image_png_bytes(prompt)
        RECIPE_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        path = RECIPE_IMAGES_DIR / f"{recipe.id}.png"
        path.write_bytes(png)
        recipe.dish_image_path = str(path)
        recipe.save(only=[Recipe.dish_image_path])
    except Exception as e:
        logger.warning("ensure_dish_image id=%s: %s", recipe.id, e)


async def generate_and_persist_recipes(
    user: UsersData,
    terms: list[str],
    cook_method: str,
    *,
    cuisine_slug: str | None = None,
    cuisine_theme: str | None = None,
    progress: Callable[[str], Awaitable[None]] | None = None,
) -> list[Recipe]:
    max_n = 5
    min_n = 3
    base_user_prompt = _user_prompt(
        terms,
        cook_method,
        user,
        cuisine_slug=cuisine_slug,
        cuisine_theme=cuisine_theme,
    )
    final_items: list[dict] = []
    violations: list[str] = []
    for attempt in range(2):
        user_prompt = base_user_prompt
        if attempt > 0 and violations:
            user_prompt += (
                "\n\nSelf-check нарушения из предыдущей попытки:\n- "
                + "\n- ".join(violations[:12])
                + "\nИсправь все нарушения и верни только валидный JSON."
            )
        data = await openai_ai.chat_json_object(
            _system_prompt(max_n),
            user_prompt,
            max_tokens=config.OPENAI_RECIPE_MAX_TOKENS,
        )
        raw_list = data.get("recipes")
        if not isinstance(raw_list, list) or not raw_list:
            violations = ["empty:recipes"]
            continue
        checked, violations = _self_check_items(raw_list, terms, cook_method)
        checked, hard_violations = _apply_user_constraints_filter(
            checked,
            user,
            force_cook_method=cook_method,
        )
        violations.extend(hard_violations)
        if checked:
            final_items = checked
            break
    if not final_items:
        if _terms_look_like_dish_name_only(terms) and config.OPENAI_API_KEY:
            return await generate_and_persist_by_dish_name(
                user,
                terms[0].strip(),
                progress=progress,
                forced_cook_method=cook_method,
                cuisine_slug=cuisine_slug,
                cuisine_theme=cuisine_theme,
            )
        fallback_item = _build_simple_fallback_item(terms, cook_method)
        if fallback_item:
            final_items = [fallback_item]
    if len(final_items) < min_n:
        need = min_n - len(final_items)
        extra_items = await _generate_relaxed_items_for_shortage(
            need_count=need,
            terms=terms,
            cook_method=cook_method,
            user=user,
            cuisine_slug=cuisine_slug,
            cuisine_theme=cuisine_theme,
        )
        for item in extra_items:
            title_key = str(item.get("title") or "").strip().lower()
            if not title_key:
                continue
            exists = any(str(x.get("title") or "").strip().lower() == title_key for x in final_items)
            if not exists:
                final_items.append(item)
    final_items, hard_violations = _apply_user_constraints_filter(
        final_items,
        user,
        force_cook_method=cook_method,
    )
    if not final_items and hard_violations:
        raise ValueError("все recipes нарушили ограничения: " + "; ".join(hard_violations[:10]))
    if not final_items:
        raise ValueError("self-check: не удалось получить валидные рецепты")
    await _refine_recipe_titles_with_llm([x for x in final_items[:max_n] if isinstance(x, dict)])
    cuisine = cuisine_slug or _cuisine_slug(user)
    model_tag = config.OPENAI_CHAT_MODEL
    rows: list[dict] = []
    for item in final_items[:max_n]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if title and not _has_cyrillic(title):
            item["title"] = await _ensure_russian_line(title, what="название блюда")
        item["title"] = _polish_recipe_title(str(item.get("title") or ""), cook_method)
        item["title"] = _canonical_title_by_context(
            str(item.get("title") or ""),
            cuisine_slug=cuisine_slug,
            cuisine_theme=cuisine_theme,
            terms=terms,
            ingredients=[str(x) for x in (item.get("ingredients") or []) if isinstance(x, str)],
        )
        item["title"] = await _canonical_title_by_free_api(
            str(item.get("title") or ""),
            cuisine_slug=cuisine_slug,
            cuisine_theme=cuisine_theme,
            terms=terms,
            ingredients=[str(x) for x in (item.get("ingredients") or []) if isinstance(x, str)],
        )
        desc = str(item.get("short_description") or "").strip()
        if desc and not _has_cyrillic(desc):
            item["short_description"] = await _ensure_russian_line(desc, what="краткое описание")
        rows.append(
            _row_from_item(
                item,
                cuisine=cuisine,
                cook_method=cook_method,
                model_name=model_tag,
                cuisine_theme=cuisine_theme,
            )
        )
    if not rows:
        raise ValueError("не удалось разобрать рецепты")
    with db.atomic():
        created = [Recipe.create(**r) for r in rows]
    await _schedule_recipe_images(created, progress)
    return created
