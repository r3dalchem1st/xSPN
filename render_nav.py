"""
Shared top-nav generator, injected into every page on the site (the hub,
the World Cup page, and every round-robin competition page) so a visitor
can jump between competitions from anywhere — the CNN Sport / Guardian
Sport pattern: a persistent row of competition tabs, each a real link to
that competition's own static page.

The league tabs are discovered dynamically via list_competitions.py rather
than hand-listed here, so adding a new competition's config never requires
a template edit. Display ORDER, though, is an explicit hand-picked list
(NAV_ORDER, direct 24 Jul reorder request) rather than purely derived from
season-start date: that heuristic broke down once a competition's "season"
could be a placeholder historical one (Champions League currently trains
on 2025-26 real data, which sorted it before every 2026-27 league by date
despite the user wanting it after Bundesliga). A competition not yet in
NAV_ORDER (newly onboarded, e.g. Copa del Rey/AFCON later) is appended
after every named entry, ordered by season start among themselves — so
onboarding still needs no nav edit, it just won't get a hand-picked
position until someone adds it to NAV_ORDER. The hub itself is always
first and outside this ordering entirely (it isn't a competition).
"""
import json
import os

from list_competitions import list_competition_slugs

NAV_ORDER = ["la_liga", "premier_league", "bundesliga", "champions_league", "world_cup"]


def _season_start(base_dir, slug):
    """A competition's earliest fixture date, ISO-formatted so string
    comparison sorts chronologically. Ordering the league tabs by season
    start (La Liga mid-Aug, Premier League a week later, Bundesliga late
    Aug) reads correctly to a visitor; alphabetical-by-slug doesn't (it
    happened to put Bundesliga first, the last of the three to kick off).
    Falls back to a date far in the future — sorting a not-yet-fetched
    competition (no schedule.json yet) last, not first — rather than
    letting a missing file crash the whole nav bar for every competition.

    Tries "schedule.json" (round_robin) first, then "league_schedule.json"
    (league_phase_knockout) — without this fallback, every cup competition
    would silently sort last forever (wrong filename, not "not fetched
    yet"), never reflecting its real season start once fetched."""
    comp_dir = os.path.join(base_dir, "competitions", slug)
    for filename in ("schedule.json", "league_schedule.json"):
        try:
            with open(os.path.join(comp_dir, filename)) as f:
                schedule = json.load(f)
            dates = [e["date"] for e in schedule.values() if e.get("date")]
            if dates:
                return min(dates)
        except (FileNotFoundError, ValueError, KeyError):
            continue
    return "9999-99-99"


def nav_entries(base_dir, active=None):
    """List of {"label": str, "href": str, "active": bool} nav entries. Hub
    is always first; every other entry (World Cup + every discovered
    competition) is ordered by NAV_ORDER, with anything not on that list
    appended after, sorted by season start among themselves. `active` is
    the current page's identifier ("hub", "world_cup", or a competition
    slug) — the matching entry gets active=True for the caller to
    highlight."""
    hub = {"id": "hub", "label": "xSPN", "href": "/xSPN/"}
    world_cup = {"id": "world_cup", "label": "World Cup 2026", "href": "/xSPN/competitions/world_cup_2026/"}
    discovered = [
        {"id": slug, "label": _display_name(base_dir, slug), "href": f"/xSPN/competitions/{slug}/"}
        for slug in list_competition_slugs(base_dir)
    ]
    rest = [world_cup] + discovered
    named = sorted((e for e in rest if e["id"] in NAV_ORDER), key=lambda e: NAV_ORDER.index(e["id"]))
    unnamed = sorted((e for e in rest if e["id"] not in NAV_ORDER), key=lambda e: _season_start(base_dir, e["id"]))
    entries = [hub] + named + unnamed
    for e in entries:
        e["active"] = (e["id"] == active)
        del e["id"]
    return entries


def _display_name(base_dir, slug):
    """Competition display name from its config, falling back to the slug
    itself if the config can't be read (never let a malformed config break
    the whole nav bar for every OTHER competition)."""
    try:
        from competition_config import load_competition
        config = load_competition(os.path.join(base_dir, "competitions", f"{slug}.json"))
        return config.name
    except (FileNotFoundError, ValueError):
        return slug


def render_nav_html(entries):
    """Nav entries -> a <nav> HTML fragment. The active entry gets
    class="active" for the caller's CSS to style; every entry is a real
    <a href> (no JavaScript routing)."""
    links = []
    for e in entries:
        cls = ' class="active"' if e["active"] else ""
        links.append(f'<a href="{e["href"]}"{cls}>{e["label"]}</a>')
    return '<nav class="xspn-nav">' + "".join(links) + '</nav>'
