import json
import os
import unittest

TEST_DB = os.path.join(os.path.dirname(__file__), "_test_search.db")


class SearchFiltersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import database as dbmod

        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)
        dbmod.db.init(TEST_DB)
        dbmod.create_tables()

    def setUp(self):
        from database import Recipe, UsersData

        from database import UserOpenedRecipe, UserPurchasedRecipe

        UserOpenedRecipe.delete().execute()
        UserPurchasedRecipe.delete().execute()
        Recipe.delete().execute()
        UsersData.delete().execute()
        UsersData.create(user_id=1)
        Recipe.create(
            title="Ореховый салат",
            cuisine="italian",
            ingredients_json=json.dumps(["орехи", "салат"]),
            steps_json="[]",
            time_minutes=15,
            difficulty="medium",
            dish_type="lunch",
            cook_method="raw",
        )

    def test_allergy_nuts_excludes(self):
        from database import Recipe, UsersData
        from services.search import passes_hard_filters

        user = UsersData.get_by_id(1)
        user.allergies_strict_json = json.dumps(["nuts"])
        user.save()
        r = Recipe.select().first()
        self.assertFalse(passes_hard_filters(r, user))

    def test_allergy_custom_text_excludes(self):
        from database import Recipe, UsersData
        from services.search import passes_hard_filters
        from settings_catalog import ALLERGY_CUSTOM_TYPE

        user = UsersData.get_by_id(1)
        user.allergies_strict_json = json.dumps(
            [{"type": ALLERGY_CUSTOM_TYPE, "l": "мёд", "s": "u_honey"}],
        )
        user.save()
        Recipe.create(
            title="Чай с мёдом",
            cuisine="russian",
            ingredients_json=json.dumps(["чай", "лимон"]),
            steps_json="[]",
            time_minutes=5,
            difficulty="easy",
            dish_type="drink",
            cook_method="boil",
        )
        r = Recipe.select().where(Recipe.title == "Чай с мёдом").first()
        self.assertFalse(passes_hard_filters(r, user))


if __name__ == "__main__":
    unittest.main()
