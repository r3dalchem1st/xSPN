"""
Model experiments under rolling_backtest.py's pre-registered rule.

    python experiments.py dev                 # screen every candidate on the DEVELOPMENT seasons only
    python experiments.py combo               # dev-screen the combination of pooled-family winners
    python experiments.py confirm [family..]  # judge each family's dev winner on the CONFIRMATION seasons
    python experiments.py confirm-production  # judge the momentum settings live in production (one look each)

The confirmation seasons are touched once per family: `confirm` records each
verdict in backtest_cache/confirmation_log.json and refuses to run a family
twice, so a disappointing result can't be quietly re-rolled with a tweaked
candidate. Families are the levers the 8 Oct audit listed (untuned half-life
and L2, Elo used only as a starting point, promoted clubs at zero) plus the
older calibration knobs and the momentum / odds-fit settings that are live in
production, which were all chosen on a single season and are re-judged here.

`dev` is resumable: each candidate's screen is saved as soon as it's computed
(backtest_cache/dev_results.json) and skipped on a re-run, so a crash or a
stopped session costs one candidate, not the whole sweep.
"""
import os

# Single-threaded BLAS in every worker: the fits are tiny, and per-process thread
# pools just multiply memory. Must be set before numpy is imported (children inherit it).
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import json  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from concurrent.futures import ProcessPoolExecutor  # noqa: E402

from multiseason_data import DEFAULT_CACHE, SEASONS  # noqa: E402
from rolling_backtest import DEV_SEASONS, judge, load_all, run_config, screen, worker_count  # noqa: E402

TEST_SEASONS = SEASONS[3:]          # 2016-17 .. 2025-26, identical for every candidate
LOG_PATH = os.path.join(DEFAULT_CACHE, "confirmation_log.json")
DEV_PATH = os.path.join(DEFAULT_CACHE, "dev_results.json")

FAMILIES = {
    "half_life": [(f"half_life={v}", {"half_life_days": v}) for v in (120, 240, 365, 730, 1095, 1825)],
    # 3.0/6.0/12.0 added AFTER the first sweep showed the improvement still rising at the
    # original grid's edge (1.5). Extending a grid on DEVELOPMENT data is fine; the
    # confirmation seasons were not touched.
    "l2": [(f"l2={v}", {"l2_reg": v}) for v in (0.03, 0.1, 0.2, 0.5, 0.8, 1.5, 3.0, 6.0, 12.0)],
    "elo_prior": [(f"elo_beta={v}", {"elo_prior_beta": v}) for v in (0.1, 0.25, 0.5, 1.0)],
    "promoted_prior": [(f"promoted=({-v},{v})", {"promoted_prior": (-v, v)}) for v in (0.1, 0.2, 0.3, 0.4)],
    "train_window": [(f"train_seasons={v}", {"train_seasons": v}) for v in (1, 2, 5, 8)],
    "shrink": [(f"shrink={v}", {"strength_shrink": v}) for v in (0.95, 0.9, 0.8)],
    "draw_inflate": [(f"draw_inflate={v}", {"draw_inflate": v}) for v in (0.05, 0.1, 0.2)],
    "rho": [("use_rho", {"use_rho": True})],
    "momentum": [(f"momentum w={w} n={n}", {"momentum_weight": w, "momentum_n": n})
                 for w in (0.02, 0.05, 0.1) for n in (5, 8)],
    "odds_fit": [(f"odds_weight={v}", {"odds_weight": v}) for v in (5.0, 25.0, 100.0)],
    # Added 26 Oct, grid fixed BEFORE any run. Training targets become (1-w)*goals + w*xG (Understat;
    # xg_data.py). Motivated by a dev-era-only split-half check (2014-15..2022-23): first-half xG
    # predicted second-half goal difference better than first-half goals (r .784 vs .733, CI on the
    # gain [+.029,+.076]). Pooled across leagues; w=0 is the baseline, w=1 is pure xG.
    "xg": [(f"xg_weight={v}", {"xg_weight": v}) for v in (0.25, 0.5, 0.75, 1.0)],
}
PER_LEAGUE = {"momentum", "odds_fit"}      # settings chosen and judged one league at a time
POOLED_FOR_COMBINATION = ["half_life", "l2", "elo_prior", "promoted_prior", "train_window", "shrink", "draw_inflate"]
LEAGUES = ["premier_league", "la_liga", "bundesliga"]


def _load(path, default):
    return json.load(open(path)) if os.path.exists(path) else default


def _save(path, obj):
    os.makedirs(DEFAULT_CACHE, exist_ok=True)
    json.dump(obj, open(path, "w"), indent=1, default=str)


def _compact(r):
    """What a screen result needs to keep (JSON-safe, no per-match arrays)."""
    return {"brier": r["brier"], "logloss": r["logloss"], "per_league": r["per_league"], "advance": r["advance"]}


def _fmt(r):
    b = r["brier"]
    leagues = " ".join(f"{k[:2].upper()} {v:+.4f}" for k, v in r["per_league"].items())
    return f"dBrier {b['mean']:+.5f} [{b['lo']:+.5f},{b['hi']:+.5f}] {'ADVANCE' if r['advance'] else '       '} | {leagues}"


def _best(entries):
    adv = [e for e in entries if e["res"]["advance"]]
    return max(adv, key=lambda e: e["res"]["brier"]["mean"]) if adv else None


