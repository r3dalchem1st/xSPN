"""
Parser for openfootball's plaintext league fixture format (e.g.
openfootball/england/2026-27/1-premierleague.txt). This predates the JSON
mirror (openfootball/football.json) and is the only source available for
competitions that mirror hasn't caught up to yet.

Format recap (see any file under github.com/openfootball for real examples):
  = <competition name>
  # <metadata lines, ignored>
  ▪ <round label>
    <Weekday> <Mon> <Day>[ <Year>]      -- a date heading; year given only
                                           on its first appearance in the file
      [HH:MM]  <Team A>  v  <Team B>  [<hg>-<ag> (<hht>-<hat>)]
                                       -- time is omitted (line just indented
                                          to align) when it repeats the
                                          previous match's kickoff time;
                                          score+half-time suffix is present
                                          only for a played match

Known gap: openfootball/england's 2023-24 season and earlier use an OLDER
format revision this parser does not handle (score sits between the teams
with no "v", no 2-space date indent, no year on the first date line) — such
a file silently parses to zero matches rather than raising. Confirmed via
2023-24/1-premierleague.txt during Task 5's live smoke test; 2024-25 onward
all use the format above. If older seasons are ever needed, this needs a
second parsing branch — not attempted here, since 2+ recent seasons already
give ample training data given the model's ~1.5yr Elo/DC recency half-life.

Knockout-tie scores (two-legged cup ties, single-match finals) add extra
tokens after the base score, confirmed against real 2025-26 UEFA Champions
League data: "3-2 a.e.t. (3-0, 1-0)" when extra time decided the match
outright, or "4-3 pen. 1-1 a.e.t. (1-1, 0-1)" when a shootout was needed
(the leading score there is the shootout tally, not goals — the true final
score, including any extra-time goals, is the one right before "a.e.t.").
The regulation/half-time breakdown in the trailing parens is parsed but not
returned — nothing downstream needs it. Before this was handled, such lines
simply failed to match and were silently dropped (same "match line we don't
recognise -> skip" fallback that already existed for stray metadata lines),
which would have quietly lost every extra-time/shootout result in a
knockout competition.
"""
import re

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}

_DATE_RE = re.compile(r'^\s{2}(\w{3}) (\w{3}) (\d{1,2})(?: (\d{4}))?\s*$')
_MATCH_RE = re.compile(
    r'^\s*(?:\d{2}:\d{2}\s+)?(.+?)\s+v\s+(.+?)'
    r'(?:\s{2,}'
    r'(?:(\d+)-(\d+)\s+pen\.\s+)?'              # shootout score, if any
    r'(\d+)-(\d+)'                              # true final score (goals)
    r'(?:\s+a\.e\.t\.)?'
    r'(?:\s*\(\d+-\d+(?:,\s*\d+-\d+)?\))?'      # regulation/HT breakdown, discarded
    r')?'
    r'\s*$'
)


def parse_openfootball_txt(text):
    """Parse an openfootball league .txt fixture file into a list of
    {"round": str | None, "date": "YYYY-MM-DD", "home": str, "away": str,
     "score": (int, int) | None} dicts, in file order.

    Raises ValueError if a match line appears before any date line."""
    matches = []
    current_round = None
    current_date = None
    current_year = None
    current_month = None

    for line in text.splitlines():
        if not line.strip():
            continue
        if line.startswith('▪'):
            current_round = line.lstrip('▪').strip()
            continue
        if line.startswith('=') or line.startswith('#'):
            continue

        date_m = _DATE_RE.match(line)
        if date_m:
            _, mon_str, day_str, year_str = date_m.groups()
            month = _MONTHS[mon_str]
            if year_str:
                current_year = int(year_str)
            elif current_year is None:
                raise ValueError(f"date line has no year and none seen yet: {line!r}")
            elif current_month is not None and month < current_month:
                current_year += 1  # season crossed a Dec -> Jan boundary
            current_month = month
            current_date = f"{current_year:04d}-{month:02d}-{int(day_str):02d}"
            continue

        if ' v ' not in line:
            continue  # metadata/blank-ish line we don't otherwise recognise
        match_m = _MATCH_RE.match(line)
        if not match_m:
            continue
        if current_date is None:
            raise ValueError(f"match line before any date line: {line!r}")
        home, away, pen_hg, pen_ag, hg, ag = match_m.groups()
        score = (int(hg), int(ag)) if hg is not None else None
        match = {
            "round": current_round, "date": current_date,
            "home": home.strip(), "away": away.strip(), "score": score,
        }
        if pen_hg is not None:
            match["pen_score"] = (int(pen_hg), int(pen_ag))
        matches.append(match)
    return matches
