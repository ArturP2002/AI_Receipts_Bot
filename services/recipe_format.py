import json
from database import Recipe
from enums import DISH_TYPE_LABEL_RU, DishType, Difficulty, cook_method_label_ru

DIFF_RU = {
    Difficulty.EASY: "лёгкая",
    Difficulty.MEDIUM: "средняя",
    Difficulty.HARD: "сложная",
}


def _steps(r: Recipe) -> list[str]:
    try:
        raw = json.loads(r.steps_json or "[]")
        if isinstance(raw, list):
            return [str(x) for x in raw]
    except json.JSONDecodeError:
        pass
    return []


def _ingredients_line(r: Recipe) -> str:
    try:
        ing = json.loads(r.ingredients_json or "[]")
        if isinstance(ing, list):
            return ", ".join(str(x) for x in ing)
    except json.JSONDecodeError:
        pass
    return ""


def _ingredients_list(r: Recipe) -> list[str]:
    try:
        ing = json.loads(r.ingredients_json or "[]")
        if isinstance(ing, list):
            return [str(x).strip() for x in ing if str(x).strip()]
    except json.JSONDecodeError:
        pass
    return []


def _tips_for_recipe(r: Recipe, ingredients: list[str]) -> list[str]:
    joined = " ".join(ingredients).lower()
    tips: list[str] = []

    if "орех" in joined:
        tips.append(
            "Орехи лучше брать свежие и ароматные: от их качества напрямую зависит вкус соуса."
        )
    if "куриц" in joined:
        tips.append(
            "Курицу не пересушивай: после готовности дай мясу отдохнуть 5-7 минут, чтобы сохранить сочность."
        )
    if "чеснок" in joined:
        tips.append(
            "Чеснок добавляй в конце или в тёплую, а не кипящую массу, чтобы аромат остался ярким."
        )

    method = cook_method_label_ru(r.cook_method).lower()
    if "жар" in method:
        tips.append(
            "Для жарки разогревай сковороду заранее: так образуется корочка и продукт не отдаёт лишнюю влагу."
        )
    elif "духов" in method or "запек" in method:
        tips.append(
            "При запекании не открывай духовку первые 15-20 минут, чтобы температура оставалась стабильной."
        )
    elif "вар" in method:
        tips.append(
            "При варке поддерживай умеренное кипение, а не бурное: так текстура будет более аккуратной."
        )

    tips.append("Попробуй блюдо перед подачей и при необходимости выровняй соль и кислотность по вкусу.")
    return tips[:3]


def format_full_card(r: Recipe, cuisine_flag: str = "") -> str:
    ingredients = _ingredients_list(r)
    method = cook_method_label_ru(r.cook_method)
    try:
        diff = DIFF_RU.get(Difficulty(r.difficulty), r.difficulty)
    except ValueError:
        diff = r.difficulty
    title = (r.title or "Рецепт").strip()

    head = f"Классический рецепт {title.lower()}{cuisine_flag}\n"
    head += "\nИнгредиенты:\n"
    if ingredients:
        head += "\n".join(f"• {x}" for x in ingredients) + "\n"
    else:
        head += "• (список ингредиентов не указан)\n"

    head += f"\nПараметры:\n• Время: {r.time_minutes} мин\n• Способ: {method}\n• Сложность: {diff}\n"
    if r.short_description:
        head += f"\n{r.short_description.strip()}\n"
    head += "\nКак приготовить:\n"
    for i, step in enumerate(_steps(r), 1):
        head += f"{i}. {step}\n"
    tips = _tips_for_recipe(r, ingredients)
    if tips:
        head += "\nСоветы:\n"
        head += "\n".join(f"• {tip}" for tip in tips)
    return head.strip()


def format_teaser_card(r: Recipe, cuisine_flag: str = "") -> str:
    ing = _ingredients_line(r)
    method = cook_method_label_ru(r.cook_method)
    steps = _steps(r)
    preview = "\n".join(f"{i}. {steps[i - 1]}" for i in range(1, min(3, len(steps) + 1)))
    body = (
        f"Рецепт: {r.title}{cuisine_flag}\n"
        f"Ингредиенты: {ing}\n"
        f"Время: {r.time_minutes} мин\n"
        f"Способ: {method}\n\n"
        f"Первые шаги приготовления:\n{preview if preview else '1. …'}"
    )
    return body.strip()
