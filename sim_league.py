"""
Season Monte Carlo simulation for round-robin competitions.

Simulates a season's remaining (SCHEDULED) fixtures many times using the
Dixon-Coles bootstrap ensemble from fit_league.py, holding already-played
(FINISHED) results fixed, to produce a full rank-distribution per team —
not a single "top-4"/"relegation-zone" cutoff, since which positions matter
(European qualification slots, relegation-zone size, playoff spots) varies
by league and by season; that's left to the caller.

Deliberately self-contained rather than importing model_common.py's
build_lambda_table(): that function hardcodes the World Cup's ALL_TEAMS/
HOST_NATIONS/squad_adj — round-robin needs a plain, team-list-agnostic
version with none of that. (model_common.py's H/D/A Poisson helpers ARE
already team-list-agnostic, but this module doesn't need them either — it
samples full scorelines directly via Poisson draws for the season simulation
rather than needing normalised H/D/A triples.)
"""
import json
import math
import os
import sys

import numpy as np


def _poisson(lam, rng):
    """Knuth's algorithm: count uniform draws until their product drops
    below exp(-lam). Fine for the small lambda values (~0.5-3) typical of
    football scoring rates."""
    l = math.exp(-lam)
    k = 0
    p = 1.0
    while True:
        p *= rng.random()
        if p <= l:
            return k
        k += 1


def build_lambda_table(teams, dc):
    """(lam, mu) for every ordered pair of `teams`, from one Dixon-Coles
    parameter set (attack/defense/home_adv — the dict shape fit_league.fit_dc
    returns). A team absent from the fit (newly promoted, no match history
    in the training window — this happens every season, not an edge case)
    defaults to attack=0.0, defense=0.0, a neutral league-average prior.
    NOT calibrated against real promoted-team performance (no backtest
    infrastructure exists yet for round-robin competitions) — a known,
    documented limitation, not a guess dressed up as a real adjustment."""
    atk, dfn, home_adv = dc["attack"], dc["defense"], dc["home_adv"]
    lg = {}
    for home in teams:
        for away in teams:
            if home == away:
                continue
            ah, dh = atk.get(home, 0.0), dfn.get(home, 0.0)
            aa, da = atk.get(away, 0.0), dfn.get(away, 0.0)
            lam = math.exp(ah + da + home_adv)
            mu = math.exp(aa + dh)
            lg[(home, away)] = (lam, mu)
    return lg


def build_lambda_tables(teams, dc_ensemble):
    """One lambda table per bootstrap-ensemble member."""
    return [build_lambda_table(teams, dc) for dc in dc_ensemble]


def simulate_season(teams, standings, remaining_fixtures, dc_ensemble, n_sims=10000, seed=42):
    """Monte Carlo the season's remaining fixtures `n_sims` times. Each
    simulated season draws a random bootstrap-ensemble member (propagating
    parameter uncertainty, same method as sim_improved.py's WC simulator),
    samples every remaining fixture's score via independent Poisson draws
    (no draw-inflation — that's a World-Cup-specific calibration against
    international-match draw rates, unvalidated for round-robin so left
    off rather than guessed at), and starts from the fixed already-played
    standings. Returns {team: [rank_1_pct, rank_2_pct, ..., rank_N_pct]} —
    the fraction of simulated seasons in which that team finished at each
    exact position (index 0 = 1st place) — so ANY cutoff (top-4, relegation
    zone, a playoff spot) can be computed by the caller by summing the
    relevant slice; this module doesn't hardcode any competition's specific
    cutoff rules, since those vary by league and by season."""
    lg_ens = build_lambda_tables(teams, dc_ensemble)
    rng = np.random.default_rng(seed)
    n_teams = len(teams)
    rank_counts = {t: [0] * n_teams for t in teams}

    for _ in range(n_sims):
        lg = lg_ens[rng.integers(len(lg_ens))]
        table = {t: dict(standings.get(t, {"pts": 0, "gd": 0, "gf": 0})) for t in teams}
        for home, away in remaining_fixtures:
            lam, mu = lg[(home, away)]
            hg = _poisson(lam, rng)
            ag = _poisson(mu, rng)
            table[home]["gf"] += hg; table[home]["gd"] += hg - ag
            table[away]["gf"] += ag; table[away]["gd"] += ag - hg
            if hg > ag: table[home]["pts"] += 3
            elif ag > hg: table[away]["pts"] += 3
            else: table[home]["pts"] += 1; table[away]["pts"] += 1
        order = sorted(teams, key=lambda t: (table[t]["pts"], table[t]["gd"], table[t]["gf"]), reverse=True)
        for rank, t in enumerate(order):
            rank_counts[t][rank] += 1

    return {t: [c / n_sims for c in counts] for t, counts in rank_counts.items()}


