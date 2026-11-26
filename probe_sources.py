"""ONE-OFF probe (delete after use): what do our football-data.org and API-Football keys
return for the 2026-27 Champions League and Copa del Rey? Prints counts, names and dates
only -- never a key, and never the account block API-Football returns."""
import json
import os
import time
import urllib.error
import urllib.request
from collections import Counter


def get(base, path, headers):
    req = urllib.request.Request(base + path, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, dict(r.headers), json.load(r)
    except urllib.error.HTTPError as e:
        try:
            body = json.load(e)
        except Exception:
            body = {"message": "unparseable error body"}
        return e.code, dict(e.headers), body
    except Exception as e:                                   # network etc.
        return None, {}, {"message": repr(e)}


def ours():
    """Team names in our current CL schedule (2025-26 openfootball), to test name matching."""
    with open("competitions/champions_league/league_schedule.json", encoding="utf-8") as f:
        sched = json.load(f)
    return {t for k in sched for t in k.split("|")}


def football_data():
    print("=" * 20, "football-data.org")
    key = os.environ.get("FD_API_KEY")
    if not key:
        print("FD_API_KEY not set")
        return
    base, h = "https://api.football-data.org/v4", {"X-Auth-Token": key}

    s, _, b = get(base, "/competitions", h)
    comps = b.get("competitions", [])
    print("competitions visible to this key:", s, len(comps))
    print("  ", [(c.get("code"), c.get("name"), c.get("plan")) for c in comps])
    print("   Copa-like:", [(c.get("code"), c.get("name")) for c in comps if "copa" in c.get("name", "").lower()
                            or "cup" in c.get("name", "").lower()])
    time.sleep(7)

    s, _, b = get(base, "/competitions/CL", h)
    if s != 200:
        print("CL meta:", s, b.get("message"))
    else:
        print("CL meta:", {k: b.get(k) for k in ("name", "code", "type")}, "currentSeason:", b.get("currentSeason"))
    time.sleep(7)

    ours_names = ours()
    for season in (2026, 2025, 2024):
        s, _, b = get(base, f"/competitions/CL/matches?season={season}", h)
        ms = b.get("matches", [])
        print(f"CL season={season}: HTTP {s}, {len(ms)} matches", "" if s == 200 else b.get("message"))
        if ms:
            print("   status:", dict(Counter(m["status"] for m in ms)), "| stage:", dict(Counter(m["stage"] for m in ms)))
            dates = sorted(m["utcDate"][:10] for m in ms)
            print("   dates:", dates[0], "->", dates[-1], "| matchdays:", sorted({m.get("matchday") for m in ms if m.get("matchday")}))
            names = sorted({t["name"] for m in ms for t in (m["homeTeam"], m["awayTeam"]) if t.get("name")})
            print(f"   {len(names)} team names; NOT in our 2025-26 CL schedule:", [n for n in names if n not in ours_names])
            fin = [m for m in ms if m["status"] == "FINISHED"][:2]
            for m in fin:
                print("   sample finished:", m["utcDate"][:10], m["homeTeam"]["name"], m["score"]["fullTime"], m["awayTeam"]["name"])
            nxt = [m for m in ms if m["status"] in ("SCHEDULED", "TIMED")][:2]
            for m in nxt:
                print("   sample upcoming:", m["utcDate"][:10], m["homeTeam"]["name"], "v", m["awayTeam"]["name"], m["stage"])
        time.sleep(7)


def api_football():
    print("=" * 20, "API-Football")
    key = os.environ.get("API_FOOTBALL_KEY")
    if not key:
        print("API_FOOTBALL_KEY not set")
        return
    base, h = "https://v3.football.api-sports.io", {"x-apisports-key": key}

    s, hd, b = get(base, "/status", h)
    r = b.get("response")
    if isinstance(r, dict):
        print("status:", s, "| plan:", (r.get("subscription") or {}).get("plan"), "| active:",
              (r.get("subscription") or {}).get("active"), "| requests:", r.get("requests"))
    else:
        print("status:", s, "| errors:", b.get("errors"))

    for lid, label in ((143, "Copa del Rey"), (2, "Champions League")):
        s, hd, b = get(base, f"/leagues?id={lid}", h)
        for lg in b.get("response", []):
            print(f"{label} (id {lid}):", lg["league"]["name"], "| seasons offered:",
                  [(x.get("year"), "current" if x.get("current") else "") for x in lg["seasons"][-5:]])
            print("   latest-season coverage:", lg["seasons"][-1].get("coverage"))
        if not b.get("response"):
            print(f"{label} /leagues:", s, b.get("errors"))
        for season in (2026, 2025):
            s, hd, b = get(base, f"/fixtures?league={lid}&season={season}", h)
            rs = b.get("response", [])
            print(f"  {label} season={season}: HTTP {s}, results={b.get('results')}, errors={b.get('errors')}")
            if rs:
                print("     rounds:", dict(Counter(x["league"]["round"] for x in rs)))
                print("     status:", dict(Counter(x["fixture"]["status"]["short"] for x in rs)))
                for x in rs[:2]:
                    print("     sample:", x["fixture"]["date"][:10], x["teams"]["home"]["name"], "v", x["teams"]["away"]["name"],
                          x["fixture"]["status"]["short"], x["goals"])
        print("  requests left today:", hd.get("x-ratelimit-requests-remaining") or hd.get("X-RateLimit-requests-Remaining"))


if __name__ == "__main__":
    football_data()
    api_football()
