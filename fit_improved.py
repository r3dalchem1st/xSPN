"""
Step 1: Fit improved model and cache parameters.
Improvements applied:
  #1 Squad market values blended into team strength
  #2 Qualifying Elo inflation fix (opponent-strength discount)
  #3 Fast Dixon-Coles (fully vectorised log-likelihood) + L2 regularisation
  #4 Exponential recency decay (18-month half-life)
"""
import sys, json, math, time, warnings
import numpy as np
from scipy.optimize import minimize
from scipy.special import gammaln
warnings.filterwarnings("ignore")

import os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from match_data import MATCHES, TOURNAMENT_WEIGHTS

# ── #1  SQUAD MARKET VALUES (EUR M, Transfermarkt Dec 2025) ──────────────────
SQUAD_VALUES = {
    "England":1300,"France":1280,"Spain":920,"Brazil":1000,"Germany":850,
    "Portugal":850,"Netherlands":720,"Argentina":570,"Belgium":550,"Colombia":450,
    "Turkey":460,"Italy":730,"Norway":420,"Switzerland":280,"Japan":290,
    "South Korea":250,"Mexico":300,"USA":350,"Croatia":350,"Uruguay":280,
    "Morocco":255,"Austria":280,"Ecuador":220,"Senegal":300,"Sweden":255,
    "Egypt":200,"Australia":185,"Algeria":195,"Paraguay":140,"Tunisia":160,
    "Saudi Arabia":120,"Canada":355,"Ghana":200,"Scotland":285,"Qatar":80,
    "South Africa":100,"Bosnia":150,"Czechia":200,"Panama":60,"Iraq":50,
    "Jordan":65,"DR Congo":120,"Uzbekistan":55,"Haiti":40,"New Zealand":50,
    "Curacao":80,"Cape Verde":100,"Ivory Coast":350,
    "Iran":150,"Slovenia":130,"Slovakia":140,"Serbia":160,"Denmark":340,
    "Poland":220,"Greece":130,"Hungary":140,"Romania":130,"Chile":180,
    "Peru":120,"Venezuela":130,"Bolivia":60,"Costa Rica":80,"El Salvador":50,
    "Jamaica":90,"Honduras":75,"Wales":260,"Israel":130,"Albania":100,
    "Georgia":100,"Ukraine":250,
}
_vals = list(SQUAD_VALUES.values())
_med  = np.median(_vals)
def squad_adj(team):
    v = SQUAD_VALUES.get(team, _med)
    return 0.12 * math.log(v / _med)

# ── #2 + #4  IMPROVED ELO (opponent discount + recency decay) ────────────────
SEED_ELOS = {
    "Argentina":2108,"France":2101,"Spain":2045,"Brazil":2082,"England":2018,
    "Belgium":2026,"Portugal":2016,"Netherlands":1988,"Germany":1975,"Italy":1967,
    "Croatia":1950,"Uruguay":1942,"Denmark":1913,"Mexico":1887,"Colombia":1875,
    "Senegal":1871,"Morocco":1852,"Switzerland":1838,"USA":1820,"Japan":1815,
    "South Korea":1785,"Ecuador":1764,"Chile":1755,"Peru":1740,"Iran":1728,
    "Australia":1720,"Norway":1718,"Poland":1710,"Turkey":1710,"Austria":1700,
    "Algeria":1695,"Sweden":1690,"Egypt":1680,"Nigeria":1672,"Cameroon":1650,
    "Saudi Arabia":1628,"Serbia":1645,"Ghana":1637,"Tunisia":1619,"Paraguay":1605,
    "Scotland":1600,"Qatar":1575,"South Africa":1535,"Ivory Coast":1610,
    "Venezuela":1552,"Costa Rica":1540,"Panama":1490,"Bolivia":1440,"Wales":1600,
    "Bosnia":1520,"Slovakia":1530,"Greece":1540,"Georgia":1498,"Ukraine":1585,
    "Romania":1520,"Hungary":1535,"Canada":1660,"New Zealand":1340,"Iraq":1490,
    "Jordan":1420,"Uzbekistan":1380,"DR Congo":1410,"Haiti":1330,"Cape Verde":1395,
    "Curacao":1290,"Albania":1495,"Czechia":1575,"Slovenia":1510,"Israel":1490,
    "China":1440,"Indonesia":1380,"Bahrain":1390,"Jamaica":1430,"Vietnam":1370,
}
HOME_ADV=100; K_BASE=40; INIT_ELO=1500
HALF_LIFE_DAYS = 365*1.5

def days_ago(date_str, ref=None):
    from datetime import date
    if ref is None:
        ref = date.today().isoformat()
    y1,m1,d1 = map(int, date_str.split("-"))
    y2,m2,d2 = map(int, ref.split("-"))
    return (date(y2,m2,d2) - date(y1,m1,d1)).days

