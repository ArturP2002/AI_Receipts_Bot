from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
import re

import config
from database import Recipe, ensure_user, get_user
from enums import CookMethod, cook_method_label_ru
import keyboards
from services import limits, search
from services import openai_ai, recipe_openai
from settings_catalog import ALLERGY_CATALOG_KEYS, ALLERGY_CUSTOM_TYPE
import states
import texts
from tg_safe_edit import safe_delete_message

router = Router()

PAGE = 3


def _added_products_note_from_recipe(r: Recipe) -> str | None:
    text = (r.short_description or "").strip()
    marker = "добавлены недостающие продукты:"
    low = text.lower()
    idx = low.find(marker)
    if idx == -1:
        return None

    start = idx + len(marker)
    end = text.find(".", start)
    chunk = text[start:end] if end != -1 else text[start:]
    chunk = chunk.strip(" :")
    if not chunk:
        return None
    return "Недостающие продукты: " + chunk


async def _safe_callback_answer(call: CallbackQuery) -> None:
    try:
        await call.answer()
    except TelegramBadRequest as exc:
        # Некритично: пользователь нажал кнопку слишком давно, Telegram инвалидирует query id.
        if "query is too old" in str(exc).lower() or "query id is invalid" in str(exc).lower():
            return
        raise


async def render_products_waiting_screen(
    message,
    *,
    edit: bool = False,
    cuisine_label: str | None = None,
    back_callback: str = "main_menu",
    back_text: str = "🔙 Назад",
) -> None:
    body = texts.ADD_PRODUCTS_PROMPT
    if cuisine_label:
        body = texts.ADD_PRODUCTS_PROMPT_STRICT
        body += f"\n\n🌍 Выбрана кухня: {cuisine_label}\nПодберу рецепты по продуктам в стиле этой кухни."
    kb = keyboards.products_entry_kb(back_callback=back_callback, back_text=back_text)
    if edit:
        await message.edit_text(body, reply_markup=kb)
    else:
        await message.answer(body, reply_markup=kb)


def _product_terms_from_text(text: str) -> list[str]:
    """Список продуктов: через запятую или через пробел."""
    t = text.strip()
    if not t:
        return []
    if "," in t:
        return [x.strip() for x in t.split(",") if x.strip()]
    return [x.strip() for x in t.split() if x.strip()]


