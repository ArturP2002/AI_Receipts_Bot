import json
from datetime import datetime

from database import (
    Referral,
    UserOpenedRecipe,
    UserPurchasedRecipe,
    UserSavedRecipe,
    UsersData,
    db,
)
from services.effective_config import get_effective_config
from services.subscription import is_subscription_active


def free_quota_total(user: UsersData) -> int:
    ec = get_effective_config()
    return ec.base_free_recipe_opens + (user.referral_free_bonus or 0)


def remaining_full_free_opens(user: UsersData) -> int:
    """Сколько бесплатных полных открытий карточек осталось пользователю."""
    return max(0, free_quota_total(user) - count_full_free_opens(user.user_id))


def count_full_free_opens(user_id: int) -> int:
    """Сколько уникальных открытий получили полную карточку в рамках бесплатной квоты."""
    return (
        UserOpenedRecipe.select()
        .where(
            (UserOpenedRecipe.user_id == user_id)
            & (UserOpenedRecipe.was_full_free == True)  # noqa: E712
        )
        .count()
    )


def has_purchased(user_id: int, recipe_id: int) -> bool:
    return (
        UserPurchasedRecipe.select()
        .where(
            (UserPurchasedRecipe.user_id == user_id)
            & (UserPurchasedRecipe.recipe_id == recipe_id)
        )
        .exists()
    )


def get_open_row(user_id: int, recipe_id: int) -> UserOpenedRecipe | None:
    try:
        return UserOpenedRecipe.get(
            (UserOpenedRecipe.user_id == user_id)
            & (UserOpenedRecipe.recipe_id == recipe_id)
        )
    except UserOpenedRecipe.DoesNotExist:
        return None


def user_can_see_full_recipe(user: UsersData, recipe_id: int) -> bool:
    if is_subscription_active(user):
        return True
    if has_purchased(user.user_id, recipe_id):
        return True
    row = get_open_row(user.user_id, recipe_id)
    if row and row.was_full_free:
        return True
    return False


def register_recipe_view(user: UsersData, recipe_id: int) -> tuple[bool, bool]:
    """
    Первое открытие карточки. Возвращает (show_full, is_first_open).
    Купленные рецепты не расходуют бесплатную квоту (was_full_free=False).
    """
    existing = get_open_row(user.user_id, recipe_id)
    if existing:
        return user_can_see_full_recipe(user, recipe_id), False

    if has_purchased(user.user_id, recipe_id):
        with db.atomic():
            UserOpenedRecipe.create(
                user_id=user.user_id,
                recipe_id=recipe_id,
                was_full_free=False,
            )
        return True, True

    if is_subscription_active(user):
        with db.atomic():
            UserOpenedRecipe.create(
                user_id=user.user_id,
                recipe_id=recipe_id,
                was_full_free=False,
            )
        return True, True

    quota = free_quota_total(user)
    used_full = count_full_free_opens(user.user_id)
    grant_full = used_full < quota

    with db.atomic():
        UserOpenedRecipe.create(
            user_id=user.user_id,
            recipe_id=recipe_id,
            was_full_free=grant_full,
        )
    return grant_full, True


def can_use_free_show_more(user: UsersData) -> bool:
    ec = get_effective_config()
    return (user.free_show_more_uses or 0) < ec.free_show_more_count


def increment_free_show_more(user: UsersData) -> None:
    user.free_show_more_uses = (user.free_show_more_uses or 0) + 1
    user.save()


def try_grant_referral_bonus_on_first_recipe_open(invitee_id: int) -> int | None:
    """При первом открытии любой карточки приглашённым — бонус пригласившему.

    Возвращает telegram id пригласившего, если бонус только что начислен, иначе None.
    """
    try:
        invitee = UsersData.get_by_id(invitee_id)
    except UsersData.DoesNotExist:
        return None
    ref_id = invitee.pending_referrer_id
    if not ref_id or ref_id == invitee_id:
        return None
    try:
        ref, created = Referral.get_or_create(
            referrer_id=ref_id,
            invitee_id=invitee_id,
            defaults={"bonus_granted": False},
        )
    except Exception:
        return None
    if ref.bonus_granted:
        return None
    try:
        UsersData.get_by_id(ref_id)
    except UsersData.DoesNotExist:
        return None
    with db.atomic():
        ref.bonus_granted = True
        ref.save()
        parent = UsersData.get_by_id(ref_id)
        bonus = get_effective_config().referral_bonus_opens
        parent.referral_free_bonus = (parent.referral_free_bonus or 0) + bonus
        parent.save()
    invitee.pending_referrer_id = None
    invitee.save()
    return ref_id


def append_search_history(user: UsersData, text: str, kind: str) -> None:
    try:
        hist = json.loads(user.search_history_json or "[]")
    except json.JSONDecodeError:
        hist = []
    hist.append({"text": text, "kind": kind, "ts": datetime.utcnow().isoformat()})
    user.search_history_json = json.dumps(hist[-20:])
    user.save()
