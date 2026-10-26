import copy
import datetime as dt

import numpy as np

import rolling_backtest as rb
from backtest_league import predict_match_probs
from rolling_backtest import DEFAULT_CONFIG, _blend_fits, _fatigue, _promoted_priors, _team_dates, run_season

TEAMS = ["A", "B", "C", "D", "E", "F"]
CFG = {"train_seasons": 3, "refit_days": 30}


def _season(year, teams, seed):
    rng = np.random.default_rng(seed)
    pairs = [(h, a) for h in teams for a in teams if h != a]
    rng.shuffle(pairs)
    rows = []
    for i, (h, a) in enumerate(pairs):
        d = (dt.date(year, 8, 1) + dt.timedelta(days=3 * (i // (len(teams) // 2)))).isoformat()
        rows.append({"date": d, "home": h, "away": a, "hg": int(rng.poisson(1.5)), "ag": int(rng.poisson(1.2)), "market": None})
    return sorted(rows, key=lambda r: r["date"])


def _data(promoted="G"):
    keys = ["s0", "s1", "s2", "s3"]
    by = {k: _season(2020 + i, TEAMS, 10 + i) for i, k in enumerate(keys)}
    by["s3"] = _season(2023, TEAMS + [promoted], 13)
    by["tier2"] = {"s2": _season(2022, ["G", "H", "I", "J"], 30)}
    return by, keys


def _preds(by, keys, **cfg):
    return [r["p"] for r in run_season(by, keys, 3, {**CFG, **cfg})]


# --- fatigue: short rest and a crowded list ---

def _ords(*iso):
    return sorted(dt.date.fromisoformat(d).toordinal() for d in iso)


def test_a_full_week_of_rest_or_a_first_match_costs_nothing():
    cfg = {**DEFAULT_CONFIG, "rest_weight": 0.03}
    assert _fatigue("T", "2024-01-08", {"T": _ords("2024-01-01")}, cfg) == 0.0
    assert _fatigue("T", "2024-01-08", {"T": _ords("2023-12-20")}, cfg) == 0.0
    assert _fatigue("T", "2024-01-08", {}, cfg) == 0.0


def test_short_rest_lowers_strength_in_proportion_to_the_days_lost():
    cfg = {**DEFAULT_CONFIG, "rest_weight": 0.03}
    four = _fatigue("T", "2024-01-08", {"T": _ords("2024-01-04")}, cfg)     # 4 days: 3 under the cap -> one unit
    two = _fatigue("T", "2024-01-08", {"T": _ords("2024-01-06")}, cfg)
    assert four == -0.03 * 3 / 3 and two < four < 0


def test_congestion_counts_only_league_matches_beyond_two_in_the_last_fortnight():
    cfg = {**DEFAULT_CONFIG, "congestion_weight": 0.02}
    weekly = {"T": _ords("2024-01-01", "2024-01-08")}              # two in the window: normal
    crowded = {"T": _ords("2023-12-30", "2024-01-01", "2024-01-05")}   # three in the window: one beyond normal
    stale = {"T": _ords("2023-12-26", "2024-01-01", "2024-01-05")}     # 12-26 is 17 days back: outside the window
    assert _fatigue("T", "2024-01-12", weekly, cfg) == 0.0
    assert _fatigue("T", "2024-01-12", crowded, cfg) == -0.02
    assert _fatigue("T", "2024-01-12", stale, cfg) == 0.0


def test_the_schedule_features_use_dates_and_teams_never_results():
    by, keys = _data()
    changed = copy.deepcopy(by)
    for r in changed["s3"]:
        r["hg"], r["ag"] = 9, 0
    assert _team_dates(by, keys, 3) == _team_dates(changed, keys, 3)


def test_a_tired_home_side_gets_a_lower_home_win_probability():
    dc = {"attack": {"A": 0.2, "B": 0.0}, "defense": {"A": 0.0, "B": 0.0}, "home_adv": 0.2, "rho": 0.0}
    rested = predict_match_probs("A", "B", "2024-01-08", False, dc)
    tired = predict_match_probs("A", "B", "2024-01-08", False, dc, shifts=(-0.1, 0.0))
    assert tired[0] < rested[0] and tired[2] > rested[2]
    assert predict_match_probs("A", "B", "2024-01-08", False, dc, shifts=None) == rested


def test_fatigue_weights_of_zero_change_nothing_and_positive_weights_reach_the_predictions():
    by, keys = _data()
    base = _preds(by, keys)
    assert base == _preds(by, keys, rest_weight=0.0, congestion_weight=0.0)
    assert base != _preds(by, keys, rest_weight=0.04)
    assert base != _preds(by, keys, congestion_weight=0.04)


# --- promoted clubs rated from the second division ---

def test_the_tier2_prior_is_gamma_times_the_clubs_second_division_rating_minus_c():
    by, keys = _data()
    cfg = {**DEFAULT_CONFIG, "tier2_prior": {"gamma": 0.5, "c": 0.1}}
    pri = _promoted_priors(cfg, {"G"}, by, keys, 3)
    cfg_full = {**DEFAULT_CONFIG, "tier2_prior": {"gamma": 1.0, "c": 0.0}}
    full = _promoted_priors(cfg_full, {"G"}, by, keys, 3)
    assert abs(pri["G"][0] - (0.5 * full["G"][0] - 0.1)) < 1e-9
    assert abs(pri["G"][1] - (0.5 * full["G"][1] + 0.1)) < 1e-9


def test_without_a_prior_setting_no_club_gets_one_and_a_constant_offset_still_works():
    by, keys = _data()
    assert _promoted_priors(DEFAULT_CONFIG, {"G"}, by, keys, 3) == {}
    assert _promoted_priors({**DEFAULT_CONFIG, "promoted_prior": (-0.2, 0.2)}, {"G"}, by, keys, 3) == {"G": (-0.2, 0.2)}


def test_a_club_missing_from_the_second_division_falls_back_to_the_neutral_prior_minus_c():
    by, keys = _data()
    cfg = {**DEFAULT_CONFIG, "tier2_prior": {"gamma": 0.5, "c": 0.1}}
    assert _promoted_priors(cfg, {"Z"}, by, keys, 3)["Z"] == (-0.1, 0.1)


def test_the_tier2_prior_uses_only_the_previous_second_division_season_not_the_current_one():
    by, keys = _data()
    by["tier2"]["s3"] = _season(2023, ["G", "H", "I", "J"], 99)
    base = _preds(by, keys, tier2_prior={"gamma": 0.75, "c": 0.0})
    later = copy.deepcopy(by)
    later["tier2"]["s3"] = _season(2023, ["G", "H", "I", "J"], 5)       # the test season's own second division
    assert base == _preds(later, keys, tier2_prior={"gamma": 0.75, "c": 0.0})
    earlier = copy.deepcopy(by)
    earlier["tier2"]["s2"] = _season(2022, ["G", "H", "I", "J"], 77)    # the season it IS rated from
    assert base != _preds(earlier, keys, tier2_prior={"gamma": 0.75, "c": 0.0})


def test_run_season_without_tier2_data_still_works_when_the_prior_is_off():
    by, keys = _data()
    by.pop("tier2")
    assert len(run_season(by, keys, 3, CFG)) == len(by["s3"])


def test_load_all_adds_the_second_division_only_when_asked(monkeypatch):
    monkeypatch.setattr(rb, "load_league", lambda code, seasons: {"1314": [code]})
    assert "tier2" not in rb.load_all(["premier_league"])["premier_league"]
    assert rb.load_all(["premier_league"], tier2=True)["premier_league"]["tier2"] == {"1314": ["E1"]}


# --- fast/slow rating blend ---

SLOW = {"attack": {"A": 0.4, "B": 0.0}, "defense": {"A": 0.0, "B": 0.2}, "home_adv": 0.3, "rho": -0.1, "converged": True, "teams": ["A", "B"]}
FAST = {"attack": {"A": 0.0, "B": 0.2}, "defense": {"A": 0.2, "B": 0.0}, "home_adv": 0.1, "rho": 0.0, "converged": False, "teams": ["A", "B"]}


def test_blend_fits_interpolates_every_rating_and_requires_both_fits_to_have_converged():
    assert _blend_fits(SLOW, FAST, 0.0)["attack"] == SLOW["attack"]
    assert _blend_fits(SLOW, FAST, 1.0)["defense"] == FAST["defense"]
    half = _blend_fits(SLOW, FAST, 0.5)
    assert half["attack"] == {"A": 0.2, "B": 0.1} and abs(half["home_adv"] - 0.2) < 1e-12
    assert half["converged"] is False and _blend_fits(SLOW, {**FAST, "converged": True}, 0.5)["converged"] is True


def test_a_blend_weight_of_zero_changes_nothing_and_two_identical_memories_blend_to_the_same_model():
    by, keys = _data()
    base = _preds(by, keys)
    assert base == _preds(by, keys, blend_weight=0.0, blend_half_life=180)
    same = _preds(by, keys, blend_weight=0.5, blend_half_life=DEFAULT_CONFIG["half_life_days"])
    assert np.allclose(np.array(base), np.array(same), atol=1e-9)
    assert not np.allclose(np.array(base), np.array(_preds(by, keys, blend_weight=0.5, blend_half_life=90)), atol=1e-6)
