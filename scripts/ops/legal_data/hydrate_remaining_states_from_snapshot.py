#!/usr/bin/env python3
"""Copy remaining-state snapshot statutes into local hydrate staging.

The operator may want these dumps treated as official Hub-authorizing
current-bundle. This program refuses that label.

Release policy still requires an official source receipt and a closed
frontier per jurisdiction. FindLaw, Vaquill point-in-time dumps, and
Senate PDFs without event-proof closure do not satisfy that contract.
Lack of residential proxies explains why live official fetches fail; it
does not convert a third-party snapshot into an official receipt.

Outputs are local NormalizedStatute JSONL only. They are not written into
live acquisition-evidence dests and do not authorize Hub mutation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).resolve()
WORKTREE = HERE.parents[3]
if str(WORKTREE) not in sys.path:
    sys.path.insert(0, str(WORKTREE))

REMAINING_STATES = ("AR", "GA", "MS", "NH", "NY", "TN", "WI")
LIVE_FETCH_BLOCKED_REASON = "residential_proxy_not_used"
REFUSAL = (
    "Release policy requires official_source_receipt_required_per_jurisdiction "
    "and closed_frontier_required_per_jurisdiction. Snapshot dumps, FindLaw, "
    "and unclosed NY event residuals cannot authorize Hub publication."
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _count_rows(path: Path) -> int:
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def hydrate_state(
    *,
    state_code: str,
    source: Path,
    output_root: Path,
) -> Dict[str, Any]:
    dest = output_root / f"staging-{state_code.lower()}-snapshot-hydrate"
    if dest.exists():
        raise RuntimeError(f"REFUSING dest exists: {dest}")
    statutes_src = source / state_code / "statutes.jsonl"
    if not statutes_src.is_file():
        raise RuntimeError(f"missing snapshot statutes for {state_code}: {statutes_src}")
    dest.mkdir(parents=True)
    statutes_dest = dest / "statutes.jsonl"
    shutil.copy2(statutes_src, statutes_dest)
    receipt = {
        "schema": "ipfs_datasets_py.state_laws.snapshot_hydrate.v1",
        "jurisdiction": state_code,
        "authorizing_for_publication": False,
        "authorizing_hub_upload": False,
        "current_bundle": False,
        "official_source_receipt": False,
        "closed_frontier": False,
        "live_official_fetch_blocked_reason": LIVE_FETCH_BLOCKED_REASON,
        "hub_authorization_refused": REFUSAL,
        "source_path": str(statutes_src),
        "source_sha256": _sha256_file(statutes_src),
        "output_path": str(statutes_dest),
        "output_sha256": _sha256_file(statutes_dest),
        "statute_count": _count_rows(statutes_dest),
        "hydrated_at": _utc_now(),
    }
    (dest / "hydration_receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--snapshot-root",
        type=Path,
        default=Path.home()
        / ".ipfs_datasets"
        / "state_laws"
        / "vaquill-snapshot-normalized-v2026.08.31",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path.home() / ".ipfs_datasets" / "state_laws",
    )
    parser.add_argument(
        "--authorizing-for-publication",
        action="store_true",
        help="Rejected. Snapshot dumps cannot authorize Hub publication.",
    )
    args = parser.parse_args()
    if args.authorizing_for_publication:
        raise SystemExit("REFUSING Hub authorization: " + REFUSAL)

    snapshot_root = args.snapshot_root.resolve()
    output_root = args.output_root.resolve()
    forbidden = (
        "acquisition-evidence",
        "live-v",
        "current-live",
        "permanently-nonauthorizing",
    )
    if any(token in str(output_root.name) for token in forbidden):
        raise SystemExit(f"REFUSING output root looks like a live dest: {output_root}")

    receipts: List[Dict[str, Any]] = []
    for code in REMAINING_STATES:
        receipts.append(
            hydrate_state(
                state_code=code,
                source=snapshot_root,
                output_root=output_root,
            )
        )
    manifest = {
        "schema": "ipfs_datasets_py.state_laws.snapshot_hydrate.v1",
        "authorizing_for_publication": False,
        "authorizing_hub_upload": False,
        "current_bundle": False,
        "live_official_fetch_blocked_reason": LIVE_FETCH_BLOCKED_REASON,
        "hub_authorization_refused": REFUSAL,
        "snapshot_root": str(snapshot_root),
        "output_root": str(output_root),
        "hydrated_at": _utc_now(),
        "states": receipts,
    }
    manifest_path = output_root / "snapshot-hydrate-remaining-v2026.08.31.manifest.json"
    if manifest_path.exists():
        raise SystemExit(f"REFUSING manifest exists: {manifest_path}")
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
