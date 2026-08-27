"""Streaming, domain-neutral multi-field BM25 physical layout builder.

The older :mod:`hf_graphrag.bm25` builder is intentionally convenient for
small, already-materialised corpora.  This module is the production physical
path: it consumes its source once, uses the shared external sorter for every
unbounded ordering operation, and retains only one document shard, one
posting cell, and one bounded route table in memory.

Domain adapters own source projection and schemas.  This module owns the
BM25 mechanics and the query-compatible physical columns.  It performs local
staging only; it never writes a release manifest or performs network I/O.
"""

from __future__ import annotations

import json
import math
import tempfile
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from .artifacts import (
    ArtifactWriterConfig,
    atomic_staging,
    atomic_write_canonical_json,
    confine_path,
    describe_file,
    resolve_release_root,
    verify_descriptor,
    write_zstd_parquet,
)
from .external_sort import (
    DEFAULT_MAX_RECORDS_IN_MEMORY,
    ExternalSortReceipt,
    external_sort_to_file,
    file_sha256,
    iter_jsonl,
    write_jsonl_atomic,
)
from .external_sort import (
    SCHEMA_VERSION as EXTERNAL_SORT_SCHEMA_VERSION,
)
from .schema import (
    COMPACT_INDEX_SCHEMA_VERSION,
    MAX_POINTERS_PER_ROW,
    MAX_ROUTING_ROWS_PER_INDEX,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    ArtifactDescriptor,
    ArtifactFamily,
    CompactIndexRow,
    canonical_json_dumps,
    digest_mapping,
    normalize_sha256,
)

SCHEMA_VERSION: Final = "hf-graphrag-streaming-multifield-bm25/v1"
CHECKPOINT_SCHEMA_VERSION: Final = (
    "hf-graphrag-streaming-multifield-bm25-checkpoint/v1"
)
CHECKPOINT_FILENAME: Final = "streaming_bm25_checkpoint.json"
AUTHORIZES_PUBLICATION: Final = False
AUTHORIZES_HUB_UPLOAD: Final = False

PathLike = str | Path
SourceKey = Callable[[Mapping[str, Any]], Any]
DocumentProjector = Callable[[Mapping[str, Any], int], "StreamingMultiFieldDocument"]
DocumentSchemaFactory = Callable[[Any, "StreamingMultiFieldBM25Profile"], Any]


class StreamingBM25Error(ValueError):
    """Raised when a streaming BM25 layout cannot be built losslessly."""


@dataclass(frozen=True, slots=True)
class StreamingMultiFieldDocument:
    """A domain-projected document with already-tokenized named fields."""

    entry_cid: str
    chunk_cid: str
    field_terms: Mapping[str, Sequence[str]]
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        entry_cid = str(self.entry_cid or "").strip()
        chunk_cid = str(self.chunk_cid or "").strip()
        if not entry_cid or not chunk_cid:
            raise StreamingBM25Error("entry_cid and chunk_cid are required")
        fields: dict[str, tuple[str, ...]] = {}
        for name, values in self.field_terms.items():
            field_name = str(name or "").strip()
            if not field_name:
                raise StreamingBM25Error("field names must be non-empty")
            terms = tuple(str(value or "").strip() for value in values)
            if any(not term for term in terms):
                raise StreamingBM25Error("token streams must not contain empty terms")
            fields[field_name] = terms
        object.__setattr__(self, "entry_cid", entry_cid)
        object.__setattr__(self, "chunk_cid", chunk_cid)
        object.__setattr__(self, "field_terms", MappingProxyType(fields))
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


@dataclass(frozen=True, slots=True)
class StreamingMultiFieldBM25Profile:
    """Domain-neutral field, scoring, schema, and physical path contract."""

    field_names: tuple[str, ...]
    field_weights: Mapping[str, float]
    query_title_fields: tuple[str, ...]
    query_body_fields: tuple[str, ...]
    tokenizer_id: str
    document_schema_version: str
    posting_schema_version: str
    config_digest: str = ""
    physical_schema_version: str = SCHEMA_VERSION
    exact_frequency_prefix: str = "field_"
    emit_exact_field_lengths: bool = False
    document_data_dir: str = "data/bm25/documents"
    posting_data_dir: str = "data/bm25/postings"
    document_index_path: str = "indexes/bm25_document_chunks.parquet"
    keyword_index_path: str = "indexes/bm25_keyword_shards.parquet"
    k1: float = 1.2
    b: float = 0.75

    def __post_init__(self) -> None:
        names = tuple(str(name or "").strip() for name in self.field_names)
        if (
            not names
            or any(not name for name in names)
            or len(set(names)) != len(names)
        ):
            raise StreamingBM25Error("field_names must be non-empty and unique")
        weights = {
            str(name): float(value) for name, value in self.field_weights.items()
        }
        if set(weights) != set(names):
            raise StreamingBM25Error("field_weights must exactly cover field_names")
        if any(not math.isfinite(value) or value <= 0.0 for value in weights.values()):
            raise StreamingBM25Error("field weights must be positive and finite")
        title = tuple(self.query_title_fields)
        body = tuple(self.query_body_fields)
        if not title or not body or set(title) & set(body):
            raise StreamingBM25Error(
                "query title/body fields must be non-empty and disjoint"
            )
        if set(title) | set(body) != set(names):
            raise StreamingBM25Error(
                "query title/body fields must partition field_names"
            )
        if not self.tokenizer_id.strip():
            raise StreamingBM25Error("tokenizer_id is required")
        if not isinstance(self.emit_exact_field_lengths, bool):
            raise StreamingBM25Error("emit_exact_field_lengths must be a boolean")
        digest = self.config_digest.removeprefix("sha256:")
        if self.config_digest and (
            len(digest) != 64
            or any(character not in "0123456789abcdefABCDEF" for character in digest)
        ):
            raise StreamingBM25Error("config_digest must be a SHA-256 digest")
        if not math.isfinite(float(self.k1)) or float(self.k1) <= 0.0:
            raise StreamingBM25Error("k1 must be positive and finite")
        if not math.isfinite(float(self.b)) or not 0.0 <= float(self.b) <= 1.0:
            raise StreamingBM25Error("b must be finite and between zero and one")
        object.__setattr__(self, "field_names", names)
        object.__setattr__(self, "field_weights", MappingProxyType(weights))


