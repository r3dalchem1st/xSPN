import json

import pytest

from competition_config import CompetitionConfig, load_competition

VALID_DATA = {
    "slug": "premier_league",
    "name": "Premier League",
    "format": "round_robin",
    "openfootball_repo": "openfootball/england",
    "openfootball_files": [{"season": "2026-27", "path": "2026-27/1-premierleague.txt"}],
    "team_aliases": {"Man United": "Manchester United FC"},
}


def test_load_valid_config():
    config = CompetitionConfig(VALID_DATA)
    assert config.slug == "premier_league"
    assert config.format == "round_robin"
    assert config.openfootball_files[0]["path"] == "2026-27/1-premierleague.txt"


def test_missing_required_field_raises():
    bad = {k: v for k, v in VALID_DATA.items() if k != "openfootball_repo"}
    with pytest.raises(ValueError, match="openfootball_repo"):
        CompetitionConfig(bad)


def test_invalid_format_raises():
    bad = dict(VALID_DATA, format="single_elimination_ladder")
    with pytest.raises(ValueError, match="unknown format"):
        CompetitionConfig(bad)


def test_league_phase_knockout_format_accepted():
    data = dict(VALID_DATA, format="league_phase_knockout")
    config = CompetitionConfig(data)
    assert config.format == "league_phase_knockout"


def test_empty_openfootball_files_raises():
    bad = dict(VALID_DATA, openfootball_files=[])
    with pytest.raises(ValueError, match="openfootball_files"):
        CompetitionConfig(bad)


def test_resolve_team_applies_alias():
    config = CompetitionConfig(VALID_DATA)
    assert config.resolve_team("Man United") == "Manchester United FC"


def test_resolve_team_passthrough_when_no_roster():
    config = CompetitionConfig(VALID_DATA)
    assert config.resolve_team("Fulham FC") == "Fulham FC"


def test_resolve_team_rejects_unknown_when_roster_set():
    data = dict(VALID_DATA, teams=["Manchester United FC", "Fulham FC"])
    config = CompetitionConfig(data)
    assert config.resolve_team("Some Random FC") is None
    assert config.resolve_team("Fulham FC") == "Fulham FC"


def test_load_competition_from_file(tmp_path):
    p = tmp_path / "premier_league.json"
    p.write_text(json.dumps(VALID_DATA))
    config = load_competition(str(p))
    assert config.name == "Premier League"


def test_extra_training_sources_defaults_to_empty_list():
    config = CompetitionConfig(VALID_DATA)
    assert config.extra_training_sources == []


def test_extra_training_sources_read_when_present():
    data = dict(VALID_DATA, extra_training_sources=[
        {"repo": "openfootball/espana", "path": "2024-25/2-liga2.txt"},
    ])
    config = CompetitionConfig(data)
    assert config.extra_training_sources == [
        {"repo": "openfootball/espana", "path": "2024-25/2-liga2.txt"},
    ]


def test_knockout_only_format_accepted():
    data = dict(VALID_DATA, format="knockout_only")
    config = CompetitionConfig(data)
    assert config.format == "knockout_only"


def test_football_data_code_defaults_to_none():
    config = CompetitionConfig(VALID_DATA)
    assert config.football_data_code is None


def test_football_data_code_read_when_present():
    data = dict(VALID_DATA, football_data_code="PL")
    config = CompetitionConfig(data)
    assert config.football_data_code == "PL"


def test_calibration_fields_default_to_no_op():
    config = CompetitionConfig(VALID_DATA)
    assert config.strength_shrink == 1.0
    assert config.draw_inflate == 0.0
    assert config.use_rho is False


def test_calibration_fields_read_when_present():
    data = dict(VALID_DATA, strength_shrink=0.6, draw_inflate=0.35, use_rho=True)
    config = CompetitionConfig(data)
    assert config.strength_shrink == 0.6
    assert config.draw_inflate == 0.35
    assert config.use_rho is True


def test_momentum_fields_default_to_no_op():
    config = CompetitionConfig(VALID_DATA)
    assert config.momentum_weight == 0.0
    assert config.momentum_n == 5


def test_momentum_fields_read_when_present():
    data = dict(VALID_DATA, momentum_weight=0.1, momentum_n=8)
    config = CompetitionConfig(data)
    assert config.momentum_weight == 0.1
    assert config.momentum_n == 8


def test_odds_history_code_defaults_to_none():
    config = CompetitionConfig(VALID_DATA)
    assert config.odds_history_code is None


def test_odds_history_code_read_when_present():
    data = dict(VALID_DATA, odds_history_code="E0")
    config = CompetitionConfig(data)
    assert config.odds_history_code == "E0"


def test_odds_api_sport_key_defaults_to_none():
    config = CompetitionConfig(VALID_DATA)
    assert config.odds_api_sport_key is None


def test_odds_api_sport_key_read_when_present():
    data = dict(VALID_DATA, odds_api_sport_key="soccer_epl")
    config = CompetitionConfig(data)
    assert config.odds_api_sport_key == "soccer_epl"
