"""Unit tests for deterministic wallet dataset export (JSONL / Parquet)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.wallets.errors import (
    ExportError,
    UnsupportedCapabilityError,
)
from ipfs_datasets_py.processors.wallets.export import (
    ExportFormat,
    ExportReceipt,
    WalletDatasetExporter,
    build_export_manifest,
    build_finality_counts,
    load_export_manifest,
    read_jsonl,
    read_parquet,
    round_trip_records,
    verify_manifest,
    write_jsonl,
    write_parquet,
)
from ipfs_datasets_py.processors.wallets.models import (
    AccountKind,
    AccountRef,
    AssetKind,
    AssetRef,
    ChainRef,
    ExactAmount,
    ExportPartition,
    ExportStatus,
    Finality,
    LedgerCursor,
    LedgerPosition,
    Provenance,
    RawPayloadPolicy,
    TransactionRecord,
    TransactionStatus,
    TransferKind,
    TransferRecord,
)
from ipfs_datasets_py.processors.wallets.protocols import (
    BoundedRequest,
    Exporter,
    OperationContext,
    RequestLimits,
)
from ipfs_datasets_py.processors.wallets.storage import StreamingDatasetSink


NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
GENESIS = "0xd4e56740f876aef8c010b86a40d5f56745a118d0906a34e69aec8c0db1cb8fa3"
DIGEST = "sha256:" + ("ab" * 32)


@pytest.fixture
def chain() -> ChainRef:
    return ChainRef(
        namespace="eip155",
        network="ethereum-mainnet",
        chain_id="1",
        genesis_hash=GENESIS,
    )


@pytest.fixture
def context() -> OperationContext:
    return OperationContext(request_id="export-test-1", limits=RequestLimits())


@pytest.fixture
def provenance() -> Provenance:
    return Provenance(
        provider="fixture-rpc",
        provider_kind="json-rpc",
        request_id="request-001",
        scope="wallet:0xabc",
        observed_at=NOW,
    )


def _run(coro):
    return asyncio.run(coro)


def _records(chain: ChainRef) -> list[TransactionRecord | TransferRecord]:
    account = AccountRef(chain, "0xabc", AccountKind.ADDRESS)
    asset = AssetRef(
        chain,
        asset_namespace="slip44",
        asset_reference="60",
        decimals=18,
        kind=AssetKind.NATIVE,
        symbol="ETH",
    )
    provenance = Provenance(
        provider="fixture-rpc",
        provider_kind="json-rpc",
        request_id="request-001",
        scope="wallet:0xabc",
        observed_at=NOW,
    )
    position = LedgerPosition(sequence=1_000, hash="0xblock", transaction_index=0)
    tx = TransactionRecord(
        chain=chain,
        provenance=provenance,
        ledger_position=position,
        finality=Finality.FINALIZED,
        transaction_hash="0xtx1",
        status=TransactionStatus.SUCCEEDED,
        participants=(account,),
        fee=ExactAmount.from_int(21_000, decimals=18),
    )
    transfer = TransferRecord(
        chain=chain,
        provenance=provenance,
        ledger_position=LedgerPosition(
            sequence=1_000, hash="0xblock", transaction_index=0, event_index=0
        ),
        finality=Finality.SAFE,
        transaction_hash="0xtx1",
        transfer_index=0,
        asset=asset,
        amount=ExactAmount.from_int(10**18, decimals=18),
        source_account=account,
        destination_account=AccountRef(chain, "0xdef", AccountKind.ADDRESS),
        transfer_kind=TransferKind.NATIVE,
    )
    return [tx, transfer]


def test_write_and_read_jsonl_round_trip_preserves_ids(
    chain: ChainRef, tmp_path: Path
) -> None:
    records = _records(chain)
    path = tmp_path / "part.jsonl"
    partition = write_jsonl(records, path)
    assert partition.format == "jsonl"
    assert partition.record_count == 2
    assert partition.digest is not None
    assert partition.digest.startswith("sha256:")
    loaded = read_jsonl(path)
    assert [row["record_id"] for row in loaded] == [r.record_id for r in records]
    assert loaded[0]["record_type"] == "transaction"
    assert loaded[1]["record_type"] == "transfer"
    assert loaded[0]["transaction_hash"] == "0xtx1"
    assert loaded[1]["amount"]["base_units"] == str(10**18)


def test_write_and_read_parquet_round_trip_preserves_ids(
    chain: ChainRef, tmp_path: Path
) -> None:
    records = _records(chain)
    path = tmp_path / "part.parquet"
    partition = write_parquet(records, path)
    assert partition.format == "parquet"
    assert partition.record_count == 2
    loaded = read_parquet(path)
    assert [row["record_id"] for row in loaded] == [r.record_id for r in records]
    assert loaded[0]["finality"] == Finality.FINALIZED.value
    assert loaded[1]["asset"]["symbol"] == "ETH"


def test_round_trip_helper_jsonl_and_parquet(chain: ChainRef, tmp_path: Path) -> None:
    records = _records(chain)
    jsonl_rows = round_trip_records(
        records, format=ExportFormat.JSONL, directory=tmp_path / "j"
    )
    parquet_rows = round_trip_records(
        records, format=ExportFormat.PARQUET, directory=tmp_path / "p"
    )
    assert [r["record_id"] for r in jsonl_rows] == [r["record_id"] for r in parquet_rows]
    assert jsonl_rows[0]["schema_version"] == records[0].schema_version


def test_exporter_builds_complete_manifest(
    chain: ChainRef,
    context: OperationContext,
    tmp_path: Path,
) -> None:
    records = _records(chain)
    cursor = LedgerCursor(
        chain=chain,
        provider="fixture-rpc",
        scope="wallet:0xabc",
        normalized_schema_major=1,
        normalizer_version="fixture@1",
        position=LedgerPosition(sequence=1_000, hash="0xblock"),
        revision="rev:1",
    )
    exporter = WalletDatasetExporter(
        chain=chain,
        output_dir=tmp_path / "out",
        formats=(ExportFormat.JSONL, ExportFormat.PARQUET),
        processor_version="wallet-exporter@1.0.0",
        normalized_schema_major=1,
        raw_payload_policy=RawPayloadPolicy.OMITTED,
        provider="fixture-rpc",
        provider_kind="json-rpc",
        provider_capabilities=("wallet_history", "dataset_export"),
        clock=lambda: NOW,
    )
    assert isinstance(exporter, Exporter)
    receipt = _run(
        exporter.export_records(
            records,
            context=context,
            scope="wallet:0xabc",
            status=ExportStatus.COMPLETE,
            checkpoint_before=None,
            checkpoint_after=cursor,
            warnings=(),
        )
    )
    assert isinstance(receipt, ExportReceipt)
    assert receipt.complete is True
    manifest = receipt.manifest
    payload = manifest.to_dict()
    assert payload["record_count"] == 2
    assert payload["checkpoint_after"]["revision"] == "rev:1"
    assert payload["raw_payload_policy"] == "omitted"
    assert "finality_counts" in payload
    assert sum(payload["finality_counts"].values()) == 2
    assert receipt.provider_capabilities == ("wallet_history", "dataset_export")
    assert receipt.processor_version == "wallet-exporter@1.0.0"
    assert receipt.normalized_schema_major == 1
    assert "jsonl" in receipt.formats
    # Sidecar parquet recorded as warning annotation.
    assert any(w.startswith("sidecar_format:parquet:") for w in receipt.warnings)
    on_disk = load_export_manifest(tmp_path / "out" / "export-manifest.json")
    assert on_disk["manifest_id"] == manifest.manifest_id
    verify_manifest(manifest)


def test_partial_export_status_and_warnings(
    chain: ChainRef,
    context: OperationContext,
    tmp_path: Path,
) -> None:
    records = _records(chain)[:1]
    exporter = WalletDatasetExporter(
        chain=chain,
        output_dir=tmp_path / "partial",
        formats=(ExportFormat.JSONL,),
        clock=lambda: NOW,
    )
    receipt = _run(
        exporter.export_records(
            records,
            context=context,
            scope="wallet:0xabc",
            status=ExportStatus.PARTIAL,
            warnings=("truncated page",),
        )
    )
    assert receipt.status is ExportStatus.PARTIAL
    assert receipt.partial is True
    assert receipt.manifest.warning_count == 1
    assert "truncated page" in receipt.manifest.warnings


def test_car_optional_without_writer(
    chain: ChainRef,
    context: OperationContext,
    tmp_path: Path,
) -> None:
    exporter = WalletDatasetExporter(
        chain=chain,
        output_dir=tmp_path / "car",
        formats=(ExportFormat.CAR,),
        enable_car=False,
        clock=lambda: NOW,
    )
    with pytest.raises(UnsupportedCapabilityError, match="CAR"):
        _run(
            exporter.export_records(
                _records(chain),
                context=context,
                scope="wallet:0xabc",
            )
        )


def test_car_with_injectable_writer(
    chain: ChainRef,
    context: OperationContext,
    tmp_path: Path,
) -> None:
    def car_writer(path: Path, payloads: list) -> dict:
        body = b"car-fixture"
        path.write_bytes(body)
        return {
            "path": path.name,
            "record_count": len(payloads),
            "byte_count": len(body),
            "digest": DIGEST,
            "cid": "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3",
        }

    exporter = WalletDatasetExporter(
        chain=chain,
        output_dir=tmp_path / "car-ok",
        formats=(ExportFormat.CAR,),
        enable_car=True,
        car_writer=car_writer,
        clock=lambda: NOW,
    )
    receipt = _run(
        exporter.export_records(
            _records(chain),
            context=context,
            scope="wallet:0xabc",
        )
    )
    assert receipt.formats == ("car",)
    assert receipt.manifest.partitions[0].cid is not None


def test_export_wallet_protocol_path(
    chain: ChainRef,
    context: OperationContext,
    tmp_path: Path,
) -> None:
    records = _records(chain)
    sink = StreamingDatasetSink(scope="wallet:0xabc")
    batch_records = tuple(records)
    from ipfs_datasets_py.processors.wallets.protocols import RecordBatch

    _run(
        sink.write(
            RecordBatch(batch_records, response_bytes=10),
            context=context,
        )
    )
    _run(sink.commit(None, context=context))
    exporter = WalletDatasetExporter(
        chain=chain,
        output_dir=tmp_path / "proto",
        formats=(ExportFormat.JSONL,),
        clock=lambda: NOW,
    )
    request = BoundedRequest(scope="wallet:0xabc", context=context)
    receipt = _run(exporter.export_wallet(request, sink))
    assert receipt.manifest.record_count == 2
    loaded = read_jsonl(tmp_path / "proto" / "records-000.jsonl")
    assert loaded[0]["record_id"] == records[0].record_id


def test_build_export_manifest_accounting(
    chain: ChainRef, provenance: Provenance
) -> None:
    records = _records(chain)
    partition = ExportPartition(
        path="part.jsonl",
        format="jsonl",
        record_count=2,
        byte_count=100,
        digest=DIGEST,
        record_types=("transaction", "transfer"),
        min_position=1_000,
        max_position=1_000,
    )
    manifest = build_export_manifest(
        chain=chain,
        provenance=provenance,
        status=ExportStatus.COMPLETE,
        raw_payload_policy=RawPayloadPolicy.OMITTED,
        partitions=(partition,),
        records=records,
        started_at=NOW,
        completed_at=NOW,
    )
    verify_manifest(manifest)
    counts = build_finality_counts(records)
    assert sum(counts.values()) == 2

    with pytest.raises(ExportError, match="partition record counts"):
        build_export_manifest(
            chain=chain,
            provenance=provenance,
            status=ExportStatus.COMPLETE,
            raw_payload_policy=RawPayloadPolicy.OMITTED,
            partitions=(
                ExportPartition(
                    path="bad.jsonl",
                    format="jsonl",
                    record_count=1,
                    byte_count=1,
                    digest=DIGEST,
                ),
            ),
            records=records,
            started_at=NOW,
            completed_at=NOW,
        )


def test_empty_export_is_valid(
    chain: ChainRef,
    context: OperationContext,
    tmp_path: Path,
) -> None:
    exporter = WalletDatasetExporter(
        chain=chain,
        output_dir=tmp_path / "empty",
        formats=(ExportFormat.JSONL,),
        clock=lambda: NOW,
    )
    receipt = _run(
        exporter.export_records(
            [],
            context=context,
            scope="wallet:0xabc",
        )
    )
    assert receipt.manifest.record_count == 0
    assert receipt.manifest.partitions[0].record_count == 0
    assert read_jsonl(tmp_path / "empty" / "records-000.jsonl") == []


def test_arrow_export_round_trip_ids(
    chain: ChainRef,
    context: OperationContext,
    tmp_path: Path,
) -> None:
    records = _records(chain)
    exporter = WalletDatasetExporter(
        chain=chain,
        output_dir=tmp_path / "arrow",
        formats=(ExportFormat.ARROW,),
        clock=lambda: NOW,
    )
    receipt = _run(
        exporter.export_records(
            records,
            context=context,
            scope="wallet:0xabc",
        )
    )
    assert receipt.formats == ("arrow",)
    assert (tmp_path / "arrow" / "records-000.arrow").is_file()
    assert receipt.manifest.record_count == 2
