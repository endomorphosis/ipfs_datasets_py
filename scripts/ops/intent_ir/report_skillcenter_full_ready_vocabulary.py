#!/usr/bin/env python3
"""Choose the verb frequency that fits every ready SkillCenter envelope."""

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
    report_full_ready_vocabulary,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-dir", type=Path, default=None)
    parser.add_argument("--split", default="corpus_split.json")
    args = parser.parse_args(argv)
    try:
        receipt = report_full_ready_vocabulary(
            args.campaign_dir or cache_root(),
            split_name=args.split,
        )
    except SkillCenterTrainingError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(
        f"min_verb_documents={receipt['min_verb_documents']} "
        f"kept_verbs={receipt['kept_verb_count']} "
        f"columns={receipt['view_column_count']} "
        f"within_feature_bound={receipt['within_feature_bound']} "
        f"full_corpus_gradient={receipt['full_corpus_gradient']}"
    )
    print("FULL_READY_VOCABULARY_DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
