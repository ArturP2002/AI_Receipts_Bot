"""Кухни для UI (slug хранится в Recipe.cuisine)."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

POPULAR_CUISINES = [
    ("russian", "🇷🇺 Русская"),
    ("georgian", "🇬🇪 Грузинская"),
    ("italian", "🇮🇹 Итальянская"),
    ("japanese", "🇯🇵 Японская"),
    ("uzbek", "🇺🇿 Узбекская"),
    ("chinese", "🇨🇳 Китайская"),
    ("turkish", "🇹🇷 Турецкая"),
    ("greek", "🇬🇷 Греческая"),
]

MORE_CUISINES = [
    ("korean", "🇰🇷 Корейская"),
    ("vietnamese", "🇻🇳 Вьетнамская"),
    ("armenian", "🇦🇲 Армянская"),
    ("thai", "🇹🇭 Тайская"),
    ("moroccan", "🇲🇦 Марокканская"),
    ("german", "🇩🇪 Немецкая"),
    ("french", "🇫🇷 Французская"),
    ("indian", "🇮🇳 Индийская"),
    ("mexican", "🇲🇽 Мексиканская"),
    ("spanish", "🇪🇸 Испанская"),
    ("ukrainian", "🇺🇦 Украинская"),
    ("azerbaijani", "🇦🇿 Азербайджанская"),
]

CUISINE_DESCRIPTION = {
    "russian": "Домашняя, сытная кухня с кашами, пирогами и щами.",
    "georgian": "Ароматные соусы, хачапури и шашлык.",
    "italian": "Паста, пицца, оливковое масло и свежие травы.",
    "japanese": "Рис, рыба, лёгкие бульоны и баланс вкуса.",
    "uzbek": "Плов, лепёшки и насыщенные специи.",
    "chinese": "Вок, лапша, соусы и сочетание текстур.",
    "turkish": "Кебабы, йогуртовые соусы и сладости.",
    "greek": "Оливки, сыр фета, морепродукты и свежие овощи.",
    "korean": "Кимчи, острые соусы и рис.",
    "vietnamese": "Супы фо, травы и лёгкие бульоны.",
    "armenian": "Долма, люля и насыщенные травы.",
    "thai": "Острая, ароматная, с яркими специями и соусами.",
    "moroccan": "Кускус, тагины и сладкие специи.",
    "german": "Колбасы, картофель и плотные супы.",
    "french": "Соусы, выпечка и изысканные сочетания.",
    "indian": "Карри, специи и бобовые.",
    "mexican": "Кукурузные лепёшки, фасоль и чили.",
    "spanish": "Паэлья, тапас и оливковое масло.",
    "ukrainian": "Борщ, вареники и сытные первые блюда.",
    "azerbaijani": "Плов, долма и насыщенные мясные блюда.",
}


ALL_CUISINE_SLUGS = [s for s, _ in POPULAR_CUISINES + MORE_CUISINES]
ALL_CUISINE_SLUG_SET = set(ALL_CUISINE_SLUGS)

# Страны / привычные названия → slug из каталога (русский ввод)
CUISINE_ALIASES: dict[str, str] = {
    "рф": "russian",
    "россия": "russian",
    "российская": "russian",
    "русская": "russian",
    "русский": "russian",
    "грузия": "georgian",
    "грузинская": "georgian",
    "грузинский": "georgian",
    "италия": "italian",
    "итальянская": "italian",
    "итальянский": "italian",
    "япония": "japanese",
    "японская": "japanese",
    "японский": "japanese",
    "узбекистан": "uzbek",
    "узбекская": "uzbek",
    "узбекский": "uzbek",
    "китай": "chinese",
    "китайская": "chinese",
    "китайский": "chinese",
    "турция": "turkish",
    "турецкая": "turkish",
    "турецкий": "turkish",
    "греция": "greek",
    "греческая": "greek",
    "греческий": "greek",
    "корея": "korean",
    "корейская": "korean",
    "корейский": "korean",
    "вьетнам": "vietnamese",
    "вьетнамская": "vietnamese",
    "армения": "armenian",
    "армянская": "armenian",
    "армянский": "armenian",
    "тайланд": "thai",
    "тайская": "thai",
    "тайский": "thai",
    "марокко": "moroccan",
    "марокканская": "moroccan",
    "германия": "german",
    "немецкая": "german",
    "немецкий": "german",
    "франция": "french",
    "французская": "french",
    "французский": "french",
    "индия": "indian",
    "индийская": "indian",
    "индийский": "indian",
    "мексика": "mexican",
    "мексиканская": "mexican",
    "испания": "spanish",
    "испанская": "spanish",
    "украина": "ukrainian",
    "украинская": "ukrainian",
    "украинский": "ukrainian",
    "азербайджан": "azerbaijani",
    "азербайджанская": "azerbaijani",
}


def _normalize_cuisine_query(s: str) -> str:
    t = s.lower().strip()
    for ch in "«»\"'!?;:()[]":
        t = t.replace(ch, " ")
    t = re.sub(r"\s+", " ", t)
    for suf in (" кухня", " кухни", "кухня", " kitchen", "ская кухня"):
        t = t.replace(suf, " ")
    t = re.sub(r"\s+", " ", t).strip()
    return t


def label_for_slug(slug: str) -> str:
    for s, lab in POPULAR_CUISINES + MORE_CUISINES:
        if s == slug:
            return lab
    return slug


def free_cuisine_slug(raw: str) -> str:
    """Внутренний slug для произвольной кухни (не из каталога). До 64 символов для Recipe.cuisine."""
    s = raw.strip().lower()
    if not s:
        return "custom"
    ascii_try = re.sub(r"[^a-z0-9]+", "_", s.encode("ascii", "ignore").decode("ascii", errors="ignore"))
    ascii_try = ascii_try.strip("_")[:50]
    if len(ascii_try) >= 2:
        return f"u_{ascii_try}"[:64]
    h = hashlib.sha256(s.encode("utf-8")).hexdigest()[:22]
    return f"u_{h}"


def resolve_cuisine_from_text(raw: str) -> tuple[str, str]:
    """
    Всегда возвращает (slug, подпись для экрана).
    Если ввод похож на кухню из каталога — slug из каталога; иначе — свой slug и подпись «🌍 …».
    """
    t = raw.strip()
    if not t:
        return "custom", "🌍 Кухня"
    cat = resolve_cuisine_slug(t)
    if cat:
        return cat, label_for_slug(cat)
    slug = free_cuisine_slug(t)
    disp = t.replace("\n", " ")[:120]
    return slug, f"🌍 {disp}"


def description_for_slug(slug: str, *, custom_fallback: str) -> str:
    return CUISINE_DESCRIPTION.get(slug, custom_fallback)


def _label_plain(label: str) -> str:
    return re.sub(r"[^\w\sа-яё\-]", "", label.lower())


def resolve_cuisine_slug(raw: str) -> str | None:
    """Сопоставить свободный ввод (страна / «итальянская») со slug из каталога."""
    n = _normalize_cuisine_query(raw)
    if not n:
        return None
    if n in CUISINE_ALIASES:
        return CUISINE_ALIASES[n]
    for word in n.split():
        if word in CUISINE_ALIASES:
            return CUISINE_ALIASES[word]
    for slug in ALL_CUISINE_SLUGS:
        if slug == n or slug in n.replace(" ", "") or n in slug:
            return slug
    for slug, lab in POPULAR_CUISINES + MORE_CUISINES:
        plain = _label_plain(lab)
        if n in plain or plain in n:
            return slug
        for part in plain.split():
            if len(part) > 2 and part in n:
                return slug
    return None


# --- Избранные кухни в настройках (JSON в UsersData.favorite_cuisines_json) ---
# Элементы: строка-slug из каталога ИЛИ {"type": "c", "l": "подпись", "s": "внутренний_slug"}

FAVORITE_CUSTOM_TYPE = "c"


def parse_favorite_cuisines_list(raw: str) -> list[Any]:
    try:
        v = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return v if isinstance(v, list) else []


def display_label_for_favorite_entry(entry: Any) -> str:
    if isinstance(entry, str) and entry.strip():
        return label_for_slug(entry.strip())
    if isinstance(entry, dict) and entry.get("type") == FAVORITE_CUSTOM_TYPE:
        lab = entry.get("l") or entry.get("label")
        if isinstance(lab, str) and lab.strip():
            return lab.strip()
        s = entry.get("s") or entry.get("slug")
        if isinstance(s, str) and s.strip():
            return label_for_slug(s.strip())
    return "—"


def summary_labels_favorites(cur: list[Any]) -> str:
    parts = [display_label_for_favorite_entry(x) for x in cur]
    parts = [p for p in parts if p and p != "—"]
    return ", ".join(parts) if parts else "—"


def first_favorite_cuisine_slug(raw: str) -> str:
    for x in parse_favorite_cuisines_list(raw):
        if isinstance(x, str) and x.strip():
            return x.strip()
        if isinstance(x, dict) and x.get("type") == FAVORITE_CUSTOM_TYPE:
            s = str(x.get("s", "")).strip()
            if s:
                return s
    return "russian"


def _norm_match(s: str) -> str:
    t = (s or "").lower().strip()
    return re.sub(r"\s+", " ", t)


def strip_leading_cuisine_decor(label: str) -> str:
    """Убирает 🌍, флаги регионов и лишние пробелы в начале подписи кухни."""
    t = (label or "").strip()
    if not t:
        return ""
    t = re.sub(r"^🌍\s*", "", t)
    while len(t) >= 2:
        a, b = ord(t[0]), ord(t[1])
        if 0x1F1E6 <= a <= 0x1F1FF and 0x1F1E6 <= b <= 0x1F1FF:
            t = t[2:].lstrip()
        else:
            break
    return t.strip()


def lookup_custom_cuisine_label_in_favorites(slug: str) -> str | None:
    """Ищет русскую подпись для slug вида u_… в JSON избранных кухонь пользователей."""
    slug = (slug or "").strip()
    if not slug.startswith("u_"):
        return None
    from database import UsersData

    try:
        qs = UsersData.select(UsersData.favorite_cuisines_json).where(
            UsersData.favorite_cuisines_json.contains(slug)
        )
    except Exception:
        return None
    for u in qs:
        for entry in parse_favorite_cuisines_list(u.favorite_cuisines_json):
            if isinstance(entry, dict) and entry.get("type") == FAVORITE_CUSTOM_TYPE:
                if entry.get("s") == slug:
                    lab = entry.get("l") or entry.get("label")
                    if isinstance(lab, str) and lab.strip():
                        return lab.strip()
    return None


def cuisine_display_ru_for_recipe(slug: str, theme: str | None) -> str | None:
    """Текст для поля Recipe.cuisine_display_ru (русский, без эмодзи-флагов в начале)."""
    slug = (slug or "").strip()
    t = (theme or "").strip()
    if t:
        stripped = strip_leading_cuisine_decor(t)
        if stripped:
            return stripped[:200]
    lab = label_for_slug(slug)
    if lab != slug:
        out = strip_leading_cuisine_decor(lab)
        return (out[:200] if out else None)
    found = lookup_custom_cuisine_label_in_favorites(slug)
    if found:
        return strip_leading_cuisine_decor(found)[:200] or None
    return None


def admin_popular_cuisine_label(slug: str, stored_display: str | None) -> str:
    """Подпись кухни для админки: сохранённый текст или разбор slug."""
    s = (stored_display or "").strip()
    if s:
        return s[:200]
    slug = (slug or "").strip()
    if not slug:
        return "—"
    lab = label_for_slug(slug)
    if lab != slug:
        out = strip_leading_cuisine_decor(lab)
        return out if out else slug
    found = lookup_custom_cuisine_label_in_favorites(slug)
    if found:
        out = strip_leading_cuisine_decor(found)
        return out if out else slug
    if slug.startswith("u_"):
        tail = slug[2:]
        hexish = set(tail) <= set("0123456789abcdef_")
        if len(tail) >= 12 and hexish:
            return "Пользовательская кухня"
        readable = tail.replace("_", " ").strip()
        return readable if readable else "Пользовательская кухня"
    return slug


def favorite_entries_match_norms(raw: str) -> list[str]:
    """Нормализованные строки для приоритета в выдаче (подбор по Recipe.cuisine и подстрокам)."""
    out: list[str] = []
    for x in parse_favorite_cuisines_list(raw):
        if isinstance(x, str) and x.strip():
            out.append(_norm_match(x.strip()))
        elif isinstance(x, dict) and x.get("type") == FAVORITE_CUSTOM_TYPE:
            s = x.get("s")
            l = x.get("l") or x.get("label")
            if isinstance(s, str) and s.strip():
                out.append(_norm_match(s))
            if isinstance(l, str) and l.strip():
                out.append(_norm_match(l.strip()))
    return [t for t in out if t]
