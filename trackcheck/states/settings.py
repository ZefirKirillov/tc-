from aiogram.fsm.state import State, StatesGroup


class AIAdvisorState(StatesGroup):
    waiting_for_question = State()

class TaskState(StatesGroup):
    entering_title = State()
    choosing_repeat = State()
    choosing_days = State()
    choosing_priority = State()
    choosing_deadline = State()
    entering_deadline = State()