def dev_stage():
    data = load_all(xg=True)
    saved = _load(DEV_PATH, {})
    with ProcessPoolExecutor(max_workers=worker_count()) as ex:
        run = lambda cfg: run_config(cfg, data, test_seasons=TEST_SEASONS, executor=ex)
        t0 = time.time()
        base = run({})
        print(f"baseline done ({time.time() - t0:.0f}s, {worker_count()} workers). Positive dBrier = candidate better. "
              f"Development seasons only: {DEV_SEASONS[0]}..{DEV_SEASONS[-1]}\n", flush=True)

        def screen_candidate(fam, label, cfg):
            if label in saved:
                return
            t = time.time()
            recs = run(cfg)
            entry = {"family": fam, "config": cfg, "ALL": _compact(screen(recs, base))}
            if fam in PER_LEAGUE:
                for lg in LEAGUES:
                    entry[lg] = _compact(screen(recs, base, leagues=[lg]))
            saved[label] = entry
            _save(DEV_PATH, saved)
            print(f"  {fam:15s} {label:28s} {_fmt(entry['ALL'])}  ({time.time() - t:.0f}s)", flush=True)

        for fam, cands in FAMILIES.items():
            for label, cfg in cands:
                screen_candidate(fam, label, cfg)

    winners, combo = {}, {}
    print("\n=== development winners (advance = paired Brier CI lower bound > 0) ===")
    for fam, cands in FAMILIES.items():
        scopes = LEAGUES if fam in PER_LEAGUE else ["ALL"]
        for sc in scopes:
            best = _best([{"label": lab, "cfg": cfg, "res": saved[lab][sc]} for lab, cfg in cands])
            winners[f"{fam}|{sc}"] = best["cfg"] if best else None
            print(f"  {fam:15s} {sc:15s} -> {best['label'] if best else 'none (baseline stays)'}")
            if best and sc == "ALL" and fam in POOLED_FOR_COMBINATION:
                combo.update(best["cfg"])
    winners["combination|ALL"] = combo or None
    _save(os.path.join(DEFAULT_CACHE, "dev_winners.json"), winners)
    print(f"\ncombination of pooled-family winners: {combo or 'none'}  (screen it with: python experiments.py combo)")


def combo_stage():
    """Dev-screen the combination of pooled-family winners (still development seasons only)."""
    data = load_all(xg=True)
    combo = _load(os.path.join(DEFAULT_CACHE, "dev_winners.json"), {}).get("combination|ALL")
    if not combo:
        return print("no combination to test")
    with ProcessPoolExecutor(max_workers=worker_count()) as ex:
        run = lambda cfg: run_config(cfg, data, test_seasons=TEST_SEASONS, executor=ex)
        r = screen(run(combo), run({}))
    print(f"COMBINATION {combo}\n  {_fmt(r)}")


# Settings live in production today (chosen on the single 2025-26 season, which is INSIDE the
# confirmation set -- so this look is optimistic for them; if they fail anyway the verdict is firm).
PRODUCTION_SETTINGS = {
    "production_momentum|premier_league": ({"momentum_weight": 0.1, "momentum_n": 8}, "premier_league"),
    "production_momentum|bundesliga": ({"momentum_weight": 0.02, "momentum_n": 5}, "bundesliga"),
}


def _judge_and_log(key, cfg, scope, run, base, log):
    if key in log:
        print(f"{key}: ALREADY CONFIRMED once ({'PASS' if log[key]['pass'] else 'FAIL'}); "
              f"refusing a second look at the confirmation seasons")
        return
    base_scoped = base if scope == "ALL" else [r for r in base if r["league"] == scope]
    r = judge(run(cfg, scope), base_scoped, leagues=None if scope == "ALL" else [scope])
    log[key] = {"config": cfg, "pass": r["pass"], "dBrier": r["brier"], "dLogloss": r["logloss"],
                "per_league": r["per_league"], "per_season": r["per_season"], "reasons": r["reasons"]}
    _save(LOG_PATH, log)
    b = r["brier"]
    print(f"{key:34s} {'PASS' if r['pass'] else 'FAIL'}  dBrier {b['mean']:+.5f} [{b['lo']:+.5f},{b['hi']:+.5f}]  "
          f"dLogloss {r['logloss']:+.5f}  {cfg}")
    print(f"    {'; '.join(r['reasons']) or 'all conditions met'}", flush=True)


def confirm_stage(families, production=False):
    log = _load(LOG_PATH, {})
    data = load_all(xg=True)
    with ProcessPoolExecutor(max_workers=worker_count()) as ex:
        # a league-scoped setting is judged on that league alone, so only compute that league
        run = lambda cfg, scope="ALL": run_config(cfg, data if scope == "ALL" else {scope: data[scope]},
                                                  test_seasons=TEST_SEASONS, executor=ex)
        base = run({})
        if production:
            for key, (cfg, scope) in PRODUCTION_SETTINGS.items():
                _judge_and_log(key, cfg, scope, run, base, log)
            return
        for key, cfg in _load(os.path.join(DEFAULT_CACHE, "dev_winners.json"), {}).items():
            fam, scope = key.split("|")
            if families and fam not in families:
                continue
            if cfg is None:
                print(f"{key}: no development winner -> nothing to confirm; baseline stays")
                continue
            _judge_and_log(key, cfg, scope, run, base, log)


if __name__ == "__main__":
    stages = {"dev": lambda: dev_stage(), "combo": lambda: combo_stage(),
              "confirm": lambda: confirm_stage(sys.argv[2:]),
              "confirm-production": lambda: confirm_stage([], production=True)}
    if len(sys.argv) < 2 or sys.argv[1] not in stages:
        raise SystemExit(__doc__)
    stages[sys.argv[1]]()