def compute_standings_and_remaining(schedule):
    """From a fetch_league.py-produced schedule.json (keyed by directed pair
    "home|away"), split into (standings, remaining_fixtures, teams):
    standings from FINISHED entries only ({team: {"pts","gd","gf"}}, teams
    with zero finished matches simply aren't keys yet — callers should use
    .get(team, {"pts":0,"gd":0,"gf":0})), remaining_fixtures as a list of
    (home, away) tuples from SCHEDULED entries, and the full team list
    (union of every team appearing in the schedule)."""
    standings = {}
    remaining = []
    teams = set()
    for key, entry in schedule.items():
        home, away = key.split("|")
        teams.add(home); teams.add(away)
        if entry["status"] == "FINISHED":
            hg, ag = entry["goals"][home], entry["goals"][away]
            for t in (home, away):
                standings.setdefault(t, {"pts": 0, "gd": 0, "gf": 0})
            standings[home]["gf"] += hg; standings[home]["gd"] += hg - ag
            standings[away]["gf"] += ag; standings[away]["gd"] += ag - hg
            if hg > ag: standings[home]["pts"] += 3
            elif ag > hg: standings[away]["pts"] += 3
            else: standings[home]["pts"] += 1; standings[away]["pts"] += 1
        elif entry["status"] == "SCHEDULED":
            remaining.append((home, away))
    return standings, remaining, sorted(teams)


def simulate_and_save(config, base_dir, n_sims=10000, seed=42):
    """Load <slug>/schedule.json and <slug>/dc_ensemble.json, run the season
    Monte Carlo, and write <slug>/league_sim.json: {team: [rank_pct,...]}
    (index 0 = 1st place). Requires fetch_league.py (schedule.json) and
    fit_league.py (dc_ensemble.json) to have already run. Returns the
    rank-distribution dict."""
    from competition_config import artifact_dir
    out_dir = artifact_dir(config, base_dir)

    schedule_path = os.path.join(out_dir, "schedule.json")
    with open(schedule_path) as f:
        schedule = json.load(f)

    ensemble_path = os.path.join(out_dir, "dc_ensemble.json")
    if not os.path.exists(ensemble_path):
        raise FileNotFoundError(f"{ensemble_path} not found — run fit_league.py first")
    with open(ensemble_path) as f:
        dc_ensemble = json.load(f)

    standings, remaining, teams = compute_standings_and_remaining(schedule)
    if not remaining:
        raise ValueError(f"{config.slug}: no SCHEDULED fixtures in {schedule_path} — "
                          f"nothing to simulate (season may be complete, or "
                          f"fetch_league.py hasn't run yet)")

    rank_dist = simulate_season(teams, standings, remaining, dc_ensemble, n_sims=n_sims, seed=seed)

    with open(os.path.join(out_dir, "league_sim.json"), "w") as f:
        json.dump(rank_dist, f, indent=2)
    return rank_dist


def main():
    if len(sys.argv) != 2:
        print("usage: python sim_league.py competitions/<slug>.json")
        raise SystemExit(1)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from competition_config import load_competition
    config = load_competition(sys.argv[1])
    base_dir = os.path.dirname(os.path.abspath(__file__))
    rank_dist = simulate_and_save(config, base_dir)
    title_odds = sorted(((t, dist[0]) for t, dist in rank_dist.items()), key=lambda x: -x[1])[:5]
    print(f"{config.name}: simulated {len(rank_dist)} teams")
    print("Top 5 title odds:")
    for t, p in title_odds:
        print(f"  {t:<28} {p:.1%}")


if __name__ == "__main__":
    main()
