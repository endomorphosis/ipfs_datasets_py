"""Stage capped Netherlands BWBR aliases. Dry-run unless --apply."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ipfs_datasets_py.processors.legal_data.legacy_migration import stage_netherlands


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-root", required=True)
    parser.add_argument("--ir-cids", required=True, help="Text file of IR entry CIDs, one per line")
    parser.add_argument("--output", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    cids = [
        line.strip()
        for line in Path(args.ir_cids).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    report = stage_netherlands(args.legacy_root, cids, args.output, apply=args.apply)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
