"""Недавно открытые рецепты конкретного пользователя (по UserOpenedRecipe)."""

import logging

from peewee import DatabaseError

from database import Recipe, UserOpenedRecipe

logger = logging.getLogger(__name__)


def get_recent_opened_recipes(user_id: int, limit: int = 3) -> list[Recipe]:
    """
    Последние уникальные открытия карточек по времени (самое свежее первым).
    Только опубликованные рецепты.
    """
    if limit <= 0:
        return []
    try:
        q = (
            UserOpenedRecipe.select(UserOpenedRecipe.recipe_id, UserOpenedRecipe.opened_at)
            .where(UserOpenedRecipe.user_id == user_id)
            .order_by(UserOpenedRecipe.opened_at.desc())
        )
        seen: set[int] = set()
        recipe_ids: list[int] = []
        for row in q:
            rid = int(row.recipe_id)
            if rid in seen:
                continue
            seen.add(rid)
            recipe_ids.append(rid)
            if len(recipe_ids) >= limit:
                break
        if not recipe_ids:
            return []
        by_id = {
            r.id: r
            for r in Recipe.select().where(
                (Recipe.id.in_(recipe_ids)) & (Recipe.is_published == True)  # noqa: E712
            )
        }
        return [by_id[i] for i in recipe_ids if i in by_id]
    except DatabaseError as e:
        logger.warning("get_recent_opened_recipes: %s", e)
        return []
