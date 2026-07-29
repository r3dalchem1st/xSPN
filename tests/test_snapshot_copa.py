import json
import os

from competition_config import CompetitionConfig
from snapshot_copa import iter_fixtures, snapshot_and_save

CONFIG_DATA = {
    "slug": "copa_del_rey", "name": "Copa del Rey", "format": "knockout_only",
    "openfootball_repo": "openfootball/espana",
    "openfootball_files": [{"season": "2024-25", "path": "2024-25/cup.txt"}],
    "team_aliases": {},
}


def test_iter_fixtures_yields_every_fixture_with_a_composite_key():
    fixtures = [
        {"round": "Round 1", "date": "2024-10-29", "home": "A", "away": "B",
         "score": [2, 0], "pen_score": None},
        {"round": "Semifinals", "date": "2025-02-25", "home": "C", "away": "D",
         "score": None, "pen_score": None},
    ]
    results = list(iter_fixtures(fixtures))
    assert results[0] == ("Round 1|A|B", "A", "B", "2024-10-29", "FINISHED")
    assert results[1] == ("Semifinals|C|D", "C", "D", "2025-02-25", "SCHEDULED")


def _dc(strength=None):
    return {"attack": strength or {}, "defense": {}, "home_adv": 0.1, "rho": -0.1}


def test_snapshot_and_save_locks_a_due_fixture(tmp_path):
    config = CompetitionConfig(CONFIG_DATA)
    out_dir = os.path.join(str(tmp_path), "competitions", config.slug)
    os.makedirs(out_dir, exist_ok=True)
    fixtures = [{"round": "Round 1", "date": "2026-11-05", "home": "A", "away": "B",
                 "score": None, "pen_score": None}]
    with open(os.path.join(out_dir, "knockout_fixtures.json"), "w") as f:
        json.dump(fixtures, f)

    added = snapshot_and_save(config, str(tmp_path), [_dc({"A": 1.0, "B": -1.0})], today="2026-11-03")

    assert added == 1
    with open(os.path.join(out_dir, "predictions_snapshot.json")) as f:
        snapshot = json.load(f)
    assert "Round 1|A|B" in snapshot
    assert snapshot["Round 1|A|B"]["predicted_winner"] == "H"  # A is much stronger


def test_snapshot_and_save_skips_a_fixture_not_yet_due(tmp_path):
    config = CompetitionConfig(CONFIG_DATA)
    out_dir = os.path.join(str(tmp_path), "competitions", config.slug)
    os.makedirs(out_dir, exist_ok=True)
    fixtures = [{"round": "Round 1", "date": "2026-12-25", "home": "A", "away": "B",
                 "score": None, "pen_score": None}]
    with open(os.path.join(out_dir, "knockout_fixtures.json"), "w") as f:
        json.dump(fixtures, f)

    added = snapshot_and_save(config, str(tmp_path), [_dc()], today="2026-11-03")

    assert added == 0


def test_snapshot_and_save_never_overwrites_an_existing_lock(tmp_path):
    config = CompetitionConfig(CONFIG_DATA)
    out_dir = os.path.join(str(tmp_path), "competitions", config.slug)
    os.makedirs(out_dir, exist_ok=True)
    fixtures = [{"round": "Round 1", "date": "2026-11-05", "home": "A", "away": "B",
                 "score": None, "pen_score": None}]
    with open(os.path.join(out_dir, "knockout_fixtures.json"), "w") as f:
        json.dump(fixtures, f)
    preexisting = {"Round 1|A|B": {"home": "A", "away": "B", "date": "2026-11-05",
                                    "ph": 0.9, "pd": 0.05, "pa": 0.05,
                                    "predicted_winner": "H", "predicted_score": "3-0",
                                    "snapped_at": "2026-11-01"}}
    with open(os.path.join(out_dir, "predictions_snapshot.json"), "w") as f:
        json.dump(preexisting, f)

    added = snapshot_and_save(config, str(tmp_path), [_dc({"A": -5.0, "B": 5.0})], today="2026-11-03")

    assert added == 0
    with open(os.path.join(out_dir, "predictions_snapshot.json")) as f:
        assert json.load(f) == preexisting  # untouched