def _looks_like_dish_request_text(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    dish_markers = (
        "хочу рецепт",
        "нужен рецепт",
        "дай рецепт",
        "рецепт блюда",
        "как приготовить",
        "приготовить",
    )
    return any(marker in t for marker in dish_markers)


def _normalize_dish_query_text(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    cleaned = re.sub(r"\s+", " ", t).strip()
    # Убираем типичные вводные, но сохраняем смысловые слова блюда/кухни/продуктов.
    cleaned = re.sub(
        r"\b(хочу|нужен|нужна|нужно|давай|пожалуйста|подскажи|дай)\b",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\b(рецепт|блюда|блюдо)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.-")
    return cleaned or t


_DISH_NAME_SINGLE_WORD_MARKERS = {
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
}


def _looks_like_dish_query_from_products_text(text: str) -> bool:
    """Эвристика: пользователь ввёл название блюда в поле продуктов."""
    t = (text or "").strip().lower()
    if not t:
        return False

    # Частый паттерн каноничных блюд: "мясо по-французски", "курица по-гречески", ...
    if re.search(r"\bпо[-\s]", t):
        return True

    # Отдельные "однословные" названия.
    for w in re.split(r"[\s,]+", t):
        w = w.strip().lower()
        if w in _DISH_NAME_SINGLE_WORD_MARKERS:
            return True

    return False


async def _classify_products_or_dish_query_with_ai(text: str) -> tuple[bool, str]:
    """
    ИИ-классификатор: что написал пользователь в поле "продукты",
    если это на самом деле запрос блюда — вернём dish_query.
    """
    raw = (text or "").strip()
    if not raw:
        return False, ""

    if not config.OPENAI_API_KEY:
        # Fallback без сети/ключа.
        return _looks_like_dish_query_from_products_text(raw), _normalize_dish_query_text(raw)

    system = (
        "Ты классификатор для Telegram-бота. "
        "Определи, является ли текст пользователя запросом блюда/названием блюда (dish) "
        "или списком продуктов (products). "
        "Верни строго JSON формата: "
        '{"kind":"dish"|"products","dish_query":string}. '
        "Правила: "
        "- kind='dish', если текст звучит как название блюда или запрос 'как приготовить ...' "
        "  (например: 'мясо по-французски', 'как приготовить сациви'). "
        "- kind='products', если текст выглядит как перечень ингредиентов/продуктов "
        "  (например: 'курица, орехи', 'курица орехи лук'). "
        "- dish_query: "
        "  * если kind='dish' — верни кратко суть запроса на русском, без лишних фраз, "
        "  * иначе dish_query='' . "
        "Без лишних ключей, без комментариев."
    )
    user = f"Текст пользователя: {raw}"
    try:
        data = await openai_ai.chat_json_object(system, user, max_tokens=180, temperature=0)
    except Exception:
        # fallback
        return _looks_like_dish_query_from_products_text(raw), _normalize_dish_query_text(raw)

    if not isinstance(data, dict):
        return _looks_like_dish_query_from_products_text(raw), _normalize_dish_query_text(raw)

    kind = str(data.get("kind") or "").strip().lower()
    dish_query = str(data.get("dish_query") or "").strip()
    if kind == "dish" and dish_query:
        return True, _normalize_dish_query_text(dish_query)
    if kind == "dish":
        # Если AI сказала dish, но пусто — используем нормализованный вход.
        return True, _normalize_dish_query_text(raw)
    if kind == "products":
        return False, ""
    # На случай непредвиденного ответа.
    return _looks_like_dish_query_from_products_text(raw), _normalize_dish_query_text(raw)


def _extra_products_hint(terms: list[str], method: str) -> str:
    base = [t.lower() for t in terms if t.strip()]
    add: list[str] = []
    if "куриц" in " ".join(base):
        add = ["лук", "чеснок", "сметана"]
    elif any("яйц" in x for x in base):
        add = ["лук", "сыр", "зелень"]
    elif any("карто" in x for x in base):
        add = ["лук", "грибы", "сыр"]
    elif any("говядин" in x or "свинин" in x for x in base):
        add = ["лук", "морковь", "сливки"]
    else:
        add = ["лук", "чеснок", "сыр"]

    if method == CookMethod.BAKE.value and "сливки" not in add:
        add[-1] = "сливки"
    if method == CookMethod.BOIL.value and "морковь" not in add:
        add[0] = "морковь"
    return f"💡 Сейчас получился только 1 рецепт. Добавь, например: {', '.join(add)} — и я попробую подобрать ещё 1-2 варианта."


def _json_list(raw: str) -> list:
    try:
        import json

        v = json.loads(raw or "[]")
        return v if isinstance(v, list) else []
    except Exception:
        return []


def _allergy_conflicts_for_terms(user, terms: list[str]) -> list[str]:
    allergy_needles = {
        "nuts": ("орехи", ("орех", "грец", "арахис", "фундук", "миндал")),
        "seafood": ("морепродукты", ("морепродукт", "кревет", "кальмар", "миди", "устриц")),
        "eggs": ("яйца", ("яйц", "омлет")),
        "gluten": ("глютен", ("глютен", "пшениц", "мук", "ржан", "ячмен")),
        "lactose": ("лактоза", ("молок", "сыр", "сливк", "творог", "йогурт", "сметан")),
        "citrus": ("цитрусовые", ("цитрус", "лимон", "лайм", "апельсин", "грейпфрут")),
        "tomatoes": ("томаты", ("томат", "помидор")),
        "spicy": ("острое", ("чили", "кайенн", "халапеньо", "остр")),
        "mushrooms": ("грибы", ("гриб", "шампиньон", "вешенк", "лисич")),
    }
    terms_norm = [t.strip().lower() for t in terms if t.strip()]
    if not terms_norm:
        return []
    selected_catalog = {
        x for x in _json_list(getattr(user, "allergies_strict_json", "[]")) if isinstance(x, str) and x in ALLERGY_CATALOG_KEYS
    }
    custom_items = [
        (x.get("l") or "").strip().lower()
        for x in _json_list(getattr(user, "allergies_strict_json", "[]"))
        if isinstance(x, dict) and x.get("type") == ALLERGY_CUSTOM_TYPE and (x.get("l") or "").strip()
    ]
    conflicts: list[str] = []
    for key in selected_catalog:
        ru_label, needles = allergy_needles.get(key, (key, (key,)))
        if any(any(n in term for n in needles) for term in terms_norm):
            conflicts.append(ru_label)
    for custom in custom_items:
        pieces = [custom] + [p for p in re.split(r"[\s,;]+", custom) if len(p) >= 2]
        if any(any(p in term for p in pieces) for term in terms_norm):
            conflicts.append(custom)
    # dedupe with order
    return list(dict.fromkeys(conflicts))


async def _go_choose_method(message: Message, state: FSMContext, user_text: str, cuisine_label: str | None) -> None:
    user = ensure_user(message.from_user.id)
    limits.append_search_history(user, user_text, "products")
    await state.update_data(products_text=user_text, dish_query=None)
    await state.set_state(states.ProductsFlow.choose_cook_method)
    ask_method = texts.CHOOSE_COOK_METHOD
    if cuisine_label:
        ask_method += f"\n\n🌍 Кухня: {cuisine_label}"
    await message.answer(ask_method, reply_markup=keyboards.cook_method_main_kb())


async def _go_dish_query(message: Message, state: FSMContext, query_text: str) -> None:
    user = ensure_user(message.from_user.id)
    flow_data = await state.get_data()
    cuisine_slug = flow_data.get("products_cuisine_slug")
    cuisine_label = flow_data.get("products_cuisine_display")
    limits.append_search_history(user, query_text, "dish_query")
    if search.is_query_too_vague_for_dish_search(query_text):
        await message.answer(texts.DISH_QUERY_CLARIFY, reply_markup=keyboards.dish_query_clarify_kb())
        return

    has_key = bool(config.OPENAI_API_KEY)
    if not has_key:
        await message.answer(texts.AI_NO_KEY)
        return

    thinking_msg = await message.answer(texts.AI_THINKING)
    try:

        async def _progress(stage: str) -> None:
            if thinking_msg and stage == "images":
                try:
                    await thinking_msg.edit_text(texts.AI_THINKING_IMAGES)
                except Exception:
                    pass

        found = await recipe_openai.generate_and_persist_by_dish_name(
            user,
            query_text,
            progress=_progress,
            cuisine_slug=cuisine_slug,
            cuisine_theme=cuisine_label,
        )
    except Exception:
        if thinking_msg:
            await safe_delete_message(thinking_msg)
        await message.answer(
            texts.NO_RESULTS,
            reply_markup=keyboards.no_results_kb("products"),
        )
        return
    if thinking_msg:
        await safe_delete_message(thinking_msg)

    await state.update_data(
        products_text=query_text,
        dish_query=query_text,
        cook_method="",
        result_ids=[r.id for r in found],
        list_offset=0,
        list_ctx="products",
    )
    await state.set_state(states.ProductsFlow.browsing_results)
    if not found:
        await message.answer(
            texts.NO_RESULTS,
            reply_markup=keyboards.no_results_kb("products"),
        )
        return
    await _send_dish_query_results(
        message.bot,
        message.chat.id,
        found,
        query_text,
        offset=0,
        list_ctx="products",
        more_cb="pr:more",
        cuisine_label=cuisine_label,
    )


async def _send_results_message(
    bot: Bot,
    chat_id: int,
    recipes: list[Recipe],
    method_label: str,
    *,
    offset: int,
    list_ctx: str,
    more_cb: str,
    cuisine_label: str | None = None,
    extra_hint: str | None = None,
):
    chunk = recipes[offset : offset + PAGE]
    if not chunk:
        await bot.send_message(
            chat_id,
            texts.NO_RESULTS,
            reply_markup=keyboards.no_results_kb(list_ctx),
        )
        return
    head = f"🍳 Вот что можно приготовить способом: {method_label}\n"
    if cuisine_label:
        head += f"🌍 Кухня: {cuisine_label}\n"
    head += "\n"
    lines = [f"{i + 1 + offset}. {r.title} — {r.time_minutes} мин" for i, r in enumerate(chunk)]
    body = head + "\n".join(lines) + "\n\nНажми на рецепт, чтобы открыть карточку."
    extras = []
    for i, r in enumerate(chunk):
        note = _added_products_note_from_recipe(r)
        if note:
            extras.append(f"{i + 1 + offset}. {note}")
    if extras:
        body += "\n\n⚠️ Для части рецептов добавлены недостающие продукты:\n" + "\n".join(extras)
    if extra_hint:
        body += f"\n\n{extra_hint}"
    show_more = offset + PAGE < len(recipes)
    await bot.send_message(
        chat_id,
        body,
        reply_markup=keyboards.recipe_list_kb(
            chunk,
            settings_ctx=list_ctx,
            show_more=show_more,
            more_callback=more_cb,
        ),
    )


async def _send_dish_query_results(
    bot: Bot,
    chat_id: int,
    recipes: list[Recipe],
    query_display: str,
    *,
    offset: int,
    list_ctx: str,
    more_cb: str,
    cuisine_label: str | None = None,
):
    chunk = recipes[offset : offset + PAGE]
    if not chunk:
        await bot.send_message(
            chat_id,
            texts.NO_RESULTS,
            reply_markup=keyboards.no_results_kb(list_ctx),
        )
        return
    safe_q = (query_display or "").replace("«", "").replace("»", "").strip() or "запрос"
    head = f"Есть варианты по запросу «{safe_q}»:\n"
    if cuisine_label:
        head += f"🌍 Кухня: {cuisine_label}\n"
    head += "\n"
    lines = [f"{i + 1 + offset}. {r.title} — {r.time_minutes} мин" for i, r in enumerate(chunk)]
    body = head + "\n".join(lines) + "\n\nНажми на рецепт, чтобы открыть карточку."
    extras = []
    for i, r in enumerate(chunk):
        note = _added_products_note_from_recipe(r)
        if note:
            extras.append(f"{i + 1 + offset}. {note}")
    if extras:
        body += "\n\n⚠️ Для части рецептов добавлены недостающие продукты:\n" + "\n".join(extras)
    show_more = offset + PAGE < len(recipes)
    await bot.send_message(
        chat_id,
        body,
        reply_markup=keyboards.recipe_list_kb(
            chunk,
            settings_ctx=list_ctx,
            show_more=show_more,
            more_callback=more_cb,
        ),
    )


@router.callback_query(F.data == "add_products")
async def add_products_entry(call: CallbackQuery, state: FSMContext):
    await state.set_state(states.ProductsFlow.waiting_input)
    await state.update_data(
        products_cuisine_slug=None,
        products_cuisine_display=None,
        products_back_callback="main_menu",
        products_back_text="🔙 Назад",
    )
    await render_products_waiting_screen(call.message, edit=True)
    await call.answer()


@router.callback_query(F.data == "pr:retry")
async def products_retry(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.set_state(states.ProductsFlow.waiting_input)
    await render_products_waiting_screen(
        call.message,
        edit=True,
        cuisine_label=data.get("products_cuisine_display"),
        back_callback=data.get("products_back_callback") or "main_menu",
        back_text=data.get("products_back_text") or "🔙 Назад",
    )
    await call.answer()


@router.message(states.ProductsFlow.waiting_input, F.text)
async def products_got_text(message: Message, state: FSMContext):
    text = message.text.strip()
    data = await state.get_data()
    cuisine_label = data.get("products_cuisine_display")
    if not text:
        await message.answer("Напиши хотя бы один продукт — через запятую или через пробел.")
        return

    user = ensure_user(message.from_user.id)
    terms = _product_terms_from_text(text)
    if not terms:
        await message.answer("Напиши хотя бы один продукт — через запятую или через пробел.")
        return
    conflicts = _allergy_conflicts_for_terms(user, terms)
    if conflicts:
        await message.answer(
            "⚠️ В списке есть продукты, которые у тебя отмечены как противопоказанные: "
            + ", ".join(conflicts)
            + ".\n"
            "Убери их из списка и отправь продукты еще раз в этот чат — тогда я продолжу подбор.\n\n"
            "Если ограничения изменились, открой «⚙️ Настроить рецепт → 🚫 Аллергии» и обнови список."
            ,
            reply_markup=keyboards.allergy_conflict_kb(),
        )
        return

    # В режиме выбранной кухни — всегда трактуем как продукты.
    if cuisine_label:
        await _go_choose_method(message, state, text, cuisine_label)
        return

    if _looks_like_dish_request_text(text):
        await _go_dish_query(message, state, _normalize_dish_query_text(text))
        return

    # С запятыми — это явный список продуктов.
    if "," in text:
        await _go_choose_method(message, state, text, cuisine_label)
        return

    # Без запятых ввод неоднозначный: уточняем, это продукты или блюдо.
    await state.update_data(pending_input_text=text)
    await state.set_state(states.ProductsFlow.disambiguate_input)
    await message.answer(texts.PRODUCTS_KIND_ASK, reply_markup=keyboards.products_kind_kb())


@router.callback_query(states.ProductsFlow.disambiguate_input, F.data == "pr_kind:products")
async def products_kind_products(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    text = (data.get("pending_input_text") or "").strip()
    cuisine_label = data.get("products_cuisine_display")
    if not text:
        await state.set_state(states.ProductsFlow.waiting_input)
        await render_products_waiting_screen(call.message, edit=True, cuisine_label=cuisine_label)
        await _safe_callback_answer(call)
        return
    await _go_choose_method(call.message, state, text, cuisine_label)
    await _safe_callback_answer(call)


@router.callback_query(states.ProductsFlow.disambiguate_input, F.data == "pr_kind:dish")
async def products_kind_dish(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    text = (data.get("pending_input_text") or "").strip()
    if not text:
        await state.set_state(states.ProductsFlow.waiting_input)
        await render_products_waiting_screen(call.message, edit=True)
        await _safe_callback_answer(call)
        return
    await _go_dish_query(call.message, state, text)
    await _safe_callback_answer(call)


@router.callback_query(F.data == "pr:back_input")
async def products_back_input(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.set_state(states.ProductsFlow.waiting_input)
    await render_products_waiting_screen(
        call.message,
        edit=True,
        cuisine_label=data.get("products_cuisine_display"),
        back_callback=data.get("products_back_callback") or "main_menu",
        back_text=data.get("products_back_text") or "🔙 Назад",
    )
    await call.answer()


@router.callback_query(F.data == "pr:back_method_main")
async def products_back_method(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.set_state(states.ProductsFlow.choose_cook_method)
    body = texts.CHOOSE_COOK_METHOD
    cuisine_label = data.get("products_cuisine_display")
    if cuisine_label:
        body += f"\n\n🌍 Кухня: {cuisine_label}"
    await call.message.edit_text(body, reply_markup=keyboards.cook_method_main_kb())
    await call.answer()


@router.callback_query(F.data.startswith("cm:"))
async def products_cook_method(call: CallbackQuery, state: FSMContext):
    raw = call.data.split(":", 1)[1]
    if raw == CookMethod.OTHER.value:
        await state.set_state(states.ProductsFlow.choose_cook_method_extra)
        await call.message.edit_text(texts.CHOOSE_COOK_METHOD_EXTRA, reply_markup=keyboards.cook_method_extra_kb())
        await call.answer()
        return

    await call.answer()
    await _apply_method_and_search(call, state, raw)


async def _apply_method_and_search(call: CallbackQuery, state: FSMContext, method: str):
    data = await state.get_data()
    text = data.get("products_text", "")
    cuisine_slug = data.get("products_cuisine_slug")
    cuisine_label = data.get("products_cuisine_display")
    user = ensure_user(call.from_user.id)
    terms = _product_terms_from_text(text)
    has_key = bool(config.OPENAI_API_KEY)
    if not has_key:
        await safe_delete_message(call.message)
        await call.bot.send_message(call.from_user.id, texts.AI_NO_KEY)
        return

    thinking_msg = await call.message.answer(texts.AI_THINKING)
    await safe_delete_message(call.message)
    try:

        async def _progress(stage: str) -> None:
            if thinking_msg and stage == "images":
                try:
                    await thinking_msg.edit_text(texts.AI_THINKING_IMAGES)
                except Exception:
                    pass

        is_dish, dish_query = await _classify_products_or_dish_query_with_ai(text)
        if is_dish:
            found = await recipe_openai.generate_and_persist_by_dish_name(
                user,
                dish_query or _normalize_dish_query_text(text),
                progress=_progress,
                forced_cook_method=method,
                cuisine_slug=cuisine_slug,
                cuisine_theme=cuisine_label,
            )
        else:
            found = await recipe_openai.generate_and_persist_recipes(
                user,
                terms,
                method,
                cuisine_slug=cuisine_slug,
                cuisine_theme=cuisine_label,
                progress=_progress,
            )
    except Exception:
        if thinking_msg:
            await safe_delete_message(thinking_msg)
        await call.bot.send_message(
            call.from_user.id,
            texts.NO_RESULTS,
            reply_markup=keyboards.no_results_kb("products"),
        )
        return
    if thinking_msg:
        await safe_delete_message(thinking_msg)
    await state.update_data(
        cook_method=method,
        dish_query=None,
        result_ids=[r.id for r in found],
        list_offset=0,
        list_ctx="products",
    )
    await state.set_state(states.ProductsFlow.browsing_results)
    label = cook_method_label_ru(method)
    if not found:
        await call.bot.send_message(
            call.from_user.id,
            texts.NO_RESULTS,
            reply_markup=keyboards.no_results_kb("products"),
        )
        return
    one_recipe_hint = _extra_products_hint(terms, method) if len(found) == 1 else None
    await _send_results_message(
        call.bot,
        call.from_user.id,
        found,
        label,
        offset=0,
        list_ctx="products",
        more_cb="pr:more",
        cuisine_label=cuisine_label,
        extra_hint=one_recipe_hint,
    )


@router.callback_query(F.data == "pr:more")
async def products_show_more(call: CallbackQuery, state: FSMContext):
    user = get_user(call.from_user.id)
    if not user:
        await call.answer("Ошибка", show_alert=True)
        return
    data = await state.get_data()
    ids = data.get("result_ids") or []
    offset = int(data.get("list_offset") or 0) + PAGE
    if offset >= len(ids):
        await call.answer("Больше нет")
        return
    if not limits.can_use_free_show_more(user):
        from handlers.payments import send_show_more_invoice

        await send_show_more_invoice(call.message, call.from_user.id, state)
        await call.answer()
        return
    limits.increment_free_show_more(user)
    await state.update_data(list_offset=offset)
    ordered = [Recipe.get_by_id(i) for i in ids]
    dish_q = data.get("dish_query")
    method = data.get("cook_method", "")
    cuisine_label = data.get("products_cuisine_display")
    await safe_delete_message(call.message)
    if dish_q:
        await _send_dish_query_results(
            call.bot,
            call.from_user.id,
            ordered,
            dish_q,
            offset=offset,
            list_ctx="products",
            more_cb="pr:more",
            cuisine_label=cuisine_label,
        )
    else:
        label = cook_method_label_ru(method) if method else "подбор"
        await _send_results_message(
            call.bot,
            call.from_user.id,
            ordered,
            label,
            offset=offset,
            list_ctx="products",
            more_cb="pr:more",
            cuisine_label=cuisine_label,
        )
    await call.answer()


@router.callback_query(F.data == "list_back:products")
async def list_back_products(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if data.get("cook_method"):
        await state.set_state(states.ProductsFlow.choose_cook_method)
        body = texts.CHOOSE_COOK_METHOD
        cuisine_label = data.get("products_cuisine_display")
        if cuisine_label:
            body += f"\n\n🌍 Кухня: {cuisine_label}"
        await call.message.edit_text(body, reply_markup=keyboards.cook_method_main_kb())
    else:
        await state.set_state(states.ProductsFlow.waiting_input)
        await render_products_waiting_screen(
            call.message,
            edit=True,
            cuisine_label=data.get("products_cuisine_display"),
            back_callback=data.get("products_back_callback") or "main_menu",
            back_text=data.get("products_back_text") or "🔙 Назад",
        )
    await call.answer()
