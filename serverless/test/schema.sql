CREATE TABLE ratings (
            user_id INTEGER,
            category TEXT,
            rating INTEGER,
            day_date TEXT,
            PRIMARY KEY (user_id, category, day_date)
        );
CREATE TABLE workouts (
            user_id INTEGER PRIMARY KEY,
            monthly_goal INTEGER DEFAULT 0,
            current_count INTEGER DEFAULT 0,
            last_workout_date TEXT,
            today_count INTEGER DEFAULT 0
        );
CREATE TABLE user_ranks (
            user_id INTEGER PRIMARY KEY,
            total_sparks INTEGER DEFAULT 0,
            current_rank INTEGER DEFAULT 1,
            last_spark_date TEXT,
            sparks_today INTEGER DEFAULT 0,
            categories_completed_today INTEGER DEFAULT 0,
            workout_completed_today INTEGER DEFAULT 0
        );
CREATE TABLE user_settings (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            notification_enabled INTEGER DEFAULT 1,
            streak_days INTEGER DEFAULT 0,
            last_active_date TEXT,
            last_ai_answer TEXT DEFAULT NULL,
            timezone TEXT DEFAULT NULL
        , notify_enabled INTEGER DEFAULT 1, notify_muted_until TEXT DEFAULT NULL, notify_msg_id INTEGER DEFAULT NULL);
CREATE TABLE diet_profile (
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
        );
CREATE TABLE diet_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            date TEXT,
            meal_type TEXT,
            food_description TEXT,
            calories REAL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        , protein REAL DEFAULT NULL, fat REAL DEFAULT NULL, carbs REAL DEFAULT NULL);
CREATE TABLE exercise_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            ex_type TEXT NOT NULL DEFAULT 'strength',
            UNIQUE(user_id, name)
        );
CREATE TABLE exercises (
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
        );
CREATE TABLE workout_log (
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
        );
CREATE TABLE weight_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            weight REAL NOT NULL
        );
CREATE TABLE body_fat_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            body_fat REAL NOT NULL
        );
CREATE TABLE my_foods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            calories REAL NOT NULL, protein REAL DEFAULT NULL, fat REAL DEFAULT NULL, carbs REAL DEFAULT NULL,
            UNIQUE(user_id, name)
        );
CREATE TABLE reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            remind_time TEXT NOT NULL,
            recurring TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
CREATE TABLE workout_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
CREATE TABLE plan_exercises (
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
        );
CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            is_priority INTEGER DEFAULT 0,
            deadline TEXT,
            repeat_days TEXT,
            is_done INTEGER DEFAULT 0,
            done_date TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
CREATE TABLE ai_workout_plan (
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
        );
CREATE TABLE ai_workout_sessions (
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
        );
CREATE UNIQUE INDEX ux_ai_workout_sessions_user_date
        ON ai_workout_sessions(user_id, date)
    ;
CREATE TABLE ai_exercise_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            exercise_name TEXT NOT NULL,
            planned_json TEXT,
            raw_input TEXT,
            result_json TEXT,
            status TEXT DEFAULT 'pending',
            FOREIGN KEY(session_id) REFERENCES ai_workout_sessions(id) ON DELETE CASCADE
        );
CREATE TABLE exercise_substitutions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            original_name TEXT NOT NULL,
            substitute_name TEXT NOT NULL,
            sets INTEGER,
            reps TEXT,
            weight REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
CREATE TABLE body_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            score INTEGER NOT NULL,
            summary TEXT,
            strengths TEXT,
            weaknesses TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
CREATE TABLE potential_notes (
            user_id INTEGER NOT NULL,
            kind TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            signature TEXT NOT NULL,
            what TEXT NOT NULL,
            fix TEXT NOT NULL,
            PRIMARY KEY (user_id, kind, start_date, end_date, signature)
        );
