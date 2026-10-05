import os
import sqlite3
import threading
import time

from trackcheck.config import DB_PATH, TURSO_DATABASE_URL, TURSO_AUTH_TOKEN, USE_TURSO, libsql


class _CompatRow:
    """Даёт результату из libsql тот же интерфейс, что и sqlite3.Row:
    доступ по индексу, по имени колонки, dict(row), .keys() — чтобы весь
    остальной код (написанный под sqlite3.Row) не пришлось переписывать."""
    __slots__ = ('_cols', '_data')

    def __init__(self, cols, values):
        self._cols = cols
        self._data = tuple(values)

    def __getitem__(self, key):
        if isinstance(key, str):
            return self._data[self._cols.index(key)]
        return self._data[key]

    def keys(self):
        return list(self._cols)

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data)

    def __repr__(self):
        return f"<Row {dict(zip(self._cols, self._data))}>"



class _CompatCursor:
    """Оборачивает курсор libsql так, чтобы fetchone()/fetchall() возвращали
    _CompatRow вместо голых кортежей (как sqlite3.Row делает для sqlite3)."""

    def __init__(self, raw_cursor):
        self._cur = raw_cursor

    def _cols(self):
        return [d[0] for d in (self._cur.description or [])]

    def fetchone(self):
        row = self._cur.fetchone()
        return None if row is None else _CompatRow(self._cols(), row)

    def fetchall(self):
        cols = self._cols()
        return [_CompatRow(cols, r) for r in self._cur.fetchall()]

    @property
    def lastrowid(self):
        return getattr(self._cur, 'lastrowid', None)

    @property
    def rowcount(self):
        return getattr(self._cur, 'rowcount', -1)



class _BufferedCursor:
    """Результат запроса, полностью прочитанный ПОД lock'ом.

    Соединение одно на весь процесс и используется из нескольких потоков (пул run_db,
    Mini App API, планировщик). Если отдавать «живой» курсор и делать fetchone()
    уже после выхода из lock'а, запись/commit из другого потока в этот промежуток
    сбрасывает незавершённое чтение — и fetchone() молча возвращает None
    (воспроизведено: «пропадающий» план тренировки → оценка активности не ставилась).
    Поэтому строки забираются сразу, а наружу уходит только буфер."""
    __slots__ = ('_rows', '_pos', 'lastrowid', 'rowcount', 'description')

    def __init__(self, rows, lastrowid, rowcount, description):
        self._rows = rows
        self._pos = 0
        self.lastrowid = lastrowid
        self.rowcount = rowcount
        self.description = description

    def fetchone(self):
        if self._pos >= len(self._rows):
            return None
        row = self._rows[self._pos]
        self._pos += 1
        return row

    def fetchall(self):
        rows = self._rows[self._pos:]
        self._pos = len(self._rows)
        return rows

    def fetchmany(self, size: int = 1):
        rows = self._rows[self._pos:self._pos + size]
        self._pos += len(rows)
        return rows

    def __iter__(self):
        while True:
            row = self.fetchone()
            if row is None:
                return
            yield row



