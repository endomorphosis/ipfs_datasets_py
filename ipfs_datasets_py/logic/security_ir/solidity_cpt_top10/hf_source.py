"""Offline-first verification and ingestion for the pinned Hugging Face source.

Imports are inert: this module performs no network access, credential lookup,
dependency installation, compilation, execution, or upload.  Intake consumes
either the digest-verified local Parquet shard or a caller-injected iterable
whose metadata has already been observed independently.

Admission is atomic.  Drift, truncation, duplicates, a late iterator failure,
or any quarantined row yields no admitted records.  Persisted cache loads read
and rehash every manifest, row, receipt, and separate source-body file on every
use.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import tempfile
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Final, Protocol, runtime_checkable

from ...ir_core.canonical import canonical_json_bytes
from ...ir_core.identity import CanonicalIdentity, canonical_identity
from .release_policy import (
    SOLIDITY_CPT_COLUMN_TYPES,
    SOLIDITY_CPT_ROW_COUNT,
)
from .source_snapshot import (
    DEFAULT_ROW_BOUNDS,
    PINNED_SOURCE_SHARD,
    PINNED_SOURCE_SNAPSHOT,
    QUARANTINE_SCHEMA_VERSION,
    SOURCE_ROW_SCHEMA_VERSION,
    AdaptedSolidityCPTRow,
    QuarantineDiagnostic,
    QuarantineReason,
    SolidityCPTRow,
    SolidityCPTRowAdapter,
    SolidityCPTRowBounds,
    SolidityCPTRowError,
    SolidityCPTSourceBody,
    SourceSnapshotObservation,
    SourceSnapshotVerification,
    SourceSnapshotVerificationError,
    read_verified_shard_bytes,
    verify_shard_bytes,
    verify_source_snapshot,
)

HF_SOURCE_SCHEMA_VERSION: Final = "solidity-cpt-hf-source/v1"
HF_INGEST_RECEIPT_SCHEMA_VERSION: Final = "solidity-cpt-hf-ingest-receipt/v1"
HF_CACHE_SCHEMA_VERSION: Final = "solidity-cpt-hf-source-cache/v1"
_CID_ALPHABET: Final = frozenset("abcdefghijklmnopqrstuvwxyz234567")
_SHA256_ALPHABET: Final = frozenset("0123456789abcdef")


class HuggingFaceSourceError(ValueError):
    """Base error for bounded source intake and cache verification."""


class HuggingFaceSourceIntegrityError(HuggingFaceSourceError):
    """Raised when source or persisted artifact integrity does not verify."""


class HuggingFaceSourceLimitError(HuggingFaceSourceError):
    """Raised before an input exceeds an explicit intake bound."""


class HuggingFaceSourceCacheMiss(HuggingFaceSourceError):
    """Raised when an exact offline snapshot is not cached."""


def _positive_int(value: Any, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise HuggingFaceSourceLimitError(f"{label} must be a positive integer")
    return value


def _cid(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 59
        or not value.startswith("b")
        or any(character not in _CID_ALPHABET for character in value)
    ):
        raise HuggingFaceSourceIntegrityError(f"{label} must be an ir_core CID")
    return value


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise HuggingFaceSourceIntegrityError(f"{label} must be a mapping")
    return value


def _exact_fields(
    value: Mapping[str, Any],
    expected: frozenset[str],
    label: str,
) -> None:
    if set(value) != set(expected):
        raise HuggingFaceSourceIntegrityError(f"{label} has unknown or missing fields")


def _strict_json_object(content: bytes, label: str) -> Mapping[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in items:
            if key in result:
                raise HuggingFaceSourceIntegrityError(f"{label} contains duplicate key {key!r}")
            result[key] = item
        return result

    def reject_constant(value: str) -> None:
        raise HuggingFaceSourceIntegrityError(f"{label} contains non-finite number {value}")

    try:
        decoded = json.loads(
            content,
            object_pairs_hook=pairs,
            parse_constant=reject_constant,
        )
    except HuggingFaceSourceIntegrityError:
        raise
    except (UnicodeError, ValueError, TypeError) as exc:
        raise HuggingFaceSourceIntegrityError(f"{label} is not strict UTF-8 JSON") from exc
    return _mapping(decoded, label)


def _safe_file(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative or "\x00" in relative:
        raise HuggingFaceSourceIntegrityError("cache path is malformed")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or pure.as_posix() != relative or any(part in {"", ".", ".."} for part in pure.parts):
        raise HuggingFaceSourceIntegrityError("cache path escapes root")
    path = root.joinpath(*pure.parts)
    if path.is_symlink() or not path.is_file():
        raise HuggingFaceSourceIntegrityError(f"cache artifact is missing, non-regular, or symlink: {relative}")
    try:
        path.resolve(strict=True).relative_to(root)
    except (OSError, ValueError) as exc:
        raise HuggingFaceSourceIntegrityError(f"cache artifact escapes root: {relative}") from exc
    return path


def _bounded_read(path: Path, maximum: int, label: str) -> bytes:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise HuggingFaceSourceIntegrityError(f"cannot stat {label}") from exc
    if size > maximum:
        raise HuggingFaceSourceLimitError(f"{label} exceeds byte limit")
    try:
        with path.open("rb") as handle:
            content = handle.read(maximum + 1)
    except OSError as exc:
        raise HuggingFaceSourceIntegrityError(f"cannot read {label}") from exc
    if len(content) > maximum:
        raise HuggingFaceSourceLimitError(f"{label} exceeds byte limit")
    return content


@dataclass(frozen=True, slots=True)
class HuggingFaceSourceLimits:
    """Hard bounds for source iteration, Parquet batches, and cache loads."""

    max_rows: int = SOLIDITY_CPT_ROW_COUNT
    max_quarantines: int = 64
    max_diagnostics: int = 64
    max_manifest_bytes: int = 64 * 1024 * 1024
    max_row_record_bytes: int = 64 * 1024
    max_source_body_bytes: int = DEFAULT_ROW_BOUNDS.max_source_bytes
    parquet_batch_rows: int = 512

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            _positive_int(getattr(self, name), name)
        if self.max_rows < SOLIDITY_CPT_ROW_COUNT:
            raise HuggingFaceSourceLimitError("max_rows cannot be below pinned source row count")
        if self.max_diagnostics > self.max_quarantines:
            raise HuggingFaceSourceLimitError("max_diagnostics cannot exceed max_quarantines")


@dataclass(frozen=True, slots=True)
class HuggingFaceIngestReceipt:
    """Content-addressed receipt for one atomic successful ingestion."""

    verification_receipt_id: str
    source_snapshot_cid: str
    config_cid: str
    row_ids: tuple[str, ...]
    source_body_cids: tuple[str, ...]
    row_count: int
    receipt_id: str = ""
    verified: bool = True
    grants_authority: bool = False
    schema_version: str = HF_INGEST_RECEIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in (
            "verification_receipt_id",
            "source_snapshot_cid",
            "config_cid",
        ):
            _cid(getattr(self, name), name)
        for name in ("row_ids", "source_body_cids"):
            values = getattr(self, name)
            if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
                raise HuggingFaceSourceIntegrityError(f"{name} must be a sequence")
            normalized = tuple(values)
            if any(not isinstance(item, str) or not item for item in normalized):
                raise HuggingFaceSourceIntegrityError(f"{name} entries must be non-empty strings")
            for item in normalized:
                _cid(item, f"{name} item")
            if name == "row_ids" and len(normalized) != len(set(normalized)):
                raise HuggingFaceSourceIntegrityError(f"{name} must not contain duplicates")
            object.__setattr__(self, name, normalized)
        if (
            type(self.row_count) is not int
            or self.row_count != len(self.row_ids)
            or self.row_count != len(self.source_body_cids)
            or self.row_count != SOLIDITY_CPT_ROW_COUNT
        ):
            raise HuggingFaceSourceIntegrityError("receipt row_count does not match exact source inventory")
        if self.source_snapshot_cid != PINNED_SOURCE_SNAPSHOT.cid:
            raise HuggingFaceSourceIntegrityError("receipt source snapshot differs from reviewed pin")
        if self.verified is not True or self.grants_authority is not False:
            raise HuggingFaceSourceIntegrityError("ingest receipt must be verified and non-authoritative")
        if self.schema_version != HF_INGEST_RECEIPT_SCHEMA_VERSION:
            raise HuggingFaceSourceIntegrityError("unknown ingest receipt schema")
        computed = self.identity.cid
        if self.receipt_id and self.receipt_id != computed:
            raise HuggingFaceSourceIntegrityError("receipt_id does not match rehashed ingest receipt")
        object.__setattr__(self, "receipt_id", computed)

    def deterministic_dict(self) -> dict[str, Any]:
        return {
            "config_cid": self.config_cid,
            "grants_authority": self.grants_authority,
            "row_count": self.row_count,
            "row_ids": list(self.row_ids),
            "schema_version": self.schema_version,
            "source_body_cids": list(self.source_body_cids),
            "source_snapshot_cid": self.source_snapshot_cid,
            "verification_receipt_id": self.verification_receipt_id,
            "verified": self.verified,
        }

    def to_dict(self) -> dict[str, Any]:
        return {"receipt_id": self.receipt_id, **self.deterministic_dict()}

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.deterministic_dict(),
            domain="solidity-cpt/hf-ingest-receipt",
            schema_version=self.schema_version,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HuggingFaceIngestReceipt:
        value = _mapping(value, "ingest receipt")
        _exact_fields(
            value,
            frozenset(
                {
                    "config_cid",
                    "grants_authority",
                    "receipt_id",
                    "row_count",
                    "row_ids",
                    "schema_version",
                    "source_body_cids",
                    "source_snapshot_cid",
                    "verification_receipt_id",
                    "verified",
                }
            ),
            "ingest receipt",
        )
        if not value["receipt_id"]:
            raise HuggingFaceSourceIntegrityError("persisted ingest receipt requires receipt_id")
        return cls(
            verification_receipt_id=value["verification_receipt_id"],
            source_snapshot_cid=value["source_snapshot_cid"],
            config_cid=value["config_cid"],
            row_ids=tuple(value["row_ids"]),
            source_body_cids=tuple(value["source_body_cids"]),
            row_count=value["row_count"],
            receipt_id=value["receipt_id"],
            verified=value["verified"],
            grants_authority=value["grants_authority"],
            schema_version=value["schema_version"],
        )


@dataclass(frozen=True, slots=True)
class HuggingFaceIngestResult:
    """Atomic intake result; rejected results never expose partial records."""

    admitted: bool
    rows: tuple[SolidityCPTRow, ...] = ()
    source_bodies: tuple[SolidityCPTSourceBody, ...] = ()
    diagnostics: tuple[QuarantineDiagnostic, ...] = ()
    receipt: HuggingFaceIngestReceipt | None = None

    def __post_init__(self) -> None:
        rows = tuple(self.rows)
        bodies = tuple(self.source_bodies)
        diagnostics = tuple(self.diagnostics)
        object.__setattr__(self, "rows", rows)
        object.__setattr__(self, "source_bodies", bodies)
        object.__setattr__(self, "diagnostics", diagnostics)
        if self.admitted:
            if diagnostics or self.receipt is None:
                raise HuggingFaceSourceIntegrityError("admitted result cannot contain quarantine diagnostics")
            if len(rows) != SOLIDITY_CPT_ROW_COUNT or len(bodies) != len(rows):
                raise HuggingFaceSourceIntegrityError("admitted result must contain exact source inventory")
            row_ids = tuple(item.row_id for item in rows)
            body_ids = tuple(item.content_cid for item in bodies)
            if self.receipt.row_ids != row_ids or self.receipt.source_body_cids != body_ids:
                raise HuggingFaceSourceIntegrityError("admitted inventories do not match receipt")
            if any(
                row.config_cid != self.receipt.config_cid or row.source_snapshot_cid != self.receipt.source_snapshot_cid
                for row in rows
            ):
                raise HuggingFaceSourceIntegrityError("admitted row lineage does not match receipt")
            by_cid = {item.content_cid: item for item in bodies}
            for row in rows:
                try:
                    body = by_cid[row.source_body_cid]
                except KeyError as exc:
                    raise HuggingFaceSourceIntegrityError("row source body is missing") from exc
                if body.sha256 != row.source_body_sha256 or len(body.text) != row.n_chars:
                    raise HuggingFaceSourceIntegrityError("row source body binding mismatch")
        elif rows or bodies or self.receipt is not None:
            raise HuggingFaceSourceIntegrityError("rejected result must not expose partial admitted artifacts")


class HuggingFaceSnapshotIngestor:
    """Verify a pin and atomically adapt a bounded injected or local stream."""

    def __init__(
        self,
        *,
        row_bounds: SolidityCPTRowBounds = DEFAULT_ROW_BOUNDS,
        limits: HuggingFaceSourceLimits | None = None,
    ) -> None:
        self.row_adapter = SolidityCPTRowAdapter(row_bounds)
        self.limits = limits or HuggingFaceSourceLimits()
        if not isinstance(self.limits, HuggingFaceSourceLimits):
            raise TypeError("limits must be HuggingFaceSourceLimits")

    def _verified_parquet_rows(
        self,
        content: bytes,
        *,
        expected_rows: int,
    ) -> Iterator[Mapping[str, Any]]:
        """Decode rows only from the exact immutable bytes already rehashed."""

        try:
            import pyarrow.parquet as pq
        except ImportError as exc:  # pragma: no cover - optional test extra
            raise HuggingFaceSourceError("pyarrow is required for Parquet source intake") from exc
        try:
            parquet = pq.ParquetFile(io.BytesIO(content))
        except Exception as exc:
            raise HuggingFaceSourceIntegrityError("cannot read verified Parquet bytes") from exc
        observed_schema = tuple((field.name, str(field.type)) for field in parquet.schema_arrow)
        if observed_schema != SOLIDITY_CPT_COLUMN_TYPES:
            raise HuggingFaceSourceIntegrityError("Parquet ordered typed schema differs from reviewed pin")
        if parquet.metadata.num_rows != expected_rows:
            raise HuggingFaceSourceIntegrityError("Parquet footer row_count differs from reviewed pin")
        for batch in parquet.iter_batches(batch_size=self.limits.parquet_batch_rows):
            yield from batch.to_pylist()

    def ingest_rows(
        self,
        observation: SourceSnapshotObservation | Mapping[str, Any],
        rows: Iterable[Mapping[str, Any]],
        *,
        shard_content: bytes | bytearray | memoryview,
        _verification_method: str = "injected_bytes",
    ) -> HuggingFaceIngestResult:
        """Admit injected rows only when they equal rows decoded from rehashed bytes."""

        metadata_verification = verify_source_snapshot(observation)
        verification = verify_shard_bytes(
            shard_content,
            observation,
            verification_method=_verification_method,
        )
        trusted_rows = self._verified_parquet_rows(
            bytes(shard_content),
            expected_rows=metadata_verification.row_count,
        )

        def rows_bound_to_verified_bytes() -> Iterator[Mapping[str, Any]]:
            supplied = iter(rows)
            for row_index, trusted in enumerate(trusted_rows):
                try:
                    candidate = next(supplied)
                except StopIteration as exc:
                    raise HuggingFaceSourceIntegrityError("injected row stream is truncated") from exc
                if canonical_json_bytes(candidate) != canonical_json_bytes(trusted):
                    raise HuggingFaceSourceIntegrityError(
                        f"injected row {row_index} differs from verified Parquet bytes"
                    )
                yield trusted
            try:
                next(supplied)
            except StopIteration:
                return
            raise HuggingFaceSourceIntegrityError("injected row stream contains extra rows")

        try:
            iterator = iter(rows_bound_to_verified_bytes())
        except TypeError as exc:
            raise HuggingFaceSourceError("rows must be iterable") from exc

        adapted: list[AdaptedSolidityCPTRow] = []
        diagnostics: list[QuarantineDiagnostic] = []
        raw_fingerprints: set[str] = set()

        def append_diagnostic(diagnostic: QuarantineDiagnostic) -> None:
            if len(diagnostics) >= self.limits.max_diagnostics:
                return
            diagnostics.append(diagnostic)

        expected_rows = metadata_verification.row_count
        observed = 0
        quarantine_count = 0
        try:
            while observed <= expected_rows:
                if observed < expected_rows and quarantine_count >= self.limits.max_quarantines:
                    append_diagnostic(
                        QuarantineDiagnostic(
                            reason=QuarantineReason.OVERSIZE,
                            code="solidity_cpt.stream.quarantine_limit",
                            message="stream reached configured quarantine limit",
                            row_index=observed,
                        )
                    )
                    break
                if observed < expected_rows and observed >= self.limits.max_rows:
                    append_diagnostic(
                        QuarantineDiagnostic(
                            reason=QuarantineReason.OVERSIZE,
                            code="solidity_cpt.stream.row_limit",
                            message="stream exceeds configured row limit",
                            row_index=observed,
                        )
                    )
                    break
                try:
                    value = next(iterator)
                except StopIteration:
                    break
                if observed == expected_rows:
                    append_diagnostic(
                        QuarantineDiagnostic(
                            reason=QuarantineReason.DRIFTED,
                            code="solidity_cpt.stream.extra_rows",
                            message="stream contains rows beyond pinned row_count",
                            row_index=observed,
                        )
                    )
                    observed += 1
                    break
                if not isinstance(value, Mapping):
                    append_diagnostic(
                        self.row_adapter.quarantine(
                            SolidityCPTRowError("source row must be a mapping"),
                            row_index=observed,
                        )
                    )
                    quarantine_count += 1
                    observed += 1
                    continue
                try:
                    fingerprint = canonical_identity(
                        value,
                        domain="solidity-cpt/raw-row",
                        schema_version=SOURCE_ROW_SCHEMA_VERSION,
                    ).cid
                except Exception as exc:
                    append_diagnostic(self.row_adapter.quarantine(exc, row_index=observed))
                    quarantine_count += 1
                    observed += 1
                    continue
                if fingerprint in raw_fingerprints:
                    append_diagnostic(
                        QuarantineDiagnostic(
                            reason=QuarantineReason.DUPLICATE,
                            code="solidity_cpt.stream.duplicate_row",
                            message="stream contains duplicate row content",
                            row_index=observed,
                        )
                    )
                    quarantine_count += 1
                    observed += 1
                    continue
                raw_fingerprints.add(fingerprint)
                try:
                    adapted.append(self.row_adapter.adapt(value, row_index=observed))
                except Exception as exc:
                    append_diagnostic(self.row_adapter.quarantine(exc, row_index=observed))
                    quarantine_count += 1
                observed += 1
        except Exception:
            append_diagnostic(
                QuarantineDiagnostic(
                    reason=QuarantineReason.MALFORMED,
                    code="solidity_cpt.stream.iterator_failure",
                    message="row iterator failed before atomic admission",
                    row_index=observed,
                )
            )

        if observed < expected_rows:
            append_diagnostic(
                QuarantineDiagnostic(
                    reason=QuarantineReason.TRUNCATED,
                    code="solidity_cpt.stream.truncated",
                    message="stream ended before pinned row_count",
                    row_index=observed,
                )
            )
        if len(adapted) != expected_rows and not diagnostics:
            append_diagnostic(
                QuarantineDiagnostic(
                    reason=QuarantineReason.DRIFTED,
                    code="solidity_cpt.stream.inventory_mismatch",
                    message="adapted inventory differs from pinned row_count",
                )
            )
        if diagnostics:
            return HuggingFaceIngestResult(
                admitted=False,
                diagnostics=tuple(diagnostics),
            )

        normalized_rows = tuple(item.row for item in adapted)
        bodies = tuple(item.source_body for item in adapted)
        receipt = HuggingFaceIngestReceipt(
            verification_receipt_id=verification.receipt_id,
            source_snapshot_cid=PINNED_SOURCE_SNAPSHOT.cid,
            config_cid=self.row_adapter.config_cid,
            row_ids=tuple(item.row_id for item in normalized_rows),
            source_body_cids=tuple(item.content_cid for item in bodies),
            row_count=len(normalized_rows),
        )
        return HuggingFaceIngestResult(
            admitted=True,
            rows=normalized_rows,
            source_bodies=bodies,
            receipt=receipt,
        )

    def ingest_local_parquet(
        self,
        path: str | os.PathLike[str],
        observation: SourceSnapshotObservation | Mapping[str, Any],
    ) -> HuggingFaceIngestResult:
        """Rehash the pinned shard, verify its footer schema, then stream rows."""

        content = read_verified_shard_bytes(path, PINNED_SOURCE_SHARD)
        verification = verify_shard_bytes(
            content,
            observation,
            verification_method="local_bytes",
        )
        trusted_rows = self._verified_parquet_rows(
            content,
            expected_rows=verification.row_count,
        )
        return self.ingest_rows(
            observation,
            trusted_rows,
            shard_content=content,
            _verification_method="local_bytes",
        )


@dataclass(frozen=True, slots=True)
class CachedBodyDescriptor:
    """Source-free descriptor for one separately persisted body file."""

    path: str
    content_cid: str
    sha256: str
    byte_length: int

    def __post_init__(self) -> None:
        pure = PurePosixPath(self.path) if isinstance(self.path, str) else None
        if (
            pure is None
            or pure.is_absolute()
            or pure.as_posix() != self.path
            or any(part in {"", ".", ".."} for part in pure.parts)
            or "\\" in self.path
            or not self.path.startswith("bodies/")
        ):
            raise HuggingFaceSourceIntegrityError("body descriptor path must be safe cache-relative text")
        _cid(self.content_cid, "body descriptor content_cid")
        if (
            not isinstance(self.sha256, str)
            or len(self.sha256) != 64
            or any(character not in _SHA256_ALPHABET for character in self.sha256)
        ):
            raise HuggingFaceSourceIntegrityError("body descriptor sha256 must be lowercase SHA-256")
        if type(self.byte_length) is not int or self.byte_length <= 0:
            raise HuggingFaceSourceIntegrityError("body descriptor byte_length must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {
            "byte_length": self.byte_length,
            "content_cid": self.content_cid,
            "path": self.path,
            "sha256": self.sha256,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CachedBodyDescriptor:
        value = _mapping(value, "body descriptor")
        _exact_fields(
            value,
            frozenset({"byte_length", "content_cid", "path", "sha256"}),
            "body descriptor",
        )
        return cls(**value)


@dataclass(frozen=True, slots=True)
class CacheManifest:
    """Strict identity for an admitted cache inventory."""

    receipt: HuggingFaceIngestReceipt
    rows: tuple[SolidityCPTRow, ...]
    bodies: tuple[CachedBodyDescriptor, ...]
    manifest_id: str = ""
    schema_version: str = HF_CACHE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != HF_CACHE_SCHEMA_VERSION:
            raise HuggingFaceSourceIntegrityError("unknown cache manifest schema")
        rows = tuple(self.rows)
        bodies = tuple(self.bodies)
        if len(rows) != self.receipt.row_count or len(bodies) != len(rows):
            raise HuggingFaceSourceIntegrityError("cache manifest inventory count mismatch")
        if tuple(item.row_id for item in rows) != self.receipt.row_ids:
            raise HuggingFaceSourceIntegrityError("cache row inventory differs from receipt")
        if tuple(item.content_cid for item in bodies) != self.receipt.source_body_cids:
            raise HuggingFaceSourceIntegrityError("cache body inventory differs from receipt")
        if any(
            item.config_cid != self.receipt.config_cid or item.source_snapshot_cid != self.receipt.source_snapshot_cid
            for item in rows
        ):
            raise HuggingFaceSourceIntegrityError("cache rows differ from receipt lineage")
        object.__setattr__(self, "rows", rows)
        object.__setattr__(self, "bodies", bodies)
        computed = self.identity.cid
        if self.manifest_id and self.manifest_id != computed:
            raise HuggingFaceSourceIntegrityError("manifest_id does not match rehashed cache inventory")
        object.__setattr__(self, "manifest_id", computed)

    def deterministic_dict(self) -> dict[str, Any]:
        return {
            "bodies": [item.to_dict() for item in self.bodies],
            "receipt": self.receipt.to_dict(),
            "rows": [item.to_dict() for item in self.rows],
            "schema_version": self.schema_version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {"manifest_id": self.manifest_id, **self.deterministic_dict()}

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.deterministic_dict(),
            domain="solidity-cpt/hf-cache-manifest",
            schema_version=self.schema_version,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CacheManifest:
        value = _mapping(value, "cache manifest")
        _exact_fields(
            value,
            frozenset({"bodies", "manifest_id", "receipt", "rows", "schema_version"}),
            "cache manifest",
        )
        if not value["manifest_id"]:
            raise HuggingFaceSourceIntegrityError("persisted cache manifest requires manifest_id")
        raw_rows = value["rows"]
        raw_bodies = value["bodies"]
        if (
            isinstance(raw_rows, (str, bytes, bytearray))
            or not isinstance(raw_rows, Sequence)
            or isinstance(raw_bodies, (str, bytes, bytearray))
            or not isinstance(raw_bodies, Sequence)
        ):
            raise HuggingFaceSourceIntegrityError("cache inventories must be sequences")
        return cls(
            receipt=HuggingFaceIngestReceipt.from_dict(_mapping(value["receipt"], "receipt")),
            rows=tuple(SolidityCPTRow.from_dict(_mapping(item, "row")) for item in raw_rows),
            bodies=tuple(CachedBodyDescriptor.from_dict(_mapping(item, "body descriptor")) for item in raw_bodies),
            manifest_id=value["manifest_id"],
            schema_version=value["schema_version"],
        )


@dataclass(frozen=True, slots=True)
class HuggingFaceCachePin:
    """Out-of-band roots required to trust a persisted cache entry."""

    manifest_id: str
    receipt_id: str
    verification_receipt_id: str
    source_snapshot_cid: str
    config_cid: str

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            _cid(getattr(self, name), name)
        if self.source_snapshot_cid != PINNED_SOURCE_SNAPSHOT.cid:
            raise HuggingFaceSourceIntegrityError("cache pin source snapshot differs from reviewed pin")

    def to_dict(self) -> dict[str, str]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HuggingFaceCachePin:
        value = _mapping(value, "cache pin")
        _exact_fields(
            value,
            frozenset(
                {
                    "config_cid",
                    "manifest_id",
                    "receipt_id",
                    "source_snapshot_cid",
                    "verification_receipt_id",
                }
            ),
            "cache pin",
        )
        return cls(**value)


@runtime_checkable
class HuggingFaceSourceFetcher(Protocol):
    """Explicitly materialize the exact pinned shard; no default fetch exists."""

    def __call__(
        self,
        snapshot: Any,
        destination: Path,
    ) -> None | str | os.PathLike[str]: ...


class HuggingFaceSourceCache:
    """Exact snapshot cache that re-reads and rehashes every artifact on load."""

    _MANIFEST = "manifest.json"

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        fetcher: HuggingFaceSourceFetcher | None = None,
        limits: HuggingFaceSourceLimits | None = None,
    ) -> None:
        root_path = Path(root).expanduser()
        try:
            root_path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise HuggingFaceSourceIntegrityError("cache root must be a real directory") from exc
        if root_path.is_symlink() or not root_path.is_dir():
            raise HuggingFaceSourceIntegrityError("cache root must be a real directory")
        self.root = root_path.resolve(strict=True)
        self.fetcher = fetcher
        self.limits = limits or HuggingFaceSourceLimits()
        if not isinstance(self.limits, HuggingFaceSourceLimits):
            raise TypeError("limits must be HuggingFaceSourceLimits")

    @property
    def cache_key(self) -> str:
        return PINNED_SOURCE_SNAPSHOT.cid

    @property
    def path(self) -> Path:
        return self.root / self.cache_key

    def store(self, result: HuggingFaceIngestResult) -> HuggingFaceCachePin:
        """Atomically persist an admitted result with separate body files."""

        if not isinstance(result, HuggingFaceIngestResult) or not result.admitted:
            raise HuggingFaceSourceIntegrityError("only an admitted ingest result may be cached")
        if self.path.exists():
            raise HuggingFaceSourceIntegrityError("exact cache entry already exists")
        temporary = Path(tempfile.mkdtemp(prefix=".stage-", dir=self.root))
        try:
            body_root = temporary / "bodies"
            body_root.mkdir()
            descriptors: list[CachedBodyDescriptor] = []
            for body in result.source_bodies:
                relative = f"bodies/{body.content_cid}.sol"
                path = temporary / relative
                path.write_bytes(body.text.encode("utf-8"))
                descriptors.append(
                    CachedBodyDescriptor(
                        path=relative,
                        content_cid=body.content_cid,
                        sha256=body.sha256,
                        byte_length=body.byte_length,
                    )
                )
            assert result.receipt is not None
            manifest = CacheManifest(
                receipt=result.receipt,
                rows=result.rows,
                bodies=tuple(descriptors),
            )
            (temporary / self._MANIFEST).write_bytes(canonical_json_bytes(manifest.to_dict()))
            temporary.replace(self.path)
            return HuggingFaceCachePin(
                manifest_id=manifest.manifest_id,
                receipt_id=result.receipt.receipt_id,
                verification_receipt_id=result.receipt.verification_receipt_id,
                source_snapshot_cid=result.receipt.source_snapshot_cid,
                config_cid=result.receipt.config_cid,
            )
        except Exception:
            if temporary.exists():
                shutil.rmtree(temporary)
            raise

    def load(
        self,
        pin: HuggingFaceCachePin | None = None,
    ) -> HuggingFaceIngestResult:
        """Load exact cached bytes, recursively rehashing every artifact."""

        path = self.path
        if not path.exists():
            raise HuggingFaceSourceCacheMiss("offline exact snapshot cache miss")
        if not isinstance(pin, HuggingFaceCachePin):
            raise HuggingFaceSourceIntegrityError("cache load requires an out-of-band cache pin")
        if path.is_symlink() or not path.is_dir():
            raise HuggingFaceSourceIntegrityError("cache entry must be a real directory")
        root = path.resolve(strict=True)
        manifest_content = _bounded_read(
            _safe_file(root, self._MANIFEST),
            self.limits.max_manifest_bytes,
            "cache manifest",
        )
        manifest = CacheManifest.from_dict(_strict_json_object(manifest_content, "cache manifest"))
        if manifest_content != canonical_json_bytes(manifest.to_dict()):
            raise HuggingFaceSourceIntegrityError("cache manifest is not canonical or has byte drift")
        if (
            manifest.manifest_id != pin.manifest_id
            or manifest.receipt.receipt_id != pin.receipt_id
            or manifest.receipt.verification_receipt_id != pin.verification_receipt_id
            or manifest.receipt.source_snapshot_cid != pin.source_snapshot_cid
            or manifest.receipt.config_cid != pin.config_cid
        ):
            raise HuggingFaceSourceIntegrityError("cache inventory differs from out-of-band pin")
        if any(len(canonical_json_bytes(item.to_dict())) > self.limits.max_row_record_bytes for item in manifest.rows):
            raise HuggingFaceSourceLimitError("cached row record exceeds byte limit")
        bodies: list[SolidityCPTSourceBody] = []
        for descriptor in manifest.bodies:
            content = _bounded_read(
                _safe_file(root, descriptor.path),
                self.limits.max_source_body_bytes,
                descriptor.path,
            )
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise HuggingFaceSourceIntegrityError("cached source body is not UTF-8") from exc
            try:
                body = SolidityCPTSourceBody(
                    text=text,
                    byte_length=descriptor.byte_length,
                    sha256=descriptor.sha256,
                    content_cid=descriptor.content_cid,
                )
            except Exception as exc:
                raise HuggingFaceSourceIntegrityError(
                    f"cached source body identity mismatch: {descriptor.path}"
                ) from exc
            bodies.append(body)
        return HuggingFaceIngestResult(
            admitted=True,
            rows=manifest.rows,
            source_bodies=tuple(bodies),
            receipt=manifest.receipt,
        )

    def materialize(
        self,
        *,
        observation: SourceSnapshotObservation | Mapping[str, Any],
        ingestor: HuggingFaceSnapshotIngestor | None = None,
        pin: HuggingFaceCachePin | None = None,
    ) -> tuple[HuggingFaceIngestResult, HuggingFaceCachePin]:
        """Load exact cache or invoke an explicit fetcher into an isolated stage."""

        if self.path.exists():
            if not isinstance(pin, HuggingFaceCachePin):
                raise HuggingFaceSourceIntegrityError("cached materialization requires an out-of-band cache pin")
            return self.load(pin), pin
        if self.fetcher is None:
            raise HuggingFaceSourceCacheMiss("offline exact snapshot cache miss")
        active_ingestor = ingestor or HuggingFaceSnapshotIngestor(limits=self.limits)
        stage = Path(tempfile.mkdtemp(prefix=".fetch-", dir=self.root))
        try:
            returned = self.fetcher(PINNED_SOURCE_SNAPSHOT, stage)
            source = Path(returned).expanduser().resolve(strict=True) if returned is not None else stage
            if source.is_symlink():
                raise HuggingFaceSourceIntegrityError("fetcher returned a symlink")
            shard_path = source / PINNED_SOURCE_SHARD.path
            result = active_ingestor.ingest_local_parquet(shard_path, observation)
            if not result.admitted:
                raise HuggingFaceSourceIntegrityError("fetched snapshot failed atomic admission")
            stored_pin = self.store(result)
            return result, stored_pin
        finally:
            if stage.exists():
                shutil.rmtree(stage)


def ingest_huggingface_rows(
    observation: SourceSnapshotObservation | Mapping[str, Any],
    rows: Iterable[Mapping[str, Any]],
    *,
    shard_content: bytes | bytearray | memoryview,
    row_bounds: SolidityCPTRowBounds = DEFAULT_ROW_BOUNDS,
    limits: HuggingFaceSourceLimits | None = None,
) -> HuggingFaceIngestResult:
    """Convenience wrapper for atomic injected streaming intake."""

    return HuggingFaceSnapshotIngestor(
        row_bounds=row_bounds,
        limits=limits,
    ).ingest_rows(observation, rows, shard_content=shard_content)


HFSourceCache = HuggingFaceSourceCache
HFSourceLimits = HuggingFaceSourceLimits
HFSourceIngestor = HuggingFaceSnapshotIngestor


__all__ = [
    "CacheManifest",
    "CachedBodyDescriptor",
    "HF_CACHE_SCHEMA_VERSION",
    "HF_INGEST_RECEIPT_SCHEMA_VERSION",
    "HF_SOURCE_SCHEMA_VERSION",
    "HFSourceCache",
    "HFSourceIngestor",
    "HFSourceLimits",
    "HuggingFaceCachePin",
    "HuggingFaceIngestReceipt",
    "HuggingFaceIngestResult",
    "HuggingFaceSnapshotIngestor",
    "HuggingFaceSourceCache",
    "HuggingFaceSourceCacheMiss",
    "HuggingFaceSourceError",
    "HuggingFaceSourceFetcher",
    "HuggingFaceSourceIntegrityError",
    "HuggingFaceSourceLimitError",
    "HuggingFaceSourceLimits",
    "ingest_huggingface_rows",
]
