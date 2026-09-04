"""
Competition configuration schema + loader.

A CompetitionConfig describes everything format-agnostic pipeline code needs
to know about one competition: its format, where its fixture data lives, and
how to resolve external team-name spellings to a canonical name. Config files
are plain JSON under competitions/<slug>.json; this module is the only place
that knows the on-disk schema, so a new competition never requires touching
Python code — just adding a JSON file.
"""
import json
import os

REQUIRED_FIELDS = [
    "slug", "name", "format", "openfootball_repo", "openfootball_files", "team_aliases",
]
VALID_FORMATS = {"round_robin", "groups_then_knockout", "knockout_only", "league_phase_knockout"}


class CompetitionConfig:
    def __init__(self, data):
        missing = [f for f in REQUIRED_FIELDS if f not in data]
        if missing:
            raise ValueError(f"competition config missing required field(s): {missing}")
        if data["format"] not in VALID_FORMATS:
            raise ValueError(
                f"unknown format {data['format']!r}, must be one of {sorted(VALID_FORMATS)}"
            )
        if not data["openfootball_files"]:
            raise ValueError("openfootball_files must list at least one season (newest first)")
        self.slug = data["slug"]
        self.name = data["name"]
        self.format = data["format"]
        self.openfootball_repo = data["openfootball_repo"]
        self.openfootball_files = data["openfootball_files"]
        self.team_aliases = data["team_aliases"]
        self.teams = data.get("teams")  # optional explicit roster whitelist
        self.extra_training_sources = data.get("extra_training_sources", [])
        # Optional football-data.org competition code (e.g. "PD" for La Liga).
        # Only set for competitions on football-data.org's free tier -- lets
        # fetch_live_scores.py patch in fast official results on top of
        # openfootball's fixtures/training data, which volunteers can take
        # days to update with a played match's score. None -> no live overlay.
        self.football_data_code = data.get("football_data_code")
        # Optional H/D/A calibration for the round-robin/cup prediction path
        # (league_calibration.py + sim_league.py/snapshot_league.py). Defaults
        # are each function's own no-op value, so an unset competition behaves
        # exactly as before these existed. Real values come from grid-searching
        # backtest_league.py against a competition's own historical seasons —
        # never guessed or copied from the WC's own (differently-tuned) values.
        self.strength_shrink = data.get("strength_shrink", 1.0)
        self.draw_inflate = data.get("draw_inflate", 0.0)
        self.use_rho = data.get("use_rho", False)
        # Optional recent-form signal (league_calibration.compute_momentum),
        # applied only to match-level H/D/A prediction (snapshot_league.py
        # and friends), not sim_league.py's season simulation -- see that
        # module's own docstring for why. momentum_weight=0.0 (default) is
        # a no-op; real values come from backtest_league.py's
        # --momentum-grid, selected to not regress raw winner accuracy even
        # when a larger weight would score better on Brier alone.
        self.momentum_weight = data.get("momentum_weight", 0.0)
        self.momentum_n = data.get("momentum_n", 5)

    def resolve_team(self, raw_name):
        """Canonical team name for a raw name from the data source. Applies
        the alias map first, then — if an explicit roster is configured —
        rejects (returns None) any name still not on the roster. With no
        roster configured, any aliased-or-passthrough name is accepted."""
        canonical = self.team_aliases.get(raw_name, raw_name)
        if self.teams is not None and canonical not in self.teams:
            return None
        return canonical


def load_competition(path):
    """Load and validate a competition config JSON file.
    Raises ValueError on schema violations, FileNotFoundError if missing."""
    with open(path) as f:
        data = json.load(f)
    return CompetitionConfig(data)


def artifact_dir(config, base_dir):
    """Directory where this competition's fetched/derived JSON artifacts
    live: <base_dir>/competitions/<slug>/. Created if missing."""
    d = os.path.join(base_dir, "competitions", config.slug)
    os.makedirs(d, exist_ok=True)
    return d
