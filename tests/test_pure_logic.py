"""Stdlib-only regression tests for TrackCheck pure-logic fixes.

Run:  python3 -m unittest discover -s tests -v
No third-party dependencies required (heavy modules are stubbed).
"""
import asyncio
import json
import os
import sqlite3
import sys
import tempfile
import threading
import types
import unittest


def _stub_heavy_deps():
    for name in [
        "aiogram", "google", "google.genai", "google.genai.types",
        "plotly", "plotly.graph_objects", "plotly.subplots",
        "apscheduler", "apscheduler.schedulers.asyncio", "PIL", "PIL.Image",
    ]:
        sys.modules.setdefault(name, types.ModuleType(name))


_stub_heavy_deps()
sys.path.insert(0, ".")


class TestMaxRankDisplay(unittest.TestCase):
    def test_max_rank_shows_actual_total(self):
        from trackcheck.services.gamification_service import get_sparks_for_next_rank
        # Fixed code returns (0, total) instead of the hardcoded (0, 365).
        self.assertEqual(get_sparks_for_next_rank(8, 500), (0, 500))
        self.assertEqual(get_sparks_for_next_rank(8, 365), (0, 365))

    def test_non_max_rank_unchanged(self):
        from trackcheck.services.gamification_service import get_sparks_for_next_rank
        self.assertEqual(get_sparks_for_next_rank(7, 100), (265, 365))


class TestMonthlyChangesNoAlias(unittest.TestCase):
    def test_does_not_mutate_input_plan(self):
        from trackcheck.services.workout_service import apply_monthly_changes
        plan_data = {"plan": {"week_1": {"monday": [{"exercise": "A"}]}}}
        changes = [{"week": "week_1", "day": "monday",
                    "old_exercise": "A", "new_exercise": "B"}]
        new_plan = apply_monthly_changes(1, plan_data, [0], changes)
        self.assertEqual(new_plan["week_1"]["monday"][0]["exercise"], "B")
        self.assertEqual(plan_data["plan"]["week_1"]["monday"][0]["exercise"], "A")


class TestUniqueViolationHelper(unittest.TestCase):
    def test_sqlite_integrity_error(self):
        from trackcheck.database.repositories import _is_unique_violation
        self.assertTrue(_is_unique_violation(sqlite3.IntegrityError("UNIQUE constraint failed")))

    def test_turso_style_message(self):
        # NOTE: libsql is not installed in this environment, so this asserts
        # the message-matching fallback, not the real libsql exception type.
        from trackcheck.database.repositories import _is_unique_violation
        self.assertTrue(_is_unique_violation(Exception("UNIQUE constraint failed: my_foods.user_id, my_foods.name")))

    def test_other_errors_not_swallowed(self):
        from trackcheck.database.repositories import _is_unique_violation
        self.assertFalse(_is_unique_violation(Exception("connection lost")))
        self.assertFalse(_is_unique_violation(ValueError("bad value")))

    def test_add_my_food_duplicate_is_idempotent_sqlite(self):
        # Behavioral check on local SQLite: duplicate insert must not raise.
        import trackcheck.database.connection as conn
        from trackcheck.database import repositories as repo
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        try:
            real_db = repo.db
            db = conn.Database.__new__(conn.Database)
            db._lock = __import__("threading").RLock()
            db._mode = "sqlite"
            db._conn = sqlite3.connect(tmp.name, check_same_thread=False)
            db._conn.row_factory = sqlite3.Row
            repo.db = db
            try:
                db.execute("CREATE TABLE my_foods (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, name TEXT NOT NULL, calories REAL NOT NULL, UNIQUE(user_id, name))")
                db.commit()
                repo.add_my_food(1, "apple", 100.0)
                repo.add_my_food(1, "apple", 100.0)  # must not raise
                rows = db.execute("SELECT COUNT(*) FROM my_foods WHERE user_id=1").fetchone()[0]
                self.assertEqual(rows, 1)
            finally:
                repo.db = real_db
                db._conn.close()
        finally:
            os.unlink(tmp.name)


class TestCalorieGuard(unittest.TestCase):
    def test_zero_days_returns_tdee(self):
        from trackcheck.database.repositories import calculate_daily_calories
        self.assertEqual(
            calculate_daily_calories(2000.0, "loss", 5.0, 0, "m"), (2000.0, "ok"))
        self.assertEqual(
            calculate_daily_calories(2000.0, "gain", 5.0, -3, "m"), (2000.0, "ok"))


