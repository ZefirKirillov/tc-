"""«Реализованный потенциал» (trackcheck/services/potential_service.py) и разбор
оценки тела (trackcheck/services/body_score_service.py).

Run:  python3 -m unittest discover -s tests -v
Stdlib-only: pure functions, no DB or network.
"""
import sys
import types
import unittest
from datetime import date, timedelta

for _name in ["aiogram", "google", "google.genai", "google.genai.types",
              "plotly", "plotly.graph_objects", "plotly.subplots",
              "apscheduler", "apscheduler.schedulers.asyncio", "PIL", "PIL.Image"]:
    sys.modules.setdefault(_name, types.ModuleType(_name))
sys.path.insert(0, ".")

from trackcheck.services.potential_service import (  # noqa: E402
    build_series, find_segments, segment_facts, fallback_note, segment_signature,
)
from trackcheck.services.body_score_service import parse_body_score  # noqa: E402


def days(n, start=date(2026, 10, 1)):
    return [(start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]


def full(sleep=8, idle=8, mood=8, food=8, act=8):
    return {"сон": sleep, "зависание": idle, "настрой": mood, "еда": food, "активность": act}


def series_of(totals, body=0):
    """Ряд, где итог дня = заданное число (через «еду»; остальное по нулям), None = пропуск."""
    ds = days(len(totals))
    ratings = {}
    for d, t in zip(ds, totals):
        if t is not None:
            ratings[d] = {"сон": 0, "зависание": 0, "настрой": 0, "еда": t, "активность": 0}
    return build_series(ds, ratings, [(ds[0], body)] if body else [])


class TestBuildSeries(unittest.TestCase):
    def test_sum_of_four_parts(self):
        ds = days(1)
        s = build_series(ds, {ds[0]: full(sleep=9, idle=6, mood=6, food=7, act=10)}, [(ds[0], 6)])
        self.assertEqual(s[0]["parts"], {"wellbeing": 7, "diet": 7, "training": 10, "body": 6})
        self.assertEqual(s[0]["total"], 30)
        self.assertFalse(s[0]["filled"])

    def test_body_carries_until_next_photo(self):
        ds = days(4)
        r = {d: full() for d in ds}
        s = build_series(ds, r, [(ds[0], 5), (ds[2], 7)])
        self.assertEqual([p["parts"]["body"] for p in s], [5, 5, 7, 7])

    def test_no_photo_yet_is_zero(self):
        ds = days(2)
        r = {d: full() for d in ds}
        s = build_series(ds, r, [(ds[1], 6)])
        self.assertEqual([p["parts"]["body"] for p in s], [0, 6])

    def test_missing_day_holds_level_and_is_filled(self):
        ds = days(4)
        r = {ds[0]: full(), ds[3]: full(food=2)}
        s = build_series(ds, r, [])
        self.assertEqual([p["total"] for p in s], [24, 24, 24, 18])
        self.assertEqual([p["filled"] for p in s], [False, True, True, False])

    def test_no_line_before_first_data(self):
        ds = days(3)
        s = build_series(ds, {ds[2]: full()}, [])
        self.assertEqual([p["total"] for p in s], [None, None, 24])

    def test_unrated_category_carries_from_last_known(self):
        ds = days(2)
        r = {ds[0]: full(sleep=4, food=6), ds[1]: {"активность": 9}}
        s = build_series(ds, r, [])
        self.assertEqual(s[1]["parts"]["diet"], 6)
        self.assertEqual(s[1]["parts"]["training"], 9)
        self.assertAlmostEqual(s[1]["parts"]["wellbeing"], round((4 + 8 + 8) / 3, 1))

    def test_never_rated_category_is_zero(self):
        ds = days(1)
        s = build_series(ds, {ds[0]: {"сон": 6}}, [])
        self.assertEqual(s[0]["parts"], {"wellbeing": 6, "diet": 0, "training": 0, "body": 0})


class TestSegments(unittest.TestCase):
    def test_drawback_from_peak_to_recovery(self):
        segs = find_segments(series_of([30, 31, 22, 20, 29, 30]))
        self.assertEqual(len(segs), 1)
        s = segs[0]
        self.assertEqual(s["kind"], "drawback")
        self.assertEqual((s["start"], s["end"]), (days(6)[1], days(6)[3]))
        self.assertEqual((s["from"], s["to"]), (31, 20))

    def test_low_stretch_after_drop_is_a_plateau(self):
        segs = find_segments(series_of([31, 22, 22, 21, 22, 22, 22, 31]))
        self.assertEqual([s["kind"] for s in segs], ["drawback", "plateau"])
        self.assertEqual((segs[0]["start"], segs[0]["end"]), (days(8)[0], days(8)[1]))
        self.assertEqual((segs[1]["start"], segs[1]["end"]), (days(8)[2], days(8)[6]))

    def test_small_dip_is_not_a_drawback(self):
        self.assertEqual(find_segments(series_of([30, 31, 27, 30, 31])), [])

    def test_plateau_needs_five_days_in_band(self):
        segs = find_segments(series_of([20, 21, 20, 22, 21, 30]))
        self.assertEqual([s["kind"] for s in segs], ["plateau"])
        self.assertEqual((segs[0]["start"], segs[0]["end"]), (days(6)[0], days(6)[4]))
        self.assertEqual(find_segments(series_of([20, 21, 20, 22, 30])), [])

    def test_high_level_is_not_a_plateau(self):
        self.assertEqual(find_segments(series_of([36, 37, 36, 37, 36, 37])), [])

    def test_filled_days_are_ignored(self):
        # 2 real days and a long gap: the flat dotted part must not count as a plateau
        self.assertEqual(find_segments(series_of([20, 21, None, None, None, None, 21])), [])

    def test_plateau_does_not_overlap_drawback(self):
        segs = find_segments(series_of([30, 20, 20, 21, 20, 21, 20]))
        kinds = [s["kind"] for s in segs]
        self.assertIn("drawback", kinds)
        dr = next(s for s in segs if s["kind"] == "drawback")
        for s in segs:
            if s["kind"] == "plateau":
                self.assertGreater(s["start"], dr["end"])


class TestNotes(unittest.TestCase):
    def test_drawback_facts_name_biggest_drop_first(self):
        ds = days(3)
        r = {ds[0]: full(act=10, sleep=8), ds[1]: full(act=1, sleep=5), ds[2]: full(act=1, sleep=5)}
        s = build_series(ds, r, [])
        seg = find_segments(s)[0]
        facts = segment_facts(s, seg)
        self.assertEqual(facts["changes"][0], ("активность", 10, 1))
        note = fallback_note(s, seg)
        self.assertIn("тренировка 10→1", note["what"])
        self.assertTrue(note["fix"])

    def test_plateau_note_names_weakest(self):
        ds = days(5)
        r = {d: full(food=3) for d in ds}
        s = build_series(ds, r, [])
        seg = find_segments(s)[0]
        self.assertEqual(seg["kind"], "plateau")
        self.assertIn("тело", fallback_note(s, seg)["what"])  # no photo → body 0 is weakest

    def test_signature_follows_data(self):
        ds = days(3)
        a = build_series(ds, {ds[0]: full(act=10), ds[1]: full(act=1), ds[2]: full(act=1)}, [])
        b = build_series(ds, {ds[0]: full(act=10), ds[1]: full(act=1, sleep=3), ds[2]: full(act=1)}, [])
        seg = find_segments(a)[0]
        self.assertNotEqual(segment_signature(a, seg), segment_signature(b, seg))
        self.assertEqual(segment_signature(a, seg), segment_signature(a, seg))


class TestParseBodyScore(unittest.TestCase):
    def test_parses_and_clamps(self):
        r = parse_body_score('```json\n{"score": 12, "summary": "ок", "strengths": ["плечи"],'
                             ' "weaknesses": [{"spot": "пресс", "fix": "планка"}, "ноги"]}\n```')
        self.assertEqual(r["score"], 10)
        self.assertEqual(r["strengths"], ["плечи"])
        self.assertEqual(r["weaknesses"], [{"spot": "пресс", "fix": "планка"}, {"spot": "ноги", "fix": ""}])

    def test_no_body(self):
        self.assertEqual(parse_body_score('{"error": "no_body"}'), {"error": "no_body"})

    def test_garbage_is_none(self):
        self.assertIsNone(parse_body_score("не могу"))
        self.assertIsNone(parse_body_score('{"score": "много"}'))
        self.assertIsNone(parse_body_score(None))


if __name__ == "__main__":
    unittest.main()
