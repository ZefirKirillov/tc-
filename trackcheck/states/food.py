from aiogram.fsm.state import State, StatesGroup


class DietState(StatesGroup):
    weight = State()
    height = State()
    age = State()
    gender = State()
    activity = State()
    goal = State()
    target_weight = State()
    target_days = State()
    confirm = State()
    meal_type = State()
    food_description = State()
    manual_calories = State()
    food_confirm = State()
    new_food_name = State()
    new_food_calories = State()
    log_weight = State()
    body_fat_measurements = State()
