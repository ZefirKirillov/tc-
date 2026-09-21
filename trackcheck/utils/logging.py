import os

from trackcheck.database.connection import db
from trackcheck.config import (USE_TURSO, TURSO_DATABASE_URL, TURSO_AUTH_TOKEN,
                               DB_PATH, libsql)


def log_db_persistence_diagnostics():
    """Печатает в лог, какой режим БД активен и куда фактически идут данные.
    Полезно для диагностики 'после редеплоя бот всё забыл'."""
    print(f"[DB] Режим: {'Turso (удалённая БД, без локального файла)' if USE_TURSO else 'локальный файл SQLite'}")
    if TURSO_DATABASE_URL and TURSO_AUTH_TOKEN and libsql is None:
        print("[DB] ⚠️ TURSO_DATABASE_URL и TURSO_AUTH_TOKEN заданы, но пакет libsql не установлен - "
              "добавь 'libsql' в requirements.txt. Пока используется локальный файл (не переживёт редеплой).")
    if USE_TURSO:
        print(f"[DB] TURSO_DATABASE_URL: {TURSO_DATABASE_URL}")
        try:
            tasks_count = db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
            ratings_count = db.execute("SELECT COUNT(*) FROM ratings").fetchone()[0]
            print(f"[DB] Текущие данные в Turso: tasks={tasks_count}, ratings={ratings_count}")
        except Exception as e:
            print(f"[DB] Не удалось прочитать счётчики строк из Turso (возможно таблицы ещё не созданы): {e}")
        return
    abs_path = os.path.abspath(DB_PATH)
    existed_before = os.path.exists(abs_path)
    size = os.path.getsize(abs_path) if existed_before else 0
    print(f"[DB] DB_PATH env: {os.environ.get('DB_PATH', '<не задан, используется default tracker.db>')}")
    print(f"[DB] Абсолютный путь к файлу БД: {abs_path}")
    print(f"[DB] Файл существовал до старта: {existed_before} (размер: {size} байт)")
    print("[DB] ⚠️ Turso не настроен (нет TURSO_DATABASE_URL/TURSO_AUTH_TOKEN) - используется локальный "
          "файл. На большинстве хостингов с эфемерной файловой системой (в т.ч. Infrlo) он не "
          "переживёт редеплой. Задай TURSO_DATABASE_URL и TURSO_AUTH_TOKEN, чтобы данные хранились "
          "в облаке Turso и не терялись.")
    try:
        tasks_count = db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        ratings_count = db.execute("SELECT COUNT(*) FROM ratings").fetchone()[0]
        print(f"[DB] Текущие данные: tasks={tasks_count}, ratings={ratings_count}")
    except Exception as e:
        print(f"[DB] Не удалось прочитать счётчики строк (возможно таблицы ещё не созданы): {e}")



def log_ratings_ai_diagnostics():
    """Печатает при старте, настроен ли отдельный ключ для авто-оценки Еды/Активности/Настроя.
    Если ключа нет - sync_diet_rating_for_today/sync_activity_rating_for_today и мод-флоу
    молча ничего не делают (это осознанное поведение - чтобы не выдумывать оценку),
    поэтому по симптомам ('значения не обновляются', 'настрой всегда просит оценить вручную')
    это выглядит как баг, хотя на самом деле просто не задана переменная окружения."""
    key_present = bool(
        os.environ.get("NARA_API") or os.environ.get("NARA_API_KEY")
        or os.environ.get("NARA_API_RATINGS") or os.environ.get("NARA_API_KEY_RATINGS")
        or os.environ.get("GOOGLE_API_KEY_RATINGS") or os.environ.get("GEMINI_API_KEY_RATINGS")
    )
    print(f"[RATINGS-AI] Ratings AI key настроен: {key_present} "
          f"(Nara: {bool(os.environ.get('NARA_API') or os.environ.get('NARA_API_KEY'))})")
    if not key_present:
        print("[RATINGS-AI] ⚠️ Ключ не задан - авто-оценка 'еда'/'активность' и AI-оценка 'настроя' "
              "не будут работать (тихо ничего не делают), 'настрой' всегда будет уходить в ручной ввод. "
              "Задайте переменную окружения NARA_API (тот же ключ покрывает и рейтинги), "
              "либо NARA_API_RATINGS / GOOGLE_API_KEY_RATINGS для отдельного ключа.")
    else:
        print(f"[AI] NaraRouter: base={os.environ.get('NARA_BASE_URL', 'https://router.bynara.id/v1')}, "
              f"model={os.environ.get('NARA_MODEL', 'ling-3.0-flash-vl-free')}")
