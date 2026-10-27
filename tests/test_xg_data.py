import copy
import datetime as dt
import json

import numpy as np
import pytest

import xg_data
from multiseason_data import to_fit_rows
from rolling_backtest import run_season


def _us(date, home, away, hg, ag, hxg, axg, is_result=True):
    return {"isResult": is_result, "h": {"title": home}, "a": {"title": away}, "goals": {"h": str(hg), "a": str(ag)},
            "xG": {"h": str(hxg), "a": str(axg)}, "datetime": f"{date} 19:00:00"}


def _fd(date, home, away, hg, ag):
    return {"date": date, "home": home, "away": away, "hg": hg, "ag": ag, "market": None}


# Understat writes "Manchester United", football-data writes "Man United".
US = [{"date": "2024-08-16", "home": "Manchester United", "away": "Fulham", "hg": 1, "ag": 0, "hxg": 2.0, "axg": 0.4},
      {"date": "2024-08-17", "home": "Fulham", "away": "Manchester United", "hg": 2, "ag": 2, "hxg": 1.1, "axg": 1.9}]
FD = [_fd("2024-08-16", "Man United", "Fulham", 1, 0), _fd("2024-08-17", "Fulham", "Man United", 2, 2)]


def test_parse_understat_keeps_played_matches_and_reads_numbers():
    rows = xg_data.parse_understat([_us("2024-08-16", "A", "B", 1, 0, 1.5, 0.25), _us("2024-09-01", "A", "C", 0, 0, 0, 0, is_result=False)])
    assert rows == [{"date": "2024-08-16", "home": "A", "away": "B", "hg": 1, "ag": 0, "hxg": 1.5, "axg": 0.25}]


def test_the_name_map_is_learned_from_matches_that_are_unique_on_date_and_score():
    assert xg_data.learn_name_map({"s": FD}, {"s": US}) == {"Manchester United": "Man United", "Fulham": "Fulham"}


def test_matches_sharing_a_date_and_score_are_not_used_to_learn_names():
    us = US + [{"date": "2024-08-16", "home": "Arsenal", "away": "Chelsea", "hg": 1, "ag": 0, "hxg": 1.0, "axg": 1.0}]
    fd = FD + [_fd("2024-08-16", "Chelsea", "Arsenal", 1, 0)]       # same day, same score, opposite teams
    mapping = xg_data.learn_name_map({"s": fd}, {"s": us})
    assert "Arsenal" not in mapping and "Chelsea" not in mapping


def test_a_club_that_maps_to_two_different_names_raises():
    us = [{"date": f"2024-08-{d}", "home": "X", "away": "Y", "hg": 1, "ag": 0, "hxg": 1.0, "axg": 1.0} for d in (10, 11)]
    fd = [_fd("2024-08-10", "Foo", "Y", 1, 0), _fd("2024-08-11", "Bar", "Y", 1, 0)]
    with pytest.raises(ValueError, match="ambiguously"):
        xg_data.learn_name_map({"s": fd}, {"s": us})


def test_attach_xg_joins_on_the_home_away_pair_and_leaves_unsourced_seasons_as_none():
    by = {"old": [_fd("2013-08-17", "Man United", "Fulham", 0, 0)], "s": copy.deepcopy(FD)}
    xg_data.attach_xg(by, {"s": US})
    assert [(r["hxg"], r["axg"]) for r in by["s"]] == [(2.0, 0.4), (1.1, 1.9)]
    assert by["old"][0]["hxg"] is None and by["old"][0]["axg"] is None


def test_attach_xg_tolerates_a_date_difference_because_it_joins_on_the_pair():
    by = {"s": copy.deepcopy(FD)}
    shifted = [{**u, "date": "2024-08-18"} if u["home"] == "Fulham" else u for u in US]   # UTC vs local kickoff
    xg_data.attach_xg(by, {"s": shifted})
    assert by["s"][1]["hxg"] == 1.1


def test_attach_xg_raises_rather_than_leaving_a_match_without_xg():
    by = {"s": copy.deepcopy(FD) + [_fd("2024-08-24", "Man United", "Arsenal", 3, 1)]}
    with pytest.raises(ValueError, match="no Understat match"):
        xg_data.attach_xg(by, {"s": US})


def test_attach_xg_raises_when_the_two_sources_disagree_on_too_many_scores():
    by = {"s": [_fd("2024-08-16", "Man United", "Fulham", 0, 3), _fd("2024-08-17", "Fulham", "Man United", 2, 2)]}
    with pytest.raises(ValueError, match="different score"):
        xg_data.attach_xg(by, {"s": US})