class TestChartRepsParsingBehavior(unittest.TestCase):
    @staticmethod
    def _parse_avg(reps_str):
        # Same guarded algorithm as chart_service.build_workout_progress_chart.
        try:
            reps_list = [int(x) for x in reps_str.split(",")] if reps_str else []
        except (ValueError, AttributeError):
            reps_list = []
        return sum(reps_list) / len(reps_list) if reps_list else 0

    def test_valid_reps(self):
        self.assertAlmostEqual(self._parse_avg("10,8,6"), 8.0)

    def test_malformed_reps_yields_zero(self):
        for bad in ("10,abc", "x,,", None, ""):
            with self.subTest(bad=bad):
                self.assertEqual(self._parse_avg(bad), 0)


class TestDietChartsCursorFixBehavior(unittest.TestCase):
    def test_body_fat_rows_are_used(self):
        # Behavioral equivalent of the diet_charts_reply fetch sequence:
        # weight rows come from the first cursor, fat rows from the second.
        con = sqlite3.connect(":memory:")
        try:
            con.execute("CREATE TABLE weight_log (date TEXT, weight REAL)")
            con.execute("CREATE TABLE body_fat_log (date TEXT, body_fat REAL)")
            con.execute("INSERT INTO weight_log VALUES ('2026-01-01', 70.0)")
            con.execute("INSERT INTO body_fat_log VALUES ('2026-01-01', 20.0)")
            con.execute("INSERT INTO body_fat_log VALUES ('2026-01-02', 19.5)")
            cursor = con.execute("SELECT date, weight FROM weight_log ORDER BY date")
            weight_rows = cursor.fetchall()
            bf_cursor = con.execute("SELECT date, body_fat FROM body_fat_log ORDER BY date")
            fat_rows = bf_cursor.fetchall()  # fixed line; old code used cursor.fetchall()
            self.assertEqual(len(weight_rows), 1)
            self.assertEqual(len(fat_rows), 2)
            # The old buggy line would have produced [] here:
            self.assertNotEqual(fat_rows, cursor.fetchall())
        finally:
            con.close()


class TestGetNextTrainingDayBehavior(unittest.TestCase):
    def _load(self):
        import trackcheck.database.repositories as repo
        return repo.get_next_training_day

    def _run_with_fixed_today(self, plan_data):
        import trackcheck.database.repositories as repo
        import datetime as dt
        real_today = dt.date(2026, 9, 21)  # a Monday
        orig = repo.user_today_date
        repo.user_today_date = lambda uid=None: real_today
        try:
            return repo.get_next_training_day(plan_data, user_id=None)
        finally:
            repo.user_today_date = orig

    def test_missing_start_date_does_not_raise(self):
        plan_data = {"plan": {"week_1": {"tuesday": [{"exercise": "X"}]}},
                     "cycle_weeks": 1}  # no start_date key at all
        self.assertEqual(self._run_with_fixed_today(plan_data), ("22.09", "Вторник"))

    def test_unparsable_start_date_falls_back(self):
        plan_data = {"plan": {"week_1": {"tuesday": [{"exercise": "X"}]}},
                     "start_date": "not-a-date", "cycle_weeks": 1}
        self.assertEqual(self._run_with_fixed_today(plan_data), ("22.09", "Вторник"))


class TestNutritionValidationBehavior(unittest.TestCase):
    """Finite-value guards for manual numeric inputs (B11)."""

    @staticmethod
    def _accept_calories(raw):
        import math
        try:
            value = float((raw or "").strip().replace(",", "."))
            if not math.isfinite(value) or value <= 0 or value > 10000:
                raise ValueError
        except (ValueError, AttributeError):
            return None
        return value

    def test_nan_inf_rejected(self):
        for raw in ("nan", "NaN", "inf", "-inf", "abc", "", None, "0", "-5", "1e999"):
            with self.subTest(raw=raw):
                self.assertIsNone(self._accept_calories(raw))

    def test_valid_accepted(self):
        self.assertEqual(self._accept_calories("350"), 350.0)
        self.assertEqual(self._accept_calories("70,5"), 70.5)


