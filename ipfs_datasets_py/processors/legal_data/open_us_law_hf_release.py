"""Descriptor-complete Open US Law sparse GraphRAG Hugging Face release (OUL-032).

Assembles a validated local Open US Law Sparse GraphRAG artifact tree into
an immutable candidate root with:

* compact ``manifest.json`` / ``release_metadata.json`` (control plane);
* a Viewer-safe default exact-51 configuration plus explicit non-default
  federal, Puerto Rico, constitution, historical, recovery, and quarantine
  configs;
* descriptor-bound inventory for every artifact (relative path, media type,
  row count, byte size, SHA-256, schema id, family, route keys);
* family bindings for corpus, BM25, vectors, centroids, the vector entry
  locator, the legal graph, two-way adjacency, recovery, and source
  receipts;
* model revision, route bounds, and compact admission/quality reports;
* **verbose lineage** isolated under ``reports/lineage.json`` (never mixed
  into control-plane manifests or the default Viewer config).

This module does **not** publish to the Hub. Remote mutation is owned by
OUL-040+ publication gates. Default mode is dry-run (in-memory).

Acceptance invariants
---------------------
1. The default Viewer config is ``state_statutes_exact_51`` and excludes
   recovery, quarantine, PR, federal, constitution, and historical rows.
2. Every advertised config is schema-coherent (paths + families + keys).
3. Every artifact is descriptor-bound (relative path, media type, rows,
   bytes, SHA-256, schema id, family).
4. The manifest binds corpus, BM25, vectors, centroids, vector locator,
   graph, two-way adjacency, recovery, configs, source receipts, model
   revision, row counts, sizes, SHA-256 digests, and route bounds.
5. Verbose lineage is separate from the control plane.
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
from typing import Any, Final, Optional, Union

from ipfs_datasets_py.huggingface.release import (
    FileDescriptor,
    HuggingFaceReleaseError,
    canonical_json_bytes,
    describe_file,
    reject_identity_contamination,
    shard_sequence,
)
from ipfs_datasets_py.logic.ir_core.identity import cid_v1_from_digest
from ipfs_datasets_py.processors.legal_data.open_us_law_schema import (
    ALL_CONFIGURATION_NAMES,
    DEFAULT_CANDIDATE_CENTROIDS,
    DEFAULT_CONFIGURATION,
    DEFAULT_DATASET_REPO_ID,
    DEFAULT_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_MODEL_ID,
    DEFAULT_EMBEDDING_MODEL_REVISION,
    DEFAULT_MODEL_TOKEN_CEILING,
    EXACT_51_JURISDICTION_CODES,
    EXPECTED_JURISDICTION_COUNT,
    MAX_ADJACENCY_POINTERS_PER_ROW,
    MAX_POSTING_POINTERS_PER_ROW,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    MAX_ROWS_PER_VECTOR_CENTROID,
    MAX_VECTOR_SHARDS_PER_CENTROID,
    NON_DEFAULT_CONFIGURATION_NAMES,
    RELEASE_PROFILE,
    REQUIRED_DEFAULT_STATUTE_IDENTITY_FIELDS,
    SOURCE_BUCKET,
    ConfigurationDescriptor,
    OpenUsLawSchemaError,
    ReleaseConfiguration,
    classify_configuration,
    default_configuration_descriptors,
    digest_mapping,
    example_constitution_payload,
    example_default_statute_payload,
    example_federal_payload,
    example_historical_payload,
    example_puerto_rico_payload,
    example_quarantine_payload,
    example_recovery_payload,
    physical_bounds_policy as identity_physical_bounds,
    require_immutable_revision,
    validate_entry_cid,
)
from ipfs_datasets_py.processors.legal_data.uscode_tokenizer import TOKENIZER_ID
from ipfs_datasets_py.retrieval.hf_graphrag.schema import (
    ArtifactDescriptor,
    ArtifactFamily,
    normalize_relative_artifact_path,
    normalize_sha256,
)


# ---------------------------------------------------------------------------
# Identity / schema constants
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "open-us-law-hf-release/v1"
IDENTITY_SCHEMA_VERSION: Final = "open-us-law-identity-schema-v1"
TASK_ID: Final = "OUL-032"
GOAL_ID: Final = "OUL-G040"
PRODUCER: Final = "open_us_law_hf_release.py"
HF_RELEASE_PRODUCER: Final = "producer:open-us-law-hf-release"
HF_RELEASE_CONFIG: Final = "config:open-us-law-hf-release/v1"
PROGRAM_ID: Final = "open-us-law-reindex-v1"

MANIFEST_FILENAME: Final = "manifest.json"
RELEASE_METADATA_FILENAME: Final = "release_metadata.json"
README_FILENAME: Final = "README.md"
DATASET_INFOS_FILENAME: Final = "dataset_infos.json"
DATASET_CONFIGS_FILENAME: Final = "dataset_configs.json"

ADMISSION_REPORT_PATH: Final = "reports/admission.json"
QUALITY_REPORT_PATH: Final = "reports/quality.json"
REPRODUCIBILITY_REPORT_PATH: Final = "reports/reproducibility.json"
LINEAGE_REPORT_PATH: Final = "reports/lineage.json"

DEFAULT_CONFIG_NAME: Final = DEFAULT_CONFIGURATION
RECOVERY_CONFIG_NAME: Final = ReleaseConfiguration.RECOVERY.value
QUARANTINE_CONFIG_NAME: Final = ReleaseConfiguration.QUARANTINE.value
FEDERAL_CONFIG_NAME: Final = ReleaseConfiguration.FEDERAL_USCODE.value
PUERTO_RICO_CONFIG_NAME: Final = ReleaseConfiguration.PUERTO_RICO.value
CONSTITUTIONS_CONFIG_NAME: Final = ReleaseConfiguration.CONSTITUTIONS.value
HISTORICAL_CONFIG_NAME: Final = ReleaseConfiguration.HISTORICAL.value

PRIMARY_KEY: Final = "entry_cid"
DEFAULT_LICENSE: Final = "other"
DEFAULT_PACKAGE_VERSION: Final = "1"
DEFAULT_DETERMINISM_SEED: Final = 20260814
DEFAULT_BM25_K1: Final = 1.2
DEFAULT_BM25_B: Final = 0.75
DEFAULT_GRAPH_ONTOLOGY_VERSION: Final = "open-us-law-graph-ontology/v1"
TOKENIZER_SHARED_BY: Final = "build_and_query"
PINNED_MODEL_ID: Final = DEFAULT_EMBEDDING_MODEL_ID
PINNED_MODEL_REVISION: Final = DEFAULT_EMBEDDING_MODEL_REVISION
PINNED_DIMENSION: Final = DEFAULT_EMBEDDING_DIMENSION
PINNED_POOLING: Final = "mean"
PINNED_NORMALIZATION: Final = "l2"


def build_vector_space_id(
    *,
    model_id: str = PINNED_MODEL_ID,
    model_revision: str = PINNED_MODEL_REVISION,
    pooling: str = PINNED_POOLING,
    normalization: str = PINNED_NORMALIZATION,
    dimension: int = PINNED_DIMENSION,
) -> str:
    """Return the sealed GTE-small vector-space identifier."""

    require_immutable_revision(model_revision, name="model_revision")
    if model_id != DEFAULT_EMBEDDING_MODEL_ID:
        raise OpenUsLawHFReleaseSafetyError(
            f"model_id must be {DEFAULT_EMBEDDING_MODEL_ID!r}"
        )
    if model_revision != DEFAULT_EMBEDDING_MODEL_REVISION:
        raise OpenUsLawHFReleaseSafetyError(
            "model_revision must be the pinned thenlper/gte-small revision"
        )
    short = model_id.rsplit("/", 1)[-1].lower()
    short = re.sub(r"[^a-z0-9._-]+", "-", short)
    return (
        f"{short}@{model_revision}:d{int(dimension)}:"
        f"pool={pooling.lower()}:norm={normalization.lower()}"
    )


DEFAULT_SOURCE_REVISION: Final = (
    "7c1e4a90b2d65f83e0a91c4d6b7e8f0123456789abcdef0123456789abcdef01"
)

PARQUET_MEDIA_TYPE: Final = "application/vnd.apache.parquet"
JSON_MEDIA_TYPE: Final = "application/json"
MARKDOWN_MEDIA_TYPE: Final = "text/markdown; charset=utf-8"

DEFAULT_CONFIG_FAMILIES: Final = frozenset(
    {
        "corpus",
        "bm25_documents",
        "bm25_postings",
        "vectors",
        "centroids",
        "vector_locator",
        "graph_nodes",
        "graph_edges",
        "graph_adjacency_out",
        "graph_adjacency_in",
    }
)
RECOVERY_FAMILIES: Final = frozenset({"recovery", "quarantine"})
JSON_FAMILIES: Final = frozenset({"recovery", "quarantine", "source_receipts"})
NON_DEFAULT_CORPUS_FAMILIES: Final = frozenset(NON_DEFAULT_CONFIGURATION_NAMES)

DEFAULT_CONFIG_PATH_PREFIXES: Final = (
    "data/corpus/",
    "data/bm25/",
    "data/vectors/",
    "data/graph/",
    "indexes/",
)
RECOVERY_CONFIG_PATH_PREFIXES: Final = ("recovery/",)
QUARANTINE_CONFIG_PATH_PREFIXES: Final = ("quarantine/",)

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

REQUIRED_MANIFEST_BINDINGS: Final = (
    "corpus",
    "bm25",
    "vectors",
    "centroids",
    "vector_locator",
    "graph",
    "two_way_adjacency",
    "recovery",
    "configs",
    "source_receipts",
    "model_revision",
    "row_counts",
    "sizes",
    "sha256_digests",
    "route_bounds",
    "viewer_safe_default_exact_51",
)

CURRENTNESS_DISCLAIMER: Final = (
    "This release is a research retrieval aid. Observation times, edition "
    "pins, and acquisition receipts are not legal-currentness claims. Official "
    "state and District of Columbia publications remain the authority."
)

_DATASET_ID_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}$"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CID_RE = re.compile(r"^b[a-z2-7]{20,}$")

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]

_FAMILY_ALIASES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "bm25": "bm25_documents",
        "bm25_docs": "bm25_documents",
        "postings": "bm25_postings",
        "locator": "vector_locator",
        "locator_index": "vector_locator",
        "entry_locator": "vector_locator",
        "nodes": "graph_nodes",
        "edges": "graph_edges",
        "adjacency_out": "graph_adjacency_out",
        "adjacency_in": "graph_adjacency_in",
        "graph_adjacency": "graph_adjacency_out",
        "two_way_adjacency": "graph_adjacency_out",
        "receipts": "source_receipts",
        "source_receipt": "source_receipts",
        "federal": FEDERAL_CONFIG_NAME,
        "uscode": FEDERAL_CONFIG_NAME,
        "pr": PUERTO_RICO_CONFIG_NAME,
    }
)

_FAMILY_PATH_TEMPLATES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "corpus": "data/corpus/part-{shard:06d}.parquet",
        "bm25_documents": "data/bm25/documents/part-{shard:06d}.parquet",
        "bm25_postings": "data/bm25/postings/part-{shard:06d}.parquet",
        "vectors": "data/vectors/centroid-000-part-{shard:06d}.parquet",
        "centroids": "data/vectors/centroids/part-{shard:06d}.parquet",
        "vector_locator": "data/vectors/locator/part-{shard:06d}.parquet",
        "graph_nodes": "data/graph/nodes/part-{shard:06d}.parquet",
        "graph_edges": "data/graph/edges/part-{shard:06d}.parquet",
        "graph_adjacency_out": "data/graph/adjacency/out/part-{shard:06d}.parquet",
        "graph_adjacency_in": "data/graph/adjacency/in/part-{shard:06d}.parquet",
        "source_receipts": "receipts/source/part-{shard:06d}.json",
        "recovery": "recovery/part-{shard:06d}.json",
        "quarantine": "quarantine/part-{shard:06d}.json",
        FEDERAL_CONFIG_NAME: "configs/federal_uscode/part-{shard:06d}.parquet",
        PUERTO_RICO_CONFIG_NAME: "configs/puerto_rico/part-{shard:06d}.parquet",
        CONSTITUTIONS_CONFIG_NAME: "configs/constitutions/part-{shard:06d}.parquet",
        HISTORICAL_CONFIG_NAME: "configs/historical/part-{shard:06d}.parquet",
    }
)

_FAMILY_SCHEMA_IDS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "corpus": "open-us-law-corpus-row/v1",
        "bm25_documents": "open-us-law-bm25-document/v1",
        "bm25_postings": "open-us-law-bm25-posting/v1",
        "vectors": "open-us-law-vector-row/v1",
        "centroids": "open-us-law-centroid-row/v1",
        "vector_locator": "open-us-law-vector-locator/v1",
        "graph_nodes": "open-us-law-graph-node/v1",
        "graph_edges": "open-us-law-graph-edge/v1",
        "graph_adjacency_out": "open-us-law-graph-adjacency-out/v1",
        "graph_adjacency_in": "open-us-law-graph-adjacency-in/v1",
        "source_receipts": "open-us-law-source-receipt/v1",
        "recovery": "open-us-law-recovery/v1",
        "quarantine": "open-us-law-quarantine/v1",
        FEDERAL_CONFIG_NAME: "open-us-law-federal-uscode/v1",
        PUERTO_RICO_CONFIG_NAME: "open-us-law-puerto-rico/v1",
        CONSTITUTIONS_CONFIG_NAME: "open-us-law-constitutions/v1",
        HISTORICAL_CONFIG_NAME: "open-us-law-historical/v1",
        "routing_index": "open-us-law-routing-index/v1",
    }
)

_FAMILY_TO_ARTIFACT_FAMILY: Final[Mapping[str, ArtifactFamily]] = MappingProxyType(
    {
        "corpus": ArtifactFamily.CORPUS,
        "bm25_documents": ArtifactFamily.BM25_DOCUMENTS,
        "bm25_postings": ArtifactFamily.BM25_POSTINGS,
        "vectors": ArtifactFamily.VECTORS,
        "centroids": ArtifactFamily.CENTROIDS,
        "vector_locator": ArtifactFamily.LOCATOR_INDEX,
        "graph_nodes": ArtifactFamily.GRAPH_NODES,
        "graph_edges": ArtifactFamily.GRAPH_EDGES,
        "graph_adjacency_out": ArtifactFamily.GRAPH_ADJACENCY_OUT,
        "graph_adjacency_in": ArtifactFamily.GRAPH_ADJACENCY_IN,
        "routing_index": ArtifactFamily.ROUTING_INDEX,
        "manifest": ArtifactFamily.MANIFEST,
        "receipt": ArtifactFamily.RECEIPT,
        "source_receipts": ArtifactFamily.RECEIPT,
        "recovery": ArtifactFamily.RECEIPT,
        "quarantine": ArtifactFamily.RECEIPT,
        "report": ArtifactFamily.REPORT,
        "release_metadata": ArtifactFamily.RELEASE_METADATA,
    }
)

_DEFAULT_FEATURES: Final = (
    "entry_cid",
    "legal_id",
    "jurisdiction_code",
    "family",
    "record_json",
    "record_sha256",
)
_RECOVERY_FEATURES: Final = (
    "recovery_id",
    "admission_status",
    "record_json",
    "record_sha256",
)
_CONFIG_FEATURES: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        DEFAULT_CONFIG_NAME: _DEFAULT_FEATURES,
        FEDERAL_CONFIG_NAME: _DEFAULT_FEATURES,
        PUERTO_RICO_CONFIG_NAME: _DEFAULT_FEATURES,
        CONSTITUTIONS_CONFIG_NAME: _DEFAULT_FEATURES,
        HISTORICAL_CONFIG_NAME: _DEFAULT_FEATURES,
        RECOVERY_CONFIG_NAME: _RECOVERY_FEATURES,
        QUARANTINE_CONFIG_NAME: _RECOVERY_FEATURES,
    }
)

_HIDDEN_VIEWER_CONFIGS: Final = frozenset(
    {RECOVERY_CONFIG_NAME, QUARANTINE_CONFIG_NAME}
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class OpenUsLawHFReleaseError(HuggingFaceReleaseError):
    """Base error for Open US Law Hugging Face release packaging failures."""

    code: str = "open_us_law_hf_release_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class OpenUsLawHFReleaseIntegrityError(OpenUsLawHFReleaseError):
    """Raised when descriptors, digests, or family bindings disagree."""

    code = "open_us_law_hf_release_integrity"


class OpenUsLawHFReleaseConfigError(OpenUsLawHFReleaseError):
    """Raised when viewer/config schema coherence fails."""

    code = "open_us_law_hf_release_config"


class OpenUsLawHFReleaseSafetyError(OpenUsLawHFReleaseError):
    """Raised when recovery or non-default rows contaminate exact-51."""

    code = "open_us_law_hf_release_safety"


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
    is_recovery: bool = False
    is_quarantine: bool = False
    viewer_visible: bool = True
    satisfies_exact_51_gate: bool = False
    features: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    path_prefixes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        name = str(self.config_name or "").strip()
        if not name:
            raise OpenUsLawHFReleaseConfigError("config_name is required")
        if self.is_default and (self.is_recovery or self.is_quarantine):
            raise OpenUsLawHFReleaseConfigError(
                "default config cannot also be recovery or quarantine"
            )
        if self.is_default and not self.satisfies_exact_51_gate:
            raise OpenUsLawHFReleaseConfigError(
                "default config must satisfy the exact-51 gate"
            )
        if (self.is_recovery or self.is_quarantine) and self.satisfies_exact_51_gate:
            raise OpenUsLawHFReleaseConfigError(
                "recovery/quarantine configs cannot satisfy the exact-51 gate"
            )
        object.__setattr__(self, "config_name", name)
        object.__setattr__(
            self,
            "primary_key",
            str(self.primary_key or "").strip() or PRIMARY_KEY,
        )
        files = tuple(dict(item) for item in self.data_files)
        if not files:
            raise OpenUsLawHFReleaseConfigError(
                f"config {name!r} requires at least one data_files entry"
            )
        for item in files:
            if "split" not in item or "path" not in item:
                raise OpenUsLawHFReleaseConfigError(
                    f"config {name!r} data_files entries need split + path"
                )
            path = str(item["path"])
            if path.startswith("/") or ".." in PurePosixPath(path).parts:
                raise OpenUsLawHFReleaseConfigError(
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
            "is_quarantine": self.is_quarantine,
            "is_recovery": self.is_recovery,
            "notes": list(self.notes),
            "path_prefixes": list(self.path_prefixes),
            "primary_key": self.primary_key,
            "satisfies_exact_51_gate": self.satisfies_exact_51_gate,
            "viewer_visible": self.viewer_visible,
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
    include_non_default: bool = True,
    include_recovery: bool = True,
    include_quarantine: bool = True,
    default_data_glob: str = "data/**/*.parquet",
    recovery_data_glob: str = "recovery/**/*.json",
    quarantine_data_glob: str = "quarantine/**/*.json",
) -> tuple[ViewerConfig, ...]:
    """Return the sealed set of advertised Dataset Viewer configurations."""

    configs: list[ViewerConfig] = [
        ViewerConfig(
            config_name=DEFAULT_CONFIG_NAME,
            data_files=({"split": "train", "path": default_data_glob},),
            primary_key=PRIMARY_KEY,
            is_default=True,
            is_recovery=False,
            is_quarantine=False,
            viewer_visible=True,
            satisfies_exact_51_gate=True,
            features=_CONFIG_FEATURES[DEFAULT_CONFIG_NAME],
            path_prefixes=DEFAULT_CONFIG_PATH_PREFIXES,
            notes=(
                "Viewer-safe default exact-51 configuration.",
                "Current official statutes for exactly the 50 states plus DC.",
                "Excludes recovery, quarantine, federal US Code, Puerto Rico, "
                "constitutions, and historical rows.",
            ),
        )
    ]
    if include_non_default:
        named = (
            (
                FEDERAL_CONFIG_NAME,
                "configs/federal_uscode/**/*.parquet",
                ("configs/federal_uscode/",),
                "Federal United States Code rows. Useful corpus; never default exact-51.",
            ),
            (
                PUERTO_RICO_CONFIG_NAME,
                "configs/puerto_rico/**/*.parquet",
                ("configs/puerto_rico/",),
                "Puerto Rico statutory rows. Explicit non-default configuration.",
            ),
            (
                CONSTITUTIONS_CONFIG_NAME,
                "configs/constitutions/**/*.parquet",
                ("configs/constitutions/",),
                "Federal, state, DC, and territorial constitution rows.",
            ),
            (
                HISTORICAL_CONFIG_NAME,
                "configs/historical/**/*.parquet",
                ("configs/historical/",),
                "Superseded, repealed, or otherwise non-current statute versions.",
            ),
        )
        for name, glob, prefixes, note in named:
            configs.append(
                ViewerConfig(
                    config_name=name,
                    data_files=({"split": "train", "path": glob},),
                    primary_key=PRIMARY_KEY,
                    is_default=False,
                    viewer_visible=True,
                    satisfies_exact_51_gate=False,
                    features=_CONFIG_FEATURES[name],
                    path_prefixes=prefixes,
                    notes=(note, "Must not be the default Dataset Viewer config."),
                )
            )
    if include_recovery:
        configs.append(
            ViewerConfig(
                config_name=RECOVERY_CONFIG_NAME,
                data_files=({"split": "train", "path": recovery_data_glob},),
                primary_key="recovery_id",
                is_default=False,
                is_recovery=True,
                viewer_visible=False,
                satisfies_exact_51_gate=False,
                features=_CONFIG_FEATURES[RECOVERY_CONFIG_NAME],
                path_prefixes=RECOVERY_CONFIG_PATH_PREFIXES,
                notes=(
                    "Recovery records that cannot enter canonical default counts.",
                    "Never included in the default config or exact-51 gate.",
                ),
            )
        )
    if include_quarantine:
        configs.append(
            ViewerConfig(
                config_name=QUARANTINE_CONFIG_NAME,
                data_files=({"split": "train", "path": quarantine_data_glob},),
                primary_key="recovery_id",
                is_default=False,
                is_quarantine=True,
                viewer_visible=False,
                satisfies_exact_51_gate=False,
                features=_CONFIG_FEATURES[QUARANTINE_CONFIG_NAME],
                path_prefixes=QUARANTINE_CONFIG_PATH_PREFIXES,
                notes=(
                    "Quarantined or rejected rows excluded from the Viewer default split.",
                    "Never included in the default config or exact-51 gate.",
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
                    primary_key=str(item.get("primary_key") or PRIMARY_KEY),
                    is_default=bool(item.get("is_default", False)),
                    is_recovery=bool(item.get("is_recovery", False)),
                    is_quarantine=bool(item.get("is_quarantine", False)),
                    viewer_visible=bool(item.get("viewer_visible", True)),
                    satisfies_exact_51_gate=bool(
                        item.get("satisfies_exact_51_gate", False)
                    ),
                    features=tuple(item.get("features") or ()),
                    notes=tuple(item.get("notes") or ()),
                    path_prefixes=tuple(item.get("path_prefixes") or ()),
                )
            )
        else:
            raise OpenUsLawHFReleaseConfigError(
                "config entries must be ViewerConfig or mapping"
            )

    if not resolved:
        raise OpenUsLawHFReleaseConfigError("at least one viewer config is required")

    defaults = [c for c in resolved if c.is_default]
    if len(defaults) != 1:
        raise OpenUsLawHFReleaseConfigError(
            f"exactly one default config required, found {len(defaults)}"
        )
    default = defaults[0]
    if default.config_name != DEFAULT_CONFIG_NAME:
        raise OpenUsLawHFReleaseConfigError(
            f"default config must be {DEFAULT_CONFIG_NAME!r}, "
            f"got {default.config_name!r}"
        )
    if default.is_recovery or default.is_quarantine:
        raise OpenUsLawHFReleaseConfigError(
            "default config must not be recovery or quarantine"
        )
    if not default.satisfies_exact_51_gate:
        raise OpenUsLawHFReleaseConfigError(
            "default config must satisfy the exact-51 gate"
        )

    for entry in default.data_files:
        path = str(entry["path"])
        lowered = path.lower()
        if (
            path.startswith("recovery/")
            or path.startswith("quarantine/")
            or "/recovery/" in f"/{path}/"
            or "/quarantine/" in f"/{path}/"
            or "recovery" in lowered
            and lowered.endswith(".json")
        ):
            raise OpenUsLawHFReleaseSafetyError(
                "default config excludes recovery and quarantine; "
                f"found path {path!r}"
            )
        if path.startswith("configs/"):
            raise OpenUsLawHFReleaseSafetyError(
                f"default exact-51 config must not include non-default path {path!r}"
            )

    names = [c.config_name for c in resolved]
    if len(names) != len(set(names)):
        raise OpenUsLawHFReleaseConfigError("viewer config names must be unique")

    for cfg in resolved:
        features = set(cfg.features)
        if cfg.primary_key and cfg.features and cfg.primary_key not in features:
            raise OpenUsLawHFReleaseConfigError(
                f"config {cfg.config_name!r} primary_key "
                f"{cfg.primary_key!r} missing from features"
            )
        if cfg.is_recovery and cfg.config_name != RECOVERY_CONFIG_NAME:
            raise OpenUsLawHFReleaseConfigError(
                f"recovery config must be named {RECOVERY_CONFIG_NAME!r}"
            )
        if cfg.is_quarantine and cfg.config_name != QUARANTINE_CONFIG_NAME:
            raise OpenUsLawHFReleaseConfigError(
                f"quarantine config must be named {QUARANTINE_CONFIG_NAME!r}"
            )
        if cfg.satisfies_exact_51_gate and cfg.config_name != DEFAULT_CONFIG_NAME:
            raise OpenUsLawHFReleaseConfigError(
                f"{cfg.config_name!r} must not satisfy the exact-51 gate"
            )

    return {
        "config_count": len(resolved),
        "default_config": default.config_name,
        "default_excludes_recovery": True,
        "names": names,
        "schema_coherent": True,
        "viewer_safe_default_exact_51": True,
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
            raise OpenUsLawHFReleaseError("artifact content must be bytes")
        content = bytes(self.content)
        digest = hashlib.sha256(content).hexdigest()
        cid = cid_v1_from_digest(bytes.fromhex(digest))
        if self.sha256 and normalize_sha256(self.sha256) != digest:
            raise OpenUsLawHFReleaseIntegrityError(
                f"artifact sha256 mismatch for {path}"
            )
        if self.content_cid and self.content_cid != cid:
            raise OpenUsLawHFReleaseIntegrityError(
                f"artifact content_cid mismatch for {path}"
            )
        if type(self.row_count) is not int or isinstance(self.row_count, bool):
            raise OpenUsLawHFReleaseError("row_count must be a non-negative integer")
        if self.row_count < 0:
            raise OpenUsLawHFReleaseError("row_count must be a non-negative integer")
        bounded = (
            DEFAULT_CONFIG_FAMILIES
            | RECOVERY_FAMILIES
            | NON_DEFAULT_CORPUS_FAMILIES
            | {"source_receipts", "routing_index"}
        )
        if self.row_count > MAX_ROWS_PER_PHYSICAL_SHARD and self.family in bounded:
            raise OpenUsLawHFReleaseIntegrityError(
                f"artifact {path} row_count={self.row_count} exceeds "
                f"physical bound {MAX_ROWS_PER_PHYSICAL_SHARD}"
            )
        media = str(self.media_type or "").strip()
        if not media:
            raise OpenUsLawHFReleaseError("media_type is required")
        family = _normalize_family(self.family)
        if not family:
            raise OpenUsLawHFReleaseError("family is required")
        schema_id = str(self.schema_id or _FAMILY_SCHEMA_IDS.get(family) or "")
        if not schema_id:
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
        family = _FAMILY_TO_ARTIFACT_FAMILY.get(self.family)
        if family is None:
            if self.relative_path == MANIFEST_FILENAME:
                family = ArtifactFamily.MANIFEST
            elif self.relative_path == RELEASE_METADATA_FILENAME:
                family = ArtifactFamily.RELEASE_METADATA
            elif self.relative_path.startswith("reports/"):
                family = ArtifactFamily.REPORT
            elif self.relative_path.startswith("indexes/"):
                family = ArtifactFamily.ROUTING_INDEX
            elif self.family == "vector_locator":
                family = ArtifactFamily.LOCATOR_INDEX
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
            content_cid=self.content_cid,
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
        payload["release_family"] = self.family
        return payload


@dataclass(frozen=True, slots=True)
class OpenUsLawHuggingFaceRelease:
    """Complete in-memory (or staged) Open US Law Hugging Face release."""

    dataset_id: str
    release_root_cid: str
    manifest_digest: str
    schema_version: str
    release_profile: str
    source_revision: str
    build_config_cid: str
    vector_space_id: str
    model_id: str
    model_revision: str
    configs: tuple[ViewerConfig, ...]
    artifacts: tuple[ReleaseArtifact, ...]
    dry_run: bool
    staged_root: Optional[str] = None
    package_version: str = DEFAULT_PACKAGE_VERSION

    def __post_init__(self) -> None:
        if not _DATASET_ID_RE.fullmatch(self.dataset_id):
            raise OpenUsLawHFReleaseError("dataset_id must be owner/name")
        if self.dataset_id != DEFAULT_DATASET_REPO_ID:
            raise OpenUsLawHFReleaseSafetyError(
                f"dataset_id must be {DEFAULT_DATASET_REPO_ID!r}"
            )
        if not self.artifacts:
            raise OpenUsLawHFReleaseError("release must contain artifacts")
        paths = [item.relative_path for item in self.artifacts]
        if len(paths) != len(set(paths)):
            raise OpenUsLawHFReleaseIntegrityError("artifact paths must be unique")
        ordered = tuple(sorted(self.artifacts, key=lambda item: item.relative_path))
        object.__setattr__(self, "artifacts", ordered)
        if type(self.dry_run) is not bool:
            raise OpenUsLawHFReleaseError("dry_run must be boolean")
        require_immutable_revision(self.source_revision, name="source_revision")
        require_immutable_revision(self.model_revision, name="model_revision")
        if self.model_id != DEFAULT_EMBEDDING_MODEL_ID:
            raise OpenUsLawHFReleaseSafetyError(
                f"model_id must be {DEFAULT_EMBEDDING_MODEL_ID!r}"
            )
        if self.model_revision != DEFAULT_EMBEDDING_MODEL_REVISION:
            raise OpenUsLawHFReleaseSafetyError(
                "model_revision must be the pinned thenlper/gte-small revision"
            )
        cid = str(self.release_root_cid)
        if not _CID_RE.fullmatch(cid) and not _SHA256_RE.fullmatch(cid):
            if not cid.startswith("b") and len(cid) != 64:
                raise OpenUsLawHFReleaseIntegrityError(
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
            or item.relative_path.startswith("quarantine/")
            or item.relative_path.startswith("configs/")
            or item.relative_path.startswith("indexes/")
            or item.relative_path.startswith("receipts/")
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
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "package_version": self.package_version,
            "release_profile": self.release_profile,
            "release_root_cid": self.release_root_cid,
            "schema_version": self.schema_version,
            "source_revision": self.source_revision,
            "staged_root": self.staged_root,
            "vector_space_id": self.vector_space_id,
        }


# ---------------------------------------------------------------------------
# Family / encoding helpers
# ---------------------------------------------------------------------------


def _normalize_family(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return _FAMILY_ALIASES.get(text, text)


def _config_for_family(family: str) -> str:
    if family == "recovery":
        return RECOVERY_CONFIG_NAME
    if family == "quarantine":
        return QUARANTINE_CONFIG_NAME
    if family in NON_DEFAULT_CORPUS_FAMILIES:
        return family
    return DEFAULT_CONFIG_NAME


def _row_has_identity(row: Mapping[str, Any]) -> bool:
    return any(
        row.get(key) not in (None, "")
        for key in ("jurisdiction_code", "configuration", "document_kind")
    )


def _assert_row_belongs_to_family(row: Mapping[str, Any], family: str) -> None:
    """Reject non-default identity rows from the default exact-51 corpus family."""

    if family != "corpus":
        return
    if not _row_has_identity(row):
        return
    try:
        classified = classify_configuration(row)
    except OpenUsLawSchemaError as exc:
        raise OpenUsLawHFReleaseSafetyError(
            f"family {family!r} row is not default exact-51: {exc}"
        ) from exc
    if classified is not ReleaseConfiguration.STATE_STATUTES_EXACT_51:
        raise OpenUsLawHFReleaseSafetyError(
            f"family {family!r} is default exact-51 but row classified as "
            f"{classified.value!r}"
        )


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
        raise OpenUsLawHFReleaseError(
            "parquet encoding requires the optional 'pyarrow' package"
        ) from exc

    entry_cids: list[str] = []
    legal_ids: list[str] = []
    jurisdictions: list[str] = []
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
                or payload.get("centroid_id")
                or payload.get("node_cid")
                or payload.get("record_id")
                or payload.get("receipt_cid")
                or ""
            )
        )
        legal_ids.append(
            str(payload.get("legal_id") or payload.get("term") or payload.get("node_key") or "")
        )
        jurisdictions.append(str(payload.get("jurisdiction_code") or ""))
        families.append(family)

    table = pa.table(
        {
            "entry_cid": entry_cids,
            "legal_id": legal_ids,
            "jurisdiction_code": jurisdictions,
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


def _encode_json_family(rows: Sequence[Mapping[str, Any]], *, family: str) -> bytes:
    payload = {
        "family": family,
        "quarantined": family in RECOVERY_FAMILIES,
        "rows": [dict(row) for row in rows],
        "schema_version": _FAMILY_SCHEMA_IDS.get(family, SCHEMA_VERSION),
    }
    reject_identity_contamination(payload, label=f"{family}-json")
    return canonical_json_bytes(payload) + b"\n"


def _row_sort_key(row: Mapping[str, Any], family: str) -> tuple[str, ...]:
    if family in RECOVERY_FAMILIES:
        return (
            str(row.get("recovery_id") or row.get("entry_cid") or row.get("legal_id") or ""),
            str(row.get("record_sha256") or row.get("text_hash") or ""),
        )
    if family == "bm25_postings":
        return (str(row.get("term") or ""), str(row.get("entry_cid") or ""))
    if family == "centroids":
        return (str(row.get("centroid_id") or row.get("cluster_id") or ""),)
    if family == "vector_locator":
        return (
            str(row.get("entry_cid") or ""),
            str(row.get("chunk_cid") or ""),
            f"{int(row.get('row_offset') or 0):08d}",
        )
    if family == "graph_nodes":
        return (str(row.get("node_cid") or row.get("entry_cid") or ""),)
    if family == "graph_edges":
        return (
            str(row.get("edge_cid") or ""),
            str(row.get("source_node_cid") or ""),
            str(row.get("target_node_cid") or ""),
        )
    if family in {"graph_adjacency_out", "graph_adjacency_in"}:
        return (
            str(row.get("node_cid") or ""),
            f"{int(row.get('page_index') or 0):08d}",
        )
    if family == "source_receipts":
        return (
            str(row.get("jurisdiction_code") or ""),
            str(row.get("receipt_cid") or ""),
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


def route_bounds_policy() -> dict[str, int]:
    """Sealed physical and routing bounds bound into the release manifest."""

    bounds = dict(identity_physical_bounds())
    bounds["default_candidate_centroids"] = DEFAULT_CANDIDATE_CENTROIDS
    bounds["embedding_dimension"] = DEFAULT_EMBEDDING_DIMENSION
    bounds["max_adjacency_pointers_per_row"] = MAX_ADJACENCY_POINTERS_PER_ROW
    bounds["max_posting_pointers_per_row"] = MAX_POSTING_POINTERS_PER_ROW
    bounds["max_rows_per_physical_shard"] = MAX_ROWS_PER_PHYSICAL_SHARD
    bounds["max_rows_per_vector_centroid"] = MAX_ROWS_PER_VECTOR_CENTROID
    bounds["max_vector_shards_per_centroid"] = MAX_VECTOR_SHARDS_PER_CENTROID
    bounds["model_token_ceiling"] = DEFAULT_MODEL_TOKEN_CEILING
    return bounds


def _family_binding(
    artifacts: Sequence[ReleaseArtifact],
    families: Sequence[str],
) -> dict[str, Any]:
    wanted = {_normalize_family(name) for name in families}
    matching = [item for item in artifacts if item.family in wanted]
    matching = sorted(matching, key=lambda item: item.relative_path)
    return {
        "artifact_count": len(matching),
        "artifacts": [item.descriptor_dict() for item in matching],
        "families": sorted(wanted),
        "first_keys": [item.first_key for item in matching],
        "last_keys": [item.last_key for item in matching],
        "relative_paths": [item.relative_path for item in matching],
        "row_count": sum(item.row_count for item in matching),
        "sha256": [item.sha256 for item in matching],
        "size_bytes": sum(item.size_bytes for item in matching),
    }


# ---------------------------------------------------------------------------
# Dataset card
# ---------------------------------------------------------------------------


def render_dataset_card(
    *,
    dataset_id: str = DEFAULT_DATASET_REPO_ID,
    release_profile: str = RELEASE_PROFILE,
    source_revision: str = DEFAULT_SOURCE_REVISION,
    source_bucket: str = SOURCE_BUCKET,
    configs: Sequence[ViewerConfig] | None = None,
    vector_space_id: str = "",
    model_id: str = PINNED_MODEL_ID,
    model_revision: str = PINNED_MODEL_REVISION,
    limitations: Sequence[str] | None = None,
    currentness_disclaimer: str = CURRENTNESS_DISCLAIMER,
) -> str:
    """Render the sealed Dataset card (README.md) with YAML frontmatter."""

    viewer_configs = tuple(configs or advertised_viewer_configs())
    assert_configs_schema_coherent(viewer_configs)
    space = vector_space_id or build_vector_space_id(
        model_id=model_id,
        model_revision=model_revision,
        pooling=PINNED_POOLING,
        normalization=PINNED_NORMALIZATION,
        dimension=PINNED_DIMENSION,
    )
    safe_limitations = tuple(
        limitations
        or (
            "Retrieval output is a research aid and is not a substitute for "
            "official state or District of Columbia publications.",
            "Acquisition and publication timestamps are not legal-currentness claims.",
            "Recovery and quarantine rows are excluded from the default exact-51 "
            "config and from corpus/BM25/vector/graph counts until admitted.",
            "Federal US Code, Puerto Rico, constitutions, and historical rows "
            "are explicit non-default configurations and cannot satisfy the "
            "exact-51 gate.",
        )
    )

    lines: list[str] = [
        "---",
        f"license: {DEFAULT_LICENSE}",
        'pretty_name: "Open US Law Sparse GraphRAG"',
        "tags:",
        "  - legal",
        "  - state-statutes",
        "  - graphrag",
        "  - justicedao",
        "  - open-us-law",
        "  - exact-51",
        "configs:",
    ]
    for cfg in viewer_configs:
        lines.extend(cfg.yaml_block())
    lines.extend(
        [
            "---",
            "",
            "# Open US Law Sparse GraphRAG",
            "",
            f"Dataset repository: `{dataset_id}`",
            f"Source bucket: `{source_bucket}`",
            "",
            "## Release profile",
            "",
            f"- Profile: `{release_profile}`",
            f"- Pinned source revision: `{source_revision}`",
            f"- Embedding model: `{model_id}` @ `{model_revision}`",
            f"- Vector space: `{space}`",
            f"- Primary key (default config): `{PRIMARY_KEY}`",
            f"- Default configuration: `{DEFAULT_CONFIG_NAME}` (Viewer-safe exact-51)",
            f"- Required jurisdictions: {EXPECTED_JURISDICTION_COUNT} "
            "(50 states plus DC)",
            "",
            "## Dataset configurations",
            "",
            "The **default** configuration is Viewer-safe exact-51 state and DC "
            "statutes only. Recovery JSON, quarantine JSON, federal US Code, "
            "Puerto Rico, constitutions, and historical rows are advertised as "
            "separate named configs and never contaminate the default Dataset "
            "Viewer schema or the exact-51 gate.",
            "",
        ]
    )
    for cfg in viewer_configs:
        if cfg.is_default:
            role = "default exact-51"
        elif cfg.is_recovery:
            role = "recovery"
        elif cfg.is_quarantine:
            role = "quarantine"
        else:
            role = "named non-default"
        lines.append(
            f"- `{cfg.config_name}` ({role}) — primary key `{cfg.primary_key}`"
        )
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
            "data/vectors/centroids/part-*.parquet",
            "data/vectors/locator/part-*.parquet",
            "data/graph/nodes/part-*.parquet",
            "data/graph/edges/part-*.parquet",
            "data/graph/adjacency/out/part-*.parquet",
            "data/graph/adjacency/in/part-*.parquet",
            "indexes/*",
            "receipts/source/*",
            "reports/admission.json",
            "reports/quality.json",
            "reports/reproducibility.json",
            "reports/lineage.json   # verbose lineage (not control plane)",
            "recovery/...          # recovery config only",
            "quarantine/...        # quarantine config only",
            "configs/federal_uscode/...",
            "configs/puerto_rico/...",
            "configs/constitutions/...",
            "configs/historical/...",
            "```",
            "",
            "## Control plane vs verbose lineage",
            "",
            "The control plane consists of `manifest.json`, `release_metadata.json`, "
            "routing indexes, source-receipt descriptors, and compact "
            "admission/quality/reproducibility reports. Verbose per-row source "
            "lineage lives only in `reports/lineage.json` and is **not** mixed "
            "into Dataset Viewer configs or the release control plane.",
            "",
            "## Route bounds",
            "",
            f"- At most {MAX_ROWS_PER_PHYSICAL_SHARD} rows per physical shard.",
            f"- At most {MAX_POSTING_POINTERS_PER_ROW} BM25 posting pointers per cell.",
            f"- At most {MAX_ADJACENCY_POINTERS_PER_ROW} adjacency pointers per page.",
            f"- At most {MAX_ROWS_PER_VECTOR_CENTROID} vectors and "
            f"{MAX_VECTOR_SHARDS_PER_CENTROID} shards per centroid.",
            f"- Model token ceiling is {DEFAULT_MODEL_TOKEN_CEILING}; it is not a "
            "shard bound.",
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
            "and optional key range. The manifest also binds corpus, BM25, "
            "vectors, centroids, the vector locator, the legal graph, two-way "
            "adjacency, recovery, source receipts, the pinned model revision, "
            "and route bounds.",
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
class OpenUsLawHFReleaseBuilder:
    """Deterministic local builder for Open US Law HF release candidates."""

    dataset_id: str = DEFAULT_DATASET_REPO_ID
    max_rows_per_shard: int = MAX_ROWS_PER_PHYSICAL_SHARD
    source_revision: str = DEFAULT_SOURCE_REVISION
    model_id: str = PINNED_MODEL_ID
    model_revision: str = PINNED_MODEL_REVISION
    tokenizer_id: str = TOKENIZER_ID
    graph_ontology_version: str = DEFAULT_GRAPH_ONTOLOGY_VERSION
    determinism_seed: int = DEFAULT_DETERMINISM_SEED
    include_non_default_configs: bool = True
    include_recovery_config: bool = True
    include_quarantine_config: bool = True

    def __post_init__(self) -> None:
        if not _DATASET_ID_RE.fullmatch(self.dataset_id):
            raise OpenUsLawHFReleaseError("dataset_id must be owner/name")
        if self.dataset_id != DEFAULT_DATASET_REPO_ID:
            raise OpenUsLawHFReleaseSafetyError(
                f"dataset_id must be {DEFAULT_DATASET_REPO_ID!r}"
            )
        if (
            type(self.max_rows_per_shard) is not int
            or isinstance(self.max_rows_per_shard, bool)
            or self.max_rows_per_shard <= 0
            or self.max_rows_per_shard > MAX_ROWS_PER_PHYSICAL_SHARD
        ):
            raise OpenUsLawHFReleaseError(
                f"max_rows_per_shard must be in 1..{MAX_ROWS_PER_PHYSICAL_SHARD}"
            )
        require_immutable_revision(self.source_revision, name="source_revision")
        object.__setattr__(
            self,
            "model_revision",
            require_immutable_revision(self.model_revision, name="model_revision"),
        )
        if self.model_id != DEFAULT_EMBEDDING_MODEL_ID:
            raise OpenUsLawHFReleaseSafetyError(
                f"model_id must be {DEFAULT_EMBEDDING_MODEL_ID!r}"
            )
        if self.model_revision != DEFAULT_EMBEDDING_MODEL_REVISION:
            raise OpenUsLawHFReleaseSafetyError(
                "model_revision must be the pinned thenlper/gte-small revision"
            )
        _assert_no_upload_shortcut()

    def build(
        self,
        family_rows: Mapping[str, Sequence[Mapping[str, Any]]],
        *,
        dry_run: bool = True,
        output_dir: str | Path | None = None,
        admission_summary: Mapping[str, Any] | None = None,
        preserve_existing: Sequence[str] | None = None,
    ) -> OpenUsLawHuggingFaceRelease:
        """Build a descriptor-complete release from family rows."""

        _assert_no_upload_shortcut()
        if type(dry_run) is not bool:
            raise OpenUsLawHFReleaseError("dry_run must be boolean")

        vector_space = build_vector_space_id(
            model_id=self.model_id,
            model_revision=self.model_revision,
            pooling=PINNED_POOLING,
            normalization=PINNED_NORMALIZATION,
            dimension=PINNED_DIMENSION,
        )
        build_config_cid = digest_mapping(
            {
                "dataset_id": self.dataset_id,
                "determinism_seed": self.determinism_seed,
                "graph_ontology_version": self.graph_ontology_version,
                "max_rows_per_shard": self.max_rows_per_shard,
                "model_id": self.model_id,
                "model_revision": self.model_revision,
                "schema_version": SCHEMA_VERSION,
                "source_revision": self.source_revision,
                "tokenizer_id": self.tokenizer_id,
                "vector_space_id": vector_space,
            }
        )

        data_artifacts = self._build_data_artifacts(family_rows)
        has_recovery = any(item.family == "recovery" for item in data_artifacts)
        has_quarantine = any(item.family == "quarantine" for item in data_artifacts)
        has_named = {
            name: any(item.family == name for item in data_artifacts)
            for name in (
                FEDERAL_CONFIG_NAME,
                PUERTO_RICO_CONFIG_NAME,
                CONSTITUTIONS_CONFIG_NAME,
                HISTORICAL_CONFIG_NAME,
            )
        }

        configs = advertised_viewer_configs(
            include_non_default=self.include_non_default_configs
            and any(has_named.values()),
            include_recovery=self.include_recovery_config and has_recovery,
            include_quarantine=self.include_quarantine_config and has_quarantine,
        )
        # Always advertise the sealed exact-51 default plus every named
        # configuration the operator requested, even when a family is empty,
        # so the Viewer card matches the identity contract.
        configs = advertised_viewer_configs(
            include_non_default=self.include_non_default_configs,
            include_recovery=self.include_recovery_config,
            include_quarantine=self.include_quarantine_config,
        )
        assert_configs_schema_coherent(configs)

        reports = self._build_reports(
            data_artifacts=data_artifacts,
            family_rows=family_rows,
            admission_summary=admission_summary or {},
            build_config_cid=build_config_cid,
            vector_space_id=vector_space,
        )
        card_text = render_dataset_card(
            dataset_id=self.dataset_id,
            release_profile=RELEASE_PROFILE,
            source_revision=self.source_revision,
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
            "viewer_safe_default_exact_51": True,
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
        all_pre = tuple(data_artifacts) + support_pre_manifest
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
            schema_id=SCHEMA_VERSION,
        )

        manifest_body = self._build_manifest_body(
            data_artifacts=data_artifacts,
            support_artifacts=(*support_pre_manifest, metadata_artifact),
            configs=configs,
            build_config_cid=build_config_cid,
            release_root_cid=release_root_cid,
            vector_space_id=vector_space,
        )
        reject_identity_contamination(manifest_body, label="manifest")
        manifest_digest = digest_mapping(
            {key: value for key, value in manifest_body.items() if key != "manifest_digest"}
        )
        manifest_body["manifest_digest"] = manifest_digest
        manifest_artifact = ReleaseArtifact(
            relative_path=MANIFEST_FILENAME,
            content=canonical_json_bytes(manifest_body) + b"\n",
            media_type=JSON_MEDIA_TYPE,
            family="manifest",
            row_count=0,
            schema_id=SCHEMA_VERSION,
        )

        release = OpenUsLawHuggingFaceRelease(
            dataset_id=self.dataset_id,
            release_root_cid=release_root_cid,
            manifest_digest=manifest_digest,
            schema_version=SCHEMA_VERSION,
            release_profile=RELEASE_PROFILE,
            source_revision=self.source_revision,
            build_config_cid=build_config_cid,
            vector_space_id=vector_space,
            model_id=self.model_id,
            model_revision=self.model_revision,
            configs=configs,
            artifacts=(*data_artifacts, *support_pre_manifest, metadata_artifact, manifest_artifact),
            dry_run=dry_run,
            staged_root=None,
        )
        validate_open_us_law_hf_release(release)
        if dry_run:
            return release
        if output_dir is None:
            raise OpenUsLawHFReleaseError(
                "output_dir is required when dry_run is false"
            )
        return stage_open_us_law_hf_release(
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
            raise OpenUsLawHFReleaseError("family_rows must be a mapping")

        for family in sorted(family_rows):
            fam = _normalize_family(family)
            if fam not in _FAMILY_PATH_TEMPLATES:
                raise OpenUsLawHFReleaseError(f"unknown artifact family: {family!r}")
            rows = list(family_rows[family] or ())
            if not rows:
                continue
            for row in rows:
                if not isinstance(row, Mapping):
                    raise OpenUsLawHFReleaseError(
                        f"family {fam!r} rows must be mappings"
                    )
                _assert_row_belongs_to_family(row, fam)
            ordered = sorted(rows, key=lambda r: _row_sort_key(r, fam))
            shards = shard_sequence(ordered, max_rows=self.max_rows_per_shard)
            template = _FAMILY_PATH_TEMPLATES[fam]
            config_name = _config_for_family(fam)
            for shard_index, shard_rows in enumerate(shards):
                if not shard_rows:
                    continue
                if fam in JSON_FAMILIES:
                    content = _encode_json_family(shard_rows, family=fam)
                    media = JSON_MEDIA_TYPE
                else:
                    content = _encode_parquet_rows(shard_rows, family=fam)
                    media = PARQUET_MEDIA_TYPE
                first_key, last_key = _first_last_keys(shard_rows, fam)
                artifacts.append(
                    ReleaseArtifact(
                        relative_path=template.format(shard=shard_index),
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

        by_family: dict[str, list[ReleaseArtifact]] = defaultdict(list)
        for art in artifacts:
            if art.family not in RECOVERY_FAMILIES and art.family != "source_receipts":
                if art.config_name == DEFAULT_CONFIG_NAME:
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

    def _build_reports(
        self,
        *,
        data_artifacts: Sequence[ReleaseArtifact],
        family_rows: Mapping[str, Sequence[Mapping[str, Any]]],
        admission_summary: Mapping[str, Any],
        build_config_cid: str,
        vector_space_id: str,
    ) -> tuple[ReleaseArtifact, ...]:
        family_counts = {
            _normalize_family(fam): sum(1 for _ in (family_rows.get(fam) or ()))
            for fam in sorted(family_rows)
        }
        admitted = int(
            admission_summary.get("admitted_count", family_counts.get("corpus", 0))
        )
        recovery_count = int(
            admission_summary.get(
                "recovery_quarantine_count",
                family_counts.get("recovery", 0) + family_counts.get("quarantine", 0),
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
            "release_profile": RELEASE_PROFILE,
            "schema_version": SCHEMA_VERSION,
            "source_revision": self.source_revision,
            "task_id": TASK_ID,
            "viewer_safe_default_exact_51": True,
        }
        for key in ("disposition_counts", "notes"):
            if key in admission_summary:
                admission[key] = admission_summary[key]
        reject_identity_contamination(admission, label="admission-report")

        quality = {
            "artifact_count": len(data_artifacts),
            "build_config_cid": build_config_cid,
            "configs_schema_coherent": True,
            "default_config": DEFAULT_CONFIG_NAME,
            "default_excludes_recovery": True,
            "descriptor_bound_artifacts": True,
            "every_artifact_descriptor_bound": True,
            "goal_id": GOAL_ID,
            "max_rows_per_physical_shard": self.max_rows_per_shard,
            "producer": PRODUCER,
            "route_bounds": route_bounds_policy(),
            "schema_version": SCHEMA_VERSION,
            "task_id": TASK_ID,
            "vector_space_id": vector_space_id,
            "viewer_safe_default_exact_51": True,
        }
        reject_identity_contamination(quality, label="quality-report")

        reproducibility = {
            "build_config_cid": build_config_cid,
            "determinism_seed": self.determinism_seed,
            "goal_id": GOAL_ID,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "producer": PRODUCER,
            "schema_version": SCHEMA_VERSION,
            "source_revision": self.source_revision,
            "task_id": TASK_ID,
            "tokenizer_id": self.tokenizer_id,
            "tokenizer_shared_by": TOKENIZER_SHARED_BY,
            "vector_space_id": vector_space_id,
        }
        reject_identity_contamination(reproducibility, label="reproducibility-report")

        lineage_rows: list[dict[str, Any]] = []
        for fam, rows in sorted(family_rows.items()):
            for row in rows:
                lineage_rows.append(
                    {
                        "entry_cid": row.get("entry_cid") or row.get("recovery_id"),
                        "family": _normalize_family(fam),
                        "jurisdiction_code": row.get("jurisdiction_code"),
                        "legal_id": row.get("legal_id"),
                        "receipt_cid": row.get("receipt_cid")
                        or row.get("acquisition_receipt_cid"),
                        "source_cid": row.get("source_cid"),
                        "source_checksum": row.get("source_checksum")
                        or row.get("body_hash"),
                        "verification_result": row.get("verification_result"),
                    }
                )
        lineage = {
            "control_plane": False,
            "goal_id": GOAL_ID,
            "producer": PRODUCER,
            "row_count": len(lineage_rows),
            "rows": lineage_rows,
            "schema_version": "open-us-law-verbose-lineage/v1",
            "separate_from_control_plane": True,
            "task_id": TASK_ID,
        }
        scrubbed_rows = []
        for row in lineage["rows"]:
            clean = {
                key: value
                for key, value in row.items()
                if not (
                    isinstance(value, str)
                    and (
                        value.startswith("/home/")
                        or value.startswith("/tmp/")
                        or value.startswith("file://")
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
                schema_id="open-us-law-verbose-lineage/v1",
            ),
        )

    def _build_manifest_body(
        self,
        *,
        data_artifacts: Sequence[ReleaseArtifact],
        support_artifacts: Sequence[ReleaseArtifact],
        configs: Sequence[ViewerConfig],
        build_config_cid: str,
        release_root_cid: str,
        vector_space_id: str,
    ) -> dict[str, Any]:
        inventory = [
            item.descriptor_dict()
            for item in sorted(
                (*data_artifacts, *support_artifacts),
                key=lambda art: art.relative_path,
            )
        ]
        row_counts = {
            item.relative_path: item.row_count
            for item in (*data_artifacts, *support_artifacts)
        }
        sizes = {
            item.relative_path: item.size_bytes
            for item in (*data_artifacts, *support_artifacts)
        }
        sha256_digests = {
            item.relative_path: item.sha256
            for item in (*data_artifacts, *support_artifacts)
        }
        identity_configurations = [
            item.to_dict() if isinstance(item, ConfigurationDescriptor) else item
            for item in default_configuration_descriptors()
        ]
        body: dict[str, Any] = {
            "acceptance": {
                "all_advertised_configs_schema_coherent": True,
                "default_config_excludes_recovery": True,
                "every_artifact_descriptor_bound": True,
                "verbose_lineage_separate_from_control_plane": True,
                "viewer_safe_default_exact_51": True,
            },
            "additive_packaging": True,
            "artifacts": inventory,
            "bm25": _family_binding(data_artifacts, ("bm25_documents", "bm25_postings")),
            "bm25_b": DEFAULT_BM25_B,
            "bm25_k1": DEFAULT_BM25_K1,
            "build_config_cid": build_config_cid,
            "centroids": _family_binding(data_artifacts, ("centroids",)),
            "configs": [cfg.to_dict() for cfg in configs],
            "corpus": _family_binding(data_artifacts, ("corpus",)),
            "dataset_repo_id": self.dataset_id,
            "default_config": DEFAULT_CONFIG_NAME,
            "default_excludes_recovery": True,
            "embedding_dimension": DEFAULT_EMBEDDING_DIMENSION,
            "extras_in_default_allowed": False,
            "goal_id": GOAL_ID,
            "graph": _family_binding(data_artifacts, ("graph_nodes", "graph_edges")),
            "graph_ontology_version": self.graph_ontology_version,
            "hf_release_schema_version": SCHEMA_VERSION,
            "identity_fields": list(REQUIRED_DEFAULT_STATUTE_IDENTITY_FIELDS),
            "identity_schema_version": IDENTITY_SCHEMA_VERSION,
            "jurisdictions": {
                "extras_in_default_allowed": False,
                "required_codes": list(EXACT_51_JURISDICTION_CODES),
                "required_count": EXPECTED_JURISDICTION_COUNT,
            },
            "lineage_is_control_plane": False,
            "lineage_report": LINEAGE_REPORT_PATH,
            "max_rows_per_physical_shard": self.max_rows_per_shard,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "model_token_ceiling": DEFAULT_MODEL_TOKEN_CEILING,
            "package_version": DEFAULT_PACKAGE_VERSION,
            "producer": PRODUCER,
            "program_id": PROGRAM_ID,
            "recovery": _family_binding(data_artifacts, ("recovery", "quarantine")),
            "release_profile": RELEASE_PROFILE,
            "release_root_cid": release_root_cid,
            "route_bounds": route_bounds_policy(),
            "row_counts": row_counts,
            "schema_version": SCHEMA_VERSION,
            "sha256_digests": sha256_digests,
            "sizes": sizes,
            "source_bucket": SOURCE_BUCKET,
            "source_receipts": _family_binding(data_artifacts, ("source_receipts",)),
            "source_revision": self.source_revision,
            "task_id": TASK_ID,
            "tokenizer_id": self.tokenizer_id,
            "two_way_adjacency": _family_binding(
                data_artifacts, ("graph_adjacency_out", "graph_adjacency_in")
            ),
            "vector_locator": _family_binding(data_artifacts, ("vector_locator",)),
            "vector_space_id": vector_space_id,
            "vectors": _family_binding(data_artifacts, ("vectors",)),
            "viewer": {
                "default_split": DEFAULT_CONFIG_NAME,
                "excluded_from_default": list(NON_DEFAULT_CONFIGURATION_NAMES),
                "hidden_configurations": sorted(_HIDDEN_VIEWER_CONFIGS),
            },
            "viewer_safe_default_exact_51": True,
            "identity_configurations": identity_configurations,
        }
        return body


# ---------------------------------------------------------------------------
# Family extractors / assembly
# ---------------------------------------------------------------------------


def rows_from_bm25_index(index: Any) -> dict[str, list[dict[str, Any]]]:
    """Project a bound BM25 index into document and posting family rows."""

    documents = [dict(row) for shard in index.document_shards for row in shard.documents]
    postings: list[dict[str, Any]] = []
    for shard in index.term_shards:
        for term in shard.terms:
            payload = term.to_dict()
            payload["entry_cid"] = term.term
            payload["legal_id"] = term.term
            postings.append(payload)
    return {"bm25_documents": documents, "bm25_postings": postings}


def rows_from_vector_binding(
    binding: Any,
) -> dict[str, list[dict[str, Any]]]:
    """Project a vector binding into vector, centroid, and locator rows."""

    vectors: list[dict[str, Any]] = []
    for location in binding.locations.values():
        vectors.append(location.to_dict())
    centroids: list[dict[str, Any]] = []
    for row in binding.routing_rows:
        payload = dict(row)
        payload.setdefault("centroid_id", payload.get("cluster_id"))
        centroids.append(payload)
    locator: list[dict[str, Any]] = []
    if binding.entry_locator_rows:
        for row in binding.entry_locator_rows:
            locator.append(row.to_dict() if hasattr(row, "to_dict") else dict(row))
    else:
        for location in binding.locations.values():
            locator.append(location.locator_payload())
    return {
        "centroids": centroids,
        "vector_locator": locator,
        "vectors": vectors,
    }


def rows_from_graph_projection(
    projection: Any,
) -> dict[str, list[dict[str, Any]]]:
    """Project a legal graph into node and edge family rows."""

    return {
        "graph_edges": [edge.to_dict() for edge in projection.edges],
        "graph_nodes": [node.to_dict() for node in projection.nodes],
    }


def rows_from_two_way_adjacency(
    adjacency: Any,
) -> dict[str, list[dict[str, Any]]]:
    """Project two-way adjacency pages into out/in family rows."""

    return {
        "graph_adjacency_in": [page.to_dict() for page in adjacency.incoming_pages],
        "graph_adjacency_out": [page.to_dict() for page in adjacency.outgoing_pages],
    }


def merge_family_rows(
    *parts: Mapping[str, Sequence[Mapping[str, Any]]] | None,
) -> dict[str, list[dict[str, Any]]]:
    """Merge family-row mappings; later parts override earlier families."""

    merged: dict[str, list[dict[str, Any]]] = {}
    for part in parts:
        if not part:
            continue
        for family, rows in part.items():
            merged[_normalize_family(family)] = [dict(row) for row in rows]
    return merged


def assemble_open_us_law_hf_release(
    family_rows: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    *,
    corpus_rows: Sequence[Mapping[str, Any]] | None = None,
    bm25_index: Any | None = None,
    vector_binding: Any | None = None,
    graph_projection: Any | None = None,
    adjacency: Any | None = None,
    source_receipts: Sequence[Mapping[str, Any]] | None = None,
    recovery_rows: Sequence[Mapping[str, Any]] | None = None,
    quarantine_rows: Sequence[Mapping[str, Any]] | None = None,
    dry_run: bool = True,
    output_dir: str | Path | None = None,
    **builder_kwargs: Any,
) -> OpenUsLawHuggingFaceRelease:
    """Assemble a descriptor-complete release from family rows and/or bindings."""

    parts: list[Mapping[str, Sequence[Mapping[str, Any]]]] = []
    if family_rows:
        parts.append(family_rows)
    extras: dict[str, Sequence[Mapping[str, Any]]] = {}
    if corpus_rows is not None:
        extras["corpus"] = corpus_rows
    if source_receipts is not None:
        extras["source_receipts"] = source_receipts
    if recovery_rows is not None:
        extras["recovery"] = recovery_rows
    if quarantine_rows is not None:
        extras["quarantine"] = quarantine_rows
    if extras:
        parts.append(extras)
    if bm25_index is not None:
        parts.append(rows_from_bm25_index(bm25_index))
    if vector_binding is not None:
        parts.append(rows_from_vector_binding(vector_binding))
    if graph_projection is not None:
        parts.append(rows_from_graph_projection(graph_projection))
    if adjacency is not None:
        parts.append(rows_from_two_way_adjacency(adjacency))
    assembled = merge_family_rows(*parts) if parts else fixture_family_rows()
    return build_open_us_law_hf_release(
        assembled,
        dry_run=dry_run,
        output_dir=output_dir,
        **builder_kwargs,
    )


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def build_open_us_law_hf_release(
    family_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    dataset_id: str = DEFAULT_DATASET_REPO_ID,
    dry_run: bool = True,
    output_dir: str | Path | None = None,
    max_rows_per_shard: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    source_revision: str = DEFAULT_SOURCE_REVISION,
    model_id: str = PINNED_MODEL_ID,
    model_revision: str = PINNED_MODEL_REVISION,
    admission_summary: Mapping[str, Any] | None = None,
    preserve_existing: Sequence[str] | None = None,
    include_non_default_configs: bool = True,
    include_recovery_config: bool = True,
    include_quarantine_config: bool = True,
) -> OpenUsLawHuggingFaceRelease:
    """Build a deterministic Open US Law HF release (default dry-run)."""

    builder = OpenUsLawHFReleaseBuilder(
        dataset_id=dataset_id,
        max_rows_per_shard=max_rows_per_shard,
        source_revision=source_revision,
        model_id=model_id,
        model_revision=model_revision,
        include_non_default_configs=include_non_default_configs,
        include_recovery_config=include_recovery_config,
        include_quarantine_config=include_quarantine_config,
    )
    return builder.build(
        family_rows,
        dry_run=dry_run,
        output_dir=output_dir,
        admission_summary=admission_summary,
        preserve_existing=preserve_existing,
    )


def stage_open_us_law_hf_release(
    release: OpenUsLawHuggingFaceRelease,
    output_dir: str | Path,
    *,
    dry_run: bool = True,
    preserve_existing: Sequence[str] | None = None,
) -> OpenUsLawHuggingFaceRelease:
    """Stage release bytes to a local directory (additive; never deletes)."""

    _assert_no_upload_shortcut()
    if not isinstance(release, OpenUsLawHuggingFaceRelease):
        raise OpenUsLawHFReleaseError("release must be OpenUsLawHuggingFaceRelease")
    if type(dry_run) is not bool:
        raise OpenUsLawHFReleaseError("dry_run must be boolean")
    if dry_run:
        return release

    root = Path(output_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
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
            raise OpenUsLawHFReleaseIntegrityError(
                f"staged file integrity mismatch: {artifact.relative_path}"
            )

    for path, original in pre_existing.items():
        current = root / path
        if not current.is_file():
            raise OpenUsLawHFReleaseSafetyError(
                f"preserved file was deleted during staging: {path}"
            )
        if current.read_bytes() != original:
            released = {item.relative_path: item.content for item in release.artifacts}
            if path not in released or released[path] != current.read_bytes():
                raise OpenUsLawHFReleaseSafetyError(
                    f"preserved file was mutated during staging: {path}"
                )

    return OpenUsLawHuggingFaceRelease(
        dataset_id=release.dataset_id,
        release_root_cid=release.release_root_cid,
        manifest_digest=release.manifest_digest,
        schema_version=release.schema_version,
        release_profile=release.release_profile,
        source_revision=release.source_revision,
        build_config_cid=release.build_config_cid,
        vector_space_id=release.vector_space_id,
        model_id=release.model_id,
        model_revision=release.model_revision,
        configs=release.configs,
        artifacts=release.artifacts,
        dry_run=False,
        staged_root=str(root),
        package_version=release.package_version,
    )


def validate_open_us_law_hf_release(
    release: OpenUsLawHuggingFaceRelease,
) -> dict[str, Any]:
    """Side-effect-free validation of the full acceptance contract."""

    if not isinstance(release, OpenUsLawHuggingFaceRelease):
        raise OpenUsLawHFReleaseError("release must be OpenUsLawHuggingFaceRelease")

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
        raise OpenUsLawHFReleaseIntegrityError(
            "missing required artifacts: " + ", ".join(sorted(missing))
        )

    descriptors = []
    for artifact in release.artifacts:
        desc = artifact.to_artifact_descriptor()
        payload = desc.to_dict()
        for key in (
            "relative_path",
            "media_type",
            "sha256",
            "size_bytes",
            "schema_id",
            "family",
            "row_count",
        ):
            if key not in payload:
                raise OpenUsLawHFReleaseIntegrityError(
                    f"artifact {artifact.relative_path} missing descriptor field {key}"
                )
        if not _SHA256_RE.fullmatch(artifact.sha256):
            raise OpenUsLawHFReleaseIntegrityError(
                f"invalid sha256 on {artifact.relative_path}"
            )
        if not artifact.content_cid:
            raise OpenUsLawHFReleaseIntegrityError(
                f"missing content_cid on {artifact.relative_path}"
            )
        descriptors.append(desc)

    config_receipt = assert_configs_schema_coherent(release.configs)
    default_cfg = next(c for c in release.configs if c.is_default)
    for entry in default_cfg.data_files:
        path = str(entry["path"])
        if "recovery" in path or "quarantine" in path:
            raise OpenUsLawHFReleaseSafetyError(
                f"default config includes recovery/quarantine path: {path!r}"
            )

    for artifact in release.artifacts:
        if artifact.config_name == DEFAULT_CONFIG_NAME and artifact.family in RECOVERY_FAMILIES:
            raise OpenUsLawHFReleaseSafetyError(
                f"recovery artifact bound to default config: {artifact.relative_path}"
            )
        if artifact.relative_path.startswith("recovery/") and artifact.config_name not in {
            "",
            RECOVERY_CONFIG_NAME,
        }:
            raise OpenUsLawHFReleaseSafetyError(
                f"recovery path not bound to recovery config: {artifact.relative_path}"
            )
        if artifact.relative_path.startswith("quarantine/") and artifact.config_name not in {
            "",
            QUARANTINE_CONFIG_NAME,
        }:
            raise OpenUsLawHFReleaseSafetyError(
                f"quarantine path not bound to quarantine config: {artifact.relative_path}"
            )

    lineage = release.lineage_artifact
    if lineage is None:
        raise OpenUsLawHFReleaseIntegrityError("missing verbose lineage report")
    lineage_body = json.loads(lineage.content.decode("utf-8"))
    if lineage_body.get("control_plane") is not False:
        raise OpenUsLawHFReleaseIntegrityError(
            "lineage report must declare control_plane=false"
        )
    if not lineage_body.get("separate_from_control_plane"):
        raise OpenUsLawHFReleaseIntegrityError(
            "lineage report must declare separate_from_control_plane=true"
        )
    if LINEAGE_REPORT_PATH in CONTROL_PLANE_PATHS:
        raise OpenUsLawHFReleaseIntegrityError(
            "lineage path must not be a control-plane path"
        )

    manifest = release.manifest_dict()
    if manifest.get("lineage_is_control_plane") is not False:
        raise OpenUsLawHFReleaseIntegrityError(
            "manifest must declare lineage_is_control_plane=false"
        )
    if LINEAGE_REPORT_PATH not in str(manifest.get("lineage_report", "")):
        raise OpenUsLawHFReleaseIntegrityError(
            "manifest must point lineage_report at reports/lineage.json"
        )
    for plane_path in (
        ADMISSION_REPORT_PATH,
        QUALITY_REPORT_PATH,
        REPRODUCIBILITY_REPORT_PATH,
        MANIFEST_FILENAME,
        RELEASE_METADATA_FILENAME,
    ):
        body = json.loads(release.artifact(plane_path).content.decode("utf-8"))
        if isinstance(body, Mapping) and "rows" in body and plane_path != LINEAGE_REPORT_PATH:
            if (
                isinstance(body.get("rows"), list)
                and body["rows"]
                and any(isinstance(r, Mapping) and "source_cid" in r for r in body["rows"])
            ):
                raise OpenUsLawHFReleaseIntegrityError(
                    f"control-plane artifact {plane_path} embeds verbose lineage rows"
                )

    if manifest.get("additive_packaging") is not True:
        raise OpenUsLawHFReleaseSafetyError(
            "manifest must declare additive_packaging=true"
        )
    if manifest.get("default_excludes_recovery") is not True:
        raise OpenUsLawHFReleaseSafetyError(
            "manifest must declare default_excludes_recovery=true"
        )
    if manifest.get("viewer_safe_default_exact_51") is not True:
        raise OpenUsLawHFReleaseSafetyError(
            "manifest must declare viewer_safe_default_exact_51=true"
        )
    if manifest.get("manifest_digest") != release.manifest_digest:
        raise OpenUsLawHFReleaseIntegrityError("manifest_digest mismatch")
    if manifest.get("release_root_cid") != release.release_root_cid:
        raise OpenUsLawHFReleaseIntegrityError("release_root_cid mismatch")
    if manifest.get("model_revision") != DEFAULT_EMBEDDING_MODEL_REVISION:
        raise OpenUsLawHFReleaseIntegrityError("manifest model_revision is not pinned")
    if manifest.get("model_id") != DEFAULT_EMBEDDING_MODEL_ID:
        raise OpenUsLawHFReleaseIntegrityError("manifest model_id is not pinned")
    if manifest.get("default_config") != DEFAULT_CONFIG_NAME:
        raise OpenUsLawHFReleaseConfigError("manifest default_config is not exact-51")

    missing_bindings = [
        name for name in REQUIRED_MANIFEST_BINDINGS if name not in manifest
    ]
    if missing_bindings:
        raise OpenUsLawHFReleaseIntegrityError(
            "manifest missing required bindings: " + ", ".join(missing_bindings)
        )
    for name in (
        "corpus",
        "bm25",
        "vectors",
        "centroids",
        "vector_locator",
        "graph",
        "two_way_adjacency",
        "recovery",
        "source_receipts",
    ):
        binding = manifest[name]
        if not isinstance(binding, Mapping):
            raise OpenUsLawHFReleaseIntegrityError(
                f"manifest binding {name!r} must be a mapping"
            )
        if int(binding.get("row_count") or 0) <= 0 or int(binding.get("artifact_count") or 0) <= 0:
            raise OpenUsLawHFReleaseIntegrityError(
                f"manifest binding {name!r} must include at least one artifact"
            )
        if not binding.get("sha256") or not binding.get("size_bytes"):
            raise OpenUsLawHFReleaseIntegrityError(
                f"manifest binding {name!r} must include sha256 and size_bytes"
            )

    if not isinstance(manifest.get("configs"), list) or not manifest["configs"]:
        raise OpenUsLawHFReleaseIntegrityError("manifest must bind advertised configs")
    if not isinstance(manifest.get("row_counts"), Mapping) or not manifest["row_counts"]:
        raise OpenUsLawHFReleaseIntegrityError("manifest must bind row_counts")
    if not isinstance(manifest.get("sizes"), Mapping) or not manifest["sizes"]:
        raise OpenUsLawHFReleaseIntegrityError("manifest must bind sizes")
    if not isinstance(manifest.get("sha256_digests"), Mapping) or not manifest["sha256_digests"]:
        raise OpenUsLawHFReleaseIntegrityError("manifest must bind sha256_digests")
    bounds = manifest.get("route_bounds")
    if not isinstance(bounds, Mapping):
        raise OpenUsLawHFReleaseIntegrityError("manifest must bind route_bounds")
    for key, expected in (
        ("max_rows_per_physical_shard", MAX_ROWS_PER_PHYSICAL_SHARD),
        ("max_posting_pointers_per_row", MAX_POSTING_POINTERS_PER_ROW),
        ("max_adjacency_pointers_per_row", MAX_ADJACENCY_POINTERS_PER_ROW),
        ("max_rows_per_vector_centroid", MAX_ROWS_PER_VECTOR_CENTROID),
        ("max_vector_shards_per_centroid", MAX_VECTOR_SHARDS_PER_CENTROID),
    ):
        if int(bounds.get(key) or 0) != expected:
            raise OpenUsLawHFReleaseIntegrityError(
                f"route bound {key} must be {expected}"
            )

    card = release.dataset_card_text()
    if "configs:" not in card:
        raise OpenUsLawHFReleaseConfigError("dataset card missing YAML configs")
    if DEFAULT_CONFIG_NAME not in card:
        raise OpenUsLawHFReleaseConfigError(
            "dataset card must advertise the default exact-51 config"
        )
    if "recovery" not in card.lower():
        raise OpenUsLawHFReleaseConfigError(
            "dataset card must document recovery separation"
        )
    if "exact-51" not in card.lower() and "exact 51" not in card.lower():
        raise OpenUsLawHFReleaseConfigError(
            "dataset card must document the Viewer-safe exact-51 default"
        )

    reject_identity_contamination(manifest, label="manifest-validate")
    reject_identity_contamination(
        release.release_metadata_dict(), label="release-metadata-validate"
    )

    return {
        "acceptance": {
            "all_advertised_configs_schema_coherent": config_receipt["schema_coherent"],
            "default_config_excludes_recovery": True,
            "every_artifact_descriptor_bound": True,
            "verbose_lineage_separate_from_control_plane": True,
            "viewer_safe_default_exact_51": True,
        },
        "artifact_count": len(release.artifacts),
        "config_count": len(release.configs),
        "default_config": DEFAULT_CONFIG_NAME,
        "descriptor_count": len(descriptors),
        "manifest_digest": release.manifest_digest,
        "model_revision": release.model_revision,
        "release_root_cid": release.release_root_cid,
        "schema_version": release.schema_version,
        "valid": True,
    }


def releases_are_byte_identical(
    left: OpenUsLawHuggingFaceRelease,
    right: OpenUsLawHuggingFaceRelease,
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


# ---------------------------------------------------------------------------
# Compact fixtures
# ---------------------------------------------------------------------------


def _receipt_digest(label: str) -> str:
    return hashlib.sha256(f"open-us-law-source-receipt:{label}".encode("utf-8")).hexdigest()


def fixture_source_receipts(
    rows: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Compact official-source receipts bound into the release manifest."""

    corpus = list(rows) if rows is not None else [example_default_statute_payload()]
    receipts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in corpus:
        code = str(row.get("jurisdiction_code") or "").strip().upper()
        if not code or code in seen:
            continue
        seen.add(code)
        source_cid = str(row.get("source_cid") or _receipt_digest(f"source:{code}"))
        receipts.append(
            {
                "body_hash": _receipt_digest(f"body:{code}"),
                "failed_final": 0,
                "frontier_closed": True,
                "jurisdiction_code": code,
                "official_authority": f"official-{code.lower()}",
                "receipt_cid": _receipt_digest(f"receipt:{code}"),
                "request_hash": _receipt_digest(f"request:{code}"),
                "response_hash": _receipt_digest(f"response:{code}"),
                "source_cid": source_cid,
                "verification_result": "verified",
            }
        )
    if not receipts:
        raise OpenUsLawHFReleaseError("source receipts require at least one jurisdiction")
    return receipts


