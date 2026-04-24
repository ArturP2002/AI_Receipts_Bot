import json

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from data.cuisine_catalog import (
    ALL_CUISINE_SLUG_SET,
    FAVORITE_CUSTOM_TYPE,
    MORE_CUISINES,
    POPULAR_CUISINES,
    free_cuisine_slug,
    resolve_cuisine_from_text,
    summary_labels_favorites,
)
from database import ensure_user
from enums import DISH_TYPE_LABEL_RU, DishType, cook_method_label_ru
import keyboards
from settings_catalog import (
    ALLERGY_CATALOG_KEYS,
    ALLERGY_CUSTOM_TYPE,
    ALLERGY_OPTIONS,
    BUDGET_OPTIONS,
    DEFAULT_DIET_PROFILE,
    DIET_MODES,
    DIETETIC_TABLES,
    DIFFICULTY_OPTIONS,
    FITNESS_OPTIONS,
    PREFERRED_COOK_METHODS,
)
import states
import texts
from tg_safe_edit import safe_delete_message, safe_edit_text

router = Router()

DIETETIC_HINTS = (
    "⚠️ Диетические столы\n"
    "Отметьте столы по назначению врача — подходящие рецепты будут чаще попадать в подбор.\n\n"
    + "\n".join(f"• {lab}" for _k, lab in DIETETIC_TABLES)
)

_DIETETIC_KEY_TO_LABEL = dict(DIETETIC_TABLES)
_DIFFICULTY_KEY_TO_LABEL = dict(DIFFICULTY_OPTIONS)
_BUDGET_KEY_TO_LABEL = dict(BUDGET_OPTIONS)


async def _settings_cuisine_prefix(state: FSMContext) -> str:
    data = await state.get_data()
    ctx = data.get("settings_back_ctx")
    if ctx not in {"cuisine_hub", "cuisine"}:
        return ""
    lab = (data.get("cuisine_display") or "").strip()
    if not lab:
        return ""
    return f"🌍 Выбрана кухня: {lab}\n\n"


async def _with_settings_cuisine_prefix(state: FSMContext, body: str) -> str:
    return f"{await _settings_cuisine_prefix(state)}{body}"


def _dietetic_summary_ru(keys: list[str]) -> str:
    if not keys:
        return "не выбраны"
    return ", ".join(_DIETETIC_KEY_TO_LABEL.get(k, k) for k in keys)


def _difficulty_summary_ru(keys: list[str]) -> str:
    if not keys:
        return "любая"
    return ", ".join(_DIFFICULTY_KEY_TO_LABEL.get(k, k) for k in keys)


def _budget_summary_ru(tier: str | None) -> str:
    return _BUDGET_KEY_TO_LABEL.get(tier or "any", tier or "любой")


def _loads(raw: str) -> list:
    try:
        v = json.loads(raw or "[]")
        return v if isinstance(v, list) else []
    except json.JSONDecodeError:
        return []


def _dumps(lst: list) -> str:
    return json.dumps(lst, ensure_ascii=False)


def _load_diet(user) -> dict:
    try:
        d = json.loads(getattr(user, "diet_profile_json", None) or "{}")
    except json.JSONDecodeError:
        d = {}
    if not isinstance(d, dict):
        d = {}
    return {**DEFAULT_DIET_PROFILE, **d}


def _save_diet(user, d: dict) -> None:
    if d.get("mode") == "vegan":
        d["no_eggs"] = True
        d["no_dairy"] = True
    user.diet_profile_json = json.dumps(d, ensure_ascii=False)
    user.save()


def _diet_kb(d: dict):
    b = InlineKeyboardBuilder()
    mode = d.get("mode", "omnivore")
    for key, label in DIET_MODES:
        mark = "✓ " if mode == key else ""
        b.add(InlineKeyboardButton(text=f"{mark}{label}", callback_data=f"stv:mode:{key}"))
    b.adjust(1)
    b.add(
        InlineKeyboardButton(
            text=f"{'✓ ' if d.get('no_eggs') else ''}🥚 Без яиц",
            callback_data="stv:egg:toggle",
        ),
        InlineKeyboardButton(
            text=f"{'✓ ' if d.get('no_dairy') else ''}🥛 Без молочного",
            callback_data="stv:milk:toggle",
        ),
    )
    b.adjust(2)
    b.add(InlineKeyboardButton(text="✔️ Готово", callback_data="stv:done"))
    b.add(InlineKeyboardButton(text="🔙 Назад", callback_data="st:root"))
    b.adjust(1)
    return b.as_markup()