def compute_elos_improved(matches):
    r = dict(SEED_ELOS)
    for row in sorted(matches, key=lambda x: x[0]):
        date, home, away, hs, as_, tournament, neutral = row
        if home not in r: r[home] = INIT_ELO
        if away not in r: r[away] = INIT_ELO
        rh, ra = r[home], r[away]
        adj = rh + (0 if neutral else HOME_ADV)
        exp_h = 1/(1+10**((ra-adj)/400))
        out_h = 1.0 if hs>as_ else (0.0 if hs<as_ else 0.5)
        gd = abs(hs-as_)
        mov = math.log(gd+1)*2.2 if gd>0 else 1.0
        importance = TOURNAMENT_WEIGHTS.get(tournament, 1.0)
        elo_gap = abs(rh - ra)
        if tournament == "WC Qualifying" and elo_gap > 300:
            opp_discount = 1.0 / (1.0 + (elo_gap - 300)/400)
        else:
            opp_discount = 1.0
        d = days_ago(date)
        recency = 0.5 ** (d / HALF_LIFE_DAYS)
        k = min(K_BASE * importance * mov * opp_discount * recency, 100)
        r[home] = rh + k*(out_h - exp_h)
        r[away] = ra + k*((1-out_h) - (1-exp_h))
    return r

# ── #3  FAST DIXON-COLES — fully vectorised + L2 regularisation ──────────────
# L2 regularisation pulls sparse-data teams toward average, preventing
# qualifying blowout records (e.g. Norway 8-0-0) from over-inflating attack.
L2_REG = 0.30

def _build_rows(matches, idx):
    """Weighted, indexed match rows shared by the point fit and bootstrap fits."""
    rows = []
    for row in matches:
        date, home, away, hg, ag, tournament, neutral = row
        if home not in idx or away not in idx: continue
        importance = TOURNAMENT_WEIGHTS.get(tournament, 1.0)
        d = days_ago(date)
        w = (0.5 ** (d / HALF_LIFE_DAYS)) * importance
        rows.append((idx[home], idx[away], hg, ag, w, bool(neutral)))
    return rows


def _fit_rows(rows, teams, x0, maxiter=2000, w_scale=None):
    """Fit Dixon-Coles params on a fixed team index from a row list. Returns res.x.
    w_scale (optional) multiplies each row's weight — used by the Bayesian
    bootstrap to perturb weights without ever dropping a team's matches."""
    n = len(teams)
    hi  = np.array([r[0] for r in rows], dtype=np.int32)
    ai  = np.array([r[1] for r in rows], dtype=np.int32)
    hg  = np.array([r[2] for r in rows], dtype=np.float64)
    ag  = np.array([r[3] for r in rows], dtype=np.float64)
    w   = np.array([r[4] for r in rows], dtype=np.float64)
    if w_scale is not None:
        w = w * w_scale
    neut= np.array([r[5] for r in rows], dtype=bool)

    glh = gammaln(hg + 1)
    gla = gammaln(ag + 1)

    m00 = (hg==0) & (ag==0)
    m01 = (hg==0) & (ag==1)
    m10 = (hg==1) & (ag==0)
    m11 = (hg==1) & (ag==1)

    def neg_ll(params):
        atk  = params[:n];  dfn  = params[n:2*n]
        hadv = params[-2];  rho  = params[-1]

        bonus = np.where(neut, 0.0, hadv)
        lam = np.exp(atk[hi] + dfn[ai] + bonus)
        mu  = np.exp(atk[ai] + dfn[hi])
        lam = np.maximum(lam, 1e-6)
        mu  = np.maximum(mu,  1e-6)

        tau = np.ones(len(rows))
        tau[m00] = np.maximum(1 - lam[m00]*mu[m00]*rho, 1e-10)
        tau[m01] = np.maximum(1 + lam[m01]*rho,          1e-10)
        tau[m10] = np.maximum(1 + mu[m10]*rho,           1e-10)
        tau[m11] = np.maximum(1 - rho,                   1e-10)

        ll_h = hg * np.log(lam) - lam - glh
        ll_a = ag * np.log(mu)  - mu  - gla
        ll   = np.sum(w * (np.log(tau) + ll_h + ll_a))

        reg  = L2_REG * (np.dot(atk, atk) + np.dot(dfn, dfn))
        return -ll + reg

    return minimize(neg_ll, x0, method='Powell',
                    options={'maxiter':maxiter,'ftol':1e-6,'xtol':1e-5})


