"""
Rolling-origin backtest over many seasons, and the pre-registered rule for
deciding whether a model change is real.

WHY: every model decision before this was made on one ~300-match holdout or a
few dozen live matches. Per-match Brier SD is ~0.06, so those samples cannot
resolve the ~0.01 effects being tuned (eval_stats.required_n: ~280 matches per
decision). This evaluates a model configuration on 10 test seasons x 3 leagues
(~10,600 matches), predicting each season only from what was knowable then.

HOW: for each test season, the model is refit every `refit_days` on the
previous `train_seasons` seasons PLUS the test season's matches played so far
(strictly before the refit date), then predicts the next block of matches. A
test asserts that changing a result never alters a prediction made before it
(no look-ahead), and that it does alter later ones (the model learns).
Data: multiseason_data.py (football-data.co.uk results + market odds).

THE PRE-REGISTERED RULE (written before any experiment was run; do not edit
after seeing results -- add a new rule version instead):
  * Seasons are split once: DEVELOPMENT (2016-17..2022-23) is used to choose
    among candidates; CONFIRMATION (2023-24..2025-26) is touched exactly once,
    by the single winning candidate of each family, and never used to choose.
  * SCREEN (development seasons, pooled): a candidate advances only if the
    paired 95% bootstrap interval on its Brier improvement over the baseline
    has a lower bound > 0. Among advancing candidates of a family, the largest
    improvement is the winner.
  * PASS (confirmation seasons) requires ALL of:
      R1  paired 95% bootstrap interval on Brier improvement: lower bound > 0
      R2  mean log-loss improvement >= 0
      R3  Brier improves in at least two-thirds of the confirmation seasons
          and (when more than one league is in scope) of the leagues
  * A candidate that does not PASS is not adopted: the baseline stays.
  * A setting scoped to one league (e.g. odds_fit_weight for La Liga) is judged
    on that league's matches alone; R3 then counts seasons only.
Accuracy is reported but is not part of the rule (it is too noisy to decide on).
"""
import contextlib
import datetime as dt
import math
import os
from concurrent.futures import ProcessPoolExecutor

import numpy as np

import fit_league as fl
from backtest_league import predict_match_probs
from eval_stats import brier_losses, correct_flags, improvement, logloss_losses
from multiseason_data import LEAGUE_CODES, SEASONS, load_league, to_fit_rows

DEFAULT_CONFIG = {
    "half_life_days": fl.HALF_LIFE_DAYS, "l2_reg": fl.L2_REG, "odds_weight": 0.0,
    "train_seasons": 3, "refit_days": 30,
    "momentum_weight": 0.0, "momentum_n": 5, "strength_shrink": 1.0, "draw_inflate": 0.0, "use_rho": False,
    "elo_prior_beta": 0.0, "promoted_prior": None, "xg_weight": 0.0,
}
DEV_SEASONS = ["1617", "1718", "1819", "1920", "2021", "2122", "2223"]
CONFIRM_SEASONS = ["2324", "2425", "2526"]


@contextlib.contextmanager
def _as_of(date_str):
    """Recency weights (and Elo) computed as of `date_str`, not real today --
    the same days_ago() patch backtest_league.fit_point_estimate uses."""
    orig = fl.days_ago
    fl.days_ago = lambda ds, ref=date_str: orig(ds, ref)
    try:
        yield
    finally:
        fl.days_ago = orig


