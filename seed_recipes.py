"""
Генерация ≥10 рецептов на каждую кухню (ТЗ п.8).
Запуск: python seed_recipes.py
"""
from __future__ import annotations

from database import Recipe, db, init_database
from data.cuisine_catalog import MORE_CUISINES, POPULAR_CUISINES, label_for_slug
from enums import CookMethod, DishType, Difficulty

ALL_SLUGS = [s for s, _ in POPULAR_CUISINES] + [s for s, _ in MORE_CUISINES]

METHODS = list(CookMethod)
DISHES = list(DishType)


def build_recipe(slug: str, index: int) -> dict:
    method = METHODS[index % len(METHODS)]
    dish = DISHES[index % len(DISHES)]
    cuisine_ru = label_for_slug(slug).split(maxsplit=1)[-1].strip()
    title = f"{cuisine_ru}: демо-рецепт №{index + 1}"
    ingredients = ["вода", "соль", "масло", "овощи", "специи", f"кухня: {cuisine_ru}"]
    steps = [
        "Подготовь ингредиенты и нарежь овощи.",
        "Разогрей сковороду или кастрюлю с маслом.",
        "Обжарь основу 5–7 минут до румяной корочки.",
        "Добавь специи и туши под крышкой 10 минут.",
        "Попробуй на соль и подавай горячим.",
    ]
    restrictions: list[str] = []
    tags = [slug, "demo", dish.value]
    if "vegan" in slug:
        pass
    return {
        "title": title,
        "cuisine": slug,
        "ingredients_json": __import__("json").dumps(ingredients, ensure_ascii=False),
        "steps_json": __import__("json").dumps(steps, ensure_ascii=False),
        "time_minutes": 10 + (index * 7) % 50,
        "difficulty": Difficulty.MEDIUM.value,
        "dish_type": dish.value,
        "cook_method": method.value,
        "tags_json": __import__("json").dumps(tags, ensure_ascii=False),
        "restrictions_json": __import__("json").dumps(restrictions, ensure_ascii=False),
        "calories": 200 + index * 10,
        "short_description": f"Демо-карточка кухни «{cuisine_ru}» для теста подбора.",
        "is_published": True,
        "popularity": 10 - (index % 10),
    }


def seed() -> None:
    init_database()
    with db.atomic():
        if Recipe.select().count() > 0:
            print("Таблица recipes не пуста — пропуск (удали БД для пересида).")
            return
        rows = []
        for slug in ALL_SLUGS:
            for i in range(10):
                rows.append(build_recipe(slug, i))
        Recipe.insert_many(rows).execute()
        print(f"Добавлено {len(rows)} рецептов для {len(ALL_SLUGS)} кухонь.")


if __name__ == "__main__":
    seed()
