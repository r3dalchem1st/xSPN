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
VALID_FORMATS = {"round_robin", "groups_then_knockout", "knockout_only"}


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
