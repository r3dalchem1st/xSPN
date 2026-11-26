"""
Validate the season simulation (the title / top-4 / relegation odds on every
league page) against how real seasons turned out.

The match-level model has been backtested; the Monte Carlo built on top of it
never was, though the title odds are arguably the site's most visible number.

METHOD: replay each past season from a checkpoint -- before any match, a
quarter of the way, halfway -- treating the rest of the REAL fixture list as
unplayed. Fit on only what was knowable then (previous 3 seasons + matches
played), build a bootstrap ensemble, simulate with the production
sim_league.simulate_season, and score each team's title / top-4 / relegation
probability against the real final table (points, goal difference, goals for,
the same tie-break the simulator uses; La Liga/Bundesliga's head-to-head rules
differ in rare ties).

TWO BASELINES, because skill has two sources:
  uniform  every team gets the same chance of each event (1/N, 4/N, 3/N)
  null     the SAME simulation with every team rated equal, so it carries the
           current standings and fixture list but no information about team
           strength. Beating `uniform` only shows the standings matter; beating
           `null` is what the rating model itself adds.
Intervals resample whole league-season-checkpoints (the 20 teams in one table
are not independent). Limitations: the ensemble here is B=20, production uses 60;
zones are the site's (top 4, bottom 3 -- Bundesliga really has 2 direct drops
plus a playoff).

RATING-NOISE FAMILY (pre-registered 26 Nov 2026, before any run). Relegation odds in the 2-10%
bins under-forecast (forecast 0.072, happened 0.132) while the ensemble carries estimation
uncertainty but not real strength drift, so `sim_league.simulate_season(rating_sd=)` adds a
season-long lognormal drift per club. Grid sd in {0.05, 0.10, 0.15, 0.20} against sd=0 at the
production blend (xg_weight 0.75). DEV = seasons 2016-17..2022-23 (`dev`) choose; CONFIRMATION =
2023-24..2025-26 (`confirm`) is looked at ONCE. An sd advances if relegation Brier improves over
sd=0 with a cluster-bootstrap CI lower bound > 0 and neither title nor top-4 Brier worsens in
point estimate; the best advancing sd gets its one confirmation look and PASSES only under the
same rule plus relegation better in >= 2 of the 3 seasons. Otherwise sd stays 0.
"""
import json
import os
import sys

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import time  # noqa: E402
from concurrent.futures import ProcessPoolExecutor  # noqa: E402

import numpy as np  # noqa: E402

import fit_league as fl  # noqa: E402
from eval_stats import improvement  # noqa: E402
from multiseason_data import DEFAULT_CACHE, SEASONS, to_fit_rows  # noqa: E402
from rolling_backtest import _as_of, load_all, worker_count  # noqa: E402
from sim_league import simulate_season  # noqa: E402

TOP_ZONE, REL_ZONE = 4, 3
EVENTS = {"title": lambda d: d[0], "top4": lambda d: sum(d[:TOP_ZONE]), "relegation": lambda d: sum(d[-REL_ZONE:])}
FRACS = (0.0, 0.25, 0.5)


def table_from(rows):
    t = {}
    for r in rows:
        for team in (r["home"], r["away"]):
            t.setdefault(team, {"pts": 0, "gd": 0, "gf": 0})
        h, a = t[r["home"]], t[r["away"]]
        h["gf"] += r["hg"]; h["gd"] += r["hg"] - r["ag"]
        a["gf"] += r["ag"]; a["gd"] += r["ag"] - r["hg"]
        if r["hg"] > r["ag"]:
            h["pts"] += 3
        elif r["hg"] < r["ag"]:
            a["pts"] += 3
        else:
            h["pts"] += 1; a["pts"] += 1
    return t


def final_order(rows):
    t = table_from(rows)
    return sorted(t, key=lambda x: (t[x]["pts"], t[x]["gd"], t[x]["gf"]), reverse=True)


def event_probs(rank_dist):
    return {team: {ev: float(f(dist)) for ev, f in EVENTS.items()} for team, dist in rank_dist.items()}


def null_ensemble(teams, home_adv):
    return [{"attack": {t: 0.0 for t in teams}, "defense": {t: 0.0 for t in teams},
             "home_adv": home_adv, "rho": 0.0, "teams": list(teams)}]


