"""Canonical persisted chunk corpus for production state-law retrieval.

The normalized parent corpus is reopened from its committed Parquet
descriptors, chunked exactly once, and spilled through the shared external
sorter.  The resulting direct-column rows are the sole replay source for
BM25, embeddings, vectors, and query hydration.  In particular, consumers do
not independently rechunk parent statutes.

All writes are local and staged atomically.  This module performs no network
I/O and never authorizes publication or upload.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from ipfs_datasets_py.processors.legal_data.open_us_law_embeddings import (
    PINNED_TOKEN_COUNTER_ID,
)
from ipfs_datasets_py.processors.legal_data.state_laws_chunker import (
    DEFAULT_MAX_CHUNKS_PER_SECTION,
    DEFAULT_OVERLAP_TOKENS,
    DEFAULT_TOKENIZER_ID,
    StateLawsChunker,
    StateLawsChunkerError,
    assert_exact_reconstruction,
    reconstruct_text,
    validate_model_token_limit,
)
from ipfs_datasets_py.processors.legal_data.state_laws_corpus_physical import (
    CORPUS_ROW_SCHEMA_VERSION,
    StateLawsStreamingCorpusPhysicalLayout,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    validate_entry_cid,
    validate_jurisdiction,
)
from ipfs_datasets_py.retrieval.hf_graphrag.artifacts import (
    ArtifactIntegrityError,
    ArtifactWriterConfig,
    atomic_staging,
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
    ExternalSortError,
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
    canonical_json_dumps,
    content_sha256,
)

SCHEMA_VERSION: Final = "state-laws-chunk-physical/v1"
CHUNK_ROW_SCHEMA_VERSION: Final = "state-laws-chunk-row-physical/v1"
CHUNK_DATA_DIR: Final = "data/corpus_chunks"
CHUNK_INDEX_PATH: Final = "indexes/corpus_chunks.parquet"
CHUNK_INDEX_KIND: Final = "corpus_chunk_range"
CANONICAL_DOCUMENT_ORDER: Final = ("jurisdiction_code", "chunk_cid")

AUTHORIZES_PUBLICATION: Final = False
AUTHORIZES_HUB_UPLOAD: Final = False
STREAMING_CHUNK_STORE_PRODUCTION_READY: Final = True

ModelTokenCounter = Callable[[str], int]

_REQUIRED_PARENT_COLUMNS: Final = frozenset(
    {
        "acquisition_receipt_id",
        "acquisition_time",
        "admission_reason",
        "admission_status",
        "code_family",
        "document_index",
        "entry_cid",
        "jurisdiction",
        "jurisdiction_code",
        "legal_id",
        "official_source_url",
        "parser_version",
        "release_point",
        "section",
        "source_authority_class",
        "source_checksum",
        "source_cid",
        "text",
        "verification_result",
    }
)


class StateLawsChunkPhysicalError(ValueError):
    """Raised when canonical chunks cannot be persisted without loss."""


def _pyarrow() -> tuple[Any, Any]:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - production dependency
        raise StateLawsChunkPhysicalError(
            "pyarrow is required for the state-law canonical chunk store"
        ) from exc
    return pa, pq


def _chunk_schema() -> Any:
    pa, _ = _pyarrow()
    return pa.schema(
        [
            ("schema_version", pa.string(), False),
            ("document_index", pa.int64(), False),
            ("parent_document_index", pa.int64(), False),
            ("entry_cid", pa.string(), False),
            ("chunk_cid", pa.string(), False),
            ("parent_entry_cid", pa.string(), False),
            ("chunk_id", pa.string(), False),
            ("chunk_index", pa.int64(), False),
            ("legal_id", pa.string(), False),
            ("parent_legal_id", pa.string(), False),
            ("jurisdiction", pa.string(), False),
            ("jurisdiction_code", pa.string(), False),
            ("code_family", pa.string(), False),
            ("section", pa.string(), False),
            ("title", pa.string(), True),
            ("chapter", pa.string(), True),
            ("subsection", pa.string(), True),
            ("part", pa.string(), True),
            ("article", pa.string(), True),
            ("heading", pa.string(), True),
            ("parent_path", pa.list_(pa.string()), False),
            ("body", pa.string(), False),
            ("exclusive_text", pa.string(), False),
            ("text", pa.string(), False),
            ("char_start", pa.int64(), False),
            ("char_end", pa.int64(), False),
            ("token_start", pa.int64(), False),
            ("token_end", pa.int64(), False),
            ("token_count", pa.int64(), False),
            ("context_char_start", pa.int64(), False),
            ("context_token_start", pa.int64(), False),
            ("overlap_token_count", pa.int64(), False),
            ("split_mode", pa.string(), False),
            ("limit_exempt", pa.bool_(), False),
            ("model_token_limit", pa.int64(), False),
            ("model_input_token_count", pa.int64(), True),
            ("model_token_counter_id", pa.string(), True),
            ("tokenizer_id", pa.string(), False),
            ("chunker_schema_version", pa.string(), False),
            ("record_type", pa.string(), False),
            ("disposition", pa.string(), False),
            ("admission_status", pa.string(), False),
            ("admission_reason", pa.string(), False),
            ("source_authority_class", pa.string(), False),
            ("verification_result", pa.string(), False),
            ("source_cid", pa.string(), False),
            ("release_point", pa.string(), False),
            ("source_checksum", pa.string(), False),
            ("acquisition_time", pa.string(), False),
            ("official_source_url", pa.string(), False),
            ("acquisition_receipt_id", pa.string(), False),
            ("parser_version", pa.string(), False),
            ("edition_as_of", pa.string(), True),
            ("effective_date", pa.string(), True),
            ("observed_at", pa.string(), True),
            ("source_parent_path", pa.string(), True),
            ("parent_text_sha256", pa.string(), False),
            ("body_sha256", pa.string(), False),
            ("embedding_text_sha256", pa.string(), False),
        ],
        metadata={
            b"document_order": b"jurisdiction_code,chunk_cid",
            b"primary_key": b"entry_cid",
            b"schema_version": CHUNK_ROW_SCHEMA_VERSION.encode("ascii"),
        },
    )


def _index_schema() -> Any:
    pa, _ = _pyarrow()
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


def _identity_sort_key(row: Mapping[str, Any]) -> tuple[str]:
    return (str(row.get("chunk_cid") or ""),)


def _canonical_sort_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return (
        str(row.get("jurisdiction_code") or ""),
        str(row.get("chunk_cid") or ""),
    )


def _sort_receipt_payload(receipt: Any) -> dict[str, Any]:
    """Keep durable sort evidence while omitting deleted staging paths."""

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


def _parent_corpus_digest(layout: StateLawsStreamingCorpusPhysicalLayout) -> str:
    return content_sha256(
        canonical_json_dumps(
            {
                "corpus_index": layout.corpus_index_descriptor.to_dict(),
                "data": [item.to_dict() for item in layout.data_descriptors],
                "row_count": layout.row_count,
            }
        )
    )


def _iter_verified_parent_rows(
    layout: StateLawsStreamingCorpusPhysicalLayout,
) -> Iterator[dict[str, Any]]:
    """Verify and reopen every committed parent shard in bounded batches."""

    _, pq = _pyarrow()
    root = Path(layout.output_dir)
    try:
        verify_descriptor(root, layout.corpus_index_descriptor)
    except ArtifactIntegrityError as exc:
        raise StateLawsChunkPhysicalError(
            "parent corpus routing-index descriptor failed verification"
        ) from exc

    expected_document_index = 0
    for descriptor in layout.data_descriptors:
        if descriptor.family is not ArtifactFamily.CORPUS:
            raise StateLawsChunkPhysicalError(
                f"parent descriptor is not corpus data: {descriptor.relative_path}"
            )
        if descriptor.schema_id != CORPUS_ROW_SCHEMA_VERSION:
            raise StateLawsChunkPhysicalError(
                f"parent descriptor schema is not canonical: {descriptor.relative_path}"
            )
        try:
            path = verify_descriptor(root, descriptor)
            parquet = pq.ParquetFile(path)
        except Exception as exc:
            raise StateLawsChunkPhysicalError(
                f"parent corpus descriptor failed verification: {descriptor.relative_path}"
            ) from exc
        if int(parquet.metadata.num_rows) != descriptor.row_count:
            raise StateLawsChunkPhysicalError(
                f"parent Parquet row count disagrees with descriptor: {descriptor.relative_path}"
            )
        missing = _REQUIRED_PARENT_COLUMNS.difference(parquet.schema_arrow.names)
        if missing:
            raise StateLawsChunkPhysicalError(
                f"parent Parquet lacks direct columns {sorted(missing)}: "
                f"{descriptor.relative_path}"
            )
        observed = 0
        try:
            batches = parquet.iter_batches(batch_size=MAX_ROWS_PER_PHYSICAL_SHARD)
            for batch in batches:
                if batch.num_rows > MAX_ROWS_PER_PHYSICAL_SHARD:
                    raise StateLawsChunkPhysicalError(
                        "parent Parquet reader exceeded its bounded batch size"
                    )
                for row in batch.to_pylist():
                    document_index = row.get("document_index")
                    if type(document_index) is not int:
                        raise StateLawsChunkPhysicalError(
                            "parent document_index must be an integer"
                        )
                    if document_index != expected_document_index:
                        raise StateLawsChunkPhysicalError(
                            "parent document indexes are not dense in committed order"
                        )
                    expected_document_index += 1
                    observed += 1
                    yield dict(row)
        except StateLawsChunkPhysicalError:
            raise
        except Exception as exc:
            raise StateLawsChunkPhysicalError(
                f"parent Parquet could not be read: {descriptor.relative_path}"
            ) from exc
        if observed != descriptor.row_count:
            raise StateLawsChunkPhysicalError(
                f"parent Parquet iteration lost rows: {descriptor.relative_path}"
            )
    if expected_document_index != layout.row_count:
        raise StateLawsChunkPhysicalError(
            "parent corpus descriptor rows do not match the layout row count"
        )


def _optional_parent_text(row: Mapping[str, Any], name: str) -> str | None:
    value = row.get(name)
    return None if value is None or value == "" else str(value)


def _validate_parent_row(parent: Mapping[str, Any]) -> None:
    parent_entry_cid = validate_entry_cid(
        str(parent.get("entry_cid") or ""), name="parent_entry_cid"
    )
    validate_entry_cid(str(parent.get("source_cid") or ""), name="source_cid")
    jurisdiction = validate_jurisdiction(
        str(parent.get("jurisdiction_code") or ""), name="jurisdiction_code"
    )
    if str(parent.get("jurisdiction") or "") != jurisdiction:
        raise StateLawsChunkPhysicalError(
            f"parent jurisdiction columns disagree: {parent_entry_cid}"
        )
    required_values = {
        "acquisition_receipt_id",
        "acquisition_time",
        "admission_reason",
        "code_family",
        "legal_id",
        "official_source_url",
        "parser_version",
        "release_point",
        "section",
        "source_checksum",
    }
    missing = sorted(
        name
        for name in required_values
        if not isinstance(parent.get(name), str) or not str(parent[name]).strip()
    )
    if missing:
        raise StateLawsChunkPhysicalError(
            f"parent lacks required canonical values {missing}: {parent_entry_cid}"
        )
    expected_gates = {
        "admission_status": "admitted",
        "source_authority_class": "official",
        "verification_result": "verified",
    }
    for name, expected in expected_gates.items():
        if str(parent.get(name) or "").strip().lower() != expected:
            raise StateLawsChunkPhysicalError(
                f"parent is not {expected} at {name}: {parent_entry_cid}"
            )


def _physical_chunk_row(
    chunk: Any,
    parent: Mapping[str, Any],
    *,
    model_input_token_count: int | None,
    model_token_counter_id: str | None,
    parent_text_sha256: str,
) -> dict[str, Any]:
    parent_entry_cid = validate_entry_cid(
        str(parent.get("entry_cid") or ""), name="parent_entry_cid"
    )
    chunk_cid = validate_entry_cid(str(chunk.chunk_cid), name="chunk_cid")
    jurisdiction = validate_jurisdiction(
        str(parent.get("jurisdiction_code") or parent.get("jurisdiction") or ""),
        name="jurisdiction_code",
    )
    if chunk.jurisdiction != jurisdiction:
        raise StateLawsChunkPhysicalError(
            f"chunk jurisdiction drifted from parent {parent_entry_cid}"
        )
    if not chunk.exclusive_text:
        raise StateLawsChunkPhysicalError(
            f"chunk has empty exclusive statutory text: {chunk_cid}"
        )
    if not chunk.text:
        raise StateLawsChunkPhysicalError(
            f"chunk has empty embedding text: {chunk_cid}"
        )
    if chunk.char_end <= chunk.char_start:
        raise StateLawsChunkPhysicalError(f"chunk has an empty span: {chunk_cid}")

    # ``body`` is deliberately exclusive for BM25; ``text`` may carry the
    # chunker's controlled overlap and is the pinned embedding input field.
    return {
        "schema_version": CHUNK_ROW_SCHEMA_VERSION,
        "parent_document_index": int(parent["document_index"]),
        "entry_cid": chunk_cid,
        "chunk_cid": chunk_cid,
        "parent_entry_cid": parent_entry_cid,
        "chunk_id": str(chunk.chunk_id),
        "chunk_index": int(chunk.chunk_index),
        "legal_id": str(parent["legal_id"]),
        "parent_legal_id": str(chunk.parent_legal_id),
        "jurisdiction": jurisdiction,
        "jurisdiction_code": jurisdiction,
        "code_family": str(parent["code_family"]),
        "section": str(parent["section"]),
        "title": _optional_parent_text(parent, "title"),
        "chapter": _optional_parent_text(parent, "chapter"),
        "subsection": _optional_parent_text(parent, "subsection"),
        "part": chunk.part or None,
        "article": chunk.article or None,
        "heading": chunk.heading or None,
        "parent_path": list(chunk.parent_path),
        "body": chunk.exclusive_text,
        "exclusive_text": chunk.exclusive_text,
        "text": chunk.text,
        "char_start": int(chunk.char_start),
        "char_end": int(chunk.char_end),
        "token_start": int(chunk.token_start),
        "token_end": int(chunk.token_end),
        "token_count": int(chunk.token_count),
        "context_char_start": int(chunk.context_char_start),
        "context_token_start": int(chunk.context_token_start),
        "overlap_token_count": int(chunk.overlap_token_count),
        "split_mode": str(chunk.split_mode),
        "limit_exempt": bool(chunk.limit_exempt),
        "model_token_limit": int(chunk.model_token_limit),
        "model_input_token_count": model_input_token_count,
        "model_token_counter_id": model_token_counter_id,
        "tokenizer_id": str(chunk.tokenizer_id),
        "chunker_schema_version": str(chunk.schema_version),
        "record_type": "statute_chunk",
        "disposition": "admitted",
        "admission_status": str(parent["admission_status"]),
        "admission_reason": str(parent["admission_reason"]),
        "source_authority_class": str(parent["source_authority_class"]),
        "verification_result": str(parent["verification_result"]),
        "source_cid": str(parent["source_cid"]),
        "release_point": str(parent["release_point"]),
        "source_checksum": str(parent["source_checksum"]),
        "acquisition_time": str(parent["acquisition_time"]),
        "official_source_url": str(parent["official_source_url"]),
        "acquisition_receipt_id": str(parent["acquisition_receipt_id"]),
        "parser_version": str(parent["parser_version"]),
        "edition_as_of": _optional_parent_text(parent, "edition_as_of"),
        "effective_date": _optional_parent_text(parent, "effective_date"),
        "observed_at": _optional_parent_text(parent, "observed_at"),
        "source_parent_path": _optional_parent_text(parent, "parent_path"),
        "parent_text_sha256": parent_text_sha256,
        "body_sha256": content_sha256(chunk.exclusive_text),
        "embedding_text_sha256": content_sha256(chunk.text),
    }


@dataclass(frozen=True, slots=True)
class StateLawsChunkPhysicalLayout:
    """Descriptor-complete, replayable canonical state-law chunk corpus."""

    output_dir: str
    parent_corpus_digest: str
    data_descriptors: tuple[ArtifactDescriptor, ...]
    corpus_index_descriptor: ArtifactDescriptor
    route_rows: tuple[Mapping[str, Any], ...]
    parent_document_count: int
    chunk_count: int
    config: Mapping[str, Any]
    sort_receipts: Mapping[str, Mapping[str, Any]]
    model_token_validation_passed: bool

    def __post_init__(self) -> None:
        if self.parent_document_count < 1 or self.chunk_count < 1:
            raise StateLawsChunkPhysicalError(
                "canonical chunk layout must contain parents and chunks"
            )
        if self.chunk_count < self.parent_document_count:
            raise StateLawsChunkPhysicalError(
                "every parent must contribute at least one canonical chunk"
            )
        if len(self.parent_corpus_digest) != 64:
            raise StateLawsChunkPhysicalError("parent corpus digest is invalid")
        if sum(item.row_count for item in self.data_descriptors) != self.chunk_count:
            raise StateLawsChunkPhysicalError(
                "chunk descriptors do not conserve the chunk count"
            )
        if len(self.data_descriptors) != len(self.route_rows):
            raise StateLawsChunkPhysicalError(
                "chunk descriptor and route counts do not match"
            )
        if self.corpus_index_descriptor.row_count != len(self.route_rows):
            raise StateLawsChunkPhysicalError(
                "chunk routing-index descriptor count does not match routes"
            )
        if (
            sum(int(row.get("row_count") or 0) for row in self.route_rows)
            != self.chunk_count
        ):
            raise StateLawsChunkPhysicalError("chunk routes do not conserve rows")
        if set(self.sort_receipts) != {"canonical_order", "chunk_identity"}:
            raise StateLawsChunkPhysicalError(
                "chunk layout lacks identity and canonical-order sort receipts"
            )
        frozen_receipts: dict[str, Mapping[str, Any]] = {}
        for label in sorted(self.sort_receipts):
            receipt = dict(self.sort_receipts[label])
            if receipt.get("status") != "complete":
                raise StateLawsChunkPhysicalError(f"chunk sort {label} is incomplete")
            for count_name in ("records_consumed", "row_count"):
                if int(receipt.get(count_name) or 0) != self.chunk_count:
                    raise StateLawsChunkPhysicalError(
                        f"chunk sort {label} {count_name} does not match chunk_count"
                    )
            maximum = int(receipt.get("max_records_in_memory") or 0)
            peak = int(receipt.get("peak_resident_records") or 0)
            if maximum < 2 or peak < 1 or peak > maximum:
                raise StateLawsChunkPhysicalError(
                    f"chunk sort {label} violated its spill bound"
                )
            if len(str(receipt.get("output_digest") or "")) != 64:
                raise StateLawsChunkPhysicalError(
                    f"chunk sort {label} lacks an output digest"
                )
            frozen_receipts[label] = MappingProxyType(receipt)
        if not isinstance(self.model_token_validation_passed, bool):
            raise StateLawsChunkPhysicalError(
                "model_token_validation_passed must be a boolean"
            )
        counter_id = self.config.get("model_token_counter_id")
        if self.model_token_validation_passed and (
            not isinstance(counter_id, str) or not counter_id.strip()
        ):
            raise StateLawsChunkPhysicalError(
                "production chunk layout lacks model-token validator identity"
            )
        object.__setattr__(self, "sort_receipts", MappingProxyType(frozen_receipts))
        object.__setattr__(self, "config", MappingProxyType(dict(self.config)))

    @property
    def production_ready(self) -> bool:
        return bool(
            STREAMING_CHUNK_STORE_PRODUCTION_READY
            and self.model_token_validation_passed
            and self.config.get("model_token_counter_id") == PINNED_TOKEN_COUNTER_ID
        )

    @property
    def descriptors(self) -> tuple[ArtifactDescriptor, ...]:
        return (*self.data_descriptors, self.corpus_index_descriptor)

    @property
    def indexes(self) -> dict[str, dict[str, Any]]:
        return {"corpus_chunks": _manifest_descriptor(self.corpus_index_descriptor)}

    @property
    def counts(self) -> dict[str, int]:
        return {
            "canonical_chunk_shards": len(self.data_descriptors),
            "canonical_chunks": self.chunk_count,
            "parent_documents": self.parent_document_count,
            "searchable_chunks": self.chunk_count,
        }

    @property
    def jurisdictions(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    str(item.metadata.get("jurisdiction_code") or "")
                    for item in self.data_descriptors
                }
                - {""}
            )
        )

    def _iter_chunks_for_code(
        self, jurisdiction_code: str | None
    ) -> Iterator[dict[str, Any]]:
        _, pq = _pyarrow()
        root = Path(self.output_dir)
        code = (
            validate_jurisdiction(jurisdiction_code, name="jurisdiction_code")
            if jurisdiction_code is not None
            else None
        )
        descriptors = tuple(
            item
            for item in self.data_descriptors
            if code is None or item.metadata.get("jurisdiction_code") == code
        )
        expected_document_index = (
            0
            if code is None or not descriptors
            else int(descriptors[0].metadata["start_document_index"])
        )
        previous_key: tuple[str, str] | None = None
        observed = 0
        for descriptor in descriptors:
            try:
                path = verify_descriptor(root, descriptor)
                parquet = pq.ParquetFile(path)
            except Exception as exc:
                raise StateLawsChunkPhysicalError(
                    f"canonical chunk descriptor failed verification: "
                    f"{descriptor.relative_path}"
                ) from exc
            if int(parquet.metadata.num_rows) != descriptor.row_count:
                raise StateLawsChunkPhysicalError(
                    f"canonical chunk descriptor row count drifted: "
                    f"{descriptor.relative_path}"
                )
            missing = set(_chunk_schema().names).difference(parquet.schema_arrow.names)
            if missing:
                raise StateLawsChunkPhysicalError(
                    f"canonical chunk shard lacks direct columns {sorted(missing)}"
                )
            shard_observed = 0
            for batch in parquet.iter_batches(batch_size=MAX_ROWS_PER_PHYSICAL_SHARD):
                if batch.num_rows > MAX_ROWS_PER_PHYSICAL_SHARD:
                    raise StateLawsChunkPhysicalError(
                        "chunk replay exceeded the bounded batch size"
                    )
                for raw in batch.to_pylist():
                    row = dict(raw)
                    cid = str(row.get("chunk_cid") or "")
                    if row.get("entry_cid") != cid:
                        raise StateLawsChunkPhysicalError(
                            "canonical chunk entry_cid is not its chunk_cid"
                        )
                    validate_entry_cid(cid, name="chunk_cid")
                    row_code = validate_jurisdiction(
                        str(row.get("jurisdiction_code") or ""),
                        name="jurisdiction_code",
                    )
                    key = (row_code, cid)
                    if previous_key is not None and key <= previous_key:
                        raise StateLawsChunkPhysicalError(
                            "canonical chunk replay order is not strictly increasing"
                        )
                    if int(row.get("document_index", -1)) != expected_document_index:
                        raise StateLawsChunkPhysicalError(
                            "canonical chunk document indexes are not dense"
                        )
                    if row.get("body") != row.get("exclusive_text"):
                        raise StateLawsChunkPhysicalError(
                            f"BM25 body drifted from exclusive text: {cid}"
                        )
                    if content_sha256(str(row["body"])) != row.get("body_sha256"):
                        raise StateLawsChunkPhysicalError(
                            f"canonical chunk body digest drifted: {cid}"
                        )
                    if content_sha256(str(row["text"])) != row.get(
                        "embedding_text_sha256"
                    ):
                        raise StateLawsChunkPhysicalError(
                            f"canonical chunk embedding-text digest drifted: {cid}"
                        )
                    previous_key = key
                    expected_document_index += 1
                    observed += 1
                    shard_observed += 1
                    yield row
            if shard_observed != descriptor.row_count:
                raise StateLawsChunkPhysicalError(
                    f"canonical chunk replay lost rows: {descriptor.relative_path}"
                )
        expected_count = sum(item.row_count for item in descriptors)
        if observed != expected_count:
            raise StateLawsChunkPhysicalError(
                "canonical chunk replay count does not match descriptors"
            )
        if code is None and observed != self.chunk_count:
            raise StateLawsChunkPhysicalError(
                "canonical chunk replay count does not match the layout"
            )

    def iter_chunks(
        self, *, jurisdiction_code: str | None = None
    ) -> Iterator[dict[str, Any]]:
        """Reopen and replay canonical rows without rerunning the chunker."""

        yield from self._iter_chunks_for_code(jurisdiction_code)

    def iter_jurisdiction_chunks(
        self, jurisdiction_code: str
    ) -> Iterator[dict[str, Any]]:
        """Replay only one jurisdiction, opening no other jurisdiction shards."""

        yield from self._iter_chunks_for_code(jurisdiction_code)

    def _iter_key_rows(self, columns: tuple[str, ...]) -> Iterator[dict[str, Any]]:
        """Replay narrow key columns without hydrating statutory text."""

        _, pq = _pyarrow()
        root = Path(self.output_dir)
        observed = 0
        for descriptor in self.data_descriptors:
            try:
                path = verify_descriptor(root, descriptor)
                parquet = pq.ParquetFile(path)
            except Exception as exc:
                raise StateLawsChunkPhysicalError(
                    f"canonical chunk descriptor failed verification: "
                    f"{descriptor.relative_path}"
                ) from exc
            if int(parquet.metadata.num_rows) != descriptor.row_count:
                raise StateLawsChunkPhysicalError(
                    f"canonical chunk descriptor row count drifted: "
                    f"{descriptor.relative_path}"
                )
            if set(columns).difference(parquet.schema_arrow.names):
                raise StateLawsChunkPhysicalError(
                    f"canonical chunk shard lacks key columns: "
                    f"{descriptor.relative_path}"
                )
            shard_observed = 0
            for batch in parquet.iter_batches(
                batch_size=MAX_ROWS_PER_PHYSICAL_SHARD,
                columns=list(columns),
            ):
                for row in batch.to_pylist():
                    shard_observed += 1
                    observed += 1
                    yield dict(row)
            if shard_observed != descriptor.row_count:
                raise StateLawsChunkPhysicalError(
                    f"canonical chunk key replay lost rows: {descriptor.relative_path}"
                )
        if observed != self.chunk_count:
            raise StateLawsChunkPhysicalError(
                "canonical chunk key replay count does not match the layout"
            )

    def iter_document_chunk_keys(self) -> Iterator[tuple[int, str]]:
        """Stream dense positional hydration keys in canonical chunk order."""

        previous: tuple[str, str] | None = None
        for expected_document_index, row in enumerate(
            self._iter_key_rows(
                ("document_index", "entry_cid", "chunk_cid", "jurisdiction_code")
            )
        ):
            chunk_cid = str(row.get("chunk_cid") or "")
            if row.get("entry_cid") != chunk_cid:
                raise StateLawsChunkPhysicalError(
                    "canonical chunk entry_cid is not its chunk_cid"
                )
            validate_entry_cid(chunk_cid, name="chunk_cid")
            jurisdiction = validate_jurisdiction(
                str(row.get("jurisdiction_code") or ""),
                name="jurisdiction_code",
            )
            key = jurisdiction, chunk_cid
            if previous is not None and key <= previous:
                raise StateLawsChunkPhysicalError(
                    "canonical chunk key replay is not strictly ordered"
                )
            document_index = row.get("document_index")
            if (
                type(document_index) is not int
                or document_index != expected_document_index
            ):
                raise StateLawsChunkPhysicalError(
                    "canonical chunk positional keys are not dense"
                )
            previous = key
            yield document_index, chunk_cid

    def iter_chunk_cids(self) -> Iterator[str]:
        for _document_index, chunk_cid in self.iter_document_chunk_keys():
            yield chunk_cid

    def iter_parent_entry_cids(self) -> Iterator[str]:
        """Stream one durable parent key for every canonical chunk row."""

        for row in self._iter_key_rows(("parent_entry_cid",)):
            yield validate_entry_cid(
                str(row.get("parent_entry_cid") or ""), name="parent_entry_cid"
            )

    @property
    def key_evidence(self) -> dict[str, Iterable[str]]:
        return {
            "chunk_cids": self.iter_chunk_cids(),
            "parent_entry_cids": self.iter_parent_entry_cids(),
        }

    def to_manifest_fragment(self) -> dict[str, Any]:
        config = dict(self.config)
        return {
            "artifacts": [_manifest_descriptor(item) for item in self.data_descriptors],
            "configs": {
                "corpus": f"{CHUNK_DATA_DIR}/jurisdiction/*/*.parquet",
                "corpus_index": CHUNK_INDEX_PATH,
            },
            "corpus": {
                "body_field": "body",
                "direct_columns": True,
                "document_order": list(CANONICAL_DOCUMENT_ORDER),
                "embedding_text_field": "text",
                "jurisdiction_partitioned": True,
                "parent_corpus_digest": self.parent_corpus_digest,
                "physical_schema_version": SCHEMA_VERSION,
                "primary_key": "entry_cid",
                "rechunk_downstream": False,
                "streaming": True,
                "model_token_validation": {
                    "counter_id": config.get("model_token_counter_id"),
                    "pinned_counter_id": PINNED_TOKEN_COUNTER_ID,
                    "pinned_identity_match": (
                        config.get("model_token_counter_id") == PINNED_TOKEN_COUNTER_ID
                    ),
                    "passed": self.model_token_validation_passed,
                    "required_for_production": True,
                },
            },
            "counts": self.counts,
            "default_config": config,
            "indexes": self.indexes,
            "jurisdictions": list(self.jurisdictions),
        }


def write_state_laws_chunk_physical_layout(
    corpus_layout: StateLawsStreamingCorpusPhysicalLayout,
    *,
    model_token_limit: int,
    output_dir: str | Path | None = None,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
    max_chunks_per_section: int = DEFAULT_MAX_CHUNKS_PER_SECTION,
    tokenizer_id: str = DEFAULT_TOKENIZER_ID,
    model_token_counter: ModelTokenCounter | None = None,
    model_token_counter_id: str | None = None,
    max_rows_per_shard: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    max_records_in_memory: int = DEFAULT_MAX_RECORDS_IN_MEMORY,
) -> StateLawsChunkPhysicalLayout:
    """Chunk a verified physical parent corpus exactly once and persist it."""

    if not isinstance(corpus_layout, StateLawsStreamingCorpusPhysicalLayout):
        raise StateLawsChunkPhysicalError(
            "corpus_layout must be a streaming state-law corpus layout"
        )
    if corpus_layout.production_ready is not True:
        raise StateLawsChunkPhysicalError(
            "parent corpus layout is not production ready"
        )
    limit = validate_model_token_limit(model_token_limit)
    if (
        type(max_rows_per_shard) is not int
        or not 1 <= max_rows_per_shard <= MAX_ROWS_PER_PHYSICAL_SHARD
    ):
        raise StateLawsChunkPhysicalError(
            f"max_rows_per_shard must be within 1..{MAX_ROWS_PER_PHYSICAL_SHARD}"
        )
    if type(max_records_in_memory) is not int or max_records_in_memory < 2:
        raise StateLawsChunkPhysicalError(
            "max_records_in_memory must be an integer of at least 2"
        )
    if type(overlap_tokens) is not int or overlap_tokens < 0:
        raise StateLawsChunkPhysicalError(
            "overlap_tokens must be a non-negative integer"
        )
    if type(max_chunks_per_section) is not int or max_chunks_per_section < 1:
        raise StateLawsChunkPhysicalError(
            "max_chunks_per_section must be a positive integer"
        )
    if model_token_counter is not None and not callable(model_token_counter):
        raise StateLawsChunkPhysicalError("model_token_counter must be callable")
    if model_token_counter is None and model_token_counter_id is not None:
        raise StateLawsChunkPhysicalError(
            "model_token_counter_id requires a model_token_counter"
        )
    if model_token_counter is not None:
        if (
            not isinstance(model_token_counter_id, str)
            or not model_token_counter_id.strip()
            or "\x00" in model_token_counter_id
            or len(model_token_counter_id.strip()) > 512
        ):
            raise StateLawsChunkPhysicalError(
                "model_token_counter_id must identify the supplied validator"
            )
        model_token_counter_id = model_token_counter_id.strip()
    try:
        chunker = StateLawsChunker(
            overlap_tokens=overlap_tokens,
            max_chunks_per_section=max_chunks_per_section,
            tokenizer_id=tokenizer_id,
        )
    except StateLawsChunkerError as exc:
        raise StateLawsChunkPhysicalError("invalid chunker configuration") from exc

    root = resolve_release_root(
        output_dir if output_dir is not None else corpus_layout.output_dir,
        must_exist=False,
    )
    root.mkdir(parents=True, exist_ok=True)
    writer_config = ArtifactWriterConfig(max_rows_per_shard=max_rows_per_shard)
    parent_digest = _parent_corpus_digest(corpus_layout)
    effective_overlap_tokens = min(overlap_tokens, max(0, limit - 1))
    config_payload = {
        "canonical_document_order": list(CANONICAL_DOCUMENT_ORDER),
        "max_chunks_per_section": chunker.max_chunks_per_section,
        "max_records_in_memory": max_records_in_memory,
        "max_rows_per_shard": max_rows_per_shard,
        "model_token_limit": limit,
        "model_token_counter_id": model_token_counter_id,
        "pinned_model_token_counter_id": PINNED_TOKEN_COUNTER_ID,
        "model_token_validation_required_for_production": True,
        "overlap_tokens": effective_overlap_tokens,
        "parent_corpus_digest": parent_digest,
        "requested_overlap_tokens": overlap_tokens,
        "schema_version": SCHEMA_VERSION,
        "tokenizer_id": chunker.tokenizer_id,
    }
    config_payload["config_digest"] = content_sha256(
        canonical_json_dumps(config_payload)
    )

    data_descriptors: list[ArtifactDescriptor] = []
    route_rows: list[dict[str, Any]] = []
    parent_count = 0
    chunk_count = 0
    sort_receipts: dict[str, Mapping[str, Any]] = {}

    with atomic_staging(root, prefix=".state-laws-chunks-") as staging:
        work = staging.path / ".work"
        work.mkdir(parents=True, exist_ok=True)

        def generated_chunks() -> Iterator[dict[str, Any]]:
            nonlocal parent_count, chunk_count
            for parent in _iter_verified_parent_rows(corpus_layout):
                parent_entry_cid = str(parent.get("entry_cid") or "")
                _validate_parent_row(parent)
                source_text = parent.get("text")
                if not isinstance(source_text, str) or not source_text.strip():
                    raise StateLawsChunkPhysicalError(
                        f"parent has empty canonical text: {parent_entry_cid}"
                    )
                try:
                    result = chunker.chunk_corpus_row(
                        parent,
                        model_token_limit=limit,
                    )
                except StateLawsChunkerError as exc:
                    raise StateLawsChunkPhysicalError(
                        f"chunking failed for parent {parent_entry_cid}"
                    ) from exc
                parent_count += 1
                if result.truncated:
                    raise StateLawsChunkPhysicalError(
                        f"chunker truncated statutory text for parent {parent_entry_cid}"
                    )
                if not result.chunks:
                    raise StateLawsChunkPhysicalError(
                        f"parent produced no canonical chunks: {parent_entry_cid}"
                    )
                if result.source_text != source_text:
                    raise StateLawsChunkPhysicalError(
                        f"chunker normalization changed canonical parent bytes: "
                        f"{parent_entry_cid}"
                    )
                try:
                    assert_exact_reconstruction(source_text, result.chunks)
                except StateLawsChunkerError as exc:
                    raise StateLawsChunkPhysicalError(
                        f"chunks do not reconstruct parent {parent_entry_cid}"
                    ) from exc
                if reconstruct_text(result.chunks) != source_text:
                    raise StateLawsChunkPhysicalError(
                        f"exclusive chunk bytes drifted for parent {parent_entry_cid}"
                    )
                if result.legal_id != str(parent.get("legal_id") or ""):
                    raise StateLawsChunkPhysicalError(
                        f"chunk legal identity drifted from parent {parent_entry_cid}"
                    )
                if (
                    result.model_token_limit != limit
                    or result.overlap_tokens != effective_overlap_tokens
                    or result.max_chunks_per_section != chunker.max_chunks_per_section
                    or result.tokenizer_id != chunker.tokenizer_id
                ):
                    raise StateLawsChunkPhysicalError(
                        f"chunker result configuration drifted for {parent_entry_cid}"
                    )
                parent_text_sha256 = content_sha256(source_text)
                for expected_index, chunk in enumerate(result.chunks):
                    if chunk.chunk_index != expected_index:
                        raise StateLawsChunkPhysicalError(
                            f"chunk indexes are not dense for parent {parent_entry_cid}"
                        )
                    model_input_token_count: int | None = None
                    if model_token_counter is not None:
                        try:
                            model_input_token_count = model_token_counter(chunk.text)
                        except Exception as exc:
                            raise StateLawsChunkPhysicalError(
                                f"model-token validation failed for chunk "
                                f"{chunk.chunk_cid}"
                            ) from exc
                        if (
                            type(model_input_token_count) is not int
                            or model_input_token_count < 0
                        ):
                            raise StateLawsChunkPhysicalError(
                                "model_token_counter must return a non-negative integer"
                            )
                        if model_input_token_count > limit:
                            raise StateLawsChunkPhysicalError(
                                f"embedding text exceeds model token limit under "
                                f"{model_token_counter_id}: chunk={chunk.chunk_cid} "
                                f"tokens={model_input_token_count} limit={limit}"
                            )
                    row = _physical_chunk_row(
                        chunk,
                        parent,
                        model_input_token_count=model_input_token_count,
                        model_token_counter_id=model_token_counter_id,
                        parent_text_sha256=parent_text_sha256,
                    )
                    chunk_count += 1
                    yield row

        identity_path = work / "chunk-identity.jsonl"
        try:
            identity_receipt = external_sort_to_file(
                generated_chunks(),
                identity_path,
                work_dir=work / "chunk-identity-sort",
                key_fn=_identity_sort_key,
                family="chunks",
                max_records_in_memory=max_records_in_memory,
                resume=False,
            )
        except ExternalSortError as exc:
            raise StateLawsChunkPhysicalError(
                "bounded canonical chunk identity sort failed"
            ) from exc
        sort_receipts["chunk_identity"] = _sort_receipt_payload(identity_receipt)
        if parent_count != corpus_layout.row_count:
            raise StateLawsChunkPhysicalError(
                "not every committed parent row was chunked exactly once"
            )
        if chunk_count < parent_count or identity_receipt.row_count != chunk_count:
            raise StateLawsChunkPhysicalError(
                "canonical chunk generation did not conserve parents and chunks"
            )

        def unique_chunks() -> Iterator[dict[str, Any]]:
            previous: str | None = None
            for row in iter_jsonl(identity_path):
                chunk_cid = str(row.get("chunk_cid") or "")
                if not chunk_cid or row.get("entry_cid") != chunk_cid:
                    raise StateLawsChunkPhysicalError(
                        "canonical chunk identity is empty or unbound"
                    )
                if chunk_cid == previous:
                    raise StateLawsChunkPhysicalError(
                        f"duplicate canonical chunk_cid: {chunk_cid}"
                    )
                if previous is not None and chunk_cid < previous:
                    raise StateLawsChunkPhysicalError(
                        "canonical chunk identity sort regressed"
                    )
                previous = chunk_cid
                yield row

        canonical_path = work / "canonical-order.jsonl"
        try:
            canonical_receipt = external_sort_to_file(
                unique_chunks(),
                canonical_path,
                work_dir=work / "canonical-order-sort",
                key_fn=_canonical_sort_key,
                family="chunks",
                max_records_in_memory=max_records_in_memory,
                resume=False,
            )
        except ExternalSortError as exc:
            raise StateLawsChunkPhysicalError(
                "bounded canonical chunk ordering failed"
            ) from exc
        sort_receipts["canonical_order"] = _sort_receipt_payload(canonical_receipt)
        if canonical_receipt.row_count != chunk_count:
            raise StateLawsChunkPhysicalError("canonical chunk ordering lost rows")

        shard_rows: list[dict[str, Any]] = []
        shard_code = ""
        part_by_code: dict[str, int] = defaultdict(int)

        def flush_shard() -> None:
            nonlocal shard_code
            if not shard_rows:
                return
            shard_id = len(data_descriptors)
            if shard_id >= MAX_ROUTING_ROWS_PER_INDEX:
                raise StateLawsChunkPhysicalError(
                    "chunk shard count exceeds the flat routing-index bound"
                )
            relative_path = (
                f"{CHUNK_DATA_DIR}/jurisdiction/{shard_code}/"
                f"part-{part_by_code[shard_code]:06d}.parquet"
            )
            target = staging.confine(relative_path)
            write_zstd_parquet(
                target,
                tuple(shard_rows),
                max_rows=max_rows_per_shard,
                config=writer_config,
                schema=_chunk_schema(),
            )
            descriptor = describe_file(
                target,
                root=staging.path,
                row_count=len(shard_rows),
                family=ArtifactFamily.CORPUS,
                schema_id=CHUNK_ROW_SCHEMA_VERSION,
                first_key=str(shard_rows[0]["chunk_cid"]),
                last_key=str(shard_rows[-1]["chunk_cid"]),
                shard_id=shard_id,
                metadata={
                    "canonical_order": list(CANONICAL_DOCUMENT_ORDER),
                    "end_document_index": int(shard_rows[-1]["document_index"]),
                    "jurisdiction_code": shard_code,
                    "stage": "canonical_chunks",
                    "start_document_index": int(shard_rows[0]["document_index"]),
                },
            )
            data_descriptors.append(descriptor)
            route = CompactIndexRow(
                relative_path=descriptor.relative_path,
                sha256=descriptor.sha256,
                size_bytes=descriptor.size_bytes,
                row_count=descriptor.row_count,
                shard_id=shard_id,
                first_key=str(shard_rows[0]["chunk_cid"]),
                last_key=str(shard_rows[-1]["chunk_cid"]),
                kind=CHUNK_INDEX_KIND,
                content_cid=descriptor.content_cid,
                start_document_index=int(shard_rows[0]["document_index"]),
                end_document_index=int(shard_rows[-1]["document_index"]),
                metadata={"jurisdiction_code": shard_code},
            ).to_dict()
            route["jurisdiction_code"] = shard_code
            route_rows.append(route)
            part_by_code[shard_code] += 1
            shard_rows.clear()

        previous_key: tuple[str, str] | None = None
        written = 0
        for document_index, row in enumerate(iter_jsonl(canonical_path)):
            code = validate_jurisdiction(
                str(row.get("jurisdiction_code") or ""),
                name="jurisdiction_code",
            )
            chunk_cid = str(row.get("chunk_cid") or "")
            key = (code, chunk_cid)
            if previous_key is not None and key <= previous_key:
                raise StateLawsChunkPhysicalError(
                    "canonical chunk order is not strictly increasing"
                )
            if shard_rows and (
                code != shard_code or len(shard_rows) >= max_rows_per_shard
            ):
                flush_shard()
            row["document_index"] = document_index
            shard_code = code
            shard_rows.append(row)
            previous_key = key
            written += 1
        flush_shard()
        if written != chunk_count:
            raise StateLawsChunkPhysicalError("chunk sharding lost canonical rows")

        expected_start = 0
        for route in route_rows:
            if int(route["start_document_index"]) != expected_start:
                raise StateLawsChunkPhysicalError(
                    "chunk document-index routes are not dense and contiguous"
                )
            expected_start = int(route["end_document_index"]) + 1
        if expected_start != chunk_count:
            raise StateLawsChunkPhysicalError(
                "chunk document-index routes do not cover every chunk"
            )

        index_target = staging.confine(CHUNK_INDEX_PATH)
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
            last_key=str(chunk_count - 1),
            metadata={
                "index_name": "corpus_chunks",
                "stage": "canonical_chunks",
            },
        )

        staging.commit_tree(CHUNK_DATA_DIR)
        staging.commit_file(CHUNK_INDEX_PATH)

    for descriptor in (*data_descriptors, corpus_index_descriptor):
        try:
            verify_descriptor(root, descriptor)
        except ArtifactIntegrityError as exc:
            raise StateLawsChunkPhysicalError(
                f"committed canonical chunk artifact failed verification: "
                f"{descriptor.relative_path}"
            ) from exc

    return StateLawsChunkPhysicalLayout(
        output_dir=str(root),
        parent_corpus_digest=parent_digest,
        data_descriptors=tuple(data_descriptors),
        corpus_index_descriptor=corpus_index_descriptor,
        route_rows=tuple(route_rows),
        parent_document_count=parent_count,
        chunk_count=chunk_count,
        config=config_payload,
        sort_receipts=sort_receipts,
        model_token_validation_passed=model_token_counter is not None,
    )


# Discoverable streaming spelling for orchestration code.
write_state_laws_chunk_physical_layout_from_corpus = (
    write_state_laws_chunk_physical_layout
)


__all__ = [
    "AUTHORIZES_HUB_UPLOAD",
    "AUTHORIZES_PUBLICATION",
    "CANONICAL_DOCUMENT_ORDER",
    "CHUNK_DATA_DIR",
    "CHUNK_INDEX_KIND",
    "CHUNK_INDEX_PATH",
    "CHUNK_ROW_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "STREAMING_CHUNK_STORE_PRODUCTION_READY",
    "ModelTokenCounter",
    "StateLawsChunkPhysicalError",
    "StateLawsChunkPhysicalLayout",
    "write_state_laws_chunk_physical_layout",
    "write_state_laws_chunk_physical_layout_from_corpus",
]