async def enter_settings(message: Message, state: FSMContext, *, edit: bool = False) -> None:
    await state.set_state(states.SettingsFlow.root)
    body = await _with_settings_cuisine_prefix(state, texts.SETTINGS_MAIN)
    if edit:
        await message.edit_text(body, reply_markup=keyboards.settings_root_kb())
    else:
        await message.answer(body, reply_markup=keyboards.settings_root_kb())


@router.callback_query(F.data == "st:root")
async def settings_root(call: CallbackQuery, state: FSMContext):
    await enter_settings(call.message, state, edit=True)
    await call.answer()


# --- 1. Кухни ---
def _catalog_slugs_selected(cur: list) -> set[str]:
    return {x for x in cur if isinstance(x, str)}


async def _render_settings_cuisines_ui(
    message: Message,
    uid: int,
    *,
    edit: bool,
    state: FSMContext | None = None,
) -> None:
    if state is not None:
        await state.set_state(states.SettingsFlow.cuisines)
    user = ensure_user(uid)
    cur = _loads(user.favorite_cuisines_json)
    sel = _catalog_slugs_selected(cur)
    b = InlineKeyboardBuilder()
    for slug, label in POPULAR_CUISINES + MORE_CUISINES:
        mark = "✓ " if slug in sel else ""
        b.add(InlineKeyboardButton(text=f"{mark}{label}", callback_data=f"stc:{slug}"))
    b.adjust(2)
    mid = InlineKeyboardBuilder()
    mid.add(
        InlineKeyboardButton(text="✍️ Добавить свою кухню", callback_data="st:cuisines_add"),
    )
    for x in cur:
        if isinstance(x, dict) and x.get("type") == FAVORITE_CUSTOM_TYPE:
            lab = (x.get("l") or "?")[:40]
            sid = x.get("s") or ""
            if sid:
                mid.add(
                    InlineKeyboardButton(
                        text=f"✓ ✍️ {lab}",
                        callback_data=f"stcr:{sid}",
                    ),
                )
    mid.adjust(1)
    foot = InlineKeyboardBuilder()
    foot.add(InlineKeyboardButton(text="✔️ Готово", callback_data="st:cuisines_done"))
    foot.add(InlineKeyboardButton(text="🔙 Назад", callback_data="st:root"))
    foot.adjust(1)
    b.attach(mid)
    b.attach(foot)
    body = (
        "🍽 Какие кухни тебе нравятся?\n"
        "Выбери кнопками или добавь свою кухню/страну текстом.\n\n"
        "Кухню из списка можно снять повторным нажатием; "
        "свою — нажатием на строку «✓ ✍️ …» ниже."
    )
    if edit:
        await message.edit_text(body, reply_markup=b.as_markup())
    else:
        await message.answer(body, reply_markup=b.as_markup())


@router.callback_query(F.data == "st:cuisines")
async def settings_cuisines(call: CallbackQuery, state: FSMContext):
    await _render_settings_cuisines_ui(call.message, call.from_user.id, edit=True, state=state)
    await call.answer()


@router.callback_query(F.data == "st:cuisines_add")
async def settings_cuisines_add_prompt(call: CallbackQuery, state: FSMContext):
    await state.set_state(states.SettingsFlow.cuisines_add)
    cancel = InlineKeyboardBuilder()
    cancel.add(InlineKeyboardButton(text="🔙 Отмена", callback_data="st:cuisines"))
    await call.message.edit_text(
        "✍️ Напиши кухню или страну одним сообщением.\n"
        "Например: «скандинавская», «Польша», «ближневосточная».\n\n"
        "Если это кухня из списка кнопок — она отметится галочкой; "
        "иначе сохраню как свою подпись для приоритета в выдаче.",
        reply_markup=cancel.as_markup(),
    )
    await call.answer()


@router.message(states.SettingsFlow.cuisines_add, F.text)
async def settings_cuisines_add_got_text(message: Message, state: FSMContext):
    raw = message.text.strip()
    if raw.startswith("/"):
        await message.answer("Напиши название кухни текстом или нажми «Отмена».")
        return
    user = ensure_user(message.from_user.id)
    cur = _loads(user.favorite_cuisines_json)
    slug, disp = resolve_cuisine_from_text(raw)
    if slug in ALL_CUISINE_SLUG_SET:
        if slug not in [x for x in cur if isinstance(x, str)]:
            cur.append(slug)
            user.favorite_cuisines_json = _dumps(cur)
            user.save()
            await message.answer(f"Добавлено в список: {disp}")
        else:
            await message.answer("Эта кухня уже отмечена в списке кнопок.")
    else:
        label_plain = disp[2:].strip() if disp.startswith("🌍 ") else disp
        label_plain = label_plain.replace("🌍", "").strip()[:120]
        dup = any(
            isinstance(x, dict)
            and x.get("type") == FAVORITE_CUSTOM_TYPE
            and x.get("s") == slug
            for x in cur
        )
        if dup:
            await message.answer("Такая кухня уже добавлена. Чтобы убрать — нажми на неё в списке.")
        else:
            cur.append(
                {
                    "type": FAVORITE_CUSTOM_TYPE,
                    "l": label_plain or raw[:120],
                    "s": slug,
                },
            )
            user.favorite_cuisines_json = _dumps(cur)
            user.save()
            await message.answer(f"Добавлено: {label_plain or raw}")
    await _render_settings_cuisines_ui(message, message.from_user.id, edit=False, state=state)


