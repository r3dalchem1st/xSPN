# Model Change Log

Parameter changes, with accuracy metrics at the time of each change.
Metrics come from `accuracy_history.json` (auto-updated each run by `score_predictions.py`).

---

## Baseline — 2026-06-28 (pre-session)

36 group stage matches scored (rounds 1–2, Jun 11–21).
Model was the broken June 1 pipeline; all 72 group snapshots locked with stale predictions.

| metric | value |
|--------|-------|
| accuracy | 0.5000 (18/36) |
| avg Brier | 0.6111 |
| avg goal error | 2.31 |
| avg log-loss | 1.2986 |
| predicted draw rate | 0.2588 |
| actual draw rate | 0.3056 |
| ECE | 0.1174 |

---

## 2026-06-28 — P7: WC 2026 match weight multiplier

**File:** `fit_improved.py`  
**Change:** `WC_2026_MULTIPLIER = 3.0` — current tournament matches get 3× weight in the Dixon-Coles fit  
**Rationale:** DC fit was slow to update from historical baselines; co-host teams (especially USA/Mexico) were being under-rated because qualifier/friendly data dominated over live WC results  
**Effect on current metrics:** changes DC parameters going forward; baseline metrics above are pre-P7

---

## 2026-06-28 — P8: Co-host home advantage

**File:** `fetch_matches.py`  
**Change:** Added `_co_host_home()` — WC 2026 group stage matches involving USA, Mexico, or Canada are stored with `neutral=False`; if the API lists the co-host as "away", home/away and goals are swapped  
**Rationale:** All co-host group games are played at their home-country venues; DC model was treating them as neutral, under-estimating the home crowd effect  
**Note:** `build_lambda_table()` in `model_common.py` already applies 65% of `home_adv` to co-hosts in all KO matches — this fix corrects the *training data* so the learned `home_adv` parameter is accurate

---

## 2026-06-28 — PEN table expansion

**File:** `model_common.py`  
**Change:** Expanded PEN table from 20 → 50 entries; all 48 WC 2026 teams now have explicit penalty shootout strengths  
**Corrections to existing values (clear tournament evidence):**

| team | old | new | evidence |
|------|-----|-----|----------|
| Spain | 0.50 | 0.35 | 1-4 WC record |
| Japan | 0.50 | 0.38 | 0-2 WC record |
| Italy | 0.67 | 0.55 | 1-3 WC / won Euro 2020 |
| France | 0.50 | 0.45 | 0-3 WC / won other comps |
| Colombia | 0.50 | 0.42 | 0-1 WC |

**Notable new entries:** Sweden 0.60 (2-0 WC), Paraguay 0.55 (1-0 WC), Australia/South Africa 0.52, USA 0.42 (0-1 WC), Austria 0.35 (historically poor)

---

## 2026-06-28 — DRAW_INFLATE calibration

**File:** `model_common.py`  
**Change:** `DRAW_INFLATE` default `0.25` → `0.50`  
**Rationale:** Measured on 36 WC 2026 group matches — model predicted 25.9% draws vs 30.6% actual. Raw Poisson draw rate ≈21.8%; to reach 30.6% requires δ≈0.55; 0.50 chosen conservatively.  
**Note:** No effect on remaining WC 2026 predictions — KO stage uses `group=False` so DRAW_INFLATE is not applied. Value applies to future group-stage tournaments.  
**Metrics at change:** see Baseline above (predictions were locked before this change)

---

## 2026-08-17 — WC_2026_MULTIPLIER retrospective validation (no change made)

