from database import Referral, UsersData, db


def link_referral_on_start(invitee_id: int, referrer_id: int | None) -> None:
    if not referrer_id or referrer_id == invitee_id:
        return
    try:
        UsersData.get_by_id(referrer_id)
    except UsersData.DoesNotExist:
        return
    with db.atomic():
        Referral.get_or_create(
            referrer_id=referrer_id,
            invitee_id=invitee_id,
            defaults={"bonus_granted": False},
        )