@dataclass(frozen=True, slots=True)
class StreamingMultiFieldBM25Config:
    """Explicit resident-record and physical-shard limits."""

    max_records_in_memory: int = DEFAULT_MAX_RECORDS_IN_MEMORY
    max_rows_per_shard: int = MAX_ROWS_PER_PHYSICAL_SHARD
    postings_per_row: int = MAX_POINTERS_PER_ROW
    max_routing_rows: int = MAX_ROUTING_ROWS_PER_INDEX
    max_documents: int | None = None

    def __post_init__(self) -> None:
        for name in (
            "max_records_in_memory",
            "max_rows_per_shard",
            "postings_per_row",
            "max_routing_rows",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise StreamingBM25Error(f"{name} must be a positive integer")
        if self.max_records_in_memory < 2:
            raise StreamingBM25Error(
                "max_records_in_memory must be >= 2 for bounded k-way merge"
            )
        if self.max_rows_per_shard > MAX_ROWS_PER_PHYSICAL_SHARD:
            raise StreamingBM25Error("max_rows_per_shard exceeds the shared bound")
        if self.postings_per_row > MAX_POINTERS_PER_ROW:
            raise StreamingBM25Error("postings_per_row exceeds the shared bound")
        if self.max_routing_rows > MAX_ROUTING_ROWS_PER_INDEX:
            raise StreamingBM25Error("max_routing_rows exceeds the shared bound")
        if self.max_documents is not None and (
            isinstance(self.max_documents, bool)
            or not isinstance(self.max_documents, int)
            or self.max_documents < 1
        ):
            raise StreamingBM25Error("max_documents must be positive when supplied")


@dataclass(frozen=True, slots=True)
class StreamingMultiFieldBM25Layout:
    """Committed local descriptors and bounded build statistics."""

    output_dir: str
    profile: StreamingMultiFieldBM25Profile
    config: StreamingMultiFieldBM25Config
    document_descriptors: tuple[ArtifactDescriptor, ...]
    posting_descriptors: tuple[ArtifactDescriptor, ...]
    document_index_descriptor: ArtifactDescriptor
    keyword_index_descriptor: ArtifactDescriptor
    document_route_rows: tuple[Mapping[str, Any], ...]
    keyword_route_rows: tuple[Mapping[str, Any], ...]
    document_count: int
    term_count: int
    posting_count: int
    posting_row_count: int
    token_instance_count: int
    average_document_length: float
    average_field_lengths: Mapping[str, float]
    sort_receipts: Mapping[str, Mapping[str, Any]]
    source_root_cid: str
    index_root_cid: str
    vocabulary_sha256: str
    document_frequency_sha256: str
    checkpoint_path: str | None = None
    resumed_stages: tuple[str, ...] = ()
    executed_stages: tuple[str, ...] = ()

    @property
    def descriptors(self) -> tuple[ArtifactDescriptor, ...]:
        return (
            *self.document_descriptors,
            *self.posting_descriptors,
            self.document_index_descriptor,
            self.keyword_index_descriptor,
        )

    @property
    def counts(self) -> dict[str, int]:
        return {
            "bm25_document_chunks": len(self.document_descriptors),
            "bm25_documents": self.document_count,
            "bm25_keyword_shards": len(self.posting_descriptors),
            "bm25_posting_rows": self.posting_row_count,
            "bm25_postings": self.posting_count,
            "bm25_terms": self.term_count,
            "bm25_token_instances": self.token_instance_count,
        }


@dataclass(frozen=True, slots=True)
class StreamingBM25VocabularyDigest:
    """Incremental digest/count proof over sorted ``(term, df)`` rows."""

    term_count: int
    term_document_pair_count: int
    vocabulary_sha256: str
    document_frequency_sha256: str


def _receipt(receipt: ExternalSortReceipt) -> dict[str, Any]:
    """Keep deterministic bounded-sort evidence without temporary paths."""

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


def digest_sorted_bm25_term_statistics(
    rows: Iterable[tuple[str, int]],
) -> StreamingBM25VocabularyDigest:
    """Hash sorted vocabulary and ``(term, df)`` arrays without materialising."""

    vocabulary = sha256()
    frequencies = sha256()
    vocabulary.update(b"[")
    frequencies.update(b"[")
    first = True
    previous: str | None = None
    term_count = 0
    term_document_pair_count = 0
    for raw_term, raw_document_frequency in rows:
        term = str(raw_term or "").strip()
        document_frequency = int(raw_document_frequency)
        if not term:
            raise StreamingBM25Error("vocabulary terms must be non-empty")
        if previous is not None and previous >= term:
            raise StreamingBM25Error(
                "vocabulary evidence must be strictly lexicographically sorted"
            )
        if document_frequency < 1:
            raise StreamingBM25Error("document frequencies must be positive")
        if not first:
            vocabulary.update(b",")
            frequencies.update(b",")
        first = False
        vocabulary.update(canonical_json_dumps(term).encode("utf-8"))
        frequencies.update(
            canonical_json_dumps([term, document_frequency]).encode("utf-8")
        )
        previous = term
        term_count += 1
        term_document_pair_count += document_frequency
    vocabulary.update(b"]")
    frequencies.update(b"]")
    return StreamingBM25VocabularyDigest(
        term_count=term_count,
        term_document_pair_count=term_document_pair_count,
        vocabulary_sha256=vocabulary.hexdigest(),
        document_frequency_sha256=frequencies.hexdigest(),
    )


def _posting_schema(pa: Any, profile: StreamingMultiFieldBM25Profile) -> Any:
    ints = pa.list_(pa.int64())
    fields: list[tuple[str, Any, bool]] = [
        ("schema_version", pa.string(), False),
        ("term", pa.string(), False),
        ("document_frequency", pa.int64(), False),
        ("corpus_frequency", pa.int64(), False),
        ("weighted_corpus_frequency", pa.float64(), False),
        ("idf", pa.float64(), False),
        ("posting_chunk_count", pa.int32(), False),
        ("posting_chunk_index", pa.int32(), False),
        ("pointer_count", pa.int32(), False),
        ("document_indices", ints, False),
        ("document_lengths", ints, False),
        ("entry_cids", pa.list_(pa.string()), False),
        ("chunk_cids", pa.list_(pa.string()), False),
        ("title_frequencies", ints, False),
        ("body_frequencies", ints, False),
        ("total_frequencies", ints, False),
        ("weighted_frequencies", pa.list_(pa.float64()), False),
    ]
    fields.extend(
        (f"{profile.exact_frequency_prefix}{name}_frequencies", ints, False)
        for name in profile.field_names
    )
    if profile.emit_exact_field_lengths:
        fields.extend(
            (f"{profile.exact_frequency_prefix}{name}_lengths", ints, False)
            for name in profile.field_names
        )
    return pa.schema(
        fields,
        metadata={
            b"b": repr(float(profile.b)).encode("ascii"),
            b"field_weights": str(dict(profile.field_weights)).encode("utf-8"),
            b"k1": repr(float(profile.k1)).encode("ascii"),
            b"schema_version": profile.posting_schema_version.encode("ascii"),
            b"tokenizer": profile.tokenizer_id.encode("utf-8"),
        },
    )


def _route_row(
    descriptor: ArtifactDescriptor,
    *,
    first_key: str,
    last_key: str,
    shard_id: int,
    kind: str,
    start_document_index: int | None = None,
    end_document_index: int | None = None,
) -> dict[str, Any]:
    return CompactIndexRow(
        relative_path=descriptor.relative_path,
        sha256=descriptor.sha256,
        size_bytes=descriptor.size_bytes,
        row_count=descriptor.row_count,
        shard_id=shard_id,
        first_key=first_key,
        last_key=last_key,
        kind=kind,
        content_cid=descriptor.content_cid,
        start_document_index=start_document_index,
        end_document_index=end_document_index,
    ).to_dict()


def _describe_committed(
    root: Path, descriptor: ArtifactDescriptor
) -> ArtifactDescriptor:
    return describe_file(
        confine_path(root, descriptor.relative_path),
        root=root,
        row_count=descriptor.row_count,
        family=descriptor.family,
        schema_id=descriptor.schema_id,
        first_key=descriptor.first_key,
        last_key=descriptor.last_key,
        shard_id=descriptor.shard_id,
        metadata=dict(descriptor.metadata),
    )


def _document_route_key(document_index: int) -> str:
    return f"{document_index:012d}"


def _identity_sort_key(row: Mapping[str, Any]) -> tuple[str]:
    return (str(row["identity"]),)


def _order_sort_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (*tuple(row["order_key"]), str(row["identity"]))


def _field_posting_sort_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        str(row["term"]),
        int(row["document_index"]),
        str(row["field"]),
        str(row["entry_cid"]),
    )


def _profile_contract(profile: StreamingMultiFieldBM25Profile) -> dict[str, Any]:
    """Return every profile value that can change physical BM25 bytes."""

    return {
        "b": float(profile.b),
        "config_digest": profile.config_digest,
        "document_data_dir": profile.document_data_dir,
        "document_index_path": profile.document_index_path,
        "document_schema_version": profile.document_schema_version,
        "emit_exact_field_lengths": profile.emit_exact_field_lengths,
        "exact_frequency_prefix": profile.exact_frequency_prefix,
        "field_names": list(profile.field_names),
        "field_weights": dict(profile.field_weights),
        "k1": float(profile.k1),
        "keyword_index_path": profile.keyword_index_path,
        "physical_schema_version": profile.physical_schema_version,
        "posting_data_dir": profile.posting_data_dir,
        "posting_schema_version": profile.posting_schema_version,
        "query_body_fields": list(profile.query_body_fields),
        "query_title_fields": list(profile.query_title_fields),
        "tokenizer_id": profile.tokenizer_id,
    }


def _config_contract(config: StreamingMultiFieldBM25Config) -> dict[str, Any]:
    return {
        "max_documents": config.max_documents,
        "max_records_in_memory": config.max_records_in_memory,
        "max_routing_rows": config.max_routing_rows,
        "max_rows_per_shard": config.max_rows_per_shard,
        "postings_per_row": config.postings_per_row,
    }


def _callable_contract(value: Callable[..., Any]) -> str:
    module = str(getattr(value, "__module__", "") or "").strip()
    qualname = str(
        getattr(value, "__qualname__", getattr(value, "__name__", "")) or ""
    ).strip()
    if not module or not qualname:
        raise StreamingBM25Error(
            "resumable BM25 callbacks must expose module and qualified names"
        )
    return f"{module}:{qualname}"


def _build_contract(
    *,
    profile: StreamingMultiFieldBM25Profile,
    config: StreamingMultiFieldBM25Config,
    source_digest: str,
    identity_key: SourceKey,
    order_key: SourceKey,
    project_document: DocumentProjector,
    document_schema_factory: DocumentSchemaFactory,
) -> dict[str, Any]:
    return {
        "callbacks": {
            "document_schema_factory": _callable_contract(document_schema_factory),
            "identity_key": _callable_contract(identity_key),
            "order_key": _callable_contract(order_key),
            "project_document": _callable_contract(project_document),
        },
        "config": _config_contract(config),
        "profile": _profile_contract(profile),
        "schema_version": SCHEMA_VERSION,
        "source_digest": source_digest,
    }


def _checkpoint_payload(
    *,
    build_contract: Mapping[str, Any],
    build_digest: str,
    stages: Mapping[str, Any],
    status: str,
    final: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "build_contract": dict(build_contract),
        "build_digest": build_digest,
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "stages": dict(stages),
        "status": status,
    }
    if final is not None:
        payload["final"] = dict(final)
    return payload


