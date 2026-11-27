import json
import os
from datetime import date

import pytest
import requests

import fetch_copa
from competition_config import CompetitionConfig
from fetch_copa import fetch_and_save, fetch_wikipedia_season, parse_wikipedia_matches

TODAY = date(2026, 11, 30)

PAGE = """intro text
==Preliminary round==
===Draw===
A table: {| class="wikitable"
|}
===First leg===
{{football box collapsible
|id=
|date=26 September 2026
|time=18:00
|team1=[[CD Anaitasuna|Anaitasuna]]
|goals1={{Plainlist|
*[[A Player]] {{goal|10}}
}}
|score=5–0
|team2=[[CD Tedeón]]
}}
==First round==
{{football box collapsible
|date=4 October 2026
|team1=[[CF UE Tavernes de la Valldigna|Tavernes]] (3)
|score=0–0
|aet=yes
|penaltyscore=4–2
|team2='''[[UD Maracena|Maracena]]'''
|penalties1=
*{{pengoal}} [[X|X]]
}}
{{football box collapsible
|date=18 November 2026
|team1=[[Real Betis]]
|score=
|team2=[[Elche CF]]
}}
==Round of 32==
{{football box collapsible
|id=
|date=17 December 2025
|team1=
|score=
|team2=
}}
"""

FINAL_BOX = """{{Football box
| date = {{Start date|2027|4|24|df=y}}
| team1 = [[Atlético Madrid]]
| score = 2–2
| aet = yes
| team2 = [[Real Sociedad]]
|penaltyscore = 3–4
}}"""


def test_parse_reads_rounds_dates_teams_scores_and_shootouts():
    ms = parse_wikipedia_matches(PAGE, today=TODAY)
    assert [m["date"] for m in ms] == ["2026-09-26", "2026-10-04", "2026-11-18"]  # date order
    prelim, shootout, unscored = ms
    # link target (not the display text), score read past a multi-line nested template
    assert prelim == {"round": "Preliminary round", "date": "2026-09-26",
                      "home": "CD Anaitasuna", "away": "CD Tedeón", "score": (5, 0)}
    # pot suffix "(3)" and bold markup dropped; score after extra time, shoot-out kept apart
    assert shootout["home"] == "CF UE Tavernes de la Valldigna" and shootout["away"] == "UD Maracena"
    assert shootout["round"] == "Round 1" and shootout["score"] == (0, 0) and shootout["pen_score"] == (4, 2)
    assert unscored["score"] is None and "pen_score" not in unscored
    assert len(ms) == 3                      # the empty round-of-32 template skeleton is skipped


def test_parse_reads_the_start_date_template_used_by_a_final_article():
    ms = parse_wikipedia_matches("==Final==\n" + FINAL_BOX, today=TODAY)
    assert ms == [{"round": "Final", "date": "2027-04-24", "home": "Atlético Madrid",
                   "away": "Real Sociedad", "score": (2, 2), "pen_score": (3, 4)}]


@pytest.mark.parametrize("text, message", [
    ("==Bracket==\n{{football box collapsible\n|date=1 December 2026\n|team1=[[A]]\n|team2=[[B]]\n}}",
     "unrecognised heading"),
    ("==First round==\n{{football box collapsible\n|date=sometime\n|team1=[[A]]\n|team2=[[B]]\n}}",
     "no readable date"),
    ("==First round==\nno boxes here", "no matches"),
    # the score template changed: every past-dated match reads as unplayed
    ("==First round==\n" + "".join(
        f"{{{{football box collapsible\n|date={d} October 2026\n|team1=[[A{d}]]\n|score={{{{score|2|1}}}}\n|team2=[[B{d}]]\n}}}}\n"
        for d in (1, 2, 3)), "score"),
])
def test_parse_fails_loudly_on_format_drift(text, message):
    with pytest.raises(ValueError, match=message):
        parse_wikipedia_matches(text, today=TODAY)


