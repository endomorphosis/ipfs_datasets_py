"""Stage municipal compact indexes. Dry-run unless --apply is set."""

from __future__ import annotations

import argparse
import json

from ipfs_datasets_py.processors.legal_data.legacy_migration import stage_municipal


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(stage_municipal(args.source, args.output, apply=args.apply), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
