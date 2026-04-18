from aiogram.fsm.state import State, StatesGroup


class ProductsFlow(StatesGroup):
    waiting_input = State()
    disambiguate_input = State()
    choose_cook_method = State()
    choose_cook_method_extra = State()
    browsing_results = State()


class CuisinesFlow(StatesGroup):
    pick_cuisine = State()
    search_cuisine = State()
    cuisine_hub = State()
    pick_meal_type = State()
    pick_time_bucket = State()
    browsing = State()


class CabinetFlow(StatesGroup):
    main = State()


class SettingsFlow(StatesGroup):
    root = State()
    cuisines = State()
    cuisines_add = State()
    diet_veg = State()
    halal = State()
    dietetic = State()
    allergies = State()
    allergies_add = State()
    allergies_quiz = State()
    fitness = State()
    time_limit = State()
    dish_types = State()
    cook_prefs = State()
    diff_budget = State()


class QuizAllergies(StatesGroup):
    q1 = State()
    q2 = State()
    q3 = State()
