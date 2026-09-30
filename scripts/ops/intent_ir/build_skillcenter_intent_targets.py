#!/usr/bin/env python3
"""Compile pilot Intent IR documents and census the feature vocabulary."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.logic.intent_ir.training.skillcenter_campaign import (  # noqa: E402
    build_targets,
    cache_root,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-dir", type=Path, default=None)
    parser.add_argument("--split", choices=("pilot_split.json", "corpus_split.json"), default="pilot_split.json")
    args = parser.parse_args(argv)
    census = build_targets(args.campaign_dir or cache_root(), split_name=args.split)
    print(
        f"ready={census['ready_count']} columns={census['column_count']} "
        f"sources={census['source_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
