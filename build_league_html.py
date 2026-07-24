"""
Renders a static Results/Bracket/Podium page for a round-robin competition,
from schedule.json (fetch_league.py), league_sim.json (sim_league.py),
predictions_snapshot.json (snapshot_league.py), and results_accuracy.json
(score_league.py). Follows the same __PLACEHOLDER__ substitution pattern as
build_html.py/template.html (this project's established convention, avoids
Python f-string escaping issues with large HTML) -- but unlike the WC page,
every pane here is rendered server-side in Python rather than client-side
JS, since nothing in a league page needs runtime recomputation.

Deliberately a separate template/script rather than extending template.html:
that template is World-Cup-specific and lives on the production GitHub Pages
site -- a new, unrelated competition's page shouldn't risk it. The two DO
deliberately share the same tab-bar/pane visual language (23 Jul restyle)
so a visitor doesn't hit a jarring style change moving between them.
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

RELEGATION_ZONE = 3  # Premier League specific; a display choice, not baked
                       # into sim_league.py (cutoffs vary by league/season)

DEFAULT_TOP_ZONE = 4  # Champions-League-style qualification (PL, La Liga, Bundesliga)
# Championship-style leagues have a SMALLER automatic-promotion count, with
# a separate playoff tier below it for the remaining spot(s) — highlighting
# all 4 rows the same as a top-flight league's European-qualification zone
# would be factually wrong, not just a simplification (a real bug found in
# the 22 Jul audit of the live Championship page, which showed 4 green rows
# when only the top 2 are actually automatically promoted). Kept here even
# though Championship itself was removed 23 Jul -- this tests the override
# *mechanism* generically, for whatever future competition needs it.
TOP_ZONE_OVERRIDES = {"Championship": 2}

_ROUND_NUM_RE = re.compile(r"(\d+)")


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


def _fmt_date(iso):
    d = date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%b %Y')}"


def season_span(schedule):
    """(display start date, display end date) spanning every fixture in the
    schedule -- the season's opening and closing matchday. (None, None) if
    the schedule is empty."""
    dates = sorted(e["date"] for e in schedule.values())
    if not dates:
        return None, None
    return _fmt_date(dates[0]), _fmt_date(dates[-1])


def build_accuracy_html(accuracy):
    """Results-tab summary cards from results_accuracy.json's "summary", or
    an empty-state note if nothing has been scored yet (correct for a
    season that hasn't started, not a bug). "Correct Winners" is counted
    directly off the match list rather than back-derived from the
    "accuracy" fraction, to avoid a rounding mismatch."""
    matches = accuracy.get("matches") or []
    summary = accuracy.get("summary") or {}
    n = summary.get("n_scored") or 0
    if not n:
        return '<div class="empty-note">No matches scored yet this season.</div>'
    correct = sum(1 for m in matches if m["correct_winner"])
    return (
        '<div class="acc-cards">'
        '<div class="acc-card"><div class="acc-lbl">Correct Winners</div>'
        f'<div class="acc-val">{correct}/{n}</div>'
        f'<div class="acc-sub">{summary["accuracy"]:.1%} accuracy</div></div>'
        '<div class="acc-card"><div class="acc-lbl">Avg Brier Score</div>'
        f'<div class="acc-val">{summary["avg_brier"]:.3f}</div>'
        '<div class="acc-sub">vs baseline 0.67</div></div>'
        '<div class="acc-card"><div class="acc-lbl">Avg Log-Loss</div>'
        f'<div class="acc-val">{summary["avg_log_loss"]:.3f}</div>'
        '<div class="acc-sub">lower is better</div></div>'
        '</div>'
    )


def build_results_rows_html(accuracy, schedule, snapshot):
    """Scored-match rows (newest first): predicted vs actual score, correct-
    winner mark, Brier. Falls back to a single empty-state row rather than
    an empty <tbody> so the table doesn't look broken before any match has
    been scored. Team names escaped (external openfootball data)."""
    matches = sorted(accuracy.get("matches") or [], key=lambda m: m["date"], reverse=True)
    if not matches:
        return '<tr><td colspan="6" class="empty-note">No matches scored yet this season.</td></tr>'
    lines = []
    for m in matches:
        key = f"{m['home']}|{m['away']}"
        goals = schedule.get(key, {}).get("goals", {})
        actual = f"{goals.get(m['home'])}-{goals.get(m['away'])}"
        predicted = snapshot.get(key, {}).get("predicted_score", "—")
        mark = ('<span class="res-ok">&#10003;</span>' if m["correct_winner"]
                else '<span class="res-err">&#10007;</span>')
        home, away = html_lib.escape(m["home"]), html_lib.escape(m["away"])
        lines.append(
            f'<tr><td class="hint">{m["date"]}</td>'
            f'<td>{home} <span class="hint">vs</span> {away}</td>'
            f'<td class="center hint">{predicted}</td>'
            f'<td class="center strong">{actual}</td>'
            f'<td class="center">{mark}</td>'
            f'<td class="center hint">{m["brier"]:.3f}</td></tr>'
        )
    return "\n".join(lines)


def _round_sort_key(round_label):
    """Numeric sort key from a "Matchday N" label -- lexical sort would put
    "Matchday 10" before "Matchday 2"."""
    m = _ROUND_NUM_RE.search(round_label or "")
    return int(m.group(1)) if m else 0


def build_bracket_html(schedule, snapshot):
    """Every fixture grouped into a bracket-styled column per round/
    matchday (sorted numerically), each match card showing its date and
    either the actual score (once FINISHED), the locked prediction (once
    due), or an "unplayed" placeholder."""
    by_round = {}
    for key, entry in schedule.items():
        by_round.setdefault(entry.get("round") or "Unscheduled", []).append((key, entry))

    lines = ['<div class="bracket-wrap"><div class="bracket">']
    for round_label in sorted(by_round, key=_round_sort_key):
        lines.append(
            f'<div class="br-col"><div class="br-title">{html_lib.escape(round_label)}</div>'
            '<div class="br-matches">'
        )
        for key, entry in sorted(by_round[round_label], key=lambda kv: kv[1]["date"]):
            home, away = key.split("|")
            h, a = html_lib.escape(home), html_lib.escape(away)
            date_line = f'<div class="bm-date">{entry["date"]}</div>'
            if entry["status"] == "FINISHED":
                hg, ag = entry["goals"][home], entry["goals"][away]
                home_cls = "win" if hg > ag else ("lose" if hg < ag else "")
                away_cls = "win" if ag > hg else ("lose" if ag < hg else "")
                lines.append(
                    f'<div class="bm">{date_line}'
                    f'<div class="bm-t {home_cls}">{h}<span class="bm-sc">{hg}</span></div>'
                    f'<div class="bm-t {away_cls}">{a}<span class="bm-sc">{ag}</span></div></div>'
                )
            elif key in snapshot:
                s = snapshot[key]
                lines.append(
                    f'<div class="bm">{date_line}'
                    f'<div class="bm-t">{h}</div><div class="bm-t">{a}</div>'
                    f'<div class="bm-pct">{s["predicted_score"]} &middot; {s["predicted_winner"]}</div></div>'
                )
            else:
                lines.append(
                    f'<div class="bm">{date_line}<div class="bm-t">{h}</div><div class="bm-t">{a}</div>'
                    '<div class="bm-pct hint">not yet predicted</div></div>'
                )
        lines.append('</div></div>')
    lines.append('</div></div>')
    return "\n".join(lines)


def build_champion_html(rows):
    """Podium-tab callout: the model's current title-odds leader, mirroring
    the WC podium's "Predicted Tournament Winner" -- picked by title_pct,
    NOT standings position (early season, real points and title odds can
    disagree, e.g. a slow starter the model still rates highest)."""
    if not rows:
        return ""
    leader = max(rows, key=lambda r: r["title_pct"])
    team = html_lib.escape(leader["team"])
    return (
        '<div class="champ-line">Predicted champion: '
        f'<strong>{team}</strong> ({leader["title_pct"]:.1%} title odds)</div>'
    )


def build_league_html(config, base_dir, template_path, relegation_zone=RELEGATION_ZONE,
                        n_sims=10000):
    """Load <slug>/schedule.json + league_sim.json (+ optional
    predictions_snapshot.json / results_accuracy.json), render the
    Results/Bracket/Podium panes into `template_path`'s __PLACEHOLDER__
    tokens, and write <slug>/index.html. Raises AssertionError if any
    __PLACEHOLDER__-shaped token survives substitution — the WC's
    build_html.py has no such check (flagged by the 22 Jul audit as a gap);
    this module adds it from the start rather than repeating the omission."""
    from competition_config import artifact_dir
    out_dir = artifact_dir(config, base_dir)

    with open(os.path.join(out_dir, "schedule.json")) as f:
        schedule = json.load(f)
    sim_path = os.path.join(out_dir, "league_sim.json")
    if not os.path.exists(sim_path):
        raise FileNotFoundError(f"{sim_path} not found — run sim_league.py first")
    with open(sim_path) as f:
        rank_dist = json.load(f)

    snapshot_path = os.path.join(out_dir, "predictions_snapshot.json")
    snapshot = json.load(open(snapshot_path)) if os.path.exists(snapshot_path) else {}
    accuracy_path = os.path.join(out_dir, "results_accuracy.json")
    accuracy = json.load(open(accuracy_path)) if os.path.exists(accuracy_path) else {}

    rows = build_standings_rows(schedule, rank_dist, relegation_zone)
    rows_html = render_rows_html(rows)
    top_zone = top_zone_for(config.name)
    nav_html = render_nav_html(nav_entries(base_dir, active=config.slug))
    season_start, season_end = season_span(schedule)

    with open(template_path, encoding="utf-8") as f:
        page = f.read()
    page = page.replace("__NAV__", nav_html)
    page = page.replace("__COMPETITION_NAME__", html_lib.escape(config.name))
    page = page.replace("__GENERATED_DATE__", date.today().isoformat())
    page = page.replace("__N_SIMS__", str(n_sims))
    page = page.replace("__RELEGATION_ZONE__", str(relegation_zone))
    page = page.replace("__TOP_ZONE__", str(top_zone))
    page = page.replace("__STANDINGS_ROWS__", rows_html)
    page = page.replace("__SEASON_START__", season_start or "TBD")
    page = page.replace("__SEASON_END__", season_end or "TBD")
    page = page.replace("__ACCURACY_CARDS__", build_accuracy_html(accuracy))
    page = page.replace("__RESULTS_ROWS__", build_results_rows_html(accuracy, schedule, snapshot))
    page = page.replace("__BRACKET_HTML__", build_bracket_html(schedule, snapshot))
    page = page.replace("__CHAMPION_LINE__", build_champion_html(rows))

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
