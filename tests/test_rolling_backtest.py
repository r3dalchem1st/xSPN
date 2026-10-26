import copy
import datetime as dt

import numpy as np

from rolling_backtest import (CONFIRM_SEASONS, DEFAULT_CONFIG, DEV_SEASONS, judge, metrics, run_config,
                              run_season, screen)

TEAMS = ["A", "B", "C", "D", "E", "F"]
STRENGTH = dict(zip(TEAMS, [0.5, 0.3, 0.1, -0.1, -0.3, -0.5]))


def _season_rows(year, teams, seed):
    """Double round robin, one matchday per week, Poisson scores from fixed strengths."""
    rng = np.random.default_rng(seed)
    start = dt.date(year, 8, 1)
    rows, day = [], 0
    pairs = [(h, a) for h in teams for a in teams if h != a]
    rng.shuffle(pairs)
    for i, (h, a) in enumerate(pairs):
        d = start + dt.timedelta(days=7 * (i // (len(teams) // 2)))
        lam, mu = np.exp(0.15 + STRENGTH.get(h, 0) - 0.5 * STRENGTH.get(a, 0)), np.exp(STRENGTH.get(a, 0) - 0.5 * STRENGTH.get(h, 0))
        rows.append({"date": d.isoformat(), "home": h, "away": a, "hg": int(rng.poisson(lam)),
                     "ag": int(rng.poisson(mu)), "market": (0.45, 0.27, 0.28)})
    return sorted(rows, key=lambda r: r["date"])


def _data(extra_team_in_test=False):
    keys = ["s0", "s1", "s2", "s3"]
    by = {k: _season_rows(2020 + i, TEAMS, seed=10 + i) for i, k in enumerate(keys)}
    if extra_team_in_test:
        by["s3"] = _season_rows(2023, TEAMS + ["G"], seed=13)
    return by, keys


CFG = {"train_seasons": 3, "refit_days": 30}


def test_run_season_returns_one_normalised_record_per_test_match():
    by, keys = _data()
    recs = run_season(by, keys, 3, CFG)
    assert len(recs) == len(by["s3"])
    assert all(abs(sum(r["p"]) - 1) < 1e-6 for r in recs)
    assert {r["season"] for r in recs} == {"s3"}
    assert all(r["o"] in (0, 1, 2) for r in recs)


def _block(date, first, days=30):
    return (dt.date.fromisoformat(date) - dt.date.fromisoformat(first)).days // days


def _alter_a_match_in_block(by, block_idx):
    first = by["s3"][0]["date"]
    altered = copy.deepcopy(by)
    target = next(r for r in altered["s3"] if _block(r["date"], first) == block_idx)
    target["hg"], target["ag"] = 9, 0
    return altered, first


def test_predictions_never_use_results_from_the_same_or_a_later_block():
    # A result in refit block 1 may only influence blocks 2+: blocks 0 and 1
    # must be bit-for-bit unchanged (no look-ahead, not even within a block).
    by, keys = _data()
    base = run_season(by, keys, 3, CFG)
    altered, first = _alter_a_match_in_block(by, 1)
    after = run_season(altered, keys, 3, CFG)
    early = [(a, b) for a, b in zip(base, after) if _block(a["date"], first) <= 1]
    assert early and all(a["p"] == b["p"] for a, b in early)


def test_later_blocks_do_learn_from_earlier_results_in_the_same_season():
    by, keys = _data()
    base = run_season(by, keys, 3, CFG)
    altered, first = _alter_a_match_in_block(by, 1)
    after = run_season(altered, keys, 3, CFG)
    late = [(a, b) for a, b in zip(base, after) if _block(a["date"], first) >= 2]
    assert late and any(a["p"] != b["p"] for a, b in late)


def test_the_training_window_excludes_seasons_older_than_train_seasons():
    by, keys = _data()
    narrow = {"train_seasons": 1, "refit_days": 30}
    base = run_season(by, keys, 3, narrow)
    altered = copy.deepcopy(by)
    for r in altered["s0"]:           # two seasons before the cut-off: must not matter
        r["hg"], r["ag"] = 9, 0
    assert [r["p"] for r in run_season(altered, keys, 3, narrow)] == [r["p"] for r in base]


def test_promoted_prior_lowers_a_newly_promoted_teams_predicted_strength():
    by, keys = _data(extra_team_in_test=True)
    plain = run_season(by, keys, 3, CFG)
    prior = run_season(by, keys, 3, {**CFG, "promoted_prior": (-0.6, 0.6)})
    g_home = [(a, b) for a, b in zip(plain, prior) if a["home"] == "G"]
    first = min(g_home, key=lambda ab: ab[0]["date"])
    assert first[1]["p"][0] < first[0]["p"][0]   # G (promoted) is less likely to win once the prior says it's weak


def test_run_config_tags_every_record_with_its_league_and_covers_requested_seasons():
    by, keys = _data()
    recs = run_config(CFG, {"toy": by}, test_seasons=["s3"], season_keys=keys)
    assert {r["league"] for r in recs} == {"toy"} and {r["season"] for r in recs} == {"s3"}


def test_metrics_reports_model_and_market_scores():
    by, keys = _data()
    m = metrics(run_config(CFG, {"toy": by}, test_seasons=["s3"], season_keys=keys))
    assert m["n"] == len(by["s3"]) and 0 < m["brier"] < 1 and 0 < m["market_brier"] < 1
    assert 0 <= m["accuracy"] <= 1


def _recs(league, season, improvement, n=40, seed=0):
    rng = np.random.default_rng(seed)
    base = []
    for i in range(n):
        o = int(rng.integers(0, 3))
        base.append({"league": league, "season": season, "date": f"2024-01-{i % 28 + 1:02d}", "home": f"H{i}",
                     "away": f"A{i}", "o": o, "p": (0.4, 0.3, 0.3), "q": None})
    return base


def _shifted(base, shift):
    out = []
    for r in base:
        p = list(r["p"])
        # move `shift` of probability mass onto the true outcome (a strictly better forecast when shift>0)
        p[r["o"]] += shift
        for k in range(3):
            if k != r["o"]:
                p[k] -= shift / 2
        out.append({**r, "p": tuple(p)})
    return out


def _all_confirm(shift_by_league):
    base, cand = [], []
    for lg, shift in shift_by_league.items():
        for s in CONFIRM_SEASONS:
            b = _recs(lg, s, 0, seed=sum(map(ord, lg + s)))
            base += b
            cand += _shifted(b, shift)
    return cand, base


def test_judge_passes_a_consistent_improvement_everywhere():
    cand, base = _all_confirm({"x": 0.05, "y": 0.05, "z": 0.05})
    j = judge(cand, base)
    assert j["pass"] and j["brier"]["lo"] > 0


def test_judge_fails_an_identical_model():
    _, base = _all_confirm({"x": 0, "y": 0, "z": 0})
    j = judge(base, base)
    assert not j["pass"]


def test_judge_fails_when_only_one_league_improves_even_if_the_pooled_mean_is_positive():
    cand, base = _all_confirm({"x": 0.20, "y": -0.01, "z": -0.01})
    j = judge(cand, base)
    assert not j["pass"] and any("league" in reason for reason in j["reasons"])


def test_the_pass_rule_requires_logloss_not_to_get_worse():
    from rolling_backtest import _passes
    brier = {"lo": 0.001, "mean": 0.003}
    leagues, seasons = {"a": 0.003, "b": 0.003, "c": 0.003}, {"s1": 0.003, "s2": 0.003, "s3": 0.003}
    assert _passes(brier, 0.001, leagues, seasons)
    assert not _passes(brier, -0.001, leagues, seasons)


def test_the_pass_rule_requires_a_positive_lower_bound_and_two_thirds_consistency():
    from rolling_backtest import _passes
    leagues, seasons = {"a": 0.003, "b": 0.003, "c": 0.003}, {"s1": 0.003, "s2": 0.003, "s3": 0.003}
    assert not _passes({"lo": -0.0001, "mean": 0.003}, 0.001, leagues, seasons)
    assert not _passes({"lo": 0.001, "mean": 0.003}, 0.001, {"a": 0.003, "b": -0.001, "c": -0.001}, seasons)
    assert not _passes({"lo": 0.001, "mean": 0.003}, 0.001, leagues, {"s1": 0.003, "s2": -0.001, "s3": -0.001})
    assert _passes({"lo": 0.001, "mean": 0.003}, 0.001, {"a": 0.003, "b": 0.003, "c": -0.001}, seasons)


def test_judge_only_looks_at_the_confirmation_seasons_and_screen_only_at_development_seasons():
    cand_c, base_c = _all_confirm({"x": 0.05})
    dev_base = _recs("x", DEV_SEASONS[0], 0)
    dev_cand = _shifted(dev_base, 0.05)
    assert judge(cand_c + dev_cand, base_c + dev_base)["brier"]["n"] == len(base_c)
    assert screen(cand_c + dev_cand, base_c + dev_base)["brier"]["n"] == len(dev_base)
