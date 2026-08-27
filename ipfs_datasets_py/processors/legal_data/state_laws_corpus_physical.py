"""Bounded physical writer for admitted normalized state-law parent rows.

The legacy-v2 adapter owns normalization and admission.  This module accepts
only its admitted :class:`CorpusRecord` outcomes, assigns the same dense
parent-document ordering, and writes direct-column Parquet shards partitioned
by jurisdiction.  Acquisition receipts are written once, as separate JSON
artifacts; downstream posting, vector, and graph artifacts therefore need only
durable content keys.  A separate canonical chunk layout owns query hydration
and the ``corpus_chunks`` route, preventing BM25 and embeddings from chunking
or ordering the same source independently.

All writes are local and staged atomically.  This module performs no network
I/O and does not authorize publication or upload.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    AdmissionStatus,
    CorpusRecord,
    SourceAuthorityClass,
    SourceReceiptRecord,
    VerificationResult,
)
from ipfs_datasets_py.retrieval.hf_graphrag.artifacts import (
    ArtifactWriterConfig,
    atomic_staging,
    atomic_write_canonical_json,
    confine_path,
    describe_file,
    resolve_release_root,
    verify_descriptor,
    write_zstd_parquet,
)
from ipfs_datasets_py.retrieval.hf_graphrag.artifacts import (
    manifest_descriptor as _manifest_descriptor,
)
from ipfs_datasets_py.retrieval.hf_graphrag.external_sort import (
    DEFAULT_MAX_RECORDS_IN_MEMORY,
    external_sort_to_file,
    iter_jsonl,
)
from ipfs_datasets_py.retrieval.hf_graphrag.schema import (
    COMPACT_INDEX_SCHEMA_VERSION,
    MAX_ROUTING_ROWS_PER_INDEX,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    ArtifactDescriptor,
    ArtifactFamily,
    CompactIndexRow,
)

SCHEMA_VERSION: Final = "state-laws-corpus-physical/v1"
CORPUS_ROW_SCHEMA_VERSION: Final = "state-laws-corpus-row-physical/v1"
CORPUS_DATA_DIR: Final = "data/corpus"
CORPUS_DOCUMENT_INDEX_PATH: Final = "indexes/corpus_documents.parquet"
# Compatibility spelling for callers that imported the original constant.
# This layout stores normalized parent statutes; the separately persisted
# canonical chunk store owns the query-facing ``corpus_chunks`` index.
CORPUS_INDEX_PATH: Final = CORPUS_DOCUMENT_INDEX_PATH
CORPUS_INDEX_KIND: Final = "corpus_document_range"

AUTHORIZES_PUBLICATION: Final = False
AUTHORIZES_HUB_UPLOAD: Final = False
MATERIALIZED_TO_LAYOUT_PRODUCTION_READY: Final = False
ITERABLE_TO_LAYOUT_PRODUCTION_READY: Final = True


class StateLawsCorpusPhysicalError(ValueError):
    """Raised when canonical rows or receipts cannot be staged losslessly."""


def _coerce_event_or_record(value: Any, *, position: int) -> CorpusRecord:
    """Accept a CorpusRecord or one admitted adapter event, fail closed."""

    if isinstance(value, CorpusRecord):
        return value

    if isinstance(value, Mapping):
        # Mapping-shaped adapter event support is useful for durable event logs.
        if "disposition" in value or "record" in value:
            disposition = str(value.get("disposition") or "").strip().lower()
            if disposition != "admitted":
                raise StateLawsCorpusPhysicalError(
                    f"events[{position}] is not admitted: {disposition!r}"
                )
            record = value.get("record")
            if not isinstance(record, Mapping):
                raise StateLawsCorpusPhysicalError(
                    f"events[{position}] admitted event has no record mapping"
                )
            return CorpusRecord.from_mapping(record)
        return CorpusRecord.from_mapping(value)

    # Avoid coupling this physical layer to the concrete adapter result type;
    # this also lets streaming wrappers expose the same small event protocol.
    if hasattr(value, "disposition") and hasattr(value, "record"):
        raw_disposition = value.disposition
        disposition = str(getattr(raw_disposition, "value", raw_disposition)).lower()
        if disposition != "admitted":
            raise StateLawsCorpusPhysicalError(
                f"events[{position}] is not admitted: {disposition!r}"
            )
        record = value.record
        if not isinstance(record, CorpusRecord):
            if isinstance(record, Mapping):
                return CorpusRecord.from_mapping(record)
            raise StateLawsCorpusPhysicalError(
                f"events[{position}] admitted event has no CorpusRecord"
            )
        return record

    raise StateLawsCorpusPhysicalError(
        f"events[{position}] must be a CorpusRecord or admitted adapter event"
    )


def _coerce_source_receipt(value: Any, *, position: int) -> SourceReceiptRecord:
    if isinstance(value, SourceReceiptRecord):
        return value
    if isinstance(value, Mapping):
        return SourceReceiptRecord.from_mapping(value)
    if hasattr(value, "record"):
        if getattr(value, "admission_eligible", False) is not True:
            raise StateLawsCorpusPhysicalError(
                f"source_receipts[{position}] is not admission eligible"
            )
        reasons = tuple(getattr(value, "qualification_reasons", ()) or ())
        if reasons:
            raise StateLawsCorpusPhysicalError(
                f"source_receipts[{position}] has qualification reasons: {reasons!r}"
            )
        record = value.record
        if isinstance(record, SourceReceiptRecord):
            return record
        if isinstance(record, Mapping):
            return SourceReceiptRecord.from_mapping(record)
    raise StateLawsCorpusPhysicalError(
        f"source_receipts[{position}] must be a source receipt or normalized receipt"
    )


def _validate_admitted_record(record: CorpusRecord, *, position: int) -> None:
    if record.admission_status is not AdmissionStatus.ADMITTED:
        raise StateLawsCorpusPhysicalError(
            f"records[{position}] is not admitted: {record.admission_status.value}"
        )
    if record.source_authority_class is not SourceAuthorityClass.OFFICIAL:
        raise StateLawsCorpusPhysicalError(
            f"records[{position}] is not from an official source"
        )
    if record.verification_result is not VerificationResult.VERIFIED:
        raise StateLawsCorpusPhysicalError(f"records[{position}] is not verified")
    if not record.text.strip():
        raise StateLawsCorpusPhysicalError(
            f"records[{position}] has empty canonical text"
        )


def _validate_receipt(
    receipt: SourceReceiptRecord,
    *,
    row_count: int,
) -> None:
    prefix = f"source receipt {receipt.receipt_id!r}"
    if receipt.source_authority_class is not SourceAuthorityClass.OFFICIAL:
        raise StateLawsCorpusPhysicalError(f"{prefix} is not official")
    if receipt.verification_result is not VerificationResult.VERIFIED:
        raise StateLawsCorpusPhysicalError(f"{prefix} is not verified")
    if not receipt.frontier_closed:
        raise StateLawsCorpusPhysicalError(f"{prefix} has an open frontier")
    if receipt.failed_final or receipt.quarantined:
        raise StateLawsCorpusPhysicalError(f"{prefix} has failed/quarantined work")
    if receipt.discovered <= 0 or receipt.fetched <= 0:
        raise StateLawsCorpusPhysicalError(f"{prefix} is empty")
    if not receipt.relative_path.startswith("receipts/"):
        raise StateLawsCorpusPhysicalError(f"{prefix} must be stored below receipts/")
    payload = receipt.payload
    if "admission_eligible" in payload and payload["admission_eligible"] is not True:
        raise StateLawsCorpusPhysicalError(f"{prefix} is not admission eligible")
    reasons = payload.get("qualification_reasons", ())
    if reasons:
        raise StateLawsCorpusPhysicalError(f"{prefix} has qualification reasons")
    for key in ("reported_canonical_row_count", "adapter_input_row_count"):
        expected = payload.get(key)
        if expected is not None and int(expected) != row_count:
            raise StateLawsCorpusPhysicalError(
                f"{prefix} {key}={expected} does not match {row_count} corpus rows"
            )


def _validate_streaming_receipt_count_evidence(
    receipt: SourceReceiptRecord,
    *,
    row_count: int,
) -> None:
    """Require the adapter's exact input/canonical count evidence."""

    prefix = f"source receipt {receipt.receipt_id!r}"
    for key in ("reported_canonical_row_count", "adapter_input_row_count"):
        if key not in receipt.payload:
            raise StateLawsCorpusPhysicalError(
                f"{prefix} lacks required streaming count evidence {key}"
            )
        raw_value = receipt.payload[key]
        if isinstance(raw_value, bool):
            raise StateLawsCorpusPhysicalError(
                f"{prefix} has invalid {key} count evidence"
            )
        try:
            value = int(raw_value)
        except (TypeError, ValueError) as exc:
            raise StateLawsCorpusPhysicalError(
                f"{prefix} has invalid {key} count evidence"
            ) from exc
        if value != row_count:
            raise StateLawsCorpusPhysicalError(
                f"{prefix} {key}={value} does not match {row_count} corpus rows"
            )


