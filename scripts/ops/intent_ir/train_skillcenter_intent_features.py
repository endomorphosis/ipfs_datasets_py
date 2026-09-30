#!/usr/bin/env python3
"""Train the native Intent IR feature candidate from the local pilot capsule."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.logic.intent_ir.training.skillcenter_campaign import (  # noqa: E402
    cache_root,
    train_features,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-dir", type=Path, default=None)
    parser.add_argument("--no-register", action="store_true")
    args = parser.parse_args(argv)
    receipt = train_features(args.campaign_dir or cache_root(), register=not args.no_register)
    print(
        f"state={receipt['state_sha256']} sources={receipt['training_source_count']} "
        f"qualified={receipt['qualified']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
