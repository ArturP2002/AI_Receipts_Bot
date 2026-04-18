import json
from datetime import datetime, timedelta

from aiogram import Bot

from database import UserSavedRecipe, UsersData, db
import config
import texts
from services.effective_config import get_effective_config


def grant_subscription(user: UsersData, days: int | None = None) -> datetime:
    ec = get_effective_config()
    d = days or ec.subscription_default_days
    now = datetime.utcnow()
    base = user.subscription_expires_at
    if base and base > now:
        new_exp = base + timedelta(days=d)
    else:
        new_exp = now + timedelta(days=d)
    user.subscription_expires_at = new_exp
    user.subscription_lapse_started_at = None
    user.archive_purge_at = None
    user.lapse_notifications_sent_json = "[]"
    user.subscription_expiry_reminders_json = "[]"
    user.save()
    return new_exp


def is_subscription_active(user: UsersData) -> bool:
    if not user.subscription_expires_at:
        return False
    return user.subscription_expires_at > datetime.utcnow()


def format_subscription_date(dt: datetime) -> str:
    """Дата окончания подписки для текстов бота: ДД.ММ.ГГГГ."""
    return dt.strftime("%d.%m.%Y")


def _parse_sent(raw: str) -> list[int]:
    try:
        v = json.loads(raw or "[]")
        return v if isinstance(v, list) else []
    except json.JSONDecodeError:
        return []


def _parse_expiry_reminder_keys(raw: str) -> set[str]:
    try:
        v = json.loads(raw or "[]")
        if not isinstance(v, list):
            return set()
        return {str(x) for x in v if isinstance(x, str)}
    except json.JSONDecodeError:
        return set()


def _save_expiry_reminder_keys(user: UsersData, keys: set[str]) -> None:
    user.subscription_expiry_reminders_json = json.dumps(sorted(keys))
    user.save()


async def process_subscription_tick(bot: Bot) -> None:
    now = datetime.utcnow()
    for user in UsersData.select():
        exp = user.subscription_expires_at
        if not exp:
            continue

        today = now.date()
        exp_day = exp.date()
        er = _parse_expiry_reminder_keys(user.subscription_expiry_reminders_json)
        er_changed = False

        if exp > now:
            delta = (exp_day - today).days
            if delta == 3 and "pre3" not in er:
                try:
                    until_s = format_subscription_date(exp)
                    await bot.send_message(
                        user.user_id,
                        texts.SUBSCRIPTION_REMIND_3_DAYS.format(until=until_s),
                    )
                except Exception:
                    pass
                er.add("pre3")
                er_changed = True
            if delta == 0 and "lastday" not in er:
                try:
                    until_s = format_subscription_date(exp)
                    await bot.send_message(
                        user.user_id,
                        texts.SUBSCRIPTION_REMIND_LAST_DAY.format(until=until_s),
                    )
                except Exception:
                    pass
                er.add("lastday")
                er_changed = True
            if er_changed:
                _save_expiry_reminder_keys(user, er)
            continue

        days_after_exp = (today - exp_day).days
        if (
            1 <= days_after_exp <= config.SUBSCRIPTION_POST_EXPIRY_REMIND_DAYS
            and "postexp" not in er
        ):
            try:
                await bot.send_message(user.user_id, texts.SUBSCRIPTION_EXPIRED_FOLLOWUP)
            except Exception:
                pass
            er.add("postexp")
            _save_expiry_reminder_keys(user, er)

        # Тариф истёк
        if user.subscription_lapse_started_at is None:
            user.subscription_lapse_started_at = now
            user.archive_purge_at = now + timedelta(days=config.ARCHIVE_GRACE_DAYS)
            user.save()
        lapse_start = user.subscription_lapse_started_at
        if not lapse_start:
            continue
        days_since = (now - lapse_start).days
        sent = set(_parse_sent(user.lapse_notifications_sent_json))
        for d in config.LAPSE_NOTIFY_DAYS:
            if days_since >= d and d not in sent:
                sent.add(d)
                remaining = max(0, config.ARCHIVE_GRACE_DAYS - days_since)
                try:
                    await bot.send_message(
                        user.user_id,
                        texts.SUBSCRIPTION_LAPSE.format(days=remaining),
                    )
                except Exception:
                    pass
        user.lapse_notifications_sent_json = json.dumps(sorted(sent))
        user.save()

        purge_at = user.archive_purge_at
        if purge_at and now >= purge_at:
            with db.atomic():
                UserSavedRecipe.delete().where(UserSavedRecipe.user_id == user.user_id).execute()
            user.archive_purge_at = None
            user.save()
            try:
                await bot.send_message(user.user_id, texts.ARCHIVE_PURGED)
            except Exception:
                pass