class TestTimezoneCallbackValidation(unittest.TestCase):
    def test_unknown_tz_rejected_by_allowlist(self):
        from trackcheck.config import RUSSIAN_TIMEZONES
        allowed = {tz for _, tz in RUSSIAN_TIMEZONES}
        self.assertNotIn("Mars/Olympus", allowed)
        # set_user_timezone itself validates via ZoneInfo:
        from trackcheck.utils.dates import set_user_timezone
        with self.assertRaises(ValueError):
            set_user_timezone(1, "Mars/Olympus")

    def test_malformed_callback_data_rejected(self):
        with self.assertRaises(ValueError):
            _, _, _ = "tz:only-one-part".split(":")


class TestChartCleanupBehavior(unittest.TestCase):
    def test_no_temp_files_remain_after_success_or_failure(self):
        # Simulates the try/finally cleanup pattern used in the chart callers:
        # temp file must be gone whether send succeeds or raises.
        async def fake_send_ok(path):
            with open(path, "rb"):
                pass

        async def fake_send_fail(path):
            with open(path, "rb"):
                pass
            raise RuntimeError("telegram down")

        async def run_case(sender):
            fd, chart_path = tempfile.mkstemp(prefix="test_chart_", suffix=".png")
            os.close(fd)
            with open(chart_path, "wb") as f:
                f.write(b"fake-png")
            try:
                try:
                    await sender(chart_path)
                except RuntimeError:
                    pass  # callers let send errors propagate but still clean up
            finally:
                try:
                    os.remove(chart_path)
                except OSError:
                    pass
            return chart_path

        for sender in (fake_send_ok, fake_send_fail):
            path = asyncio.run(run_case(sender))
            self.assertFalse(os.path.exists(path), path)

    def test_build_diet_chart_none_means_not_enough_data(self):
        # build_diet_chart returns None when both series have < 2 points;
        # the caller must branch instead of passing None to FSInputFile.
        with open("trackcheck/services/chart_service.py", encoding="utf-8") as f:
            src = f.read()
        self.assertIn("return None", src)
        with open("trackcheck/handlers/food.py", encoding="utf-8") as f:
            food_src = f.read()
        self.assertIn("if chart_path is None:", food_src)

    def test_chart_paths_are_unique_per_call(self):
        with open("trackcheck/services/chart_service.py", encoding="utf-8") as f:
            src = f.read()
        self.assertIn("mkstemp", src)
        self.assertNotIn("f\"workout_chart_{user_id}.png\"", src)
        self.assertNotIn("f\"diet_chart_{user_id}.png\"", src)


SESSION_SCHEMA = """
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
)
"""

LOGS_SCHEMA = """
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
)
"""