def test_load_understat_season_caches_to_disk_and_does_not_refetch(tmp_path):
    calls = []
    fetch = lambda code, year: calls.append((code, year)) or [_us("2024-08-16", "A", "B", 1, 0, 1.0, 1.0)]
    first = xg_data.load_understat_season("EPL", "2425", tmp_path, fetch)
    again = xg_data.load_understat_season("EPL", "2425", tmp_path, fetch)
    assert calls == [("EPL", 2024)] and first == again
    assert json.loads((tmp_path / "understat_EPL_2425.json").read_text()) == first


# --- blending xG into the training targets ---

ROWS = [{**_fd("2024-08-16", "A", "B", 2, 0), "hxg": 1.0, "axg": 0.5}, _fd("2023-08-16", "A", "B", 3, 1)]


def test_to_fit_rows_with_no_weight_is_plain_integer_goals():
    assert [(r[3], r[4]) for r in to_fit_rows(ROWS, "x")] == [(2, 0), (3, 1)]


def test_to_fit_rows_blends_goals_toward_xg_and_keeps_goals_where_xg_is_missing():
    rows = to_fit_rows(ROWS, "x", xg_weight=0.5)
    assert (rows[0][3], rows[0][4]) == (1.5, 0.25)
    assert (rows[1][3], rows[1][4]) == (3, 1)
    assert [(r[3], r[4]) for r in to_fit_rows(ROWS, "x", xg_weight=1.0)][0] == (1.0, 0.5)


# --- inside the rolling backtest ---

TEAMS = ["A", "B", "C", "D", "E", "F"]