def run_checkpoint(rows_by_season, season_keys, idx, frac, B=20, n_sims=3000, seed=0, train_seasons=3, xg_weight=0.0,
                   rating_sds=(0.0,)):
    """Records {event, team, sd, p, p_null, y} for one (season, checkpoint), one set per rating_sd (one
    fit serves them all; the standings-only null never gets noise). `xg_weight` blends the
    fit's training goals toward xG (rows need hxg/axg, see xg_data.attach_all); Elo keeps real goals."""
    rows = rows_by_season[season_keys[idx]]
    k = int(round(frac * len(rows)))
    played, rest = rows[:k], rows[k:]
    teams = sorted({t for r in rows for t in (r["home"], r["away"])})
    as_of = rest[0]["date"]
    pool = [r for key in season_keys[max(0, idx - train_seasons):idx] for r in rows_by_season[key]]
    train = pool + [r for r in played if r["date"] < as_of]
    fit_rows = to_fit_rows(train, "vs", xg_weight)
    with _as_of(as_of):
        elo = fl.compute_elos(to_fit_rows(train, "vs"))
        dc = fl.fit_dc(fit_rows, elo)
        ens = fl.fit_dc_bootstrap(fit_rows, elo, dc, B=B, seed=seed)
    standings = table_from(played)
    remaining = [(r["home"], r["away"]) for r in rest]
    model = {sd: event_probs(simulate_season(teams, standings, remaining, ens, n_sims=n_sims, seed=seed, rating_sd=sd))
             for sd in rating_sds}
    null = event_probs(simulate_season(teams, standings, remaining, null_ensemble(teams, dc["home_adv"]),
                                       n_sims=n_sims, seed=seed))
    order = final_order(rows)
    realised = {"title": {order[0]}, "top4": set(order[:TOP_ZONE]), "relegation": set(order[-REL_ZONE:])}
    return [{"event": ev, "team": t, "sd": sd, "p": model[sd][t][ev], "p_null": null[t][ev], "y": int(t in realised[ev])}
            for sd in rating_sds for ev in EVENTS for t in teams]


def _task(args):
    league, by, keys, idx, frac, B, n_sims, xg_weight, rating_sds = args
    return [{**r, "league": league, "season": keys[idx], "frac": frac}
            for r in run_checkpoint(by, keys, idx, frac, B=B, n_sims=n_sims, seed=idx, xg_weight=xg_weight,
                                    rating_sds=rating_sds)]


def run_all(data, test_seasons, fracs=FRACS, B=20, n_sims=3000, workers=1, xg_weight=0.0, rating_sds=(0.0,)):
    tasks = [(lg, by, SEASONS, SEASONS.index(s), f, B, n_sims, xg_weight, rating_sds) for lg, by in data.items()
             for s in test_seasons for f in fracs]
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            chunks = list(ex.map(_task, tasks))
    else:
        chunks = [_task(t) for t in tasks]
    return [r for c in chunks for r in c]


def summarize(records, by=None):
    """Per event: model / uniform / null Brier over team-events, and skill with a
    cluster-bootstrap interval on the improvement over each baseline."""
    out = {}
    for ev in EVENTS:
        rs = [r for r in records if r["event"] == ev and (by is None or by(r))]
        if not rs:
            continue
        n_teams = len({(r["league"], r["season"], r["frac"], r["team"]) for r in rs}) / max(
            1, len({(r["league"], r["season"], r["frac"]) for r in rs}))
        base_rate = np.mean([r["y"] for r in rs])
        y = np.array([r["y"] for r in rs], float)
        p, pn = np.array([r["p"] for r in rs]), np.array([r["p_null"] for r in rs])
        uni = np.full(len(rs), base_rate)
        loss = lambda q: (q - y) ** 2
        clusters = [f"{r['league']}|{r['season']}|{r['frac']}" for r in rs]
        vs_uni = improvement(loss(p), loss(uni), clusters=clusters, seed=0)
        vs_null = improvement(loss(p), loss(pn), clusters=clusters, seed=0)
        out[ev] = {"n": len(rs), "teams_per_table": n_teams, "brier": float(loss(p).mean()),
                   "uniform_brier": float(loss(uni).mean()), "null_brier": float(loss(pn).mean()),
                   "skill_vs_uniform": float(1 - loss(p).mean() / loss(uni).mean()), "vs_uniform": vs_uni,
                   "skill_vs_null": float(1 - loss(p).mean() / loss(pn).mean()), "vs_null": vs_null}
    return out


