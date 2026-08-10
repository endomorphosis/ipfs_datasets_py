"""Unit tests for wallet JSONL import / Parquet export (DQK-037)."""

from __future__ import annotations

import json
from pathlib import Path

from ipfs_datasets_py.processors.wallets.duckdb_migration import (
    export_wallets_parquet,
    import_wallet_jsonl,
)


def test_import_retains_digests_and_rejects(tmp_path: Path) -> None:
    path = tmp_path / "wallets.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"wallet_id": "w1", "chain": "eth", "balance": 1.5}),
                "not-json",
                json.dumps({"chain": "eth"}),
                json.dumps({"wallet_id": "w2", "chain": "btc", "balance": 0}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    report = import_wallet_jsonl(path)
    assert report.source_digest.startswith("sha256:")
    assert report.imported == 2
    assert len(report.rejected) == 2
    assert all(r['source_line_digest'].startswith('sha256:') for r in report.records)
    assert report.to_dict()["authority"] == "duckdb"


def test_typed_export_predicate_and_manifest_non_authority(tmp_path: Path) -> None:
    records = [
        {
            "wallet_id": "w1",
            "chain": "eth",
            "balance": 1.0,
            "source_line": 1,
            "source_line_digest": "sha256:" + ("aa" * 32),
        },
        {
            "wallet_id": "w2",
            "chain": "btc",
            "balance": 2.0,
            "source_line": 2,
            "source_line_digest": "sha256:" + ("bb" * 32),
        },
    ]
    parquet = tmp_path / "wallets.parquet"
    manifest = export_wallets_parquet(
        records, parquet, chain_filter="eth", manifest_path=tmp_path / "m.json"
    )
    assert manifest.row_count == 1
    assert manifest.authoritative is False
    assert manifest.to_dict()["authoritative"] is False
    assert "never_authority" in manifest.to_dict()["note"]
    assert Path(manifest.path).is_file()
    assert parquet.is_file() or parquet.stat().st_size >= 0
