import json
from datetime import datetime
from typing import Any

from peewee import (
    AutoField,
    BooleanField,
    CharField,
    CompositeKey,
    DateTimeField,
    ForeignKeyField,
    IntegerField,
    Model,
    SqliteDatabase,
    TextField,
)

db = SqliteDatabase("AI_Receipts_Bot.db", thread_safe=True)


class BaseModelData(Model):
    class Meta:
        database = db


class UsersData(BaseModelData):
    user_id = IntegerField(primary_key=True)
    created_at = DateTimeField(default=datetime.utcnow)
    referral_free_bonus = IntegerField(default=0)
    free_show_more_uses = IntegerField(default=0)
    favorite_cuisines_json = TextField(default="[]")
    zoj_prefs_json = TextField(default="[]")
    allergies_strict_json = TextField(default="[]")
    max_time_minutes = IntegerField(null=True)
    time_strict = BooleanField(default=False)
    dish_types_pref_json = TextField(default="[]")
    settings_return_json = TextField(null=True)
    subscription_expires_at = DateTimeField(null=True)
    subscription_lapse_started_at = DateTimeField(null=True)
    lapse_notifications_sent_json = TextField(default="[]")
    subscription_expiry_reminders_json = TextField(default="[]")
    archive_purge_at = DateTimeField(null=True)
    search_history_json = TextField(default="[]")
    pending_referrer_id = IntegerField(null=True)
    # Расширенные настройки подбора (10 разделов)
    diet_profile_json = TextField(default="{}")
    halal_only = BooleanField(default=False)
    dietetic_tables_json = TextField(default="[]")
    fitness_prefs_json = TextField(default="[]")
    preferred_cook_methods_json = TextField(default="[]")
    allowed_difficulties_json = TextField(default="[]")
    budget_tier = CharField(max_length=32, null=True)
    onboarding_shown = BooleanField(default=False)
    username = CharField(max_length=64, null=True)
    first_name = CharField(max_length=128, null=True)
    is_blocked = BooleanField(default=False)
    last_seen_at = DateTimeField(null=True)

    class Meta:
        db_table = "users_data"


class Recipe(BaseModelData):
    id = AutoField()
    title = CharField(max_length=255)
    cuisine = CharField(max_length=64, index=True)
    ingredients_json = TextField()
    steps_json = TextField()
    time_minutes = IntegerField(index=True)
    difficulty = CharField(max_length=32)
    dish_type = CharField(max_length=32, index=True)
    cook_method = CharField(max_length=32, index=True)
    tags_json = TextField(default="[]")
    restrictions_json = TextField(default="[]")
    calories = IntegerField(null=True)
    short_description = TextField(default="")
    is_published = BooleanField(default=True)
    popularity = IntegerField(default=0)
    global_last_opened_at = DateTimeField(null=True, index=True)
    dish_image_path = TextField(null=True)
    ai_chat_model = CharField(max_length=64, null=True)
    # Подпись кухни для отчётов/админки (русский текст без служебного slug u_…)
    cuisine_display_ru = TextField(null=True)

    class Meta:
        db_table = "recipes"


class UserOpenedRecipe(BaseModelData):
    user = ForeignKeyField(UsersData, field=UsersData.user_id, on_delete="CASCADE")
    recipe = ForeignKeyField(Recipe, field=Recipe.id, on_delete="CASCADE")
    opened_at = DateTimeField(default=datetime.utcnow)
    was_full_free = BooleanField(default=True)

    class Meta:
        db_table = "user_opened_recipe"
        primary_key = CompositeKey("user", "recipe")


class UserPurchasedRecipe(BaseModelData):
    user = ForeignKeyField(UsersData, field=UsersData.user_id, on_delete="CASCADE")
    recipe = ForeignKeyField(Recipe, field=Recipe.id, on_delete="CASCADE")
    purchased_at = DateTimeField(default=datetime.utcnow)
    telegram_payment_charge_id = CharField(max_length=128, null=True)

    class Meta:
        db_table = "user_purchased_recipe"
        primary_key = CompositeKey("user", "recipe")


class UserSavedRecipe(BaseModelData):
    user = ForeignKeyField(UsersData, field=UsersData.user_id, on_delete="CASCADE")
    recipe = ForeignKeyField(Recipe, field=Recipe.id, on_delete="CASCADE")
    saved_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        db_table = "user_saved_recipe"
        primary_key = CompositeKey("user", "recipe")


class Referral(BaseModelData):
    referrer_id = IntegerField()
    invitee_id = IntegerField()
    bonus_granted = BooleanField(default=False)
    created_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        db_table = "referrals"
        primary_key = CompositeKey("referrer_id", "invitee_id")


class StarPayment(BaseModelData):
    """Учёт оплат Telegram Stars (для админки и аналитики)."""

    id = AutoField()
    user_id = IntegerField(index=True)
    amount = IntegerField()
    payment_type = CharField(max_length=32, index=True)
    recipe_id = IntegerField(null=True, index=True)
    telegram_payment_charge_id = CharField(max_length=128, default="")
    created_at = DateTimeField(default=datetime.utcnow, index=True)

    class Meta:
        db_table = "star_payments"


class BotRuntimeSettings(BaseModelData):
    """Переопределение настроек монетизации без правки .env (одна строка id=1)."""

    id = IntegerField(primary_key=True)
    base_free_recipe_opens = IntegerField()
    recipe_star_price = IntegerField()
    show_more_star_price = IntegerField()
    subscription_star_price = IntegerField()
    subscription_default_days = IntegerField()
    free_show_more_count = IntegerField()
    referral_bonus_opens = IntegerField()
    daily_recipe_last_sent_date = CharField(max_length=10, null=True)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        db_table = "bot_runtime_settings"