def reliability(records, event, edges=(0, 0.02, 0.05, 0.1, 0.2, 0.4, 0.7, 1.0001)):
    rs = [r for r in records if r["event"] == event]
    rows = []
    for lo, hi in zip(edges, edges[1:]):
        cell = [r for r in rs if lo <= r["p"] < hi]
        if cell:
            rows.append((lo, min(hi, 1.0), len(cell), float(np.mean([r["p"] for r in cell])), float(np.mean([r["y"] for r in cell]))))
    return rows


def paired(records, sd, event, by=None):
    """Brier improvement of rating_sd=`sd` over sd=0 on the same team-events (positive = better),
    with an interval that resamples whole league-season-checkpoints."""
    key = lambda r: (r["league"], r["season"], r["frac"], r["team"])
    pick = lambda s: {key(r): r for r in records if r["event"] == event and r["sd"] == s and (by is None or by(r))}
    a, b = pick(sd), pick(0.0)
    ks = sorted(a)
    y = np.array([a[k]["y"] for k in ks], float)
    loss = lambda d: (np.array([d[k]["p"] for k in ks]) - y) ** 2
    return improvement(loss(a), loss(b), clusters=[f"{k[0]}|{k[1]}|{k[2]}" for k in ks], seed=0)


def main():
    """python validate_sim.py [xg_weight] [sd,sd,...] [dev|confirm|all]  -- e.g. `0.75 0,0.05,0.1 dev`.
    The records are kept in backtest_cache/validate_sim_<split>.json (gitignored) for later slicing."""
    t0 = time.time()
    xg_weight = float(sys.argv[1]) if len(sys.argv) > 1 else 0.0      # e.g. 0.75 = the production blend
    sds = tuple(float(x) for x in sys.argv[2].split(",")) if len(sys.argv) > 2 else (0.0,)
    split = sys.argv[3] if len(sys.argv) > 3 else "all"
    data = load_all(xg=bool(xg_weight))
    test_seasons = {"dev": SEASONS[3:10], "confirm": SEASONS[10:], "all": SEASONS[3:]}[split]
    recs = run_all(data, test_seasons, workers=worker_count(), xg_weight=xg_weight, rating_sds=sds)
    with open(os.path.join(DEFAULT_CACHE, f"validate_sim_{split}.json"), "w") as f:
        json.dump(recs, f)
    print(f"simulated {len({(r['league'], r['season'], r['frac']) for r in recs})} league-season-checkpoints "
          f"in {time.time() - t0:.0f}s\n")
    for sd in sds:
        rs = [r for r in recs if r["sd"] == sd]
        print(f"######## rating_sd={sd}")
        for label, sel in [("ALL checkpoints", None)] + [(f"checkpoint {int(f*100)}% played", (lambda r, f=f: r["frac"] == f)) for f in FRACS]:
            print(f"== {label}")
            for ev, s in summarize(rs, sel).items():
                u, nl = s["vs_uniform"], s["vs_null"]
                print(f"  {ev:11s} n={s['n']:4d} Brier {s['brier']:.4f} | uniform {s['uniform_brier']:.4f} (skill {s['skill_vs_uniform']:+.1%}, "
                      f"dBrier {u['mean']:+.4f} CI [{u['lo']:+.4f},{u['hi']:+.4f}]) | standings-only {s['null_brier']:.4f} "
                      f"(skill {s['skill_vs_null']:+.1%}, dBrier {nl['mean']:+.4f} CI [{nl['lo']:+.4f},{nl['hi']:+.4f}])")
        print("\n== reliability (all checkpoints): bin of model probability -> mean forecast vs how often it happened")
        for ev in EVENTS:
            print(f"  {ev}:")
            for lo, hi, n, mp, ob in reliability(rs, ev):
                print(f"    {lo:.2f}-{hi:.2f}  n={n:4d}  forecast {mp:.3f}  happened {ob:.3f}")
    for sd in (x for x in sds if x and 0.0 in sds):
        print(f"\n######## rating_sd={sd} vs 0: Brier improvement (positive = better), cluster CI")
        for ev in EVENTS:
            d = paired(recs, sd, ev)
            per = {s: paired(recs, sd, ev, lambda r, s=s: r["season"] == s)["mean"] for s in test_seasons}
            print(f"  {ev:11s} {d['mean']:+.5f} [{d['lo']:+.5f},{d['hi']:+.5f}]  better in {sum(v > 0 for v in per.values())}/{len(per)} seasons "
                  + " ".join(f"{s}:{v:+.4f}" for s, v in per.items()))


if __name__ == "__main__":
    main()
