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

*To review accuracy before/after any change: check `accuracy_history.json` for entries around the change date.*
