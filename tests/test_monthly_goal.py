"""Monthly workout goal derived from the plan (fixes «1/0 тренировок»).

Run:  python3 -m unittest discover -s tests -v
"""
import os
import sys
import tempfile
import types
import unittest

for _name in ["aiogram", "google", "google.genai", "google.genai.types",
              "plotly", "plotly.graph_objects", "plotly.subplots",
              "apscheduler", "apscheduler.schedulers.asyncio", "PIL", "PIL.Image"]:
    sys.modules.setdefault(_name, types.ModuleType(_name))
os.environ.setdefault("DB_PATH", tempfile.mktemp(suffix=".db"))
sys.path.insert(0, ".")

from datetime import date  # noqa: E402
from trackcheck.database.repositories import count_planned_days, count_planned_days_in_month  # noqa: E402
from trackcheck.utils.formatting import workouts_progress  # noqa: E402

EX = [{"exercise": "Жим", "sets": 3, "reps": 5}]


def plan(weeks: dict, start: str, cycle: int = 1) -> dict:
    return {"plan": {"cycle_weeks": cycle, **weeks}, "start_date": start, "cycle_weeks": cycle}


class TestPlannedDays(unittest.TestCase):
    # October 2026: the 1st is a Thursday, 31 days.
    MWF = {"week_1": {"monday": EX, "wednesday": EX, "friday": EX}}

    def test_full_month(self):
        # Mondays 5,12,19,26 + Wednesdays 7,14,21,28 + Fridays 2,9,16,23,30
        self.assertEqual(count_planned_days_in_month(plan(self.MWF, "2026-09-01"), 2026, 10), 13)

    def test_plan_started_mid_month_counts_from_start(self):
        # from Thu 15th: Fri 16,23,30 + Mon 19,26 + Wed 21,28
        self.assertEqual(count_planned_days_in_month(plan(self.MWF, "2026-10-15"), 2026, 10), 7)

    def test_two_week_cycle(self):
        weeks = {"week_1": {"monday": EX}, "week_2": {"friday": EX}}
        # start Mon 5th: w1 Mon 5 · w2 Fri 16 · w1 Mon 19 · w2 Fri 30
        self.assertEqual(count_planned_days_in_month(plan(weeks, "2026-10-05", cycle=2), 2026, 10), 4)

    def test_rest_only_or_broken_plan_is_zero(self):
        self.assertEqual(count_planned_days_in_month(plan({"week_1": {}}, "2026-10-01"), 2026, 10), 0)
        self.assertEqual(count_planned_days_in_month({"plan": None}, 2026, 10), 0)
        self.assertEqual(count_planned_days_in_month({}, 2026, 10), 0)

    def test_unparsable_start_date_counts_whole_month(self):
        self.assertEqual(count_planned_days_in_month(plan(self.MWF, "not-a-date"), 2026, 10), 13)


class TestPlannedDaysThisWeek(unittest.TestCase):
    MWF = {"week_1": {"monday": EX, "wednesday": EX, "friday": EX}}
    WEEK = (date(2026, 10, 5), date(2026, 10, 11))   # Mon..Sun

    def test_week_counts_scheduled_days_not_wizard_answer(self):
        p = plan(self.MWF, "2026-09-01")
        p["days_per_week"] = 0   # the stored wizard answer that caused «1/0»
        self.assertEqual(count_planned_days(p, *self.WEEK), 3)

    def test_plan_started_mid_week(self):
        self.assertEqual(count_planned_days(plan(self.MWF, "2026-10-07"), *self.WEEK), 2)   # Wed + Fri

    def test_cycle_week_is_respected(self):
        weeks = {"week_1": {"monday": EX, "tuesday": EX}, "week_2": {"friday": EX}}
        p = plan(weeks, "2026-09-28", cycle=2)    # 28.09 = week_1, 05.10 = week_2
        self.assertEqual(count_planned_days(p, *self.WEEK), 1)


class TestProgressText(unittest.TestCase):
    def test_with_goal(self):
        self.assertEqual(workouts_progress({"current_count": 3, "monthly_goal": 12}), "3/12")

    def test_without_goal_no_slash_zero(self):
        self.assertEqual(workouts_progress({"current_count": 1, "monthly_goal": 0}), "1")
        self.assertEqual(workouts_progress({}), "0")


if __name__ == "__main__":
    unittest.main()
