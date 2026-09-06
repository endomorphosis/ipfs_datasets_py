#!/usr/bin/env python3
"""Read-only inventory of snapshot GraphRAG inputs for all 51 jurisdictions.

NY/WI/TN/AR/NH/MS/GA are bound to /tmp/tmp_laws. Other states use LCR JSON-LD
when it is not a stub. This command never authorizes publication.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
WORKTREE = HERE.parents[3]
if str(WORKTREE) not in sys.path:
    sys.path.insert(0, str(WORKTREE))

from ipfs_datasets_py.processors.legal_data.state_laws_snapshot_graphrag import (  # noqa: E402
    DEFAULT_INVENTORY_PATH,
    DEFAULT_JSONLD_ROOT,
    DEFAULT_TMP_LAWS,
    DEFAULT_VAQUILL_ROOT,
    inventory_all,
    refuse_authorizing_for_publication,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tmp-laws", type=Path, default=DEFAULT_TMP_LAWS)
    parser.add_argument("--vaquill-root", type=Path, default=DEFAULT_VAQUILL_ROOT)
    parser.add_argument("--jsonld-root", type=Path, default=DEFAULT_JSONLD_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_INVENTORY_PATH)
    parser.add_argument(
        "--authorizing-for-publication",
        action="store_true",
        help="Rejected. Snapshot inventory cannot authorize Hub publication.",
    )
    parser.add_argument("--print-json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    refuse_authorizing_for_publication(bool(args.authorizing_for_publication))
    report = inventory_all(
        tmp_laws=args.tmp_laws.expanduser(),
        vaquill_root=args.vaquill_root.expanduser(),
        jsonld_root=args.jsonld_root.expanduser(),
    )
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.print_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        counts = report.get("chosen_source_counts") or {}
        print(
            f"inventory {output} tmp_laws={counts.get('tmp_laws')} "
            f"lcr_jsonld={counts.get('lcr_jsonld')} gap={counts.get('gap')} "
            f"authorizing_for_publication=false"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