@router.callback_query(F.data.startswith("stcr:"))
async def settings_cuisine_remove_custom(call: CallbackQuery, state: FSMContext):
    sid = call.data[5:]
    if not sid:
        await call.answer()
        return
    user = ensure_user(call.from_user.id)
    cur = _loads(user.favorite_cuisines_json)
    new = [
        x
        for x in cur
        if not (
            isinstance(x, dict)
            and x.get("type") == FAVORITE_CUSTOM_TYPE
            and x.get("s") == sid
        )
    ]
    if len(new) == len(cur):
        await call.answer("Не найдено")
        return
    user.favorite_cuisines_json = _dumps(new)
    user.save()
    await _render_settings_cuisines_ui(call.message, call.from_user.id, edit=True, state=state)
    await call.answer("Убрано")


@router.callback_query(F.data.startswith("stc:"))
async def settings_cuisine_toggle(call: CallbackQuery, state: FSMContext):
    slug = call.data.split(":", 1)[1]
    user = ensure_user(call.from_user.id)
    cur = _loads(user.favorite_cuisines_json)
    if slug in cur:
        cur.remove(slug)
    else:
        cur.append(slug)
    user.favorite_cuisines_json = _dumps(cur)
    user.save()
    await _render_settings_cuisines_ui(call.message, call.from_user.id, edit=True, state=state)


@router.callback_query(F.data == "st:cuisines_done")
async def settings_cuisines_done(call: CallbackQuery, state: FSMContext):
    user = ensure_user(call.from_user.id)
    cur = _loads(user.favorite_cuisines_json)
    body = (
        f"✅ Выбрано: {summary_labels_favorites(cur)}\n"
        f"Теперь эти кухни — в приоритете в выдаче."
    )
    await call.message.edit_text(
        await _with_settings_cuisine_prefix(state, body),
        reply_markup=keyboards.settings_done_kb(),
    )
    await call.answer()


# --- 2. Вегетарианство ---
@router.callback_query(F.data == "st:diet_veg")
async def settings_diet_veg(call: CallbackQuery, state: FSMContext):
    await state.set_state(states.SettingsFlow.diet_veg)
    user = ensure_user(call.from_user.id)
    d = _load_diet(user)
    await call.message.edit_text(
        "🌿 Вегетарианство и веганство\n"
        "Режим питания и отдельно яйца / молочные (для режима «обычное»).\n"
        "При веганском режиме яйца и молочное отключаются автоматически.",
        reply_markup=_diet_kb(d),
    )
    await call.answer()


@router.callback_query(F.data.startswith("stv:"))
async def settings_diet_veg_actions(call: CallbackQuery, state: FSMContext):
    user = ensure_user(call.from_user.id)
    d = _load_diet(user)
    parts = call.data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    if action == "done":
        _save_diet(user, d)
        body = f"✅ Режим: {d.get('mode')}, без яиц: {d.get('no_eggs')}, без молочного: {d.get('no_dairy')}"
        await call.message.edit_text(
            await _with_settings_cuisine_prefix(state, body),
            reply_markup=keyboards.settings_done_kb(),
        )
        await call.answer()
        return
    if action == "mode" and len(parts) > 2:
        d["mode"] = parts[2]
        if d["mode"] == "vegan":
            d["no_eggs"] = True
            d["no_dairy"] = True
    elif action == "egg" and len(parts) > 2 and parts[2] == "toggle":
        d["no_eggs"] = not d.get("no_eggs", False)
    elif action == "milk" and len(parts) > 2 and parts[2] == "toggle":
        d["no_dairy"] = not d.get("no_dairy", False)
    _save_diet(user, d)
    await call.message.edit_reply_markup(reply_markup=_diet_kb(d))
    await call.answer()


