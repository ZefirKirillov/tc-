from aiogram.fsm.state import State, StatesGroup


class RatingState(StatesGroup):
    waiting_for_rating = State()
    waiting_for_mood_text = State()
