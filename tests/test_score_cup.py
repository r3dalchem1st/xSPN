import json
import os

from score_cup import score_and_save

CONFIG_DATA = {
    "slug": "test_cup", "name": "Test Cup", "format": "league_phase_knockout",
    "openfootball_repo": "openfootball/example",
    "openfootball_files": [{"season": "2026-27", "path": "2026-27/cup.txt"}],
    "team_aliases": {},
}

LEAGUE_SCHEDULE = {
    "Strong FC|Weak FC": {"date": "2026-09-16", "status": "FINISHED",
                           "goals": {"Strong FC": 2, "Weak FC": 0}, "round": "League, Matchday 1"},
}
# The FINAL went to penalties: the true score (goals) is a 1-1 draw, but
# Strong FC won the shootout 4-3 -- score_cup.py must grade against the
# GOAL score (a draw), not the shootout tally.
KNOCKOUT_FIXTURES = [
    {"round": "Finals, Final", "date": "2027-05-30", "home": "Strong FC", "away": "Weak FC",
     "score": [1, 1], "pen_score": [4, 3]},
]

SNAPSHOT = {
    "Strong FC|Weak FC": {"home": "Strong FC", "away": "Weak FC", "date": "2026-09-16",
                           "ph": 0.9, "pd": 0.08, "pa": 0.02,
                           "predicted_winner": "H", "predicted_score": "2-0", "snapped_at": "2026-09-14"},
    "Finals, Final|Strong FC|Weak FC": {"home": "Strong FC", "away": "Weak FC", "date": "2027-05-30",
                                          "ph": 0.6, "pd": 0.25, "pa": 0.15,
                                          "predicted_winner": "H", "predicted_score": "2-1", "snapped_at": "2027-05-28"},
}


def _write(base_dir, slug, league_schedule, knockout_fixtures, snapshot):
    out_dir = os.path.join(base_dir, "competitions", slug)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "league_schedule.json"), "w") as f:
        json.dump(league_schedule, f)
    with open(os.path.join(out_dir, "knockout_fixtures.json"), "w") as f:
        json.dump(knockout_fixtures, f)
    with open(os.path.join(out_dir, "predictions_snapshot.json"), "w") as f:
        json.dump(snapshot, f)


def test_score_and_save_scores_league_and_knockout_matches(tmp_path):
    from competition_config import CompetitionConfig
    config = CompetitionConfig(CONFIG_DATA)
    _write(str(tmp_path), config.slug, LEAGUE_SCHEDULE, KNOCKOUT_FIXTURES, SNAPSHOT)

    out = score_and_save(config, str(tmp_path))
    assert out["summary"]["n_scored"] == 2
    by_date = {m["date"]: m for m in out["matches"]}
    assert by_date["2026-09-16"]["correct_winner"] is True  # 2-0 predicted H, actual H


def test_score_and_save_grades_a_shootout_final_by_goals_not_penalties(tmp_path):
    from competition_config import CompetitionConfig
    config = CompetitionConfig(CONFIG_DATA)
    _write(str(tmp_path), config.slug, LEAGUE_SCHEDULE, KNOCKOUT_FIXTURES, SNAPSHOT)

    out = score_and_save(config, str(tmp_path))
    by_date = {m["date"]: m for m in out["matches"]}
    final_result = by_date["2027-05-30"]
    # true score is 1-1 (a draw); predicted_winner was "H" -- so this must
    # be graded as an INCORRECT winner call, even though Strong FC actually
    # won the tie on penalties.
    assert final_result["correct_winner"] is False


def test_score_and_save_skips_fixtures_with_no_locked_snapshot(tmp_path):
    from competition_config import CompetitionConfig
    config = CompetitionConfig(CONFIG_DATA)
    _write(str(tmp_path), config.slug, LEAGUE_SCHEDULE, KNOCKOUT_FIXTURES, {})  # no snapshot at all

    out = score_and_save(config, str(tmp_path))
    assert out["summary"]["n_scored"] == 0
