"""
Fetch, parse, and write per-competition artifacts for a league_phase_knockout
competition (UEFA Champions League / Europa League's format: a partial
round-robin "league phase", then two-legged playoffs for 9th-24th, then a
two-legged knockout bracket to a single-match Final).

Deliberately a separate script from fetch_league.py rather than a shared one:
the *parsing* (openfootball_txt.py) and the *fit* (fit_league.py) are fully
reused unmodified, but the SHAPE of what needs writing out is genuinely
different here — a round-robin league has one flat schedule; this format has
a league-phase table PLUS a knockout side that needs its ties leg-paired
before anything downstream can use it. Splitting stage-classification out of
fetch_league.py's build_schedule() would have forced round-robin's simpler
case to carry knockout-stage concepts it will never need.

Usage: python fetch_cup.py competitions/<slug>.json
"""
import json
import os
import re
import sys

import requests

from competition_config import artifact_dir, load_competition
from fetch_league import fetch_openfootball_file
from fetch_live_scores import API_KEY_ENV, BASE
from fetch_live_scores import fetch_matches as fetch_live_matches
from fetch_live_scores import overlay_live_results
from openfootball_txt import parse_openfootball_txt

_COUNTRY_SUFFIX_RE = re.compile(r'\s*\([A-Z]{3}\)$')


def strip_country_suffix(raw_name):
    """openfootball's cross-country cup files suffix every team with its
    federation's 3-letter code ("Real Madrid CF (ESP)") -- round-robin
    domestic leagues never need this since every team there is already
    unambiguous within one country. Stripped before alias resolution so
    competitions/<slug>.json doesn't need a manual alias entry for all
    36+ teams, only for genuine spelling variants."""
    return _COUNTRY_SUFFIX_RE.sub('', raw_name)


_BARE_KNOCKOUT_ROUND_NAMES = {"Round of 16", "Quarterfinals", "Semifinals", "Final"}


def classify_stage(round_label):
    """"League, Matchday N" / "League phase" -> "league"; "Playoffs, ..." ->
    "playoff"; "Finals, ..." -> "final". Matched by prefix, not exact string,
    since openfootball itself isn't consistent about the matchday suffix
    (confirmed live: 2025-26 UCL says "League, Matchday 1"; 2024-25 UEL says
    just "League phase", no per-matchday label at all).

    Also treats the bare round names "Round of 16"/"Quarterfinals"/
    "Semifinals"/"Final" as "final" even with no "Finals," prefix -- a real,
    live gap this same live-data check caught: 2024-25's el.txt labels the
    knockout bracket with no prefix at all (just "▪ Quarterfinals", etc.),
    unlike 2025-26's cl.txt ("▪ Finals, Quarterfinals"). Without this, every
    Round-of-16-onward match in that file was silently excluded (same
    "unrecognised label -> skipped" fallback as any other stray heading, but
    wrong here since these genuinely are knockout fixtures).

    Returns None for a truly unrecognised label (e.g. a qualifying-round
    file pointed at by mistake) so the caller skips it rather than
    misclassifying it."""
    if not round_label:
        return None
    if round_label.startswith("League"):
        return "league"
    if round_label.startswith("Playoffs"):
        return "playoff"
    if round_label.startswith("Finals") or round_label in _BARE_KNOCKOUT_ROUND_NAMES:
        return "final"
    return None


def _resolve(config, raw_name):
    return config.resolve_team(strip_country_suffix(raw_name))


# football-data.org stage -> the openfootball round label the rest of the pipeline reads
# (classify_stage() here, sim_cup._bracket_round() and the lock keys downstream).
_FD_STAGE_LABELS = {"PLAYOFFS": "Playoffs", "LAST_16": "Finals, Round of 16",
                    "QUARTER_FINALS": "Finals, Quarterfinals", "SEMI_FINALS": "Finals, Semifinals",
                    "FINAL": "Finals, Final"}


