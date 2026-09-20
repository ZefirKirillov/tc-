from aiogram.fsm.state import State, StatesGroup


class WorkoutState(StatesGroup):
    waiting_for_goal = State()
    choosing_category = State()
    choosing_exercise = State()
    entering_reps = State()
    entering_weight = State()
    entering_distance = State()
    entering_duration = State()
    confirm_continue = State()
    creating_category = State()
    renaming_category = State()
    deleting_category_confirm = State()
    creating_exercise = State()
    renaming_exercise = State()
    deleting_exercise_confirm = State()
    setting_goal_type = State()
    setting_strength_goal = State()
    setting_weight_increment = State()
    setting_cardio_goal = State()
    current_cat_id = State()
    current_ex_id = State()

class AIPlanState(StatesGroup):
    choosing_mode = State()       # ai или manual
    choosing_goal = State()       # цель тренировок
    choosing_level = State()      # уровень
    choosing_days_count = State() # дней в неделю
    reviewing_plan = State()      # просмотр сгенерированного плана
    editing_plan = State()        # редактирование через ИИ
    entering_manual_plan = State()# ввод ручного плана
    entering_extra_notes = State() # доп пожелания

class WorkoutSessionState(StatesGroup):
    viewing_plan = State()        # экран плана на сегодня
    in_exercise = State()         # идёт упражнение
    entering_result = State()     # ввод текста результата
    skipping_day = State()        # ввод причины пропуска дня
    monthly_review = State()      # месячный пересмотр упражнений