def _corpus_schema() -> Any:
    try:
        import pyarrow as pa
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise StateLawsCorpusPhysicalError(
            "pyarrow is required for the state-law corpus physical layout"
        ) from exc
    return pa.schema(
        [
            ("schema_version", pa.string(), False),
            ("document_index", pa.int64(), False),
            ("entry_cid", pa.string(), False),
            ("legal_id", pa.string(), False),
            ("source_cid", pa.string(), False),
            ("jurisdiction", pa.string(), False),
            ("jurisdiction_code", pa.string(), False),
            ("code_family", pa.string(), False),
            ("section", pa.string(), False),
            ("title", pa.string(), True),
            ("chapter", pa.string(), True),
            ("subsection", pa.string(), True),
            ("text", pa.string(), False),
            ("admission_status", pa.string(), False),
            ("admission_reason", pa.string(), False),
            ("source_authority_class", pa.string(), False),
            ("verification_result", pa.string(), False),
            ("release_point", pa.string(), False),
            ("source_checksum", pa.string(), False),
            ("acquisition_time", pa.string(), False),
            ("official_source_url", pa.string(), False),
            ("acquisition_receipt_id", pa.string(), False),
            ("parser_version", pa.string(), False),
            ("edition_as_of", pa.string(), True),
            ("effective_date", pa.string(), True),
            ("observed_at", pa.string(), True),
            ("parent_path", pa.string(), True),
            ("public_laws", pa.list_(pa.string()), False),
            ("cites", pa.list_(pa.string()), False),
            ("amends", pa.list_(pa.string()), False),
            ("repeals", pa.list_(pa.string()), False),
            ("transfers", pa.list_(pa.string()), False),
        ],
        metadata={
            b"primary_key": b"entry_cid",
            b"schema_version": CORPUS_ROW_SCHEMA_VERSION.encode("ascii"),
        },
    )


