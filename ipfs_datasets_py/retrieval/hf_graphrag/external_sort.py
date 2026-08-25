"""Domain-neutral external sort for corpus-scale HF GraphRAG builders (OUL-026).

Spill sorted runs under a memory bound, k-way merge them, and resume
deterministically without loading the full corpus, postings, or embeddings
into RAM.  Builders then stream the merged output as bounded partitions
(at most 4,096 records — the physical shard/row bound, never a token
ceiling).

This module owns no legal ontology.  Domain adapters (US Code, patent,
CVE, SkillCenter, Open US Law) supply records and optional key functions.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
import heapq
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Final, Union

from .schema import (
    MAX_ROWS_PER_PHYSICAL_SHARD,
    PhysicalBoundError,
    canonical_json_bytes,
    canonical_json_dumps,
    content_sha256,
    digest_mapping,
)

# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "hf-graphrag-external-sort/v1"
CHECKPOINT_SCHEMA_VERSION: Final = "hf-graphrag-external-sort-checkpoint/v1"
TASK_ID: Final = "OUL-026"
CHECKPOINT_FILENAME: Final = "sort_checkpoint.json"
DEFAULT_MAX_RECORDS_IN_MEMORY: Final = 256
DEFAULT_MERGE_FAN_IN: Final = 32
DEFAULT_PARTITION_ROWS: Final = MAX_ROWS_PER_PHYSICAL_SHARD
SUPPORTED_FAMILIES: Final = frozenset(
    {
        "chunks",
        "corpus",
        "documents",
        "locators",
        "postings",
        "terms",
        "vectors",
    }
)

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]
KeyFn = Callable[[Mapping[str, Any]], Any]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ExternalSortError(ValueError):
    """Raised when spill/merge cannot complete under the contract."""

    code: str = "external_sort_failed"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class MemoryBudgetError(ExternalSortError):
    """Raised when a builder would exceed the resident-record bound."""

    code = "memory_budget_exceeded"


class ExternalSortCheckpointError(ExternalSortError):
    """Raised when a checkpoint is corrupt, stale, or config-mismatched."""

    code = "sort_checkpoint_invalid"


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExternalSortError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise ExternalSortError(f"{name} must not contain NUL")
    text = value.strip()
    if len(text) > maximum:
        raise ExternalSortError(f"{name} exceeds maximum length {maximum}")
    return text


def _require_non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ExternalSortError(f"{name} must be an integer")
    if value < 0:
        raise ExternalSortError(f"{name} must be >= 0")
    return value


def _require_positive_int(value: Any, name: str) -> int:
    number = _require_non_negative_int(value, name)
    if number < 1:
        raise ExternalSortError(f"{name} must be >= 1")
    return number


def _validate_partition_bound(max_rows: Any, *, name: str = "max_rows") -> int:
    number = _require_positive_int(max_rows, name)
    if number > MAX_ROWS_PER_PHYSICAL_SHARD:
        raise PhysicalBoundError(
            f"{name}={number} exceeds physical bound {MAX_ROWS_PER_PHYSICAL_SHARD}"
        )
    return number


def file_sha256(path: PathLike) -> str:
    """Return lowercase hex SHA-256 of the file at *path*."""

    target = Path(path)
    hasher = hashlib.sha256()
    with target.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            hasher.update(block)
    return hasher.hexdigest()


def write_bytes_atomic(path: PathLike, data: bytes) -> Path:
    """Write *data* via a sibling temp file and ``os.replace``."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".hf-graphrag-sort-",
        suffix=".tmp",
        dir=str(target.parent),
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return target


