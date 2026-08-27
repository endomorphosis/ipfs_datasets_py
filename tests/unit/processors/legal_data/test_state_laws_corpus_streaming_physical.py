"""Focused production tests for the streaming state-law corpus writer."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_corpus_physical import (
    CORPUS_INDEX_PATH,
    ITERABLE_TO_LAYOUT_PRODUCTION_READY,
    MATERIALIZED_TO_LAYOUT_PRODUCTION_READY,
    StateLawsCorpusPhysicalError,
    StateLawsStreamingCorpusPhysicalLayout,
    write_state_laws_corpus_physical_layout,
    write_state_laws_corpus_physical_layout_from_iterable,
    write_state_laws_corpus_physical_layout_streaming,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    AdmissionStatus,
    CorpusRecord,
    SourceAuthorityClass,
    SourceReceiptRecord,
    VerificationResult,
)
from ipfs_datasets_py.retrieval.hf_graphrag.artifacts import verify_descriptor

RELEASE_POINT = "state-laws-v2-2026-08-24"


def _sha256(seed: str, *, prefixed: bool = False) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return f"sha256:{digest}" if prefixed else digest


def _receipt_id(code: str) -> str:
    return f"scrape-{code.lower()}-sealed"


def _record(
    code: str,
    ordinal: int,
    *,
    entry_seed: str | None = None,
    legal_ordinal: int | None = None,
    text: str | None = None,
) -> CorpusRecord:
    receipt_id = _receipt_id(code)
    return CorpusRecord(
        entry_cid=_sha256(entry_seed or f"entry-{code}-{ordinal}", prefixed=True),
        legal_id=f"state:{code}:code:1:{legal_ordinal or ordinal}",
        source_cid=_sha256(f"source-cid-{code}-{ordinal}", prefixed=True),
        jurisdiction=code,
        code_family="code",
        section=str(legal_ordinal or ordinal),
        admission_status=AdmissionStatus.ADMITTED,
        admission_reason="verified official full-frontier acquisition",
        release_point=RELEASE_POINT,
        source_checksum=_sha256(f"source-{code}"),
        verification_result=VerificationResult.VERIFIED,
        acquisition_time="2026-08-24T00:00:00Z",
        official_source_url=f"https://legislature.{code.lower()}.gov/code",
        acquisition_receipt_id=receipt_id,
        parser_version="state-law-parser-v2",
        text=text if text is not None else f"{code} public law section {ordinal}.",
        title="1",
    )


def _receipt(
    code: str,
    row_count: int,
    *,
    payload: dict[str, Any] | None = None,
) -> SourceReceiptRecord:
    official_url = f"https://legislature.{code.lower()}.gov/code"
    checksum = _sha256(f"source-{code}")
    count_evidence = {
        "adapter_input_row_count": row_count,
        "admission_eligible": True,
        "qualification_reasons": [],
        "reported_canonical_row_count": row_count,
    }
    if payload is not None:
        count_evidence = payload
    return SourceReceiptRecord(
        receipt_id=_receipt_id(code),
        jurisdiction=code,
        official_source_url=official_url,
        release_point=RELEASE_POINT,
        observation_time="2026-08-24T00:00:00Z",
        source_authority_class=SourceAuthorityClass.OFFICIAL,
        source_checksum=checksum,
        verification_result=VerificationResult.VERIFIED,
        discovered=row_count,
        fetched=row_count,
        excluded=0,
        quarantined=0,
        failed_final=0,
        frontier_closed=True,
        relative_path=f"receipts/scrape/{code.lower()}.json",
        start_urls=(official_url,),
        content_hashes=(checksum,),
        payload=count_evidence,
    )


class OneShotRecords:
    """Iterable that fails loudly if a writer requests a second pass."""

    def __init__(self, records: list[CorpusRecord]) -> None:
        self.records = records
        self.iterations = 0
        self.yielded = 0

    def __iter__(self) -> Iterator[CorpusRecord]:
        self.iterations += 1
        if self.iterations != 1:
            raise AssertionError("one-shot corpus source was iterated more than once")
        for record in self.records:
            self.yielded += 1
            yield record


def _read_corpus_rows(
    root: Path, layout: StateLawsStreamingCorpusPhysicalLayout
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for descriptor in layout.data_descriptors:
        rows.extend(pq.read_table(root / descriptor.relative_path).to_pylist())
    return rows


def test_streaming_writer_consumes_once_spills_and_preserves_order_and_text(
    tmp_path: Path,
) -> None:
    relation_payload = _record("CA", 3).to_dict()
    relation_payload.update(
        {
            "public_laws": ["Pub. L. 117-58"],
            "cites": ["state:CA:code:1:2"],
            "amends": ["state:CA:code:1:1"],
            "repeals": ["state:CA:code:1:4"],
            "transfers": ["state:CA:code:1:5"],
        }
    )
    records = [
        CorpusRecord.from_mapping(relation_payload),
        _record("AL", 2),
        _record("CA", 1, text="§"),
        _record("AL", 1),
        _record("CA", 2),
    ]
    source = OneShotRecords(records)
    layout = write_state_laws_corpus_physical_layout_from_iterable(
        source,
        source_receipts=[_receipt("CA", 3), _receipt("AL", 2)],
        output_dir=tmp_path,
        max_rows_per_shard=2,
        max_records_in_memory=2,
    )

    assert source.iterations == 1
    assert source.yielded == len(records)
    assert layout.production_ready is True
    assert set(layout.indexes) == {"corpus_documents"}
    assert (
        layout.indexes["corpus_documents"]["relative_path"]
        == "indexes/corpus_documents.parquet"
    )
    assert layout.row_count == len(records)
    assert layout.counts == {
        "corpus_documents": len(records),
        "corpus_quarantined": 0,
        "corpus_shards": 3,
        "source_receipts": 2,
    }

    for label, receipt in layout.sort_receipts.items():
        assert receipt["status"] == "complete", label
        assert receipt["records_consumed"] == len(records), label
        assert receipt["row_count"] == len(records), label
        assert receipt["peak_resident_records"] <= 2, label
        assert receipt["max_records_in_memory"] == 2, label
        assert receipt["run_count"] >= 3, label
    assert layout.sort_receipts["entry_identity"]["family"] == "locators"
    assert layout.sort_receipts["legal_identity"]["family"] == "documents"
    assert layout.sort_receipts["document_order"]["family"] == "corpus"
    with pytest.raises(TypeError):
        layout.sort_receipts["entry_identity"]["row_count"] = 0  # type: ignore[index]

    expected = sorted(records, key=lambda row: (row.jurisdiction, row.entry_cid))
    rows = _read_corpus_rows(tmp_path, layout)
    assert [row["entry_cid"] for row in rows] == [row.entry_cid for row in expected]
    assert [row["document_index"] for row in rows] == list(range(len(records)))
    short_row = next(row for row in rows if row["text"] == "§")
    assert short_row["text"] == "§"
    relation_row = next(
        row for row in rows if row["entry_cid"] == relation_payload["entry_cid"]
    )
    assert relation_row["public_laws"] == relation_payload["public_laws"]
    assert relation_row["cites"] == relation_payload["cites"]
    assert relation_row["amends"] == relation_payload["amends"]
    assert relation_row["repeals"] == relation_payload["repeals"]
    assert relation_row["transfers"] == relation_payload["transfers"]

    assert list(layout.iter_parent_entry_cids()) == [row.entry_cid for row in expected]
    assert list(layout.key_evidence["parent_entry_cids"]) == [
        row.entry_cid for row in expected
    ]

    routes = pq.read_table(tmp_path / CORPUS_INDEX_PATH).to_pylist()
    assert sum(int(route["row_count"]) for route in routes) == len(records)
    assert [int(route["start_document_index"]) for route in routes] == [0, 2, 4]
    assert [int(route["end_document_index"]) for route in routes] == [1, 3, 4]
    assert sum(descriptor.row_count for descriptor in layout.data_descriptors) == len(
        records
    )
    for descriptor in layout.descriptors:
        assert verify_descriptor(tmp_path, descriptor).is_file()

    for receipt in layout.source_receipts:
        stored = json.loads((tmp_path / receipt.relative_path).read_text("utf-8"))
        expected_count = 2 if receipt.jurisdiction == "AL" else 3
        assert stored["payload"]["adapter_input_row_count"] == expected_count
        assert stored["payload"]["reported_canonical_row_count"] == expected_count


@pytest.mark.parametrize("duplicate_field", ("entry_cid", "legal_id"))
def test_streaming_writer_rejects_duplicate_durable_identities(
    tmp_path: Path,
    duplicate_field: str,
) -> None:
    first = _record("AL", 1)
    second_payload = _record("AL", 2).to_dict()
    second_payload[duplicate_field] = getattr(first, duplicate_field)
    second = CorpusRecord.from_mapping(second_payload)

    with pytest.raises(
        StateLawsCorpusPhysicalError,
        match=f"duplicate {duplicate_field}",
    ):
        write_state_laws_corpus_physical_layout_from_iterable(
            OneShotRecords([first, second]),
            source_receipts=[_receipt("AL", 2)],
            output_dir=tmp_path / duplicate_field,
            max_records_in_memory=2,
        )
    assert not (tmp_path / duplicate_field / "data" / "corpus").exists()


@pytest.mark.parametrize(
    "payload",
    (
        {
            "adapter_input_row_count": 1,
            "admission_eligible": True,
            "qualification_reasons": [],
            "reported_canonical_row_count": 2,
        },
        {
            "admission_eligible": True,
            "qualification_reasons": [],
            "reported_canonical_row_count": 1,
        },
    ),
)
def test_streaming_writer_requires_exact_receipt_count_evidence(
    tmp_path: Path,
    payload: dict[str, Any],
) -> None:
    with pytest.raises(
        StateLawsCorpusPhysicalError, match="count evidence|does not match"
    ):
        write_state_laws_corpus_physical_layout_from_iterable(
            OneShotRecords([_record("AL", 1)]),
            source_receipts=[_receipt("AL", 1, payload=payload)],
            output_dir=tmp_path,
            max_records_in_memory=2,
        )
    assert not (tmp_path / "data" / "corpus").exists()


def test_streaming_and_materialized_paths_have_explicit_production_fences(
    tmp_path: Path,
) -> None:
    assert ITERABLE_TO_LAYOUT_PRODUCTION_READY is True
    assert MATERIALIZED_TO_LAYOUT_PRODUCTION_READY is False
    assert (
        write_state_laws_corpus_physical_layout_streaming
        is write_state_laws_corpus_physical_layout_from_iterable
    )

    record = _record("AL", 1, text="x")
    receipt = _receipt("AL", 1)
    streaming = write_state_laws_corpus_physical_layout_from_iterable(
        OneShotRecords([record]),
        source_receipts=[receipt],
        output_dir=tmp_path / "streaming",
        max_records_in_memory=2,
    )
    legacy = write_state_laws_corpus_physical_layout(
        [record],
        source_receipts=[receipt],
        output_dir=tmp_path / "legacy",
    )
    assert streaming.production_ready is True
    assert not hasattr(streaming, "rows")
    assert not hasattr(legacy, "production_ready")
    assert legacy.rows[0]["text"] == "x"


def test_streaming_writer_rejects_unachievable_single_record_merge_bound(
    tmp_path: Path,
) -> None:
    with pytest.raises(StateLawsCorpusPhysicalError, match="at least 2"):
        write_state_laws_corpus_physical_layout_from_iterable(
            OneShotRecords([_record("AL", 1)]),
            source_receipts=[_receipt("AL", 1)],
            output_dir=tmp_path,
            max_records_in_memory=1,
        )
