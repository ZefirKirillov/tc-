"""Rule-based auto ratings for «еда» and «активность» (trackcheck/services/tracker_service.py).

Run:  python3 -m unittest discover -s tests -v
Stdlib-only: pure scoring functions, no DB or network.
"""
import sys
import types
import unittest

for _name in ["aiogram", "google", "google.genai", "google.genai.types",
              "plotly", "plotly.graph_objects", "plotly.subplots",
              "apscheduler", "apscheduler.schedulers.asyncio", "PIL", "PIL.Image"]:
    sys.modules.setdefault(_name, types.ModuleType(_name))
sys.path.insert(0, ".")

from trackcheck.services.tracker_service import (  # noqa: E402
    diet_score, exercise_score, workout_score, _num,
)


class TestDietScore(unittest.TestCase):
    def test_final_on_goal_is_10(self):
        self.assertEqual(diet_score(2000, 2000), 10)
        self.assertEqual(diet_score(1950, 2000), 10)   # 2.5% under
        self.assertEqual(diet_score(2090, 2000), 10)   # 4.5% over

    def test_final_scale_is_symmetric(self):
        self.assertEqual(diet_score(1800, 2000), 9)    # 10% under
        self.assertEqual(diet_score(2200, 2000), 9)    # 10% over
        self.assertEqual(diet_score(1000, 2000), 3)    # 50% under
        self.assertEqual(diet_score(3000, 2000), 3)    # 50% over

    def test_final_far_off_is_1(self):
        self.assertEqual(diet_score(300, 2000), 1)
        self.assertEqual(diet_score(5000, 2000), 1)

    def test_nothing_eaten_or_no_goal_is_1(self):
        self.assertEqual(diet_score(0, 2000), 1)
        self.assertEqual(diet_score(0, 2000, hour_float=12), 1)
        self.assertEqual(diet_score(1500, 0), 1)

    def test_intraday_uses_pace(self):
        # 13:00 → ~55% expected. 1100/2000 = on pace → 10.
        self.assertEqual(diet_score(1100, 2000, hour_float=13), 10)
        # 10:00 → ~32% expected (640 kcal). 500 kcal ≈ 22% behind pace → 6, not a 2 against the full day.
        self.assertEqual(diet_score(500, 2000, hour_float=10), 6)
        self.assertEqual(diet_score(500, 2000), 1)

    def test_intraday_ahead_of_pace_but_under_goal_is_fine(self):
        self.assertEqual(diet_score(1500, 2000, hour_float=12), 10)

    def test_intraday_over_goal_still_penalised(self):
        self.assertEqual(diet_score(2600, 2000, hour_float=15), 5)  # 30% over → same as final
        self.assertEqual(diet_score(2600, 2000), 5)


class TestNum(unittest.TestCase):
    def test_parsing(self):
        self.assertEqual(_num(3), 3.0)
        self.assertEqual(_num("6-8"), 6.0)
        self.assertEqual(_num("120кг"), 120.0)
        self.assertEqual(_num("92,5"), 92.5)
        self.assertIsNone(_num("собств. вес"))
        self.assertIsNone(_num(None))
        self.assertIsNone(_num(0))
        self.assertIsNone(_num(True))


class TestWorkoutScore(unittest.TestCase):
    BENCH = {"exercise": "Жим", "sets": 4, "reps": 6, "weight": 100}
    SQUAT = {"exercise": "Присед", "sets": 3, "reps": "6-8", "weight": "80кг"}
    PLANK = {"exercise": "Планка", "sets": 3, "reps": "60 сек", "weight": None}

    @staticmethod
    def done(name, **res):
        return {"exercise_name": name, "status": "done", "result": res}

    def test_exercise_as_planned_is_full(self):
        log = self.done("Жим", sets_done=4, reps_done=6, weight_done=100)
        self.assertEqual(exercise_score(self.BENCH, log), 1.0)

    def test_exceeding_plan_is_capped(self):
        log = self.done("Жим", sets_done=5, reps_done=8, weight_done=110)
        self.assertEqual(exercise_score(self.BENCH, log), 1.0)

    def test_partial_exercise(self):
        log = self.done("Жим", sets_done=2, reps_done=6, weight_done=100)   # sets 50%
        self.assertAlmostEqual(exercise_score(self.BENCH, log), (0.5 + 1 + 1) / 3)

    def test_skipped_and_missing_are_zero(self):
        self.assertEqual(exercise_score(self.BENCH, {"exercise_name": "Жим", "status": "skipped"}), 0.0)
        self.assertEqual(exercise_score(self.BENCH, None), 0.0)

    def test_done_without_numbers_counts_as_full(self):
        self.assertEqual(exercise_score(self.PLANK, self.done("Планка")), 1.0)

    def test_whole_workout(self):
        plan = [self.BENCH, self.SQUAT, self.PLANK]
        perfect = [self.done("Жим", sets_done=4, reps_done=6, weight_done=100),
                   self.done("Присед", sets_done=3, reps_done=8, weight_done=80),
                   self.done("Планка", sets_done=3, reps_done=60)]
        self.assertEqual(workout_score(plan, perfect), 10)
        one_skipped = perfect[:2] + [{"exercise_name": "Планка", "status": "skipped"}]
        self.assertEqual(workout_score(plan, one_skipped), 7)   # 2/3 → 1 + 9·0.67 = 7
        self.assertEqual(workout_score(plan, []), 1)            # nothing logged

    def test_rounding_is_half_up(self):
        # 2 exercises, 1 done → 1 + 9·0.5 = 5.5 → 6
        half = [self.done("Жим", sets_done=4, reps_done=6, weight_done=100)]
        self.assertEqual(workout_score([self.BENCH, self.SQUAT], half), 6)
        # 9 exercises: 5 full + 1 at 50% + 3 skipped → 1 + 9·(5.5/9) = 6.5 → 7 (banker's round() would give 6)
        plan = [{"exercise": f"E{i}", "sets": 4} for i in range(9)]
        logs = [self.done(f"E{i}", sets_done=4) for i in range(5)] + [self.done("E5", sets_done=2)]
        self.assertEqual(workout_score(plan, logs), 7)

    def test_string_weights_from_plan(self):
        log = self.done("Присед", sets_done=3, reps_done=6, weight_done="60кг")   # 75% weight
        self.assertAlmostEqual(exercise_score(self.SQUAT, log), (1 + 1 + 0.75) / 3)


if __name__ == "__main__":
    unittest.main()
