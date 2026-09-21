import os

try:
    import libsql
except ImportError:
    libsql = None


BOT_TOKEN = os.getenv("BOT_TOKEN")



NARA_API_KEY = os.getenv("NARA_API") or os.getenv("NARA_API_KEY")
NARA_BASE_URL = os.getenv("NARA_BASE_URL", "https://router.bynara.id/v1")
NARA_MODEL = os.getenv("NARA_MODEL", "ling-3.0-flash-vl-free")

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")



BACK_BUTTON_TEXT = "🔙 Назад"



BACK_BUTTON_CALLBACK = "nav_back"



RANKS = {
    1: {"name": "Первые Искры", "emoji": "✨", "sparks_needed": 1, "motivation": "Первый шаг сделан! Искра зажжена, путь начат!"},
    2: {"name": "Искрящийся", "emoji": "💥", "sparks_needed": 7, "motivation": "Ты искришься энергией! Каждый день делает тебя ярче!"},
    3: {"name": "Горящий Огнем", "emoji": "🔥", "sparks_needed": 14, "motivation": "Ты горишь огнём прогресса! Ничто не остановит твой настрой!"},
    4: {"name": "Восходящая звезда", "emoji": "💫", "sparks_needed": 31, "motivation": "Ты восходишь над горизонтом! Твой свет заметен всем!"},
    5: {"name": "Супер звезда", "emoji": "⭐️", "sparks_needed": 62, "motivation": "Супер звезда во всей красе! Твоя дисциплина вдохновляет!"},
    6: {"name": "Яркий", "emoji": "🌟", "sparks_needed": 93, "motivation": "Ты сияешь как никто другой! Яркость твоей дисциплины ослепляет!"},
    7: {"name": "Самый Яркий", "emoji": "☀️", "sparks_needed": 183, "motivation": "Ты — центр вселенной продуктивности! Самый яркий из всех!"},
    8: {"name": "Нейтронная Звезда", "emoji": "❤️‍🔥", "sparks_needed": 365, "motivation": "Невероятная плотность дисциплины! Ты — явление вселенского масштаба!"}
}



MAX_SPARKS_PER_DAY = 2



SPARK_FOR_CATEGORIES = 1



SPARK_FOR_WORKOUT = 1



DB_PATH = os.environ.get('DB_PATH', 'tracker.db')



TURSO_DATABASE_URL = os.environ.get('TURSO_DATABASE_URL')



TURSO_AUTH_TOKEN = os.environ.get('TURSO_AUTH_TOKEN')



USE_TURSO = bool(TURSO_DATABASE_URL and TURSO_AUTH_TOKEN and libsql is not None)



DEFAULT_TIMEZONE = "Europe/Moscow"



RUSSIAN_TIMEZONES = [
    ("Калининград (UTC+2)", "Europe/Kaliningrad"),
    ("Москва (UTC+3)", "Europe/Moscow"),
    ("Самара (UTC+4)", "Europe/Samara"),
    ("Екатеринбург (UTC+5)", "Asia/Yekaterinburg"),
    ("Омск (UTC+6)", "Asia/Omsk"),
    ("Красноярск (UTC+7)", "Asia/Krasnoyarsk"),
    ("Иркутск (UTC+8)", "Asia/Irkutsk"),
    ("Владивосток (UTC+10)", "Asia/Vladivostok"),
]



WEEKDAY_NAMES = {0: "Пн", 1: "Вт", 2: "Ср", 3: "Чт", 4: "Пт", 5: "Сб", 6: "Вс"}



WEEKDAY_RU = {0: "Понедельник", 1: "Вторник", 2: "Среда",
              3: "Четверг", 4: "Пятница", 5: "Суббота", 6: "Воскресенье"}



WEEKDAY_SHORT = {0: "Пн", 1: "Вт", 2: "Ср", 3: "Чт", 4: "Пт", 5: "Сб", 6: "Вс"}



WEEKDAY_KEY = {0: "monday", 1: "tuesday", 2: "wednesday",
               3: "thursday", 4: "friday", 5: "saturday", 6: "sunday"}



WEEKDAY_FROM_KEY = {v: k for k, v in WEEKDAY_KEY.items()}