# --- 3. Халяль ---
@router.callback_query(F.data == "st:halal")
async def settings_halal_menu(call: CallbackQuery, state: FSMContext):
    await state.set_state(states.SettingsFlow.halal)
    user = ensure_user(call.from_user.id)
    on = user.halal_only
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text=f"{'✓ ' if on else ''}Да, только халяль", callback_data="sth:1"),
    )
    b.row(
        InlineKeyboardButton(text=f"{'✓ ' if not on else ''}Нет", callback_data="sth:0"),
        InlineKeyboardButton(text="✔️ Готово", callback_data="st:done"),
    )
    b.row(InlineKeyboardButton(text="🔙 Назад", callback_data="st:root"))
    await safe_edit_text(
        call.message,
        "🥩 Халяль\n"
        "Если «Да» — из выдачи убираю очевидные несоответствия (свинина, алкоголь в составе).",
        reply_markup=b.as_markup(),
    )
    await call.answer()


@router.callback_query(F.data.startswith("sth:"))
async def settings_halal_set(call: CallbackQuery, state: FSMContext):
    user = ensure_user(call.from_user.id)
    user.halal_only = call.data.endswith(":1")
    user.save()
    await settings_halal_menu(call, state)


# --- 4. Диетические столы ---
@router.callback_query(F.data == "st:dietetic")
async def settings_dietetic(call: CallbackQuery, state: FSMContext):
    await state.set_state(states.SettingsFlow.dietetic)
    user = ensure_user(call.from_user.id)
    sel = set(_loads(user.dietetic_tables_json))
    b = InlineKeyboardBuilder()
    for key, label in DIETETIC_TABLES:
        mark = "✓ " if key in sel else ""
        b.add(InlineKeyboardButton(text=f"{mark}{label}", callback_data=f"stdt:{key}"))
    b.adjust(1)
    b.row(InlineKeyboardButton(text="✔️ Готово", callback_data="stdt:done"))
    b.row(InlineKeyboardButton(text="🔙 Назад", callback_data="st:root"))
    await call.message.edit_text(DIETETIC_HINTS, reply_markup=b.as_markup())
    await call.answer()


@router.callback_query(F.data.startswith("stdt:"))
async def settings_dietetic_toggle(call: CallbackQuery, state: FSMContext):
    key = call.data.split(":", 1)[1]
    user = ensure_user(call.from_user.id)
    if key == "done":
        cur = _loads(user.dietetic_tables_json)
        body = f"✅ Учтены столы: {_dietetic_summary_ru(cur)}"
        await call.message.edit_text(
            await _with_settings_cuisine_prefix(state, body),
            reply_markup=keyboards.settings_done_kb(),
        )
        await call.answer()
        return
    cur = _loads(user.dietetic_tables_json)
    if key in cur:
        cur.remove(key)
    else:
        cur.append(key)
    user.dietetic_tables_json = _dumps(cur)
    user.save()
    await settings_dietetic(call, state)


# --- 5. Аллергии ---
def _allergies_strip_legacy_other(cur: list) -> list:
    return [x for x in cur if x != "other"]


def _allergy_catalog_selected(cur: list) -> set[str]:
    return {x for x in cur if isinstance(x, str) and x in ALLERGY_CATALOG_KEYS}


ALLERGIES_SETTINGS_BODY = (
    "🚫 Аллергии и непереносимости\n"
    "Отмеченное полностью исключаю из подбора.\n\n"
    "Свои пункты — через «Другое»: напиши продукт или аллерген текстом "
    "(несколько — через запятую). Убрать свой пункт — нажми на строку «✓ ✍️ …» ниже."
)


def _allergies_cur_clean_persist(user) -> list:
    cur = _loads(user.allergies_strict_json)
    cur2 = _allergies_strip_legacy_other(cur)
    if cur2 != cur:
        user.allergies_strict_json = _dumps(cur2)
        user.save()
    return cur2


async def _render_settings_allergies_ui(
    message: Message,
    uid: int,
    *,
    edit: bool,
    state: FSMContext | None = None,
) -> None:
    if state is not None:
        await state.set_state(states.SettingsFlow.allergies)
    user = ensure_user(uid)
    cur = _allergies_cur_clean_persist(user)
    sel = _allergy_catalog_selected(cur)
    b = InlineKeyboardBuilder()
    for ak, label in ALLERGY_OPTIONS:
        mark = "✓ " if ak in sel else ""
        b.add(InlineKeyboardButton(text=f"{mark}{label}", callback_data=f"sta:{ak}"))
    b.adjust(2, 2, 2, 2, 2)
    mid = InlineKeyboardBuilder()
    mid.add(InlineKeyboardButton(text="✍️ Другое (свой текст)", callback_data="st:allergies_add"))
    for x in cur:
        if isinstance(x, dict) and x.get("type") == ALLERGY_CUSTOM_TYPE:
            lab = (x.get("l") or "?")[:40]
            sid = x.get("s") or ""
            if sid:
                mid.add(
                    InlineKeyboardButton(
                        text=f"✓ ✍️ {lab}",
                        callback_data=f"star:{sid}",
                    ),
                )
    mid.adjust(1)
    foot = InlineKeyboardBuilder()
    foot.add(InlineKeyboardButton(text="✔️ Готово", callback_data="st:all_done"))
    foot.add(InlineKeyboardButton(text="🔙 Назад", callback_data="st:root"))
    foot.adjust(1)
    b.attach(mid)
    b.attach(foot)
    if edit:
        await message.edit_text(ALLERGIES_SETTINGS_BODY, reply_markup=b.as_markup())
    else:
        await message.answer(ALLERGIES_SETTINGS_BODY, reply_markup=b.as_markup())