def write_json_atomic(path: PathLike, payload: Mapping[str, Any]) -> Path:
    """Write *payload* as sorted JSON via temp file + ``os.replace``."""

    text = (
        json.dumps(
            dict(payload),
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    )
    return write_bytes_atomic(path, text.encode("utf-8"))


def load_json_mapping(path: PathLike) -> dict[str, Any]:
    target = Path(path)
    if not target.is_file():
        raise ExternalSortCheckpointError(f"JSON file not found: {target}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ExternalSortCheckpointError(
            f"invalid JSON at {target}: {exc}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise ExternalSortCheckpointError(f"JSON root must be a mapping: {target}")
    return dict(payload)


def iter_jsonl(path: PathLike) -> Iterator[dict[str, Any]]:
    """Yield records from a JSONL file without loading the file into RAM."""

    target = Path(path)
    if not target.is_file():
        raise ExternalSortError(f"JSONL file not found: {target}")
    with target.open("r", encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ExternalSortError(
                    f"invalid JSONL at {target}:{line_no}: {exc}"
                ) from exc
            if not isinstance(payload, Mapping):
                raise ExternalSortError(
                    f"JSONL record at {target}:{line_no} must be a mapping"
                )
            yield dict(payload)


@dataclass(frozen=True, slots=True)
class JsonlWriteResult:
    """Outcome of an atomic JSONL write."""

    path: str
    row_count: int
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "row_count": self.row_count,
            "sha256": self.sha256,
        }


def write_jsonl_atomic(
    path: PathLike,
    records: Iterable[Mapping[str, Any]],
) -> JsonlWriteResult:
    """Stream *records* to *path* as canonical JSONL (temp file + replace)."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    hasher = hashlib.sha256()
    count = 0
    fd, tmp_name = tempfile.mkstemp(
        prefix=".hf-graphrag-sort-",
        suffix=".jsonl",
        dir=str(target.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for record in records:
                if not isinstance(record, Mapping):
                    raise ExternalSortError("JSONL records must be mappings")
                line = canonical_json_dumps(dict(record)) + "\n"
                handle.write(line)
                hasher.update(line.encode("utf-8"))
                count += 1
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return JsonlWriteResult(path=str(target), row_count=count, sha256=hasher.hexdigest())


def estimate_record_bytes(record: Mapping[str, Any]) -> int:
    """Estimate canonical JSON size of *record*."""

    return len(canonical_json_bytes(dict(record)))


# ---------------------------------------------------------------------------
# Family sort keys
# ---------------------------------------------------------------------------


def normalize_sort_family(value: Any, *, name: str = "family") -> str:
    """Normalize a builder family token to a supported sort family."""

    text = _require_non_empty_str(value, name, maximum=128).lower().replace("-", "_")
    aliases = {
        "chunk": "chunks",
        "chunks": "chunks",
        "corpus": "corpus",
        "document": "documents",
        "documents": "documents",
        "docs": "documents",
        "bm25_documents": "documents",
        "bm25_docs": "documents",
        "locator": "locators",
        "locators": "locators",
        "locator_index": "locators",
        "posting": "postings",
        "postings": "postings",
        "bm25": "postings",
        "bm25_postings": "postings",
        "term": "terms",
        "terms": "terms",
        "embedding": "vectors",
        "embeddings": "vectors",
        "vector": "vectors",
        "vectors": "vectors",
    }
    family = aliases.get(text, text)
    if family not in SUPPORTED_FAMILIES:
        raise ExternalSortError(
            f"{name} must be one of {sorted(SUPPORTED_FAMILIES)}, got {value!r}"
        )
    return family


def document_sort_key(record: Mapping[str, Any]) -> tuple[Any, ...]:
    """Stable document order: ``(document_index, entry_cid)``."""

    if not isinstance(record, Mapping):
        raise ExternalSortError("record must be a mapping")
    return (
        int(record.get("document_index") or 0),
        str(record.get("entry_cid") or ""),
    )


def posting_sort_key(record: Mapping[str, Any]) -> tuple[Any, ...]:
    """Lexicographic postings order: ``(term, entry_cid)``."""

    if not isinstance(record, Mapping):
        raise ExternalSortError("record must be a mapping")
    return (
        str(record.get("term") or ""),
        str(record.get("entry_cid") or ""),
    )


def term_sort_key(record: Mapping[str, Any]) -> tuple[Any, ...]:
    """Lexicographic term-range order."""

    if not isinstance(record, Mapping):
        raise ExternalSortError("record must be a mapping")
    return (str(record.get("term") or record.get("first_key") or ""),)


def vector_sort_key(record: Mapping[str, Any]) -> tuple[Any, ...]:
    """Descending centroid cosine, then durable ``entry_cid``.

    When *cosine_to_centroid* is absent the key falls back to ``entry_cid``
    so fixture streams without scores remain total-ordered.
    """

    if not isinstance(record, Mapping):
        raise ExternalSortError("record must be a mapping")
    cosine = record.get("cosine_to_centroid")
    if cosine is None:
        return (str(record.get("entry_cid") or ""),)
    try:
        value = float(cosine)
    except (TypeError, ValueError) as exc:
        raise ExternalSortError(
            f"cosine_to_centroid must be a finite float, got {cosine!r}"
        ) from exc
    if value != value or value in {float("inf"), float("-inf")}:
        raise ExternalSortError("cosine_to_centroid must be finite")
    return (-value, str(record.get("entry_cid") or ""))


def locator_sort_key(record: Mapping[str, Any]) -> tuple[Any, ...]:
    """Locator / compact-index order: ``(first_key, shard_id, relative_path)``."""

    if not isinstance(record, Mapping):
        raise ExternalSortError("record must be a mapping")
    shard = record.get("shard_id") or 0
    if isinstance(shard, bool) or not isinstance(shard, int):
        try:
            shard = int(shard)
        except (TypeError, ValueError) as exc:
            raise ExternalSortError(
                f"shard_id must be an integer, got {shard!r}"
            ) from exc
    return (
        str(record.get("first_key") or record.get("first_term") or ""),
        int(shard),
        str(record.get("relative_path") or record.get("path") or ""),
    )


def chunk_sort_key(record: Mapping[str, Any]) -> tuple[Any, ...]:
    """Corpus-chunk order used by streaming builders."""

    if not isinstance(record, Mapping):
        raise ExternalSortError("record must be a mapping")
    return (
        str(record.get("jurisdiction_code") or record.get("partition") or ""),
        int(record.get("document_index") or 0),
        int(record.get("chunk_index") or 0),
        str(record.get("entry_cid") or record.get("chunk_cid") or ""),
    )


def sort_key_for_family(family: str) -> KeyFn:
    """Return the sealed key function for *family*."""

    normalized = normalize_sort_family(family)
    mapping: dict[str, KeyFn] = {
        "chunks": chunk_sort_key,
        "corpus": chunk_sort_key,
        "documents": document_sort_key,
        "locators": locator_sort_key,
        "postings": posting_sort_key,
        "terms": term_sort_key,
        "vectors": vector_sort_key,
    }
    return mapping[normalized]


def total_sort_key(record: Mapping[str, Any], key_fn: KeyFn) -> tuple[Any, ...]:
    """Total order: family key, then canonical-JSON digest of the record.

    The digest tie-breaker makes equal primary keys byte-deterministic
    across different spill/run boundaries.
    """

    if not isinstance(record, Mapping):
        raise ExternalSortError("record must be a mapping")
    primary = key_fn(record)
    if not isinstance(primary, tuple):
        primary = (primary,)
    return (primary, content_sha256(canonical_json_dumps(dict(record))))


# ---------------------------------------------------------------------------
# Memory budget
# ---------------------------------------------------------------------------


class MemoryBudget:
    """Fail-closed resident-record (and optional byte) bound."""

    def __init__(
        self,
        *,
        max_resident_records: int = DEFAULT_MAX_RECORDS_IN_MEMORY,
        max_resident_bytes: int | None = None,
    ) -> None:
        self.max_resident_records = _require_positive_int(
            max_resident_records, "max_resident_records"
        )
        if max_resident_bytes is not None:
            self.max_resident_bytes: int | None = _require_positive_int(
                max_resident_bytes, "max_resident_bytes"
            )
        else:
            self.max_resident_bytes = None
        self.resident_records = 0
        self.resident_bytes = 0
        self.peak_resident_records = 0
        self.peak_resident_bytes = 0

    def acquire(self, records: int = 1, nbytes: int = 0) -> None:
        count = _require_positive_int(records, "records")
        size = _require_non_negative_int(nbytes, "nbytes")
        next_records = self.resident_records + count
        if next_records > self.max_resident_records:
            raise MemoryBudgetError(
                f"resident records {next_records} exceed bound "
                f"{self.max_resident_records}"
            )
        next_bytes = self.resident_bytes + size
        if (
            self.max_resident_bytes is not None
            and next_bytes > self.max_resident_bytes
        ):
            raise MemoryBudgetError(
                f"resident bytes {next_bytes} exceed bound {self.max_resident_bytes}"
            )
        self.resident_records = next_records
        self.resident_bytes = next_bytes
        if next_records > self.peak_resident_records:
            self.peak_resident_records = next_records
        if next_bytes > self.peak_resident_bytes:
            self.peak_resident_bytes = next_bytes

    def release(self, records: int = 1, nbytes: int = 0) -> None:
        count = _require_positive_int(records, "records")
        size = _require_non_negative_int(nbytes, "nbytes")
        if count > self.resident_records:
            raise MemoryBudgetError("cannot release more records than acquired")
        if size > self.resident_bytes:
            raise MemoryBudgetError("cannot release more bytes than acquired")
        self.resident_records -= count
        self.resident_bytes -= size

    def check_materialize(self, count: int) -> None:
        """Refuse an in-memory materialization that would exceed the bound."""

        number = _require_non_negative_int(count, "count")
        if number > self.max_resident_records:
            raise MemoryBudgetError(
                f"refusing to materialize {number} records; bound is "
                f"{self.max_resident_records}"
            )


# ---------------------------------------------------------------------------
# Configuration / checkpoint / receipt
# ---------------------------------------------------------------------------


class SortStatus(str, Enum):
    """Lifecycle of an external sort."""

    SPILLING = "spilling"
    MERGING = "merging"
    COMPLETE = "complete"
    INTERRUPTED = "interrupted"

    @classmethod
    def coerce(cls, value: Any) -> "SortStatus":
        if isinstance(value, cls):
            return value
        text = str(value or "").strip().lower()
        for item in cls:
            if item.value == text:
                return item
        raise ExternalSortError(f"unknown sort status: {value!r}")


@dataclass(frozen=True, slots=True)
class ExternalSortConfig:
    """Bounded spill/merge settings for one family."""

    max_records_in_memory: int = DEFAULT_MAX_RECORDS_IN_MEMORY
    max_bytes_in_memory: int | None = None
    merge_fan_in: int = DEFAULT_MERGE_FAN_IN
    family: str = "documents"
    resume: bool = True
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "max_records_in_memory",
            _require_positive_int(self.max_records_in_memory, "max_records_in_memory"),
        )
        if self.max_bytes_in_memory is not None:
            object.__setattr__(
                self,
                "max_bytes_in_memory",
                _require_positive_int(self.max_bytes_in_memory, "max_bytes_in_memory"),
            )
        object.__setattr__(
            self,
            "merge_fan_in",
            _require_positive_int(self.merge_fan_in, "merge_fan_in"),
        )
        object.__setattr__(self, "family", normalize_sort_family(self.family))
        object.__setattr__(
            self,
            "schema_version",
            _require_non_empty_str(self.schema_version, "schema_version"),
        )
        if self.schema_version != SCHEMA_VERSION:
            raise ExternalSortError(
                f"unsupported external-sort schema: {self.schema_version!r}"
            )
        if not isinstance(self.resume, bool):
            raise ExternalSortError("resume must be a boolean")

    def to_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "max_bytes_in_memory": self.max_bytes_in_memory,
            "max_records_in_memory": self.max_records_in_memory,
            "merge_fan_in": self.merge_fan_in,
            "resume": self.resume,
            "schema_version": self.schema_version,
        }

    @property
    def digest(self) -> str:
        payload = {
            "family": self.family,
            "max_bytes_in_memory": self.max_bytes_in_memory,
            "max_records_in_memory": self.max_records_in_memory,
            "merge_fan_in": self.merge_fan_in,
            "schema_version": self.schema_version,
        }
        return digest_mapping(payload)


@dataclass
class ExternalSortCheckpoint:
    """Atomic spill/merge progress bound to a configuration digest."""

    config_digest: str
    records_consumed: int
    run_paths: list[str]
    run_digests: list[str]
    status: SortStatus
    output_path: str = ""
    output_digest: str = ""
    row_count: int = 0
    peak_resident_records: int = 0
    schema_version: str = CHECKPOINT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_digest": self.config_digest,
            "output_digest": self.output_digest,
            "output_path": self.output_path,
            "peak_resident_records": self.peak_resident_records,
            "records_consumed": self.records_consumed,
            "row_count": self.row_count,
            "run_digests": list(self.run_digests),
            "run_paths": list(self.run_paths),
            "schema_version": self.schema_version,
            "status": self.status.value,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ExternalSortCheckpoint":
        if not isinstance(value, Mapping):
            raise ExternalSortCheckpointError("sort checkpoint must be a mapping")
        schema = value.get("schema_version")
        if schema != CHECKPOINT_SCHEMA_VERSION:
            raise ExternalSortCheckpointError(
                f"unsupported sort checkpoint schema: {schema!r}"
            )
        return cls(
            config_digest=str(value.get("config_digest") or ""),
            records_consumed=int(value.get("records_consumed") or 0),
            run_paths=[str(item) for item in (value.get("run_paths") or [])],
            run_digests=[str(item) for item in (value.get("run_digests") or [])],
            status=SortStatus.coerce(value.get("status") or SortStatus.SPILLING),
            output_path=str(value.get("output_path") or ""),
            output_digest=str(value.get("output_digest") or ""),
            row_count=int(value.get("row_count") or 0),
            peak_resident_records=int(value.get("peak_resident_records") or 0),
            schema_version=str(schema),
        )


@dataclass(frozen=True, slots=True)
class ExternalSortReceipt:
    """Byte-addressed outcome of a completed or interrupted sort."""

    output_path: str
    output_digest: str
    row_count: int
    run_count: int
    records_consumed: int
    peak_resident_records: int
    max_records_in_memory: int
    interrupted: bool
    status: str
    family: str = "documents"
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "interrupted": self.interrupted,
            "max_records_in_memory": self.max_records_in_memory,
            "output_digest": self.output_digest,
            "output_path": self.output_path,
            "peak_resident_records": self.peak_resident_records,
            "records_consumed": self.records_consumed,
            "row_count": self.row_count,
            "run_count": self.run_count,
            "schema_version": self.schema_version,
            "status": self.status,
        }


def _assert_sort_checkpoint_compatible(
    checkpoint: ExternalSortCheckpoint,
    config: ExternalSortConfig,
) -> None:
    if checkpoint.config_digest != config.digest:
        raise ExternalSortCheckpointError(
            "sort checkpoint config_digest does not match active sort configuration"
        )


# ---------------------------------------------------------------------------
# Sorter
# ---------------------------------------------------------------------------


class ExternalSorter:
    """Spill sorted runs and k-way merge them under a memory bound."""

    def __init__(
        self,
        work_dir: PathLike,
        *,
        key_fn: KeyFn | None = None,
        config: ExternalSortConfig | None = None,
        budget: MemoryBudget | None = None,
    ) -> None:
        self.work_dir = Path(work_dir)
        self.config = config or ExternalSortConfig()
        self.key_fn = key_fn or sort_key_for_family(self.config.family)
        self.budget = budget or MemoryBudget(
            max_resident_records=self.config.max_records_in_memory,
            max_resident_bytes=self.config.max_bytes_in_memory,
        )
        self.checkpoint_path = self.work_dir / CHECKPOINT_FILENAME
        self.runs_dir = self.work_dir / "runs"

    def _load_checkpoint(self) -> ExternalSortCheckpoint | None:
        if not self.checkpoint_path.is_file():
            return None
        return ExternalSortCheckpoint.from_mapping(load_json_mapping(self.checkpoint_path))

    def _write_checkpoint(self, checkpoint: ExternalSortCheckpoint) -> None:
        self.work_dir.mkdir(parents=True, exist_ok=True)
        write_json_atomic(self.checkpoint_path, checkpoint.to_dict())

    def _spill_buffer(
        self,
        buffer: list[dict[str, Any]],
        run_index: int,
    ) -> JsonlWriteResult:
        buffer.sort(key=lambda record: total_sort_key(record, self.key_fn))
        path = self.runs_dir / f"run-{run_index:06d}.jsonl"
        result = write_jsonl_atomic(path, buffer)
        released = list(buffer)
        buffer.clear()
        for record in released:
            self.budget.release(1, estimate_record_bytes(record))
        return result

    def _iter_merge(self, run_paths: Sequence[Path]) -> Iterator[dict[str, Any]]:
        if not run_paths:
            return
            yield  # pragma: no cover — keep this a generator
        # Merge heads are resident records.  Never open more streams than
        # the memory bound, even when the configured fan-in is larger.
        fan_in = min(self.config.merge_fan_in, self.config.max_records_in_memory)
        if fan_in < 2:
            fan_in = 2
        current = [Path(path) for path in run_paths]
        pass_index = 0
        while len(current) > fan_in:
            next_paths: list[Path] = []
            for group_index in range(0, len(current), fan_in):
                group = current[group_index : group_index + fan_in]
                merged_path = (
                    self.work_dir / f"merge-{pass_index:03d}-{group_index:06d}.jsonl"
                )
                write_jsonl_atomic(
                    merged_path,
                    heapq.merge(
                        *(iter_jsonl(path) for path in group),
                        key=lambda record: total_sort_key(record, self.key_fn),
                    ),
                )
                next_paths.append(merged_path)
            current = next_paths
            pass_index += 1
        # Merge heads are streaming file cursors, not buffered records.
        # Residency is capped by fan_in (<= max_records_in_memory for
        # max_records_in_memory >= 2) and is reflected in the peak.
        if len(current) > self.budget.peak_resident_records:
            self.budget.peak_resident_records = len(current)
        yield from heapq.merge(
            *(iter_jsonl(path) for path in current),
            key=lambda record: total_sort_key(record, self.key_fn),
        )

    def sort_to_file(
        self,
        records: Iterable[Mapping[str, Any]],
        output_path: PathLike,
        *,
        interrupt_after_runs: int | None = None,
    ) -> ExternalSortReceipt:
        """Spill, merge, and write a byte-deterministic JSONL artifact."""

        config = self.config
        existing = self._load_checkpoint() if config.resume else None
        if existing is not None:
            _assert_sort_checkpoint_compatible(existing, config)
            if existing.status is SortStatus.COMPLETE and existing.output_digest:
                output = Path(existing.output_path or output_path)
                if output.is_file() and file_sha256(output) == existing.output_digest:
                    return ExternalSortReceipt(
                        output_path=str(output),
                        output_digest=existing.output_digest,
                        row_count=existing.row_count,
                        run_count=len(existing.run_paths),
                        records_consumed=existing.records_consumed,
                        peak_resident_records=max(
                            existing.peak_resident_records,
                            self.budget.peak_resident_records,
                        ),
                        max_records_in_memory=config.max_records_in_memory,
                        interrupted=False,
                        status=SortStatus.COMPLETE.value,
                        family=config.family,
                    )
                raise ExternalSortError(
                    "completed sort checkpoint output digest does not match file"
                )

        skip_until = existing.records_consumed if existing else 0
        records_consumed = skip_until
        run_paths = list(existing.run_paths) if existing else []
        run_digests = list(existing.run_digests) if existing else []
        status = existing.status if existing else SortStatus.SPILLING

        if status is SortStatus.SPILLING or existing is None:
            skipped = 0
            buffer: list[dict[str, Any]] = []
            for record in records:
                if skipped < skip_until:
                    skipped += 1
                    continue
                if not isinstance(record, Mapping):
                    raise ExternalSortError("records must be mappings")
                payload = dict(record)
                nbytes = estimate_record_bytes(payload)
                self.budget.acquire(1, nbytes)
                buffer.append(payload)
                records_consumed += 1
                if len(buffer) >= config.max_records_in_memory:
                    spilled = self._spill_buffer(buffer, len(run_paths))
                    run_paths.append(spilled.path)
                    run_digests.append(spilled.sha256)
                    status = SortStatus.SPILLING
                    self._write_checkpoint(
                        ExternalSortCheckpoint(
                            config_digest=config.digest,
                            records_consumed=records_consumed,
                            run_paths=run_paths,
                            run_digests=run_digests,
                            status=status,
                            peak_resident_records=self.budget.peak_resident_records,
                        )
                    )
                    if (
                        interrupt_after_runs is not None
                        and len(run_paths) >= interrupt_after_runs
                    ):
                        return ExternalSortReceipt(
                            output_path="",
                            output_digest="",
                            row_count=0,
                            run_count=len(run_paths),
                            records_consumed=records_consumed,
                            peak_resident_records=self.budget.peak_resident_records,
                            max_records_in_memory=config.max_records_in_memory,
                            interrupted=True,
                            status=SortStatus.INTERRUPTED.value,
                            family=config.family,
                        )
            if buffer:
                spilled = self._spill_buffer(buffer, len(run_paths))
                run_paths.append(spilled.path)
                run_digests.append(spilled.sha256)

        for path, digest in zip(run_paths, run_digests):
            if not Path(path).is_file():
                raise ExternalSortError(f"missing spilled run: {path}")
            if file_sha256(path) != digest:
                raise ExternalSortError(f"spilled run digest mismatch: {path}")

        status = SortStatus.MERGING
        self._write_checkpoint(
            ExternalSortCheckpoint(
                config_digest=config.digest,
                records_consumed=records_consumed,
                run_paths=run_paths,
                run_digests=run_digests,
                status=status,
                peak_resident_records=self.budget.peak_resident_records,
            )
        )

        output = Path(output_path)
        if run_paths:
            written = write_jsonl_atomic(
                output, self._iter_merge([Path(p) for p in run_paths])
            )
        else:
            written = write_jsonl_atomic(output, ())

        complete = ExternalSortCheckpoint(
            config_digest=config.digest,
            records_consumed=records_consumed,
            run_paths=run_paths,
            run_digests=run_digests,
            status=SortStatus.COMPLETE,
            output_path=written.path,
            output_digest=written.sha256,
            row_count=written.row_count,
            peak_resident_records=self.budget.peak_resident_records,
        )
        self._write_checkpoint(complete)
        return ExternalSortReceipt(
            output_path=written.path,
            output_digest=written.sha256,
            row_count=written.row_count,
            run_count=len(run_paths),
            records_consumed=records_consumed,
            peak_resident_records=self.budget.peak_resident_records,
            max_records_in_memory=config.max_records_in_memory,
            interrupted=False,
            status=SortStatus.COMPLETE.value,
            family=config.family,
        )


def external_sort_to_file(
    records: Iterable[Mapping[str, Any]],
    output_path: PathLike,
    *,
    work_dir: PathLike,
    key_fn: KeyFn | None = None,
    family: str = "documents",
    max_records_in_memory: int = DEFAULT_MAX_RECORDS_IN_MEMORY,
    max_bytes_in_memory: int | None = None,
    budget: MemoryBudget | None = None,
    resume: bool = True,
    interrupt_after_runs: int | None = None,
) -> ExternalSortReceipt:
    """Externally sort *records* to *output_path* under a memory bound."""

    sorter = ExternalSorter(
        work_dir,
        key_fn=key_fn,
        config=ExternalSortConfig(
            max_records_in_memory=max_records_in_memory,
            max_bytes_in_memory=max_bytes_in_memory,
            family=family,
            resume=resume,
        ),
        budget=budget,
    )
    return sorter.sort_to_file(
        records,
        output_path,
        interrupt_after_runs=interrupt_after_runs,
    )


def external_sort(
    records: Iterable[Mapping[str, Any]],
    *,
    work_dir: PathLike,
    key_fn: KeyFn | None = None,
    family: str = "documents",
    max_records_in_memory: int = DEFAULT_MAX_RECORDS_IN_MEMORY,
    budget: MemoryBudget | None = None,
) -> Iterator[dict[str, Any]]:
    """Externally sort *records* and yield the merged stream."""

    work = Path(work_dir)
    output = work / "sorted.jsonl"
    receipt = external_sort_to_file(
        records,
        output,
        work_dir=work / "sort-work",
        key_fn=key_fn,
        family=family,
        max_records_in_memory=max_records_in_memory,
        budget=budget,
    )
    if receipt.interrupted:
        raise ExternalSortError("external sort interrupted before merge")
    yield from iter_jsonl(output)


def spill_sorted_run(
    records: Sequence[Mapping[str, Any]],
    path: PathLike,
    *,
    key_fn: KeyFn,
) -> JsonlWriteResult:
    """Sort *records* in memory and spill one run.  Caller bounds *records*."""

    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        raise ExternalSortError("records must be a sequence of mappings")
    ordered = sorted(
        (dict(item) for item in records),
        key=lambda rec: total_sort_key(rec, key_fn),
    )
    return write_jsonl_atomic(path, ordered)


def merge_sorted_runs(
    run_paths: Sequence[PathLike],
    output_path: PathLike,
    *,
    key_fn: KeyFn,
) -> JsonlWriteResult:
    """K-way merge already-sorted run files into *output_path*."""

    if not isinstance(run_paths, Sequence) or isinstance(run_paths, (str, bytes)):
        raise ExternalSortError("run_paths must be a sequence")
    return write_jsonl_atomic(
        output_path,
        heapq.merge(
            *(iter_jsonl(path) for path in run_paths),
            key=lambda record: total_sort_key(record, key_fn),
        ),
    )


# ---------------------------------------------------------------------------
# Bounded partition streaming
# ---------------------------------------------------------------------------


def stream_bounded_partitions(
    records: Iterable[Mapping[str, Any]],
    *,
    max_rows: int = DEFAULT_PARTITION_ROWS,
    budget: MemoryBudget | None = None,
) -> Iterator[tuple[dict[str, Any], ...]]:
    """Yield ordered partitions of at most *max_rows* records.

    Never holds more than *max_rows* records.  *max_rows* cannot exceed
    the physical 4,096-row shard bound.  Input is assumed already ordered;
    pair with :func:`external_sort` when the source is unsorted.
    """

    bound = _validate_partition_bound(max_rows)
    resident = budget or MemoryBudget(max_resident_records=bound)
    buffer: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, Mapping):
            raise ExternalSortError("records must be mappings")
        payload = dict(record)
        nbytes = estimate_record_bytes(payload)
        resident.acquire(1, nbytes)
        buffer.append(payload)
        if len(buffer) >= bound:
            yield tuple(buffer)
            released = list(buffer)
            buffer.clear()
            for item in released:
                resident.release(1, estimate_record_bytes(item))
    if buffer:
        yield tuple(buffer)
        released = list(buffer)
        buffer.clear()
        for item in released:
            resident.release(1, estimate_record_bytes(item))


def stream_sorted_partitions(
    records: Iterable[Mapping[str, Any]],
    *,
    work_dir: PathLike,
    key_fn: KeyFn | None = None,
    family: str = "documents",
    max_records_in_memory: int = DEFAULT_MAX_RECORDS_IN_MEMORY,
    max_rows: int = DEFAULT_PARTITION_ROWS,
    budget: MemoryBudget | None = None,
) -> Iterator[tuple[dict[str, Any], ...]]:
    """Externally sort *records* then stream bounded partitions."""

    yield from stream_bounded_partitions(
        external_sort(
            records,
            work_dir=work_dir,
            key_fn=key_fn,
            family=family,
            max_records_in_memory=max_records_in_memory,
            budget=budget,
        ),
        max_rows=max_rows,
    )


__all__ = [
    "CHECKPOINT_FILENAME",
    "CHECKPOINT_SCHEMA_VERSION",
    "DEFAULT_MAX_RECORDS_IN_MEMORY",
    "DEFAULT_MERGE_FAN_IN",
    "DEFAULT_PARTITION_ROWS",
    "SCHEMA_VERSION",
    "SUPPORTED_FAMILIES",
    "TASK_ID",
    "ExternalSortCheckpoint",
    "ExternalSortCheckpointError",
    "ExternalSortConfig",
    "ExternalSortError",
    "ExternalSortReceipt",
    "ExternalSorter",
    "JsonlWriteResult",
    "MemoryBudget",
    "MemoryBudgetError",
    "SortStatus",
    "chunk_sort_key",
    "document_sort_key",
    "estimate_record_bytes",
    "external_sort",
    "external_sort_to_file",
    "file_sha256",
    "iter_jsonl",
    "load_json_mapping",
    "locator_sort_key",
    "merge_sorted_runs",
    "normalize_sort_family",
    "posting_sort_key",
    "sort_key_for_family",
    "spill_sorted_run",
    "stream_bounded_partitions",
    "stream_sorted_partitions",
    "term_sort_key",
    "total_sort_key",
    "vector_sort_key",
    "write_bytes_atomic",
    "write_json_atomic",
    "write_jsonl_atomic",
]
