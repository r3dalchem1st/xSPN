import numpy as np

from validate_sim import (EVENTS, event_probs, final_order, null_ensemble, run_checkpoint, summarize,
                          table_from)

TEAMS = ["A", "B", "C", "D", "E", "F", "G", "H"]


def _row(d, h, a, hg, ag):
    return {"date": d, "home": h, "away": a, "hg": hg, "ag": ag, "market": None}


def test_table_from_awards_points_and_goal_stats():
    t = table_from([_row("2024-01-01", "A", "B", 2, 1), _row("2024-01-02", "B", "A", 0, 0)])
    assert t["A"] == {"pts": 4, "gd": 1, "gf": 2} and t["B"] == {"pts": 1, "gd": -1, "gf": 1}


def test_final_order_breaks_ties_on_goal_difference_then_goals_for():
    rows = [_row("2024-01-01", "A", "B", 1, 0), _row("2024-01-02", "C", "D", 3, 2)]
    # A and C both finish on 3 points; C has the better goal difference? both +1 -> goals for decides
    assert final_order(rows)[:2] == ["C", "A"]


def test_event_probs_slice_the_rank_distribution():
    dist = {"A": [0.5, 0.3, 0.1, 0.05, 0.03, 0.01, 0.005, 0.005], "B": [0.5, 0.2, 0.1, 0.1, 0.05, 0.03, 0.01, 0.01]}
    out = event_probs(dist)
    assert out["A"]["title"] == 0.5
    assert abs(out["A"]["top4"] - 0.95) < 1e-9
    assert abs(out["A"]["relegation"] - 0.02) < 1e-9


def test_null_ensemble_rates_every_team_equal():
    ens = null_ensemble(TEAMS, 0.3)
    assert len(ens) == 1 and set(ens[0]["attack"].values()) == {0.0} and ens[0]["home_adv"] == 0.3


def _season(year, seed):
    rng = np.random.default_rng(seed)
    pairs = [(h, a) for h in TEAMS for a in TEAMS if h != a]
    rng.shuffle(pairs)
    rows = []
    for i, (h, a) in enumerate(pairs):
        d = f"{year}-{8 + i // 28:02d}-{i % 28 + 1:02d}"
        rows.append(_row(d, h, a, int(rng.poisson(1.5)), int(rng.poisson(1.1))))
    return sorted(rows, key=lambda r: r["date"])


def _data():
    keys = ["s0", "s1", "s2", "s3"]
    return {k: _season(2020 + i, 30 + i) for i, k in enumerate(keys)}, keys


def test_run_checkpoint_outputs_coherent_probabilities_and_exactly_one_champion():
    by, keys = _data()
    recs = run_checkpoint(by, keys, 3, 0.5, B=2, n_sims=60, seed=1, train_seasons=3)
    for ev, count in (("title", 1), ("top4", 4), ("relegation", 3)):
        rows = [r for r in recs if r["event"] == ev]
        assert len(rows) == len(TEAMS)
        assert sum(r["y"] for r in rows) == count                       # realised outcome
        assert abs(sum(r["p"] for r in rows) - count) < 1e-6            # model probabilities are coherent
        assert abs(sum(r["p_null"] for r in rows) - count) < 1e-6       # so is the standings-only baseline


def test_preseason_checkpoint_has_no_standings_so_the_null_baseline_is_roughly_uniform():
    by, keys = _data()
    recs = run_checkpoint(by, keys, 3, 0.0, B=2, n_sims=400, seed=2, train_seasons=3)
    title = [r["p_null"] for r in recs if r["event"] == "title"]
    assert max(title) < 0.35 and min(title) > 0.0


def test_summarize_reports_skill_against_both_baselines_for_each_event():
    by, keys = _data()
    recs = [{**r, "league": "toy", "season": "s3", "frac": 0.5} for r in run_checkpoint(by, keys, 3, 0.5, B=2, n_sims=60, seed=1)]
    out = summarize(recs)
    for ev in EVENTS:
        s = out[ev]
        assert {"brier", "uniform_brier", "null_brier", "skill_vs_uniform", "skill_vs_null", "n"} <= set(s)
        assert s["n"] == len(TEAMS)
