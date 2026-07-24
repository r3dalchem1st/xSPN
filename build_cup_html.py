"""
Renders a League Table/Bracket/Title Odds page for a league_phase_knockout
competition, from league_schedule.json + knockout_fixtures.json
(fetch_cup.py), cup_sim.json (sim_cup.py), and optionally
predictions_snapshot.json / results_accuracy.json.

Deliberately a separate template/script from both build_league_html.py and
build_html.py, same non-refactor posture the round-robin leagues already
established -- but DOES reuse two of build_league_html.py's pure,
format-agnostic pieces directly: compute_full_standings() (works on any
"home|away"-keyed {status,goals} schedule dict, which league_schedule.json
already is) and score_match-style escaping conventions.

Only 3 tabs, not the 4 originally sketched (League Table / Playoffs /
Bracket / Title Odds) -- a real gap found while building sim_cup.py: unlike
the World Cup's bracket (fixed topology, only the occupants uncertain),
UCL/UEL's Round-of-16-onward pairings are themselves drawn at random each
season, so there's no well-defined "predicted bracket" to show before that
round's real draw happens. "Bracket" here shows the REAL bracket as it
becomes known (played or not), not a simulated prediction -- Playoffs folds
into it as just its first column, rather than a separate, redundant tab.
"""
import html as html_lib
import json
import os
import re
import sys
from datetime import date

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DIR)
from build_league_html import compute_full_standings
from render_nav import nav_entries, render_nav_html
from sim_cup import PLAYOFF_SIZE, TOP_SEEDS, _bracket_round, build_played_ties

STAGE_ORDER = ["playoff", "round_of_16", "quarterfinal", "semifinal", "final"]
STAGE_TITLES = {
    "playoff": "Play-offs", "round_of_16": "Round of 16",
    "quarterfinal": "Quarterfinal", "semifinal": "Semifinal", "final": "Final",
}


def build_standings_rows(league_schedule, zone_odds, expected_pos):
    """Ranked league-phase standings rows (pts -> gd -> gf -> expected
    final position tiebreak — see sim_cup.py's expected_pos docstring for
    why), each augmented with top8%/playoff% from sim_cup.py's zone_odds."""
    table = compute_full_standings(league_schedule)
    teams = sorted({t for key in league_schedule for t in key.split("|")})
    rows = []
    for t in teams:
        stats = table.get(t, {"played": 0, "w": 0, "d": 0, "l": 0,
                               "gf": 0, "ga": 0, "gd": 0, "pts": 0})
        odds = zone_odds.get(t, {"top8": 0.0, "playoff_zone": 0.0, "eliminated": 0.0})
        rows.append({
            "team": t, **stats,
            "top8_pct": odds["top8"], "playoff_pct": odds["playoff_zone"],
            "expected_rank": expected_pos.get(t, len(teams)),
        })
    rows.sort(key=lambda r: (r["pts"], r["gd"], r["gf"], -r["expected_rank"]), reverse=True)
    for i, r in enumerate(rows):
        r["pos"] = i + 1
    return rows


def render_rows_html(rows):
    """Standings rows -> <tr> markup. Team names escaped (external
    openfootball data, same discipline as build_league_html.py)."""
    lines = []
    for r in rows:
        team = html_lib.escape(r["team"])
        lines.append(
            f"    <tr><td>{r['pos']}</td><td>{team}</td><td>{r['played']}</td>"
            f"<td>{r['w']}</td><td>{r['d']}</td><td>{r['l']}</td>"
            f"<td>{r['gf']}</td><td>{r['ga']}</td><td>{r['gd']}</td><td>{r['pts']}</td>"
            f"<td class=\"odds\">{r['top8_pct']:.1%}</td>"
            f"<td class=\"odds\">{r['playoff_pct']:.1%}</td></tr>"
        )
    return "\n".join(lines)


