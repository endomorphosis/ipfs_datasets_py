"""Deterministic local Hugging Face release packaging for CVEfixes Security IR.

This module deliberately stops at a validated staging directory.  It does not
authenticate to, mutate, or otherwise contact the Hugging Face Hub.  Publication
is a separate operation which can consume the content-addressed manifest emitted
here.

Records are written to one Hugging Face configuration per canonical record type.
Every Parquet row retains the complete strict schema record as canonical JSON,
while also exposing the identity and lineage columns needed by Dataset Viewer
and inexpensive integrity checks.  Public staging fails closed if a record
contains a full source body, a credential, cache material, or an unsafe path.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
from types import MappingProxyType
from typing import Any, Final

from ...ir_core.canonical import canonical_json_bytes
from ...ir_core.identity import canonical_identity
from .release_policy import (
    CVEFIXES_BODY_FIELDS,
    LicenseProvenance,
    PUBLIC_RELEASE_PROFILE,
    ReleaseVisibility,
)
from .schemas import (
    CVEFIXES_DATASET_SCHEMA_VERSION,
    CanonicalDerivedRecord,
    DerivedDataset,
    EvaluationRecord,
    ReleaseManifest,
    canonical_config_cid,
    record_from_dict,
)


HF_RELEASE_SCHEMA_VERSION: Final = "cvefixes-huggingface-release/v1"
HF_PARQUET_SCHEMA_VERSION: Final = "cvefixes-huggingface-parquet/v1"
HF_QUERY_SCHEMA_VERSION: Final = "cvefixes-huggingface-query/v1"
DEFAULT_HF_DATASET_ID: Final = "sofiyapervane/cvefixes-security-ir-graphrag"
DEFAULT_LIMITATIONS: Final[tuple[str, ...]] = (
    "Derived examples are non-authoritative evidence and cannot grant execution.",
    "Coverage and labels inherit limitations of the pinned CVEfixes source.",
    "Public artifacts contain body digests, not unrestricted source bodies.",
)

_PARQUET_COLUMNS: Final[tuple[str, ...]] = (
    "record_id",
    "record_type",
    "authority",
    "source_cids",
    "parent_cids",
    "config_cid",
    "record_json",
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_CID_RE = re.compile(r"b[a-z2-7]{58}")
_DATASET_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}")
_RECORD_TYPE_RE = re.compile(r"[a-z][a-z0-9_]{0,63}")
_SECRET_VALUE_RE = re.compile(
    r"(?:-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----|"
    r"(?<![A-Za-z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Za-z0-9])|"
    r"(?<![A-Za-z0-9])(?:gh[pousr]_[A-Za-z0-9]{30,255}|"
    r"github_pat_[A-Za-z0-9_]{40,255}|"
    r"hf_[A-Za-z0-9]{20,255}|"
    r"sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,})(?![A-Za-z0-9]))"
)
_CREDENTIAL_KEYS: Final[frozenset[str]] = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "credential",
        "credentials",
        "hf_token",
        "password",
        "private_key",
        "secret",
        "token",
    }
)
_CACHE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "__pycache__",
        "cache",
        "cache_dir",
        "cache_path",
        "cached_file",
        "huggingface_hub_cache",
        "temporary_directory",
        "tmpdir",
    }
)
_CACHE_PATH_PARTS: Final[frozenset[str]] = frozenset(
    {"__pycache__", ".cache", ".git", ".pytest_cache", ".mypy_cache"}
)
_ALLOWED_TOP_LEVEL_FILES: Final[frozenset[str]] = frozenset(
    {"README.md", "dataset_infos.json", "evaluation-report.json", "manifest.json"}
)


class HuggingFaceReleaseError(ValueError):
    """Base error for malformed, unsafe, or non-reproducible releases."""


class ReleaseSafetyError(HuggingFaceReleaseError):
    """Raised when material forbidden from release staging is detected."""


class ReleaseIntegrityError(HuggingFaceReleaseError):
    """Raised when a release artifact does not match its manifest."""


class ReleaseLimitError(HuggingFaceReleaseError):
    """Raised when a release or query exceeds an explicit resource bound."""


def _canonical_json(value: Any) -> bytes:
    try:
        return canonical_json_bytes(value)
    except (TypeError, ValueError) as exc:
        raise HuggingFaceReleaseError(
            "release values must be finite canonical JSON"
        ) from exc


def _clean_text(value: Any, label: str, *, maximum: int = 4096) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
        or len(value) > maximum
    ):
        raise HuggingFaceReleaseError(
            f"{label} must be bounded, non-empty trimmed text"
        )
    return value


def _positive_int(value: Any, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise HuggingFaceReleaseError(f"{label} must be a positive integer")
    return value


def _artifact_path(value: Any) -> str:
    path = _clean_text(value, "artifact path", maximum=512)
    parsed = PurePosixPath(path)
    if (
        parsed.is_absolute()
        or path != parsed.as_posix()
        or any(part in {"", ".", ".."} for part in parsed.parts)
        or any(part.casefold() in _CACHE_PATH_PARTS for part in parsed.parts)
        or "\\" in path
    ):
        raise ReleaseSafetyError(f"unsafe release artifact path: {path!r}")
    if len(parsed.parts) == 1:
        if path not in _ALLOWED_TOP_LEVEL_FILES:
            raise ReleaseSafetyError(f"unexpected top-level artifact: {path!r}")
    elif (
        len(parsed.parts) != 3
        or parsed.parts[0] != "data"
        or not _RECORD_TYPE_RE.fullmatch(parsed.parts[1])
        or not re.fullmatch(
            r"train-\d{5}-of-\d{5}\.parquet", parsed.parts[2]
        )
    ):
        raise ReleaseSafetyError(f"unexpected release artifact path: {path!r}")
    return path


def _content_cid(content: bytes, *, media_type: str) -> str:
    return canonical_identity(
        {
            "byte_length": len(content),
            "media_type": media_type,
            "sha256": hashlib.sha256(content).hexdigest(),
        },
        domain="cvefixes-security-ir/release-artifact",
        schema_version=HF_RELEASE_SCHEMA_VERSION,
    ).cid


def _walk_public_value(value: Any, *, location: str = "$") -> None:
    """Reject forbidden keys and secret values before serialization."""

    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            if not isinstance(raw_key, str):
                raise ReleaseSafetyError(
                    f"non-string mapping key at {location}"
                )
            key = raw_key.casefold()
            child = f"{location}.{raw_key}"
            if key in CVEFIXES_BODY_FIELDS:
                raise ReleaseSafetyError(
                    f"internal body field cannot enter public staging: {child}"
                )
            if key in _CREDENTIAL_KEYS:
                raise ReleaseSafetyError(
                    f"credential field cannot enter staging: {child}"
                )
            if key in _CACHE_KEYS or key.endswith("_cache"):
                raise ReleaseSafetyError(
                    f"cache material cannot enter staging: {child}"
                )
            _walk_public_value(item, location=child)
        return
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        for index, item in enumerate(value):
            _walk_public_value(item, location=f"{location}[{index}]")
        return
    if isinstance(value, str):
        if _SECRET_VALUE_RE.search(value):
            raise ReleaseSafetyError(
                f"secret-like value cannot enter staging: {location}"
            )
        normalized = value.replace("\\", "/")
        parts = {part.casefold() for part in PurePosixPath(normalized).parts}
        if parts & _CACHE_PATH_PARTS:
            raise ReleaseSafetyError(
                f"cache path cannot enter staging: {location}"
            )


@dataclass(frozen=True, slots=True)
class ParquetReleaseConfig:
    """Deterministic Parquet and query resource bounds."""

    max_records: int = 250_000
    max_rows_per_shard: int = 10_000
    max_shards_per_config: int = 128
    max_shard_bytes: int = 64 * 1024 * 1024
    row_group_size: int = 1_024
    compression: str = "zstd"
    schema_version: str = HF_PARQUET_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in (
            "max_records",
            "max_rows_per_shard",
            "max_shards_per_config",
            "max_shard_bytes",
            "row_group_size",
        ):
            _positive_int(getattr(self, name), name)
        if self.max_rows_per_shard > self.max_records:
            raise HuggingFaceReleaseError(
                "max_rows_per_shard cannot exceed max_records"
            )
        if self.row_group_size > self.max_rows_per_shard:
            raise HuggingFaceReleaseError(
                "row_group_size cannot exceed max_rows_per_shard"
            )
        if self.compression not in {"none", "snappy", "gzip", "brotli", "zstd"}:
            raise HuggingFaceReleaseError("unsupported Parquet compression")
        if self.schema_version != HF_PARQUET_SCHEMA_VERSION:
            raise HuggingFaceReleaseError("unsupported Parquet schema version")

    def to_dict(self) -> dict[str, Any]:
        return {
            "compression": self.compression,
            "max_records": self.max_records,
            "max_rows_per_shard": self.max_rows_per_shard,
            "max_shard_bytes": self.max_shard_bytes,
            "max_shards_per_config": self.max_shards_per_config,
            "row_group_size": self.row_group_size,
            "schema_version": self.schema_version,
        }

    @property
    def cid(self) -> str:
        return canonical_config_cid(
            self.to_dict(), schema_version=self.schema_version
        )


@dataclass(frozen=True, slots=True)
class ReleaseArtifact:
    """One immutable staged file and its content identity."""

    path: str
    media_type: str
    content: bytes = field(repr=False)
    config_name: str = ""
    row_count: int = 0
    sha256: str = ""
    content_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _artifact_path(self.path))
        _clean_text(self.media_type, "media_type", maximum=128)
        if not isinstance(self.content, bytes):
            raise HuggingFaceReleaseError("artifact content must be bytes")
        if type(self.row_count) is not int or self.row_count < 0:
            raise HuggingFaceReleaseError("artifact row_count must be non-negative")
        digest = hashlib.sha256(self.content).hexdigest()
        if self.sha256 and self.sha256 != digest:
            raise ReleaseIntegrityError("artifact SHA-256 does not match content")
        content_id = _content_cid(self.content, media_type=self.media_type)
        if self.content_id and self.content_id != content_id:
            raise ReleaseIntegrityError("artifact CID does not match content")
        if self.path.endswith(".parquet"):
            if not _RECORD_TYPE_RE.fullmatch(self.config_name):
                raise HuggingFaceReleaseError(
                    "Parquet artifacts require a valid config_name"
                )
            if self.row_count <= 0:
                raise HuggingFaceReleaseError(
                    "Parquet artifacts require a positive row_count"
                )
        elif self.config_name or self.row_count:
            raise HuggingFaceReleaseError(
                "only Parquet artifacts may declare config_name or rows"
            )
        object.__setattr__(self, "sha256", digest)
        object.__setattr__(self, "content_id", content_id)

    def descriptor(self) -> dict[str, Any]:
        value = {
            "byte_length": len(self.content),
            "content_id": self.content_id,
            "media_type": self.media_type,
            "path": self.path,
            "sha256": self.sha256,
        }
        if self.config_name:
            value["config_name"] = self.config_name
            value["row_count"] = self.row_count
        return value


@dataclass(frozen=True, slots=True)
class HuggingFaceRelease:
    """A complete in-memory local release ready for validation or staging."""

    dataset_id: str
    source_dataset_id: str
    source_revision: str
    license_provenance: LicenseProvenance
    profile: str
    release_root: str
    release_manifest: ReleaseManifest
    artifacts: tuple[ReleaseArtifact, ...]
    parquet_config: ParquetReleaseConfig
    schema_version: str = HF_RELEASE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not _DATASET_ID_RE.fullmatch(self.dataset_id):
            raise HuggingFaceReleaseError("dataset_id must be owner/name")
        _clean_text(self.source_dataset_id, "source_dataset_id", maximum=256)
        _clean_text(self.source_revision, "source_revision", maximum=256)
        if not isinstance(self.license_provenance, LicenseProvenance):
            raise ReleaseIntegrityError("license_provenance is invalid")
        if (
            self.license_provenance.dataset_id != self.source_dataset_id
            or self.license_provenance.source_revision != self.source_revision
            or not self.license_provenance.reviewed_for_release
        ):
            raise ReleaseIntegrityError(
                "release source does not match reviewed license provenance"
            )
        _clean_text(self.profile, "profile", maximum=256)
        if not _CID_RE.fullmatch(self.release_root):
            raise ReleaseIntegrityError("release_root must be a CIDv1 string")
        if not isinstance(self.release_manifest, ReleaseManifest):
            raise ReleaseIntegrityError("release_manifest is invalid")
        if self.schema_version != HF_RELEASE_SCHEMA_VERSION:
            raise ReleaseIntegrityError("unsupported release schema version")
        artifacts = tuple(sorted(self.artifacts, key=lambda item: item.path))
        if not artifacts or len({item.path for item in artifacts}) != len(artifacts):
            raise ReleaseIntegrityError(
                "artifacts must be non-empty with unique paths"
            )
        required = {
            "README.md",
            "dataset_infos.json",
            "evaluation-report.json",
            "manifest.json",
        }
        if not required <= {item.path for item in artifacts}:
            raise ReleaseIntegrityError("release is missing required artifacts")
        object.__setattr__(self, "artifacts", artifacts)

    def artifact(self, path: str) -> ReleaseArtifact:
        for artifact in self.artifacts:
            if artifact.path == path:
                return artifact
        raise KeyError(path)

    @property
    def parquet_artifacts(self) -> tuple[ReleaseArtifact, ...]:
        return tuple(
            item for item in self.artifacts if item.path.endswith(".parquet")
        )


@dataclass(frozen=True, slots=True)
class ReleaseValidation:
    """Side-effect-free result of validating every local artifact."""

    release_root: str
    artifact_count: int
    shard_count: int
    row_count: int
    valid: bool = True
    credentials_required: bool = False


@dataclass(frozen=True, slots=True)
class ReleaseQuery:
    """A text/filter query whose caller-provided limits can only narrow."""

    text: str = ""
    record_types: tuple[str, ...] = ()
    authorities: tuple[str, ...] = ()
    max_shards: int | None = None
    max_rows: int | None = None
    max_results: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or len(self.text) > 4096:
            raise ReleaseLimitError("query text must be at most 4096 characters")
        for name in ("record_types", "authorities"):
            value = getattr(self, name)
            if isinstance(value, (str, bytes, bytearray)) or not isinstance(
                value, Sequence
            ):
                raise HuggingFaceReleaseError(f"{name} must be a sequence")
            normalized = tuple(sorted({_clean_text(item, name) for item in value}))
            if len(normalized) != len(tuple(value)):
                raise HuggingFaceReleaseError(f"{name} must not contain duplicates")
            object.__setattr__(self, name, normalized)
        if not self.text and not self.record_types and not self.authorities:
            raise HuggingFaceReleaseError("release query must not be empty")
        for name in ("max_shards", "max_rows", "max_results"):
            value = getattr(self, name)
            if value is not None:
                _positive_int(value, name)


@dataclass(frozen=True, slots=True)
class ReleaseQueryResponse:
    release_root: str
    results: tuple[Mapping[str, Any], ...]
    shards_scanned: int
    rows_scanned: int
    truncated_shards: bool
    truncated_rows: bool
    truncated_results: bool
    schema_version: str = HF_QUERY_SCHEMA_VERSION
    grants_execution_authority: bool = False

    def __post_init__(self) -> None:
        if self.grants_execution_authority is not False:
            raise HuggingFaceReleaseError(
                "release queries cannot grant execution authority"
            )


def _pyarrow() -> tuple[Any, Any]:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - dependency is in project extras
        raise HuggingFaceReleaseError(
            "pyarrow is required to build or validate a release"
        ) from exc
    return pa, pq


def _parquet_schema() -> Any:
    pa, _ = _pyarrow()
    return pa.schema(
        [
            pa.field("record_id", pa.string(), nullable=False),
            pa.field("record_type", pa.string(), nullable=False),
            pa.field("authority", pa.string(), nullable=False),
            pa.field("source_cids", pa.list_(pa.string()), nullable=False),
            pa.field("parent_cids", pa.list_(pa.string()), nullable=False),
            pa.field("config_cid", pa.string(), nullable=False),
            pa.field("record_json", pa.string(), nullable=False),
        ],
        metadata={
            b"cvefixes_schema_version": HF_PARQUET_SCHEMA_VERSION.encode("ascii")
        },
    )


def _record_row(record: CanonicalDerivedRecord) -> dict[str, Any]:
    value = record.to_dict()
    _walk_public_value(value)
    return {
        "authority": record.authority.value,
        "config_cid": record.config_cid,
        "parent_cids": list(record.parent_cids),
        "record_id": record.record_id,
        "record_json": _canonical_json(value).decode("utf-8"),
        "record_type": record.RECORD_TYPE,
        "source_cids": list(record.source_cids),
    }


def _write_parquet(rows: Sequence[Mapping[str, Any]], config: ParquetReleaseConfig) -> bytes:
    pa, pq = _pyarrow()
    table = pa.Table.from_pylist(list(rows), schema=_parquet_schema())
    output = io.BytesIO()
    pq.write_table(
        table,
        output,
        compression=None if config.compression == "none" else config.compression,
        data_page_version="1.0",
        row_group_size=config.row_group_size,
        use_dictionary=False,
        version="2.6",
        write_statistics=True,
    )
    return output.getvalue()


def _partition_rows(
    rows: tuple[Mapping[str, Any], ...], config: ParquetReleaseConfig
) -> tuple[tuple[Mapping[str, Any], ...], ...]:
    """Split rows deterministically, shrinking chunks that exceed byte bounds."""

    pending = [
        rows[index : index + config.max_rows_per_shard]
        for index in range(0, len(rows), config.max_rows_per_shard)
    ]
    result: list[tuple[Mapping[str, Any], ...]] = []
    while pending:
        chunk = tuple(pending.pop(0))
        content = _write_parquet(chunk, config)
        if len(content) <= config.max_shard_bytes:
            result.append(chunk)
            continue
        if len(chunk) == 1:
            raise ReleaseLimitError(
                "one Parquet row exceeds max_shard_bytes"
            )
        midpoint = len(chunk) // 2
        pending[0:0] = [chunk[:midpoint], chunk[midpoint:]]
    if len(result) > config.max_shards_per_config:
        raise ReleaseLimitError("Parquet config exceeds max_shards_per_config")
    return tuple(result)


def _dataset_infos(
    artifacts: Sequence[ReleaseArtifact],
    *,
    dataset_id: str,
    dataset_root: str,
) -> dict[str, Any]:
    configs: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        if not artifact.config_name:
            continue
        config = configs.setdefault(
            artifact.config_name,
            {
                "features": {
                    "authority": {"dtype": "string"},
                    "config_cid": {"dtype": "string"},
                    "parent_cids": {"feature": {"dtype": "string"}},
                    "record_id": {"dtype": "string"},
                    "record_json": {"dtype": "string"},
                    "record_type": {"dtype": "string"},
                    "source_cids": {"feature": {"dtype": "string"}},
                },
                "splits": {"train": {"num_bytes": 0, "num_examples": 0}},
            },
        )
        config["splits"]["train"]["num_bytes"] += len(artifact.content)
        config["splits"]["train"]["num_examples"] += artifact.row_count
    return {
        "configs": {key: configs[key] for key in sorted(configs)},
        "dataset_id": dataset_id,
        "derived_dataset_root": dataset_root,
        "schema_version": HF_PARQUET_SCHEMA_VERSION,
    }


def _dataset_card(
    *,
    dataset_id: str,
    source: LicenseProvenance,
    profile: str,
    config_names: Sequence[str],
    limitations: Sequence[str],
) -> bytes:
    safe_limitations = tuple(
        _clean_text(item, "limitation", maximum=2048) for item in limitations
    )
    if not safe_limitations:
        raise HuggingFaceReleaseError("dataset card requires limitations")
    card_data = {
        "configs": [{"config_name": item} for item in sorted(config_names)],
        "dataset_info": {"features": []},
        "license": source.license_expression,
        "pretty_name": "CVEfixes Security IR GraphRAG",
        "source_datasets": [source.dataset_id],
    }
    yaml_lines = ["---"]
    yaml_lines.extend(
        (
            f"license: {json.dumps(card_data['license'])}",
            f"pretty_name: {json.dumps(card_data['pretty_name'])}",
            "configs:",
        )
    )
    yaml_lines.extend(
        f"- config_name: {json.dumps(item)}" for item in sorted(config_names)
    )
    yaml_lines.extend(
        (
            "source_datasets:",
            f"- {json.dumps(source.dataset_id)}",
            "---",
            "",
            "# CVEfixes Security IR GraphRAG",
            "",
            "## Source and provenance",
            "",
            f"- Source dataset: `{source.dataset_id}`",
            f"- Pinned source revision: `{source.source_revision}`",
            f"- License expression: `{source.license_expression}`",
            f"- License evidence: {source.evidence_url}",
            f"- Release profile: `{profile}`",
            "",
            "All source text is treated as inert, untrusted data. Derived records "
            "and query results are non-authoritative and cannot grant execution.",
            "",
            "## Dataset configurations",
            "",
        )
    )
    yaml_lines.extend(f"- `{item}`" for item in sorted(config_names))
    yaml_lines.extend(("", "## Limitations", ""))
    yaml_lines.extend(f"- {item}" for item in safe_limitations)
    yaml_lines.extend(
        (
            "",
            "## Evaluation",
            "",
            "Measured gates and their non-authoritative promotion review are in "
            "`evaluation-report.json`.",
            "",
        )
    )
    content = "\n".join(yaml_lines).encode("utf-8")
    _walk_public_value(content.decode("utf-8"), location="$.dataset_card")
    return content


def _evaluation_record(
    dataset: DerivedDataset, evaluation: EvaluationRecord | None
) -> EvaluationRecord:
    candidates = tuple(
        item for item in dataset.records if isinstance(item, EvaluationRecord)
    )
    if evaluation is None:
        if len(candidates) != 1:
            raise HuggingFaceReleaseError(
                "release requires exactly one EvaluationRecord"
            )
        return candidates[0]
    if not isinstance(evaluation, EvaluationRecord):
        raise HuggingFaceReleaseError("evaluation must be an EvaluationRecord")
    if evaluation.record_id not in {item.record_id for item in candidates}:
        raise HuggingFaceReleaseError(
            "evaluation record must be present in the derived dataset"
        )
    return evaluation


def _release_root(
    artifacts: Sequence[ReleaseArtifact],
    *,
    dataset_id: str,
    license_provenance: LicenseProvenance,
    profile: str,
    dataset_root: str,
    config_cid: str,
) -> str:
    return canonical_identity(
        {
            "artifacts": [item.descriptor() for item in sorted(artifacts, key=lambda x: x.path)],
            "config_cid": config_cid,
            "dataset_id": dataset_id,
            "derived_dataset_root": dataset_root,
            "profile": profile,
            "schema_version": HF_RELEASE_SCHEMA_VERSION,
            "source": license_provenance.to_dict(),
        },
        domain="cvefixes-security-ir/huggingface-release",
        schema_version=HF_RELEASE_SCHEMA_VERSION,
    ).cid


def build_huggingface_release(
    dataset: DerivedDataset,
    *,
    license_provenance: LicenseProvenance,
    evaluation: EvaluationRecord | None = None,
    dataset_id: str = DEFAULT_HF_DATASET_ID,
    parquet_config: ParquetReleaseConfig | None = None,
    limitations: Sequence[str] = DEFAULT_LIMITATIONS,
) -> HuggingFaceRelease:
    """Build a deterministic, credential-free, public release in memory."""

    if not isinstance(dataset, DerivedDataset):
        raise HuggingFaceReleaseError("dataset must be a DerivedDataset")
    if not isinstance(license_provenance, LicenseProvenance):
        raise HuggingFaceReleaseError(
            "license_provenance must be LicenseProvenance"
        )
    if not _DATASET_ID_RE.fullmatch(dataset_id):
        raise HuggingFaceReleaseError("dataset_id must be owner/name")
    if not license_provenance.reviewed_for_release:
        raise ReleaseSafetyError(
            "release requires reviewed, redistributable license provenance"
        )
    config = parquet_config or ParquetReleaseConfig()
    if not isinstance(config, ParquetReleaseConfig):
        raise HuggingFaceReleaseError(
            "parquet_config must be ParquetReleaseConfig"
        )
    records = tuple(
        item for item in dataset.records if not isinstance(item, ReleaseManifest)
    )
    if len(records) != len(dataset.records):
        raise HuggingFaceReleaseError(
            "input dataset must not contain a prior release manifest"
        )
    if len(records) > config.max_records:
        raise ReleaseLimitError("dataset exceeds max_records")
    evaluation_record = _evaluation_record(dataset, evaluation)

    grouped: dict[str, list[CanonicalDerivedRecord]] = {}
    for record in records:
        grouped.setdefault(record.RECORD_TYPE, []).append(record)
    artifacts: list[ReleaseArtifact] = []
    for config_name in sorted(grouped):
        ordered = tuple(
            _record_row(item)
            for item in sorted(grouped[config_name], key=lambda item: item.record_id)
        )
        chunks = _partition_rows(ordered, config)
        shard_total = len(chunks)
        for index, chunk in enumerate(chunks):
            content = _write_parquet(chunk, config)
            artifacts.append(
                ReleaseArtifact(
                    path=(
                        f"data/{config_name}/"
                        f"train-{index:05d}-of-{shard_total:05d}.parquet"
                    ),
                    media_type="application/vnd.apache.parquet",
                    content=content,
                    config_name=config_name,
                    row_count=len(chunk),
                )
            )

    parquet_artifacts = tuple(artifacts)
    config_names = tuple(sorted(grouped))
    card = _dataset_card(
        dataset_id=dataset_id,
        source=license_provenance,
        profile=PUBLIC_RELEASE_PROFILE.name,
        config_names=config_names,
        limitations=limitations,
    )
    artifacts.append(
        ReleaseArtifact(
            "README.md", "text/markdown; charset=utf-8", card
        )
    )
    artifacts.append(
        ReleaseArtifact(
            "evaluation-report.json",
            "application/json",
            _canonical_json(
                {
                    "evaluation": evaluation_record.to_dict(),
                    "grants_execution_authority": False,
                    "schema_version": HF_RELEASE_SCHEMA_VERSION,
                }
            ),
        )
    )
    infos = _dataset_infos(
        parquet_artifacts, dataset_id=dataset_id, dataset_root=dataset.cid
    )
    artifacts.append(
        ReleaseArtifact(
            "dataset_infos.json", "application/json", _canonical_json(infos)
        )
    )
    root = _release_root(
        artifacts,
        dataset_id=dataset_id,
        license_provenance=license_provenance,
        profile=PUBLIC_RELEASE_PROFILE.name,
        dataset_root=dataset.cid,
        config_cid=config.cid,
    )
    source_cids = tuple(
        sorted({cid for record in records for cid in record.source_cids})
    )
    manifest_record = ReleaseManifest(
        source_cids=source_cids,
        parent_cids=(dataset.cid,),
        config_cid=config.cid,
        dataset_id=dataset_id,
        profile=PUBLIC_RELEASE_PROFILE.name,
        record_cids=tuple(item.record_id for item in records),
        shard_cids=tuple(item.content_id for item in parquet_artifacts),
        payload={
            "derived_dataset_schema_version": CVEFIXES_DATASET_SCHEMA_VERSION,
            "grants_execution_authority": False,
            "release_root": root,
            "release_schema_version": HF_RELEASE_SCHEMA_VERSION,
        },
    )
    manifest_value = {
        "artifacts": [
            item.descriptor() for item in sorted(artifacts, key=lambda item: item.path)
        ],
        "dataset_id": dataset_id,
        "derived_dataset_root": dataset.cid,
        "release_manifest": manifest_record.to_dict(),
        "release_root": root,
        "schema_version": HF_RELEASE_SCHEMA_VERSION,
        "source": license_provenance.to_dict(),
    }
    _walk_public_value(manifest_value)
    artifacts.append(
        ReleaseArtifact(
            "manifest.json", "application/json", _canonical_json(manifest_value)
        )
    )
    release = HuggingFaceRelease(
        dataset_id=dataset_id,
        source_dataset_id=license_provenance.dataset_id,
        source_revision=license_provenance.source_revision,
        license_provenance=license_provenance,
        profile=PUBLIC_RELEASE_PROFILE.name,
        release_root=root,
        release_manifest=manifest_record,
        artifacts=tuple(artifacts),
        parquet_config=config,
    )
    validate_huggingface_release(release)
    return release


def _read_parquet_rows(artifact: ReleaseArtifact) -> tuple[dict[str, Any], ...]:
    _, pq = _pyarrow()
    try:
        table = pq.read_table(io.BytesIO(artifact.content))
    except Exception as exc:
        raise ReleaseIntegrityError(
            f"cannot read Parquet artifact {artifact.path}"
        ) from exc
    if tuple(table.schema.names) != _PARQUET_COLUMNS:
        raise ReleaseIntegrityError(
            f"unexpected Parquet schema in {artifact.path}"
        )
    metadata = table.schema.metadata or {}
    if metadata.get(b"cvefixes_schema_version") != HF_PARQUET_SCHEMA_VERSION.encode(
        "ascii"
    ):
        raise ReleaseIntegrityError(
            f"missing Parquet schema version in {artifact.path}"
        )
    return tuple(table.to_pylist())


def validate_huggingface_release(
    release: HuggingFaceRelease,
) -> ReleaseValidation:
    """Verify roots, schemas, row identities, and bounds without credentials."""

    if not isinstance(release, HuggingFaceRelease):
        raise HuggingFaceReleaseError("release must be a HuggingFaceRelease")
    manifest = json.loads(release.artifact("manifest.json").content)
    if manifest.get("release_root") != release.release_root:
        raise ReleaseIntegrityError("manifest release_root mismatch")
    if ReleaseManifest.from_dict(manifest.get("release_manifest", {})) != release.release_manifest:
        raise ReleaseIntegrityError("canonical release manifest mismatch")
    if manifest.get("source") != release.license_provenance.to_dict():
        raise ReleaseIntegrityError("manifest license provenance mismatch")
    described = manifest.get("artifacts")
    if not isinstance(described, list):
        raise ReleaseIntegrityError("manifest artifacts must be a list")
    expected = [
        item.descriptor()
        for item in release.artifacts
        if item.path != "manifest.json"
    ]
    if described != expected:
        raise ReleaseIntegrityError("artifact inventory mismatch")
    computed_root = _release_root(
        tuple(item for item in release.artifacts if item.path != "manifest.json"),
        dataset_id=release.dataset_id,
        license_provenance=release.license_provenance,
        profile=release.profile,
        dataset_root=manifest.get("derived_dataset_root", ""),
        config_cid=release.parquet_config.cid,
    )
    if computed_root != release.release_root:
        raise ReleaseIntegrityError("release root does not match artifacts")

    rows_seen: set[str] = set()
    row_count = 0
    config_shards: dict[str, int] = {}
    for artifact in release.parquet_artifacts:
        if len(artifact.content) > release.parquet_config.max_shard_bytes:
            raise ReleaseLimitError("Parquet artifact exceeds max_shard_bytes")
        rows = _read_parquet_rows(artifact)
        if len(rows) != artifact.row_count:
            raise ReleaseIntegrityError("Parquet row count mismatch")
        if len(rows) > release.parquet_config.max_rows_per_shard:
            raise ReleaseLimitError("Parquet artifact exceeds row bound")
        config_shards[artifact.config_name] = (
            config_shards.get(artifact.config_name, 0) + 1
        )
        for row in rows:
            if row["record_type"] != artifact.config_name:
                raise ReleaseIntegrityError("record crossed Parquet config")
            try:
                value = json.loads(row["record_json"])
                record = record_from_dict(value)
            except Exception as exc:
                raise ReleaseIntegrityError(
                    "Parquet row does not contain a canonical record"
                ) from exc
            _walk_public_value(value)
            if (
                record.record_id != row["record_id"]
                or record.authority.value != row["authority"]
                or list(record.source_cids) != row["source_cids"]
                or list(record.parent_cids) != row["parent_cids"]
                or record.config_cid != row["config_cid"]
                or _canonical_json(value).decode("utf-8") != row["record_json"]
            ):
                raise ReleaseIntegrityError("Parquet identity column mismatch")
            if record.record_id in rows_seen:
                raise ReleaseIntegrityError("duplicate record across shards")
            rows_seen.add(record.record_id)
        row_count += len(rows)
    if row_count > release.parquet_config.max_records:
        raise ReleaseLimitError("release exceeds max_records")
    if any(
        count > release.parquet_config.max_shards_per_config
        for count in config_shards.values()
    ):
        raise ReleaseLimitError("release config exceeds shard bound")
    if rows_seen != set(release.release_manifest.record_cids):
        raise ReleaseIntegrityError("manifest record inventory mismatch")
    if {item.content_id for item in release.parquet_artifacts} != set(
        release.release_manifest.shard_cids
    ):
        raise ReleaseIntegrityError("manifest shard inventory mismatch")
    return ReleaseValidation(
        release_root=release.release_root,
        artifact_count=len(release.artifacts),
        shard_count=len(release.parquet_artifacts),
        row_count=row_count,
    )


def stage_huggingface_release(
    release: HuggingFaceRelease,
    output_directory: str | os.PathLike[str],
    *,
    validate_only: bool = True,
) -> ReleaseValidation:
    """Validate or write a release locally; validation is the safe default.

    The function never reads a token or cache environment variable.  A real
    staging run refuses symlink targets and non-empty directories so unrelated
    files cannot be overwritten or smuggled into a publication.
    """

    validation = validate_huggingface_release(release)
    if type(validate_only) is not bool:
        raise HuggingFaceReleaseError("validate_only must be boolean")
    if validate_only:
        return validation
    root = Path(output_directory)
    if root.exists():
        if root.is_symlink() or not root.is_dir():
            raise ReleaseSafetyError("staging target must be a real directory")
        if any(root.iterdir()):
            raise ReleaseSafetyError("staging target must be empty")
    else:
        root.mkdir(parents=True, mode=0o755)
    resolved_root = root.resolve(strict=True)
    for artifact in release.artifacts:
        destination = root.joinpath(*PurePosixPath(artifact.path).parts)
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        if destination.parent.resolve(strict=True) != resolved_root and (
            resolved_root not in destination.parent.resolve(strict=True).parents
        ):
            raise ReleaseSafetyError("artifact escaped staging directory")
        if destination.exists() or destination.is_symlink():
            raise ReleaseSafetyError("staging refuses to overwrite artifacts")
        temporary = destination.with_name(f".{destination.name}.tmp")
        if temporary.exists() or temporary.is_symlink():
            raise ReleaseSafetyError("staging temporary path already exists")
        with temporary.open("xb") as handle:
            handle.write(artifact.content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(destination)
    return validation


class BoundedReleaseQueryClient:
    """Credential-free bounded query client over validated local shards."""

    def __init__(
        self,
        release: HuggingFaceRelease,
        *,
        max_shards: int = 8,
        max_rows: int = 10_000,
        max_results: int = 25,
    ) -> None:
        validate_huggingface_release(release)
        self._release = release
        self.max_shards = _positive_int(max_shards, "max_shards")
        self.max_rows = _positive_int(max_rows, "max_rows")
        self.max_results = _positive_int(max_results, "max_results")

    def query(self, query: ReleaseQuery) -> ReleaseQueryResponse:
        if not isinstance(query, ReleaseQuery):
            raise HuggingFaceReleaseError("query must be a ReleaseQuery")
        shard_limit = min(query.max_shards or self.max_shards, self.max_shards)
        row_limit = min(query.max_rows or self.max_rows, self.max_rows)
        result_limit = min(query.max_results or self.max_results, self.max_results)
        selected = tuple(
            artifact
            for artifact in self._release.parquet_artifacts
            if not query.record_types or artifact.config_name in query.record_types
        )
        scanned = selected[:shard_limit]
        text_terms = tuple(query.text.casefold().split())
        results: list[Mapping[str, Any]] = []
        rows_scanned = 0
        truncated_rows = False
        truncated_results = False
        for artifact in scanned:
            for row in _read_parquet_rows(artifact):
                if rows_scanned >= row_limit:
                    truncated_rows = True
                    break
                rows_scanned += 1
                if query.authorities and row["authority"] not in query.authorities:
                    continue
                haystack = row["record_json"].casefold()
                if text_terms and not all(term in haystack for term in text_terms):
                    continue
                if len(results) >= result_limit:
                    truncated_results = True
                    continue
                record = record_from_dict(json.loads(row["record_json"]))
                results.append(MappingProxyType(record.to_dict()))
            if truncated_rows:
                break
        return ReleaseQueryResponse(
            release_root=self._release.release_root,
            results=tuple(results),
            shards_scanned=len(scanned),
            rows_scanned=rows_scanned,
            truncated_shards=len(selected) > len(scanned),
            truncated_rows=truncated_rows,
            truncated_results=truncated_results,
        )


# Descriptive compatibility names for publication tooling and downstream clients.
HFReleaseBuilderConfig = ParquetReleaseConfig
HFReleaseArtifact = ReleaseArtifact
HFRelease = HuggingFaceRelease
HFReleaseQuery = ReleaseQuery
HFReleaseQueryClient = BoundedReleaseQueryClient
build_hf_release = build_huggingface_release
validate_hf_release = validate_huggingface_release
stage_hf_release = stage_huggingface_release


__all__ = [
    "BoundedReleaseQueryClient",
    "DEFAULT_HF_DATASET_ID",
    "DEFAULT_LIMITATIONS",
    "HF_PARQUET_SCHEMA_VERSION",
    "HF_QUERY_SCHEMA_VERSION",
    "HF_RELEASE_SCHEMA_VERSION",
    "HFRelease",
    "HFReleaseArtifact",
    "HFReleaseBuilderConfig",
    "HFReleaseQuery",
    "HFReleaseQueryClient",
    "HuggingFaceRelease",
    "HuggingFaceReleaseError",
    "ParquetReleaseConfig",
    "ReleaseArtifact",
    "ReleaseIntegrityError",
    "ReleaseLimitError",
    "ReleaseQuery",
    "ReleaseQueryResponse",
    "ReleaseSafetyError",
    "ReleaseValidation",
    "build_hf_release",
    "build_huggingface_release",
    "stage_hf_release",
    "stage_huggingface_release",
    "validate_hf_release",
    "validate_huggingface_release",
]