def _index_schema() -> Any:
    try:
        import pyarrow as pa
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise StateLawsCorpusPhysicalError(
            "pyarrow is required for the state-law corpus physical layout"
        ) from exc
    return pa.schema(
        [
            ("schema_version", pa.string(), False),
            ("kind", pa.string(), False),
            ("shard_id", pa.int64(), False),
            ("relative_path", pa.string(), False),
            ("sha256", pa.string(), False),
            ("size_bytes", pa.int64(), False),
            ("row_count", pa.int64(), False),
            ("first_key", pa.string(), False),
            ("last_key", pa.string(), False),
            ("content_cid", pa.string(), True),
            ("cid", pa.string(), True),
            ("start_document_index", pa.int64(), False),
            ("end_document_index", pa.int64(), False),
            ("jurisdiction_code", pa.string(), False),
        ],
        metadata={b"schema_version": COMPACT_INDEX_SCHEMA_VERSION.encode("ascii")},
    )


def _physical_row(record: CorpusRecord, *, document_index: int) -> dict[str, Any]:
    row = record.to_dict()
    row["document_index"] = document_index
    row["jurisdiction_code"] = record.jurisdiction
    return row


@dataclass(frozen=True, slots=True)
class StateLawsCorpusPhysicalLayout:
    """Committed corpus shards, source receipts, and query routing index."""

    output_dir: str
    rows: tuple[Mapping[str, Any], ...]
    source_receipts: tuple[SourceReceiptRecord, ...]
    data_descriptors: tuple[ArtifactDescriptor, ...]
    receipt_descriptors: tuple[ArtifactDescriptor, ...]
    corpus_index_descriptor: ArtifactDescriptor
    route_rows: tuple[Mapping[str, Any], ...]

    @property
    def descriptors(self) -> tuple[ArtifactDescriptor, ...]:
        return (
            *self.data_descriptors,
            *self.receipt_descriptors,
            self.corpus_index_descriptor,
        )

    @property
    def entry_cid_to_document_index(self) -> dict[str, int]:
        return {str(row["entry_cid"]): int(row["document_index"]) for row in self.rows}

    @property
    def indexes(self) -> dict[str, dict[str, Any]]:
        return {
            "corpus_documents": _manifest_descriptor(self.corpus_index_descriptor)
        }

    @property
    def counts(self) -> dict[str, int]:
        return {
            "corpus_documents": len(self.rows),
            "corpus_shards": len(self.data_descriptors),
            "corpus_quarantined": 0,
            "source_receipts": len(self.source_receipts),
        }

    @property
    def key_evidence(self) -> dict[str, tuple[str, ...]]:
        return {"parent_entry_cids": tuple(str(row["entry_cid"]) for row in self.rows)}

    def to_manifest_fragment(self) -> dict[str, Any]:
        return {
            "artifacts": [
                *(_manifest_descriptor(item) for item in self.data_descriptors),
                *(_manifest_descriptor(item) for item in self.receipt_descriptors),
            ],
            "configs": {
                "corpus": f"{CORPUS_DATA_DIR}/jurisdiction/*/*.parquet",
                "corpus_document_index": CORPUS_DOCUMENT_INDEX_PATH,
            },
            "corpus": {
                "direct_columns": True,
                "document_order": ["jurisdiction_code", "entry_cid"],
                "jurisdiction_partitioned": True,
                "physical_schema_version": SCHEMA_VERSION,
                "primary_key": "entry_cid",
                "source_receipts_embedded": False,
            },
            "counts": self.counts,
            "default_config": {
                "admission_status": "admitted",
                "allow_quarantine": False,
            },
            "indexes": self.indexes,
            "jurisdictions": sorted(
                {receipt.jurisdiction for receipt in self.source_receipts}
            ),
            "source_receipts": [
                _manifest_descriptor(item) for item in self.receipt_descriptors
            ],
        }