def _group_ties(knockout_fixtures):
    """{stage: {frozenset(pair): [legs sorted by date]}}, using the exact
    same round classification sim_cup.py's Monte Carlo treats as "already
    known" for that round — so what a visitor sees here always matches what
    the simulation itself is trusting as fact."""
    grouped = {}
    for fx in knockout_fixtures:
        stage = _bracket_round(fx["round"])
        if stage is None:
            continue
        grouped.setdefault(stage, {}).setdefault(frozenset((fx["home"], fx["away"])), []).append(fx)
    for stage in grouped:
        for pair in grouped[stage]:
            grouped[stage][pair].sort(key=lambda fx: fx["date"])
    return grouped


def _leg_row_html(fx, snapshot):
    home, away = html_lib.escape(fx["home"]), html_lib.escape(fx["away"])
    date_line = f'<div class="bm-date">{fx["date"]}</div>'
    if fx["score"] is not None:
        hg, ag = fx["score"]
        home_cls = "win" if hg > ag else ("lose" if hg < ag else "")
        away_cls = "win" if ag > hg else ("lose" if ag < hg else "")
        pen = f' <span class="hint">(pens {fx["pen_score"][0]}-{fx["pen_score"][1]})</span>' if fx["pen_score"] else ""
        return (f'{date_line}<div class="bm-t {home_cls}">{home}<span class="bm-sc">{hg}</span></div>'
                f'<div class="bm-t {away_cls}">{away}<span class="bm-sc">{ag}{pen}</span></div>')
    key = f"{fx['round']}|{fx['home']}|{fx['away']}"
    if key in snapshot:
        s = snapshot[key]
        return (f'{date_line}<div class="bm-t">{home}</div><div class="bm-t">{away}</div>'
                f'<div class="bm-pct">{s["predicted_score"]} &middot; {s["predicted_winner"]}</div>')
    return f'{date_line}<div class="bm-t">{home}</div><div class="bm-t">{away}</div><div class="bm-pct hint">not yet predicted</div>'


def _tie_card_html(pair, legs, decided, snapshot):
    lines = ['<div class="bm">']
    for fx in legs:
        lines.append(_leg_row_html(fx, snapshot))
    winner = decided.get(pair)
    if winner:
        lines.append(f'<div class="bm-pct"><strong>Advances: {html_lib.escape(winner)}</strong></div>')
    lines.append('</div>')
    return "\n".join(lines)


def build_bracket_html(knockout_fixtures, snapshot):
    """Every REAL knockout fixture (played or scheduled), grouped into one
    column per bracket stage in the correct sequence — NOT the leagues'
    build_bracket_html's numeric-Matchday sort, which would put "Round of
    16" (extracts "16") after "Playoffs, Matchday 1/2" and scramble
    Quarterfinal/Semifinal/Final (no digits at all, all sort at 0)."""
    if not knockout_fixtures:
        return '<div class="empty-note">Knockout stage not drawn yet.</div>'
    ties = _group_ties(knockout_fixtures)
    decided = build_played_ties(knockout_fixtures)
    lines = ['<div class="bracket-wrap"><div class="bracket">']
    for stage in STAGE_ORDER:
        if stage not in ties:
            continue
        lines.append(f'<div class="br-col"><div class="br-title">{STAGE_TITLES[stage]}</div><div class="br-matches">')
        for pair, legs in ties[stage].items():
            lines.append(_tie_card_html(pair, legs, decided, snapshot))
        lines.append('</div></div>')
    lines.append('</div></div>')
    return "\n".join(lines)


def build_odds_rows_html(stage_odds):
    """Title-odds rows, champion% descending. Falls back to a single
    empty-state row rather than an empty <tbody> if the simulation hasn't
    run yet (real near-term state — see module docstring)."""
    if not stage_odds:
        return '<tr><td colspan="6" class="empty-note">No simulation yet — league-phase draw may not be released.</td></tr>'
    rows = sorted(stage_odds.items(), key=lambda kv: -kv[1]["champion"])
    lines = []
    for team, odds in rows:
        t = html_lib.escape(team)
        lines.append(
            f'<tr><td>{t}</td>'
            f'<td class="odds">{odds["round_of_16"]:.1%}</td>'
            f'<td class="odds">{odds["quarterfinal"]:.1%}</td>'
            f'<td class="odds">{odds["semifinal"]:.1%}</td>'
            f'<td class="odds">{odds["final"]:.1%}</td>'
            f'<td class="odds">{odds["champion"]:.1%}</td></tr>'
        )
    return "\n".join(lines)


