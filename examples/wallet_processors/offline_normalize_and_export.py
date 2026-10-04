#!/usr/bin/env python3
"""Build synthetic normalized ledger records and export JSONL offline.

Uses only fixture-style synthetic addresses (repeating 0x11… / 0x22… patterns).
Does not sign, broadcast, or contact providers.

Usage:
    python offline_normalize_and_export.py
    python offline_normalize_and_export.py --output-dir /tmp/wallet-export-demo
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_EXAMPLES_DIR = Path(__file__).resolve().parent
if str(_EXAMPLES_DIR) not in sys.path:
    sys.path.insert(0, str(_EXAMPLES_DIR))

from _common import (  # noqa: E402
    ETHEREUM_MAINNET_GENESIS,
    SYNTHETIC_BLOCK_HASH,
    SYNTHETIC_EVM_ADDRESS_A,
    SYNTHETIC_EVM_ADDRESS_B,
    SYNTHETIC_TX_HASH,
    refuse_network_unless_opted_in,
)


def _build_records():
    from ipfs_datasets_py.processors.wallets.models import (
        AccountKind,
        AccountRef,
        AssetKind,
        AssetRef,
        ChainRef,
        ExactAmount,
        Finality,
        LedgerPosition,
        Provenance,
        TransactionRecord,
        TransactionStatus,
        TransferKind,
        TransferRecord,
    )

    now = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    chain = ChainRef(
        namespace="eip155",
        network="ethereum-mainnet",
        chain_id="1",
        genesis_hash=ETHEREUM_MAINNET_GENESIS,
    )
    source = AccountRef(chain, SYNTHETIC_EVM_ADDRESS_A, AccountKind.ADDRESS)
    dest = AccountRef(chain, SYNTHETIC_EVM_ADDRESS_B, AccountKind.ADDRESS)
    asset = AssetRef(
        chain,
        asset_namespace="slip44",
        asset_reference="60",
        decimals=18,
        kind=AssetKind.NATIVE,
        symbol="ETH",
    )
    provenance = Provenance(
        provider="offline-example",
        provider_kind="fixture",
        request_id="offline-normalize-export-1",
        scope="wallet:synthetic-demo",
        observed_at=now,
    )
    position = LedgerPosition(
        sequence=19_000_001,
        hash=SYNTHETIC_BLOCK_HASH,
        transaction_index=0,
    )
    tx = TransactionRecord(
        chain=chain,
        provenance=provenance,
        ledger_position=position,
        finality=Finality.FINALIZED,
        transaction_hash=SYNTHETIC_TX_HASH,
        status=TransactionStatus.SUCCEEDED,
        participants=(source, dest),
        fee=ExactAmount.from_int(21_000, decimals=18),
    )
    transfer = TransferRecord(
        chain=chain,
        provenance=provenance,
        ledger_position=LedgerPosition(
            sequence=19_000_001,
            hash=SYNTHETIC_BLOCK_HASH,
            transaction_index=0,
            event_index=0,
        ),
        finality=Finality.FINALIZED,
        transaction_hash=SYNTHETIC_TX_HASH,
        transfer_index=0,
        asset=asset,
        amount=ExactAmount.from_int(10**18, decimals=18),
        source_account=source,
        destination_account=dest,
        transfer_kind=TransferKind.NATIVE,
    )
    return chain, [tx, transfer]


def main(argv: list[str] | None = None) -> int:
    refuse_network_unless_opted_in(argv)

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for JSONL + summary (default: temporary directory).",
    )
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="Network opt-in flag (also requires WALLET_PROCESSORS_ALLOW_NETWORK=1).",
    )
    args = parser.parse_args(argv)

    from ipfs_datasets_py.processors.wallets.export import write_jsonl

    chain, records = _build_records()

    if args.output_dir is None:
        tmp = tempfile.TemporaryDirectory(prefix="wallet-proc-example-")
        out_dir = Path(tmp.name)
        cleanup = tmp
    else:
        out_dir = args.output_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        cleanup = None

    try:
        part_path = out_dir / "part-000.jsonl"
        partition = write_jsonl(records, part_path)
        summary = {
            "offline": True,
            "chain": chain.to_dict(),
            "record_count": partition.record_count,
            "partition_digest": partition.digest,
            "partition_path": str(part_path),
            "record_ids": [r.record_id for r in records],
            "note": (
                "Synthetic fixture addresses only; no signing or broadcast; "
                "no live provider calls."
            ),
            "identity_reminders": {
                "World ID": "protocol — not exported as ledger rows here",
                "World Chain": "use family world-chain for L2 ledger scans",
                "WLD": "asset identity on World Chain mainnet (chain id 480)",
                "XRPL": "classic ledger family xrpl",
                "Xaman": "payload family xaman composed over XRPL",
            },
        }
        summary_path = out_dir / "export_summary.json"
        summary_path.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(summary, indent=2, sort_keys=True))
        print(f"\nWrote {part_path} and {summary_path}", file=sys.stderr)
    finally:
        if cleanup is not None:
            cleanup.cleanup()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
