"""
Renders the site's landing/hub page — one card per competition (World Cup +
every round-robin league discovered via list_competitions.py), each linking
to that competition's own page. Root now serves this page; the World Cup
moved to its own competitions/world_cup_2026/ subpath (see build_html.py).
"""
import html as html_lib
import json
import os
import re

from render_nav import nav_entries, render_nav_html


def league_snapshot(base_dir, slug):
    """One-line snapshot for a round-robin competition's hub card: current
    title-odds leader + percentage, or None if no simulation has run yet."""
    sim_path = os.path.join(base_dir, "competitions", slug, "league_sim.json")
    if not os.path.exists(sim_path):
        return None
    with open(sim_path) as f:
        rank_dist = json.load(f)
    if not rank_dist:
        return None
    leader, dist = max(rank_dist.items(), key=lambda kv: kv[1][0])
    return f"{html_lib.escape(leader)} leads at {dist[0]:.0%} to win the title"


def cup_snapshot(base_dir, slug):
    """One-line snapshot for a league_phase_knockout competition's hub card:
    current champion-odds leader + percentage, or None if no simulation has
    run yet -- the real state UCL/UEL start in (sim_cup.py needs at least
    24 teams in league_schedule.json, which won't exist until each
    competition's real league-phase draw is released)."""
    sim_path = os.path.join(base_dir, "competitions", slug, "cup_sim.json")
    if not os.path.exists(sim_path):
        return None
    with open(sim_path) as f:
        sim = json.load(f)
    stage_odds = sim.get("stage_odds") or {}
    if not stage_odds:
        return None
    leader, odds = max(stage_odds.items(), key=lambda kv: kv[1]["champion"])
    return f"{html_lib.escape(leader)} leads at {odds['champion']:.0%} to win the title"


def world_cup_snapshot(base_dir):
    """One-line snapshot for the World Cup hub card: the actual champion,
    once decided, since the tournament is over (falls back to a generic
    label if bracket_data.json is ever missing/unreadable)."""
    bracket_path = os.path.join(base_dir, "bracket_data.json")
    if not os.path.exists(bracket_path):
        return "2026 tournament predictions"
    with open(bracket_path) as f:
        bracket = json.load(f)
    champion = bracket.get("champion")
    return f"Champion: {html_lib.escape(champion)}" if champion else "2026 tournament predictions"


def build_hub_cards(base_dir):
    """One card dict per competition: {"name", "href", "snapshot"}. World
    Cup first (fixed, predates the config system entirely), then every
    discovered round-robin competition."""
    cards = [{
        "name": "World Cup 2026",
        "href": "/xSPN/competitions/world_cup_2026/",
        "snapshot": world_cup_snapshot(base_dir),
    }]
    from competition_config import load_competition
    from list_competitions import list_competition_slugs
    for slug in list_competition_slugs(base_dir):
        config = load_competition(os.path.join(base_dir, "competitions", f"{slug}.json"))
        if config.format == "league_phase_knockout":
            snapshot = cup_snapshot(base_dir, slug)
        else:
            snapshot = league_snapshot(base_dir, slug)
        cards.append({
            "name": html_lib.escape(config.name),
            "href": f"/xSPN/competitions/{slug}/",
            "snapshot": snapshot or "Season predictions",
        })
    return cards


def render_cards_html(cards):
    lines = []
    for c in cards:
        lines.append(
            f'    <a class="hub-card" href="{c["href"]}">'
            f'<div class="hub-card-name">{c["name"]}</div>'
            f'<div class="hub-card-snapshot">{c["snapshot"]}</div></a>'
        )
    return "\n".join(lines)


def build_hub_html(base_dir, template_path, out_path):
    """Load every competition's snapshot, render the hub cards + shared nav
    into `template_path`'s __PLACEHOLDER__ tokens, and write to `out_path`.
    Raises AssertionError if any __PLACEHOLDER__-shaped token survives
    substitution, same safety check as build_league_html.py."""
    cards = build_hub_cards(base_dir)
    nav_html = render_nav_html(nav_entries(base_dir, active="hub"))

    with open(template_path, encoding="utf-8") as f:
        page = f.read()
    page = page.replace("__NAV__", nav_html)
    page = page.replace("__HUB_CARDS__", render_cards_html(cards))

    leftover = re.findall(r"__[A-Z_]+__", page)
    assert not leftover, f"unconsumed placeholder(s) in output: {leftover}"

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(page)
    return out_path


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    template_path = os.path.join(base_dir, "hub_template.html")
    out_path = os.path.join(base_dir, "index.html")
    build_hub_html(base_dir, template_path, out_path)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
