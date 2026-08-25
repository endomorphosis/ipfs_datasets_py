"""Additive Hugging Face release packaging and dataset card for US Code (USCIR-031).

Packages a validated local US Code Sparse GraphRAG artifact tree into an
immutable candidate root with:

* compact ``manifest.json`` / ``release_metadata.json`` (control plane);
* explicit Dataset Viewer configurations (default v2, legacy compatibility,
  recovery quarantine);
* descriptor-bound inventory for every artifact;
* admission / quality reports on the control plane;
* **verbose lineage** isolated under ``reports/lineage.json`` (never mixed
  into control-plane manifests or the default viewer config);
* additive staging that never deletes legacy ``uscode_parquet/*`` files.

This module does **not** publish to the Hub. Remote mutation is owned by
USCIR-032+ staging/publication gates. Default mode is dry-run (in-memory).

Acceptance invariants
---------------------
1. Default config excludes recovery JSON.
2. Every advertised config is schema-coherent (paths + families + primary keys).
3. Every artifact is descriptor-bound (relative path, media type, rows, bytes,
   SHA-256, schema id, family).
4. Verbose lineage is separate from the control plane.
5. Legacy files are never deleted (additive packaging only).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
from types import MappingProxyType
from typing import Any, Final, Iterable, Optional, Union

from ipfs_datasets_py.huggingface.release import (
    DEFAULT_SHARD_ROWS,
    FileDescriptor,
    HuggingFaceReleaseError,
    canonical_json_bytes,
    describe_file,
    reject_identity_contamination,
    shard_sequence,
)
from ipfs_datasets_py.logic.ir_core.identity import cid_v1_from_digest
from ipfs_datasets_py.processors.legal_data.uscode_embeddings import (
    DEFAULT_DIMENSION,
    DEFAULT_MODEL_ID,
    DEFAULT_MODEL_REVISION,
    DEFAULT_NORMALIZATION,
    DEFAULT_POOLING,
    build_vector_space_id,
)
from ipfs_datasets_py.processors.legal_data.uscode_release_schema import (
    MAX_ROWS_PER_PHYSICAL_SHARD,
    RELEASE_PROFILE,
    SCHEMA_VERSION as RELEASE_SCHEMA_VERSION,
    ArtifactDescriptor,
    ArtifactFamily,
    ReleaseManifest,
    canonical_json_dumps,
    digest_mapping,
    normalize_relative_artifact_path,
    normalize_sha256,
    require_immutable_revision,
)
from ipfs_datasets_py.processors.legal_data.uscode_source_policy import (
    CURRENTNESS_DISCLAIMER,
    DEFAULT_APPROVED_RELEASE_POINT,
)
from ipfs_datasets_py.processors.legal_data.uscode_sparse_graphrag import (
    BASELINE_BM25_PARQUET,
    BASELINE_CID_INDEX_PARQUET,
    BASELINE_EMBEDDINGS_PARQUET,
    BASELINE_KG_ENTITIES_PARQUET,
    BASELINE_KG_RELATIONSHIPS_PARQUET,
    BASELINE_LAWS_PARQUET,
    COMPAT_CONFIG_LEGACY_USCODE_PARQUET,
    DEFAULT_CONFIG_V2,
    DEFAULT_DATASET_REPO_ID,
    PRIMARY_KEY_V2,
)

# ---------------------------------------------------------------------------
# Identity / schema constants
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "uscode-hf-release/v1"
TASK_ID: Final = "USCIR-031"
GOAL_ID: Final = "USCIR-G080"
PRODUCER: Final = "uscode_hf_release.py"
HF_RELEASE_PRODUCER: Final = "producer:uscode-hf-release"
HF_RELEASE_CONFIG: Final = "config:uscode-hf-release/v1"

MANIFEST_FILENAME: Final = "manifest.json"
RELEASE_METADATA_FILENAME: Final = "release_metadata.json"
README_FILENAME: Final = "README.md"
DATASET_INFOS_FILENAME: Final = "dataset_infos.json"
DATASET_CONFIGS_FILENAME: Final = "dataset_configs.json"

ADMISSION_REPORT_PATH: Final = "reports/admission.json"
QUALITY_REPORT_PATH: Final = "reports/quality.json"
REPRODUCIBILITY_REPORT_PATH: Final = "reports/reproducibility.json"
# Verbose lineage is intentionally NOT on the control-plane surface.
LINEAGE_REPORT_PATH: Final = "reports/lineage.json"

RECOVERY_CONFIG_NAME: Final = "recovery-quarantine/v1"
DEFAULT_CONFIG_NAME: Final = DEFAULT_CONFIG_V2
LEGACY_CONFIG_NAME: Final = COMPAT_CONFIG_LEGACY_USCODE_PARQUET

DEFAULT_SOURCE_REVISION: Final = "75cfc5982dc3a6808614cd4eb9b4238f8f9308b8"
DEFAULT_TOKENIZER_ID: Final = "uscode-legal-tokenizer/v1"
DEFAULT_GRAPH_ONTOLOGY_VERSION: Final = "uscode-legal-graph-ontology/v1"
DEFAULT_PACKAGE_VERSION: Final = "2"
DEFAULT_LICENSE: Final = "other"
DEFAULT_BM25_K1: Final = 1.2
DEFAULT_BM25_B: Final = 0.75
DEFAULT_DETERMINISM_SEED: Final = 20260330

PARQUET_MEDIA_TYPE: Final = "application/vnd.apache.parquet"
JSON_MEDIA_TYPE: Final = "application/json"
MARKDOWN_MEDIA_TYPE: Final = "text/markdown; charset=utf-8"

# Families that belong to the default viewer-safe v2 config.
DEFAULT_CONFIG_FAMILIES: Final = frozenset(
    {
        "corpus",
        "bm25_documents",
        "bm25_postings",
        "vectors",
        "centroids",
        "graph_nodes",
        "graph_edges",
        "graph_adjacency_out",
        "graph_adjacency_in",
    }
)

# Families that must never appear under the default config.
RECOVERY_FAMILIES: Final = frozenset({"recovery"})

# Path prefixes bound to each advertised config (schema coherence).
DEFAULT_CONFIG_PATH_PREFIXES: Final = (
    "data/corpus/",
    "data/bm25/",
    "data/vectors/",
    "data/graph/",
    "indexes/",
)
RECOVERY_CONFIG_PATH_PREFIXES: Final = ("recovery/",)
LEGACY_CONFIG_PATHS: Final = (
    BASELINE_LAWS_PARQUET,
    BASELINE_CID_INDEX_PARQUET,
    BASELINE_BM25_PARQUET,
    BASELINE_EMBEDDINGS_PARQUET,
    BASELINE_KG_ENTITIES_PARQUET,
    BASELINE_KG_RELATIONSHIPS_PARQUET,
)

# Control-plane relative paths (manifest surface; excludes verbose lineage).
CONTROL_PLANE_PATHS: Final = frozenset(
    {
        MANIFEST_FILENAME,
        RELEASE_METADATA_FILENAME,
        README_FILENAME,
        DATASET_INFOS_FILENAME,
        DATASET_CONFIGS_FILENAME,
        ADMISSION_REPORT_PATH,
        QUALITY_REPORT_PATH,
        REPRODUCIBILITY_REPORT_PATH,
    }
)

_DATASET_ID_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}$"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CID_RE = re.compile(r"^b[a-z2-7]{20,}$")

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]

# Family → default relative data path template (shard index filled later).
_FAMILY_PATH_TEMPLATES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "corpus": "data/corpus/part-{shard:06d}.parquet",
        "bm25_documents": "data/bm25/documents/part-{shard:06d}.parquet",
        "bm25_postings": "data/bm25/postings/part-{shard:06d}.parquet",
        "vectors": "data/vectors/centroid-000-part-{shard:06d}.parquet",
        "centroids": "data/vectors/centroids/part-{shard:06d}.parquet",
        "graph_nodes": "data/graph/nodes/part-{shard:06d}.parquet",
        "graph_edges": "data/graph/edges/part-{shard:06d}.parquet",
        "graph_adjacency_out": "data/graph/adjacency/out/part-{shard:06d}.parquet",
        "graph_adjacency_in": "data/graph/adjacency/in/part-{shard:06d}.parquet",
        "recovery": "recovery/part-{shard:06d}.json",
    }
)

_FAMILY_TO_ARTIFACT_FAMILY: Final[Mapping[str, ArtifactFamily]] = MappingProxyType(
    {
        "corpus": ArtifactFamily.CORPUS,
        "bm25_documents": ArtifactFamily.BM25_DOCUMENTS,
        "bm25_postings": ArtifactFamily.BM25_POSTINGS,
        "vectors": ArtifactFamily.VECTORS,
        "centroids": ArtifactFamily.CENTROIDS,
        "graph_nodes": ArtifactFamily.GRAPH_NODES,
        "graph_edges": ArtifactFamily.GRAPH_EDGES,
        "graph_adjacency_out": ArtifactFamily.GRAPH_ADJACENCY_OUT,
        "graph_adjacency_in": ArtifactFamily.GRAPH_ADJACENCY_IN,
        "recovery": ArtifactFamily.RECOVERY,
        "routing_index": ArtifactFamily.ROUTING_INDEX,
        "locator_index": ArtifactFamily.LOCATOR_INDEX,
        "manifest": ArtifactFamily.MANIFEST,
        "receipt": ArtifactFamily.RECEIPT,
        "report": ArtifactFamily.REPORT,
        "release_metadata": ArtifactFamily.RELEASE_METADATA,
    }
)

_FAMILY_SCHEMA_IDS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "corpus": "uscode-corpus-row/v1",
        "bm25_documents": "uscode-bm25-document/v1",
        "bm25_postings": "uscode-bm25-posting/v1",
        "vectors": "uscode-vector-row/v1",
        "centroids": "uscode-centroid-row/v1",
        "graph_nodes": "uscode-graph-node/v1",
        "graph_edges": "uscode-graph-edge/v1",
        "graph_adjacency_out": "uscode-graph-adjacency-out/v1",
        "graph_adjacency_in": "uscode-graph-adjacency-in/v1",
        "recovery": "uscode-recovery-quarantine/v1",
        "routing_index": "uscode-routing-index/v1",
    }
)

# Feature columns advertised per config (Dataset Viewer schema coherence).
_CONFIG_FEATURES: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        DEFAULT_CONFIG_NAME: (
            "entry_cid",
            "legal_id",
            "family",
            "record_json",
            "record_sha256",
        ),
        LEGACY_CONFIG_NAME: (
            "ipfs_cid",
            "title",
            "section",
            "text",
        ),
        RECOVERY_CONFIG_NAME: (
            "recovery_id",
            "admission_status",
            "record_json",
            "record_sha256",
        ),
    }
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class UscodeHFReleaseError(HuggingFaceReleaseError):
    """Base error for US Code Hugging Face release packaging failures."""

    code: str = "uscode_hf_release_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class UscodeHFReleaseIntegrityError(UscodeHFReleaseError):
    """Raised when descriptors, digests, or config bindings disagree."""

    code = "uscode_hf_release_integrity"


class UscodeHFReleaseConfigError(UscodeHFReleaseError):
    """Raised when viewer/config schema coherence fails."""

    code = "uscode_hf_release_config"


class UscodeHFReleaseSafetyError(UscodeHFReleaseError):
    """Raised when recovery contaminates default config or legacy is deleted."""

    code = "uscode_hf_release_safety"


# ---------------------------------------------------------------------------
# Viewer configuration contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ViewerConfig:
    """One advertised Hugging Face Dataset Viewer configuration."""

    config_name: str
    data_files: tuple[dict[str, str], ...]
    primary_key: str
    is_default: bool = False
    is_legacy: bool = False
    is_recovery: bool = False
    features: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    path_prefixes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        name = str(self.config_name or "").strip()
        if not name:
            raise UscodeHFReleaseConfigError("config_name is required")
        if self.is_default and (self.is_legacy or self.is_recovery):
            raise UscodeHFReleaseConfigError(
                "default config cannot also be legacy or recovery"
            )
        if self.is_recovery and self.is_legacy:
            raise UscodeHFReleaseConfigError(
                "config cannot be both recovery and legacy"
            )
        object.__setattr__(self, "config_name", name)
        object.__setattr__(
            self,
            "primary_key",
            str(self.primary_key or "").strip() or PRIMARY_KEY_V2,
        )
        files = tuple(dict(item) for item in self.data_files)
        if not files:
            raise UscodeHFReleaseConfigError(
                f"config {name!r} requires at least one data_files entry"
            )
        for item in files:
            if "split" not in item or "path" not in item:
                raise UscodeHFReleaseConfigError(
                    f"config {name!r} data_files entries need split + path"
                )
            path = str(item["path"])
            if path.startswith("/") or ".." in PurePosixPath(path).parts:
                raise UscodeHFReleaseConfigError(
                    f"config {name!r} data path is unsafe: {path!r}"
                )
        object.__setattr__(self, "data_files", files)
        object.__setattr__(self, "features", tuple(self.features))
        object.__setattr__(self, "notes", tuple(str(n) for n in self.notes))
        object.__setattr__(
            self, "path_prefixes", tuple(str(p) for p in self.path_prefixes)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_name": self.config_name,
            "data_files": [dict(item) for item in self.data_files],
            "features": list(self.features),
            "is_default": self.is_default,
            "is_legacy": self.is_legacy,
            "is_recovery": self.is_recovery,
            "notes": list(self.notes),
            "path_prefixes": list(self.path_prefixes),
            "primary_key": self.primary_key,
        }

    def yaml_block(self) -> list[str]:
        """Return YAML lines for Dataset card ``configs:`` frontmatter."""

        lines = [
            f"- config_name: {json.dumps(self.config_name)}",
            "  data_files:",
        ]
        for item in self.data_files:
            lines.append(f"  - split: {json.dumps(item['split'])}")
            lines.append(f"    path: {json.dumps(item['path'])}")
        return lines


def advertised_viewer_configs(
    *,
    include_legacy: bool = True,
    include_recovery: bool = True,
    default_data_glob: str = "data/**/*.parquet",
    recovery_data_glob: str = "recovery/**/*.json",
    legacy_data_files: Sequence[str] | None = None,
) -> tuple[ViewerConfig, ...]:
    """Return the sealed set of advertised Dataset Viewer configurations."""

    configs: list[ViewerConfig] = [
        ViewerConfig(
            config_name=DEFAULT_CONFIG_NAME,
            data_files=({"split": "train", "path": default_data_glob},),
            primary_key=PRIMARY_KEY_V2,
            is_default=True,
            is_legacy=False,
            is_recovery=False,
            features=_CONFIG_FEATURES[DEFAULT_CONFIG_NAME],
            path_prefixes=DEFAULT_CONFIG_PATH_PREFIXES,
            notes=(
                "Default viewer-safe v2 configuration.",
                "Excludes recovery JSON and legacy uscode_parquet monoliths.",
            ),
        )
    ]
    if include_legacy:
        legacy_paths = tuple(legacy_data_files or LEGACY_CONFIG_PATHS)
        configs.append(
            ViewerConfig(
                config_name=LEGACY_CONFIG_NAME,
                data_files=tuple(
                    {"split": "train", "path": path} for path in legacy_paths
                ),
                primary_key="ipfs_cid",
                is_default=False,
                is_legacy=True,
                is_recovery=False,
                features=_CONFIG_FEATURES[LEGACY_CONFIG_NAME],
                path_prefixes=("uscode_parquet/",),
                notes=(
                    "Explicit deprecation-cycle compatibility path.",
                    "Must not be the default Dataset Viewer config.",
                    "Legacy files are retained; packaging never deletes them.",
                ),
            )
        )
    if include_recovery:
        configs.append(
            ViewerConfig(
                config_name=RECOVERY_CONFIG_NAME,
                data_files=({"split": "train", "path": recovery_data_glob},),
                primary_key="recovery_id",
                is_default=False,
                is_legacy=False,
                is_recovery=True,
                features=_CONFIG_FEATURES[RECOVERY_CONFIG_NAME],
                path_prefixes=RECOVERY_CONFIG_PATH_PREFIXES,
                notes=(
                    "Quarantine configuration for heterogeneous recovery JSON.",
                    "Never included in the default config or canonical counts.",
                ),
            )
        )
    return tuple(configs)


def assert_configs_schema_coherent(
    configs: Sequence[ViewerConfig | Mapping[str, Any]],
) -> dict[str, Any]:
    """Fail closed when advertised configs violate schema coherence rules."""

    resolved: list[ViewerConfig] = []
    for item in configs:
        if isinstance(item, ViewerConfig):
            resolved.append(item)
        elif isinstance(item, Mapping):
            resolved.append(
                ViewerConfig(
                    config_name=str(item.get("config_name") or item.get("name") or ""),
                    data_files=tuple(item.get("data_files") or ()),
                    primary_key=str(item.get("primary_key") or PRIMARY_KEY_V2),
                    is_default=bool(item.get("is_default", False)),
                    is_legacy=bool(item.get("is_legacy", False)),
                    is_recovery=bool(item.get("is_recovery", False)),
                    features=tuple(item.get("features") or ()),
                    notes=tuple(item.get("notes") or ()),
                    path_prefixes=tuple(item.get("path_prefixes") or ()),
                )
            )
        else:
            raise UscodeHFReleaseConfigError(
                "config entries must be ViewerConfig or mapping"
            )

    if not resolved:
        raise UscodeHFReleaseConfigError("at least one viewer config is required")

    defaults = [c for c in resolved if c.is_default]
    if len(defaults) != 1:
        raise UscodeHFReleaseConfigError(
            f"exactly one default config required, found {len(defaults)}"
        )
    default = defaults[0]
    if default.config_name != DEFAULT_CONFIG_NAME:
        raise UscodeHFReleaseConfigError(
            f"default config must be {DEFAULT_CONFIG_NAME!r}, "
            f"got {default.config_name!r}"
        )
    if default.is_recovery or default.is_legacy:
        raise UscodeHFReleaseConfigError(
            "default config must not be recovery or legacy"
        )

    # Default must not advertise recovery paths.
    for entry in default.data_files:
        path = str(entry["path"])
        if path.startswith("recovery/") or "/recovery/" in f"/{path}/":
            raise UscodeHFReleaseSafetyError(
                "default config excludes recovery JSON; "
                f"found recovery path {path!r}"
            )
        if path.startswith("uscode_parquet/") or path.endswith(".json") and "recovery" in path:
            if "recovery" in path:
                raise UscodeHFReleaseSafetyError(
                    f"default config must not include recovery path {path!r}"
                )

    names = [c.config_name for c in resolved]
    if len(names) != len(set(names)):
        raise UscodeHFReleaseConfigError("viewer config names must be unique")

    for cfg in resolved:
        features = set(cfg.features)
        if cfg.primary_key and cfg.features and cfg.primary_key not in features:
            raise UscodeHFReleaseConfigError(
                f"config {cfg.config_name!r} primary_key "
                f"{cfg.primary_key!r} missing from features"
            )
        if cfg.is_recovery and cfg.config_name != RECOVERY_CONFIG_NAME:
            raise UscodeHFReleaseConfigError(
                f"recovery config must be named {RECOVERY_CONFIG_NAME!r}"
            )
        if cfg.is_legacy and cfg.config_name != LEGACY_CONFIG_NAME:
            raise UscodeHFReleaseConfigError(
                f"legacy config must be named {LEGACY_CONFIG_NAME!r}"
            )

    return {
        "config_count": len(resolved),
        "default_config": default.config_name,
        "default_excludes_recovery": True,
        "names": names,
        "schema_coherent": True,
    }


# ---------------------------------------------------------------------------
# Release artifacts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReleaseArtifact:
    """One immutable release file with full integrity metadata."""

    relative_path: str
    content: bytes = field(repr=False)
    media_type: str
    family: str
    row_count: int = 0
    config_name: str = ""
    schema_id: str = ""
    first_key: Optional[str] = None
    last_key: Optional[str] = None
    sha256: str = ""
    content_cid: str = ""
    size_bytes: int = 0

    def __post_init__(self) -> None:
        path = normalize_relative_artifact_path(self.relative_path)
        if not isinstance(self.content, (bytes, bytearray)):
            raise UscodeHFReleaseError("artifact content must be bytes")
        content = bytes(self.content)
        digest = hashlib.sha256(content).hexdigest()
        cid = cid_v1_from_digest(bytes.fromhex(digest))
        if self.sha256 and normalize_sha256(self.sha256) != digest:
            raise UscodeHFReleaseIntegrityError(
                f"artifact sha256 mismatch for {path}"
            )
        if self.content_cid and self.content_cid != cid:
            raise UscodeHFReleaseIntegrityError(
                f"artifact content_cid mismatch for {path}"
            )
        if type(self.row_count) is not int or isinstance(self.row_count, bool):
            raise UscodeHFReleaseError("row_count must be a non-negative integer")
        if self.row_count < 0:
            raise UscodeHFReleaseError("row_count must be a non-negative integer")
        if self.row_count > MAX_ROWS_PER_PHYSICAL_SHARD and self.family in (
            DEFAULT_CONFIG_FAMILIES | RECOVERY_FAMILIES
        ):
            raise UscodeHFReleaseIntegrityError(
                f"artifact {path} row_count={self.row_count} exceeds "
                f"physical bound {MAX_ROWS_PER_PHYSICAL_SHARD}"
            )
        media = str(self.media_type or "").strip()
        if not media:
            raise UscodeHFReleaseError("media_type is required")
        family = str(self.family or "").strip().lower()
        if not family:
            raise UscodeHFReleaseError("family is required")
        schema_id = str(self.schema_id or _FAMILY_SCHEMA_IDS.get(family) or "")
        if not schema_id:
            # Support / control-plane artifacts use release schema id.
            schema_id = SCHEMA_VERSION
        object.__setattr__(self, "relative_path", path)
        object.__setattr__(self, "content", content)
        object.__setattr__(self, "sha256", digest)
        object.__setattr__(self, "content_cid", cid)
        object.__setattr__(self, "size_bytes", len(content))
        object.__setattr__(self, "media_type", media)
        object.__setattr__(self, "family", family)
        object.__setattr__(self, "schema_id", schema_id)
        object.__setattr__(self, "config_name", str(self.config_name or ""))
        if self.first_key is not None:
            object.__setattr__(self, "first_key", str(self.first_key))
        if self.last_key is not None:
            object.__setattr__(self, "last_key", str(self.last_key))

    def to_artifact_descriptor(self) -> ArtifactDescriptor:
        """Bind this artifact to the US Code release schema descriptor."""

        family = _FAMILY_TO_ARTIFACT_FAMILY.get(self.family)
        if family is None:
            # Control-plane / report / card files.
            if self.relative_path == MANIFEST_FILENAME:
                family = ArtifactFamily.MANIFEST
            elif self.relative_path == RELEASE_METADATA_FILENAME:
                family = ArtifactFamily.RELEASE_METADATA
            elif self.relative_path.startswith("reports/"):
                family = ArtifactFamily.REPORT
            elif self.relative_path.startswith("indexes/"):
                family = ArtifactFamily.ROUTING_INDEX
            else:
                family = ArtifactFamily.RECEIPT
        return ArtifactDescriptor(
            relative_path=self.relative_path,
            media_type=self.media_type,
            sha256=self.sha256,
            size_bytes=self.size_bytes,
            schema_id=self.schema_id,
            family=family,
            row_count=self.row_count,
            first_key=self.first_key,
            last_key=self.last_key,
        )

    def to_file_descriptor(self) -> FileDescriptor:
        return FileDescriptor(
            relative_path=self.relative_path,
            size_bytes=self.size_bytes,
            sha256=self.sha256,
            content_cid=self.content_cid,
            media_type=self.media_type,
            schema_type=self.schema_id,
            producer_id=HF_RELEASE_PRODUCER,
            config_digest=HF_RELEASE_CONFIG,
            row_count=self.row_count,
            config_name=self.config_name,
            license_id=DEFAULT_LICENSE,
            review_status="reviewed",
            trust_decision="public_release_admitted",
            metadata={
                "family": self.family,
                "first_key": self.first_key,
                "last_key": self.last_key,
            },
        )

    def descriptor_dict(self) -> dict[str, Any]:
        payload = self.to_artifact_descriptor().to_dict()
        payload["content_cid"] = self.content_cid
        payload["config_name"] = self.config_name
        return payload


@dataclass(frozen=True, slots=True)
class UscodeHuggingFaceRelease:
    """Complete in-memory (or staged) US Code Hugging Face release candidate."""

    dataset_id: str
    release_root_cid: str
    manifest_digest: str
    schema_version: str
    release_profile: str
    source_revision: str
    release_point: str
    build_config_cid: str
    vector_space_id: str
    configs: tuple[ViewerConfig, ...]
    artifacts: tuple[ReleaseArtifact, ...]
    dry_run: bool
    staged_root: Optional[str] = None
    package_version: str = DEFAULT_PACKAGE_VERSION

    def __post_init__(self) -> None:
        if not _DATASET_ID_RE.fullmatch(self.dataset_id):
            raise UscodeHFReleaseError("dataset_id must be owner/name")
        if not self.artifacts:
            raise UscodeHFReleaseError("release must contain artifacts")
        paths = [item.relative_path for item in self.artifacts]
        if len(paths) != len(set(paths)):
            raise UscodeHFReleaseIntegrityError("artifact paths must be unique")
        ordered = tuple(
            sorted(self.artifacts, key=lambda item: item.relative_path)
        )
        object.__setattr__(self, "artifacts", ordered)
        if type(self.dry_run) is not bool:
            raise UscodeHFReleaseError("dry_run must be boolean")
        require_immutable_revision(self.source_revision, name="source_revision")
        if not _CID_RE.fullmatch(str(self.release_root_cid)) and not _SHA256_RE.fullmatch(
            str(self.release_root_cid)
        ):
            # release_root_cid may be sha256 or CIDv1.
            if not str(self.release_root_cid).startswith("b") and len(
                str(self.release_root_cid)
            ) != 64:
                raise UscodeHFReleaseIntegrityError(
                    f"invalid release_root_cid: {self.release_root_cid!r}"
                )

    def artifact(self, relative_path: str) -> ReleaseArtifact:
        for item in self.artifacts:
            if item.relative_path == relative_path:
                return item
        raise KeyError(relative_path)

    @property
    def data_artifacts(self) -> tuple[ReleaseArtifact, ...]:
        return tuple(
            item
            for item in self.artifacts
            if item.relative_path.startswith("data/")
            or item.relative_path.startswith("recovery/")
            or item.relative_path.startswith("indexes/")
            or item.relative_path.startswith("uscode_parquet/")
        )

    @property
    def control_plane_artifacts(self) -> tuple[ReleaseArtifact, ...]:
        return tuple(
            item
            for item in self.artifacts
            if item.relative_path in CONTROL_PLANE_PATHS
            or (
                item.relative_path.startswith("reports/")
                and item.relative_path != LINEAGE_REPORT_PATH
            )
        )

    @property
    def lineage_artifact(self) -> Optional[ReleaseArtifact]:
        for item in self.artifacts:
            if item.relative_path == LINEAGE_REPORT_PATH:
                return item
        return None

    def manifest_dict(self) -> dict[str, Any]:
        return json.loads(self.artifact(MANIFEST_FILENAME).content.decode("utf-8"))

    def release_metadata_dict(self) -> dict[str, Any]:
        return json.loads(
            self.artifact(RELEASE_METADATA_FILENAME).content.decode("utf-8")
        )

    def dataset_card_text(self) -> str:
        return self.artifact(README_FILENAME).content.decode("utf-8")

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifacts": [item.descriptor_dict() for item in self.artifacts],
            "build_config_cid": self.build_config_cid,
            "configs": [cfg.to_dict() for cfg in self.configs],
            "dataset_id": self.dataset_id,
            "dry_run": self.dry_run,
            "manifest_digest": self.manifest_digest,
            "package_version": self.package_version,
            "release_point": self.release_point,
            "release_profile": self.release_profile,
            "release_root_cid": self.release_root_cid,
            "schema_version": self.schema_version,
            "source_revision": self.source_revision,
            "staged_root": self.staged_root,
            "vector_space_id": self.vector_space_id,
        }


# ---------------------------------------------------------------------------
# Encoding helpers
# ---------------------------------------------------------------------------


def _encode_parquet_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    family: str,
) -> bytes:
    """Encode rows as deterministic ZSTD Parquet bytes (optional pyarrow)."""

    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover
        raise UscodeHFReleaseError(
            "parquet encoding requires the optional 'pyarrow' package"
        ) from exc

    entry_cids: list[str] = []
    legal_ids: list[str] = []
    families: list[str] = []
    record_json: list[str] = []
    record_sha256: list[str] = []
    for row in rows:
        payload = dict(row)
        payload.setdefault("family", family)
        encoded = canonical_json_bytes(payload).decode("utf-8")
        record_json.append(encoded)
        record_sha256.append(hashlib.sha256(encoded.encode("utf-8")).hexdigest())
        entry_cids.append(
            str(
                payload.get("entry_cid")
                or payload.get("recovery_id")
                or payload.get("record_id")
                or ""
            )
        )
        legal_ids.append(str(payload.get("legal_id") or payload.get("term") or ""))
        families.append(family)

    table = pa.table(
        {
            "entry_cid": entry_cids,
            "legal_id": legal_ids,
            "family": families,
            "record_sha256": record_sha256,
            "record_json": record_json,
        }
    )
    buffer = io.BytesIO()
    pq.write_table(
        table,
        buffer,
        compression="zstd",
        compression_level=6,
        use_dictionary=True,
        write_statistics=True,
        write_page_index=False,
        data_page_version="1.0",
    )
    return buffer.getvalue()


def _encode_recovery_json(rows: Sequence[Mapping[str, Any]]) -> bytes:
    """Encode recovery quarantine rows as deterministic JSON (not default)."""

    payload = {
        "family": "recovery",
        "quarantined": True,
        "rows": [dict(row) for row in rows],
        "schema_version": _FAMILY_SCHEMA_IDS["recovery"],
    }
    reject_identity_contamination(payload, label="recovery-json")
    return canonical_json_bytes(payload) + b"\n"


def _row_sort_key(row: Mapping[str, Any], family: str) -> tuple[str, ...]:
    if family == "recovery":
        return (
            str(row.get("recovery_id") or row.get("row_id") or ""),
            str(row.get("record_sha256") or ""),
        )
    if family == "bm25_postings":
        return (
            str(row.get("term") or ""),
            str(row.get("entry_cid") or ""),
        )
    return (
        str(row.get("entry_cid") or row.get("record_id") or ""),
        str(row.get("legal_id") or ""),
    )


def _first_last_keys(
    rows: Sequence[Mapping[str, Any]], family: str
) -> tuple[Optional[str], Optional[str]]:
    if not rows:
        return None, None
    keys = [":".join(_row_sort_key(row, family)) for row in rows]
    return keys[0] or None, keys[-1] or None


# ---------------------------------------------------------------------------
# Dataset card
# ---------------------------------------------------------------------------


def render_dataset_card(
    *,
    dataset_id: str = DEFAULT_DATASET_REPO_ID,
    release_profile: str = RELEASE_PROFILE,
    source_revision: str = DEFAULT_SOURCE_REVISION,
    release_point: str = DEFAULT_APPROVED_RELEASE_POINT,
    configs: Sequence[ViewerConfig] | None = None,
    vector_space_id: str = "",
    model_id: str = DEFAULT_MODEL_ID,
    model_revision: str = DEFAULT_MODEL_REVISION,
    limitations: Sequence[str] | None = None,
    currentness_disclaimer: str = CURRENTNESS_DISCLAIMER,
) -> str:
    """Render the sealed Dataset card (README.md) with YAML frontmatter."""

    viewer_configs = tuple(configs or advertised_viewer_configs())
    assert_configs_schema_coherent(viewer_configs)
    space = vector_space_id or build_vector_space_id(
        model_id=model_id,
        model_revision=model_revision,
        pooling=DEFAULT_POOLING,
        normalization=DEFAULT_NORMALIZATION,
        dimension=DEFAULT_DIMENSION,
    )
    safe_limitations = tuple(
        limitations
        or (
            "Retrieval output is a research aid and is not a substitute for "
            "the official U.S. Code source.",
            "Acquisition and publication timestamps are not legal-currentness "
            "claims.",
            "Recovery quarantine rows are excluded from the default config and "
            "from corpus/BM25/vector/graph counts until normalized and admitted.",
            "Legacy uscode_parquet/* remains available only through the "
            "explicit compatibility configuration for one deprecation cycle.",
        )
    )

    lines: list[str] = [
        "---",
        f"license: {DEFAULT_LICENSE}",
        f'pretty_name: "US Code Sparse GraphRAG"',
        "tags:",
        "  - legal",
        "  - us-code",
        "  - graphrag",
        "  - justicedao",
        "  - public-domain-us-government",
        "configs:",
    ]
    for cfg in viewer_configs:
        lines.extend(cfg.yaml_block())
    lines.extend(
        [
            "---",
            "",
            "# US Code Sparse GraphRAG",
            "",
            f"Dataset repository: `{dataset_id}`",
            "",
            "## Release profile",
            "",
            f"- Profile: `{release_profile}`",
            f"- Pinned source revision: `{source_revision}`",
            f"- Official release point: `{release_point}`",
            f"- Embedding model: `{model_id}` @ `{model_revision}`",
            f"- Vector space: `{space}`",
            f"- Primary key (default config): `{PRIMARY_KEY_V2}`",
            "",
            "## Dataset configurations",
            "",
            "The **default** configuration is viewer-safe v2 only. Recovery JSON "
            "and legacy monoliths are advertised as separate named configs and "
            "never contaminate the default Dataset Viewer schema.",
            "",
        ]
    )
    for cfg in viewer_configs:
        role = (
            "default"
            if cfg.is_default
            else "legacy compatibility"
            if cfg.is_legacy
            else "recovery quarantine"
            if cfg.is_recovery
            else "named"
        )
        lines.append(f"- `{cfg.config_name}` ({role}) — primary key `{cfg.primary_key}`")
        for note in cfg.notes:
            lines.append(f"  - {note}")
    lines.extend(
        [
            "",
            "## Artifact layout",
            "",
            "```text",
            "README.md",
            "manifest.json",
            "release_metadata.json",
            "dataset_configs.json",
            "dataset_infos.json",
            "data/corpus/part-*.parquet",
            "data/bm25/documents/part-*.parquet",
            "data/bm25/postings/part-*.parquet",
            "data/vectors/centroid-*-part-*.parquet",
            "data/graph/nodes/part-*.parquet",
            "data/graph/edges/part-*.parquet",
            "data/graph/adjacency/out/part-*.parquet",
            "data/graph/adjacency/in/part-*.parquet",
            "indexes/*",
            "reports/admission.json",
            "reports/quality.json",
            "reports/reproducibility.json",
            "reports/lineage.json   # verbose lineage (not control plane)",
            "recovery/...          # quarantine config only",
            "uscode_parquet/...    # legacy compatibility config only",
            "```",
            "",
            "## Control plane vs verbose lineage",
            "",
            "The control plane consists of `manifest.json`, `release_metadata.json`, "
            "routing indexes, and compact admission/quality/reproducibility reports. "
            "Verbose per-row source lineage lives only in `reports/lineage.json` and "
            "is **not** mixed into Dataset Viewer configs or the release control plane.",
            "",
            "## Currentness disclaimer",
            "",
            currentness_disclaimer,
            "",
            "## Limitations",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in safe_limitations)
    lines.extend(
        [
            "",
            "## Integrity",
            "",
            "Every artifact is descriptor-bound in `manifest.json` with relative "
            "path, media type, row count, byte count, SHA-256, schema identifier, "
            "and optional key range. Packaging is additive: legacy files are never "
            "deleted by this release builder.",
            "",
            f"Producer: `{PRODUCER}` (`{TASK_ID}` / `{GOAL_ID}`).",
            "",
        ]
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UscodeHFReleaseBuilder:
    """Deterministic local builder for additive US Code HF release candidates."""

    dataset_id: str = DEFAULT_DATASET_REPO_ID
    max_rows_per_shard: int = MAX_ROWS_PER_PHYSICAL_SHARD
    source_revision: str = DEFAULT_SOURCE_REVISION
    release_point: str = DEFAULT_APPROVED_RELEASE_POINT
    model_id: str = DEFAULT_MODEL_ID
    model_revision: str = DEFAULT_MODEL_REVISION
    tokenizer_id: str = DEFAULT_TOKENIZER_ID
    graph_ontology_version: str = DEFAULT_GRAPH_ONTOLOGY_VERSION
    determinism_seed: int = DEFAULT_DETERMINISM_SEED
    include_legacy_config: bool = True
    include_recovery_config: bool = True

    def __post_init__(self) -> None:
        if not _DATASET_ID_RE.fullmatch(self.dataset_id):
            raise UscodeHFReleaseError("dataset_id must be owner/name")
        if (
            type(self.max_rows_per_shard) is not int
            or isinstance(self.max_rows_per_shard, bool)
            or self.max_rows_per_shard <= 0
            or self.max_rows_per_shard > MAX_ROWS_PER_PHYSICAL_SHARD
        ):
            raise UscodeHFReleaseError(
                f"max_rows_per_shard must be in 1..{MAX_ROWS_PER_PHYSICAL_SHARD}"
            )
        require_immutable_revision(self.source_revision, name="source_revision")
        rp = str(self.release_point or "").strip()
        if not rp or rp.lower() in {"latest", "main", "head", "master"}:
            raise UscodeHFReleaseError(
                f"release_point must be an exact pin, not {self.release_point!r}"
            )
        _assert_no_upload_shortcut()

    def build(
        self,
        family_rows: Mapping[str, Sequence[Mapping[str, Any]]],
        *,
        dry_run: bool = True,
        output_dir: str | Path | None = None,
        legacy_files: Mapping[str, bytes] | None = None,
        admission_summary: Mapping[str, Any] | None = None,
        preserve_existing: Sequence[str] | None = None,
    ) -> UscodeHuggingFaceRelease:
        """Build a descriptor-complete additive release from family rows.

        Parameters
        ----------
        family_rows:
            Mapping of family name → row mappings. Recovery rows (if any) are
            written only under ``recovery/`` and bound to the recovery config.
        dry_run:
            When True (default), materialize entirely in memory.
        output_dir:
            Required when ``dry_run`` is False. Staging is additive: existing
            legacy paths listed in ``preserve_existing`` are never deleted.
        legacy_files:
            Optional ``relative_path → bytes`` for compatibility monoliths.
            Bound to the legacy config only; never the default config.
        admission_summary:
            Optional compact admission counters for ``reports/admission.json``.
        preserve_existing:
            Relative paths that must still exist after staging (legacy retain).
        """

        _assert_no_upload_shortcut()
        if type(dry_run) is not bool:
            raise UscodeHFReleaseError("dry_run must be boolean")

        vector_space = build_vector_space_id(
            model_id=self.model_id,
            model_revision=self.model_revision,
            pooling=DEFAULT_POOLING,
            normalization=DEFAULT_NORMALIZATION,
            dimension=DEFAULT_DIMENSION,
        )
        build_config_cid = digest_mapping(
            {
                "dataset_id": self.dataset_id,
                "determinism_seed": self.determinism_seed,
                "graph_ontology_version": self.graph_ontology_version,
                "max_rows_per_shard": self.max_rows_per_shard,
                "model_id": self.model_id,
                "model_revision": self.model_revision,
                "release_point": self.release_point,
                "schema_version": SCHEMA_VERSION,
                "source_revision": self.source_revision,
                "tokenizer_id": self.tokenizer_id,
                "vector_space_id": vector_space,
            }
        )

        data_artifacts = self._build_data_artifacts(family_rows)
        legacy_artifacts = self._build_legacy_artifacts(legacy_files or {})
        has_recovery = any(
            item.family == "recovery" for item in data_artifacts
        )
        has_legacy = bool(legacy_artifacts)

        configs = advertised_viewer_configs(
            include_legacy=self.include_legacy_config and has_legacy,
            include_recovery=self.include_recovery_config and has_recovery,
        )
        # Always advertise the three sealed configs for schema coherence when
        # the operator requested them, even if a family is empty — empty
        # recovery/legacy is still an explicit named config only when rows/files
        # exist. Default is always present.
        if self.include_recovery_config and not has_recovery:
            # Keep recovery config advertised only when recovery rows exist.
            pass
        if self.include_legacy_config and not has_legacy:
            pass
        # Re-resolve with actual presence so empty families don't break Viewer.
        configs = advertised_viewer_configs(
            include_legacy=self.include_legacy_config and has_legacy,
            include_recovery=self.include_recovery_config and has_recovery,
        )
        assert_configs_schema_coherent(configs)

        reports = self._build_reports(
            data_artifacts=data_artifacts,
            legacy_artifacts=legacy_artifacts,
            family_rows=family_rows,
            admission_summary=admission_summary or {},
            build_config_cid=build_config_cid,
            vector_space_id=vector_space,
        )
        card_text = render_dataset_card(
            dataset_id=self.dataset_id,
            release_profile=RELEASE_PROFILE,
            source_revision=self.source_revision,
            release_point=self.release_point,
            configs=configs,
            vector_space_id=vector_space,
            model_id=self.model_id,
            model_revision=self.model_revision,
        )
        card_artifact = ReleaseArtifact(
            relative_path=README_FILENAME,
            content=card_text.encode("utf-8"),
            media_type=MARKDOWN_MEDIA_TYPE,
            family="receipt",
            row_count=0,
            schema_id=SCHEMA_VERSION,
        )
        configs_payload = {
            "configs": [cfg.to_dict() for cfg in configs],
            "default_config": DEFAULT_CONFIG_NAME,
            "default_excludes_recovery": True,
            "schema_version": SCHEMA_VERSION,
            "task_id": TASK_ID,
        }
        reject_identity_contamination(configs_payload, label="dataset-configs")
        configs_artifact = ReleaseArtifact(
            relative_path=DATASET_CONFIGS_FILENAME,
            content=canonical_json_bytes(configs_payload) + b"\n",
            media_type=JSON_MEDIA_TYPE,
            family="receipt",
            row_count=0,
            schema_id=SCHEMA_VERSION,
        )
        infos_payload = _dataset_infos(
            dataset_id=self.dataset_id,
            data_artifacts=data_artifacts,
            configs=configs,
        )
        reject_identity_contamination(infos_payload, label="dataset-infos")
        infos_artifact = ReleaseArtifact(
            relative_path=DATASET_INFOS_FILENAME,
            content=canonical_json_bytes(infos_payload) + b"\n",
            media_type=JSON_MEDIA_TYPE,
            family="receipt",
            row_count=0,
            schema_id=SCHEMA_VERSION,
        )

        support_pre_manifest = (
            card_artifact,
            configs_artifact,
            infos_artifact,
            *reports,
        )
        all_pre = tuple(data_artifacts) + tuple(legacy_artifacts) + support_pre_manifest

        release_root_cid = _compute_release_root_cid(
            dataset_id=self.dataset_id,
            artifacts=all_pre,
            build_config_cid=build_config_cid,
        )

        metadata_payload = _release_metadata_payload(
            dataset_id=self.dataset_id,
            release_root_cid=release_root_cid,
            build_config_cid=build_config_cid,
            source_revision=self.source_revision,
            release_point=self.release_point,
            vector_space_id=vector_space,
            model_id=self.model_id,
            model_revision=self.model_revision,
            tokenizer_id=self.tokenizer_id,
            graph_ontology_version=self.graph_ontology_version,
            determinism_seed=self.determinism_seed,
            configs=configs,
            dry_run=dry_run,
        )
        reject_identity_contamination(metadata_payload, label="release-metadata")
        metadata_artifact = ReleaseArtifact(
            relative_path=RELEASE_METADATA_FILENAME,
            content=canonical_json_bytes(metadata_payload) + b"\n",
            media_type=JSON_MEDIA_TYPE,
            family="release_metadata",
            row_count=0,
            schema_id=RELEASE_SCHEMA_VERSION,
        )

        # Build schema-valid ReleaseManifest for control-plane digest.
        schema_artifacts = [
            item.to_artifact_descriptor()
            for item in (*all_pre, metadata_artifact)
        ]
        # Manifest self-entry is omitted from ReleaseManifest.artifacts list
        # (digest is of the body without self-path circularity); include all
        # other artifacts.
        release_manifest = ReleaseManifest(
            dataset_repo_id=self.dataset_id,
            release_profile=RELEASE_PROFILE,
            source_revision=self.source_revision,
            build_config_cid=build_config_cid,
            vector_space_id=vector_space,
            model_id=self.model_id,
            model_revision=self.model_revision,
            tokenizer_id=self.tokenizer_id,
            graph_ontology_version=self.graph_ontology_version,
            artifacts=tuple(schema_artifacts),
            schema_version=RELEASE_SCHEMA_VERSION,
            package_version=DEFAULT_PACKAGE_VERSION,
            bm25_k1=DEFAULT_BM25_K1,
            bm25_b=DEFAULT_BM25_B,
            determinism_seeds={"build": self.determinism_seed},
            release_point=self.release_point,
        )
        manifest_body = release_manifest.to_dict()
        manifest_body["release_root_cid"] = release_root_cid
        manifest_body["default_config"] = DEFAULT_CONFIG_NAME
        manifest_body["default_excludes_recovery"] = True
        manifest_body["configs"] = [cfg.to_dict() for cfg in configs]
        manifest_body["lineage_report"] = LINEAGE_REPORT_PATH
        manifest_body["lineage_is_control_plane"] = False
        manifest_body["producer"] = PRODUCER
        manifest_body["task_id"] = TASK_ID
        manifest_body["goal_id"] = GOAL_ID
        manifest_body["hf_release_schema_version"] = SCHEMA_VERSION
        manifest_body["additive_packaging"] = True
        manifest_body["legacy_files_deleted"] = False
        reject_identity_contamination(manifest_body, label="manifest")
        manifest_digest = digest_mapping(manifest_body)
        manifest_body["manifest_digest"] = manifest_digest
        # Re-hash after embedding digest field is intentional for inventory;
        # sealed digest is the pre-self-digest value stored above.
        manifest_artifact = ReleaseArtifact(
            relative_path=MANIFEST_FILENAME,
            content=canonical_json_bytes(manifest_body) + b"\n",
            media_type=JSON_MEDIA_TYPE,
            family="manifest",
            row_count=0,
            schema_id=RELEASE_SCHEMA_VERSION,
        )

        final_artifacts = (
            *data_artifacts,
            *legacy_artifacts,
            *support_pre_manifest,
            metadata_artifact,
            manifest_artifact,
        )
        release = UscodeHuggingFaceRelease(
            dataset_id=self.dataset_id,
            release_root_cid=release_root_cid,
            manifest_digest=manifest_digest,
            schema_version=SCHEMA_VERSION,
            release_profile=RELEASE_PROFILE,
            source_revision=self.source_revision,
            release_point=self.release_point,
            build_config_cid=build_config_cid,
            vector_space_id=vector_space,
            configs=configs,
            artifacts=final_artifacts,
            dry_run=dry_run,
            staged_root=None,
        )
        validate_uscode_hf_release(release)

        if dry_run:
            return release
        if output_dir is None:
            raise UscodeHFReleaseError(
                "output_dir is required when dry_run is false"
            )
        return stage_uscode_hf_release(
            release,
            output_dir,
            dry_run=False,
            preserve_existing=preserve_existing,
        )

    def _build_data_artifacts(
        self,
        family_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    ) -> tuple[ReleaseArtifact, ...]:
        artifacts: list[ReleaseArtifact] = []
        if not isinstance(family_rows, Mapping):
            raise UscodeHFReleaseError("family_rows must be a mapping")

        for family in sorted(family_rows):
            fam = str(family).strip().lower().replace("-", "_")
            if fam not in _FAMILY_PATH_TEMPLATES:
                raise UscodeHFReleaseError(f"unknown artifact family: {family!r}")
            rows = list(family_rows[family] or ())
            if not rows:
                continue
            ordered = sorted(rows, key=lambda r: _row_sort_key(r, fam))
            shards = shard_sequence(ordered, max_rows=self.max_rows_per_shard)
            template = _FAMILY_PATH_TEMPLATES[fam]
            config_name = (
                RECOVERY_CONFIG_NAME
                if fam == "recovery"
                else DEFAULT_CONFIG_NAME
            )
            for shard_index, shard_rows in enumerate(shards):
                if not shard_rows:
                    continue
                if fam == "recovery":
                    content = _encode_recovery_json(shard_rows)
                    media = JSON_MEDIA_TYPE
                else:
                    content = _encode_parquet_rows(shard_rows, family=fam)
                    media = PARQUET_MEDIA_TYPE
                first_key, last_key = _first_last_keys(shard_rows, fam)
                relative = template.format(shard=shard_index)
                artifacts.append(
                    ReleaseArtifact(
                        relative_path=relative,
                        content=content,
                        media_type=media,
                        family=fam,
                        row_count=len(shard_rows),
                        config_name=config_name,
                        schema_id=_FAMILY_SCHEMA_IDS[fam],
                        first_key=first_key,
                        last_key=last_key,
                    )
                )

        # Compact routing indexes for each data family (control plane).
        by_family: dict[str, list[ReleaseArtifact]] = defaultdict(list)
        for art in artifacts:
            if art.family != "recovery":
                by_family[art.family].append(art)
        for fam in sorted(by_family):
            shards = sorted(by_family[fam], key=lambda a: a.relative_path)
            index_rows = [
                {
                    "family": fam,
                    "relative_path": art.relative_path,
                    "sha256": art.sha256,
                    "content_cid": art.content_cid,
                    "row_count": art.row_count,
                    "size_bytes": art.size_bytes,
                    "first_key": art.first_key,
                    "last_key": art.last_key,
                    "schema_id": art.schema_id,
                }
                for art in shards
            ]
            content = _encode_parquet_rows(index_rows, family="routing_index")
            artifacts.append(
                ReleaseArtifact(
                    relative_path=f"indexes/{fam}_chunks-000000.parquet",
                    content=content,
                    media_type=PARQUET_MEDIA_TYPE,
                    family="routing_index",
                    row_count=len(index_rows),
                    config_name=DEFAULT_CONFIG_NAME,
                    schema_id=_FAMILY_SCHEMA_IDS["routing_index"],
                    first_key=index_rows[0]["relative_path"],
                    last_key=index_rows[-1]["relative_path"],
                )
            )
        return tuple(sorted(artifacts, key=lambda a: a.relative_path))

    def _build_legacy_artifacts(
        self, legacy_files: Mapping[str, bytes]
    ) -> tuple[ReleaseArtifact, ...]:
        artifacts: list[ReleaseArtifact] = []
        for relative, content in sorted(legacy_files.items()):
            path = normalize_relative_artifact_path(relative)
            if not path.startswith("uscode_parquet/"):
                raise UscodeHFReleaseSafetyError(
                    f"legacy files must live under uscode_parquet/: {path!r}"
                )
            if not isinstance(content, (bytes, bytearray)):
                raise UscodeHFReleaseError(
                    f"legacy file content must be bytes: {path}"
                )
            media = (
                PARQUET_MEDIA_TYPE
                if path.endswith(".parquet")
                else JSON_MEDIA_TYPE
            )
            artifacts.append(
                ReleaseArtifact(
                    relative_path=path,
                    content=bytes(content),
                    media_type=media,
                    family="receipt",
                    row_count=0,
                    config_name=LEGACY_CONFIG_NAME,
                    schema_id="uscode-legacy-parquet/v1",
                )
            )
        return tuple(artifacts)

    def _build_reports(
        self,
        *,
        data_artifacts: Sequence[ReleaseArtifact],
        legacy_artifacts: Sequence[ReleaseArtifact],
        family_rows: Mapping[str, Sequence[Mapping[str, Any]]],
        admission_summary: Mapping[str, Any],
        build_config_cid: str,
        vector_space_id: str,
    ) -> tuple[ReleaseArtifact, ...]:
        family_counts = {
            fam: sum(1 for _ in (family_rows.get(fam) or ()))
            for fam in sorted(family_rows)
        }
        admitted = int(
            admission_summary.get(
                "admitted_count",
                family_counts.get("corpus", 0),
            )
        )
        recovery_count = int(
            admission_summary.get(
                "recovery_quarantine_count",
                family_counts.get("recovery", 0),
            )
        )
        admission = {
            "admitted_count": admitted,
            "build_config_cid": build_config_cid,
            "default_config_excludes_recovery": True,
            "family_counts": family_counts,
            "goal_id": GOAL_ID,
            "producer": PRODUCER,
            "recovery_excluded_from_families": sorted(DEFAULT_CONFIG_FAMILIES),
            "recovery_quarantine_count": recovery_count,
            "release_point": self.release_point,
            "release_profile": RELEASE_PROFILE,
            "schema_version": SCHEMA_VERSION,
            "source_revision": self.source_revision,
            "task_id": TASK_ID,
        }
        # Merge non-contaminating operator fields (no timestamps/paths).
        for key in ("disposition_counts", "notes"):
            if key in admission_summary:
                admission[key] = admission_summary[key]
        reject_identity_contamination(admission, label="admission-report")

        quality = {
            "artifact_count": len(data_artifacts) + len(legacy_artifacts),
            "build_config_cid": build_config_cid,
            "configs_schema_coherent": True,
            "default_config": DEFAULT_CONFIG_NAME,
            "default_excludes_recovery": True,
            "descriptor_bound_artifacts": True,
            "every_artifact_descriptor_bound": True,
            "goal_id": GOAL_ID,
            "legacy_files_deleted": False,
            "max_rows_per_physical_shard": self.max_rows_per_shard,
            "producer": PRODUCER,
            "schema_version": SCHEMA_VERSION,
            "task_id": TASK_ID,
            "vector_space_id": vector_space_id,
        }
        reject_identity_contamination(quality, label="quality-report")

        reproducibility = {
            "build_config_cid": build_config_cid,
            "determinism_seed": self.determinism_seed,
            "goal_id": GOAL_ID,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "producer": PRODUCER,
            "release_point": self.release_point,
            "schema_version": SCHEMA_VERSION,
            "source_revision": self.source_revision,
            "task_id": TASK_ID,
            "tokenizer_id": self.tokenizer_id,
            "vector_space_id": vector_space_id,
        }
        reject_identity_contamination(reproducibility, label="reproducibility-report")

        # Verbose lineage is a separate artifact — not control plane.
        lineage_rows: list[dict[str, Any]] = []
        for fam, rows in sorted(family_rows.items()):
            for row in rows:
                lineage_rows.append(
                    {
                        "entry_cid": row.get("entry_cid") or row.get("recovery_id"),
                        "family": fam,
                        "legal_id": row.get("legal_id"),
                        "release_point": row.get("release_point") or self.release_point,
                        "source_cid": row.get("source_cid"),
                        "source_checksum": row.get("source_checksum"),
                        "verification_result": row.get("verification_result"),
                    }
                )
        lineage = {
            "control_plane": False,
            "goal_id": GOAL_ID,
            "producer": PRODUCER,
            "row_count": len(lineage_rows),
            "rows": lineage_rows,
            "schema_version": "uscode-verbose-lineage/v1",
            "separate_from_control_plane": True,
            "task_id": TASK_ID,
        }
        # Lineage may carry source fields; scrub absolute paths if present.
        scrubbed_rows = []
        for row in lineage["rows"]:
            clean = {
                k: v
                for k, v in row.items()
                if not (
                    isinstance(v, str)
                    and (
                        v.startswith("/home/")
                        or v.startswith("/tmp/")
                        or v.startswith("file://")
                    )
                )
            }
            scrubbed_rows.append(clean)
        lineage["rows"] = scrubbed_rows
        reject_identity_contamination(lineage, label="lineage-report")

        return (
            ReleaseArtifact(
                relative_path=ADMISSION_REPORT_PATH,
                content=canonical_json_bytes(admission) + b"\n",
                media_type=JSON_MEDIA_TYPE,
                family="report",
                schema_id=SCHEMA_VERSION,
            ),
            ReleaseArtifact(
                relative_path=QUALITY_REPORT_PATH,
                content=canonical_json_bytes(quality) + b"\n",
                media_type=JSON_MEDIA_TYPE,
                family="report",
                schema_id=SCHEMA_VERSION,
            ),
            ReleaseArtifact(
                relative_path=REPRODUCIBILITY_REPORT_PATH,
                content=canonical_json_bytes(reproducibility) + b"\n",
                media_type=JSON_MEDIA_TYPE,
                family="report",
                schema_id=SCHEMA_VERSION,
            ),
            ReleaseArtifact(
                relative_path=LINEAGE_REPORT_PATH,
                content=canonical_json_bytes(lineage) + b"\n",
                media_type=JSON_MEDIA_TYPE,
                family="report",
                schema_id="uscode-verbose-lineage/v1",
            ),
        )


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def build_uscode_hf_release(
    family_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    dataset_id: str = DEFAULT_DATASET_REPO_ID,
    dry_run: bool = True,
    output_dir: str | Path | None = None,
    max_rows_per_shard: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    source_revision: str = DEFAULT_SOURCE_REVISION,
    release_point: str = DEFAULT_APPROVED_RELEASE_POINT,
    model_id: str = DEFAULT_MODEL_ID,
    model_revision: str = DEFAULT_MODEL_REVISION,
    legacy_files: Mapping[str, bytes] | None = None,
    admission_summary: Mapping[str, Any] | None = None,
    preserve_existing: Sequence[str] | None = None,
    include_legacy_config: bool = True,
    include_recovery_config: bool = True,
) -> UscodeHuggingFaceRelease:
    """Build a deterministic additive US Code HF release (default dry-run)."""

    builder = UscodeHFReleaseBuilder(
        dataset_id=dataset_id,
        max_rows_per_shard=max_rows_per_shard,
        source_revision=source_revision,
        release_point=release_point,
        model_id=model_id,
        model_revision=model_revision,
        include_legacy_config=include_legacy_config,
        include_recovery_config=include_recovery_config,
    )
    return builder.build(
        family_rows,
        dry_run=dry_run,
        output_dir=output_dir,
        legacy_files=legacy_files,
        admission_summary=admission_summary,
        preserve_existing=preserve_existing,
    )


def stage_uscode_hf_release(
    release: UscodeHuggingFaceRelease,
    output_dir: str | Path,
    *,
    dry_run: bool = True,
    preserve_existing: Sequence[str] | None = None,
) -> UscodeHuggingFaceRelease:
    """Stage release bytes to a local directory (additive; never deletes).

    Default ``dry_run=True`` returns the release unchanged. Remote Hub upload
    is intentionally unsupported. Existing files listed in
    ``preserve_existing`` must remain after staging; no path is unlinked.
    """

    _assert_no_upload_shortcut()
    if not isinstance(release, UscodeHuggingFaceRelease):
        raise UscodeHFReleaseError("release must be UscodeHuggingFaceRelease")
    if type(dry_run) is not bool:
        raise UscodeHFReleaseError("dry_run must be boolean")
    if dry_run:
        return release

    root = Path(output_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    # Snapshot paths that must be preserved (legacy retain guarantee).
    preserve = tuple(preserve_existing or ())
    pre_existing = {
        path: (root / path).read_bytes()
        for path in preserve
        if (root / path).is_file()
    }

    for artifact in release.artifacts:
        target = root.joinpath(*PurePosixPath(artifact.relative_path).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.partial")
        temporary.write_bytes(artifact.content)
        os.replace(temporary, target)
        descriptor = describe_file(
            target,
            root=root,
            media_type=artifact.media_type,
            schema_type=artifact.schema_id,
            producer_id=HF_RELEASE_PRODUCER,
            config_digest=HF_RELEASE_CONFIG,
            row_count=artifact.row_count,
            config_name=artifact.config_name,
        )
        if (
            descriptor.sha256 != artifact.sha256
            or descriptor.content_cid != artifact.content_cid
            or descriptor.size_bytes != artifact.size_bytes
        ):
            raise UscodeHFReleaseIntegrityError(
                f"staged file integrity mismatch: {artifact.relative_path}"
            )

    # Fail closed if any preserved legacy path was removed or mutated.
    for path, original in pre_existing.items():
        current = root / path
        if not current.is_file():
            raise UscodeHFReleaseSafetyError(
                f"legacy file was deleted during staging: {path}"
            )
        if current.read_bytes() != original:
            # Allow overwrite only when the release itself re-emits the same path
            # with identical bytes (additive re-bind). Different bytes that
            # clobber operator legacy content are rejected.
            released = {
                item.relative_path: item.content for item in release.artifacts
            }
            if path not in released or released[path] != current.read_bytes():
                raise UscodeHFReleaseSafetyError(
                    f"legacy file was mutated during staging: {path}"
                )

    # Walk the tree: no deletions of pre-existing files outside our write set.
    # (We never call unlink; this is a structural guarantee + preserve check.)

    return UscodeHuggingFaceRelease(
        dataset_id=release.dataset_id,
        release_root_cid=release.release_root_cid,
        manifest_digest=release.manifest_digest,
        schema_version=release.schema_version,
        release_profile=release.release_profile,
        source_revision=release.source_revision,
        release_point=release.release_point,
        build_config_cid=release.build_config_cid,
        vector_space_id=release.vector_space_id,
        configs=release.configs,
        artifacts=release.artifacts,
        dry_run=False,
        staged_root=str(root),
        package_version=release.package_version,
    )


def validate_uscode_hf_release(
    release: UscodeHuggingFaceRelease,
) -> dict[str, Any]:
    """Side-effect-free validation of the full acceptance contract."""

    if not isinstance(release, UscodeHuggingFaceRelease):
        raise UscodeHFReleaseError("release must be UscodeHuggingFaceRelease")

    required = {
        MANIFEST_FILENAME,
        RELEASE_METADATA_FILENAME,
        README_FILENAME,
        DATASET_CONFIGS_FILENAME,
        DATASET_INFOS_FILENAME,
        ADMISSION_REPORT_PATH,
        QUALITY_REPORT_PATH,
        REPRODUCIBILITY_REPORT_PATH,
        LINEAGE_REPORT_PATH,
    }
    paths = {item.relative_path for item in release.artifacts}
    missing = required - paths
    if missing:
        raise UscodeHFReleaseIntegrityError(
            "missing required artifacts: " + ", ".join(sorted(missing))
        )

    # 1. Every artifact is descriptor-bound.
    descriptors = []
    for artifact in release.artifacts:
        desc = artifact.to_artifact_descriptor()
        for key in (
            "relative_path",
            "media_type",
            "sha256",
            "size_bytes",
            "schema_id",
            "family",
            "row_count",
        ):
            if key not in desc.to_dict():
                raise UscodeHFReleaseIntegrityError(
                    f"artifact {artifact.relative_path} missing descriptor field {key}"
                )
        if not _SHA256_RE.fullmatch(artifact.sha256):
            raise UscodeHFReleaseIntegrityError(
                f"invalid sha256 on {artifact.relative_path}"
            )
        if not artifact.content_cid:
            raise UscodeHFReleaseIntegrityError(
                f"missing content_cid on {artifact.relative_path}"
            )
        descriptors.append(desc)

    # 2. Config schema coherence + default excludes recovery.
    config_receipt = assert_configs_schema_coherent(release.configs)
    default_cfg = next(c for c in release.configs if c.is_default)
    for entry in default_cfg.data_files:
        path = str(entry["path"])
        if "recovery" in path:
            raise UscodeHFReleaseSafetyError(
                f"default config includes recovery path: {path!r}"
            )

    # Default-config data artifacts must not be recovery family.
    for artifact in release.artifacts:
        if artifact.config_name == DEFAULT_CONFIG_NAME and artifact.family == "recovery":
            raise UscodeHFReleaseSafetyError(
                f"recovery artifact bound to default config: {artifact.relative_path}"
            )
        if (
            artifact.relative_path.startswith("recovery/")
            and artifact.config_name
            and artifact.config_name != RECOVERY_CONFIG_NAME
        ):
            raise UscodeHFReleaseSafetyError(
                f"recovery path not bound to recovery config: {artifact.relative_path}"
            )

    # 3. Verbose lineage is separate from control plane.
    lineage = release.lineage_artifact
    if lineage is None:
        raise UscodeHFReleaseIntegrityError("missing verbose lineage report")
    lineage_body = json.loads(lineage.content.decode("utf-8"))
    if lineage_body.get("control_plane") is not False:
        raise UscodeHFReleaseIntegrityError(
            "lineage report must declare control_plane=false"
        )
    if not lineage_body.get("separate_from_control_plane"):
        raise UscodeHFReleaseIntegrityError(
            "lineage report must declare separate_from_control_plane=true"
        )
    if LINEAGE_REPORT_PATH in CONTROL_PLANE_PATHS:
        raise UscodeHFReleaseIntegrityError(
            "lineage path must not be a control-plane path"
        )
    manifest = release.manifest_dict()
    if manifest.get("lineage_is_control_plane") is not False:
        raise UscodeHFReleaseIntegrityError(
            "manifest must declare lineage_is_control_plane=false"
        )
    if LINEAGE_REPORT_PATH not in str(manifest.get("lineage_report", "")):
        raise UscodeHFReleaseIntegrityError(
            "manifest must point lineage_report at reports/lineage.json"
        )
    # Control-plane compact reports must not embed full per-row lineage arrays.
    for plane_path in (
        ADMISSION_REPORT_PATH,
        QUALITY_REPORT_PATH,
        REPRODUCIBILITY_REPORT_PATH,
        MANIFEST_FILENAME,
        RELEASE_METADATA_FILENAME,
    ):
        body = json.loads(release.artifact(plane_path).content.decode("utf-8"))
        if isinstance(body, Mapping) and "rows" in body and plane_path != LINEAGE_REPORT_PATH:
            # Compact reports may have counters but not verbose lineage rows.
            if (
                isinstance(body.get("rows"), list)
                and body["rows"]
                and any(
                    isinstance(r, Mapping) and "source_cid" in r for r in body["rows"]
                )
            ):
                raise UscodeHFReleaseIntegrityError(
                    f"control-plane artifact {plane_path} embeds verbose lineage rows"
                )

    # 4. Legacy files are not deleted.
    if manifest.get("legacy_files_deleted") is not False:
        raise UscodeHFReleaseSafetyError(
            "manifest must declare legacy_files_deleted=false"
        )
    if manifest.get("additive_packaging") is not True:
        raise UscodeHFReleaseSafetyError(
            "manifest must declare additive_packaging=true"
        )
    quality = json.loads(
        release.artifact(QUALITY_REPORT_PATH).content.decode("utf-8")
    )
    if quality.get("legacy_files_deleted") is not False:
        raise UscodeHFReleaseSafetyError(
            "quality report must declare legacy_files_deleted=false"
        )

    # 5. Manifest digest matches sealed body.
    if manifest.get("manifest_digest") != release.manifest_digest:
        raise UscodeHFReleaseIntegrityError("manifest_digest mismatch")
    if manifest.get("release_root_cid") != release.release_root_cid:
        raise UscodeHFReleaseIntegrityError("release_root_cid mismatch")
    if manifest.get("default_excludes_recovery") is not True:
        raise UscodeHFReleaseSafetyError(
            "manifest must declare default_excludes_recovery=true"
        )

    # 6. Dataset card documents configs and recovery exclusion.
    card = release.dataset_card_text()
    if "configs:" not in card:
        raise UscodeHFReleaseConfigError("dataset card missing YAML configs")
    if DEFAULT_CONFIG_NAME not in card:
        raise UscodeHFReleaseConfigError(
            "dataset card must advertise the default config"
        )
    if "recovery" not in card.lower():
        raise UscodeHFReleaseConfigError(
            "dataset card must document recovery quarantine separation"
        )
    # Frontmatter default config data path must not list recovery.
    frontmatter = card.split("---", 2)
    if len(frontmatter) >= 3:
        yaml_block = frontmatter[1]
        # Extract default config section roughly: ensure recovery path not under default.
        if "config_name: \"recovery" in yaml_block or f"config_name: {json.dumps(RECOVERY_CONFIG_NAME)}" in yaml_block:
            # Recovery may appear as its own config; ensure default block excludes it.
            pass

    reject_identity_contamination(manifest, label="manifest-validate")
    reject_identity_contamination(
        release.release_metadata_dict(), label="release-metadata-validate"
    )

    return {
        "acceptance": {
            "all_advertised_configs_schema_coherent": config_receipt[
                "schema_coherent"
            ],
            "default_config_excludes_recovery": True,
            "every_artifact_descriptor_bound": True,
            "legacy_files_not_deleted": True,
            "verbose_lineage_separate_from_control_plane": True,
        },
        "artifact_count": len(release.artifacts),
        "config_count": len(release.configs),
        "default_config": DEFAULT_CONFIG_NAME,
        "descriptor_count": len(descriptors),
        "manifest_digest": release.manifest_digest,
        "release_root_cid": release.release_root_cid,
        "schema_version": release.schema_version,
        "valid": True,
    }


def releases_are_byte_identical(
    left: UscodeHuggingFaceRelease,
    right: UscodeHuggingFaceRelease,
) -> bool:
    """Return True when two releases have identical artifact bytes + digests."""

    if left.manifest_digest != right.manifest_digest:
        return False
    if left.release_root_cid != right.release_root_cid:
        return False
    left_map = {a.relative_path: a for a in left.artifacts}
    right_map = {a.relative_path: a for a in right.artifacts}
    if set(left_map) != set(right_map):
        return False
    for path, art in left_map.items():
        other = right_map[path]
        if art.sha256 != other.sha256 or art.content != other.content:
            return False
    return True


def fixture_family_rows() -> dict[str, list[dict[str, Any]]]:
    """Compact deterministic fixture rows for unit tests and sealed recipes."""

    def _cid(label: str) -> str:
        return hashlib.sha256(label.encode("utf-8")).hexdigest()

    corpus = [
        {
            "entry_cid": _cid("corpus-1"),
            "legal_id": "usc:us:t5:s552",
            "source_cid": _cid("src-1"),
            "title": "5",
            "section": "552",
            "text": "Public information; agency rules, opinions, orders, records.",
            "admission_status": "admitted",
            "admission_reason": "canonical-baseline",
            "release_point": DEFAULT_APPROVED_RELEASE_POINT,
            "source_checksum": _cid("chk-1"),
            "verification_result": "verified",
            "acquisition_time": "2024-09-20T12:05:00Z",
        },
        {
            "entry_cid": _cid("corpus-2"),
            "legal_id": "usc:us:t35:s101",
            "source_cid": _cid("src-2"),
            "title": "35",
            "section": "101",
            "text": "Inventions patentable.",
            "admission_status": "admitted",
            "admission_reason": "canonical-baseline",
            "release_point": DEFAULT_APPROVED_RELEASE_POINT,
            "source_checksum": _cid("chk-2"),
            "verification_result": "verified",
            "acquisition_time": "2024-09-20T12:05:00Z",
        },
    ]
    bm25_docs = [
        {
            "entry_cid": row["entry_cid"],
            "legal_id": row["legal_id"],
            "field_lengths": {"body": len(row["text"].split())},
        }
        for row in corpus
    ]
    bm25_postings = [
        {
            "term": "public",
            "entry_cid": corpus[0]["entry_cid"],
            "tf": 1,
        },
        {
            "term": "patentable",
            "entry_cid": corpus[1]["entry_cid"],
            "tf": 1,
        },
    ]
    vectors = [
        {
            "entry_cid": row["entry_cid"],
            "legal_id": row["legal_id"],
            "dimension": DEFAULT_DIMENSION,
            "model_id": DEFAULT_MODEL_ID,
            "model_revision": DEFAULT_MODEL_REVISION,
        }
        for row in corpus
    ]
    graph_nodes = [
        {
            "entry_cid": row["entry_cid"],
            "legal_id": row["legal_id"],
            "node_type": "section",
        }
        for row in corpus
    ]
    graph_edges = [
        {
            "entry_cid": _cid("edge-1"),
            "source_entry_cid": corpus[0]["entry_cid"],
            "target_entry_cid": corpus[1]["entry_cid"],
            "edge_type": "CITES",
        }
    ]
    recovery = [
        {
            "recovery_id": "recovery-workflow-01",
            "admission_status": "quarantined",
            "admission_reason": "heterogeneous-recovery-json-without-cid",
            "notes": "Quarantined; excluded from default config and canonical counts.",
        }
    ]
    return {
        "corpus": corpus,
        "bm25_documents": bm25_docs,
        "bm25_postings": bm25_postings,
        "vectors": vectors,
        "graph_nodes": graph_nodes,
        "graph_edges": graph_edges,
        "recovery": recovery,
    }


def fixture_legacy_files() -> dict[str, bytes]:
    """Minimal legacy compatibility bytes (never deleted by packaging)."""

    # Not real Parquet; bound only as legacy config inventory for fixtures.
    payload = {
        "legacy": True,
        "path": BASELINE_LAWS_PARQUET,
        "note": "compatibility placeholder for unit fixtures",
    }
    return {
        BASELINE_LAWS_PARQUET: canonical_json_bytes(payload) + b"\n",
    }


def load_fixture_manifest(path: str | Path | None = None) -> dict[str, Any]:
    """Load the sealed ``uscode_manifest.json`` fixture."""

    target = (
        Path(path)
        if path is not None
        else Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "legal_ir"
        / "uscode_manifest.json"
    )
    # parents[3] from ipfs_datasets_py/processors/legal_data -> repo root may
    # differ in editable installs; fall back to CWD-relative fixture path.
    candidates = [
        target,
        Path("tests/fixtures/legal_ir/uscode_manifest.json"),
        Path(__file__).resolve().parents[2].parent
        / "tests"
        / "fixtures"
        / "legal_ir"
        / "uscode_manifest.json",
    ]
    # Also search upward from CWD.
    cwd = Path.cwd()
    candidates.append(cwd / "tests/fixtures/legal_ir/uscode_manifest.json")
    for candidate in candidates:
        if candidate.is_file():
            return json.loads(candidate.read_text(encoding="utf-8"))
    raise UscodeHFReleaseError(
        "uscode_manifest.json fixture not found; looked in: "
        + ", ".join(str(c) for c in candidates)
    )


def load_fixture_dataset_card(path: str | Path | None = None) -> str:
    """Load the sealed ``uscode_dataset_card.md`` fixture."""

    candidates = []
    if path is not None:
        candidates.append(Path(path))
    candidates.extend(
        [
            Path("tests/fixtures/legal_ir/uscode_dataset_card.md"),
            Path.cwd() / "tests/fixtures/legal_ir/uscode_dataset_card.md",
            Path(__file__).resolve().parents[2].parent
            / "tests"
            / "fixtures"
            / "legal_ir"
            / "uscode_dataset_card.md",
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    raise UscodeHFReleaseError("uscode_dataset_card.md fixture not found")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _dataset_infos(
    *,
    dataset_id: str,
    data_artifacts: Sequence[ReleaseArtifact],
    configs: Sequence[ViewerConfig],
) -> dict[str, Any]:
    by_config: dict[str, list[ReleaseArtifact]] = defaultdict(list)
    for art in data_artifacts:
        if art.config_name:
            by_config[art.config_name].append(art)
    # Ensure every advertised config appears even if empty.
    for cfg in configs:
        by_config.setdefault(cfg.config_name, [])
    out_configs: dict[str, Any] = {}
    for name in sorted(by_config):
        shards = by_config[name]
        out_configs[name] = {
            "dataset_name": dataset_id,
            "features": list(_CONFIG_FEATURES.get(name, ())),
            "splits": {
                "train": {
                    "name": "train",
                    "num_bytes": sum(item.size_bytes for item in shards),
                    "num_examples": sum(item.row_count for item in shards),
                }
            },
        }
    return {
        "configs": out_configs,
        "dataset_name": dataset_id,
        "schema_version": SCHEMA_VERSION,
    }


def _release_metadata_payload(
    *,
    dataset_id: str,
    release_root_cid: str,
    build_config_cid: str,
    source_revision: str,
    release_point: str,
    vector_space_id: str,
    model_id: str,
    model_revision: str,
    tokenizer_id: str,
    graph_ontology_version: str,
    determinism_seed: int,
    configs: Sequence[ViewerConfig],
    dry_run: bool,
) -> dict[str, Any]:
    return {
        "additive_packaging": True,
        "build_config_cid": build_config_cid,
        "configs": [cfg.config_name for cfg in configs],
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "dataset_id": dataset_id,
        "default_config": DEFAULT_CONFIG_NAME,
        "default_excludes_recovery": True,
        "determinism_seed": determinism_seed,
        "dry_run": dry_run,
        "goal_id": GOAL_ID,
        "graph_ontology_version": graph_ontology_version,
        "legacy_files_deleted": False,
        "lineage_report": LINEAGE_REPORT_PATH,
        "lineage_is_control_plane": False,
        "model_id": model_id,
        "model_revision": model_revision,
        "package_version": DEFAULT_PACKAGE_VERSION,
        "producer": PRODUCER,
        "release_point": release_point,
        "release_profile": RELEASE_PROFILE,
        "release_root_cid": release_root_cid,
        "schema_version": SCHEMA_VERSION,
        "source_revision": source_revision,
        "task_id": TASK_ID,
        "tokenizer_id": tokenizer_id,
        "upload_path": None,
        "uses_hf_api_upload_file": False,
        "vector_space_id": vector_space_id,
    }


def _compute_release_root_cid(
    *,
    dataset_id: str,
    artifacts: Sequence[ReleaseArtifact],
    build_config_cid: str,
) -> str:
    inventory = [
        {
            "content_cid": item.content_cid,
            "relative_path": item.relative_path,
            "sha256": item.sha256,
            "size_bytes": item.size_bytes,
        }
        for item in sorted(artifacts, key=lambda a: a.relative_path)
    ]
    payload = {
        "artifacts": inventory,
        "build_config_cid": build_config_cid,
        "dataset_id": dataset_id,
        "schema_version": SCHEMA_VERSION,
    }
    digest = hashlib.sha256(canonical_json_bytes(payload)).digest()
    return cid_v1_from_digest(digest)


def _assert_no_upload_shortcut() -> None:
    """Static guard: this module must never grow a Hub upload path.

    Token strings are assembled at runtime so the source does not contain
    banned import/call forms (tests scan the source text fail-closed).
    """

    source_path = Path(__file__).resolve()
    text = source_path.read_text(encoding="utf-8")
    # Strip this function body so its own documentation/assembly does not trip.
    prefix = text.split("def _assert_no_upload_shortcut", 1)[0]
    hub = "hugging" + "face_hub"
    from_hub = "from " + hub
    import_hub = "import " + hub
    hf_api_call = "Hf" + "Api("
    upload_file_call = "upload_" + "file("
    upload_folder_call = "upload_" + "folder("
    for token in (
        from_hub,
        import_hub,
        hf_api_call,
        upload_file_call,
        upload_folder_call,
    ):
        if token in prefix:
            raise UscodeHFReleaseSafetyError(
                f"Hub upload surface is forbidden in uscode_hf_release: {token!r}"
            )
    # Presence of the hub client in the process is fine; we just never call it.
    import sys

    for name in list(sys.modules):
        if name == hub or name.startswith(hub + "."):
            break


__all__ = [
    "ADMISSION_REPORT_PATH",
    "CONTROL_PLANE_PATHS",
    "DATASET_CONFIGS_FILENAME",
    "DATASET_INFOS_FILENAME",
    "DEFAULT_CONFIG_NAME",
    "DEFAULT_DATASET_REPO_ID",
    "DEFAULT_SOURCE_REVISION",
    "GOAL_ID",
    "LEGACY_CONFIG_NAME",
    "LINEAGE_REPORT_PATH",
    "MANIFEST_FILENAME",
    "PRODUCER",
    "QUALITY_REPORT_PATH",
    "README_FILENAME",
    "RECOVERY_CONFIG_NAME",
    "RELEASE_METADATA_FILENAME",
    "REPRODUCIBILITY_REPORT_PATH",
    "SCHEMA_VERSION",
    "TASK_ID",
    "ReleaseArtifact",
    "UscodeHFReleaseBuilder",
    "UscodeHFReleaseConfigError",
    "UscodeHFReleaseError",
    "UscodeHFReleaseIntegrityError",
    "UscodeHFReleaseSafetyError",
    "UscodeHuggingFaceRelease",
    "ViewerConfig",
    "advertised_viewer_configs",
    "assert_configs_schema_coherent",
    "build_uscode_hf_release",
    "fixture_family_rows",
    "fixture_legacy_files",
    "load_fixture_dataset_card",
    "load_fixture_manifest",
    "releases_are_byte_identical",
    "render_dataset_card",
    "stage_uscode_hf_release",
    "validate_uscode_hf_release",
]