@router.callback_query(F.data == "st:allergies")
async def settings_allergies(call: CallbackQuery, state: FSMContext):
    await _render_settings_allergies_ui(call.message, call.from_user.id, edit=True, state=state)
    await call.answer()


@router.callback_query(F.data == "st:allergies_add")
async def settings_allergies_add_prompt(call: CallbackQuery, state: FSMContext):
    await state.set_state(states.SettingsFlow.allergies_add)
    cancel = InlineKeyboardBuilder()
    cancel.add(InlineKeyboardButton(text="🔙 Отмена", callback_data="st:allergies"))
    await call.message.edit_text(
        "✍️ Напиши продукты или аллергены, которые нужно исключить.\n"
        "Одним сообщением; несколько — через запятую.\n"
        "Например: «арахис», «мёд, кунжут».\n\n"
        "В подборе буду отфильтровывать рецепты, где в ингредиентах или названии "
        "встречается этот текст.",
        reply_markup=cancel.as_markup(),
    )
    await call.answer()


@router.message(states.SettingsFlow.allergies_add, F.text)
async def settings_allergies_add_got_text(message: Message, state: FSMContext):
    raw = message.text.strip()
    if raw.startswith("/"):
        await message.answer("Напиши аллергены текстом или нажми «Отмена».")
        return
    user = ensure_user(message.from_user.id)
    cur = _loads(user.allergies_strict_json)
    cur = _allergies_strip_legacy_other(cur)
    parts = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
    if not parts:
        await message.answer("Напиши хотя бы одно слово или нажми «Отмена».")
        return
    added = 0
    for piece in parts:
        slug = free_cuisine_slug(piece)
        dup = any(
            isinstance(x, dict)
            and x.get("type") == ALLERGY_CUSTOM_TYPE
            and x.get("s") == slug
            for x in cur
        )
        if dup:
            continue
        label = piece.replace("\n", " ")[:120]
        cur.append({"type": ALLERGY_CUSTOM_TYPE, "l": label, "s": slug})
        added += 1
    user.allergies_strict_json = _dumps(cur)
    user.save()
    if added:
        await message.answer(f"Добавлено пунктов: {added}.")
    else:
        await message.answer("Такие пункты уже были в списке. Чтобы убрать — нажми на них в настройках.")
    await _render_settings_allergies_ui(message, message.from_user.id, edit=False, state=state)


@router.callback_query(F.data.startswith("star:"))
async def settings_allergy_remove_custom(call: CallbackQuery, state: FSMContext):
    sid = call.data[5:]
    if not sid:
        await call.answer()
        return
    user = ensure_user(call.from_user.id)
    cur = _loads(user.allergies_strict_json)
    new = [
        x
        for x in cur
        if not (
            isinstance(x, dict)
            and x.get("type") == ALLERGY_CUSTOM_TYPE
            and x.get("s") == sid
        )
    ]
    if len(new) == len(cur):
        await call.answer("Не найдено")
        return
    user.allergies_strict_json = _dumps(new)
    user.save()
    await _render_settings_allergies_ui(call.message, call.from_user.id, edit=True, state=state)
    await call.answer("Убрано")


@router.callback_query(lambda c: c.data and c.data.startswith("sta:") and c.data != "sta:manual")
async def settings_allergy_toggle(call: CallbackQuery, state: FSMContext):
    key = call.data.split(":", 1)[1]
    if key not in ALLERGY_CATALOG_KEYS:
        await call.answer()
        return
    user = ensure_user(call.from_user.id)
    cur = _loads(user.allergies_strict_json)
    cur = _allergies_strip_legacy_other(cur)
    str_keys = [x for x in cur if isinstance(x, str)]
    if key in str_keys:
        cur = [x for x in cur if x != key]
    else:
        cur.append(key)
    user.allergies_strict_json = _dumps(cur)
    user.save()
    await _render_settings_allergies_ui(call.message, call.from_user.id, edit=True, state=state)
    await call.answer()


