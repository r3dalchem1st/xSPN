"""ONE-OFF (delete after use): the football-data.org feed vs the openfootball data we hold,
for the FINISHED 2025-26 Champions League -- do scores, shoot-outs, dates and stages agree?"""
import json

import fetch_cup
from competition_config import load_competition
from sim_cup import _bracket_round

config = load_competition("competitions/champions_league.json")
fd = fetch_cup.fetch_football_data_season("CL", 2025)
print("FD 2025 matches kept:", len(fd))
sched_fd, sk1 = fetch_cup.build_league_schedule(config, fd)
ko_fd, sk2 = fetch_cup.build_knockout_fixtures(config, fd)
print("skipped (unmapped names):", sk1, sk2)

with open("competitions/champions_league/league_schedule.json", encoding="utf-8") as f:
    sched_of = json.load(f)
with open("competitions/champions_league/knockout_fixtures.json", encoding="utf-8") as f:
    ko_of = json.load(f)

print("\n== league phase:", len(sched_fd), "FD vs", len(sched_of), "openfootball")
print("keys only in FD:", sorted(set(sched_fd) - set(sched_of))[:5], "| only in openfootball:", sorted(set(sched_of) - set(sched_fd))[:5])
bad_goals = [(k, sched_fd[k]["goals"], sched_of[k]["goals"]) for k in sched_fd if k in sched_of and sched_fd[k]["goals"] != sched_of[k]["goals"]]
bad_date = [(k, sched_fd[k]["date"], sched_of[k]["date"]) for k in sched_fd if k in sched_of and sched_fd[k]["date"] != sched_of[k]["date"]]
bad_round = [(k, sched_fd[k]["round"], sched_of[k]["round"]) for k in sched_fd if k in sched_of and sched_fd[k]["round"] != sched_of[k]["round"]]
print("score mismatches:", len(bad_goals), bad_goals[:5])
print("date mismatches:", len(bad_date), bad_date[:5])
print("round-label mismatches:", len(bad_round), bad_round[:3])

print("\n== knockout:", len(ko_fd), "FD vs", len(ko_of), "openfootball")


def idx(fixtures):
    return {(fx["home"], fx["away"], _bracket_round(fx["round"])): fx for fx in fixtures}


a, b = idx(ko_fd), idx(ko_of)
print("only in FD:", sorted(set(a) - set(b))[:5], "| only in openfootball:", sorted(set(b) - set(a))[:5])
for field in ("score", "pen_score", "date"):
    bad = [(k, a[k][field], b[k][field]) for k in a if k in b and a[k][field] != b[k][field]]
    print(f"{field} mismatches:", len(bad), bad[:6])
print("ET/pens matches in FD:", [(fx["home"], fx["away"], fx["score"], fx["pen_score"]) for fx in ko_fd if fx["pen_score"]])
print("bracket buckets FD:", {r: sum(1 for fx in ko_fd if _bracket_round(fx["round"]) == r) for r in
                              ("playoff", "round_of_16", "quarterfinal", "semifinal", "final")})