def _season(year, seed):
    rng = np.random.default_rng(seed)
    pairs = [(h, a) for h in TEAMS for a in TEAMS if h != a]
    rng.shuffle(pairs)
    rows = []
    for i, (h, a) in enumerate(pairs):
        d = (dt.date(year, 8, 1) + dt.timedelta(days=7 * (i // 3))).isoformat()
        hg, ag = int(rng.poisson(1.5)), int(rng.poisson(1.2))
        rows.append({"date": d, "home": h, "away": a, "hg": hg, "ag": ag, "market": None,
                     "hxg": hg + float(rng.normal(0, 0.4)), "axg": ag + float(rng.normal(0, 0.4))})
    return sorted(rows, key=lambda r: r["date"])


def _data():
    keys = ["s0", "s1", "s2", "s3"]
    return {k: _season(2020 + i, 10 + i) for i, k in enumerate(keys)}, keys


def _preds(by, keys, **cfg):
    return [r["p"] for r in run_season(by, keys, 3, {"train_seasons": 3, "refit_days": 30, **cfg})]


def test_xg_weight_zero_changes_nothing_and_a_positive_weight_reaches_the_fit():
    by, keys = _data()
    assert _preds(by, keys) == _preds(by, keys, xg_weight=0.0)
    assert _preds(by, keys) != _preds(by, keys, xg_weight=0.5)


def test_xg_of_the_block_being_predicted_never_leaks_into_its_own_predictions():
    by, keys = _data()
    first = by["s3"][0]["date"]
    block = lambda r: (dt.date.fromisoformat(r["date"]) - dt.date.fromisoformat(first)).days // 30
    altered = copy.deepcopy(by)
    target = next(r for r in altered["s3"] if block(r) == 1)
    target["hxg"], target["axg"] = 9.0, 0.0
    base, changed = _preds(by, keys, xg_weight=1.0), _preds(altered, keys, xg_weight=1.0)
    cut = sum(block(r) <= 1 for r in by["s3"])
    assert base[:cut] == changed[:cut]          # blocks 0 and 1 are fit before that match is revealed
    assert base[cut:] != changed[cut:]          # later blocks do learn from it, as they do from goals


def test_elo_and_the_evaluation_outcome_keep_using_real_goals_not_xg():
    by, keys = _data()
    skewed = copy.deepcopy(by)
    for r in skewed["s3"]:
        r["hxg"], r["axg"] = 0.0, 0.0           # absurd xG: outcomes are still scored on the real score
    recs = run_season(skewed, keys, 3, {"train_seasons": 3, "refit_days": 30, "xg_weight": 0.5})
    assert [r["o"] for r in recs] == [0 if r["hg"] > r["ag"] else (2 if r["hg"] < r["ag"] else 1) for r in skewed["s3"]]


# --- live: xG for the production training rows ---

LIVE = [["2024-08-16", "Manchester United FC", "Fulham FC", 1, 0, "L", False],
        ["2024-08-17", "Fulham FC", "Manchester United FC", 2, 2, "L", False]]
RAW = [_us("2024-08-16", "Manchester United", "Fulham", 1, 0, 2.0, 0.4),
       _us("2024-08-17", "Fulham", "Manchester United", 2, 2, 1.1, 1.9)]


def _blocked(code, year):
    raise OSError("blocked")


def test_season_of_follows_the_august_to_july_calendar():
    dates = ("2024-08-01", "2025-05-25", "2025-07-31", "2025-08-01", "2026-10-03")
    assert [xg_data.season_of(d) for d in dates] == ["2425", "2425", "2425", "2526", "2627"]


def test_live_xg_is_parallel_to_the_rows_and_joined_through_the_learned_name_map(capsys):
    assert xg_data.live_xg("EPL", LIVE, lambda code, year: RAW) == [(2.0, 0.4), (1.1, 1.9)]
    assert "::warning::" not in capsys.readouterr().out


def test_live_xg_asks_understat_for_each_season_the_rows_fall_in():
    asked = []
    rows = LIVE + [["2025-09-13", "Fulham FC", "Arsenal FC", 0, 0, "L", False]]
    xg_data.live_xg("EPL", rows, lambda code, year: asked.append((code, year)) or RAW)
    assert sorted(asked) == [("EPL", 2024), ("EPL", 2025)]


def test_live_xg_leaves_a_match_understat_has_not_published_as_none_and_says_so(capsys):
    rows = LIVE + [["2024-08-24", "Manchester United FC", "Arsenal FC", 3, 1, "L", False]]
    assert xg_data.live_xg("EPL", rows, lambda code, year: RAW) == [(2.0, 0.4), (1.1, 1.9), None]
    assert "only 2/3 matches joined" in capsys.readouterr().out


def test_live_xg_keeps_the_seasons_it_has_when_another_is_unreachable(capsys):
    rows = LIVE + [["2023-08-12", "Manchester United FC", "Fulham FC", 0, 0, "L", False]]
    fetch = lambda code, year: RAW if year == 2024 else _blocked(code, year)
    assert xg_data.live_xg("EPL", rows, fetch) == [(2.0, 0.4), (1.1, 1.9), None]
    out = capsys.readouterr().out
    assert "2324 unavailable (OSError: blocked)" in out and out.count("::warning::") == 1


def test_live_xg_never_raises_when_understat_is_unreachable(capsys):
    assert xg_data.live_xg("EPL", LIVE, _blocked) == [None, None]
    assert "::warning::" in capsys.readouterr().out


def test_live_xg_treats_a_response_in_the_wrong_shape_as_unreachable(capsys):
    assert xg_data.live_xg("EPL", LIVE, lambda code, year: [{"isResult": True}]) == [None, None]
    assert "unavailable (KeyError" in capsys.readouterr().out


def test_live_xg_gives_up_on_an_ambiguous_name_map_instead_of_raising(capsys):
    rows = [["2024-08-10", "Foo FC", "Y FC", 1, 0, "L", False], ["2024-08-11", "Bar FC", "Y FC", 1, 0, "L", False]]
    raw = [_us("2024-08-10", "X", "Y", 1, 0, 1.0, 1.0), _us("2024-08-11", "X", "Y", 1, 0, 1.0, 1.0)]
    assert xg_data.live_xg("EPL", rows, lambda code, year: raw) == [None, None]
    assert "ambiguously" in capsys.readouterr().out


def test_live_xg_drops_a_season_whose_scores_disagree_with_understat(capsys):
    rows = [["2024-08-16", "Manchester United FC", "Fulham FC", 0, 3, "L", False], LIVE[1]]
    assert xg_data.live_xg("EPL", rows, lambda code, year: RAW) == [None, None]
    assert "different score" in capsys.readouterr().out


def test_blend_xg_is_the_same_formula_the_backtest_validated():
    from fit_league import blend_xg
    xg = [(r["hxg"], r["axg"]) if "hxg" in r else None for r in ROWS]
    assert blend_xg(to_fit_rows(ROWS, "x"), xg, 0.75) == to_fit_rows(ROWS, "x", xg_weight=0.75)
