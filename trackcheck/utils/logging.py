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
        os.environ.get("VYCE_API_KEY") or os.environ.get("VYCE_API_KEY_RATINGS")
        or os.environ.get("ATRIA_API_KEY") or os.environ.get("ATRIA_API_KEY_RATINGS")
        or os.environ.get("GOOGLE_API_KEY_RATINGS") or os.environ.get("GEMINI_API_KEY_RATINGS")
    )
    print(f"[RATINGS-AI] Ratings AI key настроен: {key_present} "
          f"(Vyce: {bool(os.environ.get('VYCE_API_KEY'))}, "
          f"Atria: {bool(os.environ.get('ATRIA_API_KEY'))})")
    if not key_present:
        print("[RATINGS-AI] ⚠️ Ключ не задан - авто-оценка 'еда'/'активность' и AI-оценка 'настроя' "
              "не будут работать (тихо ничего не делают), 'настрой' всегда будет уходить в ручной ввод. "
              "Задайте переменную окружения VYCE_API_KEY или ATRIA_API_KEY (тот же ключ покрывает и рейтинги), "
              "либо VYCE_API_KEY_RATINGS / GOOGLE_API_KEY_RATINGS для отдельного ключа.")
    else:
        if os.environ.get("VYCE_API_KEY"):
            print(f"[AI] Vyce: base={os.environ.get('VYCE_BASE_URL', 'https://vyceai.com/v1')}, "
                  f"model={os.environ.get('VYCE_MODEL', 'deepseek-v4-flash')}")
        if os.environ.get("ATRIA_API_KEY"):
            print(f"[AI] Atria: base={os.environ.get('ATRIA_BASE_URL', 'https://api.atria-asi.ai/v1')}, "
                  f"model={os.environ.get('ATRIA_MODEL', 'Atria-Dawn-Preview')}, "
                  f"reasoning_effort={os.environ.get('ATRIA_REASONING_EFFORT', 'low') or '-'}")
        print("[AI] Каждый ИИ-вызов логируется строкой [AI-ROUTE] "
              "(caller/provider/model/reason); детали — в строках [VYCE]/[ATRIA]/[GEMINI].")
        if os.environ.get("GIGACHAT_AUTH_KEY") or os.environ.get("GIGACHAT_CREDENTIALS"):
            print(f"[AI] GigaChat (только фото): model={os.environ.get('GIGACHAT_MODEL', 'GigaChat-2-Max')}")
        print("[AI] Fallback-цепочка: текст — Vyce (VYCE_API_KEY) → Atria (ATRIA_API_KEY) → Google; "
              "фото — GigaChat (GIGACHAT_AUTH_KEY) → Google (GOOGLE_API_KEY, если задан).")