@dataclass(frozen=True, slots=True)
class StateLawsStreamingCorpusPhysicalLayout:
    """Descriptor-complete corpus layout built from a one-shot source."""

    output_dir: str
    source_receipts: tuple[SourceReceiptRecord, ...]
    data_descriptors: tuple[ArtifactDescriptor, ...]
    receipt_descriptors: tuple[ArtifactDescriptor, ...]
    corpus_index_descriptor: ArtifactDescriptor
    route_rows: tuple[Mapping[str, Any], ...]
    row_count: int
    sort_receipts: Mapping[str, Mapping[str, Any]]

    def __post_init__(self) -> None:
        if self.row_count < 1:
            raise StateLawsCorpusPhysicalError(
                "streaming corpus layout must contain at least one row"
            )
        if sum(item.row_count for item in self.data_descriptors) != self.row_count:
            raise StateLawsCorpusPhysicalError(
                "streaming corpus data descriptor counts do not match row_count"
            )
        if len(self.data_descriptors) != len(self.route_rows):
            raise StateLawsCorpusPhysicalError(
                "streaming corpus shard/route counts do not match"
            )
        if (
            sum(int(row.get("row_count") or 0) for row in self.route_rows)
            != self.row_count
        ):
            raise StateLawsCorpusPhysicalError(
                "streaming corpus route counts do not match row_count"
            )
        if self.corpus_index_descriptor.row_count != len(self.route_rows):
            raise StateLawsCorpusPhysicalError(
                "streaming corpus index descriptor count does not match routes"
            )
        if len(self.source_receipts) != len(self.receipt_descriptors):
            raise StateLawsCorpusPhysicalError(
                "streaming source receipt descriptor count does not match receipts"
            )

        expected_sort_receipts = {
            "document_order",
            "entry_identity",
            "legal_identity",
        }
        if set(self.sort_receipts) != expected_sort_receipts:
            raise StateLawsCorpusPhysicalError(
                "streaming corpus layout lacks its three external-sort receipts"
            )
        frozen_receipts: dict[str, Mapping[str, Any]] = {}
        for label in sorted(expected_sort_receipts):
            receipt = dict(self.sort_receipts[label])
            if receipt.get("status") != "complete":
                raise StateLawsCorpusPhysicalError(
                    f"streaming corpus sort {label} is not complete"
                )
            for count_key in ("records_consumed", "row_count"):
                if int(receipt.get(count_key) or 0) != self.row_count:
                    raise StateLawsCorpusPhysicalError(
                        f"streaming corpus sort {label} {count_key} does not "
                        "match row_count"
                    )
            peak = int(receipt.get("peak_resident_records") or 0)
            maximum = int(receipt.get("max_records_in_memory") or 0)
            if maximum < 2 or peak < 1 or peak > maximum:
                raise StateLawsCorpusPhysicalError(
                    f"streaming corpus sort {label} violated its spill bound"
                )
            output_digest = str(receipt.get("output_digest") or "")
            if len(output_digest) != 64:
                raise StateLawsCorpusPhysicalError(
                    f"streaming corpus sort {label} lacks an output digest"
                )
            frozen_receipts[label] = MappingProxyType(receipt)
        object.__setattr__(
            self,
            "sort_receipts",
            MappingProxyType(frozen_receipts),
        )

    @property
    def production_ready(self) -> bool:
        return ITERABLE_TO_LAYOUT_PRODUCTION_READY

    @property
    def descriptors(self) -> tuple[ArtifactDescriptor, ...]:
        return (
            *self.data_descriptors,
            *self.receipt_descriptors,
            self.corpus_index_descriptor,
        )

    @property
    def indexes(self) -> dict[str, dict[str, Any]]:
        return {
            "corpus_documents": _manifest_descriptor(self.corpus_index_descriptor)
        }

    @property
    def counts(self) -> dict[str, int]:
        return {
            "corpus_documents": self.row_count,
            "corpus_shards": len(self.data_descriptors),
            "corpus_quarantined": 0,
            "source_receipts": len(self.source_receipts),
        }

    def iter_parent_entry_cids(self) -> Iterable[str]:
        """Reopen committed shards and stream the exact corpus key set."""

        try:
            import pyarrow.parquet as pq
        except ImportError as exc:  # pragma: no cover - release dependency
            raise StateLawsCorpusPhysicalError(
                "pyarrow is required to stream corpus key evidence"
            ) from exc
        root = Path(self.output_dir)
        for descriptor in self.data_descriptors:
            path = confine_path(root, descriptor.relative_path)
            parquet = pq.ParquetFile(path)
            for batch in parquet.iter_batches(columns=["entry_cid"]):
                for value in batch.column(0).to_pylist():
                    yield str(value)

    @property
    def key_evidence(self) -> dict[str, Iterable[str]]:
        return {"parent_entry_cids": self.iter_parent_entry_cids()}

    def to_manifest_fragment(self) -> dict[str, Any]:
        return {
            "artifacts": [
                *(_manifest_descriptor(item) for item in self.data_descriptors),
                *(_manifest_descriptor(item) for item in self.receipt_descriptors),
            ],
            "configs": {
                "corpus": f"{CORPUS_DATA_DIR}/jurisdiction/*/*.parquet",
                "corpus_document_index": CORPUS_DOCUMENT_INDEX_PATH,
            },
            "corpus": {
                "direct_columns": True,
                "document_order": ["jurisdiction_code", "entry_cid"],
                "jurisdiction_partitioned": True,
                "physical_schema_version": SCHEMA_VERSION,
                "primary_key": "entry_cid",
                "source_receipts_embedded": False,
                "streaming": True,
            },
            "counts": self.counts,
            "default_config": {
                "admission_status": "admitted",
                "allow_quarantine": False,
            },
            "indexes": self.indexes,
            "jurisdictions": [item.jurisdiction for item in self.source_receipts],
            "source_receipts": [
                _manifest_descriptor(item) for item in self.receipt_descriptors
            ],
        }


def _entry_identity_sort_key(row: Mapping[str, Any]) -> tuple[str]:
    return (str(row["entry_cid"]),)


def _legal_identity_sort_key(row: Mapping[str, Any]) -> tuple[str]:
    return (str(row["legal_id"]),)


def _corpus_order_sort_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return str(row["jurisdiction"]), str(row["entry_cid"])


def _sort_receipt_payload(receipt: Any) -> dict[str, Any]:
    return {
        "family": receipt.family,
        "max_records_in_memory": receipt.max_records_in_memory,
        "output_digest": receipt.output_digest,
        "peak_resident_records": receipt.peak_resident_records,
        "records_consumed": receipt.records_consumed,
        "row_count": receipt.row_count,
        "run_count": receipt.run_count,
        "status": receipt.status,
    }