def _load_checkpoint(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise StreamingBM25Error(
            f"BM25 checkpoint must be a regular file: {path}"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StreamingBM25Error(f"invalid BM25 checkpoint: {path}") from exc
    if not isinstance(payload, Mapping):
        raise StreamingBM25Error("BM25 checkpoint must be a JSON object")
    return dict(payload)


def _assert_checkpoint_identity(
    checkpoint: Mapping[str, Any],
    *,
    build_contract: Mapping[str, Any],
    build_digest: str,
) -> None:
    stages = checkpoint.get("stages")
    if (
        checkpoint.get("schema_version") != CHECKPOINT_SCHEMA_VERSION
        or checkpoint.get("build_digest") != build_digest
        or checkpoint.get("status") not in {"building", "complete"}
        or canonical_json_dumps(checkpoint.get("build_contract"))
        != canonical_json_dumps(dict(build_contract))
        or not isinstance(stages, Mapping)
    ):
        raise StreamingBM25Error(
            "BM25 checkpoint does not match the active source/profile/config"
        )


def _verify_jsonl_stage(
    path: Path,
    value: Mapping[str, Any],
    *,
    label: str,
) -> int:
    if path.is_symlink() or not path.is_file():
        raise StreamingBM25Error(f"{label} checkpoint artifact is missing or unsafe")
    expected_digest = str(value.get("sha256") or "")
    try:
        expected_digest = normalize_sha256(expected_digest, name=f"{label}.sha256")
    except Exception as exc:
        raise StreamingBM25Error(f"{label} checkpoint digest is invalid") from exc
    if file_sha256(path) != expected_digest:
        raise StreamingBM25Error(f"{label} checkpoint artifact digest mismatch")
    expected_rows = value.get("row_count")
    if type(expected_rows) is not int or expected_rows < 0:
        raise StreamingBM25Error(f"{label} checkpoint row_count is invalid")
    observed_rows = sum(1 for _ in iter_jsonl(path))
    if observed_rows != expected_rows:
        raise StreamingBM25Error(f"{label} checkpoint row coverage mismatch")
    return observed_rows


def _jsonl_stage_record(result: Any) -> dict[str, Any]:
    return {
        "row_count": int(result.row_count),
        "sha256": str(result.sha256),
        "status": "complete",
    }


def _sort_stage_record(receipt: ExternalSortReceipt) -> dict[str, Any]:
    return {
        "artifact": {
            "row_count": receipt.row_count,
            "sha256": receipt.output_digest,
        },
        "sort_receipt": receipt.to_dict(),
        "status": "complete",
    }


def _sort_receipt_from_stage(
    value: Mapping[str, Any],
    *,
    output_path: Path,
    family: str,
    label: str,
    max_records_in_memory: int,
) -> ExternalSortReceipt:
    artifact = value.get("artifact")
    receipt_value = value.get("sort_receipt")
    if (
        value.get("status") != "complete"
        or not isinstance(artifact, Mapping)
        or not isinstance(receipt_value, Mapping)
    ):
        raise StreamingBM25Error(f"{label} sort checkpoint is malformed")
    _verify_jsonl_stage(output_path, artifact, label=label)
    try:
        receipt = ExternalSortReceipt(
            output_path=str(receipt_value.get("output_path") or ""),
            output_digest=str(receipt_value.get("output_digest") or ""),
            row_count=int(receipt_value.get("row_count", -1)),
            run_count=int(receipt_value.get("run_count", -1)),
            records_consumed=int(receipt_value.get("records_consumed", -1)),
            peak_resident_records=int(
                receipt_value.get("peak_resident_records", -1)
            ),
            max_records_in_memory=int(
                receipt_value.get("max_records_in_memory", -1)
            ),
            interrupted=receipt_value.get("interrupted"),
            status=str(receipt_value.get("status") or ""),
            family=str(receipt_value.get("family") or ""),
            schema_version=str(receipt_value.get("schema_version") or ""),
        )
    except (TypeError, ValueError) as exc:
        raise StreamingBM25Error(f"{label} sort receipt is malformed") from exc
    try:
        recorded_output = Path(receipt.output_path).expanduser().resolve()
    except (OSError, RuntimeError) as exc:
        raise StreamingBM25Error(f"{label} sort output path is invalid") from exc
    if (
        recorded_output != output_path.resolve()
        or receipt.output_digest != artifact.get("sha256")
        or receipt.row_count != artifact.get("row_count")
        or receipt.records_consumed != receipt.row_count
        or receipt.run_count < 1
        or receipt.peak_resident_records < 1
        or receipt.peak_resident_records > receipt.max_records_in_memory
        or receipt.max_records_in_memory != max_records_in_memory
        or receipt.interrupted is not False
        or receipt.status != "complete"
        or receipt.family != family
        or receipt.schema_version != EXTERNAL_SORT_SCHEMA_VERSION
    ):
        raise StreamingBM25Error(f"{label} sort receipt failed verification")
    return receipt


@contextmanager
def _ephemeral_work_dir(root: Path) -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix=".streaming-bm25-work-", dir=root) as value:
        yield Path(value)


def _reject_symlink_tree(path: Path, *, label: str) -> None:
    if path.is_symlink():
        raise StreamingBM25Error(f"{label} must not be a symlink")
    if not path.exists():
        return
    for child in path.rglob("*"):
        if child.is_symlink():
            raise StreamingBM25Error(f"{label} contains a symlink: {child}")


def _verify_completed_stages(
    checkpoint: Mapping[str, Any],
    *,
    checkpoint_path: Path,
    profile: StreamingMultiFieldBM25Profile,
    config: StreamingMultiFieldBM25Config,
) -> dict[str, Any]:
    stages = checkpoint.get("stages")
    required = {
        "documents",
        "pointers",
        "posting_fields",
        "projection",
        "source_identity",
        "source_spool",
        "term_stats",
    }
    if not isinstance(stages, Mapping) or set(stages) != required:
        raise StreamingBM25Error("completed BM25 checkpoint stage coverage drift")
    work = checkpoint_path.parent / "work"
    _reject_symlink_tree(work, label="BM25 checkpoint work tree")
    if not work.is_dir():
        raise StreamingBM25Error("completed BM25 checkpoint work tree is missing")

    source_stage = stages["source_spool"]
    projection_stage = stages["projection"]
    pointer_stage = stages["pointers"]
    stats_stage = stages["term_stats"]
    if not all(
        isinstance(value, Mapping)
        for value in (source_stage, projection_stage, pointer_stage, stats_stage)
    ):
        raise StreamingBM25Error("completed BM25 checkpoint stage is malformed")
    source_count = _verify_jsonl_stage(
        work / "source.jsonl", source_stage, label="source_spool"
    )
    identity_receipt = _sort_receipt_from_stage(
        stages["source_identity"],
        output_path=work / "identity-sorted.jsonl",
        family="documents",
        label="source_identity",
        max_records_in_memory=config.max_records_in_memory,
    )
    document_receipt = _sort_receipt_from_stage(
        stages["documents"],
        output_path=work / "documents-sorted.jsonl",
        family="documents",
        label="documents",
        max_records_in_memory=config.max_records_in_memory,
    )
    posting_receipt = _sort_receipt_from_stage(
        stages["posting_fields"],
        output_path=work / "field-postings-sorted.jsonl",
        family="postings",
        label="posting_fields",
        max_records_in_memory=config.max_records_in_memory,
    )
    projection_count = _verify_jsonl_stage(
        work / "projected-documents.jsonl",
        projection_stage,
        label="projection",
    )
    posting_count = _verify_jsonl_stage(
        work / "pointers.jsonl", pointer_stage, label="pointers"
    )
    term_count = _verify_jsonl_stage(
        work / "term-stats.jsonl", stats_stage, label="term_stats"
    )
    if (
        source_count != identity_receipt.row_count
        or source_count != document_receipt.row_count
        or source_count != projection_count
        or source_count < 1
        or posting_receipt.row_count < 1
        or posting_count < 1
        or term_count < 1
    ):
        raise StreamingBM25Error("completed BM25 stage row coverage drift")
    if config.max_documents is not None and source_count > config.max_documents:
        raise StreamingBM25Error("completed BM25 source exceeds document ceiling")

    token_instance_count = 0
    field_length_sums = {name: 0 for name in profile.field_names}
    field_posting_count = 0
    for expected_index, envelope in enumerate(
        iter_jsonl(work / "projected-documents.jsonl")
    ):
        document = envelope.get("document")
        postings = envelope.get("field_postings")
        if not isinstance(document, Mapping) or not isinstance(postings, list):
            raise StreamingBM25Error("completed BM25 projection spool is malformed")
        if int(document.get("document_index", -1)) != expected_index:
            raise StreamingBM25Error(
                "completed BM25 projection indexes are not dense"
            )
        total = int(document.get("document_length", 0))
        observed_total = 0
        for name in profile.field_names:
            length = int(document.get(f"{name}_length", -1))
            if length < 0:
                raise StreamingBM25Error(
                    "completed BM25 projection field length is invalid"
                )
            field_length_sums[name] += length
            observed_total += length
        if total < 1 or total != observed_total:
            raise StreamingBM25Error(
                "completed BM25 projection lengths do not reconcile"
            )
        token_instance_count += total
        field_posting_count += len(postings)
    try:
        declared_field_sums = {
            str(name): int(value)
            for name, value in dict(projection_stage["field_length_sums"]).items()
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise StreamingBM25Error(
            "completed BM25 projection statistics are malformed"
        ) from exc
    if (
        declared_field_sums != field_length_sums
        or int(projection_stage.get("token_instance_count", -1))
        != token_instance_count
        or int(projection_stage.get("field_posting_count", -1))
        != field_posting_count
        or posting_receipt.row_count != field_posting_count
    ):
        raise StreamingBM25Error("completed BM25 projection statistics drift")

    term_proof = digest_sorted_bm25_term_statistics(
        (str(row["term"]), int(row["document_frequency"]))
        for row in iter_jsonl(work / "term-stats.jsonl")
    )
    if (
        term_proof.term_count != term_count
        or term_proof.term_document_pair_count != posting_count
    ):
        raise StreamingBM25Error("completed BM25 vocabulary proof drift")
    effective_config_digest = profile.config_digest or digest_mapping(
        {
            "b": profile.b,
            "field_names": list(profile.field_names),
            "field_weights": dict(profile.field_weights),
            "k1": profile.k1,
            "tokenizer_id": profile.tokenizer_id,
        }
    )
    source_root_cid = "sha256:" + digest_mapping(
        {
            "document_count": source_count,
            "identity_sort_sha256": identity_receipt.output_digest,
            "schema_version": f"{SCHEMA_VERSION}/source-root/v1",
        }
    )
    index_root_cid = "sha256:" + digest_mapping(
        {
            "config_digest": effective_config_digest,
            "document_count": source_count,
            "document_frequency_sha256": term_proof.document_frequency_sha256,
            "document_order_sha256": document_receipt.output_digest,
            "field_postings_sha256": posting_receipt.output_digest,
            "pointer_rows_sha256": str(pointer_stage["sha256"]),
            "posting_count": posting_count,
            "schema_version": f"{SCHEMA_VERSION}/index-root/v1",
            "source_root_cid": source_root_cid,
            "term_count": term_count,
            "term_stats_sha256": str(stats_stage["sha256"]),
            "token_instance_count": token_instance_count,
            "vocabulary_sha256": term_proof.vocabulary_sha256,
        }
    )
    return {
        "document_count": source_count,
        "document_frequency_sha256": term_proof.document_frequency_sha256,
        "field_length_sums": field_length_sums,
        "index_root_cid": index_root_cid,
        "posting_count": posting_count,
        "receipts": {
            "documents": _receipt(document_receipt),
            "posting_fields": _receipt(posting_receipt),
            "source_identity": _receipt(identity_receipt),
        },
        "source_root_cid": source_root_cid,
        "term_count": term_count,
        "token_instance_count": token_instance_count,
        "vocabulary_sha256": term_proof.vocabulary_sha256,
    }


def _final_checkpoint_record(
    layout: StreamingMultiFieldBM25Layout,
) -> dict[str, Any]:
    return {
        "average_document_length": layout.average_document_length,
        "average_field_lengths": dict(layout.average_field_lengths),
        "document_count": layout.document_count,
        "document_descriptors": [
            item.to_dict() for item in layout.document_descriptors
        ],
        "document_frequency_sha256": layout.document_frequency_sha256,
        "document_index_descriptor": layout.document_index_descriptor.to_dict(),
        "document_route_rows": [dict(item) for item in layout.document_route_rows],
        "index_root_cid": layout.index_root_cid,
        "keyword_index_descriptor": layout.keyword_index_descriptor.to_dict(),
        "keyword_route_rows": [dict(item) for item in layout.keyword_route_rows],
        "posting_count": layout.posting_count,
        "posting_descriptors": [item.to_dict() for item in layout.posting_descriptors],
        "posting_row_count": layout.posting_row_count,
        "sort_receipts": {
            name: dict(value) for name, value in layout.sort_receipts.items()
        },
        "source_root_cid": layout.source_root_cid,
        "term_count": layout.term_count,
        "token_instance_count": layout.token_instance_count,
        "vocabulary_sha256": layout.vocabulary_sha256,
    }


def _restore_completed_layout(
    checkpoint: Mapping[str, Any],
    *,
    root: Path,
    checkpoint_path: Path,
    profile: StreamingMultiFieldBM25Profile,
    config: StreamingMultiFieldBM25Config,
) -> StreamingMultiFieldBM25Layout:
    """Reverify and restore a completed layout without touching its source."""

    final = checkpoint.get("final")
    if checkpoint.get("status") != "complete" or not isinstance(final, Mapping):
        raise StreamingBM25Error("completed BM25 checkpoint has no final receipt")
    stage_evidence = _verify_completed_stages(
        checkpoint,
        checkpoint_path=checkpoint_path,
        profile=profile,
        config=config,
    )
    try:
        documents = tuple(
            ArtifactDescriptor.from_mapping(value)
            for value in final.get("document_descriptors", [])
        )
        postings = tuple(
            ArtifactDescriptor.from_mapping(value)
            for value in final.get("posting_descriptors", [])
        )
        document_index = ArtifactDescriptor.from_mapping(
            final["document_index_descriptor"]
        )
        keyword_index = ArtifactDescriptor.from_mapping(
            final["keyword_index_descriptor"]
        )
    except Exception as exc:
        raise StreamingBM25Error(
            "completed BM25 checkpoint descriptors are malformed"
        ) from exc
    if not documents or not postings:
        raise StreamingBM25Error("completed BM25 checkpoint has empty data families")
    for shard_id, descriptor in enumerate(documents):
        if (
            descriptor.relative_path
            != f"{profile.document_data_dir}/part-{shard_id:06d}.parquet"
            or descriptor.family is not ArtifactFamily.BM25_DOCUMENTS
            or descriptor.schema_id != profile.document_schema_version
            or descriptor.shard_id != shard_id
            or descriptor.row_count > config.max_rows_per_shard
        ):
            raise StreamingBM25Error("completed BM25 document descriptor drift")
        try:
            verify_descriptor(root, descriptor)
        except Exception as exc:
            raise StreamingBM25Error(
                f"completed BM25 document failed verification: "
                f"{descriptor.relative_path}"
            ) from exc
    for shard_id, descriptor in enumerate(postings):
        if (
            descriptor.relative_path
            != f"{profile.posting_data_dir}/part-{shard_id:06d}.parquet"
            or descriptor.family is not ArtifactFamily.BM25_POSTINGS
            or descriptor.schema_id != profile.posting_schema_version
            or descriptor.shard_id != shard_id
            or descriptor.row_count > config.max_rows_per_shard
        ):
            raise StreamingBM25Error("completed BM25 posting descriptor drift")
        try:
            verify_descriptor(root, descriptor)
        except Exception as exc:
            raise StreamingBM25Error(
                f"completed BM25 posting failed verification: "
                f"{descriptor.relative_path}"
            ) from exc
    for descriptor, expected_path in (
        (document_index, profile.document_index_path),
        (keyword_index, profile.keyword_index_path),
    ):
        if (
            descriptor.relative_path != expected_path
            or descriptor.family is not ArtifactFamily.ROUTING_INDEX
            or descriptor.schema_id != COMPACT_INDEX_SCHEMA_VERSION
            or descriptor.row_count > config.max_routing_rows
        ):
            raise StreamingBM25Error("completed BM25 routing descriptor drift")
        try:
            verify_descriptor(root, descriptor)
        except Exception as exc:
            raise StreamingBM25Error(
                f"completed BM25 route failed verification: {expected_path}"
            ) from exc

    document_routes = tuple(
        dict(value) for value in final.get("document_route_rows", [])
    )
    keyword_routes = tuple(dict(value) for value in final.get("keyword_route_rows", []))
    if (
        len(document_routes) != len(documents)
        or len(keyword_routes) != len(postings)
        or len(document_routes) != document_index.row_count
        or len(keyword_routes) != keyword_index.row_count
    ):
        raise StreamingBM25Error("completed BM25 route coverage drift")
    try:
        import pyarrow.parquet as pq

        physical_document_routes = tuple(
            pq.read_table(confine_path(root, profile.document_index_path)).to_pylist()
        )
        physical_keyword_routes = tuple(
            pq.read_table(confine_path(root, profile.keyword_index_path)).to_pylist()
        )
    except Exception as exc:
        raise StreamingBM25Error("completed BM25 routes are unreadable") from exc
    if [canonical_json_dumps(value) for value in physical_document_routes] != [
        canonical_json_dumps(value) for value in document_routes
    ] or [canonical_json_dumps(value) for value in physical_keyword_routes] != [
        canonical_json_dumps(value) for value in keyword_routes
    ]:
        raise StreamingBM25Error("completed BM25 checkpoint routes differ on disk")
    for route, descriptor in (*zip(document_routes, documents), *zip(keyword_routes, postings)):
        if (
            route.get("relative_path") != descriptor.relative_path
            or route.get("sha256") != descriptor.sha256
            or int(route.get("size_bytes", -1)) != descriptor.size_bytes
            or int(route.get("row_count", -1)) != descriptor.row_count
            or int(route.get("shard_id", -1)) != descriptor.shard_id
        ):
            raise StreamingBM25Error("completed BM25 route target drift")

    try:
        document_count = int(final["document_count"])
        posting_count = int(final["posting_count"])
        posting_row_count = int(final["posting_row_count"])
        term_count = int(final["term_count"])
        token_instance_count = int(final["token_instance_count"])
        average_document_length = float(final["average_document_length"])
        average_field_lengths = {
            str(name): float(value)
            for name, value in dict(final["average_field_lengths"]).items()
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise StreamingBM25Error("completed BM25 counts are malformed") from exc
    if (
        document_count != sum(item.row_count for item in documents)
        or document_count != stage_evidence["document_count"]
        or posting_row_count != sum(item.row_count for item in postings)
        or posting_count
        != sum(int(route.get("posting_count", -1)) for route in keyword_routes)
        or posting_count != stage_evidence["posting_count"]
        or term_count != sum(int(route.get("term_count", -1)) for route in keyword_routes)
        or term_count != stage_evidence["term_count"]
        or token_instance_count
        != sum(
            int(route.get("token_instance_count", -1)) for route in keyword_routes
        )
        or token_instance_count != stage_evidence["token_instance_count"]
        or document_count < 1
        or posting_count < 1
        or term_count < 1
        or set(average_field_lengths) != set(profile.field_names)
        or not math.isfinite(average_document_length)
        or average_document_length <= 0.0
        or any(not math.isfinite(value) or value < 0.0 for value in average_field_lengths.values())
    ):
        raise StreamingBM25Error("completed BM25 count conservation failed")
    if not math.isclose(
        average_document_length,
        float(token_instance_count) / float(document_count),
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise StreamingBM25Error("completed BM25 average length drift")
    for name in profile.field_names:
        expected_average = float(stage_evidence["field_length_sums"][name]) / float(
            document_count
        )
        if not math.isclose(
            average_field_lengths[name],
            expected_average,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise StreamingBM25Error("completed BM25 average field length drift")
    try:
        vocabulary_sha256 = normalize_sha256(
            final["vocabulary_sha256"], name="vocabulary_sha256"
        )
        document_frequency_sha256 = normalize_sha256(
            final["document_frequency_sha256"],
            name="document_frequency_sha256",
        )
        source_root_cid = "sha256:" + normalize_sha256(
            final["source_root_cid"], name="source_root_cid"
        )
        index_root_cid = "sha256:" + normalize_sha256(
            final["index_root_cid"], name="index_root_cid"
        )
    except Exception as exc:
        raise StreamingBM25Error("completed BM25 root digest is invalid") from exc
    if (
        vocabulary_sha256 != stage_evidence["vocabulary_sha256"]
        or document_frequency_sha256
        != stage_evidence["document_frequency_sha256"]
        or source_root_cid != stage_evidence["source_root_cid"]
        or index_root_cid != stage_evidence["index_root_cid"]
    ):
        raise StreamingBM25Error("completed BM25 root/vocabulary proof drift")
    receipts = final.get("sort_receipts")
    if not isinstance(receipts, Mapping) or set(receipts) != {
        "documents",
        "posting_fields",
        "source_identity",
    }:
        raise StreamingBM25Error("completed BM25 sort receipts are incomplete")
    if canonical_json_dumps(receipts) != canonical_json_dumps(
        stage_evidence["receipts"]
    ):
        raise StreamingBM25Error("completed BM25 sort receipt drift")
    return StreamingMultiFieldBM25Layout(
        output_dir=str(root),
        profile=profile,
        config=config,
        document_descriptors=documents,
        posting_descriptors=postings,
        document_index_descriptor=document_index,
        keyword_index_descriptor=keyword_index,
        document_route_rows=document_routes,
        keyword_route_rows=keyword_routes,
        document_count=document_count,
        term_count=term_count,
        posting_count=posting_count,
        posting_row_count=posting_row_count,
        token_instance_count=token_instance_count,
        average_document_length=average_document_length,
        average_field_lengths=MappingProxyType(average_field_lengths),
        sort_receipts=MappingProxyType(
            {
                str(name): MappingProxyType(dict(value))
                for name, value in receipts.items()
                if isinstance(value, Mapping)
            }
        ),
        source_root_cid=source_root_cid,
        index_root_cid=index_root_cid,
        vocabulary_sha256=vocabulary_sha256,
        document_frequency_sha256=document_frequency_sha256,
        checkpoint_path=str(checkpoint_path),
        resumed_stages=tuple(sorted({*checkpoint["stages"], "publication"})),
        executed_stages=(),
    )


def write_streaming_multifield_bm25_layout(
    source: Iterable[Mapping[str, Any]],
    output_dir: PathLike,
    *,
    profile: StreamingMultiFieldBM25Profile,
    config: StreamingMultiFieldBM25Config,
    identity_key: SourceKey,
    order_key: SourceKey,
    project_document: DocumentProjector,
    document_schema_factory: DocumentSchemaFactory,
    checkpoint_dir: PathLike | None = None,
    source_digest: str | None = None,
    resume: bool = False,
) -> StreamingMultiFieldBM25Layout:
    """Build a query-compatible multi-field BM25 layout from a one-shot source.

    ``identity_key`` must return a durable unique identity. ``order_key`` must
    return a JSON-serialisable scalar or tuple/list. ``project_document`` is
    called only after the source has been externally sorted and receives the
    dense output ``document_index``. No input, vocabulary, or posting list is
    materialised in full.

    Supplying ``checkpoint_dir`` enables restart/reuse.  In that mode callers
    must also supply ``source_digest``: the SHA-256 identity of the immutable
    upstream artifact or receipt that owns ``source``.  A checkpoint is bound
    to that digest, the complete profile/configuration, callback identities,
    and this writer schema.  Stable JSONL stages are rehashed and row-counted
    before reuse; completed Parquet artifacts are descriptor-reverified.
    ``resume=True`` never consumes ``source`` when a verified completed source
    spool is available.
    """

    if isinstance(source, (str, bytes, bytearray)):
        raise StreamingBM25Error("source must be an iterable of mappings")
    if not isinstance(profile, StreamingMultiFieldBM25Profile):
        raise StreamingBM25Error("profile must be StreamingMultiFieldBM25Profile")
    if not isinstance(config, StreamingMultiFieldBM25Config):
        raise StreamingBM25Error("config must be StreamingMultiFieldBM25Config")
    if not isinstance(resume, bool):
        raise StreamingBM25Error("resume must be a boolean")
    if checkpoint_dir is None and (resume or source_digest is not None):
        raise StreamingBM25Error(
            "checkpoint_dir is required when source_digest or resume is supplied"
        )
    if checkpoint_dir is not None and source_digest is None:
        raise StreamingBM25Error(
            "source_digest is required for resumable BM25 construction"
        )
    if checkpoint_dir is not None and not profile.config_digest:
        raise StreamingBM25Error(
            "profile.config_digest is required for resumable BM25 construction"
        )

    data_owner = profile.document_data_dir.rsplit("/", 1)[0]
    if profile.posting_data_dir.rsplit("/", 1)[0] != data_owner:
        raise StreamingBM25Error(
            "document and posting data directories must share one atomic owner"
        )

    root = resolve_release_root(output_dir, must_exist=False)
    root.mkdir(parents=True, exist_ok=True)
    for relative_path in (
        profile.document_data_dir.rsplit("/", 1)[0],
        profile.document_index_path,
        profile.keyword_index_path,
    ):
        if confine_path(root, relative_path).is_symlink():
            raise StreamingBM25Error(
                f"refusing to replace symlinked output: {relative_path}"
            )

    checkpoint_root: Path | None = None
    checkpoint_path: Path | None = None
    build_contract: dict[str, Any] | None = None
    build_digest = ""
    stages: dict[str, Any] = {}
    prior_checkpoint: dict[str, Any] = {}
    normalized_source_digest: str | None = None
    if checkpoint_dir is not None:
        try:
            normalized_source_digest = normalize_sha256(
                source_digest, name="source_digest"
            )
        except Exception as exc:
            raise StreamingBM25Error(
                "source_digest must be a SHA-256 digest"
            ) from exc
        unresolved_checkpoint_root = Path(checkpoint_dir).expanduser().absolute()
        cursor = Path(unresolved_checkpoint_root.anchor)
        for component in unresolved_checkpoint_root.parts[1:]:
            cursor /= component
            if cursor.is_symlink():
                raise StreamingBM25Error(
                    f"BM25 checkpoint path contains a symlink: {cursor}"
                )
        unresolved_checkpoint_root.mkdir(parents=True, exist_ok=True)
        checkpoint_root = unresolved_checkpoint_root.resolve()
        owned_data_root = confine_path(root, data_owner)
        if checkpoint_root == owned_data_root or owned_data_root in checkpoint_root.parents:
            raise StreamingBM25Error(
                "BM25 checkpoint directory must be outside the published data tree"
            )
        checkpoint_path = checkpoint_root / CHECKPOINT_FILENAME
        if checkpoint_path.is_symlink():
            raise StreamingBM25Error("BM25 checkpoint file must not be a symlink")
        build_contract = _build_contract(
            profile=profile,
            config=config,
            source_digest=normalized_source_digest,
            identity_key=identity_key,
            order_key=order_key,
            project_document=project_document,
            document_schema_factory=document_schema_factory,
        )
        build_digest = digest_mapping(build_contract)
        if resume and checkpoint_path.exists():
            prior_checkpoint = _load_checkpoint(checkpoint_path)
            _assert_checkpoint_identity(
                prior_checkpoint,
                build_contract=build_contract,
                build_digest=build_digest,
            )
            stages = {
                str(name): dict(value)
                for name, value in dict(prior_checkpoint["stages"]).items()
                if isinstance(value, Mapping)
            }
            if len(stages) != len(prior_checkpoint["stages"]):
                raise StreamingBM25Error("BM25 checkpoint stages are malformed")
            if prior_checkpoint.get("status") == "complete":
                return _restore_completed_layout(
                    prior_checkpoint,
                    root=root,
                    checkpoint_path=checkpoint_path,
                    profile=profile,
                    config=config,
                )

    try:
        import pyarrow as pa
    except ImportError as exc:  # pragma: no cover - optional release extra
        raise StreamingBM25Error("pyarrow is required for streaming BM25") from exc

    shard_config = ArtifactWriterConfig(
        max_rows_per_shard=config.max_rows_per_shard,
        max_pointers_per_row=config.postings_per_row,
        max_routing_rows=config.max_routing_rows,
    )
    route_config = ArtifactWriterConfig(
        max_rows_per_shard=config.max_routing_rows,
        max_pointers_per_row=config.postings_per_row,
        max_routing_rows=config.max_routing_rows,
    )
    document_schema = document_schema_factory(pa, profile)
    posting_schema = _posting_schema(pa, profile)
    resumed_stages: set[str] = set()
    executed_stages: set[str] = set()

    def save_checkpoint(
        *, status: str = "building", final: Mapping[str, Any] | None = None
    ) -> None:
        if checkpoint_path is None:
            return
        assert build_contract is not None
        atomic_write_canonical_json(
            checkpoint_path,
            _checkpoint_payload(
                build_contract=build_contract,
                build_digest=build_digest,
                stages=stages,
                status=status,
                final=final,
            ),
        )

    if checkpoint_path is not None and not prior_checkpoint:
        save_checkpoint()

    work_manager = (
        _ephemeral_work_dir(root)
        if checkpoint_root is None
        else nullcontext(checkpoint_root / "work")
    )
    with work_manager as work:
        work.mkdir(parents=True, exist_ok=True)
        _reject_symlink_tree(work, label="BM25 checkpoint work tree")

        def run_sort_stage(
            name: str,
            records: Iterable[Mapping[str, Any]],
            output_path: Path,
            *,
            work_dir: Path,
            key_fn: Callable[[Mapping[str, Any]], tuple[Any, ...]],
            family: str,
        ) -> ExternalSortReceipt:
            existing = stages.get(name)
            if isinstance(existing, Mapping) and existing.get("status") == "complete":
                receipt = _sort_receipt_from_stage(
                    existing,
                    output_path=output_path,
                    family=family,
                    label=name,
                    max_records_in_memory=config.max_records_in_memory,
                )
                resumed_stages.add(name)
                return receipt
            if existing is not None and (
                not isinstance(existing, Mapping)
                or existing.get("status") != "building"
            ):
                raise StreamingBM25Error(f"{name} checkpoint stage is malformed")
            stage_was_started = bool(existing)
            if not stage_was_started:
                stages[name] = {"status": "building"}
                save_checkpoint()
            receipt = external_sort_to_file(
                records,
                output_path,
                work_dir=work_dir,
                key_fn=key_fn,
                family=family,
                max_records_in_memory=config.max_records_in_memory,
                resume=bool(checkpoint_root is not None and resume and stage_was_started),
            )
            if receipt.interrupted or receipt.status != "complete":
                raise StreamingBM25Error(f"{name} sort interrupted before completion")
            stages[name] = _sort_stage_record(receipt)
            save_checkpoint()
            if stage_was_started:
                resumed_stages.add(name)
            else:
                executed_stages.add(name)
            return _sort_receipt_from_stage(
                stages[name],
                output_path=output_path,
                family=family,
                label=name,
                max_records_in_memory=config.max_records_in_memory,
            )

        source_path = work / "source.jsonl"

        def prepared_source() -> Iterable[Mapping[str, Any]]:
            for position, row in enumerate(source):
                if not isinstance(row, Mapping):
                    raise StreamingBM25Error(f"source row {position} must be a mapping")
                identity = str(identity_key(row) or "").strip()
                if not identity:
                    raise StreamingBM25Error(f"source row {position} has no identity")
                primary = order_key(row)
                if isinstance(primary, tuple):
                    primary = list(primary)
                elif not isinstance(primary, list):
                    primary = [primary]
                yield {
                    "identity": identity,
                    "order_key": primary,
                    "source": dict(row),
                }

        source_stage = stages.get("source_spool")
        if source_stage is not None:
            if not isinstance(source_stage, Mapping) or source_stage.get("status") != "complete":
                raise StreamingBM25Error("source_spool checkpoint stage is malformed")
            _verify_jsonl_stage(source_path, source_stage, label="source_spool")
            resumed_stages.add("source_spool")
        else:
            source_write = write_jsonl_atomic(source_path, prepared_source())
            stages["source_spool"] = _jsonl_stage_record(source_write)
            save_checkpoint()
            executed_stages.add("source_spool")

        identity_path = work / "identity-sorted.jsonl"
        identity_receipt = run_sort_stage(
            "source_identity",
            iter_jsonl(source_path),
            identity_path,
            work_dir=work / "identity-sort",
            key_fn=_identity_sort_key,
            family="documents",
        )
        if identity_receipt.row_count == 0:
            raise StreamingBM25Error("source produced no BM25 documents")
        if identity_receipt.row_count != int(stages["source_spool"]["row_count"]):
            raise StreamingBM25Error("source identity sort changed row coverage")
        if (
            config.max_documents is not None
            and identity_receipt.row_count > config.max_documents
        ):
            raise StreamingBM25Error(
                f"document count {identity_receipt.row_count} exceeds configured ceiling "
                f"{config.max_documents}"
            )

        def unique_source() -> Iterable[Mapping[str, Any]]:
            previous: str | None = None
            for envelope in iter_jsonl(identity_path):
                identity = str(envelope["identity"])
                if identity == previous:
                    raise StreamingBM25Error(f"duplicate document identity: {identity}")
                previous = identity
                yield envelope

        ordered_path = work / "documents-sorted.jsonl"
        document_receipt = run_sort_stage(
            "documents",
            unique_source(),
            ordered_path,
            work_dir=work / "document-sort",
            key_fn=_order_sort_key,
            family="documents",
        )
        if document_receipt.row_count != identity_receipt.row_count:
            raise StreamingBM25Error("document ordering changed source coverage")

        projection_path = work / "projected-documents.jsonl"
        projection_stage = stages.get("projection")
        if projection_stage is not None:
            if (
                not isinstance(projection_stage, Mapping)
                or projection_stage.get("status") != "complete"
            ):
                raise StreamingBM25Error("projection checkpoint stage is malformed")
            _verify_jsonl_stage(projection_path, projection_stage, label="projection")
            resumed_stages.add("projection")
        else:
            projection_token_count = 0
            projection_field_sums = {name: 0 for name in profile.field_names}
            projection_posting_count = 0

            def projected_records() -> Iterable[Mapping[str, Any]]:
                nonlocal projection_posting_count, projection_token_count
                for document_index, envelope in enumerate(iter_jsonl(ordered_path)):
                    source_row = envelope.get("source")
                    if not isinstance(source_row, Mapping):
                        raise StreamingBM25Error("sorted source envelope lost its row")
                    document = project_document(source_row, document_index)
                    if document.entry_cid != str(envelope["identity"]):
                        raise StreamingBM25Error(
                            "projection changed the durable source identity"
                        )
                    if set(document.field_terms) != set(profile.field_names):
                        raise StreamingBM25Error(
                            "projected fields do not exactly match the profile"
                        )
                    lengths = {
                        name: len(document.field_terms[name])
                        for name in profile.field_names
                    }
                    total_length = sum(lengths.values())
                    if total_length < 1:
                        raise StreamingBM25Error(
                            f"document has no searchable tokens: {document.entry_cid}"
                        )
                    row = dict(document.payload)
                    reserved = {
                        "schema_version",
                        "document_index",
                        "route_key",
                        "entry_cid",
                        "chunk_cid",
                        "document_length",
                        *(f"{name}_length" for name in profile.field_names),
                    }
                    if reserved & set(row):
                        raise StreamingBM25Error(
                            "document payload overrides a computed physical column"
                        )
                    row.update(
                        {
                            "schema_version": profile.document_schema_version,
                            "document_index": document_index,
                            "route_key": _document_route_key(document_index),
                            "entry_cid": document.entry_cid,
                            "chunk_cid": document.chunk_cid,
                            "document_length": total_length,
                        }
                    )
                    postings: list[dict[str, Any]] = []
                    for name, length in lengths.items():
                        row[f"{name}_length"] = length
                        projection_field_sums[name] += length
                    projection_token_count += total_length
                    for name in profile.field_names:
                        for term, tf in sorted(
                            Counter(document.field_terms[name]).items()
                        ):
                            posting = {
                                "chunk_cid": document.chunk_cid,
                                "document_index": document_index,
                                "document_length": total_length,
                                "entry_cid": document.entry_cid,
                                "field": name,
                                "term": term,
                                "tf": int(tf),
                            }
                            if profile.emit_exact_field_lengths:
                                posting["field_length"] = lengths[name]
                            postings.append(posting)
                    projection_posting_count += len(postings)
                    yield {"document": row, "field_postings": postings}

            projection_write = write_jsonl_atomic(
                projection_path, projected_records()
            )
            if projection_write.row_count != document_receipt.row_count:
                raise StreamingBM25Error("document projection changed row coverage")
            stages["projection"] = {
                **_jsonl_stage_record(projection_write),
                "field_length_sums": projection_field_sums,
                "field_posting_count": projection_posting_count,
                "token_instance_count": projection_token_count,
            }
            save_checkpoint()
            executed_stages.add("projection")

        def projected_field_postings() -> Iterable[Mapping[str, Any]]:
            for position, envelope in enumerate(iter_jsonl(projection_path)):
                postings = envelope.get("field_postings")
                if not isinstance(postings, list):
                    raise StreamingBM25Error(
                        f"projection row {position} lost field postings"
                    )
                for posting in postings:
                    if not isinstance(posting, Mapping):
                        raise StreamingBM25Error(
                            f"projection row {position} has malformed posting"
                        )
                    yield posting

        field_path = work / "field-postings-sorted.jsonl"
        posting_receipt = run_sort_stage(
            "posting_fields",
            projected_field_postings(),
            field_path,
            work_dir=work / "posting-sort",
            key_fn=_field_posting_sort_key,
            family="postings",
        )
        if posting_receipt.row_count == 0:
            raise StreamingBM25Error("BM25 projection produced no postings")
        if posting_receipt.row_count != int(
            stages["projection"].get("field_posting_count", -1)
        ):
            raise StreamingBM25Error("field posting projection changed coverage")

        pointer_path = work / "pointers.jsonl"

        def pointer_records() -> Iterable[Mapping[str, Any]]:
            current_key: tuple[str, int] | None = None
            current: dict[str, Any] | None = None
            field_tfs: dict[str, int] = {}
            field_lengths: dict[str, int] = {}
            for item in iter_jsonl(field_path):
                key = (str(item["term"]), int(item["document_index"]))
                if current_key is not None and key != current_key:
                    assert current is not None
                    pointer = {
                        **current,
                        "field_tfs": dict(field_tfs),
                        "tf": sum(field_tfs.values()),
                    }
                    if profile.emit_exact_field_lengths:
                        pointer["field_lengths"] = dict(field_lengths)
                    yield pointer
                    field_tfs.clear()
                    field_lengths.clear()
                if key != current_key:
                    current_key = key
                    current = {
                        "chunk_cid": str(item["chunk_cid"]),
                        "document_index": int(item["document_index"]),
                        "document_length": int(item["document_length"]),
                        "entry_cid": str(item["entry_cid"]),
                        "term": str(item["term"]),
                    }
                name = str(item["field"])
                if name in field_tfs:
                    raise StreamingBM25Error("duplicate field-frequency record")
                field_tfs[name] = int(item["tf"])
                if profile.emit_exact_field_lengths:
                    length = int(item.get("field_length", -1))
                    if length < field_tfs[name]:
                        raise StreamingBM25Error(
                            "field length is absent or smaller than term frequency"
                        )
                    field_lengths[name] = length
            if current is not None:
                pointer = {
                    **current,
                    "field_tfs": dict(field_tfs),
                    "tf": sum(field_tfs.values()),
                }
                if profile.emit_exact_field_lengths:
                    pointer["field_lengths"] = dict(field_lengths)
                yield pointer

        pointer_stage = stages.get("pointers")
        if pointer_stage is not None:
            if (
                not isinstance(pointer_stage, Mapping)
                or pointer_stage.get("status") != "complete"
            ):
                raise StreamingBM25Error("pointers checkpoint stage is malformed")
            posting_count = _verify_jsonl_stage(
                pointer_path, pointer_stage, label="pointers"
            )
            resumed_stages.add("pointers")
        else:
            pointer_write = write_jsonl_atomic(pointer_path, pointer_records())
            posting_count = pointer_write.row_count
            stages["pointers"] = _jsonl_stage_record(pointer_write)
            save_checkpoint()
            executed_stages.add("pointers")
        if posting_count < 1:
            raise StreamingBM25Error("BM25 pointer aggregation produced no rows")

        stats_path = work / "term-stats.jsonl"

        def term_stats_records() -> Iterable[Mapping[str, Any]]:
            current_term: str | None = None
            df = corpus_frequency = 0
            weighted = 0.0
            for pointer in iter_jsonl(pointer_path):
                term = str(pointer["term"])
                if current_term is not None and term != current_term:
                    yield {
                        "term": current_term,
                        "document_frequency": df,
                        "corpus_frequency": corpus_frequency,
                        "weighted_corpus_frequency": weighted,
                        "posting_chunk_count": math.ceil(df / config.postings_per_row),
                    }
                    df = corpus_frequency = 0
                    weighted = 0.0
                current_term = term
                field_tfs = dict(pointer["field_tfs"])
                df += 1
                corpus_frequency += int(pointer["tf"])
                weighted += sum(
                    int(field_tfs.get(name, 0)) * profile.field_weights[name]
                    for name in profile.field_names
                )
            if current_term is not None:
                yield {
                    "term": current_term,
                    "document_frequency": df,
                    "corpus_frequency": corpus_frequency,
                    "weighted_corpus_frequency": weighted,
                    "posting_chunk_count": math.ceil(df / config.postings_per_row),
                }

        stats_stage = stages.get("term_stats")
        if stats_stage is not None:
            if (
                not isinstance(stats_stage, Mapping)
                or stats_stage.get("status") != "complete"
            ):
                raise StreamingBM25Error("term_stats checkpoint stage is malformed")
            term_count = _verify_jsonl_stage(
                stats_path, stats_stage, label="term_stats"
            )
            resumed_stages.add("term_stats")
        else:
            stats_write = write_jsonl_atomic(stats_path, term_stats_records())
            term_count = stats_write.row_count
            stages["term_stats"] = _jsonl_stage_record(stats_write)
            save_checkpoint()
            executed_stages.add("term_stats")
        if term_count < 1:
            raise StreamingBM25Error("term statistics produced no vocabulary")
        term_proof = digest_sorted_bm25_term_statistics(
            (str(row["term"]), int(row["document_frequency"]))
            for row in iter_jsonl(stats_path)
        )
        if (
            term_proof.term_count != term_count
            or term_proof.term_document_pair_count != posting_count
        ):
            raise StreamingBM25Error(
                "streaming vocabulary proof does not reconcile with postings"
            )
        vocabulary_sha256 = term_proof.vocabulary_sha256
        document_frequency_sha256 = term_proof.document_frequency_sha256

        document_descriptors: list[ArtifactDescriptor] = []
        posting_descriptors: list[ArtifactDescriptor] = []
        document_routes: list[dict[str, Any]] = []
        posting_routes: list[dict[str, Any]] = []
        document_count = 0
        token_instance_count = 0
        field_length_sums = {name: 0 for name in profile.field_names}
        posting_row_count = 0

        with atomic_staging(root, prefix=".streaming-bm25-") as session:
            document_rows: list[dict[str, Any]] = []

            def flush_documents() -> None:
                if not document_rows:
                    return
                shard_id = len(document_descriptors)
                if shard_id >= config.max_routing_rows:
                    raise StreamingBM25Error(
                        "document shard count exceeds routing bound"
                    )
                relative = (
                    f"{profile.document_data_dir}/part-{shard_id:06d}.parquet"
                )
                staged = session.confine(relative)
                write_zstd_parquet(
                    staged,
                    tuple(document_rows),
                    config=shard_config,
                    schema=document_schema,
                )
                first = str(document_rows[0]["route_key"])
                last = str(document_rows[-1]["route_key"])
                descriptor = describe_file(
                    staged,
                    root=session.staging_dir,
                    row_count=len(document_rows),
                    family=ArtifactFamily.BM25_DOCUMENTS,
                    schema_id=profile.document_schema_version,
                    first_key=first,
                    last_key=last,
                    shard_id=shard_id,
                    metadata={"direct_columns": True, "streaming": True},
                )
                document_descriptors.append(descriptor)
                route = _route_row(
                    descriptor,
                    first_key=first,
                    last_key=last,
                    shard_id=shard_id,
                    kind="bm25_documents",
                    start_document_index=int(document_rows[0]["document_index"]),
                    end_document_index=int(document_rows[-1]["document_index"]),
                )
                route["document_count"] = len(document_rows)
                document_routes.append(route)
                document_rows.clear()

            for envelope in iter_jsonl(projection_path):
                row = envelope.get("document")
                if not isinstance(row, Mapping):
                    raise StreamingBM25Error("projection spool lost a document row")
                document_row = dict(row)
                if int(document_row.get("document_index", -1)) != document_count:
                    raise StreamingBM25Error(
                        "projection spool document indexes are not dense"
                    )
                total_length = int(document_row.get("document_length", 0))
                if total_length < 1:
                    raise StreamingBM25Error(
                        "projection spool contains an empty document"
                    )
                computed_total = 0
                for name in profile.field_names:
                    length = int(document_row.get(f"{name}_length", -1))
                    if length < 0:
                        raise StreamingBM25Error(
                            "projection spool contains an invalid field length"
                        )
                    field_length_sums[name] += length
                    computed_total += length
                if computed_total != total_length:
                    raise StreamingBM25Error(
                        "projection spool field lengths do not reconcile"
                    )
                document_count += 1
                token_instance_count += total_length
                document_rows.append(document_row)
                if len(document_rows) >= config.max_rows_per_shard:
                    flush_documents()
            flush_documents()
            expected_projection = stages["projection"]
            if (
                document_count != document_receipt.row_count
                or document_count != int(expected_projection["row_count"])
                or token_instance_count
                != int(expected_projection.get("token_instance_count", -1))
                or field_length_sums
                != {
                    str(name): int(value)
                    for name, value in dict(
                        expected_projection.get("field_length_sums", {})
                    ).items()
                }
            ):
                raise StreamingBM25Error(
                    "projection checkpoint statistics failed conservation"
                )

            posting_rows: list[dict[str, Any]] = []

            def flush_postings() -> None:
                nonlocal posting_row_count
                if not posting_rows:
                    return
                shard_id = len(posting_descriptors)
                if shard_id >= config.max_routing_rows:
                    raise StreamingBM25Error(
                        "posting shard count exceeds routing bound"
                    )
                relative = (
                    f"{profile.posting_data_dir}/part-{shard_id:06d}.parquet"
                )
                staged = session.confine(relative)
                write_zstd_parquet(
                    staged,
                    tuple(posting_rows),
                    config=shard_config,
                    schema=posting_schema,
                )
                first = str(posting_rows[0]["term"])
                last = str(posting_rows[-1]["term"])
                pointers = sum(int(row["pointer_count"]) for row in posting_rows)
                terms = len({str(row["term"]) for row in posting_rows})
                instances = sum(
                    sum(int(value) for value in row["total_frequencies"])
                    for row in posting_rows
                )
                descriptor = describe_file(
                    staged,
                    root=session.staging_dir,
                    row_count=len(posting_rows),
                    family=ArtifactFamily.BM25_POSTINGS,
                    schema_id=profile.posting_schema_version,
                    first_key=first,
                    last_key=last,
                    shard_id=shard_id,
                    metadata={
                        "direct_columns": True,
                        "pointer_count": pointers,
                        "streaming": True,
                        "term_count": terms,
                    },
                )
                posting_descriptors.append(descriptor)
                route = _route_row(
                    descriptor,
                    first_key=first,
                    last_key=last,
                    shard_id=shard_id,
                    kind="bm25_postings",
                )
                route.update(
                    {
                        "posting_count": pointers,
                        "term_count": terms,
                        "token_instance_count": instances,
                    }
                )
                posting_routes.append(route)
                posting_row_count += len(posting_rows)
                posting_rows.clear()

            pointer_iterator = iter(iter_jsonl(pointer_path))
            pointer = next(pointer_iterator, None)
            previous_term: str | None = None
            for stats in iter_jsonl(stats_path):
                term = str(stats["term"])
                if previous_term is not None and previous_term >= term:
                    raise StreamingBM25Error("vocabulary is not strictly sorted")
                previous_term = term
                chunks = int(stats["posting_chunk_count"])
                if chunks > config.max_rows_per_shard:
                    raise StreamingBM25Error(
                        f"term {term!r} needs {chunks} rows and cannot fit one routed shard"
                    )
                if (
                    posting_rows
                    and len(posting_rows) + chunks > config.max_rows_per_shard
                ):
                    flush_postings()
                df = int(stats["document_frequency"])
                idf = math.log(1.0 + (document_count - df + 0.5) / (df + 0.5))
                consumed = 0
                for chunk_index in range(chunks):
                    cells: list[Mapping[str, Any]] = []
                    while consumed < df and len(cells) < config.postings_per_row:
                        if pointer is None or str(pointer["term"]) != term:
                            raise StreamingBM25Error(
                                f"posting coverage ended early for {term!r}"
                            )
                        cells.append(pointer)
                        consumed += 1
                        pointer = next(pointer_iterator, None)
                    exact = {
                        name: [
                            int(item["field_tfs"].get(name, 0)) for item in cells
                        ]
                        for name in profile.field_names
                    }
                    totals = [int(item["tf"]) for item in cells]
                    row: dict[str, Any] = {
                        "schema_version": profile.posting_schema_version,
                        "term": term,
                        "document_frequency": df,
                        "corpus_frequency": int(stats["corpus_frequency"]),
                        "weighted_corpus_frequency": float(
                            stats["weighted_corpus_frequency"]
                        ),
                        "idf": idf,
                        "posting_chunk_count": chunks,
                        "posting_chunk_index": chunk_index,
                        "pointer_count": len(cells),
                        "document_indices": [
                            int(item["document_index"]) for item in cells
                        ],
                        "document_lengths": [
                            int(item["document_length"]) for item in cells
                        ],
                        "entry_cids": [str(item["entry_cid"]) for item in cells],
                        "chunk_cids": [str(item["chunk_cid"]) for item in cells],
                        "title_frequencies": [
                            sum(
                                exact[name][offset]
                                for name in profile.query_title_fields
                            )
                            for offset in range(len(cells))
                        ],
                        "body_frequencies": [
                            sum(
                                exact[name][offset]
                                for name in profile.query_body_fields
                            )
                            for offset in range(len(cells))
                        ],
                        "total_frequencies": totals,
                        "weighted_frequencies": [
                            sum(
                                exact[name][offset] * profile.field_weights[name]
                                for name in profile.field_names
                            )
                            for offset in range(len(cells))
                        ],
                    }
                    for name in profile.field_names:
                        row[
                            f"{profile.exact_frequency_prefix}{name}_frequencies"
                        ] = exact[name]
                    if profile.emit_exact_field_lengths:
                        for name in profile.field_names:
                            row[
                                f"{profile.exact_frequency_prefix}{name}_lengths"
                            ] = [
                                int(item.get("field_lengths", {}).get(name, 0))
                                for item in cells
                            ]
                    posting_rows.append(row)
                if consumed != df:
                    raise StreamingBM25Error(
                        f"posting coverage mismatch for {term!r}"
                    )
            if pointer is not None:
                raise StreamingBM25Error(
                    "posting rows remain after vocabulary exhaustion"
                )
            flush_postings()

            if (
                sum(int(route["posting_count"]) for route in posting_routes)
                != posting_count
                or sum(int(route["term_count"]) for route in posting_routes)
                != term_count
                or sum(
                    int(route["token_instance_count"]) for route in posting_routes
                )
                != token_instance_count
            ):
                raise StreamingBM25Error(
                    "physical posting shards failed count conservation"
                )

            document_index_path = session.confine(profile.document_index_path)
            write_zstd_parquet(
                document_index_path, tuple(document_routes), config=route_config
            )
            document_index_descriptor = describe_file(
                document_index_path,
                root=session.staging_dir,
                row_count=len(document_routes),
                family=ArtifactFamily.ROUTING_INDEX,
                schema_id=COMPACT_INDEX_SCHEMA_VERSION,
                metadata={
                    "direct_columns": True,
                    "kind": "bm25_documents",
                    "streaming": True,
                },
            )
            keyword_index_path = session.confine(profile.keyword_index_path)
            write_zstd_parquet(
                keyword_index_path, tuple(posting_routes), config=route_config
            )
            keyword_index_descriptor = describe_file(
                keyword_index_path,
                root=session.staging_dir,
                row_count=len(posting_routes),
                family=ArtifactFamily.ROUTING_INDEX,
                schema_id=COMPACT_INDEX_SCHEMA_VERSION,
                metadata={
                    "direct_columns": True,
                    "kind": "bm25_postings",
                    "streaming": True,
                },
            )

            session.commit_tree(data_owner)
            session.commit_file(profile.document_index_path)
            session.commit_file(profile.keyword_index_path)

        committed_documents = tuple(
            _describe_committed(root, item) for item in document_descriptors
        )
        committed_postings = tuple(
            _describe_committed(root, item) for item in posting_descriptors
        )
        committed_document_index = _describe_committed(
            root, document_index_descriptor
        )
        committed_keyword_index = _describe_committed(root, keyword_index_descriptor)
        average_document_length = float(token_instance_count) / float(document_count)
        average_field_lengths = {
            name: float(field_length_sums[name]) / float(document_count)
            for name in profile.field_names
        }
        effective_config_digest = profile.config_digest or digest_mapping(
            {
                "b": profile.b,
                "field_names": list(profile.field_names),
                "field_weights": dict(profile.field_weights),
                "k1": profile.k1,
                "tokenizer_id": profile.tokenizer_id,
            }
        )
        source_root_cid = "sha256:" + digest_mapping(
            {
                "document_count": document_count,
                "identity_sort_sha256": identity_receipt.output_digest,
                "schema_version": f"{SCHEMA_VERSION}/source-root/v1",
            }
        )
        index_root_cid = "sha256:" + digest_mapping(
            {
                "config_digest": effective_config_digest,
                "document_count": document_count,
                "document_frequency_sha256": document_frequency_sha256,
                "document_order_sha256": document_receipt.output_digest,
                "field_postings_sha256": posting_receipt.output_digest,
                "pointer_rows_sha256": str(stages["pointers"]["sha256"]),
                "posting_count": posting_count,
                "schema_version": f"{SCHEMA_VERSION}/index-root/v1",
                "source_root_cid": source_root_cid,
                "term_count": term_count,
                "term_stats_sha256": str(stages["term_stats"]["sha256"]),
                "token_instance_count": token_instance_count,
                "vocabulary_sha256": vocabulary_sha256,
            }
        )
        executed_stages.add("publication")
        layout = StreamingMultiFieldBM25Layout(
            output_dir=str(root),
            profile=profile,
            config=config,
            document_descriptors=committed_documents,
            posting_descriptors=committed_postings,
            document_index_descriptor=committed_document_index,
            keyword_index_descriptor=committed_keyword_index,
            document_route_rows=tuple(dict(row) for row in document_routes),
            keyword_route_rows=tuple(dict(row) for row in posting_routes),
            document_count=document_count,
            term_count=term_count,
            posting_count=posting_count,
            posting_row_count=posting_row_count,
            token_instance_count=token_instance_count,
            average_document_length=average_document_length,
            average_field_lengths=MappingProxyType(average_field_lengths),
            sort_receipts=MappingProxyType(
                {
                    "documents": MappingProxyType(_receipt(document_receipt)),
                    "posting_fields": MappingProxyType(_receipt(posting_receipt)),
                    "source_identity": MappingProxyType(_receipt(identity_receipt)),
                }
            ),
            source_root_cid=source_root_cid,
            index_root_cid=index_root_cid,
            vocabulary_sha256=vocabulary_sha256,
            document_frequency_sha256=document_frequency_sha256,
            checkpoint_path=(str(checkpoint_path) if checkpoint_path else None),
            resumed_stages=tuple(sorted(resumed_stages)),
            executed_stages=tuple(sorted(executed_stages)),
        )
        if checkpoint_path is not None:
            save_checkpoint(status="complete", final=_final_checkpoint_record(layout))
        return layout


__all__ = [
    "AUTHORIZES_HUB_UPLOAD",
    "AUTHORIZES_PUBLICATION",
    "CHECKPOINT_FILENAME",
    "CHECKPOINT_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "StreamingBM25Error",
    "StreamingBM25VocabularyDigest",
    "StreamingMultiFieldBM25Config",
    "StreamingMultiFieldBM25Layout",
    "StreamingMultiFieldBM25Profile",
    "StreamingMultiFieldDocument",
    "digest_sorted_bm25_term_statistics",
    "write_streaming_multifield_bm25_layout",
]