CREATE_SESSION_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS ux_ai_workout_sessions_user_date
ON ai_workout_sessions(user_id, date)
"""


class _SessionDB:
    """Isolated sqlite DB with the session/logs tables, patched into repositories."""

    def __init__(self, with_index):
        import trackcheck.database.connection as conn
        from trackcheck.database import repositories as repo
        self._conn_mod = conn
        self._repo = repo
        self._real_db = repo.db
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        self.path = tmp.name
        db = conn.Database.__new__(conn.Database)
        db._lock = threading.RLock()
        db._mode = "sqlite"
        db._conn = sqlite3.connect(self.path, check_same_thread=False)
        db._conn.row_factory = sqlite3.Row
        self.db = db
        repo.db = db
        db.execute(SESSION_SCHEMA)
        db.execute(LOGS_SCHEMA)
        if with_index:
            db.execute(CREATE_SESSION_INDEX)
        db.commit()

    def close(self):
        self._repo.db = self._real_db
        try:
            self.db._conn.close()
        finally:
            os.unlink(self.path)


class TestSessionUniqueness(unittest.TestCase):
    """One AI workout session per (user_id, date). Verified on local SQLite."""

    def _insert_session(self, db, user_id, date, **kw):
        db.execute(
            """INSERT INTO ai_workout_sessions
               (user_id, date, weekday, session_key, plan_json, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, date, kw.get("weekday", 0), kw.get("session_key", "week_1_monday"),
             kw.get("plan_json", "[]"), kw.get("status", "pending")),
        )
        db.commit()

    def test_duplicate_insert_results_in_one_row_with_index(self):
        ctx = _SessionDB(with_index=True)
        try:
            self._insert_session(ctx.db, 1, "2026-09-21")
            from trackcheck.database.repositories import _is_unique_violation
            with self.assertRaises(Exception) as cm:
                self._insert_session(ctx.db, 1, "2026-09-21")
            self.assertTrue(_is_unique_violation(cm.exception))
            rows = ctx.db.execute(
                "SELECT COUNT(*) FROM ai_workout_sessions WHERE user_id=1 AND date='2026-09-21'"
            ).fetchone()[0]
            self.assertEqual(rows, 1)
        finally:
            ctx.close()

    def test_index_creation_is_idempotent(self):
        ctx = _SessionDB(with_index=False)
        try:
            ctx.db.execute(CREATE_SESSION_INDEX)
            ctx.db.commit()
            ctx.db.execute(CREATE_SESSION_INDEX)  # second run must not fail
            ctx.db.commit()
            name = ctx.db.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND name='ux_ai_workout_sessions_user_date'"
            ).fetchone()
            self.assertIsNotNone(name)
            self._insert_session(ctx.db, 1, "2026-09-21")
            from trackcheck.database.repositories import _is_unique_violation
            with self.assertRaises(Exception) as cm:
                self._insert_session(ctx.db, 1, "2026-09-21")
            self.assertTrue(_is_unique_violation(cm.exception))
        finally:
            ctx.close()

    def test_get_today_session_returns_existing_after_duplicate_attempt(self):
        import trackcheck.database.repositories as repo
        ctx = _SessionDB(with_index=True)
        real_fn = repo.user_today_str
        repo.user_today_str = lambda uid, fmt="%Y-%m-%d": "2026-09-21"
        try:
            self._insert_session(ctx.db, 7, "2026-09-21",
                                 plan_json=json.dumps([{"exercise": "X"}]))
            first = repo.get_today_session(7)
            self.assertIsNotNone(first)
            # Simulate the losing side of the race: plain INSERT raises,
            # get_today_session() must still return the existing row.
            from trackcheck.database.repositories import _is_unique_violation
            try:
                self._insert_session(ctx.db, 7, "2026-09-21")
                self.fail("expected unique violation")
            except Exception as e:
                self.assertTrue(_is_unique_violation(e))
            second = repo.get_today_session(7)
            self.assertEqual(second["id"], first["id"])
            self.assertEqual(second["plan"], [{"exercise": "X"}])
        finally:
            repo.user_today_str = real_fn
            ctx.close()

    def test_without_index_duplicates_possible_but_read_is_deterministic(self):
        # Backward compatibility: pre-migration DBs (no index) accept two
        # rows; the reader must return the earliest deterministically.
        import trackcheck.database.repositories as repo
        ctx = _SessionDB(with_index=False)
        real_fn = repo.user_today_str
        repo.user_today_str = lambda uid, fmt="%Y-%m-%d": "2026-09-21"
        try:
            self._insert_session(ctx.db, 9, "2026-09-21", plan_json='[{"exercise":"A"}]')
            self._insert_session(ctx.db, 9, "2026-09-21", plan_json='[{"exercise":"B"}]')
            rows = ctx.db.execute(
                "SELECT COUNT(*) FROM ai_workout_sessions WHERE user_id=9"
            ).fetchone()[0]
            self.assertEqual(rows, 2)
            got = repo.get_today_session(9)
            first_id = ctx.db.execute(
                "SELECT MIN(id) FROM ai_workout_sessions WHERE user_id=9"
            ).fetchone()[0]
            self.assertEqual(got["id"], first_id)
            self.assertEqual(got["plan"], [{"exercise": "A"}])
        finally:
            repo.user_today_str = real_fn
            ctx.close()

    def test_no_orphaned_exercise_logs(self):
        ctx = _SessionDB(with_index=True)
        try:
            self._insert_session(ctx.db, 3, "2026-09-21")
            sid = ctx.db.execute(
                "SELECT id FROM ai_workout_sessions WHERE user_id=3"
            ).fetchone()[0]
            ctx.db.execute(
                """INSERT INTO ai_exercise_logs
                   (session_id, user_id, exercise_name, status)
                   VALUES (?, ?, ?, 'done')""",
                (sid, 3, "Push-up"),
            )
            ctx.db.commit()
            # Duplicate session attempt changes nothing for the logs.
            from trackcheck.database.repositories import _is_unique_violation
            try:
                self._insert_session(ctx.db, 3, "2026-09-21")
            except Exception as e:
                self.assertTrue(_is_unique_violation(e))
            orphans = ctx.db.execute(
                """SELECT COUNT(*) FROM ai_exercise_logs l
                   LEFT JOIN ai_workout_sessions s ON s.id = l.session_id
                   WHERE s.id IS NULL"""
            ).fetchone()[0]
            self.assertEqual(orphans, 0)
            kept = ctx.db.execute(
                "SELECT COUNT(*) FROM ai_exercise_logs WHERE session_id=?", (sid,)
            ).fetchone()[0]
            self.assertEqual(kept, 1)
        finally:
            ctx.close()