def football_data_match(m):
    """One football-data.org match as the dict parse_openfootball_txt() returns
    ({round, date, home, away, score, pen_score}), so the build_* functions below take either
    source unchanged. None for a slot whose teams aren't known yet (a knockout fixture before
    its draw) or a stage this pipeline doesn't model. Only a FINISHED match gets a score: the
    true final score including extra time, with a shoot-out kept apart in pen_score
    (football-data.org's fullTime may count shoot-out goals, so a shoot-out match is
    regulation + extra time instead)."""
    if m.get("stage") == "LEAGUE_STAGE":
        label = f"League, Matchday {m['matchday']}" if m.get("matchday") else "League phase"
    else:
        label = _FD_STAGE_LABELS.get(m.get("stage"))
    home, away = (m.get("homeTeam") or {}).get("name"), (m.get("awayTeam") or {}).get("name")
    if not label or not home or not away:
        return None
    match = {"round": label, "date": m["utcDate"][:10], "home": home, "away": away, "score": None}
    sc = m.get("score") or {}
    full = sc.get("fullTime") or {}
    if m.get("status") == "FINISHED" and full.get("home") is not None:
        pens = sc.get("penalties") if sc.get("duration") == "PENALTY_SHOOTOUT" else None
        reg, extra = sc.get("regularTime") or {}, sc.get("extraTime") or {}
        if pens and reg.get("home") is not None:
            full = {side: reg[side] + (extra.get(side) or 0) for side in ("home", "away")}
        match["score"] = (full["home"], full["away"])
        if pens:
            match["pen_score"] = (pens["home"], pens["away"])
    return match


def fetch_football_data_season(code, season, timeout=30):
    """Every match of one football-data.org season, as football_data_match() dicts in date
    order. Unlike fetch_live_scores.fetch_matches (an optional overlay that shrugs failures
    off) this IS the data source, so a missing key or a failed request raises
    requests.RequestException and fetch_and_save aborts loudly."""
    api_key = os.environ.get(API_KEY_ENV, "")
    if not api_key:
        raise requests.RequestException(f"{API_KEY_ENV} not set")
    resp = requests.get(f"{BASE}/competitions/{code}/matches", params={"season": season},
                        headers={"X-Auth-Token": api_key}, timeout=timeout)
    resp.raise_for_status()
    matches = (football_data_match(m) for m in resp.json().get("matches", []))
    return sorted((m for m in matches if m), key=lambda m: m["date"])


def build_training_rows(config, parsed_matches):
    """Training rows [date, home, away, hg, ag, label, neutral] from every
    PLAYED match regardless of stage -- unlike fit_improved.py's WC-specific
    WC_2026_MULTIPLIER (needed there to make live tournament evidence
    outweigh diluting friendlies/qualifiers), every match here is a genuine
    competitive fixture at similar intensity, so no stage-based reweighting
    is needed; fit_league.py's existing recency half-life already gives
    current-season matches more influence than older ones. Returns
    (rows, n_skipped)."""
    rows, n_skipped = [], 0
    for m in parsed_matches:
        if m["score"] is None or classify_stage(m["round"]) is None:
            continue
        home, away = _resolve(config, m["home"]), _resolve(config, m["away"])
        if not home or not away:
            print(f"    ! unmapped team name(s): {m['home']!r} / {m['away']!r} — skipped")
            n_skipped += 1
            continue
        hg, ag = m["score"]
        rows.append([m["date"], home, away, hg, ag, config.name, False])
    return rows, n_skipped


def build_league_schedule(config, parsed_matches):
    """League-phase-only fixtures from one season, in the exact shape
    sim_league.compute_standings_and_remaining() expects: {"home|away":
    {date, status, goals, round}}. A directed key is safe here (unlike a
    domestic league's double round-robin) since the league phase draw pairs
    any two teams at most once. Returns (schedule, n_skipped)."""
    sched, n_skipped = {}, 0
    for m in parsed_matches:
        if classify_stage(m["round"]) != "league":
            continue
        home, away = _resolve(config, m["home"]), _resolve(config, m["away"])
        if not home or not away:
            n_skipped += 1
            continue
        if m["score"] is not None:
            status, goals = "FINISHED", {home: m["score"][0], away: m["score"][1]}
        else:
            status, goals = "SCHEDULED", {home: None, away: None}
        sched[f"{home}|{away}"] = {
            "date": m["date"], "status": status, "goals": goals, "round": m["round"],
        }
    return sched, n_skipped


def build_knockout_fixtures(config, parsed_matches):
    """Playoff + Finals matches from one season, as a flat chronological
    list: {round, date, home, away, score, pen_score}. Deliberately NOT
    leg-paired or aggregated here -- pairing two legs into one tie is a
    knockout-bracket concept that belongs to sim_cup.py (which already has
    to know the bracket topology to seed the playoff round and advance
    winners), not to this fetch/normalise layer. Returns (fixtures, n_skipped)."""
    fixtures, n_skipped = [], 0
    for m in parsed_matches:
        stage = classify_stage(m["round"])
        if stage not in ("playoff", "final"):
            continue
        home, away = _resolve(config, m["home"]), _resolve(config, m["away"])
        if not home or not away:
            n_skipped += 1
            continue
        fixtures.append({
            "round": m["round"], "date": m["date"], "home": home, "away": away,
            "score": list(m["score"]) if m["score"] is not None else None,
            "pen_score": list(m["pen_score"]) if m.get("pen_score") is not None else None,
        })
    return fixtures, n_skipped


