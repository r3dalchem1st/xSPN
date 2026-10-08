"""
Scores actual round-robin results against their locked
predictions_snapshot.json entries: correct-winner rate, Brier score,
log-loss — mirroring score_predictions.py's WC metrics. Self-contained for
the same reason as snapshot_league.py (avoids the fit_improved.py import
chain — see this plan's Global Constraints).
"""
import json
import math
import os
import sys


def score_match(entry, actual_hg, actual_ag):
    """Score one locked prediction against its actual result. Returns
    {"correct_winner": bool, "brier": float in [0,2], "log_loss": float,
    "total_goal_error": int} (log_loss clamped away from -inf on a fully-
    confident miss). total_goal_error is |predicted − actual| goal distance
    (WC's score_predictions.py convention) — an honest exact-scoreline
    distance, not a quality grade (a 2-0 call that finishes 4-0 is a
    correct-winner + clean-sheet hit, not a 2-goal demerit); Brier/log-loss/
    correct_winner remain the metrics that grade call quality."""
    if actual_hg > actual_ag: actual = "H"
    elif actual_hg < actual_ag: actual = "A"
    else: actual = "D"
    correct = (entry["predicted_winner"] == actual)
    oh, od, oa = (1 if actual == "H" else 0), (1 if actual == "D" else 0), (1 if actual == "A" else 0)
    ph, pd_, pa = entry["ph"], entry["pd"], entry["pa"]
    brier = (ph - oh) ** 2 + (pd_ - od) ** 2 + (pa - oa) ** 2
    p_actual = {"H": ph, "D": pd_, "A": pa}[actual]
    log_loss = -math.log(max(p_actual, 1e-10))
    pred_hg, pred_ag = (int(x) for x in entry["predicted_score"].split("-"))
    total_goal_error = abs(pred_hg - actual_hg) + abs(pred_ag - actual_ag)
    result = {"correct_winner": correct, "brier": brier, "log_loss": log_loss,
              "total_goal_error": total_goal_error}
    market = entry.get("market")
    if market:
        # The bookmaker's odds as recorded when this prediction locked (see
        # snapshot_league.py) scored on the same result -- display/analysis
        # only; the model's own numbers above never see it.
        mp = (market["ph"], market["pd"], market["pa"])
        market_winner = "HDA"[mp.index(max(mp))]
        result["market_winner"] = market_winner
        result["market_correct_winner"] = market_winner == actual
        result["market_brier"] = (mp[0] - oh) ** 2 + (mp[1] - od) ** 2 + (mp[2] - oa) ** 2
        result["disagree"] = market_winner != entry["predicted_winner"]
    return result


def summarise_vs_market(matches):
    """Our record against the bookmaker over the scored matches that have a
    recorded market: accuracy/Brier for both, plus -- the number that
    answers "who's right when we disagree" -- on the matches where we picked
    DIFFERENT winners, how often each side was right (never both; the rest
    were wrong on both sides). None if no scored match has a market."""
    mm = [m for m in matches if "market_brier" in m]
    if not mm:
        return None
    n = len(mm)
    diff = [m for m in mm if m["disagree"]]
    return {
        "n": n,
        "accuracy": sum(m["correct_winner"] for m in mm) / n,
        "market_accuracy": sum(m["market_correct_winner"] for m in mm) / n,
        "avg_brier": sum(m["brier"] for m in mm) / n,
        "market_avg_brier": sum(m["market_brier"] for m in mm) / n,
        "disagree_n": len(diff),
        "we_right": sum(m["correct_winner"] for m in diff),
        "market_right": sum(m["market_correct_winner"] for m in diff),
    }


def score_and_save(config, base_dir):
    """Load <slug>/schedule.json + predictions_snapshot.json, score every
    FINISHED fixture that has a locked snapshot entry, and write
    <slug>/results_accuracy.json: {"matches": [...], "summary": {...}}.
    Fixtures without a snapshot entry (not yet due to lock, or genuinely
    never locked) are skipped, not fabricated."""
    from competition_config import artifact_dir
    out_dir = artifact_dir(config, base_dir)

    with open(os.path.join(out_dir, "schedule.json")) as f:
        schedule = json.load(f)
    snapshot_path = os.path.join(out_dir, "predictions_snapshot.json")
    if not os.path.exists(snapshot_path):
        snapshot = {}
    else:
        with open(snapshot_path) as f:
            snapshot = json.load(f)

    matches = []
    for key, entry in schedule.items():
        if entry["status"] != "FINISHED":
            continue
        if key not in snapshot:
            continue
        home, away = key.split("|")
        hg, ag = entry["goals"][home], entry["goals"][away]
        if hg is None or ag is None:
            continue
        result = score_match(snapshot[key], hg, ag)
        matches.append({"home": home, "away": away, "date": entry["date"], **result})

    n = len(matches)
    summary = {
        "n_scored": n,
        "accuracy": sum(m["correct_winner"] for m in matches) / n if n else None,
        "avg_brier": sum(m["brier"] for m in matches) / n if n else None,
        "avg_log_loss": sum(m["log_loss"] for m in matches) / n if n else None,
        "avg_goal_error": sum(m["total_goal_error"] for m in matches) / n if n else None,
    }
    vs_market = summarise_vs_market(matches)
    if vs_market:
        summary["vs_market"] = vs_market

    out = {"matches": matches, "summary": summary}
    with open(os.path.join(out_dir, "results_accuracy.json"), "w") as f:
        json.dump(out, f, indent=2)
    return out


def main():
    if len(sys.argv) != 2:
        print("usage: python score_league.py competitions/<slug>.json")
        raise SystemExit(1)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from competition_config import load_competition
    config = load_competition(sys.argv[1])
    base_dir = os.path.dirname(os.path.abspath(__file__))
    out = score_and_save(config, base_dir)
    s = out["summary"]
    print(f"{config.name}: {s['n_scored']} matches scored")
    if s["n_scored"]:
        print(f"  accuracy={s['accuracy']:.1%}  avg_brier={s['avg_brier']:.3f}  avg_log_loss={s['avg_log_loss']:.3f}")


if __name__ == "__main__":
    main()