**File:** `fit_improved.py`
**Status:** validated against real data; **value left unchanged at 3.0** — evidence is real but weak, and the parameter is currently inert (see below).
**Background:** P7 (28 Jun, above) shipped `WC_2026_MULTIPLIER = 3.0` with a comment promising a "review after each round by comparing Brier at 2.0/3.0/4.0" — that review was never run while the tournament was live, and the 22 Jul codebase audit flagged it as still unvalidated.
**Method:** now that the full 2026 bracket is known, fit on every match before the R32/knockout boundary (2026-06-28 — includes all 72 real group-stage results, each receiving the multiplier's weight) and score the out-of-sample forecast for the 32-34 knockout matches at M ∈ {2.0, 3.0, 4.0}. Same methodology as `backtest.py` (days_ago() monkeypatched to the cutoff, same Brier/log-loss scoring). Script: `docs/experiments/wc2026_multiplier_grid.py` (local, not committed — mirrors the existing `docs/experiments/` convention).

| multiplier | n  | accuracy | Brier  | log-loss |
|-----------:|---:|---------:|-------:|---------:|
| 2.0        | 34 | 0.735    | 0.4707 | 0.8135   |
| 3.0 (shipped) | 34 | 0.735 | 0.4737 | 0.8173   |
| 4.0        | 34 | 0.706    | 0.4766 | 0.8211   |

**Reading:** monotonically worse as M increases — 2.0 would have scored slightly better than the shipped 3.0 on this holdout, and 4.0 worse still. Directionally consistent with "3.0 over-weighted live evidence a little," but this is a **single cutoff, n=34** — not the multi-round grid the original comment envisioned, and the gap between 2.0 and 3.0 (Brier 0.4707 vs 0.4737) is small relative to what a single retrospective test can distinguish.
**Decision:** don't change the shipped value. The World Cup concluded 19 Jul, so `WC_2026_MULTIPLIER`'s condition (`tournament == "World Cup" and date >= "2026-06-01"`) has no live matches to apply to until the next World Cup (2030) — changing it now would have zero effect on anything currently running. Recorded here so a future session doesn't re-flag this as "never validated": it has been, the evidence just isn't strong enough to act on yet.
**If revisited for a future tournament:** run the fuller multi-cutoff grid the original comment intended (score after each round, not just once from the group-stage boundary) before committing to a value; this one data point leans toward starting from something closer to 2.0 rather than 3.0.

---

## 2026-10-26 — league model re-judged on 10 seasons under a pre-registered rule: three live settings removed

**Files:** `competitions/premier_league.json`, `bundesliga.json`, `la_liga.json`
**Method:** `rolling_backtest.py` / `experiments.py` — rolling-origin refit every 30 days, 10 test seasons x 3 leagues (10,660 matches). Seasons 2016-17..2022-23 chose candidates; 2023-24..2025-26 were looked at ONCE per family (`backtest_cache/confirmation_log.json`). A change must clear a paired-bootstrap Brier CI > 0, log-loss no worse, and gains in >= 2/3 of seasons and leagues; otherwise the baseline stays.
**Changes (all toward the baseline, because nothing cleared the rule):**
- Premier League `momentum_weight` 0.1 (n=8) -> 0.0: confirmation dBrier -0.0050 [-0.0111, +0.0011], log-loss -0.0073, worse in all 3 seasons.
- Bundesliga `momentum_weight` 0.02 (n=5) -> 0.0: dBrier +0.0019 [-0.0001, +0.0038] — a near-miss that did not clear the CI bar (and was selected on 2025-26, inside the confirmation set, so even this look is optimistic).
- La Liga `odds_fit_weight` 100 -> 0.0: dev +0.0047 but confirmation dBrier -0.0007 [-0.0056, +0.0042], log-loss -0.0018, better in 1 of 3 seasons. Inconclusive rather than harmful; La Liga's CI run also drops from ~4 min to ~40 s.
**Judged and left unchanged:** half-life (547.5 d already ~optimal), Elo as a prior, promoted-club prior, strength shrink, draw inflation, rho — none advanced on dev. L2 0.30 -> 3.0 (dev +0.0012) and a longer training window (8 seasons, dev +0.0014) advanced on dev but FAILED confirmation (+0.0002 and -0.00005); their combination also failed (-0.0004).
**Reading:** every lever is worth ~0.001-0.002 Brier, below single-season noise. Future changes go through `experiments.py`, not a one-season grid.

---

## 2026-10-26 (later) — xG-blended training targets PASS the pre-registered rule (NOT yet in production)

**Files:** `xg_data.py`, `multiseason_data.py` (`to_fit_rows(xg_weight)`), `rolling_backtest.py`, `experiments.py` — harness only; the live pipeline is unchanged.
**Change tested:** the Poisson fit's training targets become `(1-w)*goals + w*xG` (Understat per-match xG, 2014-15 onward; 2013-14 rows keep their goals). Elo, momentum and the scored outcomes still use real goals. Grid {0.25, 0.5, 0.75, 1.0} was fixed before any run, pooled across the three leagues.
**Development (2016-17..2022-23):** every weight advanced, positive in all 3 leagues: dBrier +0.0019 / +0.0030 / +0.0032 / +0.0025; winner w=0.75, CI [+0.0015, +0.0049].
**Confirmation (2023-24..2025-26, one look):** w=0.75 **PASS** — dBrier +0.0032 [+0.0008, +0.0056], log-loss +0.0042, improving in the required share of seasons and leagues. Accuracy 52.4% -> 53.2% (confirmation), 52.5% -> 53.1% (development); the Brier gap to the market closes from +0.0143 to +0.0111 (about a quarter). Zero non-converged refits in 10,660.
**Why believed:** a monotone dose-response, the same sign in every league and season block, and an independent dev-era split-half check (first-half xG predicted second-half goal difference better than first-half goals, r .784 vs .733, gain CI [+.029, +.076]).
**Not shipped because** production would need Understat fetched in CI twice daily (an unofficial endpoint) and joined to openfootball club names — a standing unattended dependency that needs a go-ahead.

---

## 2026-10-26 (later still) — three more families judged: fatigue, promoted clubs from the 2nd division, two-speed ratings. None adopted.

**Files:** `rolling_backtest.py` (`rest_weight`, `congestion_weight`, `tier2_prior`, `blend_half_life`/`blend_weight`), `backtest_league.py` (`predict_match_probs(shifts=)`), `multiseason_data.py` (`TIER2_CODES`), `experiments.py` — harness only; grids were fixed before any run.
- **Fatigue (rest days / fixture congestion), 6 candidates:** nothing advanced; every effect within +-0.0003 Brier, intervals spanning zero (best: congestion_weight=0.04, +0.00013 [-0.00012,+0.00037]). Not a design failure: on the development seasons 20% of team-matches have <=4 days' rest and 12.5% sit in a 3+-games-in-14-days spell, yet the residual (actual - expected score) on rest difference is +0.002/day, CI [-0.003,+0.008]; on congestion -0.010/match, CI [-0.028,+0.008]. League fixtures only — cup and European games are NOT in this data, so real congestion is only partly seen.
- **Promoted clubs rated from the second division (E1/SP2/D2, previous season), 9 candidates (gamma x tier-2 rating - c):** nothing advanced (range -0.0005..+0.00002). All 81 promoted clubs across the 10 test seasons map to a club in the division's previous season, so this is a fair test; with the earlier constant-offset family it says the L2 shrinkage already handles promoted clubs about as well as any prior we can build from results.
- **Two-speed ratings ((1-k) slow fit + k fast fit), 8 candidates:** one advanced on development (slow 1095 d / fast 180 d / k=0.5, +0.00067 [+0.00007,+0.00127], Bundesliga flat) and FAILED its one confirmation look: +0.00077 [-0.00010,+0.00164], log-loss +0.0011 — the lower bound just missed zero. Baseline stays.
**Running tally of confirmation looks:** 8 (L2, train window, L2+window, La Liga odds-fit, PL momentum, BL momentum, xG, two-speed); 1 PASS (xG). With that many looks, a single marginal pass would deserve suspicion; xG's was not marginal (consistent dose-response, same sign in every league, independent split-half support).

---

## 2026-10-27 — xG-blended training targets (w=0.75) in production for Premier League, La Liga, Bundesliga

**Files:** `xg_data.py` (`live_xg`, `season_of`), `fetch_league.py` (writes `xg_by_match.json`), `fit_league.py` (`blend_xg`; `fit_and_save` blends the targets for the point fit AND every bootstrap refit — Elo keeps real goals), `competition_config.py` (`understat_code`, `xg_weight`), `snapshot_league.py` (model stamp gains `xg_weight` and `xg_coverage`), the three `competitions/*.json` (`understat_code`, `xg_weight: 0.75`), `update-leagues.yml` (commits `xg_by_match.json`), `validate_sim.py` (optional xG weight).
- **Why:** the only family to pass the pre-registered rule (26 Oct): +0.0032 Brier [+0.0008,+0.0056], log-loss +0.0042 on the confirmation seasons. w=0.75 was the best of the four weights on development seasons.
- **How it runs:** every fetch pulls Understat's per-match xG for each season in the competition config, learns the Understat -> openfootball club map from matches unique on (date, score), joins on (home, away) per season, and writes `xg_by_match.json` parallel to `fetched_matches.json` (rounded to 4 dp). First run against the live data: 840/840 PL, 855/855 La Liga, 674/674 Bundesliga training matches joined, no warnings.
- **Fallback (Understat is unofficial and may block CI):** `live_xg` never raises. A season it cannot fetch (network, HTTP, bad JSON/schema), a club map that will not resolve, or a season whose joined scores disagree with ours by more than 2% leaves those matches `None` and prints a `::warning::`; the fit then trains them on real goals, exactly as before this change. A match Understat has not published yet is also `None` (warns only below 90% of a season joined). `fit_and_save` ignores an `xg_by_match.json` whose length does not match `fetched_matches.json`. Each lock's stamp records `xg_weight` (asked for) and `xg_coverage` (share of training matches that actually had xG; 0.0 = a plain-goals fit), so a run during an outage is identifiable. Locks made before today carry neither key (read as no xG).
- **Live matches the validated path:** the blend moves match probabilities by a mean 3.2 / 1.3 / 2.7 pp (H/D/A) in the backtest (2024-25, 2025-26; favourite flips 6%) and 3-4 / 1.4-2.3 / 2.7-3.7 pp on the live fixtures (flips 6-10%); the blend formula is pinned equal to `to_fit_rows` by a test.
- **Season simulation re-validated** (`validate_sim.py 0.75`, 90 checkpoints, B=20, same seeds; goals-only in brackets): Brier title 0.0181 (0.0194), top-4 0.0540 (0.0560), relegation 0.0845 (0.0838). Skill vs the standings-only null: title +47.7% (+44.2%), top-4 +47.0% (+45.1%), relegation +10.1% (+10.8%). No paired interval between the two runs was computed, so title/top-4 are "better in point estimate", relegation "flat". The relegation under-forecast is not fixed (5-10% bin: forecast 0.072, happened 0.132; the 2-5% bin did improve, 0.033 vs 0.028).
- **Consequence:** predictions change today — a few points per match, with 6-10% of upcoming favourites flipping. Locked predictions are untouched.

---

*To review accuracy before/after any change: check `accuracy_history.json` for entries around the change date.*
