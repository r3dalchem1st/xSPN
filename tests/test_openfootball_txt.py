import pytest

from openfootball_txt import parse_openfootball_txt

UNPLAYED = """= English Championship 2026/27

# Date       Fri Aug 14 2026 - Sat May 1 2027 (260d)
# Teams      24
# Matches    552



▪ Matchday 1
  Fri Aug 14 2026
    20:00  Wolverhampton Wanderers FC v Blackburn Rovers FC
  Sat Aug 15
    12:30  Bolton Wanderers FC     v Preston North End FC
    15:00  Norwich City FC         v West Bromwich Albion FC
           Bristol City FC         v Millwall FC
  Sun Aug 16
    13:30  Watford FC              v Southampton FC
  Mon Aug 17
    20:00  Cardiff City FC         v Wrexham AFC
"""

PLAYED = """= English Premier League 2024/25

# Date       Fri Aug 16 2024 - Sun May 25 2025 (282d)
# Teams      20
# Matches    380



▪ Matchday 1
  Fri Aug 16 2024
    20:00  Manchester United FC    v Fulham FC                1-0 (0-0)
  Sat Aug 17
    12:30  Ipswich Town FC         v Liverpool FC             0-2 (0-0)
    15:00  Arsenal FC              v Wolverhampton Wanderers FC  2-0 (1-0)
           Everton FC              v Brighton & Hove Albion FC  0-3 (0-1)
"""

ROLLOVER = """= Test League 2024/25

▪ Matchday 20
  Mon Dec 30 2024
    20:00  Team A v Team B            1-1 (0-0)
  Wed Jan 1
    15:00  Team C v Team D            2-0 (1-0)
"""


def test_parses_unplayed_fixtures_with_no_score():
    matches = parse_openfootball_txt(UNPLAYED)
    assert len(matches) == 6
    first = matches[0]
    assert first == {
        "round": "Matchday 1", "date": "2026-08-14",
        "home": "Wolverhampton Wanderers FC", "away": "Blackburn Rovers FC",
        "score": None,
    }
    # a continuation line with no leading time still resolves under the
    # previous date heading
    continuation = matches[3]
    assert continuation["date"] == "2026-08-15"
    assert continuation["home"] == "Bristol City FC"


def test_parses_played_fixtures_with_score():
    matches = parse_openfootball_txt(PLAYED)
    assert len(matches) == 4
    assert matches[0] == {
        "round": "Matchday 1", "date": "2024-08-16",
        "home": "Manchester United FC", "away": "Fulham FC", "score": (1, 0),
    }
    assert matches[3] == {
        "round": "Matchday 1", "date": "2024-08-17",
        "home": "Everton FC", "away": "Brighton & Hove Albion FC", "score": (0, 3),
    }


def test_year_rolls_over_at_a_dateless_month_boundary():
    matches = parse_openfootball_txt(ROLLOVER)
    assert matches[0]["date"] == "2024-12-30"
    assert matches[1]["date"] == "2025-01-01"


def test_match_line_before_any_date_line_raises():
    with pytest.raises(ValueError, match="before any date line"):
        parse_openfootball_txt("▪ Matchday 1\n    20:00  Team A v Team B\n")
