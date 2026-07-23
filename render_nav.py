"""
Shared top-nav generator, injected into every page on the site (the hub,
the World Cup page, and every round-robin competition page) so a visitor
can jump between competitions from anywhere — the CNN Sport / Guardian
Sport pattern: a persistent row of competition tabs, each a real link to
that competition's own static page.

The league tabs are discovered dynamically via list_competitions.py rather
than hand-listed here, so adding Copa del Rey/Champions League/AFCON later
needs zero template edits — same "just add a config" philosophy as the rest
of this project. The World Cup and the hub itself are added as fixed extra
entries since neither has a competitions/<slug>.json config (the WC predates
that system entirely; the hub isn't a competition at all).
"""
import os

from list_competitions import list_competition_slugs


def nav_entries(base_dir, active=None):
    """List of {"label": str, "href": str, "active": bool} nav entries, in
    display order: hub first, World Cup second, then every discovered
    round-robin competition alphabetically by slug. `active` is the current
    page's identifier ("hub", "world_cup", or a competition slug) — the
    matching entry gets active=True for the caller to highlight."""
    entries = [
        {"id": "hub", "label": "xSPN", "href": "/xSPN/"},
        {"id": "world_cup", "label": "World Cup 2026", "href": "/xSPN/competitions/world_cup_2026/"},
    ]
    for slug in list_competition_slugs(base_dir):
        entries.append({
            "id": slug,
            "label": _display_name(base_dir, slug),
            "href": f"/xSPN/competitions/{slug}/",
        })
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
