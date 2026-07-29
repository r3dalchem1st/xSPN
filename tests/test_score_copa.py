import json
import os

from competition_config import CompetitionConfig
from score_copa import score_and_save

CONFIG_DATA = {
    "slug": "copa_del_rey", "name": "Copa del Rey", "format": "knockout_only",
    "openfootball_repo": "openfootball/espana",
    "openfootball_files": [{"season": "2024-25", "path": "2024-25/cup.txt"}],
    "team_aliases": {},
}


def test_score_and_save_scores_a_finished_locked_fixture(tmp_path):
    config = CompetitionConfig(CONFIG_DATA)
    out_dir = os.path.join(str(tmp_path), "competitions", config.slug)
    os.makedirs(out_dir, exist_ok=True)
    fixtures = [{"round": "Round 1", "date": "2024-10-29", "home": "A", "away": "B",
                 "score": [2, 0], "pen_score": None}]
    with open(os.path.join(out_dir, "knockout_fixtures.json"), "w") as f:
        json.dump(fixtures, f)
    snapshot = {"Round 1|A|B": {"home": "A", "away": "B", "date": "2024-10-29",
                                 "ph": 0.7, "pd": 0.2, "pa": 0.1,
                                 "predicted_winner": "H", "predicted_score": "2-0",
                                 "snapped_at": "2024-10-27"}}
    with open(os.path.join(out_dir, "predictions_snapshot.json"), "w") as f:
        json.dump(snapshot, f)

    result = score_and_save(config, str(tmp_path))

    assert result["summary"]["n_scored"] == 1
    assert result["summary"]["accuracy"] == 1.0
    assert result["matches"][0]["correct_winner"] is True


def test_score_and_save_skips_a_finished_fixture_with_no_snapshot(tmp_path):
    config = CompetitionConfig(CONFIG_DATA)
    out_dir = os.path.join(str(tmp_path), "competitions", config.slug)
    os.makedirs(out_dir, exist_ok=True)
    fixtures = [{"round": "Round 1", "date": "2024-10-29", "home": "A", "away": "B",
                 "score": [2, 0], "pen_score": None}]
    with open(os.path.join(out_dir, "knockout_fixtures.json"), "w") as f:
        json.dump(fixtures, f)

    result = score_and_save(config, str(tmp_path))

    assert result["summary"]["n_scored"] == 0
    assert result["summary"]["accuracy"] is None


def test_score_and_save_skips_an_unplayed_fixture(tmp_path):
    config = CompetitionConfig(CONFIG_DATA)
    out_dir = os.path.join(str(tmp_path), "competitions", config.slug)
    os.makedirs(out_dir, exist_ok=True)
    fixtures = [{"round": "Round 1", "date": "2026-11-05", "home": "A", "away": "B",
                 "score": None, "pen_score": None}]
    with open(os.path.join(out_dir, "knockout_fixtures.json"), "w") as f:
        json.dump(fixtures, f)
    snapshot = {"Round 1|A|B": {"home": "A", "away": "B", "date": "2026-11-05",
                                 "ph": 0.7, "pd": 0.2, "pa": 0.1,
                                 "predicted_winner": "H", "predicted_score": "2-0",
                                 "snapped_at": "2026-11-03"}}
    with open(os.path.join(out_dir, "predictions_snapshot.json"), "w") as f:
        json.dump(snapshot, f)

    result = score_and_save(config, str(tmp_path))

    assert result["summary"]["n_scored"] == 0
