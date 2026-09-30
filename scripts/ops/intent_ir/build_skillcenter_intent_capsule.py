#!/usr/bin/env python3
"""Normalize policy-eligible SkillCenter rows into content-addressed Intent IR."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.logic.intent_ir.training.skillcenter_campaign import (  # noqa: E402
    build_intent_capsule,
    cache_root,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--campaign-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    summary = build_intent_capsule(args.snapshot, args.campaign_dir or cache_root())
    print(
        f"documents={summary['document_count']} "
        f"train={summary['train_documents']} eval={summary['eval_documents']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