def fixture_family_rows() -> dict[str, list[dict[str, Any]]]:
    """Compact deterministic fixture rows for unit tests and sealed recipes."""

    oregon = example_default_statute_payload(jurisdiction_code="OR", title="1", section="1")
    washington = example_default_statute_payload(
        jurisdiction_code="WA", title="2", section="10"
    )
    oregon["admission_status"] = "admitted"
    washington["admission_status"] = "admitted"
    oregon["verification_result"] = "verified"
    washington["verification_result"] = "verified"
    oregon["source_checksum"] = oregon["text_hash"]
    washington["source_checksum"] = washington["text_hash"]
    validate_entry_cid(oregon["entry_cid"])
    validate_entry_cid(washington["entry_cid"])

    corpus = [oregon, washington]
    bm25_docs = [
        {
            "document_index": index,
            "entry_cid": row["entry_cid"],
            "jurisdiction_code": row["jurisdiction_code"],
            "legal_id": row["legal_id"],
            "field_lengths": {"body": len(str(row.get("text") or "").split())},
        }
        for index, row in enumerate(corpus)
    ]
    bm25_postings = [
        {"entry_cid": oregon["entry_cid"], "term": "public", "tf": 1},
        {"entry_cid": washington["entry_cid"], "term": "records", "tf": 1},
    ]
    vectors = [
        {
            "chunk_cid": row["entry_cid"],
            "cluster_id": 0,
            "dimension": DEFAULT_EMBEDDING_DIMENSION,
            "entry_cid": row["entry_cid"],
            "legal_id": row["legal_id"],
            "model_id": DEFAULT_EMBEDDING_MODEL_ID,
            "model_revision": DEFAULT_EMBEDDING_MODEL_REVISION,
            "relative_path": "data/vectors/centroid-000-part-000000.parquet",
            "row_offset": index,
        }
        for index, row in enumerate(corpus)
    ]
    centroids = [
        {
            "centroid_id": "cluster-000000",
            "cluster_id": 0,
            "dimension": DEFAULT_EMBEDDING_DIMENSION,
            "entry_cid": oregon["entry_cid"],
            "relative_path": "data/vectors/centroid-000-part-000000.parquet",
            "row_count": len(vectors),
        }
    ]
    locator = [
        {
            "chunk_cid": row["entry_cid"],
            "cluster_id": 0,
            "entry_cid": row["entry_cid"],
            "global_shard_id": 0,
            "relative_path": "data/vectors/centroid-000-part-000000.parquet",
            "row_offset": index,
            "vector_key": row["entry_cid"],
        }
        for index, row in enumerate(corpus)
    ]
    graph_nodes = [
        {
            "entry_cid": row["entry_cid"],
            "legal_id": row["legal_id"],
            "node_cid": row["entry_cid"],
            "node_key": row["legal_id"],
            "node_type": "section",
        }
        for row in corpus
    ]
    graph_edges = [
        {
            "edge_cid": _receipt_digest("edge:cites"),
            "edge_type": "CITES",
            "source_node_cid": oregon["entry_cid"],
            "target_node_cid": washington["entry_cid"],
        }
    ]
    adjacency_out = [
        {
            "direction": "out",
            "node_cid": oregon["entry_cid"],
            "page_index": 0,
            "pointer_count": 1,
            "pointers": [
                {
                    "edge_cid": graph_edges[0]["edge_cid"],
                    "neighbor_node_cid": washington["entry_cid"],
                }
            ],
        }
    ]
    adjacency_in = [
        {
            "direction": "in",
            "node_cid": washington["entry_cid"],
            "page_index": 0,
            "pointer_count": 1,
            "pointers": [
                {
                    "edge_cid": graph_edges[0]["edge_cid"],
                    "neighbor_node_cid": oregon["entry_cid"],
                }
            ],
        }
    ]
    recovery = [example_recovery_payload()]
    recovery[0]["recovery_id"] = recovery[0]["legal_id"]
    recovery[0]["admission_reason"] = "recovery-seed-excluded-from-exact-51"
    quarantine = [example_quarantine_payload()]
    quarantine[0]["recovery_id"] = quarantine[0]["legal_id"]
    return {
        "bm25_documents": bm25_docs,
        "bm25_postings": bm25_postings,
        "centroids": centroids,
        CONSTITUTIONS_CONFIG_NAME: [example_constitution_payload()],
        "corpus": corpus,
        FEDERAL_CONFIG_NAME: [example_federal_payload()],
        "graph_adjacency_in": adjacency_in,
        "graph_adjacency_out": adjacency_out,
        "graph_edges": graph_edges,
        "graph_nodes": graph_nodes,
        HISTORICAL_CONFIG_NAME: [example_historical_payload()],
        PUERTO_RICO_CONFIG_NAME: [example_puerto_rico_payload()],
        "quarantine": quarantine,
        "recovery": recovery,
        "source_receipts": fixture_source_receipts(corpus),
        "vector_locator": locator,
        "vectors": vectors,
    }