class Database:
    """
    Обёртка над одним постоянным соединением с базой данных.
    Режим 'turso': подключение напрямую к облачной Turso по сети, без
    локального файла - данные переживают любой редеплой.
    Режим 'sqlite': локальный файл, как раньше (фолбэк для локальной
    разработки без облачной БД).
    Оба режима дают одинаковый интерфейс execute()/commit()/close(), так что
    остальной код бота не завязан на то, какой режим сейчас активен.
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_connection()
        return cls._instance

    def _init_connection(self):
        self._lock = threading.RLock()
        if USE_TURSO:
            self._mode = 'turso'
            self._conn = libsql.connect(database=TURSO_DATABASE_URL, auth_token=TURSO_AUTH_TOKEN)
        else:
            self._mode = 'sqlite'
            self._conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON")

    def execute(self, query: str, params: tuple = ()):
        t_wait = time.perf_counter()
        with self._lock:
            t_run = time.perf_counter()
            try:
                return self._execute_locked(query, params)
            finally:
                _log_if_slow(query, t_run - t_wait, time.perf_counter() - t_run)

    def _execute_locked(self, query: str, params: tuple):
        _q = query.strip().upper()
        is_write = _q.startswith(
            ('INSERT', 'UPDATE', 'DELETE', 'CREATE', 'DROP', 'ALTER', 'PRAGMA')
        )
        if _q.startswith(('INSERT', 'UPDATE', 'DELETE')):
            # Лог тяжёлых действий в Render livetail (stdout).
            # Только форматирование уже имеющихся аргументов — без доп.
            # запросов, ~микросекунды. Отключение: ACTION_LOG_ENABLED=0.
            try:
                from trackcheck.utils.action_log import log_action
                uid = params[0] if params and isinstance(params[0], int) else None
                one_line = ' '.join(query.split())
                log_action(_q.split()[0] + '_DB', uid, one_line[:120])
            except Exception:
                pass
        if self._mode == 'turso':
            cur = self._conn.execute(query, params)
            if is_write:
                try:
                    self._conn.commit()
                except Exception as e:
                    # Некоторые режимы Turso автокоммитят каждый запрос сами -
                    # тогда commit() может быть не нужен/не поддержан. Не роняем
                    # бота из-за этого, но логируем на случай если причина другая.
                    print(f"[DB-TURSO] commit() после записи: {e}")
            wrapped = _CompatCursor(cur)
            desc = getattr(cur, 'description', None)
            rows = wrapped.fetchall() if desc else []
            return _BufferedCursor(rows, wrapped.lastrowid, wrapped.rowcount, desc)
        else:
            cur = self._conn.cursor()
            cur.execute(query, params)
            if is_write:
                self._conn.commit()
            rows = cur.fetchall() if cur.description else []
            return _BufferedCursor(rows, cur.lastrowid, cur.rowcount, cur.description)

    def commit(self):
        with self._lock:
            self._conn.commit()

    def close(self):
        with self._lock:
            self._conn.close()



# Диагностика скорости: каждый запрос к Turso — сетевой round-trip, и все они
# идут через один lock. Логируем медленные (порог DB_SLOW_MS, 0 — выключить),
# отдельно время ожидания lock'а — оно показывает очередь из других запросов.
_SLOW_MS = float(os.environ.get("DB_SLOW_MS", "250"))


def _log_if_slow(query: str, wait_s: float, run_s: float) -> None:
    if _SLOW_MS <= 0 or (wait_s + run_s) * 1000 < _SLOW_MS:
        return
    try:
        q = ' '.join(query.split())[:90]
        print(f"[DB-SLOW] {run_s * 1000:.0f}ms query, {wait_s * 1000:.0f}ms lock wait | {q}", flush=True)
    except Exception:
        pass


db = Database()



def init_db():
    db.execute('''
        CREATE TABLE IF NOT EXISTS ratings (
            user_id INTEGER,
            category TEXT,
            rating INTEGER,
            day_date TEXT,
            PRIMARY KEY (user_id, category, day_date)
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS workouts (
            user_id INTEGER PRIMARY KEY,
            monthly_goal INTEGER DEFAULT 0,
            current_count INTEGER DEFAULT 0,
            last_workout_date TEXT,
            today_count INTEGER DEFAULT 0
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS user_ranks (
            user_id INTEGER PRIMARY KEY,
            total_sparks INTEGER DEFAULT 0,
            current_rank INTEGER DEFAULT 1,
            last_spark_date TEXT,
            sparks_today INTEGER DEFAULT 0,
            categories_completed_today INTEGER DEFAULT 0,
            workout_completed_today INTEGER DEFAULT 0
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            notification_enabled INTEGER DEFAULT 1,
            streak_days INTEGER DEFAULT 0,
            last_active_date TEXT,
            last_ai_answer TEXT DEFAULT NULL,
            timezone TEXT DEFAULT NULL
        )
    ''')
    cursor = db.execute("PRAGMA table_info(user_settings)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'last_ai_answer' not in columns:
        db.execute("ALTER TABLE user_settings ADD COLUMN last_ai_answer TEXT DEFAULT NULL")
    if 'timezone' not in columns:
        db.execute("ALTER TABLE user_settings ADD COLUMN timezone TEXT DEFAULT NULL")
    if 'notify_enabled' not in columns:
        db.execute("ALTER TABLE user_settings ADD COLUMN notify_enabled INTEGER DEFAULT 1")
    if 'notify_muted_until' not in columns:
        db.execute("ALTER TABLE user_settings ADD COLUMN notify_muted_until TEXT DEFAULT NULL")
    if 'notify_msg_id' not in columns:
        db.execute("ALTER TABLE user_settings ADD COLUMN notify_msg_id INTEGER DEFAULT NULL")
    db.execute("UPDATE user_settings SET notification_enabled = 1 WHERE notification_enabled IS NULL")
    db.execute('''
        CREATE TABLE IF NOT EXISTS diet_profile (
            user_id INTEGER PRIMARY KEY,
            weight REAL,
            height REAL,
            age INTEGER,
            gender TEXT,
            activity_level REAL,
            goal_type TEXT,
            target_weight_change REAL,
            target_days INTEGER,
            daily_calories REAL,
            last_update_date TEXT
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS diet_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            date TEXT,
            meal_type TEXT,
            food_description TEXT,
            calories REAL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor = db.execute("PRAGMA table_info(diet_log)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'meal_type' not in columns:
        db.execute("ALTER TABLE diet_log ADD COLUMN meal_type TEXT DEFAULT 'Еда'")
    db.execute('''
        CREATE TABLE IF NOT EXISTS exercise_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            ex_type TEXT NOT NULL DEFAULT 'strength',
            UNIQUE(user_id, name)
        )
    ''')
    cursor = db.execute("PRAGMA table_info(exercise_categories)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'ex_type' not in columns:
        db.execute("ALTER TABLE exercise_categories ADD COLUMN ex_type TEXT NOT NULL DEFAULT 'strength'")
    db.execute('''
        CREATE TABLE IF NOT EXISTS exercises (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            target_sets INTEGER,
            target_reps TEXT,
            target_weight REAL,
            target_distance REAL,
            target_duration INTEGER,
            weight_increment REAL,
            last_achieved_date TEXT,
            FOREIGN KEY(category_id) REFERENCES exercise_categories(id) ON DELETE CASCADE,
            UNIQUE(user_id, category_id, name)
        )
    ''')
    cursor = db.execute("PRAGMA table_info(exercises)")
    existing_columns = [col[1] for col in cursor.fetchall()]
    columns_to_add = [
        ('target_sets', 'INTEGER'),
        ('target_reps', 'TEXT'),
        ('target_weight', 'REAL'),
        ('target_distance', 'REAL'),
        ('target_duration', 'INTEGER'),
        ('weight_increment', 'REAL'),
        ('last_achieved_date', 'TEXT')
    ]
    for col_name, col_type in columns_to_add:
        if col_name not in existing_columns:
            db.execute(f"ALTER TABLE exercises ADD COLUMN {col_name} {col_type}")
    db.execute('''
        CREATE TABLE IF NOT EXISTS workout_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            category_id INTEGER,
            exercise_name TEXT NOT NULL,
            sets INTEGER,
            reps TEXT,
            weight REAL,
            distance REAL,
            duration INTEGER,
            FOREIGN KEY(category_id) REFERENCES exercise_categories(id) ON DELETE SET NULL
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS weight_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            weight REAL NOT NULL
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS body_fat_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            body_fat REAL NOT NULL
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS my_foods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            calories REAL NOT NULL,
            UNIQUE(user_id, name)
        )
    ''')
    # Таблицы для умных напоминаний
    db.execute('''
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            remind_time TEXT NOT NULL,
            recurring TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS workout_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS plan_exercises (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER NOT NULL,
            exercise_id INTEGER NOT NULL,
            sets INTEGER,
            reps TEXT,
            weight REAL,
            distance REAL,
            duration INTEGER,
            day_of_week INTEGER,
            FOREIGN KEY(plan_id) REFERENCES workout_plans(id) ON DELETE CASCADE,
            FOREIGN KEY(exercise_id) REFERENCES exercises(id) ON DELETE CASCADE
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            is_priority INTEGER DEFAULT 0,
            deadline TEXT,
            repeat_days TEXT,
            is_done INTEGER DEFAULT 0,
            done_date TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # Таблицы для новой системы тренировок с ИИ
    db.execute('''
        CREATE TABLE IF NOT EXISTS ai_workout_plan (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            mode TEXT NOT NULL DEFAULT 'ai',
            goal TEXT,
            level TEXT,
            days_per_week INTEGER,
            plan_json TEXT NOT NULL,
            cycle_weeks INTEGER DEFAULT 1,
            start_date TEXT,
            last_monthly_review TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS ai_workout_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            weekday INTEGER NOT NULL,
            session_key TEXT NOT NULL,
            plan_json TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            skip_reason TEXT,
            feedback TEXT,
            completed_at TEXT
        )
    ''')
    # One AI workout session per user per date. Idempotent: safe to run on
    # every startup and on databases created before this index existed.
    # NOTE: on a database that already contains duplicate (user_id, date)
    # rows this statement fails — resolve duplicates first (see the
    # production migration plan), never silently.
    db.execute('''
        CREATE UNIQUE INDEX IF NOT EXISTS ux_ai_workout_sessions_user_date
        ON ai_workout_sessions(user_id, date)
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS ai_exercise_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            exercise_name TEXT NOT NULL,
            planned_json TEXT,
            raw_input TEXT,
            result_json TEXT,
            status TEXT DEFAULT 'pending',
            FOREIGN KEY(session_id) REFERENCES ai_workout_sessions(id) ON DELETE CASCADE
        )
    ''')
    db.commit()
