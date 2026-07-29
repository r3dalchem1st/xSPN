"""
Renders a Bracket/Title Odds page for a knockout_only competition, from
knockout_fixtures.json (fetch_copa.py) and copa_sim.json (sim_copa.py),
optionally predictions_snapshot.json. No League Table tab -- this format
has no league phase to show (see build_cup_html.py for the
league_phase_knockout equivalent that does need one).
"""
import html as html_lib
import json
import os
import re
import sys
from datetime import date

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DIR)
from render_nav import nav_entries, render_nav_html
from sim_copa import ROUND_ORDER, _stage, build_played_ties

STAGE_TITLES = {
    "preliminary": "Preliminary Round", "round_1": "Round 1", "round_2": "Round 2",
    "round_3": "Round 3", "round_of_16": "Round of 16", "quarterfinal": "Quarterfinals",
    "semifinal": "Semifinal", "final": "Final",
}


def _group_ties(knockout_fixtures):
    """{stage: {frozenset(pair): [legs sorted by date]}} -- same grouping
    convention as build_cup_html.py's _group_ties, over Copa's 8 stages
    instead of 4."""
    grouped = {}
    for fx in knockout_fixtures:
        stage = _stage(fx["round"])
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


def _tie_card_html(stage, pair, legs, decided, snapshot):
    lines = ['<div class="bm">']
    for fx in legs:
        lines.append(_leg_row_html(fx, snapshot))
    winner = decided.get((stage, pair))
    if winner:
        lines.append(f'<div class="bm-pct"><strong>Advances: {html_lib.escape(winner)}</strong></div>')
    lines.append('</div>')
    return "\n".join(lines)


def build_bracket_html(knockout_fixtures, snapshot):
    if not knockout_fixtures:
        return '<div class="empty-note">Draw not released yet.</div>'
    ties = _group_ties(knockout_fixtures)
    decided = build_played_ties(knockout_fixtures)
    lines = ['<div class="bracket-wrap"><div class="bracket">']
    for stage in ROUND_ORDER:
        if stage not in ties:
            continue
        lines.append(f'<div class="br-col"><div class="br-title">{STAGE_TITLES[stage]}</div><div class="br-matches">')
        for pair, legs in ties[stage].items():
            lines.append(_tie_card_html(stage, pair, legs, decided, snapshot))
        lines.append('</div></div>')
    lines.append('</div></div>')
    return "\n".join(lines)


def build_odds_rows_html(stage_odds):
    if not stage_odds:
        return '<tr><td colspan="5" class="empty-note">No simulation yet — draw may not be released.</td></tr>'
    contenders = [(t, o) for t, o in stage_odds.items() if o["champion"] > 0.0]
    eliminated = len(stage_odds) - len(contenders)
    rows = sorted(contenders, key=lambda kv: -kv[1]["champion"])
    lines = []
    for team, odds in rows:
        t = html_lib.escape(team)
        lines.append(
            f'<tr><td>{t}</td>'
            f'<td class="odds">{odds.get("quarterfinal", 0.0):.1%}</td>'
            f'<td class="odds">{odds.get("semifinal", 0.0):.1%}</td>'
            f'<td class="odds">{odds.get("final", 0.0):.1%}</td>'
            f'<td class="odds">{odds["champion"]:.1%}</td></tr>'
        )
    if eliminated:
        lines.append(f'<tr><td colspan="5" class="empty-note">{eliminated} eliminated team(s) hidden.</td></tr>')
    return "\n".join(lines)


def build_champion_html(stage_odds):
    if not stage_odds:
        return ""
    leader, odds = max(stage_odds.items(), key=lambda kv: kv[1]["champion"])
    if odds["champion"] == 0.0:
        return ""
    team = html_lib.escape(leader)
    return (
        '<div class="champ-line">Current title-odds leader: '
        f'<strong>{team}</strong> ({odds["champion"]:.1%})</div>'
    )


def build_copa_html(config, base_dir, template_path, n_sims=10000):
    from competition_config import artifact_dir
    out_dir = artifact_dir(config, base_dir)

    ko_path = os.path.join(out_dir, "knockout_fixtures.json")
    knockout_fixtures = []
    if os.path.exists(ko_path):
        with open(ko_path) as f:
            knockout_fixtures = json.load(f)

    sim_path = os.path.join(out_dir, "copa_sim.json")
    stage_odds = {}
    if os.path.exists(sim_path):
        with open(sim_path) as f:
            stage_odds = json.load(f)

    snapshot_path = os.path.join(out_dir, "predictions_snapshot.json")
    snapshot = json.load(open(snapshot_path)) if os.path.exists(snapshot_path) else {}

    nav_html = render_nav_html(nav_entries(base_dir, active=config.slug))

    with open(template_path, encoding="utf-8") as f:
        page = f.read()
    page = page.replace("__NAV__", nav_html)
    page = page.replace("__COMPETITION_NAME__", html_lib.escape(config.name))
    page = page.replace("__GENERATED_DATE__", date.today().isoformat())
    page = page.replace("__N_SIMS__", str(n_sims))
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
        print("usage: python build_copa_html.py competitions/<slug>.json")
        raise SystemExit(1)
    from competition_config import load_competition
    config = load_competition(sys.argv[1])
    base_dir = os.path.dirname(os.path.abspath(__file__))
    template_path = os.path.join(base_dir, "copa_template.html")
    out_path = build_copa_html(config, base_dir, template_path)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
