import json, os, random, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
os.environ.update(DB_PATH="/dev/null", TURSO_DATABASE_URL="")
sys.stdout, _OUT = sys.stderr, sys.stdout
from trackcheck.services import potential_service as ps
from datetime import date, timedelta
random.seed(int(sys.argv[1]))
cases = []
for _ in range(60):
    n = random.randint(5, 45)
    start = date(2026, 1, 1)
    dates = [(start + timedelta(days=i)).isoformat() for i in range(n)]
    by = {}
    mood = random.randint(3, 9)
    for d in dates:
        if random.random() < 0.15:
            continue
        mood = max(1, min(10, mood + random.choice([-3, -1, 0, 0, 1, 2])))
        by[d] = {c: max(1, min(10, mood + random.randint(-2, 2))) for c in ps.CATEGORIES if random.random() < 0.8}
    body = sorted({(random.choice(dates), random.randint(3, 9)) for _ in range(random.randint(0, 3))})
    series = ps.build_series(dates, by, body)
    segs = ps.find_segments(series)
    out = []
    for s in segs:
        out.append({**s, "signature": ps.segment_signature(series, s), "fallback": ps.fallback_note(series, s),
                    "prompt": ps.note_prompt("Тест", series, s)})
    cases.append({"dates": dates, "by": by, "body": body, "series": series, "segments": out})
_OUT.write(json.dumps(cases, ensure_ascii=False))
