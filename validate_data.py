"""
Sanity-check the training data before the model is fit. Catches the kind of
fat-fingered entry (impossible score, bad date, unknown tournament, malformed
row) that would silently skew predictions. Exits non-zero on any hard error so
the CI workflow stops before publishing a corrupted forecast.
"""
import sys, os
from datetime import date, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from match_data import MATCHES, TOURNAMENT_WEIGHTS

MAX_GOALS = 20                      # higher than any real international result
FUTURE_SLACK = timedelta(days=2)    # allow a little clock skew
today = date.today()
known_tournaments = set(TOURNAMENT_WEIGHTS)

errors, warnings = [], []
seen = {}

for i, row in enumerate(MATCHES):
    where = f"row {i}: {row!r}"
    if not (isinstance(row, tuple) and len(row) == 7):
        errors.append(f"{where} — not a 7-field tuple"); continue
    d, home, away, hg, ag, tour, neutral = row

    try:
        y, m, dd = map(int, d.split("-")); md = date(y, m, dd)
    except Exception:
        errors.append(f"{where} — bad date {d!r}"); md = None
    if md and md > today + FUTURE_SLACK:
        errors.append(f"{where} — date {d} is in the future")

    if not home or not away or home == away:
        errors.append(f"{where} — bad team names")
    if not (isinstance(hg, int) and isinstance(ag, int) and 0 <= hg <= MAX_GOALS and 0 <= ag <= MAX_GOALS):
        errors.append(f"{where} — implausible score {hg}-{ag}")
    if not isinstance(neutral, bool):
        errors.append(f"{where} — neutral flag not boolean: {neutral!r}")
    if tour not in known_tournaments:
        warnings.append(f"{where} — unknown tournament {tour!r} (weight defaults to 1.0)")

    key = (d, tuple(sorted([str(home), str(away)])))
    if key in seen and seen[key] == row:
        errors.append(f"{where} — exact duplicate of an earlier row")
    seen[key] = row

print(f"Validated {len(MATCHES)} matches: {len(errors)} error(s), {len(warnings)} warning(s).")
for w in warnings[:20]: print("  WARN:", w)
for e in errors[:40]:   print("  ERROR:", e)
if errors:
    print("Data validation FAILED — refusing to fit on bad data.")
    sys.exit(1)
print("Data validation passed.")