def write_state_laws_corpus_physical_layout_from_iterable(
    events_or_records: Iterable[Any],
    *,
    source_receipts: Sequence[Any],
    output_dir: str | Path,
    max_rows_per_shard: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    max_records_in_memory: int = DEFAULT_MAX_RECORDS_IN_MEMORY,
) -> StateLawsStreamingCorpusPhysicalLayout:
    """Write the corpus from one-shot input with disk-backed global ordering."""

    if isinstance(events_or_records, (str, bytes, bytearray)):
        raise StateLawsCorpusPhysicalError(
            "events_or_records must be an iterable of admitted records"
        )
    if (
        isinstance(max_rows_per_shard, bool)
        or not isinstance(max_rows_per_shard, int)
        or not 1 <= max_rows_per_shard <= MAX_ROWS_PER_PHYSICAL_SHARD
    ):
        raise StateLawsCorpusPhysicalError(
            f"max_rows_per_shard must be within 1..{MAX_ROWS_PER_PHYSICAL_SHARD}"
        )
    if (
        isinstance(max_records_in_memory, bool)
        or not isinstance(max_records_in_memory, int)
        or max_records_in_memory < 2
    ):
        raise StateLawsCorpusPhysicalError(
            "max_records_in_memory must be an integer of at least 2"
        )

    receipts = tuple(
        _coerce_source_receipt(value, position=position)
        for position, value in enumerate(source_receipts)
    )
    if not receipts:
        raise StateLawsCorpusPhysicalError("at least one source receipt is required")
    receipt_codes = [receipt.jurisdiction for receipt in receipts]
    receipt_ids = [receipt.receipt_id for receipt in receipts]
    receipt_paths = [receipt.relative_path for receipt in receipts]
    for label, values in (
        ("jurisdiction", receipt_codes),
        ("receipt_id", receipt_ids),
        ("relative_path", receipt_paths),
    ):
        if len(values) != len(set(values)):
            raise StateLawsCorpusPhysicalError(f"duplicate source receipt {label}")
    receipts = tuple(sorted(receipts, key=lambda item: item.jurisdiction))
    receipts_by_code = {receipt.jurisdiction: receipt for receipt in receipts}

    root = resolve_release_root(output_dir, must_exist=False)
    root.mkdir(parents=True, exist_ok=True)
    writer_config = ArtifactWriterConfig(max_rows_per_shard=max_rows_per_shard)
    data_descriptors: list[ArtifactDescriptor] = []
    receipt_descriptors: list[ArtifactDescriptor] = []
    route_rows: list[dict[str, Any]] = []
    sort_receipts: dict[str, Mapping[str, Any]] = {}
    row_count_by_code = {code: 0 for code in receipts_by_code}

    with atomic_staging(root, prefix=".state-laws-corpus-streaming-") as staging:
        work = staging.path / ".work"
        work.mkdir(parents=True, exist_ok=True)

        def prepared_rows() -> Iterable[Mapping[str, Any]]:
            for position, value in enumerate(events_or_records):
                record = _coerce_event_or_record(value, position=position)
                _validate_admitted_record(record, position=position)
                receipt = receipts_by_code.get(record.jurisdiction)
                if receipt is None:
                    raise StateLawsCorpusPhysicalError(
                        f"record jurisdiction {record.jurisdiction} lacks a source receipt"
                    )
                if record.acquisition_receipt_id != receipt.receipt_id:
                    raise StateLawsCorpusPhysicalError(
                        f"record {record.entry_cid} does not bind receipt {receipt.receipt_id!r}"
                    )
                yield {
                    "entry_cid": record.entry_cid,
                    "jurisdiction": record.jurisdiction,
                    "legal_id": record.legal_id,
                    "record": record.to_dict(),
                }

        entry_path = work / "entry-identity.jsonl"
        entry_receipt = external_sort_to_file(
            prepared_rows(),
            entry_path,
            work_dir=work / "entry-sort",
            key_fn=_entry_identity_sort_key,
            family="locators",
            max_records_in_memory=max_records_in_memory,
            resume=False,
        )
        sort_receipts["entry_identity"] = _sort_receipt_payload(entry_receipt)
        if entry_receipt.row_count < 1:
            raise StateLawsCorpusPhysicalError(
                "at least one admitted CorpusRecord is required"
            )

        def unique_entries() -> Iterable[Mapping[str, Any]]:
            previous: str | None = None
            for row in iter_jsonl(entry_path):
                identity = str(row["entry_cid"])
                if identity == previous:
                    raise StateLawsCorpusPhysicalError(
                        f"duplicate entry_cid in corpus input: {identity}"
                    )
                previous = identity
                yield row

        legal_path = work / "legal-identity.jsonl"
        legal_receipt = external_sort_to_file(
            unique_entries(),
            legal_path,
            work_dir=work / "legal-sort",
            key_fn=_legal_identity_sort_key,
            family="documents",
            max_records_in_memory=max_records_in_memory,
            resume=False,
        )
        sort_receipts["legal_identity"] = _sort_receipt_payload(legal_receipt)

        def unique_legal_ids() -> Iterable[Mapping[str, Any]]:
            previous: str | None = None
            for row in iter_jsonl(legal_path):
                identity = str(row["legal_id"])
                if identity == previous:
                    raise StateLawsCorpusPhysicalError(
                        f"duplicate legal_id in corpus input: {identity}"
                    )
                previous = identity
                yield row

        ordered_path = work / "corpus-order.jsonl"
        order_receipt = external_sort_to_file(
            unique_legal_ids(),
            ordered_path,
            work_dir=work / "corpus-order-sort",
            key_fn=_corpus_order_sort_key,
            family="corpus",
            max_records_in_memory=max_records_in_memory,
            resume=False,
        )
        sort_receipts["document_order"] = _sort_receipt_payload(order_receipt)
        if order_receipt.row_count != entry_receipt.row_count:
            raise StateLawsCorpusPhysicalError("corpus identity sorts lost rows")

        shard_rows: list[dict[str, Any]] = []
        shard_code = ""
        part_by_code: dict[str, int] = defaultdict(int)

        def flush_shard() -> None:
            nonlocal shard_code
            if not shard_rows:
                return
            shard_id = len(data_descriptors)
            if shard_id >= MAX_ROUTING_ROWS_PER_INDEX:
                raise StateLawsCorpusPhysicalError(
                    "corpus shard count exceeds the flat routing-index bound"
                )
            part_index = part_by_code[shard_code]
            relative_path = (
                f"{CORPUS_DATA_DIR}/jurisdiction/{shard_code}/"
                f"part-{part_index:06d}.parquet"
            )
            target = staging.confine(relative_path)
            write_zstd_parquet(
                target,
                tuple(shard_rows),
                max_rows=max_rows_per_shard,
                config=writer_config,
                schema=_corpus_schema(),
            )
            descriptor = describe_file(
                target,
                root=staging.path,
                row_count=len(shard_rows),
                family=ArtifactFamily.CORPUS,
                schema_id=CORPUS_ROW_SCHEMA_VERSION,
                first_key=str(shard_rows[0]["entry_cid"]),
                last_key=str(shard_rows[-1]["entry_cid"]),
                shard_id=shard_id,
                metadata={
                    "jurisdiction_code": shard_code,
                    "start_document_index": int(shard_rows[0]["document_index"]),
                    "end_document_index": int(shard_rows[-1]["document_index"]),
                    "streaming": True,
                },
            )
            data_descriptors.append(descriptor)
            route = CompactIndexRow(
                relative_path=descriptor.relative_path,
                sha256=descriptor.sha256,
                size_bytes=descriptor.size_bytes,
                row_count=descriptor.row_count,
                shard_id=shard_id,
                first_key=str(shard_rows[0]["entry_cid"]),
                last_key=str(shard_rows[-1]["entry_cid"]),
                kind=CORPUS_INDEX_KIND,
                content_cid=descriptor.content_cid,
                start_document_index=int(shard_rows[0]["document_index"]),
                end_document_index=int(shard_rows[-1]["document_index"]),
                metadata={"jurisdiction_code": shard_code},
            ).to_dict()
            route["jurisdiction_code"] = shard_code
            route_rows.append(route)
            part_by_code[shard_code] += 1
            shard_rows.clear()

        for document_index, envelope in enumerate(iter_jsonl(ordered_path)):
            record_payload = envelope.get("record")
            if not isinstance(record_payload, Mapping):
                raise StateLawsCorpusPhysicalError(
                    "externally sorted corpus envelope lost its record"
                )
            record = CorpusRecord.from_mapping(record_payload)
            code = record.jurisdiction
            if shard_rows and (
                code != shard_code or len(shard_rows) >= max_rows_per_shard
            ):
                flush_shard()
            shard_code = code
            shard_rows.append(_physical_row(record, document_index=document_index))
            row_count_by_code[code] += 1
        flush_shard()

        if len(route_rows) > MAX_ROUTING_ROWS_PER_INDEX:
            raise StateLawsCorpusPhysicalError(
                "corpus route count exceeds the flat routing-index bound"
            )
        expected_start = 0
        for route in route_rows:
            if int(route["start_document_index"]) != expected_start:
                raise StateLawsCorpusPhysicalError(
                    "corpus document-index ranges are not dense and contiguous"
                )
            expected_start = int(route["end_document_index"]) + 1
        if expected_start != order_receipt.row_count:
            raise StateLawsCorpusPhysicalError(
                "corpus document-index routes do not cover every canonical row"
            )

        populated_codes = {code for code, count in row_count_by_code.items() if count}
        if populated_codes != set(receipts_by_code):
            missing = sorted(set(receipts_by_code) - populated_codes)
            raise StateLawsCorpusPhysicalError(
                f"source receipt jurisdictions have no corpus rows: {missing}"
            )
        for receipt in receipts:
            _validate_receipt(
                receipt, row_count=row_count_by_code[receipt.jurisdiction]
            )
            _validate_streaming_receipt_count_evidence(
                receipt,
                row_count=row_count_by_code[receipt.jurisdiction],
            )

        index_target = staging.confine(CORPUS_INDEX_PATH)
        write_zstd_parquet(
            index_target,
            tuple(route_rows),
            max_rows=MAX_ROUTING_ROWS_PER_INDEX,
            schema=_index_schema(),
        )
        corpus_index_descriptor = describe_file(
            index_target,
            root=staging.path,
            row_count=len(route_rows),
            family=ArtifactFamily.ROUTING_INDEX,
            schema_id=COMPACT_INDEX_SCHEMA_VERSION,
            first_key="0",
            last_key=str(order_receipt.row_count - 1),
            metadata={"index_name": "corpus_documents", "streaming": True},
        )

        for receipt in receipts:
            receipt_target = staging.confine(receipt.relative_path)
            atomic_write_canonical_json(receipt_target, receipt.to_dict())
            receipt_descriptors.append(
                describe_file(
                    receipt_target,
                    root=staging.path,
                    row_count=1,
                    family=ArtifactFamily.RECEIPT,
                    media_type="application/json",
                    schema_id=receipt.schema_version,
                    first_key=receipt.receipt_id,
                    last_key=receipt.receipt_id,
                    metadata={
                        "jurisdiction_code": receipt.jurisdiction,
                        "receipt_kind": "source_receipt",
                    },
                )
            )

        staging.commit_tree(CORPUS_DATA_DIR)
        staging.commit_file(CORPUS_INDEX_PATH)
        for receipt in receipts:
            staging.commit_file(receipt.relative_path)

    for descriptor in (
        *data_descriptors,
        *receipt_descriptors,
        corpus_index_descriptor,
    ):
        verify_descriptor(root, descriptor)

    return StateLawsStreamingCorpusPhysicalLayout(
        output_dir=str(root),
        source_receipts=receipts,
        data_descriptors=tuple(data_descriptors),
        receipt_descriptors=tuple(receipt_descriptors),
        corpus_index_descriptor=corpus_index_descriptor,
        route_rows=tuple(route_rows),
        row_count=order_receipt.row_count,
        sort_receipts=sort_receipts,
    )


