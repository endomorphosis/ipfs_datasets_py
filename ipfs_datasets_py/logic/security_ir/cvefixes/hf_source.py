"""Pinned, fail-closed reader for the CVEfixes Security IR Hub release.

The release builder in :mod:`.hf_release` creates deterministic artifacts, but
an immutable Hub revision is still an untrusted transport boundary.  This
module binds a repository revision to a pinned manifest digest, verifies every
manifest artifact and Parquet row, reconstructs the canonical derived dataset,
and only then exposes bounded candidate lookup and Security IR adaptation.

No network access occurs unless a caller explicitly supplies a fetcher to
``HuggingFaceSourceCache``.  Cache entries retain the complete repository,
revision, manifest, and release-root pin and are reverified on every use.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from typing import Any, Final, Protocol, runtime_checkable

from ...ir_core.canonical import canonical_json_bytes
from .adapter import (
    CVEfixesAdapterResult,
    CandidateReview,
    CandidateReviewState,
    adapt_cvefixes_candidate,
)
from .hf_release import (
    DEFAULT_HF_DATASET_ID,
    HF_META_SCHEMA_VERSION,
    HF_PARQUET_SCHEMA_VERSION,
    HF_RELEASE_SCHEMA_VERSION,
    ReleaseArtifact,
)
from .schemas import (
    CanonicalDerivedRecord,
    DerivedDataset,
    PolicyCandidate,
    ReleaseManifest,
    SourceRecord,
    record_from_dict,
)


HF_SOURCE_SCHEMA_VERSION: Final = "cvefixes-huggingface-source/v1"
HF_SOURCE_CACHE_SCHEMA_VERSION: Final = "cvefixes-huggingface-source-cache/v1"

_DATASET_ID_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}/"
    r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}$"
)
_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CID_RE = re.compile(r"^b[a-z2-7]{58}$")
_MUTABLE_REVISIONS: Final = frozenset(
    {"head", "latest", "main", "master", "refs/heads/main", "refs/heads/master"}
)
_PARQUET_COLUMNS: Final = (
    "record_id",
    "record_type",
    "authority",
    "source_cids",
    "parent_cids",
    "config_cid",
    "record_json",
)
_META_COLUMNS: Final = (
    "cid",
    "end_document_index",
    "first_key",
    "kind",
    "last_key",
    "relative_path",
    "row_count",
    "schema_version",
    "sha256",
    "shard_id",
    "size_bytes",
    "start_document_index",
)
_META_INDEX_NAMES: Final = frozenset(
    {"corpus_chunks", "graph_edge_chunks", "graph_node_chunks"}
)
_MANIFEST_FIELDS: Final = frozenset(
    {
        "artifacts",
        "dataset_id",
        "derived_dataset_root",
        "release_manifest",
        "release_root",
        "schema_version",
        "source",
    }
)
_DESCRIPTOR_FIELDS: Final = frozenset(
    {"byte_length", "content_id", "media_type", "path", "sha256"}
)
_PARQUET_DESCRIPTOR_FIELDS: Final = _DESCRIPTOR_FIELDS | {
    "config_name",
    "row_count",
}
_AUTHORITY_KEYS: Final = frozenset(
    {
        "authoritative",
        "authoritative_policy",
        "grants_authority",
        "grants_execution_authority",
        "permits_execution",
        "proof_authoritative",
    }
)


class HuggingFaceSourceError(ValueError):
    """Base error for invalid pins, snapshots, or source queries."""


class HuggingFaceSourcePinError(HuggingFaceSourceError):
    """Raised when a source is not bound to an immutable exact revision."""


class HuggingFaceSourceIntegrityError(HuggingFaceSourceError):
    """Raised when manifest, artifact, shard, or row evidence does not verify."""


class HuggingFaceSourceLimitError(HuggingFaceSourceError):
    """Raised when a source or lookup exceeds an explicit resource bound."""


class HuggingFaceSourceCacheMiss(HuggingFaceSourceError):
    """Raised when an offline cache lacks the exact requested revision."""


def _positive_int(value: Any, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise HuggingFaceSourceLimitError(f"{label} must be a positive integer")
    return value


def _strict_json_object(content: bytes, label: str) -> Mapping[str, Any]:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise HuggingFaceSourceIntegrityError(
                    f"{label} contains duplicate key {key!r}"
                )
            result[key] = value
        return result

    def reject_constant(value: str) -> Any:
        raise HuggingFaceSourceIntegrityError(
            f"{label} contains non-finite number {value}"
        )

    try:
        value = json.loads(
            content,
            object_pairs_hook=object_pairs,
            parse_constant=reject_constant,
        )
    except HuggingFaceSourceIntegrityError:
        raise
    except (UnicodeError, ValueError, TypeError) as exc:
        raise HuggingFaceSourceIntegrityError(
            f"{label} is not strict UTF-8 JSON"
        ) from exc
    if not isinstance(value, Mapping):
        raise HuggingFaceSourceIntegrityError(f"{label} must contain an object")
    return value


def _artifact_path(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise HuggingFaceSourceIntegrityError(
            "artifact path must be normalized root-relative POSIX text"
        )
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise HuggingFaceSourceIntegrityError(
            "artifact path must not escape the snapshot"
        )
    return value


def _safe_file(root: Path, relative_path: str) -> Path:
    path = root.joinpath(*PurePosixPath(_artifact_path(relative_path)).parts)
    if path.is_symlink() or not path.is_file():
        raise HuggingFaceSourceIntegrityError(
            f"required artifact is missing or not a regular file: {relative_path}"
        )
    try:
        path.resolve(strict=True).relative_to(root)
    except (OSError, ValueError) as exc:
        raise HuggingFaceSourceIntegrityError(
            f"artifact escapes snapshot root: {relative_path}"
        ) from exc
    return path


def _read_bounded(path: Path, maximum: int, label: str) -> bytes:
    size = path.stat().st_size
    if size > maximum:
        raise HuggingFaceSourceLimitError(f"{label} exceeds byte limit")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise HuggingFaceSourceIntegrityError(f"cannot read {label}") from exc


def _assert_candidate_has_no_authority(
    value: Any, *, location: str = "candidate"
) -> None:
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key)
            folded = key.casefold()
            child = f"{location}.{key}"
            if folded in _AUTHORITY_KEYS and item not in (False, None, ""):
                raise HuggingFaceSourceIntegrityError(
                    f"{child} cannot grant candidate authority"
                )
            if folded == "authority" and isinstance(item, str) and (
                item.casefold() not in {"candidate", "non_authoritative"}
            ):
                raise HuggingFaceSourceIntegrityError(
                    f"{child} cannot broaden candidate authority"
                )
            _assert_candidate_has_no_authority(item, location=child)
    elif isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        for index, item in enumerate(value):
            _assert_candidate_has_no_authority(
                item, location=f"{location}[{index}]"
            )


@dataclass(frozen=True, slots=True)
class HuggingFaceSourcePin:
    """Exact public identity required before a Hub release may be read."""

    revision: str
    manifest_sha256: str
    release_root: str
    dataset_id: str = DEFAULT_HF_DATASET_ID
    schema_version: str = HF_SOURCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.dataset_id, str) or not _DATASET_ID_RE.fullmatch(
            self.dataset_id
        ):
            raise HuggingFaceSourcePinError("dataset_id must be exact owner/name")
        if not isinstance(self.revision, str):
            raise HuggingFaceSourcePinError(
                "revision must be an immutable lowercase commit hash"
            )
        folded = self.revision.casefold()
        if (
            folded in _MUTABLE_REVISIONS
            or folded.startswith("refs/heads/")
            or not _REVISION_RE.fullmatch(self.revision)
        ):
            raise HuggingFaceSourcePinError(
                "revision must be an immutable lowercase 40-hex commit hash"
            )
        if not isinstance(self.manifest_sha256, str) or not _SHA256_RE.fullmatch(
            self.manifest_sha256
        ):
            raise HuggingFaceSourcePinError(
                "manifest_sha256 must be lowercase SHA-256"
            )
        if not isinstance(self.release_root, str) or not _CID_RE.fullmatch(
            self.release_root
        ):
            raise HuggingFaceSourcePinError("release_root must be a CIDv1 string")
        if self.schema_version != HF_SOURCE_SCHEMA_VERSION:
            raise HuggingFaceSourcePinError("unsupported source pin schema")

    @property
    def logical_source(self) -> str:
        return f"hf://datasets/{self.dataset_id}@{self.revision}"

    @property
    def cache_key(self) -> str:
        return hashlib.sha256(canonical_json_bytes(self.to_dict())).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "manifest_sha256": self.manifest_sha256,
            "release_root": self.release_root,
            "revision": self.revision,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HuggingFaceSourcePin":
        if not isinstance(value, Mapping):
            raise HuggingFaceSourcePinError("source pin must be a mapping")
        expected = {
            "dataset_id",
            "manifest_sha256",
            "release_root",
            "revision",
            "schema_version",
        }
        if set(value) != expected:
            raise HuggingFaceSourcePinError(
                "source pin has unknown or missing fields"
            )
        return cls(
            dataset_id=value["dataset_id"],
            revision=value["revision"],
            manifest_sha256=value["manifest_sha256"],
            release_root=value["release_root"],
            schema_version=value["schema_version"],
        )


@dataclass(frozen=True, slots=True)
class HuggingFaceSourceLimits:
    """Hard upper bounds for snapshot validation and policy access."""

    max_manifest_bytes: int = 4 * 1024 * 1024
    max_artifacts: int = 512
    max_shards: int = 128
    max_shard_bytes: int = 64 * 1024 * 1024
    max_rows: int = 250_000
    max_results: int = 25

    def __post_init__(self) -> None:
        for name in (
            "max_manifest_bytes",
            "max_artifacts",
            "max_shards",
            "max_shard_bytes",
            "max_rows",
            "max_results",
        ):
            _positive_int(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class PolicyLookup:
    """Exact filters over verified policy candidates."""

    text: str = ""
    effect: str = ""
    cve_id: str = ""
    cwe_id: str = ""
    language: str = ""
    max_results: int | None = None

    def __post_init__(self) -> None:
        for name in ("text", "effect", "cve_id", "cwe_id", "language"):
            value = getattr(self, name)
            if not isinstance(value, str) or "\x00" in value:
                raise HuggingFaceSourceError(f"{name} must be text")
            if len(value) > 4096:
                raise HuggingFaceSourceLimitError(f"{name} is too long")
        if not any(
            (self.text, self.effect, self.cve_id, self.cwe_id, self.language)
        ):
            raise HuggingFaceSourceError("policy lookup must not be empty")
        if self.max_results is not None:
            _positive_int(self.max_results, "max_results")


@dataclass(frozen=True, slots=True)
class PolicyLookupResponse:
    """Bounded candidates; this response is evidence, never authority."""

    candidates: tuple[PolicyCandidate, ...]
    candidates_scanned: int
    truncated: bool
    release_root: str
    revision: str
    grants_execution_authority: bool = False

    def __post_init__(self) -> None:
        if self.grants_execution_authority is not False:
            raise HuggingFaceSourceIntegrityError(
                "policy lookup cannot grant execution authority"
            )


@dataclass(frozen=True, slots=True)
class HuggingFaceSourceReceipt:
    """Side-effect-free verification summary for one exact source."""

    dataset_id: str
    revision: str
    manifest_sha256: str
    release_root: str
    artifact_count: int
    shard_count: int
    row_count: int
    record_count: int
    offline: bool
    verified: bool = True
    grants_execution_authority: bool = False

    def __post_init__(self) -> None:
        if self.verified is not True:
            raise HuggingFaceSourceIntegrityError(
                "source receipt must represent completed verification"
            )
        if self.grants_execution_authority is not False:
            raise HuggingFaceSourceIntegrityError(
                "source verification cannot grant execution authority"
            )


@dataclass(frozen=True, slots=True)
class LoadedHuggingFaceSecurityIR:
    """Verified canonical records and bounded, non-authoritative accessors."""

    pin: HuggingFaceSourcePin
    records: tuple[CanonicalDerivedRecord, ...]
    receipt: HuggingFaceSourceReceipt

    def __post_init__(self) -> None:
        if not isinstance(self.pin, HuggingFaceSourcePin):
            raise TypeError("pin must be a HuggingFaceSourcePin")
        if not isinstance(self.receipt, HuggingFaceSourceReceipt):
            raise TypeError("receipt must be a HuggingFaceSourceReceipt")
        if (
            self.receipt.dataset_id != self.pin.dataset_id
            or self.receipt.revision != self.pin.revision
            or self.receipt.manifest_sha256 != self.pin.manifest_sha256
            or self.receipt.release_root != self.pin.release_root
        ):
            raise HuggingFaceSourceIntegrityError(
                "loaded source receipt does not preserve pin identity"
            )

    @property
    def dataset(self) -> DerivedDataset:
        return DerivedDataset(records=self.records)

    @property
    def candidates(self) -> tuple[PolicyCandidate, ...]:
        return tuple(
            record
            for record in self.records
            if isinstance(record, PolicyCandidate)
        )

    @property
    def source_records(self) -> tuple[SourceRecord, ...]:
        return tuple(
            record for record in self.records if isinstance(record, SourceRecord)
        )

    def lookup_policies(
        self,
        query: PolicyLookup,
        *,
        limits: HuggingFaceSourceLimits | None = None,
    ) -> PolicyLookupResponse:
        if not isinstance(query, PolicyLookup):
            raise TypeError("query must be a PolicyLookup")
        active_limits = limits or HuggingFaceSourceLimits()
        if not isinstance(active_limits, HuggingFaceSourceLimits):
            raise TypeError("limits must be HuggingFaceSourceLimits")
        maximum = min(
            query.max_results or active_limits.max_results,
            active_limits.max_results,
        )
        results: list[PolicyCandidate] = []
        scanned = 0
        truncated = False
        terms = tuple(query.text.casefold().split())
        for candidate in self.candidates:
            scanned += 1
            wire = candidate.to_dict()
            haystack = canonical_json_bytes(wire).decode("utf-8").casefold()
            if terms and not all(term in haystack for term in terms):
                continue
            if query.effect and candidate.effect != query.effect:
                continue
            if query.cve_id and query.cve_id.casefold() not in haystack:
                continue
            if query.cwe_id and query.cwe_id.casefold() not in haystack:
                continue
            if query.language and query.language.casefold() not in haystack:
                continue
            if len(results) >= maximum:
                truncated = True
                continue
            results.append(candidate)
        return PolicyLookupResponse(
            candidates=tuple(results),
            candidates_scanned=scanned,
            truncated=truncated,
            release_root=self.pin.release_root,
            revision=self.pin.revision,
        )

    def security_ir_declarations(
        self,
        query: PolicyLookup,
        *,
        review: CandidateReview | None = None,
        limits: HuggingFaceSourceLimits | None = None,
    ) -> tuple[CVEfixesAdapterResult, ...]:
        """Adapt matching candidates while preserving candidate authority."""

        active_review = review or CandidateReview(
            CandidateReviewState.OBSERVED_CANDIDATE
        )
        if not isinstance(active_review, CandidateReview):
            raise TypeError("review must be a CandidateReview")
        response = self.lookup_policies(query, limits=limits)
        sources = self.source_records
        results: list[CVEfixesAdapterResult] = []
        for candidate in response.candidates:
            covered = tuple(
                source
                for source in sources
                if set(candidate.source_cids)
                & ({source.cid} | set(source.source_cids))
            )
            if not covered:
                raise HuggingFaceSourceIntegrityError(
                    f"candidate {candidate.cid} has no verified source record"
                )
            try:
                result = adapt_cvefixes_candidate(
                    candidate,
                    sources=covered,
                    review=active_review,
                )
            except Exception as exc:
                raise HuggingFaceSourceIntegrityError(
                    f"candidate {candidate.cid} cannot form canonical Security IR"
                ) from exc
            if result.grants_execution_authority is not False:
                raise HuggingFaceSourceIntegrityError(
                    "candidate adaptation attempted to grant authority"
                )
            results.append(result)
        return tuple(results)


def _parquet_rows(
    artifact: ReleaseArtifact,
    *,
    limits: HuggingFaceSourceLimits,
) -> tuple[Mapping[str, Any], ...]:
    if len(artifact.content) > limits.max_shard_bytes:
        raise HuggingFaceSourceLimitError(
            f"Parquet shard exceeds byte limit: {artifact.path}"
        )
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - project test extra
        raise HuggingFaceSourceError(
            "pyarrow is required to verify Hugging Face source shards"
        ) from exc
    try:
        table = pq.read_table(io.BytesIO(artifact.content))
    except Exception as exc:
        raise HuggingFaceSourceIntegrityError(
            f"cannot read Parquet shard {artifact.path}"
        ) from exc
    if tuple(table.schema.names) != _PARQUET_COLUMNS:
        raise HuggingFaceSourceIntegrityError(
            f"unknown Parquet schema in {artifact.path}"
        )
    metadata = table.schema.metadata or {}
    if metadata.get(b"cvefixes_schema_version") != HF_PARQUET_SCHEMA_VERSION.encode(
        "ascii"
    ):
        raise HuggingFaceSourceIntegrityError(
            f"unknown Parquet schema version in {artifact.path}"
        )
    return tuple(table.to_pylist())


def _meta_rows(
    artifact: ReleaseArtifact,
    *,
    limits: HuggingFaceSourceLimits,
) -> tuple[Mapping[str, Any], ...]:
    if len(artifact.content) > limits.max_shard_bytes:
        raise HuggingFaceSourceLimitError(
            f"meta-index exceeds shard byte limit: {artifact.path}"
        )
    try:
        import pyarrow.parquet as pq

        table = pq.read_table(io.BytesIO(artifact.content))
    except Exception as exc:
        raise HuggingFaceSourceIntegrityError(
            f"cannot decode meta-index: {artifact.path}"
        ) from exc
    if tuple(table.schema.names) != _META_COLUMNS:
        raise HuggingFaceSourceIntegrityError(
            f"unknown meta-index schema in {artifact.path}"
        )
    metadata = table.schema.metadata or {}
    if metadata.get(b"schema_version") != HF_META_SCHEMA_VERSION.encode("ascii"):
        raise HuggingFaceSourceIntegrityError(
            f"unknown meta-index schema version in {artifact.path}"
        )
    return tuple(table.to_pylist())


def _verify_meta_indexes(
    indexes: Sequence[ReleaseArtifact],
    shards: Sequence[ReleaseArtifact],
    *,
    limits: HuggingFaceSourceLimits,
) -> None:
    if not indexes:
        return
    data = {item.path: item for item in shards}
    covered: set[str] = set()
    for index in sorted(indexes, key=lambda item: item.path):
        rows = _meta_rows(index, limits=limits)
        if len(rows) != index.row_count:
            raise HuggingFaceSourceIntegrityError(
                "meta-index row count does not match descriptor"
            )
        document_index = 0
        for shard_id, row in enumerate(rows):
            relative_path = row.get("relative_path")
            shard = data.get(relative_path)
            if shard is None or relative_path in covered:
                raise HuggingFaceSourceIntegrityError(
                    "meta-index must point to one unique data shard"
                )
            end_document_index = document_index + shard.row_count - 1
            if (
                row.get("cid") != shard.content_id
                or row.get("sha256") != shard.sha256
                or row.get("size_bytes") != len(shard.content)
                or row.get("row_count") != shard.row_count
                or row.get("kind") != shard.config_name
                or row.get("schema_version") != HF_META_SCHEMA_VERSION
                or row.get("shard_id") != shard_id
                or row.get("start_document_index") != document_index
                or row.get("end_document_index") != end_document_index
            ):
                raise HuggingFaceSourceIntegrityError(
                    "meta-index shard binding mismatch"
                )
            covered.add(relative_path)
            document_index = end_document_index + 1
    if covered != set(data):
        raise HuggingFaceSourceIntegrityError(
            "meta-index pointers do not cover data shards exactly"
        )


def _verified_artifacts(
    root: Path,
    descriptors: Any,
    *,
    limits: HuggingFaceSourceLimits,
) -> tuple[ReleaseArtifact, ...]:
    if isinstance(descriptors, (str, bytes, bytearray)) or not isinstance(
        descriptors, Sequence
    ):
        raise HuggingFaceSourceIntegrityError(
            "manifest artifacts must be a sequence"
        )
    if not descriptors or len(descriptors) > limits.max_artifacts:
        raise HuggingFaceSourceLimitError(
            "manifest artifact inventory is empty or exceeds limit"
        )
    artifacts: list[ReleaseArtifact] = []
    paths: set[str] = set()
    for raw in descriptors:
        if not isinstance(raw, Mapping):
            raise HuggingFaceSourceIntegrityError(
                "artifact descriptor must be an object"
            )
        is_parquet = str(raw.get("path", "")).endswith(".parquet")
        expected_fields = (
            _PARQUET_DESCRIPTOR_FIELDS if is_parquet else _DESCRIPTOR_FIELDS
        )
        if set(raw) != expected_fields:
            raise HuggingFaceSourceIntegrityError(
                "artifact descriptor has unknown or missing fields"
            )
        path = _artifact_path(raw["path"])
        if path == "manifest.json" or path in paths:
            raise HuggingFaceSourceIntegrityError(
                "artifact paths must be unique and exclude manifest.json"
            )
        paths.add(path)
        file_path = _safe_file(root, path)
        declared_size = raw["byte_length"]
        if type(declared_size) is not int or declared_size < 0:
            raise HuggingFaceSourceIntegrityError(
                "artifact byte_length must be non-negative"
            )
        byte_limit = (
            limits.max_shard_bytes
            if is_parquet
            else limits.max_manifest_bytes
        )
        content = _read_bounded(file_path, byte_limit, path)
        try:
            artifact = ReleaseArtifact(
                path=path,
                media_type=raw["media_type"],
                content=content,
                config_name=raw.get("config_name", ""),
                row_count=raw.get("row_count", 0),
                sha256=raw["sha256"],
                content_id=raw["content_id"],
            )
        except Exception as exc:
            raise HuggingFaceSourceIntegrityError(
                f"artifact identity mismatch: {path}"
            ) from exc
        if artifact.descriptor() != dict(raw):
            raise HuggingFaceSourceIntegrityError(
                f"artifact descriptor mismatch: {path}"
            )
        artifacts.append(artifact)
    return tuple(artifacts)


def load_huggingface_security_ir(
    root: str | os.PathLike[str],
    pin: HuggingFaceSourcePin,
    *,
    limits: HuggingFaceSourceLimits | None = None,
    offline: bool = True,
) -> LoadedHuggingFaceSecurityIR:
    """Load and fully verify one exact local Hub snapshot."""

    if not isinstance(pin, HuggingFaceSourcePin):
        raise TypeError("pin must be a HuggingFaceSourcePin")
    active_limits = limits or HuggingFaceSourceLimits()
    if not isinstance(active_limits, HuggingFaceSourceLimits):
        raise TypeError("limits must be HuggingFaceSourceLimits")
    if type(offline) is not bool:
        raise TypeError("offline must be boolean")
    snapshot_root = Path(root).expanduser()
    if snapshot_root.is_symlink() or not snapshot_root.is_dir():
        raise HuggingFaceSourceIntegrityError(
            "snapshot root must be a real directory"
        )
    snapshot_root = snapshot_root.resolve(strict=True)
    manifest_path = _safe_file(snapshot_root, "manifest.json")
    manifest_content = _read_bounded(
        manifest_path, active_limits.max_manifest_bytes, "manifest.json"
    )
    manifest_digest = hashlib.sha256(manifest_content).hexdigest()
    if manifest_digest != pin.manifest_sha256:
        raise HuggingFaceSourceIntegrityError("pinned manifest digest mismatch")
    manifest = _strict_json_object(manifest_content, "manifest.json")
    if frozenset(manifest) not in {
        _MANIFEST_FIELDS,
        _MANIFEST_FIELDS | {"indexes"},
    }:
        raise HuggingFaceSourceIntegrityError(
            "manifest has unknown or missing fields"
        )
    if manifest["schema_version"] != HF_RELEASE_SCHEMA_VERSION:
        raise HuggingFaceSourceIntegrityError("unknown release schema")
    if manifest["dataset_id"] != pin.dataset_id:
        raise HuggingFaceSourceIntegrityError("manifest dataset_id mismatch")
    if manifest["release_root"] != pin.release_root:
        raise HuggingFaceSourceIntegrityError("manifest release_root mismatch")

    artifacts = _verified_artifacts(
        snapshot_root, manifest["artifacts"], limits=active_limits
    )
    artifact_paths = {item.path for item in artifacts}
    required_paths = {
        "README.md",
        "dataset_infos.json",
        "evaluation-report.json",
    }
    if not required_paths <= artifact_paths:
        raise HuggingFaceSourceIntegrityError(
            "release is missing required public artifacts"
        )
    all_shards = tuple(
        item for item in artifacts if item.path.endswith(".parquet")
    )
    shards = tuple(
        item for item in all_shards if item.path.startswith("data/")
    )
    indexes = tuple(
        item for item in all_shards if item.path.startswith("indexes/")
    )
    if not shards:
        raise HuggingFaceSourceIntegrityError("release has no Parquet shards")
    if len(all_shards) > active_limits.max_shards:
        raise HuggingFaceSourceLimitError("release exceeds shard limit")
    data_root = snapshot_root / "data"
    if data_root.is_symlink() or not data_root.is_dir():
        raise HuggingFaceSourceIntegrityError(
            "release data path must be a real directory"
        )
    observed_shards = {
        path.relative_to(snapshot_root).as_posix()
        for path in data_root.rglob("*.parquet")
        if path.is_file()
    }
    if observed_shards != {item.path for item in shards}:
        raise HuggingFaceSourceIntegrityError(
            "manifest Parquet inventory does not match snapshot shards"
        )
    index_root = snapshot_root / "indexes"
    observed_indexes = (
        {
            path.relative_to(snapshot_root).as_posix()
            for path in index_root.glob("*.parquet")
            if path.is_file()
        }
        if index_root.is_dir() and not index_root.is_symlink()
        else set()
    )
    if observed_indexes != {item.path for item in indexes}:
        raise HuggingFaceSourceIntegrityError(
            "manifest meta-index inventory does not match snapshot indexes"
        )
    manifest_indexes = manifest.get("indexes", {})
    expected_indexes = {
        PurePosixPath(item.path).stem: item.descriptor() for item in indexes
    }
    if (
        not set(expected_indexes) <= _META_INDEX_NAMES
        or not isinstance(manifest_indexes, Mapping)
        or dict(manifest_indexes) != expected_indexes
    ):
        raise HuggingFaceSourceIntegrityError(
            "manifest meta-index descriptor binding mismatch"
        )

    try:
        release_manifest = ReleaseManifest.from_dict(
            manifest["release_manifest"]
        )
    except Exception as exc:
        raise HuggingFaceSourceIntegrityError(
            "canonical release manifest is invalid"
        ) from exc
    if (
        release_manifest.dataset_id != pin.dataset_id
        or release_manifest.payload.get("release_root") != pin.release_root
        or release_manifest.payload.get("release_schema_version")
        != HF_RELEASE_SCHEMA_VERSION
    ):
        raise HuggingFaceSourceIntegrityError(
            "release manifest identity does not match source pin"
        )

    records: list[CanonicalDerivedRecord] = []
    row_ids: set[str] = set()
    rows = 0
    for shard in shards:
        shard_rows = _parquet_rows(shard, limits=active_limits)
        if len(shard_rows) != shard.row_count:
            raise HuggingFaceSourceIntegrityError(
                f"Parquet row count mismatch: {shard.path}"
            )
        for row in shard_rows:
            rows += 1
            if rows > active_limits.max_rows:
                raise HuggingFaceSourceLimitError("release exceeds row limit")
            if not isinstance(row, Mapping) or set(row) != set(_PARQUET_COLUMNS):
                raise HuggingFaceSourceIntegrityError(
                    f"Parquet row shape mismatch: {shard.path}"
                )
            try:
                wire_bytes = row["record_json"].encode("utf-8")
                wire = _strict_json_object(wire_bytes, "record_json")
                record = record_from_dict(wire)
            except HuggingFaceSourceIntegrityError:
                raise
            except Exception as exc:
                raise HuggingFaceSourceIntegrityError(
                    f"invalid canonical row in {shard.path}"
                ) from exc
            if (
                record.RECORD_TYPE != shard.config_name
                or row["record_type"] != shard.config_name
                or row["record_id"] != record.record_id
                or row["authority"] != record.authority.value
                or row["source_cids"] != list(record.source_cids)
                or row["parent_cids"] != list(record.parent_cids)
                or row["config_cid"] != record.config_cid
                or canonical_json_bytes(wire).decode("utf-8")
                != row["record_json"]
            ):
                raise HuggingFaceSourceIntegrityError(
                    f"Parquet row identity mismatch: {shard.path}"
                )
            if record.record_id in row_ids:
                raise HuggingFaceSourceIntegrityError(
                    "duplicate canonical row identity"
                )
            if isinstance(record, PolicyCandidate):
                _assert_candidate_has_no_authority(record.scope)
                _assert_candidate_has_no_authority(record.payload)
            row_ids.add(record.record_id)
            records.append(record)

    if row_ids != set(release_manifest.record_cids):
        raise HuggingFaceSourceIntegrityError(
            "manifest record inventory does not match verified rows"
        )
    if {item.content_id for item in shards} != set(
        release_manifest.shard_cids
    ):
        raise HuggingFaceSourceIntegrityError(
            "manifest shard inventory does not match verified artifacts"
        )
    _verify_meta_indexes(indexes, shards, limits=active_limits)
    dataset = DerivedDataset(records=tuple(records))
    if (
        dataset.cid != manifest["derived_dataset_root"]
        or release_manifest.parent_cids != (dataset.cid,)
    ):
        raise HuggingFaceSourceIntegrityError(
            "derived dataset identity does not match manifest"
        )

    try:
        infos_artifact = next(
            item for item in artifacts if item.path == "dataset_infos.json"
        )
    except StopIteration as exc:
        raise HuggingFaceSourceIntegrityError(
            "release is missing dataset_infos.json"
        ) from exc
    infos = _strict_json_object(infos_artifact.content, "dataset_infos.json")
    if (
        set(infos)
        != {
            "configs",
            "dataset_id",
            "derived_dataset_root",
            "schema_version",
        }
        or infos.get("schema_version") != HF_PARQUET_SCHEMA_VERSION
        or infos.get("dataset_id") != pin.dataset_id
        or infos.get("derived_dataset_root") != dataset.cid
        or not isinstance(infos.get("configs"), Mapping)
        or set(infos["configs"]) != {
            item.config_name for item in all_shards
        }
    ):
        raise HuggingFaceSourceIntegrityError(
            "dataset_infos schema or identity mismatch"
        )
    for config_name, config_value in infos["configs"].items():
        if not isinstance(config_value, Mapping):
            raise HuggingFaceSourceIntegrityError(
                "dataset_infos config must be an object"
            )
        split = config_value.get("splits")
        train = split.get("train") if isinstance(split, Mapping) else None
        config_shards = tuple(
            item for item in all_shards if item.config_name == config_name
        )
        if (
            set(config_value) != {"features", "splits"}
            or not isinstance(config_value.get("features"), Mapping)
            or not isinstance(train, Mapping)
            or set(train) != {"num_bytes", "num_examples"}
            or train["num_bytes"]
            != sum(len(item.content) for item in config_shards)
            or train["num_examples"]
            != sum(item.row_count for item in config_shards)
        ):
            raise HuggingFaceSourceIntegrityError(
                "dataset_infos config counts do not match verified shards"
            )

    receipt = HuggingFaceSourceReceipt(
        dataset_id=pin.dataset_id,
        revision=pin.revision,
        manifest_sha256=pin.manifest_sha256,
        release_root=pin.release_root,
        artifact_count=len(artifacts) + 1,
        shard_count=len(shards),
        row_count=rows,
        record_count=len(records),
        offline=offline,
    )
    return LoadedHuggingFaceSecurityIR(
        pin=pin,
        records=tuple(sorted(records, key=lambda item: item.record_id)),
        receipt=receipt,
    )


@runtime_checkable
class HuggingFaceSourceFetcher(Protocol):
    """Materialize an exact pinned dataset revision at ``destination``."""

    def __call__(
        self, pin: HuggingFaceSourcePin, destination: Path
    ) -> None | str | os.PathLike[str]:
        ...


class HuggingFaceHubSourceFetcher:
    """Explicit opt-in Hugging Face Hub fetcher for immutable revisions."""

    def __init__(self, *, local_files_only: bool = False) -> None:
        self.local_files_only = bool(local_files_only)

    def __call__(
        self, pin: HuggingFaceSourcePin, destination: Path
    ) -> Path:
        try:
            from huggingface_hub import snapshot_download
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise HuggingFaceSourceError(
                "huggingface_hub is required for Hub source fetching"
            ) from exc
        try:
            result = snapshot_download(
                repo_id=pin.dataset_id,
                revision=pin.revision,
                repo_type="dataset",
                local_dir=str(destination),
                local_files_only=self.local_files_only,
            )
        except Exception as exc:  # pragma: no cover - backend/network dependent
            raise HuggingFaceSourceError(
                f"failed to fetch exact source {pin.logical_source}"
            ) from exc
        return Path(result)


class HuggingFaceSourceCache:
    """Revision-preserving, content-verified cache for Hub source snapshots."""

    _MARKER = ".cvefixes-hf-source.json"

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
            raise HuggingFaceSourceIntegrityError(
                "cache root must be a real directory"
            ) from exc
        if root_path.is_symlink() or not root_path.is_dir():
            raise HuggingFaceSourceIntegrityError(
                "cache root must be a real directory"
            )
        self.root = root_path.resolve(strict=True)
        self.fetcher = fetcher
        self.limits = limits or HuggingFaceSourceLimits()
        if not isinstance(self.limits, HuggingFaceSourceLimits):
            raise TypeError("limits must be HuggingFaceSourceLimits")
        self.snapshots = self.root / "snapshots"
        self.snapshots.mkdir(exist_ok=True)
        if self.snapshots.is_symlink() or not self.snapshots.is_dir():
            raise HuggingFaceSourceIntegrityError(
                "cache snapshots path must be a real directory"
            )

    def path_for(self, pin: HuggingFaceSourcePin) -> Path:
        if not isinstance(pin, HuggingFaceSourcePin):
            raise TypeError("pin must be a HuggingFaceSourcePin")
        return self.snapshots / pin.cache_key

    def load(self, pin: HuggingFaceSourcePin) -> LoadedHuggingFaceSecurityIR:
        """Return a reverified offline entry for exactly ``pin``."""

        path = self.path_for(pin)
        if not path.exists():
            raise HuggingFaceSourceCacheMiss(
                f"offline cache miss for {pin.logical_source}"
            )
        self._verify_marker(path, pin)
        return load_huggingface_security_ir(
            path, pin, limits=self.limits, offline=True
        )

    def materialize(
        self, pin: HuggingFaceSourcePin
    ) -> LoadedHuggingFaceSecurityIR:
        """Load an exact cache entry, or fetch, verify, and atomically promote."""

        path = self.path_for(pin)
        if path.exists():
            return self.load(pin)
        if self.fetcher is None:
            raise HuggingFaceSourceCacheMiss(
                f"offline cache miss for {pin.logical_source}"
            )
        temporary = Path(
            tempfile.mkdtemp(prefix=f".{pin.cache_key}.", dir=self.snapshots)
        )
        try:
            returned = self.fetcher(pin, temporary)
            if returned is not None:
                returned_path = Path(returned).expanduser().resolve(strict=True)
                if returned_path != temporary.resolve(strict=True):
                    if returned_path.is_symlink() or not returned_path.is_dir():
                        raise HuggingFaceSourceIntegrityError(
                            "fetcher must return a real snapshot directory"
                        )
                    shutil.copytree(
                        returned_path,
                        temporary,
                        dirs_exist_ok=True,
                        symlinks=False,
                    )
            loaded = load_huggingface_security_ir(
                temporary, pin, limits=self.limits, offline=False
            )
            marker = {
                "pin": pin.to_dict(),
                "schema_version": HF_SOURCE_CACHE_SCHEMA_VERSION,
            }
            (temporary / self._MARKER).write_bytes(canonical_json_bytes(marker))
            try:
                temporary.replace(path)
            except FileExistsError:
                shutil.rmtree(temporary)
                return self.load(pin)
            return loaded
        except Exception:
            if temporary.exists():
                shutil.rmtree(temporary)
            raise

    def _verify_marker(self, path: Path, pin: HuggingFaceSourcePin) -> None:
        if path.is_symlink() or not path.is_dir():
            raise HuggingFaceSourceIntegrityError(
                "cache entry must be a real directory"
            )
        marker_path = _safe_file(path.resolve(strict=True), self._MARKER)
        marker = _strict_json_object(
            _read_bounded(
                marker_path,
                self.limits.max_manifest_bytes,
                "cache identity marker",
            ),
            "cache identity marker",
        )
        if set(marker) != {"pin", "schema_version"} or (
            marker["schema_version"] != HF_SOURCE_CACHE_SCHEMA_VERSION
        ):
            raise HuggingFaceSourceIntegrityError(
                "cache identity marker has unknown schema"
            )
        try:
            cached_pin = HuggingFaceSourcePin.from_dict(marker["pin"])
        except Exception as exc:
            raise HuggingFaceSourceIntegrityError(
                "cache identity marker contains an invalid pin"
            ) from exc
        if cached_pin != pin:
            raise HuggingFaceSourceIntegrityError(
                "cache entry revision identity does not match requested pin"
            )


# Compact aliases for call sites that already establish CVEfixes context.
HFSourcePin = HuggingFaceSourcePin
HFSourceLimits = HuggingFaceSourceLimits
HFSourceCache = HuggingFaceSourceCache
load_hf_source = load_huggingface_security_ir


__all__ = [
    "HF_SOURCE_CACHE_SCHEMA_VERSION",
    "HF_SOURCE_SCHEMA_VERSION",
    "HFSourceCache",
    "HFSourceLimits",
    "HFSourcePin",
    "HuggingFaceHubSourceFetcher",
    "HuggingFaceSourceCache",
    "HuggingFaceSourceCacheMiss",
    "HuggingFaceSourceError",
    "HuggingFaceSourceFetcher",
    "HuggingFaceSourceIntegrityError",
    "HuggingFaceSourceLimitError",
    "HuggingFaceSourceLimits",
    "HuggingFaceSourcePin",
    "HuggingFaceSourcePinError",
    "HuggingFaceSourceReceipt",
    "LoadedHuggingFaceSecurityIR",
    "PolicyLookup",
    "PolicyLookupResponse",
    "load_hf_source",
    "load_huggingface_security_ir",
]
