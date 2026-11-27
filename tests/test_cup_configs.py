import os

from competition_config import load_competition

COMPETITIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "competitions",
)


def test_champions_league_config_loads():
    config = load_competition(os.path.join(COMPETITIONS_DIR, "champions_league.json"))
    assert config.slug == "champions_league"
    assert config.format == "league_phase_knockout"
    assert config.openfootball_repo == "openfootball/champions-league"
    seasons = [f["season"] for f in config.openfootball_files]
    assert seasons == sorted(seasons, reverse=True)
    assert config.football_data_code == "CL"


def test_copa_del_rey_config_loads():
    config = load_competition(os.path.join(COMPETITIONS_DIR, "copa_del_rey.json"))
    assert config.slug == "copa_del_rey"
    assert config.format == "knockout_only"
    assert config.openfootball_repo == "openfootball/espana"
    assert config.extra_training_sources  # non-empty, per the design doc
    # Not on football-data.org's free tier; openfootball has no Copa file after 2024-25, so the
    # current editions come from Wikipedia (newest first) and the four Supercopa clubs enter late.
    assert config.football_data_code is None
    assert [p["season"] for p in config.wikipedia_pages] == ["2026-27", "2025-26"]
    assert config.current_season == "2026-27"
    assert len(config.late_entrants["round_3"]) == 4
    assert {"repo": "openfootball/espana", "path": "2026-27/1-liga.txt"} in config.extra_training_sources
