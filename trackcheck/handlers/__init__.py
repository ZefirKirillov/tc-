from aiogram import Router

from trackcheck.keyboards.common import BackKeyboardMiddleware

router = Router()
router.message.outer_middleware(BackKeyboardMiddleware())
router.callback_query.outer_middleware(BackKeyboardMiddleware())

from . import navigation  # noqa: E402,F401
from . import dashboard  # noqa: E402,F401
from . import categories  # noqa: E402,F401
from . import ai  # noqa: E402,F401
from . import start  # noqa: E402,F401
from . import workouts  # noqa: E402,F401
from . import food  # noqa: E402,F401
from . import stats  # noqa: E402,F401
from . import settings  # noqa: E402,F401

__all__ = ["router"]
