import json
import os

from snapshot_cup import iter_fixtures, snapshot_and_save

LEAGUE_SCHEDULE = {
    "Strong FC|Weak FC": {"date": "2026-09-16", "status": "SCHEDULED",
                           "goals": {"Strong FC": None, "Weak FC": None}, "round": "League, Matchday 1"},
}
KNOCKOUT_FIXTURES = [
    {"round": "Finals, Final", "date": "2027-05-30", "home": "Strong FC", "away": "Weak FC",
     "score": None, "pen_score": None},
]

DC_SAMPLE = {
    "attack": {"Strong FC": 0.8, "Weak FC": -0.6},
    "defense": {"Strong FC": -0.3, "Weak FC": 0.4},
    "home_adv": 0.2,
    "rho": -0.1,
    "teams": ["Strong FC", "Weak FC"],
}

CONFIG_DATA = {
    "slug": "test_cup", "name": "Test Cup", "format": "league_phase_knockout",
    "openfootball_repo": "openfootball/example",
    "openfootball_files": [{"season": "2026-27", "path": "2026-27/cup.txt"}],
    "team_aliases": {},
}


def test_iter_fixtures_covers_both_league_and_knockout_artifacts():
    entries = list(iter_fixtures(LEAGUE_SCHEDULE, KNOCKOUT_FIXTURES))
    keys = [e[0] for e in entries]
    assert "Strong FC|Weak FC" in keys
    assert "Finals, Final|Strong FC|Weak FC" in keys


def test_iter_fixtures_derives_knockout_status_from_score():
    entries = {e[0]: e for e in iter_fixtures(LEAGUE_SCHEDULE, KNOCKOUT_FIXTURES)}
    assert entries["Finals, Final|Strong FC|Weak FC"][4] == "SCHEDULED"


def test_snapshot_and_save_locks_both_league_and_knockout_fixtures_when_due(tmp_path):
    from competition_config import CompetitionConfig
    config = CompetitionConfig(CONFIG_DATA)
    out_dir = os.path.join(str(tmp_path), "competitions", config.slug)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "league_schedule.json"), "w") as f:
        json.dump(LEAGUE_SCHEDULE, f)
    with open(os.path.join(out_dir, "knockout_fixtures.json"), "w") as f:
        json.dump(KNOCKOUT_FIXTURES, f)

    added = snapshot_and_save(config, str(tmp_path), [DC_SAMPLE], today="2026-09-14")
    assert added == 1  # only the league fixture is within its lock window (2026-09-16)

    with open(os.path.join(out_dir, "predictions_snapshot.json")) as f:
        snapshot = json.load(f)
    assert "Strong FC|Weak FC" in snapshot
    assert "Finals, Final|Strong FC|Weak FC" not in snapshot  # 2027-05-30 is far outside the window

    added2 = snapshot_and_save(config, str(tmp_path), [DC_SAMPLE], today="2027-05-28")
    assert added2 == 1
    with open(os.path.join(out_dir, "predictions_snapshot.json")) as f:
        snapshot = json.load(f)
    assert "Finals, Final|Strong FC|Weak FC" in snapshot
    assert snapshot["Finals, Final|Strong FC|Weak FC"]["home"] == "Strong FC"
