#!/usr/bin/env python3
"""Audit the immutable legacy-to-accepted autoencoder feature inventory."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_feature_inventory import (  # noqa: E402
    LegacyFeatureInventoryError,
    audit_legacy_feature_inventory,
    write_inventory_atomic,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--old-state",
        type=Path,
        required=True,
        help="Immutable legacy JSON state.",
    )
    parser.add_argument(
        "--new-state",
        type=Path,
        required=True,
        help="Accepted compact feature-transfer checkpoint.",
    )
    parser.add_argument(
        "--transfer-report",
        type=Path,
        required=True,
        help="Accepted transfer report bound by the checkpoint and canary.",
    )
    parser.add_argument(
        "--canary-report",
        type=Path,
        required=True,
        help="Immutable CUDA evaluation-canary report.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Destination for the source-free content-addressed inventory.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"refusing to overwrite output: {output}")
    try:
        inventory = audit_legacy_feature_inventory(
            args.old_state,
            args.new_state,
            args.transfer_report,
            args.canary_report,
            package_root=REPO_ROOT / "ipfs_datasets_py",
        )
        write_inventory_atomic(output, inventory)
    except LegacyFeatureInventoryError as exc:
        raise SystemExit(f"legacy feature inventory audit failed: {exc}") from exc
    counts = inventory["row_counts"]
    print(
        "audit_decision=verified_immutable_inputs "
        f"legacy_rows={counts['legacy_rows']} "
        f"accepted_rows={counts['accepted_rows']} "
        f"exact_rows={counts['transferable_exact']} "
        f"overridden_rows={counts['overridden']} "
        f"omitted_rows={counts['omitted']} "
        f"inventory_sha256={inventory['inventory_sha256']} "
        f"output={output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