ALL_MODELS = [
    UsersData,
    Recipe,
    UserOpenedRecipe,
    UserPurchasedRecipe,
    UserSavedRecipe,
    Referral,
    StarPayment,
    BotRuntimeSettings,
]


def create_tables():
    with db:
        db.create_tables(ALL_MODELS, safe=True)


def migrate_users_schema() -> None:
    """Добавляет новые колонки в users_data для существующих SQLite-файлов."""
    cursor = db.execute_sql("PRAGMA table_info(users_data)")
    existing = {row[1] for row in cursor.fetchall()}
    additions: list[tuple[str, str]] = [
        ("diet_profile_json", "TEXT DEFAULT '{}'"),
        ("halal_only", "INTEGER DEFAULT 0"),
        ("dietetic_tables_json", "TEXT DEFAULT '[]'"),
        ("fitness_prefs_json", "TEXT DEFAULT '[]'"),
        ("preferred_cook_methods_json", "TEXT DEFAULT '[]'"),
        ("allowed_difficulties_json", "TEXT DEFAULT '[]'"),
        ("budget_tier", "TEXT"),
        ("subscription_expiry_reminders_json", "TEXT DEFAULT '[]'"),
        ("onboarding_shown", "INTEGER DEFAULT 0"),
    ]
    for col, ddl in additions:
        if col not in existing:
            db.execute_sql(f"ALTER TABLE users_data ADD COLUMN {col} {ddl}")
    admin_cols: list[tuple[str, str]] = [
        ("username", "VARCHAR(64)"),
        ("first_name", "VARCHAR(128)"),
        ("is_blocked", "INTEGER DEFAULT 0"),
        ("last_seen_at", "DATETIME"),
    ]
    cursor = db.execute_sql("PRAGMA table_info(users_data)")
    existing = {row[1] for row in cursor.fetchall()}
    for col, ddl in admin_cols:
        if col not in existing:
            db.execute_sql(f"ALTER TABLE users_data ADD COLUMN {col} {ddl}")


def migrate_recipes_schema() -> None:
    cursor = db.execute_sql("PRAGMA table_info(recipes)")
    existing = {row[1] for row in cursor.fetchall()}
    if "global_last_opened_at" not in existing:
        db.execute_sql("ALTER TABLE recipes ADD COLUMN global_last_opened_at DATETIME")
    if "dish_image_path" not in existing:
        db.execute_sql("ALTER TABLE recipes ADD COLUMN dish_image_path TEXT")
    if "ai_chat_model" not in existing:
        db.execute_sql("ALTER TABLE recipes ADD COLUMN ai_chat_model VARCHAR(64)")
    if "cuisine_display_ru" not in existing:
        db.execute_sql("ALTER TABLE recipes ADD COLUMN cuisine_display_ru TEXT")


def ensure_bot_runtime_settings_row() -> None:
    import config as _cfg

    if BotRuntimeSettings.select().where(BotRuntimeSettings.id == 1).exists():
        return
    BotRuntimeSettings.create(
        id=1,
        base_free_recipe_opens=_cfg.BASE_FREE_RECIPE_OPENS,
        recipe_star_price=_cfg.RECIPE_STAR_PRICE,
        show_more_star_price=_cfg.SHOW_MORE_STAR_PRICE,
        subscription_star_price=_cfg.SUBSCRIPTION_STAR_PRICE,
        subscription_default_days=_cfg.SUBSCRIPTION_DEFAULT_DAYS,
        free_show_more_count=_cfg.FREE_SHOW_MORE_COUNT,
        referral_bonus_opens=_cfg.REFERRAL_BONUS_OPENS,
        daily_recipe_last_sent_date=None,
    )


def migrate_runtime_settings_schema() -> None:
    cursor = db.execute_sql("PRAGMA table_info(bot_runtime_settings)")
    existing = {row[1] for row in cursor.fetchall()}
    if "daily_recipe_last_sent_date" not in existing:
        db.execute_sql("ALTER TABLE bot_runtime_settings ADD COLUMN daily_recipe_last_sent_date VARCHAR(10)")


def init_database():
    if db.is_closed():
        db.connect()
    create_tables()
    migrate_users_schema()
    migrate_recipes_schema()
    migrate_runtime_settings_schema()
    ensure_bot_runtime_settings_row()


def _jloads(s: str, default: Any) -> Any:
    try:
        return json.loads(s) if s else default
    except json.JSONDecodeError:
        return default


def ensure_user(user_id: int, referrer_from_start: int | None = None) -> UsersData:
    user, _ = UsersData.get_or_create(user_id=user_id)
    if referrer_from_start and referrer_from_start != user_id:
        if user.pending_referrer_id is None:
            user.pending_referrer_id = referrer_from_start
            user.save()
    return user


def get_user(user_id: int) -> UsersData | None:
    try:
        return UsersData.get_by_id(user_id)
    except UsersData.DoesNotExist:
        return None


def sync_telegram_profile(
    user_id: int,
    username: str | None,
    first_name: str | None,
) -> None:
    user, _ = UsersData.get_or_create(user_id=user_id)
    user.username = username[:64] if username else None
    user.first_name = first_name[:128] if first_name else None
    user.last_seen_at = datetime.utcnow()
    user.save()


def user_has_recipe_in_archive(user_id: int, recipe_id: int) -> bool:
    return (
        UserSavedRecipe.select()
        .where(
            (UserSavedRecipe.user_id == user_id) & (UserSavedRecipe.recipe_id == recipe_id)
        )
        .exists()
    )
