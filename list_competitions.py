"""
Discovers all configured competitions (competitions/*.json), for the
GitHub Actions workflow to fan out over via a matrix strategy. Kept as a
tiny standalone script (not folded into competition_config.py) so the
workflow's discovery step is unit-testable like everything else in this
project, rather than an untested inline YAML/bash one-liner.
"""
import glob
import json
import os


def list_competition_slugs(base_dir):
    """Sorted list of competition slugs — one per competitions/<slug>.json
    file found under base_dir. Sorted for deterministic output (matters for
    reproducible CI matrix ordering, not just cosmetic)."""
    pattern = os.path.join(base_dir, "competitions", "*.json")
    return sorted(
        os.path.splitext(os.path.basename(p))[0]
        for p in glob.glob(pattern)
    )


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    slugs = list_competition_slugs(base_dir)
    print(json.dumps(slugs))


if __name__ == "__main__":
    main()