def test_fetch_wikipedia_season_inlines_the_final_from_its_own_article(monkeypatch):
    pages = {
        "2026–27 Copa del Rey": "==First round==\n{{football box collapsible\n|date=4 October 2026\n"
                                "|team1=[[A]]\n|score=1–0\n|team2=[[B]]\n}}\n==Final==\n{{:2027 Copa del Rey final}}\n",
        "2027 Copa del Rey final": f"intro <onlyinclude>{FINAL_BOX}</onlyinclude> trailing text",
    }
    monkeypatch.setattr(fetch_copa, "_wikipedia_wikitext", lambda page, timeout: pages[page])
    ms = fetch_wikipedia_season("2026–27 Copa del Rey")
    assert [(m["round"], m["home"]) for m in ms] == [("Round 1", "A"), ("Final", "Atlético Madrid")]


def test_wikipedia_api_error_is_a_request_exception(monkeypatch):
    class Resp:
        def raise_for_status(self): pass
        def json(self): return {"error": {"info": "The page you specified doesn't exist."}}

    class Session:
        def get(self, *a, **kw): return Resp()

    monkeypatch.setattr(fetch_copa, "_wikipedia_session", Session())
    with pytest.raises(requests.RequestException, match="doesn't exist"):
        fetch_copa._wikipedia_wikitext("Nope", 5)


CONFIG_DATA = {
    "slug": "copa_del_rey", "name": "Copa del Rey", "format": "knockout_only",
    "openfootball_repo": "openfootball/espana",
    "openfootball_files": [{"season": "2024-25", "path": "2024-25/cup.txt"}],
    "wikipedia_pages": [{"season": "2026-27", "page": "2026–27 Copa del Rey"}],
    "team_aliases": {"Real Betis": "Real Betis Balompié"},
}
WIKI_MATCHES = [
    {"round": "Round 1", "date": "2026-10-29", "home": "Real Betis", "away": "CD Tedeón", "score": (3, 0)},
    {"round": "Round 2", "date": "2026-12-02", "home": "Real Betis", "away": "Elche CF", "score": None},
]
OLD_CUP = [{"round": "Final", "date": "2025-04-26", "home": "FC Barcelona", "away": "Real Madrid",
            "score": (3, 2), "pen_score": None}]


def test_fetch_and_save_takes_the_current_edition_from_wikipedia_and_history_from_openfootball(tmp_path, monkeypatch):
    config = CompetitionConfig(CONFIG_DATA)
    monkeypatch.setattr(fetch_copa, "fetch_wikipedia_season", lambda page: WIKI_MATCHES)
    monkeypatch.setattr(fetch_copa, "fetch_openfootball_file", lambda repo, path, timeout=10: "cup-text")
    monkeypatch.setattr(fetch_copa, "parse_openfootball_txt", lambda text: OLD_CUP)

    summary = fetch_and_save(config, str(tmp_path))

    assert summary["current_season_failed"] is False and summary["knockout_fixtures"] == 2
    out = tmp_path / "competitions" / "copa_del_rey"
    ko = json.loads((out / "knockout_fixtures.json").read_text())
    assert [fx["home"] for fx in ko] == ["Real Betis Balompié", "Real Betis Balompié"]   # aliased, newest edition only
    assert "Final" not in [fx["round"] for fx in ko]                                       # not the 2024-25 final
    rows = json.loads((out / "fetched_matches.json").read_text())
    assert len(rows) == 2                      # the played Wikipedia match + the played 2024-25 final


def test_fetch_and_save_keeps_the_old_fixtures_when_the_wikipedia_page_is_unreadable(tmp_path, monkeypatch):
    config = CompetitionConfig(CONFIG_DATA)
    out = tmp_path / "competitions" / "copa_del_rey"
    out.mkdir(parents=True)
    old = [{"round": "Final", "date": "2025-04-26", "home": "A", "away": "B", "score": [1, 0], "pen_score": None}]
    (out / "knockout_fixtures.json").write_text(json.dumps(old))

    def broken(page):
        raise ValueError("no matches found on the page")

    monkeypatch.setattr(fetch_copa, "fetch_wikipedia_season", broken)
    monkeypatch.setattr(fetch_copa, "fetch_openfootball_file", lambda repo, path, timeout=10: "cup-text")
    monkeypatch.setattr(fetch_copa, "parse_openfootball_txt", lambda text: OLD_CUP)

    summary = fetch_and_save(config, str(tmp_path))

    assert summary["current_season_failed"] is True
    assert "Wikipedia 2026–27 Copa del Rey" in summary["failed_seasons"]
    assert json.loads((out / "knockout_fixtures.json").read_text()) == old     # untouched, not replaced by 2024-25
