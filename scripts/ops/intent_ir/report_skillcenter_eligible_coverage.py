#!/usr/bin/env python3
"""Score ready SkillCenter envelopes that were not reservoir gradient steps."""

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
    report_eligible_coverage,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-dir", type=Path, default=None)
    parser.add_argument("--split", default="corpus_split.json")
    args = parser.parse_args(argv)
    try:
        receipt = report_eligible_coverage(
            args.campaign_dir or cache_root(),
            split_name=args.split,
        )
    except SkillCenterTrainingError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(
        f"inferred={receipt['inferred_source_count']} "
        f"unknown_atom_rows={receipt['rows_with_unknown_atoms']} "
        f"full_ready_columns={receipt['full_ready_view_column_count']} "
        f"within_feature_bound={receipt['full_ready_within_feature_bound']} "
        f"full_corpus_gradient={receipt['full_corpus_gradient']}"
    )
    print("ELIGIBLE_COVERAGE_DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
