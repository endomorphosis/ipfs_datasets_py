#!/usr/bin/env python3
"""Draw a leakage-safe Intent IR split.

The pilot draw is at most 1,024 train-eligible rows. ``--full-corpus`` splits
every train-eligible capsule row with the shingle blocking index.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.logic.intent_ir.training.skillcenter_campaign import (  # noqa: E402
    SkillCenterTrainingError,
    build_corpus_split,
    build_pilot_split,
    cache_root,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-dir", type=Path, default=None)
    parser.add_argument("--full-corpus", action="store_true")
    args = parser.parse_args(argv)
    campaign_dir = args.campaign_dir or cache_root()
    try:
        if args.full_corpus:
            payload = build_corpus_split(campaign_dir)
            print(f"corpus_rows={payload['corpus_row_count']} digest={payload['manifest_digest']}")
            return 0
        payload = build_pilot_split(campaign_dir)
    except SkillCenterTrainingError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"pilot_rows={payload['pilot_row_count']} digest={payload['manifest_digest']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
