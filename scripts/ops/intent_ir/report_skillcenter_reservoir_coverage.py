#!/usr/bin/env python3
"""Score train rows that were not gradient steps in the 1,024-source reservoir."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.logic.intent_ir.training.skillcenter_campaign import (  # noqa: E402
    SkillCenterTrainingError,
    cache_root,
    report_reservoir_coverage,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-dir", type=Path, default=None)
    parser.add_argument("--split", choices=("pilot_split.json", "corpus_split.json"), default="corpus_split.json")
    args = parser.parse_args(argv)
    census_name = (
        "vocabulary_census.json" if args.split == "pilot_split.json" else "corpus_vocabulary_census.json"
    )
    try:
        receipt = report_reservoir_coverage(
            args.campaign_dir or cache_root(),
            split_name=args.split,
            census_name=census_name,
        )
    except SkillCenterTrainingError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(
        f"reservoir={receipt['reservoir_source_count']} "
        f"inferred={receipt['inferred_source_count']} "
        f"full_corpus_gradient={receipt['full_corpus_gradient']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
