"""
Pure math for converting bookmaker decimal odds into a fair (de-vigged)
H/D/A probability triple -- independent of which odds provider supplies the
raw numbers, so this doesn't need to change once a real feed (The Odds API
or otherwise) is wired in.

A bookmaker's quoted odds always sum to slightly MORE than "fair" (their
margin, aka the "overround" or "vig") -- e.g. three roughly-50/33/17%
outcomes might be quoted at odds implying 53/35/18%, summing to 106%. The
simple, standard correction (used here) is multiplicative: convert each
odd to a raw implied probability (1/odds), then divide every one by the
sum so they add back to exactly 1.0. This is the same baseline approach
published sports-forecasting research uses before any fancier method
(Shin's method, the power method) -- not attempted here since there's no
real odds data yet to validate a fancier correction against; upgrade this
once backtest_league.py can score it against real fixtures the way
strength_shrink/draw_inflate/momentum already were.
"""


def implied_probs_from_odds(home_odds, draw_odds, away_odds):
    """De-vigged (P(home), P(draw), P(away)) from three decimal odds (e.g.
    2.10 means a $1 stake returns $2.10 total). Raises ValueError for a
    non-positive odd -- there's no sane way to imply a probability from it,
    and silently producing a nonsensical negative/infinite probability
    would be worse than failing loudly."""
    if home_odds <= 0 or draw_odds <= 0 or away_odds <= 0:
        raise ValueError(f"odds must be positive: got {(home_odds, draw_odds, away_odds)}")
    raw = (1.0 / home_odds, 1.0 / draw_odds, 1.0 / away_odds)
    overround = sum(raw)
    return tuple(p / overround for p in raw)


def overround(home_odds, draw_odds, away_odds):
    """The bookmaker's total margin as a fraction (e.g. 0.06 = 6% overround).
    Useful as a sanity check on a live feed -- a real bookmaker's H/D/A
    market is almost always in roughly the 1.02-1.12 range; a value far
    outside that on real data suggests a parsing bug, not a weird market."""
    return (1.0 / home_odds) + (1.0 / draw_odds) + (1.0 / away_odds) - 1.0
