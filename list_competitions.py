"""
Discovers configured competitions (competitions/*.json), for a GitHub
Actions workflow to fan out over via a matrix strategy. Kept as a tiny
standalone script (not folded into competition_config.py) so the workflow's
discovery step is unit-testable like everything else in this project,
rather than an untested inline YAML/bash one-liner.

An optional `fmt` filters to competitions whose config's "format" field
matches exactly — needed once competitions/ started holding more than one
pipeline shape (round_robin leagues vs. league_phase_knockout cups): each
format's workflow calls a different, incompatible script chain, so a
workflow must only ever discover the slugs its own pipeline understands.
With no filter, behaviour is unchanged from before formats diverged (a pure
filename glob, configs not even parsed) — existing callers/tests that pass
no format keep working against configs that aren't even valid JSON yet.
"""
import glob
import json
import os
import sys


def list_competition_slugs(base_dir, fmt=None):
    """Sorted list of competition slugs found under base_dir. With no `fmt`,
    every competitions/<slug>.json file's slug is returned (filenames only,
    not parsed). With `fmt`, each config is loaded and only slugs whose
    config.format == fmt are returned."""
    pattern = os.path.join(base_dir, "competitions", "*.json")
    paths = sorted(glob.glob(pattern))
    if fmt is None:
        return [os.path.splitext(os.path.basename(p))[0] for p in paths]
    from competition_config import load_competition
    return sorted(
        config.slug
        for config in (load_competition(p) for p in paths)
        if config.format == fmt
    )


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    fmt = sys.argv[1] if len(sys.argv) > 1 else None
    slugs = list_competition_slugs(base_dir, fmt=fmt)
    print(json.dumps(slugs))


if __name__ == "__main__":
    main()
