"""
Pre-match prediction locking for round-robin competitions.

Locks each fixture's predicted H/D/A + scoreline once its real date is
within LOCK_WINDOW_DAYS, append-only (a locked entry is never overwritten),
mirroring the WC's snapshot_predictions.py discipline: predictions must be
graded against what the model said BEFORE kickoff, not what it says today.

Round-robin has no bracket/round-dependency the way WC knockouts do (every
fixture is independent, and the full season's fixture list is known from
day one), so this is deliberately simpler than snapshot_predictions.py's
round-based knockout gate — a single per-match date check is sufficient and
correct here.

Self-contained (own hda_probs/likely_score, reusing only sim_league.py's
build_lambda_tables) rather than importing model_common.py — importing
anything from model_common.py transitively imports fit_improved.py
(executing its entire WC-specific module body) just to reach two pure
helper functions; not worth that coupling for a round-robin-only module.
"""
import json
import math
import os
import sys
from datetime import date

from sim_league import build_lambda_tables

LOCK_WINDOW_DAYS = 5  # WIDER than the WC's LOCK_WINDOW_DAYS=2 on purpose: this
# runs once daily (update-leagues.yml), not the WC's 4x/day, so a window this
# tight left a real permanent-miss risk — if any single daily run failed or
# was skipped inside a 2-day window, the fixture would flip to FINISHED
# before ever being locked, and fixture_due()'s own SCHEDULED-only check
# means it could never be locked retroactively (score_league.py would then
# silently skip it forever). Round-robin fixtures are known a full season
# ahead, unlike the WC's, so there's no freshness reason to lock any closer
# to kickoff than this — widening costs nothing and buys real redundancy
# against a few consecutive missed runs.


def hda_probs(home, away, lg_ens, max_g=10):
    """Mean P(home win), P(draw), P(away win) over the bootstrap ensemble.
    No draw-inflation (a World-Cup-specific calibration against
    international-match draw rates, unvalidated for round-robin — see
    sim_league.py's Global Constraints for the same reasoning)."""
    tph = tpd = tpa = 0.0
    n = 0
    for lg in lg_ens:
        lam, mu = lg[(home, away)]
        elam, emu = math.exp(-lam), math.exp(-mu)
        ph_l = [elam * lam**h / math.factorial(h) for h in range(max_g + 1)]
        pa_l = [emu * mu**a / math.factorial(a) for a in range(max_g + 1)]
        ph = pd = pa = 0.0
        for h in range(max_g + 1):
            for a in range(max_g + 1):
                p = ph_l[h] * pa_l[a]
                if h > a: ph += p
                elif h < a: pa += p
                else: pd += p
        s = ph + pd + pa
        if not s:
            continue
        tph += ph / s; tpd += pd / s; tpa += pa / s; n += 1
    return (tph / n, tpd / n, tpa / n) if n else (0.0, 0.0, 0.0)


def likely_score(lam, mu, allowed=None, max_g=6):
    """Most probable (home, away) scoreline under independent Poisson,
    optionally restricted to results in `allowed` (e.g. {"H"} to force a
    home-win-consistent scoreline, so the displayed score never contradicts
    the predicted winner)."""
    best_p, best = -1.0, (round(lam), round(mu))
    for h in range(max_g + 1):
        ph = (lam ** h * math.exp(-lam)) / math.factorial(h)
        for a in range(max_g + 1):
            res = 'H' if h > a else ('A' if h < a else 'D')
            if allowed and res not in allowed:
                continue
            p = ph * (mu ** a * math.exp(-mu)) / math.factorial(a)
            if p > best_p:
                best_p = p; best = (h, a)
    return best


def fixture_due(real_date, today, lock_window_days=LOCK_WINDOW_DAYS):
    """A fixture is lockable once its real date is within lock_window_days
    AND not already in the past (locking a past fixture would fabricate
    hindsight — copy the now-known actual result in as a fake
    "prediction"). Mirrors snapshot_predictions.py's fixture_due() exactly,
    including the explicit lower bound the WC pipeline only added after a
    live incident (6 Jul — see CONTEXT.md); written in from day one here."""
    try:
        days_until = (date.fromisoformat(real_date) - date.fromisoformat(today)).days
    except ValueError:
        return False
    return 0 <= days_until <= lock_window_days


def snapshot_and_save(config, base_dir, dc_ensemble, today=None):
    """Load <slug>/schedule.json + existing predictions_snapshot.json (if
    any), lock any newly-due fixture's current model prediction, and write
    the (possibly extended) snapshot back. `today` defaults to the real
    date but can be overridden (e.g. for testing against a schedule whose
    fixtures are all in the future). Returns the number of newly locked
    entries."""
    from competition_config import artifact_dir
    out_dir = artifact_dir(config, base_dir)
    today = today or date.today().isoformat()

    with open(os.path.join(out_dir, "schedule.json")) as f:
        schedule = json.load(f)

    snapshot_path = os.path.join(out_dir, "predictions_snapshot.json")
    if os.path.exists(snapshot_path):
        with open(snapshot_path) as f:
            snapshot = json.load(f)
    else:
        snapshot = {}

    teams = sorted({t for key in schedule for t in key.split("|")})
    lg_ens = build_lambda_tables(teams, dc_ensemble)

    added = 0
    for key, entry in schedule.items():
        if key in snapshot:
            continue
        if entry["status"] != "SCHEDULED":
            continue
        if not fixture_due(entry["date"], today):
            continue
        home, away = key.split("|")
        ph, pd, pa = hda_probs(home, away, lg_ens)
        outcome = max([("H", ph), ("D", pd), ("A", pa)], key=lambda x: x[1])[0]
        lam, mu = lg_ens[0][(home, away)]
        hg, ag = likely_score(lam, mu, allowed={outcome})
        snapshot[key] = {
            "home": home, "away": away, "date": entry["date"],
            "ph": ph, "pd": pd, "pa": pa,
            "predicted_winner": outcome, "predicted_score": f"{hg}-{ag}",
            "snapped_at": today,
        }
        added += 1

    with open(snapshot_path, "w") as f:
        json.dump(snapshot, f, indent=2)
    return added


def main():
    if len(sys.argv) != 2:
        print("usage: python snapshot_league.py competitions/<slug>.json")
        raise SystemExit(1)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from competition_config import artifact_dir, load_competition
    config = load_competition(sys.argv[1])
    base_dir = os.path.dirname(os.path.abspath(__file__))
    out_dir = artifact_dir(config, base_dir)
    with open(os.path.join(out_dir, "dc_ensemble.json")) as f:
        dc_ensemble = json.load(f)
    added = snapshot_and_save(config, base_dir, dc_ensemble)
    print(f"{config.name}: {added} new prediction(s) locked.")


if __name__ == "__main__":
    main()
