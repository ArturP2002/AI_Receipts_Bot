"""
HTTP-сервер админ mini app: статика /admin/ + API /admin/api/*.
Доступ к API только с валидным Telegram WebApp initData и user_id из ADMIN_USER_IDS.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from time import time
from typing import Any

from aiohttp import web
from aiogram.utils.web_app import safe_parse_webapp_init_data
from peewee import JOIN, fn, SQL

from aiogram import Bot

from bot_secrets import ADMIN_USER_IDS, BOT_TOKEN
from data.cuisine_catalog import admin_popular_cuisine_label
from database import (
    BotRuntimeSettings,
    Recipe,
    Referral,
    StarPayment,
    UserOpenedRecipe,
    UserPurchasedRecipe,
    UsersData,
    db,
    init_database,
)
from services.effective_config import get_effective_config, update_runtime_settings

logger = logging.getLogger(__name__)

_WEBAPP_DIR = Path(__file__).resolve().parent / "webapp" / "admin"


def _json_error(status: int, msg: str) -> web.Response:
    return web.json_response({"ok": False, "error": msg}, status=status)


def _parse_body_init(data: dict[str, Any]) -> str:
    raw = data.get("init_data")
    if raw and isinstance(raw, str):
        return raw.strip()
    return ""


def _admin_uid_from_init(init_data: str) -> int:
    if not init_data:
        raise ValueError("empty_init")
    parsed = safe_parse_webapp_init_data(BOT_TOKEN, init_data)
    if time() - parsed.auth_date.timestamp() > 26 * 3600:
        raise ValueError("stale_auth")
    if not parsed.user:
        raise PermissionError("no_user")
    uid = int(parsed.user.id)
    if uid not in ADMIN_USER_IDS:
        raise PermissionError("not_admin")
    return uid


async def _read_admin_request(request: web.Request) -> tuple[int, dict[str, Any]]:
    try:
        data = await request.json()
    except Exception:
        raise web.HTTPBadRequest(
            text=json.dumps({"ok": False, "error": "invalid_json"}),
            content_type="application/json",
        )
    init_data = _parse_body_init(data)
    try:
        admin_uid = _admin_uid_from_init(init_data)
    except ValueError as e:
        if str(e) == "empty_init":
            raise web.HTTPUnauthorized(
                text=json.dumps({"ok": False, "error": "Нужен init_data из Telegram WebApp"}),
                content_type="application/json",
            )
        raise web.HTTPUnauthorized(
            text=json.dumps(
                {"ok": False, "error": "Подпись init_data недействительна или устарела"}
            ),
            content_type="application/json",
        )
    except PermissionError:
        raise web.HTTPForbidden(
            text=json.dumps({"ok": False, "error": "Доступ только для администраторов"}),
            content_type="application/json",
        )
    return admin_uid, data


def _since(period: str) -> datetime | None:
    now = datetime.utcnow()
    if period == "today":
        return datetime(now.year, now.month, now.day)
    if period == "week":
        return now - timedelta(days=7)
    if period == "month":
        return now - timedelta(days=30)
    return None


def _active_users_count(since: datetime) -> int:
    return (
        UserOpenedRecipe.select(fn.COUNT(fn.DISTINCT(UserOpenedRecipe.user_id)))
        .where(UserOpenedRecipe.opened_at >= since)
        .scalar()
        or 0
    )


def _revenue_sum(since: datetime | None) -> int:
    q = StarPayment.select(fn.SUM(StarPayment.amount))
    if since:
        q = q.where(StarPayment.created_at >= since)
    return int(q.scalar() or 0)


async def handle_dashboard(request: web.Request) -> web.Response:
    await _read_admin_request(request)

    now = datetime.utcnow()
    day_start = datetime(now.year, now.month, now.day)
    week_start = now - timedelta(days=7)
    month_start = now - timedelta(days=30)

    total_users = UsersData.select().count()
    opens_total = UserOpenedRecipe.select().count()
    purchases_total = UserPurchasedRecipe.select().count()

    popular_recipes = []
    q_pr = (
        UserOpenedRecipe.select(
            UserOpenedRecipe.recipe_id,
            fn.COUNT(SQL("*")).alias("cnt"),
        )
        .group_by(UserOpenedRecipe.recipe_id)
        .order_by(fn.COUNT(SQL("*")).desc())
        .limit(12)
    )
    for row in q_pr:
        try:
            rec = Recipe.get_by_id(row.recipe_id)
            popular_recipes.append(
                {"recipe_id": row.recipe_id, "title": rec.title, "opens": int(row.cnt)}
            )
        except Recipe.DoesNotExist:
            popular_recipes.append(
                {"recipe_id": row.recipe_id, "title": "?", "opens": int(row.cnt)}
            )

    popular_cuisines = []
    q_cu = (
        UserOpenedRecipe.select(
            Recipe.cuisine,
            fn.MAX(Recipe.cuisine_display_ru).alias("disp"),
            fn.COUNT(SQL("*")).alias("cnt"),
        )
        .join(Recipe, on=(UserOpenedRecipe.recipe_id == Recipe.id), join_type=JOIN.INNER)
        .group_by(Recipe.cuisine)
        .order_by(fn.COUNT(SQL("*")).desc())
        .limit(12)
    )
    for row in q_cu.dicts():
        slug = row["cuisine"]
        stored = row.get("disp")
        popular_cuisines.append(
            {
                "cuisine_label": admin_popular_cuisine_label(slug, stored),
                "cuisine_slug": slug,
                "opens": int(row["cnt"]),
            }
        )

    payload = {
        "ok": True,
        "data": {
            "users_total": total_users,
            "active_users": {
                "day": _active_users_count(day_start),
                "week": _active_users_count(week_start),
                "month": _active_users_count(month_start),
            },
            "opens_total": opens_total,
            "purchases_total": purchases_total,
            "revenue": {
                "today": _revenue_sum(day_start),
                "week": _revenue_sum(week_start),
                "month": _revenue_sum(month_start),
            },
            "popular_recipes": popular_recipes,
            "popular_cuisines": popular_cuisines,
        },
    }
    return web.json_response(payload)


async def handle_users_list(request: web.Request) -> web.Response:
    _, data = await _read_admin_request(request)

    page = max(1, int(data.get("page") or 1))
    page_size = min(50, max(5, int(data.get("page_size") or 20)))
    q_raw = (data.get("q") or "").strip()

    query = UsersData.select()
    if q_raw.isdigit():
        query = query.where(UsersData.user_id == int(q_raw))
    elif q_raw:
        query = query.where(
            (
                UsersData.username.is_null(False)
                & UsersData.username.contains(q_raw)
            )
            | (
                UsersData.first_name.is_null(False)
                & UsersData.first_name.contains(q_raw)
            )
        )

    total = query.count()
    rows = (
        query.order_by(UsersData.created_at.desc())
        .paginate(page, page_size)
        .execute()
    )

    out = []
    for u in rows:
        opened_n = (
            UserOpenedRecipe.select()
            .where(UserOpenedRecipe.user_id == u.user_id)
            .count()
        )
        bought_n = (
            UserPurchasedRecipe.select()
            .where(UserPurchasedRecipe.user_id == u.user_id)
            .count()
        )
        stars_paid = (
            StarPayment.select(fn.SUM(StarPayment.amount))
            .where(StarPayment.user_id == u.user_id)
            .scalar()
            or 0
        )
        out.append(
            {
                "user_id": u.user_id,
                "username": u.username,
                "first_name": u.first_name,
                "created_at": u.created_at.isoformat() if u.created_at else None,
                "is_blocked": bool(u.is_blocked),
                "opened_recipes": opened_n,
                "purchased_recipes": bought_n,
                "referral_free_bonus": u.referral_free_bonus or 0,
                "free_show_more_uses": u.free_show_more_uses or 0,
                "stars_paid_total": int(stars_paid),
            }
        )

    return web.json_response({"ok": True, "data": {"items": out, "total": total, "page": page}})


async def handle_user_detail(request: web.Request) -> web.Response:
    await _read_admin_request(request)
    try:
        uid = int(request.match_info["user_id"])
    except (KeyError, ValueError):
        return _json_error(400, "bad user_id")

    try:
        u = UsersData.get_by_id(uid)
    except UsersData.DoesNotExist:
        return _json_error(404, "Пользователь не найден")

    opened_n = UserOpenedRecipe.select().where(UserOpenedRecipe.user_id == uid).count()
    bought_n = UserPurchasedRecipe.select().where(UserPurchasedRecipe.user_id == uid).count()
    stars_paid = (
        StarPayment.select(fn.SUM(StarPayment.amount)).where(StarPayment.user_id == uid).scalar()
        or 0
    )

    detail = {
        "user_id": u.user_id,
        "username": u.username,
        "first_name": u.first_name,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_seen_at": u.last_seen_at.isoformat() if u.last_seen_at else None,
        "is_blocked": bool(u.is_blocked),
        "opened_recipes": opened_n,
        "purchased_recipes": bought_n,
        "referral_free_bonus": u.referral_free_bonus or 0,
        "free_show_more_uses": u.free_show_more_uses or 0,
        "pending_referrer_id": u.pending_referrer_id,
        "subscription_expires_at": u.subscription_expires_at.isoformat()
        if u.subscription_expires_at
        else None,
        "halal_only": bool(u.halal_only),
        "max_time_minutes": u.max_time_minutes,
        "time_strict": bool(u.time_strict),
        "onboarding_shown": bool(u.onboarding_shown),
        "stars_paid_total": int(stars_paid),
    }
    return web.json_response({"ok": True, "data": detail})


async def handle_user_block(request: web.Request) -> web.Response:
    _, data = await _read_admin_request(request)
    try:
        uid = int(request.match_info["user_id"])
    except (KeyError, ValueError):
        return _json_error(400, "bad user_id")
    blocked = bool(data.get("blocked"))
    UsersData.update(is_blocked=blocked).where(UsersData.user_id == uid).execute()
    bot: Bot | None = request.app.get("telegram_bot")
    if bot:
        try:
            if blocked:
                await bot.send_message(
                    uid,
                    "⛔ Ваш доступ к боту ограничен администратором.\n"
                    "Если это ошибка — напишите в поддержку проекта.",
                )
            else:
                await bot.send_message(uid, "✅ Доступ к боту восстановлен. Снова можно пользоваться сервисом.")
        except Exception as exc:
            logger.warning("admin notify block user=%s: %s", uid, exc)
    return web.json_response({"ok": True, "data": {"user_id": uid, "blocked": blocked}})


async def handle_user_bonus(request: web.Request) -> web.Response:
    _, data = await _read_admin_request(request)
    try:
        uid = int(request.match_info["user_id"])
    except (KeyError, ValueError):
        return _json_error(400, "bad user_id")
    try:
        bonus = int(data.get("bonus_opens") or 0)
    except (TypeError, ValueError):
        return _json_error(400, "bonus_opens")
    if not (1 <= bonus <= 10_000):
        return _json_error(400, "bonus_opens 1…10000")
    try:
        u = UsersData.get_by_id(uid)
    except UsersData.DoesNotExist:
        return _json_error(404, "not found")
    u.referral_free_bonus = (u.referral_free_bonus or 0) + bonus
    u.save()
    bot: Bot | None = request.app.get("telegram_bot")
    if bot:
        try:
            await bot.send_message(
                uid,
                f"🎁 Администратор начислил вам +{bonus} бесплатных полных открытий "
                "карточек рецептов.\nОткройте любой рецепт — лимит обновится автоматически.",
            )
        except Exception as exc:
            logger.warning("admin notify bonus user=%s: %s", uid, exc)
    return web.json_response(
        {"ok": True, "data": {"user_id": uid, "referral_free_bonus": u.referral_free_bonus}}
    )


async def handle_payments_list(request: web.Request) -> web.Response:
    _, data = await _read_admin_request(request)
    period = (data.get("period") or "month").strip().lower()
    since = _since(period)
    q = StarPayment.select().order_by(StarPayment.created_at.desc()).limit(300)
    if since:
        q = q.where(StarPayment.created_at >= since)
    items = []
    for p in q:
        uname = None
        try:
            u = UsersData.get_by_id(p.user_id)
            uname = u.username or u.first_name
        except UsersData.DoesNotExist:
            pass
        title = None
        if p.recipe_id:
            try:
                title = Recipe.get_by_id(p.recipe_id).title
            except Recipe.DoesNotExist:
                title = "?"
        items.append(
            {
                "id": p.id,
                "user_id": p.user_id,
                "user_label": uname,
                "amount": p.amount,
                "payment_type": p.payment_type,
                "recipe_id": p.recipe_id,
                "recipe_title": title,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
        )
    return web.json_response({"ok": True, "data": {"items": items, "period": period}})


async def handle_settings_get(request: web.Request) -> web.Response:
    await _read_admin_request(request)
    ec = get_effective_config()
    row = None
    try:
        row = BotRuntimeSettings.get_by_id(1)
    except BotRuntimeSettings.DoesNotExist:
        pass
    payload = {
        "base_free_recipe_opens": ec.base_free_recipe_opens,
        "recipe_star_price": ec.recipe_star_price,
        "show_more_star_price": ec.show_more_star_price,
        "subscription_star_price": ec.subscription_star_price,
        "subscription_default_days": ec.subscription_default_days,
        "free_show_more_count": ec.free_show_more_count,
        "referral_bonus_opens": ec.referral_bonus_opens,
        "updated_at": row.updated_at.isoformat() if row and row.updated_at else None,
    }
    return web.json_response({"ok": True, "data": payload})


async def handle_settings_post(request: web.Request) -> web.Response:
    _, data = await _read_admin_request(request)
    allowed = {
        "base_free_recipe_opens",
        "recipe_star_price",
        "show_more_star_price",
        "subscription_star_price",
        "subscription_default_days",
        "free_show_more_count",
        "referral_bonus_opens",
    }
    patch: dict[str, int] = {}
    for k in allowed:
        if k in data and data[k] is not None:
            try:
                patch[k] = int(data[k])
            except (TypeError, ValueError):
                return _json_error(400, f"bad int: {k}")
    if not patch:
        return web.json_response({"ok": True, "data": {"note": "nothing to update"}})
    try:
        ec = update_runtime_settings(**patch)
    except Exception as exc:
        logger.exception("settings update: %s", exc)
        return _json_error(500, "save failed")
    return web.json_response(
        {
            "ok": True,
            "data": {
                "base_free_recipe_opens": ec.base_free_recipe_opens,
                "recipe_star_price": ec.recipe_star_price,
                "show_more_star_price": ec.show_more_star_price,
                "subscription_star_price": ec.subscription_star_price,
                "subscription_default_days": ec.subscription_default_days,
                "free_show_more_count": ec.free_show_more_count,
                "referral_bonus_opens": ec.referral_bonus_opens,
            },
        }
    )


async def handle_referrals(request: web.Request) -> web.Response:
    await _read_admin_request(request)
    rows = Referral.select().order_by(Referral.created_at.desc()).limit(500)
    items = []
    for ref in rows:
        ref_u = inv_u = None
        try:
            a = UsersData.get_by_id(ref.referrer_id)
            ref_u = a.username or a.first_name
        except UsersData.DoesNotExist:
            pass
        try:
            b = UsersData.get_by_id(ref.invitee_id)
            inv_u = b.username or b.first_name
        except UsersData.DoesNotExist:
            pass
        items.append(
            {
                "referrer_id": ref.referrer_id,
                "referrer_label": ref_u,
                "invitee_id": ref.invitee_id,
                "invitee_label": inv_u,
                "bonus_granted": bool(ref.bonus_granted),
                "created_at": ref.created_at.isoformat() if ref.created_at else None,
            }
        )
    return web.json_response({"ok": True, "data": {"items": items}})


async def handle_index(_request: web.Request) -> web.FileResponse:
    index_path = _WEBAPP_DIR / "index.html"
    if not index_path.is_file():
        return web.Response(text="Admin UI not found", status=404)
    return web.FileResponse(index_path)


def create_admin_app(bot: Bot | None = None) -> web.Application:
    app = web.Application()
    app["telegram_bot"] = bot
    app.router.add_get("/admin/", handle_index)
    app.router.add_static("/admin/assets/", _WEBAPP_DIR / "assets", show_index=False)
    app.router.add_post("/admin/api/dashboard", handle_dashboard)
    app.router.add_post("/admin/api/users/list", handle_users_list)
    app.router.add_post("/admin/api/users/{user_id}", handle_user_detail)
    app.router.add_post("/admin/api/users/{user_id}/block", handle_user_block)
    app.router.add_post("/admin/api/users/{user_id}/bonus", handle_user_bonus)
    app.router.add_post("/admin/api/payments/list", handle_payments_list)
    app.router.add_post("/admin/api/settings", handle_settings_get)
    app.router.add_post("/admin/api/settings/update", handle_settings_post)
    app.router.add_post("/admin/api/referrals/list", handle_referrals)
    return app


_admin_runner: web.AppRunner | None = None


async def start_admin_http_server(bot: Bot | None = None) -> None:
    global _admin_runner
    from bot_secrets import ADMIN_WEBAPP_HOST, ADMIN_WEBAPP_PORT

    init_database()
    if not ADMIN_USER_IDS:
        logger.warning("ADMIN_USER_IDS пуст — mini app API откроется, но вход будет невозможен")
    app = create_admin_app(bot)
    _admin_runner = web.AppRunner(app)
    await _admin_runner.setup()
    site = web.TCPSite(_admin_runner, ADMIN_WEBAPP_HOST, ADMIN_WEBAPP_PORT)
    await site.start()
    logger.info(
        "Админ mini app: http://%s:%s/admin/ (в Telegram укажите https URL в ADMIN_WEBAPP_PUBLIC_URL)",
        ADMIN_WEBAPP_HOST,
        ADMIN_WEBAPP_PORT,
    )


async def stop_admin_http_server() -> None:
    global _admin_runner
    if _admin_runner:
        await _admin_runner.cleanup()
        _admin_runner = None