def fetch_and_save(config, base_dir):
    """Fetch every configured season (newest first -- football-data.org's
    `football_data_seasons`, then openfootball's files), parse each, and write:
      competitions/<slug>/fetched_matches.json   -- training rows from every
        played match in every configured season (any stage)
      competitions/<slug>/league_schedule.json   -- newest season's
        league-phase fixtures only, played + unplayed
      competitions/<slug>/knockout_fixtures.json -- newest season's
        playoff + final fixtures only, played + unplayed, leg-pairing left
        to sim_cup.py

    league_schedule.json/knockout_fixtures.json are left UNTOUCHED if the
    newest season's fetch fails -- same reasoning as fetch_league.py: a
    transient failure must never wipe a good live artifact to empty.

    Returns a summary dict, same shape as fetch_league.fetch_and_save's."""
    out_dir = artifact_dir(config, base_dir)
    all_rows, current_league_sched, current_ko_fixtures = [], {}, []
    total_skipped, failed = 0, []
    current_season_failed = False

    # Newest first, as ever: the config's football-data.org seasons (if any), then openfootball's.
    sources = [(f"football-data.org {config.football_data_code} {year}",
                lambda year=year: fetch_football_data_season(config.football_data_code, year))
               for year in config.football_data_seasons]
    sources += [(entry["path"],
                 lambda path=entry["path"]: parse_openfootball_txt(
                     fetch_openfootball_file(config.openfootball_repo, path)))
                for entry in config.openfootball_files]

    for i, (label, load) in enumerate(sources):
        try:
            parsed = load()
        except requests.RequestException as e:
            print(f"  ! failed to fetch {label}: {e}")
            failed.append(label)
            if i == 0:
                current_season_failed = True
            continue
        rows, n_skipped = build_training_rows(config, parsed)
        all_rows.extend(rows)
        total_skipped += n_skipped
        if i == 0:
            current_league_sched, sk1 = build_league_schedule(config, parsed)
            current_ko_fixtures, sk2 = build_knockout_fixtures(config, parsed)
            total_skipped += sk1 + sk2

    with open(os.path.join(out_dir, "fetched_matches.json"), "w") as f:
        json.dump(all_rows, f, indent=2)

    if current_season_failed:
        print("  ! current-season fetch failed — leaving existing league_schedule.json "
              "/ knockout_fixtures.json untouched")
    else:
        if config.football_data_code and not config.football_data_seasons:
            # (Skipped when football-data.org already IS the current season's source.)
            # Only the league phase is a home|away-keyed schedule dict --
            # knockout_fixtures.json is a flat leg list (see its own
            # docstring above) and isn't in scope for this overlay.
            raw = fetch_live_matches(config.football_data_code)
            if raw:
                _, n_overlaid, n_date_corrected, _ = overlay_live_results(config, current_league_sched, raw)
                if n_overlaid or n_date_corrected:
                    print(f"  live-score overlay: {n_overlaid} result(s), "
                          f"{n_date_corrected} date correction(s) from football-data.org")
        with open(os.path.join(out_dir, "league_schedule.json"), "w") as f:
            json.dump(current_league_sched, f, indent=2)
        with open(os.path.join(out_dir, "knockout_fixtures.json"), "w") as f:
            json.dump(current_ko_fixtures, f, indent=2)

    return {"matches": len(all_rows), "league_scheduled": len(current_league_sched),
            "knockout_fixtures": len(current_ko_fixtures), "skipped": total_skipped,
            "failed_seasons": failed, "current_season_failed": current_season_failed}


def main():
    if len(sys.argv) != 2:
        print("usage: python fetch_cup.py competitions/<slug>.json")
        raise SystemExit(1)
    config = load_competition(sys.argv[1])
    base_dir = os.path.dirname(os.path.abspath(__file__))
    summary = fetch_and_save(config, base_dir)
    print(f"{config.name}: {summary['matches']} training rows, "
          f"{summary['league_scheduled']} current-season league-phase fixtures, "
          f"{summary['knockout_fixtures']} current-season knockout fixtures, "
          f"{summary['skipped']} skipped, "
          f"{len(summary['failed_seasons'])} season(s) failed to fetch.")
    if summary["current_season_failed"]:
        print("FATAL: current-season fetch failed — aborting so CI surfaces this loudly "
              "instead of silently leaving stale (but intact) artifacts in place.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