def _blocks(rows, refit_days):
    first = dt.date.fromisoformat(rows[0]["date"])
    grouped = {}
    for r in rows:
        grouped.setdefault((dt.date.fromisoformat(r["date"]) - first).days // refit_days, []).append(r)
    return [grouped[k] for k in sorted(grouped)]


def _build_prior(cfg, elo, promoted):
    beta, pp = cfg["elo_prior_beta"], cfg["promoted_prior"]
    if not beta and not pp:
        return None
    atk, dfn = {}, {}
    if beta:
        mean = float(np.mean(list(elo.values())))
        for t, e in elo.items():
            z = (e - mean) / 400.0
            atk[t], dfn[t] = beta * z, -beta * z
    if pp:
        for t in promoted:
            atk[t], dfn[t] = atk.get(t, 0.0) + pp[0], dfn.get(t, 0.0) + pp[1]
    return {"attack": atk, "defense": dfn}


def _with_promoted_defaults(dc, cfg, promoted):
    """A promoted club that hasn't played yet is absent from the fit and would
    default to a league-average rating; give it the prior instead."""
    pp = cfg["promoted_prior"]
    if not pp:
        return dc
    dc = {**dc, "attack": dict(dc["attack"]), "defense": dict(dc["defense"])}
    for t in promoted:
        dc["attack"].setdefault(t, pp[0])
        dc["defense"].setdefault(t, pp[1])
    return dc


def run_season(rows_by_season, season_keys, test_idx, config):
    """Out-of-sample predictions for one test season -> list of records
    {season, date, home, away, o, p, q, conv}. o: 0=H 1=D 2=A; p: model
    (ph,pd,pa); q: de-vigged market or None; conv: did the block's fit converge."""
    cfg = {**DEFAULT_CONFIG, **config}
    test_key = season_keys[test_idx]
    pool_keys = season_keys[max(0, test_idx - cfg["train_seasons"]):test_idx]
    pool = [r for k in pool_keys for r in rows_by_season[k]]
    test_rows = rows_by_season[test_key]
    prev_teams = {t for r in rows_by_season[season_keys[test_idx - 1]] for t in (r["home"], r["away"])}
    promoted = {t for r in test_rows for t in (r["home"], r["away"])} - prev_teams

    out = []
    for block in _blocks(test_rows, cfg["refit_days"]):
        as_of = block[0]["date"]
        train = pool + [r for r in test_rows if r["date"] < as_of]
        plain = to_fit_rows(train, "bt")       # real goals: Elo, momentum and scoring never see xG
        fit_rows = to_fit_rows(train, "bt", cfg["xg_weight"]) if cfg["xg_weight"] else plain
        with _as_of(as_of):
            elo = fl.compute_elos(plain, half_life_days=cfg["half_life_days"])
            dc = fl.fit_dc(fit_rows, elo,
                           mkt_probs_by_match=[r["market"] for r in train] if cfg["odds_weight"] else None,
                           odds_weight=cfg["odds_weight"], half_life_days=cfg["half_life_days"],
                           l2_reg=cfg["l2_reg"], prior=_build_prior(cfg, elo, promoted))
        dc = _with_promoted_defaults(dc, cfg, promoted)
        revealed = plain + to_fit_rows(block, "bt")  # compute_momentum filters to strictly-before each match
        for r in block:
            p = predict_match_probs(r["home"], r["away"], r["date"], False, dc, cfg["strength_shrink"],
                                    cfg["draw_inflate"], cfg["use_rho"], cfg["momentum_weight"],
                                    cfg["momentum_n"], revealed)
            out.append({"season": test_key, "date": r["date"], "home": r["home"], "away": r["away"],
                        "o": 0 if r["hg"] > r["ag"] else (2 if r["hg"] < r["ag"] else 1),
                        "p": tuple(p), "q": r["market"], "conv": dc["converged"]})
    return out


def _task(args):
    league, rows_by_season, season_keys, idx, config = args
    return [{**rec, "league": league} for rec in run_season(rows_by_season, season_keys, idx, config)]


def worker_count():
    """Parallel workers: XSPN_WORKERS (default 6), capped by cores. Each worker is a
    full Python process importing numpy+scipy (~hundreds of MB of commit on Windows);
    an 18-worker run exhausted the pagefile on a 16 GB machine and crashed the session."""
    return max(1, min(int(os.environ.get("XSPN_WORKERS", "6")), os.cpu_count() or 1))


def run_config(config, data, test_seasons=None, season_keys=None, workers=1, executor=None):
    """Run one model configuration over every league in `data`
    ({league: {season: rows}}) for `test_seasons` (default: every season with
    enough history). Records come back in a stable (league, season, date) order
    so two configs' records line up match-for-match for paired comparison.
    Pass an existing `executor` to reuse one worker pool across many configs
    (respawning a pool per config is slow and multiplies peak memory)."""
    cfg = {**DEFAULT_CONFIG, **config}
    keys = season_keys or SEASONS
    wanted = test_seasons or keys[cfg["train_seasons"]:]
    tasks = [(lg, by, keys, keys.index(s), config) for lg, by in data.items() for s in wanted]
    if executor is not None:
        chunks = list(executor.map(_task, tasks))
    elif workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            chunks = list(ex.map(_task, tasks))
    else:
        chunks = [_task(t) for t in tasks]
    return [rec for chunk in chunks for rec in chunk]


def load_all(leagues=None, seasons=SEASONS, xg=False):
    """{league: {season: rows}} for the three leagues (cached CSVs after first run).
    xg=True also attaches Understat's per-match xG (xg_data.py; cached after first run)."""
    data = {lg: load_league(LEAGUE_CODES[lg], seasons) for lg in (leagues or LEAGUE_CODES)}
    if xg:
        from xg_data import attach_all
        attach_all(data)
    return data


def _arrays(records):
    P = np.array([r["p"] for r in records], float)
    o = np.array([r["o"] for r in records], int)
    return P, o


def metrics(records):
    """Model (and market, where recorded) accuracy / Brier / log-loss over `records`."""
    P, o = _arrays(records)
    out = {"n": len(records), "brier": float(brier_losses(P, o).mean()), "logloss": float(logloss_losses(P, o).mean()),
           "accuracy": float(correct_flags(P, o).mean())}
    has_q = [r for r in records if r["q"]]
    if has_q:
        Q = np.array([r["q"] for r in has_q], float)
        oq = np.array([r["o"] for r in has_q], int)
        out.update(market_n=len(has_q), market_brier=float(brier_losses(Q, oq).mean()),
                   market_logloss=float(logloss_losses(Q, oq).mean()), market_accuracy=float(correct_flags(Q, oq).mean()))
    return out


def _aligned(cand, base, seasons, leagues):
    keyf = lambda r: (r["league"], r["season"], r["date"], r["home"], r["away"])
    assert [keyf(r) for r in cand] == [keyf(r) for r in base], "candidate and baseline must cover identical matches"
    idx = [i for i, r in enumerate(base) if r["season"] in seasons and (leagues is None or r["league"] in leagues)]
    return [cand[i] for i in idx], [base[i] for i in idx]


def _compare(cand, base, seasons, leagues, n_boot=5000, seed=0):
    c, b = _aligned(cand, base, seasons, leagues)
    Pc, o = _arrays(c)
    Pb, _ = _arrays(b)
    bl_c, bl_b = brier_losses(Pc, o), brier_losses(Pb, o)
    brier = improvement(bl_c, bl_b, n_boot=n_boot, seed=seed)
    logloss = float((logloss_losses(Pb, o) - logloss_losses(Pc, o)).mean())
    d = bl_b - bl_c
    group = lambda key: {g: float(d[[i for i, r in enumerate(b) if r[key] == g]].mean()) for g in sorted({r[key] for r in b})}
    return {"brier": brier, "logloss": logloss, "per_league": group("league"), "per_season": group("season")}


def _two_thirds(values):
    return sum(v > 0 for v in values) >= math.ceil(2 * len(values) / 3)


def _passes(brier, logloss, per_league, per_season):
    return (brier["lo"] > 0 and logloss >= 0 and _two_thirds(per_season.values())
            and (len(per_league) < 2 or _two_thirds(per_league.values())))


def screen(cand, base, leagues=None, n_boot=5000):
    """Development-season screen: does the candidate's Brier improvement have a
    positive lower bound? (Used to choose which candidate reaches confirmation.)"""
    r = _compare(cand, base, DEV_SEASONS, leagues, n_boot)
    r["advance"] = bool(r["brier"]["lo"] > 0)
    return r


def judge(cand, base, leagues=None, n_boot=5000):
    """Confirmation-season verdict per the pre-registered rule in the module
    docstring. Touch this once per family winner."""
    r = _compare(cand, base, CONFIRM_SEASONS, leagues, n_boot)
    reasons = []
    if not r["brier"]["lo"] > 0:
        reasons.append(f"Brier improvement CI lower bound {r['brier']['lo']:+.5f} is not > 0")
    if r["logloss"] < 0:
        reasons.append(f"log-loss got worse ({r['logloss']:+.5f})")
    if not _two_thirds(r["per_season"].values()):
        reasons.append(f"Brier improved in too few seasons: {r['per_season']}")
    if len(r["per_league"]) >= 2 and not _two_thirds(r["per_league"].values()):
        reasons.append(f"Brier improved in too few leagues: {r['per_league']}")
    r["pass"] = _passes(r["brier"], r["logloss"], r["per_league"], r["per_season"])
    r["reasons"] = reasons
    return r


def main():
    import time
    t = time.time()
    data = load_all()
    recs = run_config({}, data, workers=worker_count())
    print(f"baseline (production defaults, plain model) over {len(recs)} out-of-sample matches in {time.time()-t:.0f}s, "
          f"{sum(1 for r in recs if not r['conv'])} non-converged fits\n")
    print(f"{'':16s} {'n':>5} {'model Brier':>12} {'market Brier':>13} {'model acc':>10} {'market acc':>11}")
    for lg in list(data) + ["ALL"]:
        sub = [r for r in recs if lg == "ALL" or r["league"] == lg]
        m = metrics(sub)
        print(f"{lg:16s} {m['n']:5d} {m['brier']:12.4f} {m['market_brier']:13.4f} {m['accuracy']:10.3f} {m['market_accuracy']:11.3f}")


if __name__ == "__main__":
    main()
