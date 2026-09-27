"""Stage Caselaw centroid and opinion-CID indexes. Dry-run unless --apply."""

from __future__ import annotations

import argparse
import json

from ipfs_datasets_py.processors.legal_data.legacy_migration import stage_caselaw


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--text-pin", default="")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    report = stage_caselaw(
        args.checkout_root,
        args.output,
        apply=args.apply,
        text_pin=args.text_pin,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