def build_champion_html(stage_odds):
    if not stage_odds:
        return ""
    leader, odds = max(stage_odds.items(), key=lambda kv: kv[1]["champion"])
    team = html_lib.escape(leader)
    return (
        '<div class="champ-line">Current title-odds leader: '
        f'<strong>{team}</strong> ({odds["champion"]:.1%})</div>'
    )


def build_cup_html(config, base_dir, template_path, n_sims=10000):
    """Load <slug>/league_schedule.json + knockout_fixtures.json (+
    optional cup_sim.json / predictions_snapshot.json /
    results_accuracy.json), render the League Table/Bracket/Title-Odds
    panes into `template_path`'s __PLACEHOLDER__ tokens, and write
    <slug>/index.html. Unlike build_league_html.py, a missing cup_sim.json
    is NOT fatal — sim_cup.py itself refuses to run until the league-phase
    draw is released (needs >=24 teams), a real, expected, weeks-long state
    for these two competitions right now, not a broken pipeline."""
    from competition_config import artifact_dir
    out_dir = artifact_dir(config, base_dir)

    with open(os.path.join(out_dir, "league_schedule.json")) as f:
        league_schedule = json.load(f)
    ko_path = os.path.join(out_dir, "knockout_fixtures.json")
    knockout_fixtures = []
    if os.path.exists(ko_path):
        with open(ko_path) as f:
            knockout_fixtures = json.load(f)

    sim_path = os.path.join(out_dir, "cup_sim.json")
    zone_odds, stage_odds, expected_pos = {}, {}, {}
    if os.path.exists(sim_path):
        with open(sim_path) as f:
            sim = json.load(f)
        zone_odds = sim.get("zone_odds") or {}
        stage_odds = sim.get("stage_odds") or {}
        expected_pos = sim.get("expected_pos") or {}

    snapshot_path = os.path.join(out_dir, "predictions_snapshot.json")
    snapshot = json.load(open(snapshot_path)) if os.path.exists(snapshot_path) else {}

    rows = build_standings_rows(league_schedule, zone_odds, expected_pos)
    rows_html = render_rows_html(rows)
    nav_html = render_nav_html(nav_entries(base_dir, active=config.slug))

    with open(template_path, encoding="utf-8") as f:
        page = f.read()
    page = page.replace("__NAV__", nav_html)
    page = page.replace("__COMPETITION_NAME__", html_lib.escape(config.name))
    page = page.replace("__GENERATED_DATE__", date.today().isoformat())
    page = page.replace("__N_SIMS__", str(n_sims))
    page = page.replace("__TOP_SEEDS__", str(TOP_SEEDS))
    page = page.replace("__PLAYOFF_START__", str(TOP_SEEDS + 1))
    page = page.replace("__PLAYOFF_END__", str(TOP_SEEDS + PLAYOFF_SIZE))
    page = page.replace("__STANDINGS_ROWS__", rows_html)
    page = page.replace("__BRACKET_HTML__", build_bracket_html(knockout_fixtures, snapshot))
    page = page.replace("__ODDS_ROWS__", build_odds_rows_html(stage_odds))
    page = page.replace("__CHAMPION_LINE__", build_champion_html(stage_odds))

    leftover = re.findall(r"__[A-Z_]+__", page)
    assert not leftover, f"unconsumed placeholder(s) in output: {leftover}"

    out_path = os.path.join(out_dir, "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(page)
    return out_path


def main():
    if len(sys.argv) != 2:
        print("usage: python build_cup_html.py competitions/<slug>.json")
        raise SystemExit(1)
    from competition_config import load_competition
    config = load_competition(sys.argv[1])
    base_dir = os.path.dirname(os.path.abspath(__file__))
    template_path = os.path.join(base_dir, "cup_template.html")
    out_path = build_cup_html(config, base_dir, template_path)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