def _allergy_summary_labels(cur: list) -> str:
    label_by_key = dict(ALLERGY_OPTIONS)
    parts: list[str] = []
    for x in _allergies_strip_legacy_other(cur):
        if isinstance(x, str) and x in ALLERGY_CATALOG_KEYS:
            parts.append(label_by_key.get(x, x))
        elif isinstance(x, dict) and x.get("type") == ALLERGY_CUSTOM_TYPE:
            lab = x.get("l")
            if isinstance(lab, str) and lab.strip():
                parts.append(f"✍️ {lab.strip()}")
    return ", ".join(parts) if parts else "ничего"


@router.callback_query(F.data == "st:all_done")
async def settings_all_done(call: CallbackQuery, state: FSMContext):
    user = ensure_user(call.from_user.id)
    cur = _loads(user.allergies_strict_json)
    body = f"✅ Исключаю из выдачи: {_allergy_summary_labels(cur)}"
    await call.message.edit_text(
        await _with_settings_cuisine_prefix(state, body),
        reply_markup=keyboards.settings_done_kb(),
    )
    await call.answer()


# --- 6. ЗОЖ и фитнес ---
@router.callback_query(F.data == "st:fitness")
async def settings_fitness(call: CallbackQuery, state: FSMContext):
    await state.set_state(states.SettingsFlow.fitness)
    user = ensure_user(call.from_user.id)
    sel = set(_loads(user.fitness_prefs_json))
    b = InlineKeyboardBuilder()
    for key, label in FITNESS_OPTIONS:
        mark = "✓ " if key in sel else ""
        b.add(InlineKeyboardButton(text=f"{mark}{label}", callback_data=f"stf:{key}"))
    b.add(InlineKeyboardButton(text="✔️ Готово", callback_data="stf:done"))
    b.add(InlineKeyboardButton(text="🔙 Назад", callback_data="st:root"))
    b.adjust(1)
    await call.message.edit_text(
        "🏋️ ЗОЖ и фитнес\n"
        "«Без жареного» — убираю жарку и фритюр из выдачи.\n"
        "Остальное усиливает приоритет по тегам в рецептах.",
        reply_markup=b.as_markup(),
    )
    await call.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("stf:") and c.data != "stf:done")
async def settings_fitness_toggle(call: CallbackQuery, state: FSMContext):
    key = call.data.split(":", 1)[1]
    user = ensure_user(call.from_user.id)
    cur = _loads(user.fitness_prefs_json)
    if key in cur:
        cur.remove(key)
    else:
        cur.append(key)
    user.fitness_prefs_json = _dumps(cur)
    user.save()
    await settings_fitness(call, state)


@router.callback_query(F.data == "stf:done")
async def settings_fitness_done(call: CallbackQuery, state: FSMContext):
    user = ensure_user(call.from_user.id)
    cur = _loads(user.fitness_prefs_json)
    body = f"✅ ЗОЖ: {', '.join(cur) or 'без ограничений'}"
    await call.message.edit_text(
        await _with_settings_cuisine_prefix(state, body),
        reply_markup=keyboards.settings_done_kb(),
    )
    await call.answer()


# --- 7. Время ---
@router.callback_query(F.data == "st:time")
async def settings_time(call: CallbackQuery, state: FSMContext):
    await state.set_state(states.SettingsFlow.time_limit)
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="⚡ До 15 минут", callback_data="stt:15"))
    b.add(InlineKeyboardButton(text="🕒 До 30 минут", callback_data="stt:30"))
    b.add(InlineKeyboardButton(text="🔥 До 60 минут", callback_data="stt:60"))
    b.add(InlineKeyboardButton(text="🌙 Не важно", callback_data="stt:0"))
    b.add(InlineKeyboardButton(text="🔙 Назад", callback_data="st:root"))
    b.adjust(1)
    await call.message.edit_text(
        "⏱ Максимальное время приготовления\n"
        "(Строгое ограничение по времени в данных пользователя можно включить отдельно при необходимости.)",
        reply_markup=b.as_markup(),
    )
    await call.answer()


@router.callback_query(F.data.startswith("stt:"))
async def settings_time_pick(call: CallbackQuery, state: FSMContext):
    v = int(call.data.split(":")[1])
    user = ensure_user(call.from_user.id)
    user.max_time_minutes = None if v == 0 else v
    user.save()
    await call.message.edit_text(
        await _with_settings_cuisine_prefix(state, texts.SETTINGS_SAVED),
        reply_markup=keyboards.settings_done_kb(),
    )
    await call.answer()


