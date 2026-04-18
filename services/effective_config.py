"""Эффективные настройки монетизации: строка bot_runtime_settings (id=1) поверх config."""

from dataclasses import dataclass
from datetime import datetime

import config
from database import BotRuntimeSettings, db


@dataclass(frozen=True)
class EffectiveConfig:
    base_free_recipe_opens: int
    recipe_star_price: int
    show_more_star_price: int
    subscription_star_price: int
    subscription_default_days: int
    free_show_more_count: int
    referral_bonus_opens: int


def get_effective_config() -> EffectiveConfig:
    try:
        row = BotRuntimeSettings.get_by_id(1)
    except BotRuntimeSettings.DoesNotExist:
        row = None
    if not row:
        return EffectiveConfig(
            base_free_recipe_opens=config.BASE_FREE_RECIPE_OPENS,
            recipe_star_price=config.RECIPE_STAR_PRICE,
            show_more_star_price=config.SHOW_MORE_STAR_PRICE,
            subscription_star_price=config.SUBSCRIPTION_STAR_PRICE,
            subscription_default_days=config.SUBSCRIPTION_DEFAULT_DAYS,
            free_show_more_count=config.FREE_SHOW_MORE_COUNT,
            referral_bonus_opens=config.REFERRAL_BONUS_OPENS,
        )
    return EffectiveConfig(
        base_free_recipe_opens=max(0, int(row.base_free_recipe_opens)),
        recipe_star_price=max(1, int(row.recipe_star_price)),
        show_more_star_price=max(1, int(row.show_more_star_price)),
        subscription_star_price=max(1, int(row.subscription_star_price)),
        subscription_default_days=max(1, int(row.subscription_default_days)),
        free_show_more_count=max(0, int(row.free_show_more_count)),
        referral_bonus_opens=max(0, int(row.referral_bonus_opens)),
    )


def update_runtime_settings(**kwargs: int) -> EffectiveConfig:
    keys = {
        "base_free_recipe_opens",
        "recipe_star_price",
        "show_more_star_price",
        "subscription_star_price",
        "subscription_default_days",
        "free_show_more_count",
        "referral_bonus_opens",
    }
    patch = {k: int(v) for k, v in kwargs.items() if k in keys and v is not None}
    if not patch:
        return get_effective_config()
    patch["updated_at"] = datetime.utcnow()
    with db.atomic():
        BotRuntimeSettings.update(**patch).where(BotRuntimeSettings.id == 1).execute()
    return get_effective_config()
