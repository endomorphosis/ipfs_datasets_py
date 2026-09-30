#!/usr/bin/env python3
"""Evaluate the deterministic compiler and the from-scratch Intent feature state."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.logic.intent_ir.training.skillcenter_campaign import (  # noqa: E402
    cache_root,
    evaluate_features,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    receipt = evaluate_features(args.campaign_dir or cache_root())
    print(
        f"deterministic={len(receipt['arms']['deterministic_only'])} "
        f"unknown_atoms={receipt['unknown_atoms']} "
        f"formulas_generated={receipt['decoded_formulas_generated']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
