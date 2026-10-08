import json
import os

from competition_config import CompetitionConfig
from score_league import score_and_save, score_match

PERFECT_HOME_CALL = {"home": "Strong FC", "away": "Weak FC", "date": "2026-08-15",
                       "ph": 0.9, "pd": 0.08, "pa": 0.02,
                       "predicted_winner": "H", "predicted_score": "2-0",
                       "snapped_at": "2026-08-13"}


def test_score_match_correct_winner_and_low_brier_on_a_good_call():
    result = score_match(PERFECT_HOME_CALL, actual_hg=2, actual_ag=0)
    assert result["correct_winner"] is True
    assert result["brier"] < 0.1  # (0.9-1)^2 + (0.08-0)^2 + (0.02-0)^2 = 0.0168


def test_score_match_wrong_winner_gives_high_brier():
    result = score_match(PERFECT_HOME_CALL, actual_hg=0, actual_ag=1)  # away win, not predicted
    assert result["correct_winner"] is False
    assert result["brier"] > 1.0  # (0.9-0)^2 + (0.08-0)^2 + (0.02-1)^2 = 1.7672


def test_score_match_log_loss_is_finite_even_on_a_confident_miss():
    result = score_match(PERFECT_HOME_CALL, actual_hg=0, actual_ag=1)
    import math
    assert math.isfinite(result["log_loss"])


def test_score_match_total_goal_error_is_exact_score_distance():
    # predicted_score "2-0" vs actual 2-0 -> exact match, zero error
    result = score_match(PERFECT_HOME_CALL, actual_hg=2, actual_ag=0)
    assert result["total_goal_error"] == 0


def test_score_match_total_goal_error_sums_both_legs_of_the_miss():
    # predicted_score "2-0" vs actual 4-1 -> |2-4| + |0-1| = 3
    result = score_match(PERFECT_HOME_CALL, actual_hg=4, actual_ag=1)
    assert result["total_goal_error"] == 3


# --- market comparison (display/analysis only; see snapshot_league.py) ---

HOME_CALL_MARKET_AGREES = dict(PERFECT_HOME_CALL, market={"ph": 0.7, "pd": 0.2, "pa": 0.1})
HOME_CALL_MARKET_PICKS_AWAY = dict(PERFECT_HOME_CALL, market={"ph": 0.2, "pd": 0.2, "pa": 0.6})


def test_score_match_has_no_market_fields_without_a_recorded_market():
    result = score_match(PERFECT_HOME_CALL, actual_hg=2, actual_ag=0)
    assert not any(k.startswith("market") for k in result) and "disagree" not in result


def test_score_match_scores_the_market_on_the_same_result():
    result = score_match(HOME_CALL_MARKET_AGREES, actual_hg=2, actual_ag=0)
    assert result["market_winner"] == "H" and result["market_correct_winner"] is True
    assert abs(result["market_brier"] - ((0.7 - 1) ** 2 + 0.2 ** 2 + 0.1 ** 2)) < 1e-9
    assert result["disagree"] is False


def test_score_match_flags_a_disagreement_and_who_was_right():
    result = score_match(HOME_CALL_MARKET_PICKS_AWAY, actual_hg=2, actual_ag=0)
    assert result["disagree"] is True
    assert result["correct_winner"] is True and result["market_correct_winner"] is False


LEAGUE_CONFIG = CompetitionConfig({
    "slug": "test_league", "name": "Test League", "format": "round_robin",
    "openfootball_repo": "x/y", "openfootball_files": [{"season": "2026-27", "path": "p"}],
    "team_aliases": {},
})


def _finished(home, away, hg, ag):
    return {"date": "2026-08-16", "status": "FINISHED", "goals": {home: hg, away: ag}, "round": "Matchday 1"}


def _snap(home, away, winner, market=None):
    e = {"home": home, "away": away, "date": "2026-08-16", "ph": 0.6 if winner == "H" else 0.2,
         "pd": 0.2, "pa": 0.6 if winner == "A" else 0.2, "predicted_winner": winner,
         "predicted_score": "1-0" if winner == "H" else "0-1", "snapped_at": "2026-08-14"}
    if market:
        e["market"] = market
    return e


def _score(tmp_path, schedule, snapshot):
    out_dir = tmp_path / "competitions" / "test_league"
    os.makedirs(out_dir, exist_ok=True)
    (out_dir / "schedule.json").write_text(json.dumps(schedule))
    (out_dir / "predictions_snapshot.json").write_text(json.dumps(snapshot))
    return score_and_save(LEAGUE_CONFIG, str(tmp_path))


def test_score_and_save_summarises_the_record_against_the_market(tmp_path):
    schedule = {"A|B": _finished("A", "B", 1, 0),   # we H (right), market A (wrong)  -> disagree, we were right
                "C|D": _finished("C", "D", 0, 1),   # we H (wrong), market A (right) -> disagree, market right
                "E|F": _finished("E", "F", 2, 2),   # we H (wrong), market H (wrong) -> agree
                "G|H": _finished("G", "H", 1, 0)}   # no market recorded for this one
    toward_away = {"ph": 0.2, "pd": 0.2, "pa": 0.6}
    toward_home = {"ph": 0.6, "pd": 0.2, "pa": 0.2}
    snapshot = {"A|B": _snap("A", "B", "H", toward_away), "C|D": _snap("C", "D", "H", toward_away),
                "E|F": _snap("E", "F", "H", toward_home), "G|H": _snap("G", "H", "H")}
    vs = _score(tmp_path, schedule, snapshot)["summary"]["vs_market"]
    assert vs["n"] == 3  # the match with no recorded market is excluded, not guessed
    assert (vs["disagree_n"], vs["we_right"], vs["market_right"]) == (2, 1, 1)
    assert abs(vs["accuracy"] - 1 / 3) < 1e-9 and abs(vs["market_accuracy"] - 1 / 3) < 1e-9


def test_score_and_save_omits_vs_market_when_nothing_was_recorded(tmp_path):
    out = _score(tmp_path, {"A|B": _finished("A", "B", 1, 0)}, {"A|B": _snap("A", "B", "H")})
    assert "vs_market" not in out["summary"]
