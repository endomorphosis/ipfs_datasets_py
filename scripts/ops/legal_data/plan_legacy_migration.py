"""Inventory local legacy corpora. Does not stage or migrate."""

from __future__ import annotations

import argparse

from ipfs_datasets_py.processors.legal_data.legacy_migration import (
    plan_legacy_migration,
    write_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout-root", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    write_report(args.report, plan_legacy_migration(args.checkout_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
