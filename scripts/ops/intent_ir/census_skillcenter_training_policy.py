#!/usr/bin/env python3
"""Classify SkillCenter corpus rows before any Intent IR training use."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.logic.intent_ir.training.skillcenter_campaign import (  # noqa: E402
    cache_root,
    census_policy,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    output = args.output_dir or cache_root()
    summary = census_policy(args.snapshot, output)
    print(json.dumps(summary["allowed_use"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