write_state_laws_corpus_physical_layout_streaming = (
    write_state_laws_corpus_physical_layout_from_iterable
)


def write_state_laws_corpus_physical_layout(
    events_or_records: Iterable[Any],
    *,
    source_receipts: Sequence[Any],
    output_dir: str | Path,
    max_rows_per_shard: int = MAX_ROWS_PER_PHYSICAL_SHARD,
) -> StateLawsCorpusPhysicalLayout:
    """Compatibility writer for already materialized admitted records.

    Production callers must use
    :func:`write_state_laws_corpus_physical_layout_from_iterable`.
    """

    if (
        not isinstance(max_rows_per_shard, int)
        or isinstance(max_rows_per_shard, bool)
        or not 1 <= max_rows_per_shard <= MAX_ROWS_PER_PHYSICAL_SHARD
    ):
        raise StateLawsCorpusPhysicalError(
            f"max_rows_per_shard must be within 1..{MAX_ROWS_PER_PHYSICAL_SHARD}"
        )

    records = tuple(
        _coerce_event_or_record(value, position=position)
        for position, value in enumerate(events_or_records)
    )
    if not records:
        raise StateLawsCorpusPhysicalError(
            "at least one admitted CorpusRecord is required"
        )
    for position, record in enumerate(records):
        _validate_admitted_record(record, position=position)

    entry_cids = [record.entry_cid for record in records]
    legal_ids = [record.legal_id for record in records]
    if len(entry_cids) != len(set(entry_cids)):
        raise StateLawsCorpusPhysicalError("duplicate entry_cid in corpus input")
    if len(legal_ids) != len(set(legal_ids)):
        raise StateLawsCorpusPhysicalError("duplicate legal_id in corpus input")

    # This is exactly the unchunked ordering in state_laws_bm25._document_sort_tuple.
    ordered = tuple(sorted(records, key=lambda row: (row.jurisdiction, row.entry_cid)))
    rows = tuple(
        _physical_row(record, document_index=document_index)
        for document_index, record in enumerate(ordered)
    )
    rows_by_jurisdiction: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        rows_by_jurisdiction[str(row["jurisdiction_code"])].append(row)

    receipts = tuple(
        _coerce_source_receipt(value, position=position)
        for position, value in enumerate(source_receipts)
    )
    if not receipts:
        raise StateLawsCorpusPhysicalError("at least one source receipt is required")
    receipt_codes = [receipt.jurisdiction for receipt in receipts]
    receipt_ids = [receipt.receipt_id for receipt in receipts]
    receipt_paths = [receipt.relative_path for receipt in receipts]
    for label, values in (
        ("jurisdiction", receipt_codes),
        ("receipt_id", receipt_ids),
        ("relative_path", receipt_paths),
    ):
        if len(values) != len(set(values)):
            raise StateLawsCorpusPhysicalError(f"duplicate source receipt {label}")
    if set(receipt_codes) != set(rows_by_jurisdiction):
        missing = sorted(set(rows_by_jurisdiction) - set(receipt_codes))
        extra = sorted(set(receipt_codes) - set(rows_by_jurisdiction))
        raise StateLawsCorpusPhysicalError(
            f"source receipt jurisdiction mismatch: missing={missing}, extra={extra}"
        )
    receipts = tuple(sorted(receipts, key=lambda item: item.jurisdiction))
    receipts_by_code = {receipt.jurisdiction: receipt for receipt in receipts}
    for code, jurisdiction_rows in rows_by_jurisdiction.items():
        receipt = receipts_by_code[code]
        _validate_receipt(receipt, row_count=len(jurisdiction_rows))
        row_receipt_ids = {
            str(row["acquisition_receipt_id"]) for row in jurisdiction_rows
        }
        if row_receipt_ids != {receipt.receipt_id}:
            raise StateLawsCorpusPhysicalError(
                f"corpus rows for {code} do not bind source receipt {receipt.receipt_id!r}"
            )

    root = resolve_release_root(output_dir, must_exist=False)
    root.mkdir(parents=True, exist_ok=True)
    writer_config = ArtifactWriterConfig(max_rows_per_shard=max_rows_per_shard)
    data_descriptors: list[ArtifactDescriptor] = []
    receipt_descriptors: list[ArtifactDescriptor] = []
    route_rows: list[dict[str, Any]] = []

    with atomic_staging(root, prefix=".state-laws-corpus-") as staging:
        shard_id = 0
        for code in sorted(rows_by_jurisdiction):
            jurisdiction_rows = rows_by_jurisdiction[code]
            for part_index, start in enumerate(
                range(0, len(jurisdiction_rows), max_rows_per_shard)
            ):
                shard_rows = jurisdiction_rows[start : start + max_rows_per_shard]
                # Do not use Hive's ``jurisdiction=XX`` spelling here: Arrow
                # would synthesize a dictionary partition column that clashes
                # with the canonical direct string ``jurisdiction`` column.
                relative_path = (
                    f"{CORPUS_DATA_DIR}/jurisdiction/{code}/"
                    f"part-{part_index:06d}.parquet"
                )
                target = staging.confine(relative_path)
                write_zstd_parquet(
                    target,
                    shard_rows,
                    max_rows=max_rows_per_shard,
                    config=writer_config,
                    schema=_corpus_schema(),
                )
                descriptor = describe_file(
                    target,
                    root=staging.path,
                    row_count=len(shard_rows),
                    family=ArtifactFamily.CORPUS,
                    schema_id=CORPUS_ROW_SCHEMA_VERSION,
                    first_key=str(shard_rows[0]["entry_cid"]),
                    last_key=str(shard_rows[-1]["entry_cid"]),
                    shard_id=shard_id,
                    metadata={
                        "jurisdiction_code": code,
                        "start_document_index": int(shard_rows[0]["document_index"]),
                        "end_document_index": int(shard_rows[-1]["document_index"]),
                    },
                )
                data_descriptors.append(descriptor)
                route = CompactIndexRow(
                    relative_path=descriptor.relative_path,
                    sha256=descriptor.sha256,
                    size_bytes=descriptor.size_bytes,
                    row_count=descriptor.row_count,
                    shard_id=shard_id,
                    first_key=str(shard_rows[0]["entry_cid"]),
                    last_key=str(shard_rows[-1]["entry_cid"]),
                    kind=CORPUS_INDEX_KIND,
                    content_cid=descriptor.content_cid,
                    start_document_index=int(shard_rows[0]["document_index"]),
                    end_document_index=int(shard_rows[-1]["document_index"]),
                    metadata={"jurisdiction_code": code},
                ).to_dict()
                route["jurisdiction_code"] = code
                route_rows.append(route)
                shard_id += 1

        route_rows.sort(key=lambda row: int(row["start_document_index"]))
        expected_start = 0
        for route in route_rows:
            if int(route["start_document_index"]) != expected_start:
                raise StateLawsCorpusPhysicalError(
                    "corpus document-index ranges are not dense and contiguous"
                )
            expected_start = int(route["end_document_index"]) + 1
        if expected_start != len(rows):
            raise StateLawsCorpusPhysicalError(
                "corpus document-index routes do not cover every canonical row"
            )

        index_target = staging.confine(CORPUS_INDEX_PATH)
        write_zstd_parquet(
            index_target,
            route_rows,
            max_rows=MAX_ROWS_PER_PHYSICAL_SHARD,
            schema=_index_schema(),
        )
        corpus_index_descriptor = describe_file(
            index_target,
            root=staging.path,
            row_count=len(route_rows),
            family=ArtifactFamily.ROUTING_INDEX,
            schema_id=COMPACT_INDEX_SCHEMA_VERSION,
            first_key="0",
            last_key=str(len(rows) - 1),
            metadata={"index_name": "corpus_documents"},
        )

        for receipt in receipts:
            receipt_target = staging.confine(receipt.relative_path)
            atomic_write_canonical_json(receipt_target, receipt.to_dict())
            receipt_descriptors.append(
                describe_file(
                    receipt_target,
                    root=staging.path,
                    row_count=1,
                    family=ArtifactFamily.RECEIPT,
                    media_type="application/json",
                    schema_id=receipt.schema_version,
                    first_key=receipt.receipt_id,
                    last_key=receipt.receipt_id,
                    metadata={
                        "jurisdiction_code": receipt.jurisdiction,
                        "receipt_kind": "source_receipt",
                    },
                )
            )

        staging.commit_tree(CORPUS_DATA_DIR)
        staging.commit_file(CORPUS_INDEX_PATH)
        for receipt in receipts:
            staging.commit_file(receipt.relative_path)

    # Re-resolve every committed path.  A symlink inserted between staging and
    # return must not be accepted as a release artifact.
    for descriptor in (
        *data_descriptors,
        *receipt_descriptors,
        corpus_index_descriptor,
    ):
        target = confine_path(root, descriptor.relative_path)
        if target.is_symlink() or not target.is_file():
            raise StateLawsCorpusPhysicalError(
                f"committed corpus artifact is missing or unsafe: {descriptor.relative_path}"
            )

    return StateLawsCorpusPhysicalLayout(
        output_dir=str(root),
        rows=rows,
        source_receipts=receipts,
        data_descriptors=tuple(data_descriptors),
        receipt_descriptors=tuple(receipt_descriptors),
        corpus_index_descriptor=corpus_index_descriptor,
        route_rows=tuple(route_rows),
    )


__all__ = [
    "AUTHORIZES_HUB_UPLOAD",
    "AUTHORIZES_PUBLICATION",
    "CORPUS_DATA_DIR",
    "CORPUS_DOCUMENT_INDEX_PATH",
    "CORPUS_INDEX_PATH",
    "CORPUS_ROW_SCHEMA_VERSION",
    "ITERABLE_TO_LAYOUT_PRODUCTION_READY",
    "MATERIALIZED_TO_LAYOUT_PRODUCTION_READY",
    "SCHEMA_VERSION",
    "StateLawsCorpusPhysicalError",
    "StateLawsCorpusPhysicalLayout",
    "StateLawsStreamingCorpusPhysicalLayout",
    "write_state_laws_corpus_physical_layout",
    "write_state_laws_corpus_physical_layout_from_iterable",
    "write_state_laws_corpus_physical_layout_streaming",
]
