import json
import os
import unittest

TEST_DB = os.path.join(os.path.dirname(__file__), "_test_limits.db")


def _recipe_defaults(title: str, rid: int = 0) -> dict:
    return {
        "title": title,
        "cuisine": "italian",
        "ingredients_json": json.dumps(["курица"]),
        "steps_json": json.dumps(["шаг 1"]),
        "time_minutes": 10 + rid,
        "difficulty": "medium",
        "dish_type": "dinner",
        "cook_method": "fry",
    }


class LimitsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import database as dbmod

        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)
        dbmod.db.init(TEST_DB)
        dbmod.create_tables()

    def setUp(self):
        import database as dbmod
        from database import Recipe, UserOpenedRecipe, UserPurchasedRecipe, UsersData

        UserOpenedRecipe.delete().execute()
        UserPurchasedRecipe.delete().execute()
        Recipe.delete().execute()
        UsersData.delete().execute()
        UsersData.create(user_id=1, referral_free_bonus=0)

    def test_eleventh_unique_is_teaser(self):
        from database import Recipe, UsersData
        from services import limits

        user = UsersData.get_by_id(1)
        for i in range(11):
            Recipe.create(**_recipe_defaults(f"R{i}", i))
            rid = Recipe.select().order_by(Recipe.id.desc()).get().id
            full, first = limits.register_recipe_view(user, rid)
            self.assertTrue(first, f"iter {i}")
            if i < 10:
                self.assertTrue(full, f"iter {i} should be full")
            else:
                self.assertFalse(full)

    def test_repeat_open_same_recipe_stays_full(self):
        from database import Recipe, UsersData
        from services import limits

        user = UsersData.get_by_id(1)
        Recipe.create(**_recipe_defaults("One", 0))
        rid = Recipe.select().first().id
        f1, t1 = limits.register_recipe_view(user, rid)
        f2, t2 = limits.register_recipe_view(user, rid)
        self.assertTrue(f1 and t1)
        self.assertTrue(f2 and not t2)


if __name__ == "__main__":
    unittest.main()
