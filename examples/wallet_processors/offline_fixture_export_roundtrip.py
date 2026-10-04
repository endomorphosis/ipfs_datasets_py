#!/usr/bin/env python3
"""Round-trip shared wallet export fixtures through write_jsonl (offline).

Reads synthetic records from tests/fixtures/wallets/_shared and demonstrates
deterministic partition digests without network access.

Usage:
    python offline_fixture_export_roundtrip.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_EXAMPLES_DIR = Path(__file__).resolve().parent
if str(_EXAMPLES_DIR) not in sys.path:
    sys.path.insert(0, str(_EXAMPLES_DIR))

from _common import refuse_network_unless_opted_in  # noqa: E402


def _repo_fixtures() -> Path:
    # examples/wallet_processors -> examples -> ipfs_datasets_py -> repo? or package root
    # Path: ipfs_datasets_py/examples/wallet_processors/this_file
    package_root = Path(__file__).resolve().parents[2]
    fixtures = package_root / "tests" / "fixtures" / "wallets" / "_shared" / "export_sample_records.json"
    if not fixtures.is_file():
        raise FileNotFoundError(f"Missing fixture file: {fixtures}")
    return fixtures


def _records_from_fixture(payload: dict):
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

    chain_data = payload["chain"]
    chain = ChainRef(
        namespace=chain_data["namespace"],
        network=chain_data["network"],
        chain_id=chain_data["chain_id"],
        genesis_hash=chain_data["genesis_hash"],
    )
    now = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    provenance = Provenance(
        provider="fixture-export-sample",
        provider_kind="fixture",
        request_id="offline-fixture-roundtrip",
        scope=f"wallet:{payload['account']}",
        observed_at=now,
    )
    account = AccountRef(chain, payload["account"], AccountKind.ADDRESS)
    asset_meta = payload["asset"]
    asset = AssetRef(
        chain,
        asset_namespace=asset_meta["asset_namespace"],
        asset_reference=asset_meta["asset_reference"],
        decimals=int(asset_meta["decimals"]),
        kind=AssetKind(asset_meta["kind"]),
        symbol=asset_meta.get("symbol"),
    )

    records: list = []
    for tx in payload["transactions"]:
        finality = Finality(tx.get("finality", "confirmed"))
        status = TransactionStatus(tx.get("status", "succeeded"))
        records.append(
            TransactionRecord(
                chain=chain,
                provenance=provenance,
                ledger_position=LedgerPosition(
                    sequence=int(tx["sequence"]),
                    hash=tx["block_hash"],
                    transaction_index=int(tx["transaction_index"]),
                ),
                finality=finality,
                transaction_hash=tx["transaction_hash"],
                status=status,
                participants=(account,),
                fee=None,
            )
        )
    for tr in payload.get("transfers", []):
        records.append(
            TransferRecord(
                chain=chain,
                provenance=provenance,
                ledger_position=LedgerPosition(
                    sequence=int(tr["sequence"]),
                    hash=tr["block_hash"],
                    transaction_index=int(tr["transaction_index"]),
                    event_index=int(tr.get("event_index", 0)),
                ),
                finality=Finality(tr.get("finality", "confirmed")),
                transaction_hash=tr["transaction_hash"],
                transfer_index=int(tr["transfer_index"]),
                asset=asset,
                amount=ExactAmount.from_int(int(tr["base_units"]), decimals=asset.decimals),
                source_account=AccountRef(
                    chain, tr["from_address"], AccountKind.ADDRESS
                ),
                destination_account=AccountRef(
                    chain, tr["to_address"], AccountKind.ADDRESS
                ),
                transfer_kind=TransferKind(tr.get("kind", "native")),
            )
        )
    return records


def main() -> int:
    refuse_network_unless_opted_in()

    from ipfs_datasets_py.processors.wallets.export import read_jsonl, write_jsonl

    fixture_path = _repo_fixtures()
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    records = _records_from_fixture(payload)

    with tempfile.TemporaryDirectory(prefix="wallet-fixture-rt-") as tmp:
        path = Path(tmp) / "fixture-part.jsonl"
        partition = write_jsonl(records, path)
        loaded = read_jsonl(path)
        assert len(loaded) == len(records)
        assert partition.record_count == len(records)
        assert partition.digest and partition.digest.startswith("sha256:")

        summary = {
            "offline": True,
            "fixture": str(fixture_path),
            "record_count": partition.record_count,
            "partition_digest": partition.digest,
            "schema": payload.get("schema"),
            "note": "Fixture round-trip only; no network; no signing.",
            "distinctions_referenced": [
                "World ID",
                "World Chain",
                "WLD",
                "Xaman",
                "XRPL",
            ],
        }
        print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
