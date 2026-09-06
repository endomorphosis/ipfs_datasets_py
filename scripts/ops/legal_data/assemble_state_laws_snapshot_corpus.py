#!/usr/bin/env python3
"""Assemble a non-authorizing snapshot corpus onto the OUL canonical row shape.

Remaining seven states (NY WI TN AR NH MS GA) must come from the /tmp/tmp_laws
ingest. Destinations that look like live acquisition-evidence are refused.
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
    DEFAULT_CORPUS_ROOT,
    DEFAULT_INVENTORY_PATH,
    DEFAULT_JSONLD_ROOT,
    DEFAULT_TMP_LAWS,
    DEFAULT_VAQUILL_ROOT,
    SnapshotGraphragError,
    assemble_corpus,
    inventory_all,
    refuse_authorizing_for_publication,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tmp-laws", type=Path, default=DEFAULT_TMP_LAWS)
    parser.add_argument("--vaquill-root", type=Path, default=DEFAULT_VAQUILL_ROOT)
    parser.add_argument("--jsonld-root", type=Path, default=DEFAULT_JSONLD_ROOT)
    parser.add_argument("--inventory", type=Path, default=None)
    parser.add_argument("--dest", type=Path, default=DEFAULT_CORPUS_ROOT)
    parser.add_argument(
        "--authorizing-for-publication",
        action="store_true",
        help="Rejected. Snapshot assembly cannot authorize Hub publication.",
    )
    parser.add_argument("--print-json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    refuse_authorizing_for_publication(bool(args.authorizing_for_publication))
    if args.inventory is not None:
        inventory = json.loads(args.inventory.expanduser().read_text(encoding="utf-8"))
    else:
        inventory = inventory_all(
            tmp_laws=args.tmp_laws.expanduser(),
            vaquill_root=args.vaquill_root.expanduser(),
            jsonld_root=args.jsonld_root.expanduser(),
        )
    try:
        summary = assemble_corpus(inventory, dest_root=args.dest.expanduser().resolve())
    except SnapshotGraphragError as exc:
        raise SystemExit(str(exc)) from exc
    if args.print_json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(
            f"assembled {summary.get('assembled_row_count')} rows under "
            f"{summary.get('dest_root')} authorizing_for_publication=false"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