# --- 8. Тип блюда ---
@router.callback_query(F.data == "st:dishtype")
async def settings_dishtype(call: CallbackQuery, state: FSMContext):
    await state.set_state(states.SettingsFlow.dish_types)
    user = ensure_user(call.from_user.id)
    sel = set(_loads(user.dish_types_pref_json))
    b = InlineKeyboardBuilder()
    for dt in DishType:
        mark = "✓ " if dt.value in sel else ""
        b.add(
            InlineKeyboardButton(
                text=f"{mark}{DISH_TYPE_LABEL_RU[dt]}",
                callback_data=f"std:{dt.value}",
            )
        )
    b.add(InlineKeyboardButton(text="✔️ Готово", callback_data="st:dt_done"))
    b.add(InlineKeyboardButton(text="🔙 Назад", callback_data="st:root"))
    b.adjust(1)
    await call.message.edit_text(
        "🍳 Тип блюда\nМожно выбрать несколько (включая напитки).",
        reply_markup=b.as_markup(),
    )
    await call.answer()


@router.callback_query(F.data.startswith("std:"))
async def settings_dt_toggle(call: CallbackQuery, state: FSMContext):
    if call.data == "st:dt_done" or call.data.startswith("stdt:"):
        return
    key = call.data.split(":", 1)[1]
    user = ensure_user(call.from_user.id)
    cur = _loads(user.dish_types_pref_json)
    if key in cur:
        cur.remove(key)
    else:
        cur.append(key)
    user.dish_types_pref_json = _dumps(cur)
    user.save()
    await settings_dishtype(call, state)


@router.callback_query(F.data == "st:dt_done")
async def settings_dt_done(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text(
        await _with_settings_cuisine_prefix(state, texts.SETTINGS_SAVED),
        reply_markup=keyboards.settings_done_kb(),
    )
    await call.answer()


# --- 9. Способ приготовления (предпочтения) ---
@router.callback_query(F.data == "st:cookpref")
async def settings_cookpref(call: CallbackQuery, state: FSMContext):
    await state.set_state(states.SettingsFlow.cook_prefs)
    user = ensure_user(call.from_user.id)
    sel = set(_loads(user.preferred_cook_methods_json))
    b = InlineKeyboardBuilder()
    for key, label in PREFERRED_COOK_METHODS:
        mark = "✓ " if key in sel else ""
        b.add(InlineKeyboardButton(text=f"{mark}{label}", callback_data=f"stcm:{key}"))
    b.add(InlineKeyboardButton(text="✔️ Готово", callback_data="stcm:done"))
    b.add(InlineKeyboardButton(text="🔙 Назад", callback_data="st:root"))
    b.adjust(2, 2, 2, 1, 1)
    await call.message.edit_text(
        "🍲 Предпочитаемые способы приготовления\n"
        "Пустой список = без приоритета. Если выбрано — такие рецепты выше в выдаче.",
        reply_markup=b.as_markup(),
    )
    await call.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("stcm:") and c.data != "stcm:done")
async def settings_cookpref_toggle(call: CallbackQuery, state: FSMContext):
    key = call.data.split(":", 1)[1]
    user = ensure_user(call.from_user.id)
    cur = _loads(user.preferred_cook_methods_json)
    if key in cur:
        cur.remove(key)
    else:
        cur.append(key)
    user.preferred_cook_methods_json = _dumps(cur)
    user.save()
    await settings_cookpref(call, state)


@router.callback_query(F.data == "stcm:done")
async def settings_cookpref_done(call: CallbackQuery, state: FSMContext):
    user = ensure_user(call.from_user.id)
    cur = _loads(user.preferred_cook_methods_json)
    labels = [cook_method_label_ru(x) for x in cur if isinstance(x, str)]
    body = f"✅ Способы: {', '.join(labels) or 'любые'}"
    await call.message.edit_text(
        await _with_settings_cuisine_prefix(state, body),
        reply_markup=keyboards.settings_done_kb(),
    )
    await call.answer()


# --- 10. Сложность и бюджет ---
@router.callback_query(F.data == "st:diffbud")
async def settings_diffbud(call: CallbackQuery, state: FSMContext):
    await state.set_state(states.SettingsFlow.diff_budget)
    user = ensure_user(call.from_user.id)
    diff_sel = set(_loads(user.allowed_difficulties_json))
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="— Сложность (несколько) —", callback_data="st:nop"))
    for key, label in DIFFICULTY_OPTIONS:
        mark = "✓ " if key in diff_sel else ""
        b.add(InlineKeyboardButton(text=f"{mark}{label}", callback_data=f"stdif:{key}"))
    b.adjust(1)
    bt = getattr(user, "budget_tier", None) or "any"
    b.add(InlineKeyboardButton(text="— Бюджет (один) —", callback_data="st:nop"))
    for key, label in BUDGET_OPTIONS:
        mark = "✓ " if bt == key else ""
        b.add(InlineKeyboardButton(text=f"{mark}{label}", callback_data=f"stbq:{key}"))
    b.adjust(1)
    b.row(InlineKeyboardButton(text="✔️ Готово", callback_data="stdif:done"))
    b.row(InlineKeyboardButton(text="🔙 Назад", callback_data="st:root"))
    await call.message.edit_text(
        "💰 Сложность и бюджет\n"
        "Сложность: если ничего не отмечено — подбираю любую.\n"
        "Бюджет: один вариант; чем конкретнее выбор — тем точнее приоритет в выдаче.",
        reply_markup=b.as_markup(),
    )
    await call.answer()