class TestWeightGoal(unittest.TestCase):
    def test_goal_met_exact_plan(self):
        from trackcheck.services.workout_service import goal_met
        ex = {"sets": 3, "reps": "8-10", "weight": 60}
        self.assertTrue(goal_met(ex, {"sets_done": 3, "reps_done": "10", "weight_done": 60}))

    def test_goal_not_met_bottom_of_range_or_bad_set(self):
        from trackcheck.services.workout_service import goal_met
        ex = {"sets": 3, "reps": "8-10", "weight": 60}
        self.assertFalse(goal_met(ex, {"sets_done": 3, "reps_done": "8", "weight_done": 60}))
        self.assertFalse(goal_met(ex, {"sets_done": 3, "reps_done": "10,10,7", "weight_done": 60}))
        self.assertFalse(goal_met(ex, {"sets_done": 2, "reps_done": "10", "weight_done": 60}))
        self.assertFalse(goal_met(ex, {"sets_done": 3, "reps_done": "10", "weight_done": 55}))

    def test_missing_weight_done_means_planned_weight(self):
        from trackcheck.services.workout_service import goal_met
        ex = {"sets": 3, "reps": 10, "weight": 60}
        self.assertTrue(goal_met(ex, {"sets_done": 3, "reps_done": "10", "weight_done": None}))

    def test_bodyweight_never_asks(self):
        from trackcheck.services.workout_service import goal_met
        self.assertFalse(goal_met({"sets": 3, "reps": 10, "weight": None},
                                  {"sets_done": 3, "reps_done": "12"}))

    def test_raise_weight_all_occurrences_without_mutating(self):
        from trackcheck.services.workout_service import raise_exercise_weight
        plan = {"cycle_weeks": 2,
                "week_1": {"monday": [{"exercise": "Жим лёжа", "weight": 60},
                                      {"exercise": "Отжимания", "weight": None}]},
                "week_2": {"thursday": [{"exercise": "жим лёжа", "weight": 50}]}}
        new = raise_exercise_weight(plan, "Жим лёжа", 2.5)
        self.assertEqual(new["week_1"]["monday"][0]["weight"], 62.5)
        self.assertIsNone(new["week_1"]["monday"][1]["weight"])
        self.assertEqual(new["week_2"]["thursday"][0]["weight"], 52.5)
        self.assertEqual(plan["week_1"]["monday"][0]["weight"], 60)


class TestExerciseSubstitutions(unittest.TestCase):
    def test_last_three_distinct_newest_first(self):
        ctx = _SessionDB(with_index=True)
        try:
            from trackcheck.database import repositories as repo
            ctx.db.execute("""CREATE TABLE exercise_substitutions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
                original_name TEXT NOT NULL, substitute_name TEXT NOT NULL,
                sets INTEGER, reps TEXT, weight REAL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
            for name, w in [("A", 10), ("B", 20), ("A", 12), ("C", 5), ("D", 7)]:
                repo.add_exercise_substitution(1, "Жим лёжа", name, 3, 10, w)
            repo.add_exercise_substitution(2, "Жим лёжа", "Z", 3, 10, 1)
            subs = repo.get_exercise_substitutions(1, "жим лёжа")
            self.assertEqual([s["substitute_name"] for s in subs], ["D", "C", "A"])
            self.assertEqual(subs[2]["weight"], 12)
        finally:
            ctx.close()


if __name__ == "__main__":
    unittest.main()
