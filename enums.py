"""Нормализованные enum для рецептов и UI (ТЗ)."""

from enum import StrEnum


class CookMethod(StrEnum):
    BOIL = "boil"
    FRY = "fry"
    BAKE = "bake"
    OTHER = "other"
    STEW = "stew"
    STEAM = "steam"
    GRILL = "grill"
    DEEP_FRY = "deep_fry"
    BBQ = "bbq"
    RAW = "raw"


class DishType(StrEnum):
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    SNACK = "snack"
    DESSERT = "dessert"
    BEVERAGE = "beverage"


class Difficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


# Отображение для кнопок/текста
COOK_METHOD_LABEL_RU = {
    CookMethod.BOIL: "Сварить",
    CookMethod.FRY: "Пожарить",
    CookMethod.BAKE: "Запечь",
    CookMethod.OTHER: "Другое",
    CookMethod.STEW: "Тушить",
    CookMethod.STEAM: "На пару",
    CookMethod.GRILL: "На гриле",
    CookMethod.DEEP_FRY: "Во фритюре",
    CookMethod.BBQ: "На мангале",
    CookMethod.RAW: "Без термической обработки",
}


def cook_method_label_ru(value: str | None) -> str:
    """Русская подпись для кода способа приготовления (для сообщений пользователю)."""
    if value is None:
        return ""
    v = str(value).strip()
    if not v:
        return ""
    try:
        return COOK_METHOD_LABEL_RU[CookMethod(v)]
    except ValueError:
        return v

DISH_TYPE_LABEL_RU = {
    DishType.BREAKFAST: "Завтрак",
    DishType.LUNCH: "Обед",
    DishType.DINNER: "Ужин",
    DishType.SNACK: "Перекус",
    DishType.DESSERT: "Десерт",
    DishType.BEVERAGE: "Напитки",
}

TIME_BUCKET_LABEL_RU = {
    "fast": "5–15 минут",
    "medium": "15–45 минут",
    "long": "45+ минут",
}

SETTINGS_RETURN_KEY = "settings_return"
