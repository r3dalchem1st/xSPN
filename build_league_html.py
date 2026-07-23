"""
Renders a static standings + title/relegation-odds page for a round-robin
competition, from schedule.json (fetch_league.py) + league_sim.json
(sim_league.py). Follows the same __PLACEHOLDER__ substitution pattern as
build_html.py/template.html (this project's established convention, avoids
Python f-string escaping issues with large HTML).

Deliberately a separate template/script rather than extending template.html:
that template is World-Cup-specific (Bracket/Podium tabs, group logic) and
lives on the production GitHub Pages site — a new, unrelated competition's
page shouldn't risk it.
"""
import html as html_lib
import json
import os
import re
import sys
from datetime import date

RELEGATION_ZONE = 3  # Premier League specific; a display choice, not baked
                       # into sim_league.py (cutoffs vary by league/season)

DEFAULT_TOP_ZONE = 4  # Champions-League-style qualification (PL, La Liga, Bundesliga)
# Championship-style leagues have a SMALLER automatic-promotion count, with
# a separate playoff tier below it for the remaining spot(s) — highlighting
# all 4 rows the same as a top-flight league's European-qualification zone
# would be factually wrong, not just a simplification (a real bug found in
# the 22 Jul audit of the live Championship page, which showed 4 green rows
# when only the top 2 are actually automatically promoted).
TOP_ZONE_OVERRIDES = {"Championship": 2}


def top_zone_for(competition_name):
    """Size of the promotion/qualification highlight zone (the green-
    bordered top rows). Keyed by competition NAME (config.name), not slug —
    that's what callers already have in scope without a schema change."""
    return TOP_ZONE_OVERRIDES.get(competition_name, DEFAULT_TOP_ZONE)


def compute_full_standings(schedule):
    """Full current standings from FINISHED schedule entries:
    {team: {"played","w","d","l","gf","ga","gd","pts"}}."""
    table = {}
    for key, entry in schedule.items():
        if entry["status"] != "FINISHED":
            continue
        home, away = key.split("|")
        hg, ag = entry["goals"][home], entry["goals"][away]
        for t in (home, away):
            table.setdefault(t, {"played": 0, "w": 0, "d": 0, "l": 0,
                                  "gf": 0, "ga": 0, "gd": 0, "pts": 0})
        table[home]["played"] += 1; table[away]["played"] += 1
        table[home]["gf"] += hg; table[home]["ga"] += ag; table[home]["gd"] += hg - ag
        table[away]["gf"] += ag; table[away]["ga"] += hg; table[away]["gd"] += ag - hg
        if hg > ag:
            table[home]["w"] += 1; table[home]["pts"] += 3; table[away]["l"] += 1
        elif ag > hg:
            table[away]["w"] += 1; table[away]["pts"] += 3; table[home]["l"] += 1
        else:
            table[home]["d"] += 1; table[home]["pts"] += 1
            table[away]["d"] += 1; table[away]["pts"] += 1
    return table


def build_standings_rows(schedule, rank_dist, relegation_zone=RELEGATION_ZONE):
    """Ranked standings rows (pts -> gd -> gf -> expected final position),
    each augmented with title% and relegation-zone% from rank_dist
    (sim_league.py's per-team rank distribution, index 0 = 1st place).
    The expected-position tiebreak matters most preseason or on any tied
    group of teams: with everyone still on 0 points, sorting on pts/gd/gf
    alone falls back to whatever order `teams` happens to be in (here,
    alphabetical) rather than anything meaningful — the model's own
    projected finish is a far more useful tiebreak than alphabetical order.
    Returns a list of dicts with a "pos" field set after sorting."""
    table = compute_full_standings(schedule)
    teams = sorted({t for key in schedule for t in key.split("|")})
    n = len(teams)
    rows = []
    for t in teams:
        stats = table.get(t, {"played": 0, "w": 0, "d": 0, "l": 0,
                               "gf": 0, "ga": 0, "gd": 0, "pts": 0})
        dist = rank_dist.get(t, [0.0] * n)
        expected_rank = sum((i + 1) * p for i, p in enumerate(dist))
        rows.append({
            "team": t, **stats,
            "title_pct": dist[0],
            "releg_pct": sum(dist[-relegation_zone:]),
            "expected_rank": expected_rank,
        })
    rows.sort(key=lambda r: (r["pts"], r["gd"], r["gf"], -r["expected_rank"]), reverse=True)
    for i, r in enumerate(rows):
        r["pos"] = i + 1
    return rows


def render_rows_html(rows):
    """Standings rows -> <tr> markup. Team names are escaped: they
    ultimately originate from openfootball's external data, and the 22 Jul
    audit flagged unescaped externally-sourced names flowing into HTML
    elsewhere in this project (template.html's injury notes) — this module
    doesn't repeat that gap."""
    lines = []
    for r in rows:
        team = html_lib.escape(r["team"])
        lines.append(
            f"    <tr><td>{r['pos']}</td><td>{team}</td><td>{r['played']}</td>"
            f"<td>{r['w']}</td><td>{r['d']}</td><td>{r['l']}</td>"
            f"<td>{r['gf']}</td><td>{r['ga']}</td><td>{r['gd']}</td><td>{r['pts']}</td>"
            f"<td class=\"odds\">{r['title_pct']:.1%}</td>"
            f"<td class=\"odds\">{r['releg_pct']:.1%}</td></tr>"
        )
    return "\n".join(lines)


def build_league_html(config, base_dir, template_path, relegation_zone=RELEGATION_ZONE,
                        n_sims=10000):
    """Load <slug>/schedule.json + league_sim.json, render the standings
    table into `template_path`'s __PLACEHOLDER__ tokens, and write
    <slug>/index.html. Raises AssertionError if any __PLACEHOLDER__-shaped
    token survives substitution — the WC's build_html.py has no such check
    (flagged by the 22 Jul audit as a gap); this module adds it from the
    start rather than repeating the omission."""
    from competition_config import artifact_dir
    out_dir = artifact_dir(config, base_dir)

    with open(os.path.join(out_dir, "schedule.json")) as f:
        schedule = json.load(f)
    sim_path = os.path.join(out_dir, "league_sim.json")
    if not os.path.exists(sim_path):
        raise FileNotFoundError(f"{sim_path} not found — run sim_league.py first")
    with open(sim_path) as f:
        rank_dist = json.load(f)

    rows = build_standings_rows(schedule, rank_dist, relegation_zone)
    rows_html = render_rows_html(rows)
    top_zone = top_zone_for(config.name)

    with open(template_path, encoding="utf-8") as f:
        page = f.read()
    page = page.replace("__COMPETITION_NAME__", html_lib.escape(config.name))
    page = page.replace("__GENERATED_DATE__", date.today().isoformat())
    page = page.replace("__N_SIMS__", str(n_sims))
    page = page.replace("__RELEGATION_ZONE__", str(relegation_zone))
    page = page.replace("__TOP_ZONE__", str(top_zone))
    page = page.replace("__STANDINGS_ROWS__", rows_html)

    leftover = re.findall(r"__[A-Z_]+__", page)
    assert not leftover, f"unconsumed placeholder(s) in output: {leftover}"

    out_path = os.path.join(out_dir, "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(page)
    return out_path


def main():
    if len(sys.argv) != 2:
        print("usage: python build_league_html.py competitions/<slug>.json")
        raise SystemExit(1)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from competition_config import load_competition
    config = load_competition(sys.argv[1])
    base_dir = os.path.dirname(os.path.abspath(__file__))
    template_path = os.path.join(base_dir, "league_template.html")
    out_path = build_league_html(config, base_dir, template_path)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
