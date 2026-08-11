"""Unit tests for wallet legacy import / typed Parquet export (DQK-037).

Acceptance:

* Imports retain original digests and rejects
* Typed exports support predicate pushdown
* JSON manifests are generated outputs, never authority
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.wallets.duckdb_migration import (
    BOUNDED_EXTENSION_MAX_KEYS,
    TYPED_EXPORT_COLUMNS,
    bound_extension_fields,
    export_typed_partitions,
    export_wallets_parquet,
    import_legacy_bundle,
    import_payload_json_parquet,
    import_wallet_jsonl,
    stream_records_jsonl,
)


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def test_import_retains_digests_and_rejects(tmp_path: Path) -> None:
    path = tmp_path / "wallets.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"wallet_id": "w1", "chain": "eth", "balance": 1}),
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
    assert report.source_digest == _sha256_file(path)
    assert report.imported == 2
    assert len(report.rejected) == 2
    assert {r.reason for r in report.rejected} == {"invalid_json", "missing_wallet_id"}
    assert all(r["source_line_digest"].startswith("sha256:") for r in report.records)
    assert all(r["source_digest"] == report.source_digest for r in report.records)
    assert report.to_dict()["authority"] == "duckdb"
    assert report.to_dict()["source_digest"] == report.source_digest


def test_stream_records_jsonl_skips_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"wallet_id": "a", "chain": "eth"}),
                "",
                json.dumps({"wallet_id": "b", "chain": "btc"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    lines = list(stream_records_jsonl(path))
    assert len(lines) == 2
    assert lines[0][0] == 1
    assert lines[1][0] == 3


def test_metadata_sidecar_is_advisory_not_authority(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    path.write_text(
        json.dumps({"wallet_id": "w1", "balance": 2}) + "\n",
        encoding="utf-8",
    )
    meta = tmp_path / "records.meta.json"
    meta.write_text(
        json.dumps({"chain": "eth", "note": "sidecar-only"}),
        encoding="utf-8",
    )
    report = import_wallet_jsonl(path)
    assert report.imported == 1
    assert report.records[0]["chain"] == "eth"
    assert report.sidecar_digest is not None
    assert report.sidecar_digest.startswith("sha256:")
    # Source digest remains the primary artifact bytes, not the sidecar.
    assert report.source_digest == _sha256_file(path)
    assert report.source_digest != report.sidecar_digest


def test_import_legacy_bundle_records_jsonl(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "records.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "record_id": "rec:1",
                        "record_type": "transfer",
                        "chain": "eth",
                        "finality": "confirmed",
                        "ledger_position": {"sequence": 10},
                        "amount_base_units": "100",
                        "extensions": {"eth": {"schema_version": "v1", "data": {"gas": 1}}},
                    }
                ),
                json.dumps({"wallet_id": "w2", "chain": "btc", "balance": 5}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (bundle / "content.digest").write_text("sha256:deadbeef\n", encoding="utf-8")
    report = import_legacy_bundle(bundle)
    assert report.source_kind == "legacy_bundle"
    assert report.imported == 2
    assert report.records[0]["record_type"] == "transfer"
    assert report.records[0]["sequence"] == 10
    assert report.records[0]["balance_base_units"] == "100"
    assert "eth" in report.records[0]["extension_namespaces"]


def test_rejects_secret_bearing_payloads(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text(
        json.dumps(
            {
                "wallet_id": "w1",
                "chain": "eth",
                "private_key": "0xabc",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    report = import_wallet_jsonl(path)
    assert report.imported == 0
    assert len(report.rejected) == 1
    assert "forbidden_key" in report.rejected[0].reason


def test_typed_export_predicate_and_manifest_non_authority(tmp_path: Path) -> None:
    records = [
        {
            "wallet_id": "w1",
            "chain": "eth",
            "balance": 1,
            "source_line": 1,
            "source_line_digest": "sha256:" + ("aa" * 32),
        },
        {
            "wallet_id": "w2",
            "chain": "btc",
            "balance": 2,
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
    assert parquet.is_file()
    # Manifest on disk matches non-authority contract.
    on_disk = json.loads(Path(manifest.path).read_text(encoding="utf-8"))
    assert on_disk["authoritative"] is False
    assert on_disk["content_digest"].startswith("sha256:")


def test_typed_export_supports_sql_predicate_pushdown(tmp_path: Path) -> None:
    duckdb = pytest.importorskip("duckdb")
    records = [
        {
            "record_id": "r1",
            "record_type": "transfer",
            "wallet_id": "w1",
            "chain": "eth",
            "finality": "confirmed",
            "sequence": 1,
            "balance_base_units": "10",
        },
        {
            "record_id": "r2",
            "record_type": "transfer",
            "wallet_id": "w2",
            "chain": "btc",
            "finality": "pending",
            "sequence": 2,
            "balance_base_units": "20",
        },
        {
            "record_id": "r3",
            "record_type": "block",
            "wallet_id": "w3",
            "chain": "eth",
            "finality": "confirmed",
            "sequence": 3,
            "balance_base_units": "0",
        },
    ]
    parquet = tmp_path / "typed.parquet"
    export_wallets_parquet(records, parquet)

    con = duckdb.connect()
    try:
        # Predicate pushdown surface is typed columns, not payload_json.
        cols = [
            row[0]
            for row in con.execute(
                "DESCRIBE SELECT * FROM read_parquet(?)", [str(parquet)]
            ).fetchall()
        ]
        assert "payload_json" not in cols
        for required in ("chain", "record_type", "finality", "sequence", "wallet_id"):
            assert required in cols

        eth_confirmed = con.execute(
            "SELECT record_id FROM read_parquet(?) "
            "WHERE chain = ? AND finality = ? ORDER BY sequence",
            [str(parquet), "eth", "confirmed"],
        ).fetchall()
        assert [r[0] for r in eth_confirmed] == ["r1", "r3"]

        seq_window = con.execute(
            "SELECT count(*) FROM read_parquet(?) WHERE sequence BETWEEN 2 AND 3",
            [str(parquet)],
        ).fetchone()
        assert seq_window is not None
        assert seq_window[0] == 2
    finally:
        con.close()

    # Explicit filter path also prunes at export time.
    filtered = tmp_path / "eth_only.parquet"
    man = export_wallets_parquet(records, filtered, chain_filter="eth")
    assert man.row_count == 2


def test_export_typed_partitions_deterministic_manifest(tmp_path: Path) -> None:
    records = [
        {
            "record_id": "a",
            "record_type": "transfer",
            "wallet_id": "w1",
            "chain": "eth",
            "balance_base_units": "1",
        },
        {
            "record_id": "b",
            "record_type": "transfer",
            "wallet_id": "w2",
            "chain": "btc",
            "balance_base_units": "2",
        },
        {
            "record_id": "c",
            "record_type": "block",
            "wallet_id": "w3",
            "chain": "eth",
            "balance_base_units": "0",
        },
    ]
    out_a = tmp_path / "export_a"
    out_b = tmp_path / "export_b"
    man_a = export_typed_partitions(records, out_a)
    man_b = export_typed_partitions(records, out_b)
    assert man_a.row_count == 3
    assert man_a.content_digest == man_b.content_digest
    assert man_a.authoritative is False
    assert len(man_a.partitions) == 3  # eth/transfer, btc/transfer, eth/block
    # Partition files exist under hive-style layout.
    assert (out_a / "chain=eth" / "record_type=transfer" / "part.parquet").is_file()
    on_disk = json.loads(Path(man_a.path).read_text(encoding="utf-8"))
    assert on_disk["authoritative"] is False
    assert "never_authority" in on_disk["note"]
    assert on_disk["row_count"] == 3


def test_bound_extension_fields_limits() -> None:
    huge = {f"k{i}": {"nested": {"deep": {"x": i}}} for i in range(100)}
    bounded = bound_extension_fields(huge)
    assert len(bounded) <= BOUNDED_EXTENSION_MAX_KEYS
    # Forbidden keys stripped.
    dirty = {"ok": 1, "private_key": "nope", "nested": {"mnemonic": "x"}}
    cleaned = bound_extension_fields(dirty)
    assert "private_key" not in cleaned
    assert cleaned.get("ok") == 1


def test_import_payload_json_parquet_roundtrip(tmp_path: Path) -> None:
    """Opaque payload_json Parquet → validated rows → typed partitions.

    Uses DuckDB to materialize the legacy opaque column so the round-trip
    runs without pyarrow (CI bootstrap only guarantees duckdb).
    """

    duckdb = pytest.importorskip("duckdb")

    payloads = [
        {"wallet_id": "w1", "chain": "eth", "balance": 3, "record_type": "wallet"},
        {"wallet_id": "w2", "chain": "btc", "balance": 4, "record_type": "wallet"},
        "not-an-object",
    ]
    path = tmp_path / "opaque.parquet"
    con = duckdb.connect()
    try:
        con.execute(
            """
            CREATE TABLE opaque (
                record_id VARCHAR,
                record_type VARCHAR,
                finality VARCHAR,
                sequence BIGINT,
                payload_json VARCHAR
            )
            """
        )
        for index, payload in enumerate(payloads, start=1):
            record_id = payload["wallet_id"] if isinstance(payload, dict) else "bad"
            con.execute(
                "INSERT INTO opaque VALUES (?, ?, ?, ?, ?)",
                [
                    record_id,
                    "wallet",
                    "unknown",
                    index,
                    json.dumps(payload),
                ],
            )
        con.execute(
            f"COPY opaque TO '{path.as_posix()}' (FORMAT PARQUET)"
        )
    finally:
        con.close()

    report = import_payload_json_parquet(path)
    assert report.source_kind == "payload_json_parquet"
    assert report.source_digest == _sha256_file(path)
    assert report.imported == 2
    assert len(report.rejected) == 1
    assert report.rejected[0].reason == "not_object"

    # Re-export as typed partitions — no payload_json authority.
    out = tmp_path / "typed_out"
    manifest = export_typed_partitions(report.records, out)
    assert manifest.row_count == 2
    assert manifest.authoritative is False
    for col in ("chain", "wallet_id", "record_type"):
        assert col in TYPED_EXPORT_COLUMNS

    # Typed parquet must not reintroduce opaque payload_json authority.
    typed_part = next(out.rglob("part.parquet"))
    con = duckdb.connect()
    try:
        cols = [
            row[0]
            for row in con.execute(
                "DESCRIBE SELECT * FROM read_parquet(?)", [str(typed_part)]
            ).fetchall()
        ]
    finally:
        con.close()
    assert "payload_json" not in cols
    assert "chain" in cols


def test_invalid_balance_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bal.jsonl"
    path.write_text(
        json.dumps({"wallet_id": "w1", "chain": "eth", "balance": 1.5}) + "\n",
        encoding="utf-8",
    )
    report = import_wallet_jsonl(path)
    assert report.imported == 0
    assert report.rejected[0].reason == "invalid_balance"