def _x0_from_elo(teams, elo_ratings):
    avg_elo = np.mean(list(elo_ratings.values()))
    x0_atk  = np.array([0.1*(elo_ratings.get(t,INIT_ELO)-avg_elo)/400 for t in teams])
    x0_def  = np.zeros(len(teams))
    return np.concatenate([x0_atk, x0_def, [0.1, -0.1]])


def _unpack(p, teams):
    n = len(teams)
    return {
        "attack":  {t: float(p[i])   for i,t in enumerate(teams)},
        "defense": {t: float(p[n+i]) for i,t in enumerate(teams)},
        "home_adv": float(p[-2]),
        "rho":      float(p[-1]),
    }


def fit_dc_fast(matches, elo_ratings):
    teams = sorted({m[1] for m in matches} | {m[2] for m in matches})
    idx = {t:i for i,t in enumerate(teams)}
    rows = _build_rows(matches, idx)
    res = _fit_rows(rows, teams, _x0_from_elo(teams, elo_ratings))
    out = _unpack(res.x, teams)
    out.update(teams=teams, converged=bool(res.success), fun=float(res.fun))
    return out


def fit_dc_bootstrap(matches, elo_ratings, point_dc, B=60, seed=42):
    """Bayesian-bootstrap the Dixon-Coles fit B times to capture parameter
    uncertainty. Each refit keeps EVERY match but multiplies its weight by a
    Dirichlet(1) draw (normalised to mean 1, so total weight — and thus the L2
    balance — is preserved). Unlike resampling-with-replacement this never drops
    a sparse team's scarce games, so it doesn't manufacture freak ratings.
    Warm-started from the point estimate for fast convergence."""
    teams = point_dc["teams"]
    idx = {t:i for i,t in enumerate(teams)}
    rows = _build_rows(matches, idx)
    x0 = np.concatenate([
        [point_dc["attack"][t]  for t in teams],
        [point_dc["defense"][t] for t in teams],
        [point_dc["home_adv"], point_dc["rho"]],
    ])
    rng = np.random.default_rng(seed)
    M = len(rows)
    ensemble = []
    for b in range(B):
        e = rng.exponential(1.0, size=M)
        w_scale = e / e.mean()          # Dirichlet weights, mean 1
        res = _fit_rows(rows, teams, x0, maxiter=1500, w_scale=w_scale)
        ensemble.append(_unpack(res.x, teams))
    return ensemble

# ── MAIN ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Fitting improved model (vectorised + L2 reg)...")
    t0 = time.time()

    elo = compute_elos_improved(MATCHES)
    top10 = sorted(elo.items(), key=lambda x:-x[1])[:10]
    print("\nTop 10 Elo:")
    for i,(t,v) in enumerate(top10,1): print(f"  {i:2}. {t:<22} {v:.0f}")

    print("\nFitting Dixon-Coles...")
    t1 = time.time()
    dc = fit_dc_fast(MATCHES, elo)
    print(f"  Converged: {dc['converged']}  LL: {dc['fun']:.2f}  ({time.time()-t1:.1f}s)")
    print(f"  Rho: {dc['rho']:.4f}  HomeAdv: {dc['home_adv']:.4f}")

    # Print top attack params to verify Norway is reined in
    top_atk = sorted(dc['attack'].items(), key=lambda x:-x[1])[:8]
    print("\n  Top attack params:")
    for t,v in top_atk: print(f"    {t:<22} {v:.4f}")

    # Bootstrap ensemble — captures parameter uncertainty for the simulator.
    B = int(os.environ.get("DC_BOOTSTRAP", "60"))
    print(f"\nBootstrapping {B} Dixon-Coles refits...")
    t2 = time.time()
    ensemble = fit_dc_bootstrap(MATCHES, elo, dc, B=B)
    print(f"  Done ({time.time()-t2:.1f}s)")

    def _round_dc(d):
        return {"attack":  {t: round(v,4) for t,v in d["attack"].items()},
                "defense": {t: round(v,4) for t,v in d["defense"].items()},
                "home_adv": round(d["home_adv"],4), "rho": round(d["rho"],4)}

    # model_params.json stays small (Elo + point estimate) and is committed
    # daily; the 60-member ensemble is large and derived, so it goes to its own
    # file that is regenerated every run and NOT committed (see .gitignore). This
    # keeps the git history from ballooning with ~35k-line ensemble churn 3×/day.
    with open("model_params.json","w") as f:
        json.dump({"elo": {t:round(v,2) for t,v in elo.items()}, "dc": dc}, f, indent=2)
    with open("dc_ensemble.json","w") as f:
        json.dump([_round_dc(m) for m in ensemble], f)

    print(f"\nTotal fit time: {time.time()-t0:.1f}s")
    print("Saved: model_params.json (slim) + dc_ensemble.json (uncommitted)")