@router.callback_query(F.data == "st:nop")
async def settings_nop(call: CallbackQuery, state: FSMContext):
    await call.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("stdif:") and c.data != "stdif:done")
async def settings_diff_toggle(call: CallbackQuery, state: FSMContext):
    key = call.data.split(":", 1)[1]
    user = ensure_user(call.from_user.id)
    cur = _loads(user.allowed_difficulties_json)
    if key in cur:
        cur.remove(key)
    else:
        cur.append(key)
    user.allowed_difficulties_json = _dumps(cur)
    user.save()
    await settings_diffbud(call, state)


@router.callback_query(F.data.startswith("stbq:"))
async def settings_budget_set(call: CallbackQuery, state: FSMContext):
    key = call.data.split(":", 1)[1]
    user = ensure_user(call.from_user.id)
    user.budget_tier = None if key == "any" else key
    user.save()
    await settings_diffbud(call, state)


@router.callback_query(F.data == "stdif:done")
async def settings_diff_done(call: CallbackQuery, state: FSMContext):
    user = ensure_user(call.from_user.id)
    d = _loads(user.allowed_difficulties_json)
    bt = user.budget_tier or "any"
    body = f"✅ Сложность: {_difficulty_summary_ru(d)}; бюджет: {_budget_summary_ru(user.budget_tier)}"
    await call.message.edit_text(
        await _with_settings_cuisine_prefix(state, body),
        reply_markup=keyboards.settings_done_kb(),
    )
    await call.answer()


# --- Навигация «Готово» из настроек ---
@router.callback_query(F.data == "st:done")
async def settings_done_navigate(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    ctx = data.get("settings_back_ctx", "cabinet")
    await call.answer()
    if ctx == "cabinet":
        from handlers.cabinet import show_cabinet

        await show_cabinet(call.message, state, edit=True)
        return
    if ctx == "cuisine_hub":
        slug = data.get("cuisine_slug", "italian")
        from data.cuisine_catalog import description_for_slug, label_for_slug

        await state.set_state(states.CuisinesFlow.cuisine_hub)
        lab = data.get("cuisine_display") or label_for_slug(slug)
        desc = description_for_slug(slug, custom_fallback=texts.CUISINE_CUSTOM_FALLBACK)
        await call.message.edit_text(
            f"🌍 Выбрана кухня: {lab}\n\n{lab}\n{desc}\n\nЧто будем готовить?",
            reply_markup=keyboards.cuisine_hub_kb(slug),
        )
        return
    if ctx == "products":
        await state.set_state(states.ProductsFlow.browsing_results)
        from database import Recipe
        from handlers import products

        ids = data.get("result_ids") or []
        if not ids:
            await state.set_state(states.ProductsFlow.waiting_input)
            await products.render_products_waiting_screen(call.message, edit=True)
            return
        ordered = [Recipe.get_by_id(i) for i in ids]
        offset = int(data.get("list_offset") or 0)
        method = data.get("cook_method", "")
        label = cook_method_label_ru(method) if method else "подбор"
        await safe_delete_message(call.message)
        await products._send_results_message(
            call.bot,
            call.from_user.id,
            ordered,
            label,
            offset=offset,
            list_ctx="products",
            more_cb="pr:more",
            cuisine_label=data.get("products_cuisine_display"),
        )
        return
    if ctx == "cuisine":
        await state.set_state(states.CuisinesFlow.browsing)
        from database import Recipe
        from handlers import cuisines

        user = ensure_user(call.from_user.id)
        ids = data.get("result_ids") or []
        slug = data.get("cuisine_slug", "")
        offset = int(data.get("list_offset") or 0)
        ordered = [Recipe.get_by_id(i) for i in ids]
        await safe_delete_message(call.message)
        lab = data.get("cuisine_display")
        await cuisines._send_cuisine_list(
            call.message, user, ordered, slug, offset, "cu:more", hub_label=lab
        )
        return
    from services.limits import remaining_full_free_opens

    user = ensure_user(call.from_user.id)
    await call.message.edit_text(
        texts.get_welcome_text(remaining_full_free_opens(user)),
        reply_markup=keyboards.start_kb(),
    )