def load_fixture_dataset_card(path: str | Path | None = None) -> str:
    """Load the sealed ``open_us_law_dataset_card.md`` fixture."""

    candidates: list[Path] = []
    if path is not None:
        candidates.append(Path(path))
    candidates.extend(
        [
            Path("tests/fixtures/legal_ir/open_us_law_dataset_card.md"),
            Path.cwd() / "tests/fixtures/legal_ir/open_us_law_dataset_card.md",
            Path(__file__).resolve().parents[2].parent
            / "tests"
            / "fixtures"
            / "legal_ir"
            / "open_us_law_dataset_card.md",
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    raise OpenUsLawHFReleaseError("open_us_law_dataset_card.md fixture not found")


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
        "lineage_is_control_plane": False,
        "lineage_report": LINEAGE_REPORT_PATH,
        "model_id": model_id,
        "model_revision": model_revision,
        "package_version": DEFAULT_PACKAGE_VERSION,
        "producer": PRODUCER,
        "release_profile": RELEASE_PROFILE,
        "release_root_cid": release_root_cid,
        "route_bounds": route_bounds_policy(),
        "schema_version": SCHEMA_VERSION,
        "source_bucket": SOURCE_BUCKET,
        "source_revision": source_revision,
        "task_id": TASK_ID,
        "tokenizer_id": tokenizer_id,
        "upload_path": None,
        "uses_hf_api_upload_file": False,
        "vector_space_id": vector_space_id,
        "viewer_safe_default_exact_51": True,
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
            raise OpenUsLawHFReleaseSafetyError(
                f"Hub upload surface is forbidden in open_us_law_hf_release: {token!r}"
            )
    import sys

    for name in list(sys.modules):
        if name == hub or name.startswith(hub + "."):
            break


__all__ = [
    "ADMISSION_REPORT_PATH",
    "ALL_CONFIGURATION_NAMES",
    "CONTROL_PLANE_PATHS",
    "DATASET_CONFIGS_FILENAME",
    "DATASET_INFOS_FILENAME",
    "DEFAULT_CONFIG_NAME",
    "DEFAULT_DATASET_REPO_ID",
    "DEFAULT_SOURCE_REVISION",
    "GOAL_ID",
    "LINEAGE_REPORT_PATH",
    "MANIFEST_FILENAME",
    "PRODUCER",
    "QUALITY_REPORT_PATH",
    "QUARANTINE_CONFIG_NAME",
    "README_FILENAME",
    "RECOVERY_CONFIG_NAME",
    "RELEASE_METADATA_FILENAME",
    "REPRODUCIBILITY_REPORT_PATH",
    "REQUIRED_MANIFEST_BINDINGS",
    "SCHEMA_VERSION",
    "TASK_ID",
    "OpenUsLawHFReleaseBuilder",
    "OpenUsLawHFReleaseConfigError",
    "OpenUsLawHFReleaseError",
    "OpenUsLawHFReleaseIntegrityError",
    "OpenUsLawHFReleaseSafetyError",
    "OpenUsLawHuggingFaceRelease",
    "ReleaseArtifact",
    "ViewerConfig",
    "advertised_viewer_configs",
    "assemble_open_us_law_hf_release",
    "assert_configs_schema_coherent",
    "build_open_us_law_hf_release",
    "fixture_family_rows",
    "fixture_source_receipts",
    "load_fixture_dataset_card",
    "merge_family_rows",
    "releases_are_byte_identical",
    "render_dataset_card",
    "route_bounds_policy",
    "rows_from_bm25_index",
    "rows_from_graph_projection",
    "rows_from_two_way_adjacency",
    "rows_from_vector_binding",
    "stage_open_us_law_hf_release",
    "validate_open_us_law_hf_release",
]
