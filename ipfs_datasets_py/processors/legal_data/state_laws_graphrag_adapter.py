"""Adapt the shared bounded Hub GraphRAG substrate to state laws (LCR-026).

This module is the legal-domain adapter between:

* state-law v2 schemas, filters, and official provenance
  (:mod:`state_laws_release_schema`, :mod:`state_laws_corpus`,
  :mod:`state_laws_chunker`); and
* the domain-neutral Hugging Face GraphRAG substrate
  (:mod:`ipfs_datasets_py.retrieval.hf_graphrag`).

It maps state records onto bounded writers, CID locators, manifest
descriptors, the immutable Hub resolver, and streaming/external-sort
interfaces. Shared ``hf_graphrag`` modules are consumed, not forked.

Design invariants
-----------------
* Required semantic families must close on the default release.
* Vector shards must be centroid-specific; a fake global ``centroid-000``
  layout, hash-mod, round-robin, or positional assignment is rejected.
* Incoming and outgoing adjacency are both mandatory and must reconcile
  every durable edge.
* Full official-source lineage lives once per source document. Posting
  cells, adjacency pages, and compact locators must not duplicate it.
* Artifact paths are release-relative POSIX paths. Absolute, home, and
  drive-letter paths fail closed.
* The default Viewer/release config is the exact 51-jurisdiction set
  (50 states + DC). Subset, IA-only, and sample configs cannot be default.
* Manifest descriptors bind path, SHA-256, size, and row count. Drift
  against observed bytes fails closed.
* The adapter never contacts the Hub, never uploads, and never writes a
  cache under a home path unless the caller supplies an explicit cache
  directory. Unit tests inject :class:`MappingTransport`.

Physical sharding of structure-aware chunks (LCR-025) is owned here.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Final, Optional, Union
import hashlib
import json
import os
import re

from ipfs_datasets_py.processors.legal_data.state_laws_completeness import (
    CANONICAL_JURISDICTION_ORDER,
    EXPECTED_JURISDICTION_COUNT,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    ADR_PATH,
    CANONICAL_JURISDICTIONS,
    DEFAULT_DATASET_REPO_ID,
    DEFAULT_EMBEDDING_MODEL_ID,
    DEFAULT_EMBEDDING_MODEL_REVISION,
    MAX_ADJACENCY_POINTERS_PER_ROW,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    MAX_ROWS_PER_VECTOR_CENTROID,
    MAX_VECTOR_SHARDS_PER_CENTROID,
    PREVIOUS_PUBLIC_PIN,
    RELEASE_PROFILE,
    REQUIRED_SEMANTIC_FAMILIES,
    SCHEMA_VERSION as RELEASE_SCHEMA_VERSION,
    AdjacencyRecord,
    ArtifactDescriptor as StateArtifactDescriptor,
    ArtifactFamily as StateArtifactFamily,
    ArtifactPathError as StateArtifactPathError,
    GraphEdgeRecord,
    GraphNodeRecord,
    LocatorRecord,
    PhysicalBoundError as StatePhysicalBoundError,
    SemanticFamilyClosureError,
    content_sha256,
    digest_mapping,
    example_manifest_payload,
    normalize_relative_artifact_path,
    normalize_sha256,
    require_immutable_revision,
    required_semantic_families,
    validate_centroid_capacity,
    validate_entry_cid,
    validate_jurisdiction,
    validate_jurisdiction_set,
    validate_semantic_family_closure,
)
from ipfs_datasets_py.retrieval.hf_graphrag.artifacts import (
    ArtifactWriterConfig,
    shard_sequence,
    stable_sort_rows,
    write_bounded_shards,
)
from ipfs_datasets_py.retrieval.hf_graphrag.external_sort import (
    DEFAULT_MAX_RECORDS_IN_MEMORY,
    MemoryBudget,
    external_sort_to_file,
    sort_key_for_family,
    stream_bounded_partitions,
    stream_sorted_partitions,
)
from ipfs_datasets_py.retrieval.hf_graphrag.graph import (
    GraphEdge,
    GraphNode,
    coerce_graph_edges,
    coerce_graph_nodes,
)
from ipfs_datasets_py.retrieval.hf_graphrag.locators import (
    KIND_CORPUS,
    KIND_VECTORS,
    DualCidLocators,
    KeyLocatorIndex,
    LocatorRow,
    build_corpus_locator,
    build_dual_cid_locators,
    build_vector_locator,
)
from ipfs_datasets_py.retrieval.hf_graphrag.resolver import (
    DEFAULT_SUPPORTED_RELEASE_SCHEMAS,
    ArtifactDescriptor as ResolverArtifactDescriptor,
    ImmutableHubResolver,
)
from ipfs_datasets_py.retrieval.hf_graphrag.schema import (
    DESCRIPTOR_SCHEMA_VERSION,
    PARQUET_MEDIA_TYPE,
    ArtifactDescriptor as SharedArtifactDescriptor,
    ArtifactFamily as SharedArtifactFamily,
    ArtifactPathError as SharedArtifactPathError,
    part_filename,
    physical_bounds_policy as shared_physical_bounds_policy,
)
from ipfs_datasets_py.retrieval.hf_graphrag.vectors import (
    ASSIGNMENT as SHARED_CENTROID_ASSIGNMENT,
    VECTOR_DATA_DIR,
)

# ---------------------------------------------------------------------------
# Identity / pins
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "state-laws-graphrag-adapter/v1"
REPORT_SCHEMA: Final = "ipfs_datasets_py/legal-corpora-reindex-substrate-compatibility@1"
TASK_ID: Final = "LCR-026"
GOAL_ID: Final = "LCR-G030"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
BOARD_NAMESPACE: Final = "legal-corpora-reindex-v1"
BUNDLE: Final = "shared-substrate"
PRODUCER: Final = "state_laws_graphrag_adapter.py"
GRAPH_ONTOLOGY_VERSION: Final = "state-laws-graph-ontology/v1"
DEFAULT_VIEWER_CONFIG: Final = "state_statutes_exact_51"
PRIMARY_KEY: Final = "entry_cid"
REQUIRED_CENTROID_ASSIGNMENT: Final = SHARED_CENTROID_ASSIGNMENT

AUTHORIZES_PUBLICATION: Final = False
AUTHORIZES_HUB_UPLOAD: Final = False
AUTHORIZES_RELEASE: Final = False
AUTHORIZES_NETWORK: Final = False

REPORT_RELATIVE_PATH: Final = (
    "docs/reports/legal_corpora_reindex/substrate_compatibility.json"
)
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REPORT_PATH: Final = _REPO_ROOT / REPORT_RELATIVE_PATH

SUPPORTED_RELEASE_SCHEMAS: Final = frozenset(
    {
        RELEASE_PROFILE,
        RELEASE_SCHEMA_VERSION,
        SCHEMA_VERSION,
        DESCRIPTOR_SCHEMA_VERSION,
        "hf-graphrag-release/v1",
        "hf-graphrag-artifact-schema/v1",
        "publicus-ir-graphrag/v2",
        "uscode-sparse-graphrag-release-schema-v2",
        *DEFAULT_SUPPORTED_RELEASE_SCHEMAS,
    }
)

SHARED_SUBSTRATE_MODULES: Final = (
    "ipfs_datasets_py/retrieval/hf_graphrag/schema.py",
    "ipfs_datasets_py/retrieval/hf_graphrag/artifacts.py",
    "ipfs_datasets_py/retrieval/hf_graphrag/locators.py",
    "ipfs_datasets_py/retrieval/hf_graphrag/resolver.py",
    "ipfs_datasets_py/retrieval/hf_graphrag/external_sort.py",
    "ipfs_datasets_py/retrieval/hf_graphrag/graph.py",
    "ipfs_datasets_py/retrieval/hf_graphrag/vectors.py",
)

FAMILY_RELATIVE_DIRS: Final = MappingProxyType(
    {
        SharedArtifactFamily.CORPUS.value: "data/corpus",
        SharedArtifactFamily.BM25_DOCUMENTS.value: "data/bm25/documents",
        SharedArtifactFamily.BM25_POSTINGS.value: "data/bm25/postings",
        SharedArtifactFamily.VECTORS.value: VECTOR_DATA_DIR,
        SharedArtifactFamily.CENTROIDS.value: "data/vectors",
        SharedArtifactFamily.GRAPH_NODES.value: "data/graph/nodes",
        SharedArtifactFamily.GRAPH_EDGES.value: "data/graph/edges",
        SharedArtifactFamily.GRAPH_ADJACENCY_OUT.value: "data/graph/adjacency/out",
        SharedArtifactFamily.GRAPH_ADJACENCY_IN.value: "data/graph/adjacency/in",
        SharedArtifactFamily.LOCATOR_INDEX.value: "indexes",
        SharedArtifactFamily.ROUTING_INDEX.value: "indexes",
        SharedArtifactFamily.MANIFEST.value: ".",
        SharedArtifactFamily.RECEIPT.value: "receipts",
        SharedArtifactFamily.REPORT.value: "reports",
        SharedArtifactFamily.RELEASE_METADATA.value: ".",
    }
)

JURISDICTION_PARTITIONED_FAMILIES: Final = frozenset(
    {
        SharedArtifactFamily.CORPUS.value,
        SharedArtifactFamily.BM25_DOCUMENTS.value,
    }
)

FAMILY_PRIMARY_KEYS: Final = MappingProxyType(
    {
        SharedArtifactFamily.CORPUS.value: ("entry_cid",),
        SharedArtifactFamily.BM25_DOCUMENTS.value: ("entry_cid",),
        SharedArtifactFamily.BM25_POSTINGS.value: ("term",),
        SharedArtifactFamily.VECTORS.value: ("entry_cid",),
        SharedArtifactFamily.CENTROIDS.value: ("centroid_id",),
        SharedArtifactFamily.GRAPH_NODES.value: ("node_cid",),
        SharedArtifactFamily.GRAPH_EDGES.value: ("edge_cid",),
        SharedArtifactFamily.GRAPH_ADJACENCY_OUT.value: ("node_cid",),
        SharedArtifactFamily.GRAPH_ADJACENCY_IN.value: ("node_cid",),
        SharedArtifactFamily.LOCATOR_INDEX.value: ("first_key",),
        SharedArtifactFamily.ROUTING_INDEX.value: ("first_key",),
    }
)

FAMILY_TIE_BREAKERS: Final = MappingProxyType(
    {
        SharedArtifactFamily.CORPUS.value: ("legal_id", "entry_cid"),
        SharedArtifactFamily.BM25_DOCUMENTS.value: ("entry_cid",),
        SharedArtifactFamily.BM25_POSTINGS.value: ("term",),
        SharedArtifactFamily.VECTORS.value: ("entry_cid",),
        SharedArtifactFamily.CENTROIDS.value: ("centroid_id",),
        SharedArtifactFamily.GRAPH_NODES.value: ("node_cid",),
        SharedArtifactFamily.GRAPH_EDGES.value: ("edge_cid",),
        SharedArtifactFamily.GRAPH_ADJACENCY_OUT.value: ("node_cid", "page_index"),
        SharedArtifactFamily.GRAPH_ADJACENCY_IN.value: ("node_cid", "page_index"),
        SharedArtifactFamily.LOCATOR_INDEX.value: ("first_key", "relative_path"),
        SharedArtifactFamily.ROUTING_INDEX.value: ("first_key", "relative_path"),
    }
)

# State-only families project onto the nearest shared family.
_STATE_FAMILY_ALIASES: Final = MappingProxyType(
    {
        "source_receipt": SharedArtifactFamily.RECEIPT,
        "scrape_receipt": SharedArtifactFamily.RECEIPT,
        "acquisition_receipt": SharedArtifactFamily.RECEIPT,
        "recovery": SharedArtifactFamily.REPORT,
        "publication": SharedArtifactFamily.RELEASE_METADATA,
        "rollback": SharedArtifactFamily.RECEIPT,
    }
)

FILTER_FIELDS: Final = (
    "jurisdiction",
    "code_family",
    "title",
    "chapter",
    "section",
    "subsection",
    "edition",
    "status",
    "release_point",
    "legal_id",
    "source",
    "version",
)

PROVENANCE_FIELDS: Final = (
    "source_cid",
    "release_point",
    "source_checksum",
    "verification_result",
    "acquisition_time",
    "official_source_url",
    "acquisition_receipt_id",
    "parser_version",
    "jurisdiction",
    "code_family",
    "source_authority_class",
)

# Full source lineage must not be copied onto postings / adjacency / locators.
LINEAGE_FORBIDDEN_ON_INDEX_FAMILIES: Final = frozenset(
    {
        "official_source_url",
        "acquisition_receipt_id",
        "parser_version",
        "acquisition_time",
        "source_checksum",
        "release_point",
        "source_authority_class",
        "verification_result",
        "source_lineage",
        "full_lineage",
        "lineage_payload",
        "lineage",
    }
)

INDEX_FAMILIES_WITHOUT_LINEAGE: Final = frozenset(
    {
        SharedArtifactFamily.BM25_POSTINGS.value,
        SharedArtifactFamily.GRAPH_ADJACENCY_OUT.value,
        SharedArtifactFamily.GRAPH_ADJACENCY_IN.value,
        SharedArtifactFamily.LOCATOR_INDEX.value,
        SharedArtifactFamily.ROUTING_INDEX.value,
        "postings",
        "bm25",
    }
)

FAKE_CENTROID_ASSIGNMENTS: Final = frozenset(
    {
        "hash-mod",
        "hash_mod",
        "hashmod",
        "mod-n",
        "modulo",
        "round-robin",
        "round_robin",
        "single-centroid",
        "single_centroid",
        "global",
        "global-centroid",
        "global_centroid",
        "nominal",
        "nominal-centroid",
        "fake",
        "document_index",
        "row-index",
        "row_index",
        "positional",
        "all-in-one",
        "all_in_one",
    }
)

SUBSET_CONFIG_MARKERS: Final = frozenset(
    {
        "ia",
        "canonical_ia",
        "embeddings_sample",
        "embedding_sample",
        "one_state",
        "single_state",
        "subset",
        "sample",
        "legacy-sample",
        "legacy_sample",
        "requested_scope",
        "partial",
    }
)

_HOME_PATH_RE: Final = re.compile(r"(?:/home/|/Users/|\\\\Users\\\\)")
_TOKEN_RE: Final = re.compile(
    r"(?:hf_[A-Za-z0-9]{10,}|Bearer\s+[A-Za-z0-9\-._~+/]+=*)",
    re.IGNORECASE,
)
_CENTROID_PATH_RE: Final = re.compile(r"centroid-(\d+)")

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class StateLawsGraphragAdapterError(ValueError):
    """Base error for the state-law GraphRAG substrate adapter."""

    code: str = "state_laws_graphrag_adapter_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class AbsentSemanticFamilyError(StateLawsGraphragAdapterError):
    """Raised when a default release omits a required semantic family."""

    code = "absent_semantic_family"


class FakeCentroidPlacementError(StateLawsGraphragAdapterError):
    """Raised when vector shards are not true centroid-routed placement."""

    code = "fake_centroid_placement"


class MissingTwoWayAdjacencyError(StateLawsGraphragAdapterError):
    """Raised when incoming or outgoing adjacency is missing or unreconciliation."""

    code = "missing_two_way_adjacency"


class UnsafeLineageDuplicationError(StateLawsGraphragAdapterError):
    """Raised when full source lineage is copied onto index families."""

    code = "unsafe_lineage_duplication"


class AbsolutePathError(StateLawsGraphragAdapterError):
    """Raised when an artifact path is absolute or otherwise unsafe."""

    code = "absolute_path"


class SubsetConfigError(StateLawsGraphragAdapterError):
    """Raised when a default Viewer/release config is a jurisdiction subset."""

    code = "subset_config"


class DescriptorDriftError(StateLawsGraphragAdapterError):
    """Raised when a descriptor disagrees with observed bytes or counts."""

    code = "descriptor_drift"


class AdapterPinError(StateLawsGraphragAdapterError):
    """Raised when a Dataset pin is mutable or missing."""

    code = "immutable_pin_invalid"


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 1024) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StateLawsGraphragAdapterError(f"{name} must be a non-empty string")
    text = value.strip()
    if "\x00" in text:
        raise StateLawsGraphragAdapterError(f"{name} must not contain NUL")
    if len(text) > maximum:
        raise StateLawsGraphragAdapterError(
            f"{name} exceeds maximum length {maximum}"
        )
    return text


def _require_non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise StateLawsGraphragAdapterError(f"{name} must be an integer")
    if value < 0:
        raise StateLawsGraphragAdapterError(f"{name} must be >= 0")
    return value


def _as_mapping(value: Any, name: str) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        payload = value.to_dict()
        if isinstance(payload, Mapping):
            return dict(payload)
    if isinstance(value, Mapping):
        return dict(value)
    raise StateLawsGraphragAdapterError(f"{name} must be a mapping")


def _as_sequence(value: Any, name: str) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, bytearray)):
        raise StateLawsGraphragAdapterError(f"{name} must be a sequence of records")
    if isinstance(value, Sequence):
        return tuple(value)
    if isinstance(value, (set, frozenset)):
        return tuple(value)
    raise StateLawsGraphragAdapterError(f"{name} must be a sequence")


def _fold_token(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _contains_home_or_token(payload: Any) -> bool:
    rendered = (
        payload
        if isinstance(payload, str)
        else json.dumps(payload, sort_keys=True, default=str)
    )
    if _HOME_PATH_RE.search(rendered):
        return True
    if _TOKEN_RE.search(rendered):
        return True
    for name in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HUGGINGFACE_TOKEN"):
        secret = os.environ.get(name)
        if secret and secret in rendered:
            return True
    return False


def assert_no_home_paths_or_tokens(payload: Any) -> None:
    """Fail closed when a public surface would leak home paths or tokens."""

    if _contains_home_or_token(payload):
        raise StateLawsGraphragAdapterError(
            "adapter payload must not contain home paths or token material"
        )


def require_relative_artifact_path(value: Any, *, name: str = "relative_path") -> str:
    """Require a confined POSIX path relative to the release root."""

    text = _require_non_empty_str(value, name, maximum=512)
    if text.startswith("/") or text.startswith("~") or "\\" in text:
        raise AbsolutePathError(f"{name} must be relative, not absolute: {value!r}")
    if len(text) >= 2 and text[1] == ":":
        raise AbsolutePathError(f"{name} must not include a drive letter: {value!r}")
    if _HOME_PATH_RE.search(text):
        raise AbsolutePathError(f"{name} must not contain a home path: {value!r}")
    try:
        return normalize_relative_artifact_path(text, name=name)
    except StateArtifactPathError as exc:
        raise AbsolutePathError(str(exc)) from exc
    except SharedArtifactPathError as exc:
        raise AbsolutePathError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Family / path mapping
# ---------------------------------------------------------------------------


def map_state_family_to_shared(value: Any) -> SharedArtifactFamily:
    """Map a state-law family token onto the shared :class:`ArtifactFamily`."""

    if isinstance(value, SharedArtifactFamily):
        return value
    if isinstance(value, StateArtifactFamily):
        alias = _STATE_FAMILY_ALIASES.get(value.value)
        if alias is not None:
            return alias
        return SharedArtifactFamily.coerce(value.value)
    text = _fold_token(value)
    if text in _STATE_FAMILY_ALIASES:
        return _STATE_FAMILY_ALIASES[text]
    try:
        return SharedArtifactFamily.coerce(value)
    except Exception as exc:
        raise StateLawsGraphragAdapterError(
            f"unknown artifact family: {value!r}"
        ) from exc


def family_relative_dir(
    family: Any,
    *,
    jurisdiction: str | None = None,
) -> str:
    """Return the release-relative directory for *family*."""

    shared = map_state_family_to_shared(family)
    base = FAMILY_RELATIVE_DIRS.get(shared.value)
    if not base:
        raise StateLawsGraphragAdapterError(
            f"no relative directory for family {shared.value!r}"
        )
    if shared.value in JURISDICTION_PARTITIONED_FAMILIES:
        code = validate_jurisdiction(jurisdiction, name="jurisdiction")
        return f"{base}/jurisdiction={code}"
    if base == ".":
        return ""
    return base


def family_primary_keys(family: Any) -> tuple[str, ...]:
    shared = map_state_family_to_shared(family)
    keys = FAMILY_PRIMARY_KEYS.get(shared.value)
    if not keys:
        return (PRIMARY_KEY,)
    return tuple(keys)


def family_tie_breakers(family: Any) -> tuple[str, ...]:
    shared = map_state_family_to_shared(family)
    return tuple(FAMILY_TIE_BREAKERS.get(shared.value, (PRIMARY_KEY,)))


def default_writer_config() -> ArtifactWriterConfig:
    """Return the sealed 4,096-row/pointer writer configuration."""

    return ArtifactWriterConfig(
        max_rows_per_shard=MAX_ROWS_PER_PHYSICAL_SHARD,
        max_pointers_per_row=MAX_ADJACENCY_POINTERS_PER_ROW,
    )


# ---------------------------------------------------------------------------
# Descriptor mapping
# ---------------------------------------------------------------------------


def to_shared_artifact_descriptor(
    descriptor: StateArtifactDescriptor | Mapping[str, Any],
) -> SharedArtifactDescriptor:
    """Project a state-law descriptor onto the shared descriptor contract."""

    if isinstance(descriptor, StateArtifactDescriptor):
        payload = descriptor.to_dict()
    elif isinstance(descriptor, Mapping):
        payload = dict(descriptor)
    else:
        raise StateLawsGraphragAdapterError("descriptor must be a mapping")
    relative = require_relative_artifact_path(
        payload.get("relative_path") or payload.get("path") or ""
    )
    family = map_state_family_to_shared(payload.get("family", "corpus"))
    metadata = {
        key: value
        for key, value in {
            "jurisdiction": payload.get("jurisdiction"),
            "centroid_id": payload.get("centroid_id"),
        }.items()
        if value not in (None, "")
    }
    return SharedArtifactDescriptor(
        relative_path=relative,
        sha256=payload.get("sha256") or "",
        size_bytes=int(payload.get("size_bytes") or 0),
        row_count=int(payload.get("row_count") or 0),
        media_type=str(payload.get("media_type") or PARQUET_MEDIA_TYPE),
        schema_id=str(payload.get("schema_id") or DESCRIPTOR_SCHEMA_VERSION),
        family=family,
        first_key=payload.get("first_key"),
        last_key=payload.get("last_key"),
        key_range=payload.get("key_range"),
        metadata=metadata,
    )


def to_resolver_descriptor(
    descriptor: StateArtifactDescriptor
    | SharedArtifactDescriptor
    | Mapping[str, Any],
) -> ResolverArtifactDescriptor:
    """Project a descriptor onto the immutable resolver descriptor."""

    if isinstance(descriptor, SharedArtifactDescriptor):
        payload = descriptor.to_dict()
    elif isinstance(descriptor, StateArtifactDescriptor):
        payload = descriptor.to_dict()
    elif isinstance(descriptor, Mapping):
        payload = dict(descriptor)
    else:
        raise StateLawsGraphragAdapterError("descriptor must be a mapping")
    relative = require_relative_artifact_path(
        payload.get("relative_path") or payload.get("path") or ""
    )
    return ResolverArtifactDescriptor(
        relative_path=relative,
        size_bytes=int(payload.get("size_bytes") or 0),
        sha256=str(payload.get("sha256") or ""),
        schema_id=str(payload.get("schema_id") or payload.get("schema_version") or ""),
        row_count=payload.get("row_count"),
        cid=payload.get("content_cid") or payload.get("cid"),
        media_type=str(payload.get("media_type") or "application/octet-stream"),
    )


def to_state_artifact_descriptor(
    descriptor: SharedArtifactDescriptor | Mapping[str, Any],
    *,
    jurisdiction: str | None = None,
    centroid_id: str | None = None,
) -> StateArtifactDescriptor:
    """Project a shared descriptor back onto the state-law contract."""

    if isinstance(descriptor, SharedArtifactDescriptor):
        payload = descriptor.to_dict()
        metadata = dict(descriptor.metadata)
    elif isinstance(descriptor, Mapping):
        payload = dict(descriptor)
        metadata = dict(payload.get("metadata") or {})
    else:
        raise StateLawsGraphragAdapterError("descriptor must be a mapping")
    return StateArtifactDescriptor(
        relative_path=require_relative_artifact_path(payload.get("relative_path") or ""),
        media_type=str(payload.get("media_type") or PARQUET_MEDIA_TYPE),
        sha256=str(payload.get("sha256") or ""),
        size_bytes=int(payload.get("size_bytes") or 0),
        schema_id=str(payload.get("schema_id") or DESCRIPTOR_SCHEMA_VERSION),
        family=map_state_family_to_shared(payload.get("family", "corpus")).value,
        row_count=int(payload.get("row_count") or 0),
        first_key=payload.get("first_key"),
        last_key=payload.get("last_key"),
        centroid_id=centroid_id or payload.get("centroid_id") or metadata.get("centroid_id"),
        jurisdiction=jurisdiction
        or payload.get("jurisdiction")
        or metadata.get("jurisdiction"),
        key_range=payload.get("key_range"),
    )


# ---------------------------------------------------------------------------
# Locator mapping
# ---------------------------------------------------------------------------


def _locator_kind_for_family(family: Any) -> str:
    shared = map_state_family_to_shared(family)
    if shared is SharedArtifactFamily.CORPUS:
        return KIND_CORPUS
    if shared is SharedArtifactFamily.VECTORS:
        return KIND_VECTORS
    raise StateLawsGraphragAdapterError(
        f"shared locators support corpus and vectors, got {shared.value!r}"
    )


def to_locator_row(
    record: LocatorRecord | LocatorRow | Mapping[str, Any],
    *,
    shard_id: int = 0,
) -> LocatorRow:
    """Project a state-law locator record onto a shared :class:`LocatorRow`."""

    if isinstance(record, LocatorRow):
        return record
    if isinstance(record, LocatorRecord):
        payload = record.to_dict()
    elif isinstance(record, Mapping):
        payload = dict(record)
    else:
        raise StateLawsGraphragAdapterError("locator record must be a mapping")
    relative = require_relative_artifact_path(payload.get("relative_path") or "")
    family = payload.get("family") or payload.get("kind") or KIND_CORPUS
    kind = payload.get("kind")
    if kind in {KIND_CORPUS, KIND_VECTORS}:
        locator_kind = kind
    else:
        locator_kind = _locator_kind_for_family(family)
    metadata = {
        key: value
        for key, value in {
            "locator_id": payload.get("locator_id"),
            "jurisdiction": payload.get("jurisdiction"),
            "family": map_state_family_to_shared(family).value
            if family
            else locator_kind,
        }.items()
        if value not in (None, "")
    }
    return LocatorRow(
        first_key=str(payload.get("first_key") or ""),
        last_key=str(payload.get("last_key") or ""),
        relative_path=relative,
        sha256=str(payload.get("sha256") or ""),
        size_bytes=int(payload.get("size_bytes") or 0),
        row_count=int(payload.get("row_count") or 0),
        shard_id=int(payload.get("shard_id", shard_id) or 0),
        kind=locator_kind,
        metadata=metadata,
    )


def build_state_corpus_locator(
    records: Sequence[LocatorRecord | Mapping[str, Any]],
) -> KeyLocatorIndex:
    """Build a CID-to-corpus locator from state-law locator records."""

    rows = tuple(
        to_locator_row(record, shard_id=index)
        for index, record in enumerate(records)
    )
    return build_corpus_locator(rows)


def build_state_vector_locator(
    records: Sequence[LocatorRecord | Mapping[str, Any]],
) -> KeyLocatorIndex:
    """Build a CID-to-vector locator from state-law locator records."""

    rows = tuple(
        to_locator_row(record, shard_id=index)
        for index, record in enumerate(records)
    )
    return build_vector_locator(rows)


def build_state_dual_locators(
    *,
    corpus_records: Sequence[LocatorRecord | Mapping[str, Any]],
    vector_records: Sequence[LocatorRecord | Mapping[str, Any]],
) -> DualCidLocators:
    """Build paired corpus and vector locators sharing ``entry_cid``."""

    return build_dual_cid_locators(
        corpus_rows=tuple(
            to_locator_row(record, shard_id=index)
            for index, record in enumerate(corpus_records)
        ),
        vector_rows=tuple(
            to_locator_row(record, shard_id=index)
            for index, record in enumerate(vector_records)
        ),
    )


# ---------------------------------------------------------------------------
# Graph mapping
# ---------------------------------------------------------------------------


def to_shared_graph_node(
    record: GraphNodeRecord | Mapping[str, Any],
) -> GraphNode:
    """Project a state-law graph node onto the shared graph node type."""

    if isinstance(record, GraphNodeRecord):
        payload = record.to_dict()
    else:
        payload = _as_mapping(record, "graph node")
    return coerce_graph_nodes((payload,))[0]


def to_shared_graph_edge(
    record: GraphEdgeRecord | Mapping[str, Any],
) -> GraphEdge:
    """Project a state-law graph edge onto the shared graph edge type."""

    if isinstance(record, GraphEdgeRecord):
        payload = record.to_dict()
    else:
        payload = _as_mapping(record, "graph edge")
    return coerce_graph_edges((payload,))[0]


def _coerce_adjacency_record(value: Any) -> AdjacencyRecord:
    if isinstance(value, AdjacencyRecord):
        return value
    return AdjacencyRecord.from_mapping(_as_mapping(value, "adjacency"))


def _coerce_graph_edge_record(value: Any) -> GraphEdgeRecord:
    if isinstance(value, GraphEdgeRecord):
        return value
    if isinstance(value, GraphEdge):
        return GraphEdgeRecord.from_mapping(value.to_dict())
    return GraphEdgeRecord.from_mapping(_as_mapping(value, "graph edge"))


# ---------------------------------------------------------------------------
# Filters / provenance
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StateLawsFilters:
    """Jurisdiction-aware retrieval filters projected onto shared metadata."""

    jurisdiction: Optional[str] = None
    code_family: Optional[str] = None
    title: Optional[str] = None
    chapter: Optional[str] = None
    section: Optional[str] = None
    subsection: Optional[str] = None
    edition: Optional[str] = None
    status: Optional[str] = None
    release_point: Optional[str] = None
    legal_id: Optional[str] = None
    source: Optional[str] = None
    version: Optional[str] = None

    def __post_init__(self) -> None:
        if self.jurisdiction not in (None, ""):
            object.__setattr__(
                self, "jurisdiction", validate_jurisdiction(self.jurisdiction)
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            key: getattr(self, key)
            for key in FILTER_FIELDS
            if getattr(self, key) not in (None, "")
        }

    def to_metadata_equals(self) -> dict[str, str]:
        """Project onto shared query ``metadata_equals`` filters."""

        return {key: str(value) for key, value in self.to_dict().items()}

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "StateLawsFilters":
        if value is None:
            return cls()
        payload = dict(value) if isinstance(value, Mapping) else {}
        kwargs = {
            key: payload[key]
            for key in FILTER_FIELDS
            if key in payload and payload[key] not in (None, "")
        }
        return cls(**kwargs)


def project_corpus_provenance(record: Mapping[str, Any]) -> dict[str, Any]:
    """Extract official provenance fields from a corpus (document-level) row."""

    payload = _as_mapping(record, "corpus record")
    return {
        field: payload[field]
        for field in PROVENANCE_FIELDS
        if field in payload and payload[field] not in (None, "")
    }


def project_writer_row(
    record: Mapping[str, Any] | Any,
    family: Any,
) -> dict[str, Any]:
    """Project a state record onto a bounded-writer row for *family*.

    Corpus rows retain official provenance (once per document). Postings,
    adjacency, and locators fail closed if they carry duplicated lineage.
    """

    payload = _as_mapping(record, "writer row")
    shared = map_state_family_to_shared(family)
    if "relative_path" in payload and payload["relative_path"]:
        payload["relative_path"] = require_relative_artifact_path(
            payload["relative_path"]
        )
    if shared.value in INDEX_FAMILIES_WITHOUT_LINEAGE or _fold_token(family) in {
        "postings",
        "bm25",
        "bm25_postings",
    }:
        leaked = LINEAGE_FORBIDDEN_ON_INDEX_FAMILIES.intersection(payload)
        if leaked:
            raise UnsafeLineageDuplicationError(
                f"{shared.value} rows must not duplicate source lineage fields "
                f"{sorted(leaked)}"
            )
        if "source_cid" in payload and shared is SharedArtifactFamily.BM25_POSTINGS:
            raise UnsafeLineageDuplicationError(
                "bm25_postings must not copy source_cid lineage onto posting cells"
            )
    return payload


# ---------------------------------------------------------------------------
# Bounded writers / shard planning
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PlannedShard:
    """In-memory shard plan (no Parquet I/O) for one physical retrieval unit."""

    relative_path: str
    family: str
    row_count: int
    first_key: str
    last_key: str
    shard_id: int
    rows: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "first_key": self.first_key,
            "last_key": self.last_key,
            "relative_path": self.relative_path,
            "row_count": self.row_count,
            "shard_id": self.shard_id,
        }


def _row_key(row: Mapping[str, Any], keys: Sequence[str]) -> str:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    raise StateLawsGraphragAdapterError(
        f"row is missing sort keys {list(keys)}"
    )


def plan_bounded_shards(
    rows: Sequence[Mapping[str, Any] | Any],
    *,
    family: Any,
    jurisdiction: str | None = None,
    max_rows: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    sort: bool = True,
) -> tuple[PlannedShard, ...]:
    """Plan ≤4,096-row shards without writing Parquet.

    Physical sharding of LCR-025 chunks lives here. The integer 4,096 is a
    row/pointer bound, never a model-token ceiling.
    """

    shared = map_state_family_to_shared(family)
    if (
        not isinstance(max_rows, int)
        or isinstance(max_rows, bool)
        or max_rows <= 0
    ):
        raise StateLawsGraphragAdapterError("max_rows must be a positive integer")
    if max_rows > MAX_ROWS_PER_PHYSICAL_SHARD:
        raise StatePhysicalBoundError(
            f"max_rows={max_rows} exceeds physical bound "
            f"{MAX_ROWS_PER_PHYSICAL_SHARD}"
        )
    projected = [project_writer_row(row, shared) for row in rows]
    primary = family_primary_keys(shared)
    ties = family_tie_breakers(shared)
    if sort and projected:
        try:
            ordered = list(
                stable_sort_rows(projected, primary, tie_breakers=ties)
            )
        except Exception:
            ordered = sorted(
                projected,
                key=lambda row: tuple(str(row.get(key) or "") for key in (*primary, *ties)),
            )
    else:
        ordered = projected
    directory = family_relative_dir(shared, jurisdiction=jurisdiction)
    shards = shard_sequence(ordered, max_rows=max_rows)
    planned: list[PlannedShard] = []
    for shard_id, group in enumerate(shards):
        if not group:
            continue
        relative = "/".join(
            part
            for part in (directory, part_filename(shard_id))
            if part
        )
        relative = require_relative_artifact_path(relative)
        planned.append(
            PlannedShard(
                relative_path=relative,
                family=shared.value,
                row_count=len(group),
                first_key=_row_key(group[0], primary),
                last_key=_row_key(group[-1], primary),
                shard_id=shard_id,
                rows=tuple(dict(item) for item in group),
            )
        )
    return tuple(planned)


def write_state_family_shards(
    rows: Sequence[Mapping[str, Any] | Any],
    *,
    root: PathLike,
    family: Any,
    jurisdiction: str | None = None,
    config: ArtifactWriterConfig | None = None,
    index_path: str | None = None,
) -> Any:
    """Write one state-law family through the shared bounded artifact writer."""

    shared = map_state_family_to_shared(family)
    projected = [project_writer_row(row, shared) for row in rows]
    data_dir = family_relative_dir(shared, jurisdiction=jurisdiction)
    if not data_dir:
        raise StateLawsGraphragAdapterError(
            f"family {shared.value!r} is not a sharded data family"
        )
    return write_bounded_shards(
        projected,
        root=root,
        data_dir=data_dir,
        index_path=index_path,
        family=shared,
        primary_keys=family_primary_keys(shared),
        tie_breakers=family_tie_breakers(shared),
        config=config or default_writer_config(),
    )


# ---------------------------------------------------------------------------
# Streaming / external sort
# ---------------------------------------------------------------------------


def state_family_sort_key(family: Any):
    """Return a jurisdiction-aware sort key for the shared external sorter."""

    shared = map_state_family_to_shared(family)
    if shared is SharedArtifactFamily.CORPUS:
        def _corpus_key(record: Mapping[str, Any]) -> tuple[Any, ...]:
            return (
                str(record.get("jurisdiction") or record.get("jurisdiction_code") or ""),
                str(record.get("legal_id") or ""),
                str(record.get("entry_cid") or record.get("chunk_cid") or ""),
            )

        return _corpus_key
    if shared is SharedArtifactFamily.BM25_POSTINGS:
        return sort_key_for_family("postings")
    if shared is SharedArtifactFamily.VECTORS:
        return sort_key_for_family("vectors")
    if shared is SharedArtifactFamily.LOCATOR_INDEX:
        return sort_key_for_family("locators")
    if shared is SharedArtifactFamily.BM25_DOCUMENTS:
        return sort_key_for_family("documents")
    return sort_key_for_family("chunks")


def stream_state_family_partitions(
    records: Iterable[Mapping[str, Any]],
    *,
    family: Any,
    work_dir: PathLike,
    max_rows: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    max_records_in_memory: int = DEFAULT_MAX_RECORDS_IN_MEMORY,
    budget: MemoryBudget | None = None,
) -> Iterator[tuple[dict[str, Any], ...]]:
    """Externally sort *records* and yield ≤4,096-row partitions."""

    shared = map_state_family_to_shared(family)
    return stream_sorted_partitions(
        (project_writer_row(record, shared) for record in records),
        work_dir=work_dir,
        key_fn=state_family_sort_key(shared),
        family="corpus" if shared is SharedArtifactFamily.CORPUS else "documents",
        max_records_in_memory=max_records_in_memory,
        max_rows=max_rows,
        budget=budget,
    )


def external_sort_state_family(
    records: Iterable[Mapping[str, Any]],
    output_path: PathLike,
    *,
    work_dir: PathLike,
    family: Any,
    max_records_in_memory: int = DEFAULT_MAX_RECORDS_IN_MEMORY,
) -> Any:
    """Spill/merge-sort one state-law family under a memory bound."""

    shared = map_state_family_to_shared(family)
    projected = [project_writer_row(record, shared) for record in records]
    return external_sort_to_file(
        projected,
        output_path,
        work_dir=work_dir,
        key_fn=state_family_sort_key(shared),
        family="corpus" if shared is SharedArtifactFamily.CORPUS else "documents",
        max_records_in_memory=max_records_in_memory,
    )


def iter_physical_shards(
    records: Iterable[Mapping[str, Any]],
    *,
    max_rows: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    budget: MemoryBudget | None = None,
) -> Iterator[tuple[dict[str, Any], ...]]:
    """Stream already-ordered records as physical shards (no full materialize)."""

    return stream_bounded_partitions(records, max_rows=max_rows, budget=budget)


# ---------------------------------------------------------------------------
# Immutable resolver
# ---------------------------------------------------------------------------


def supported_state_release_schemas() -> frozenset[str]:
    """Release schemas the adapter admits on the shared resolver."""

    return SUPPORTED_RELEASE_SCHEMAS


def build_immutable_resolver(
    *,
    repo_id: str = DEFAULT_DATASET_REPO_ID,
    revision: str,
    local_root: PathLike | None = None,
    transport: Any = None,
    cache_dir: PathLike | None = None,
    require_descriptor: bool = True,
) -> ImmutableHubResolver:
    """Construct :class:`ImmutableHubResolver` for the state-law profile.

    Live Hub transport is **not** authorized here. Callers must supply
    ``local_root`` or an injected transport (typically
    :class:`MappingTransport`) plus an explicit ``cache_dir`` so the
    adapter never writes under ``~/.cache``.
    """

    try:
        pin = require_immutable_revision(revision, name="revision")
    except Exception as exc:
        raise AdapterPinError(str(exc)) from exc
    if len(pin) != 40 or any(ch not in "0123456789abcdef" for ch in pin.lower()):
        # Publication pins may be SHA-256; Hub resolver requires 40-hex.
        # Surface that as a pin error rather than letting the shared
        # resolver become the only gate.
        try:
            resolver_revision = pin
            if len(pin) != 40:
                raise AdapterPinError(
                    "immutable Hub resolver requires a 40-hex commit SHA"
                )
        except AdapterPinError:
            raise
    if transport is None and local_root is None:
        raise StateLawsGraphragAdapterError(
            "live Hub transport is not authorized; pass local_root or a "
            "test MappingTransport"
        )
    if cache_dir is None:
        raise StateLawsGraphragAdapterError(
            "cache_dir is required so the adapter never writes under a home path"
        )
    return ImmutableHubResolver(
        repo_id=repo_id,
        revision=pin if len(pin) == 40 else revision,
        local_root=local_root,
        transport=transport,
        cache_dir=cache_dir,
        supported_schemas=set(SUPPORTED_RELEASE_SCHEMAS),
        require_descriptor=require_descriptor,
    )


# ---------------------------------------------------------------------------
# Reject gates
# ---------------------------------------------------------------------------


def present_families_from(value: Any) -> frozenset[str]:
    """Collect family tokens from a manifest, descriptor list, or mapping."""

    names: set[str] = set()
    if value is None:
        return frozenset()
    if hasattr(value, "present_families"):
        return frozenset(item.value for item in value.present_families())
    if isinstance(value, Mapping):
        if "families" in value:
            return frozenset(
                map_state_family_to_shared(item).value
                for item in _as_sequence(value.get("families"), "families")
            )
        artifacts = value.get("artifacts") or value.get("descriptors") or ()
        for item in _as_sequence(artifacts, "artifacts"):
            payload = _as_mapping(item, "artifact")
            if payload.get("family"):
                names.add(map_state_family_to_shared(payload["family"]).value)
        return frozenset(names)
    for item in _as_sequence(value, "families"):
        if isinstance(item, (SharedArtifactFamily, StateArtifactFamily)):
            names.add(map_state_family_to_shared(item).value)
        elif isinstance(item, Mapping):
            family = item.get("family")
            if family:
                names.add(map_state_family_to_shared(family).value)
        else:
            names.add(map_state_family_to_shared(item).value)
    return frozenset(names)


def assert_semantic_families_present(value: Any) -> dict[str, Any]:
    """Reject a default release that omits any required semantic family."""

    present = present_families_from(value)
    try:
        return validate_semantic_family_closure(present)
    except SemanticFamilyClosureError as exc:
        raise AbsentSemanticFamilyError(str(exc)) from exc


def assert_centroid_placement_is_real(payload: Mapping[str, Any]) -> None:
    """Reject hash-mod, positional, or fake global ``centroid-000`` layouts."""

    assignment = payload.get("assignment") or payload.get("centroid_assignment")
    if assignment not in (None, ""):
        folded = _fold_token(assignment)
        if folded in FAKE_CENTROID_ASSIGNMENTS:
            raise FakeCentroidPlacementError(
                f"centroid assignment {assignment!r} is not "
                f"{REQUIRED_CENTROID_ASSIGNMENT}"
            )
        if folded != _fold_token(REQUIRED_CENTROID_ASSIGNMENT):
            raise FakeCentroidPlacementError(
                f"centroid assignment must be {REQUIRED_CENTROID_ASSIGNMENT}, "
                f"got {assignment!r}"
            )
    if payload.get("global_centroid") or payload.get("nominal_centroid"):
        raise FakeCentroidPlacementError(
            "global/nominal centroid-000 placement is rejected"
        )
    if payload.get("fake_centroid") is True:
        raise FakeCentroidPlacementError("fake centroid placement is rejected")

    descriptors = list(_as_sequence(payload.get("artifacts") or payload.get("descriptors"), "artifacts"))
    vector_paths: list[str] = []
    for item in descriptors:
        desc = _as_mapping(item, "descriptor")
        family = desc.get("family")
        if family and map_state_family_to_shared(family) is SharedArtifactFamily.VECTORS:
            path = require_relative_artifact_path(desc.get("relative_path") or "")
            vector_paths.append(path)
    extra_paths = payload.get("vector_paths") or ()
    for item in _as_sequence(extra_paths, "vector_paths"):
        vector_paths.append(require_relative_artifact_path(item))

    if vector_paths:
        non_centroid = [
            path
            for path in vector_paths
            if "centroid-" not in PurePosixPath(path).name
            and "centroid-" not in path
        ]
        if non_centroid:
            raise FakeCentroidPlacementError(
                "vector shard paths must be centroid-specific "
                f"(centroid-*-part-*), got {non_centroid[:3]!r}"
            )
        centroid_ids = {
            match.group(1)
            for path in vector_paths
            for match in [_CENTROID_PATH_RE.search(path)]
            if match
        }
        cluster_count = payload.get("cluster_count")
        row_count = int(payload.get("vector_row_count") or payload.get("row_count") or 0)
        if not row_count:
            for item in descriptors:
                desc = _as_mapping(item, "descriptor")
                if desc.get("family") and map_state_family_to_shared(
                    desc["family"]
                ) is SharedArtifactFamily.VECTORS:
                    row_count += int(desc.get("row_count") or 0)
        if centroid_ids == {"000"}:
            if cluster_count not in (None, 0, 1) and int(cluster_count) > 1:
                raise FakeCentroidPlacementError(
                    "all vector shards named centroid-000 while cluster_count>1"
                )
            if row_count > MAX_ROWS_PER_VECTOR_CENTROID:
                raise FakeCentroidPlacementError(
                    "fake global centroid-000 layout exceeds "
                    f"{MAX_ROWS_PER_VECTOR_CENTROID} rows"
                )

    centroids = _as_sequence(payload.get("centroids"), "centroids")
    for item in centroids:
        record = item if isinstance(item, Mapping) else _as_mapping(item, "centroid")
        rows, shards = validate_centroid_capacity(
            row_count=record.get("row_count", 0),
            shard_count=record.get("shard_count", 0),
        )
        if rows > 0 and shards == 0:
            raise FakeCentroidPlacementError(
                "centroid declares rows without physical shards"
            )
        if shards > MAX_VECTOR_SHARDS_PER_CENTROID:
            raise FakeCentroidPlacementError(
                f"centroid shard_count={shards} exceeds "
                f"{MAX_VECTOR_SHARDS_PER_CENTROID}"
            )


def assert_two_way_adjacency(
    *,
    edges: Sequence[Any] | None = None,
    out_pages: Sequence[Any] | None = None,
    in_pages: Sequence[Any] | None = None,
    families: Iterable[Any] | None = None,
) -> dict[str, Any]:
    """Reject missing or unreconciliation incoming/outgoing adjacency."""

    if families is not None:
        present = present_families_from(families)
        if SharedArtifactFamily.GRAPH_ADJACENCY_OUT.value not in present:
            raise MissingTwoWayAdjacencyError(
                "release missing graph_adjacency_out"
            )
        if SharedArtifactFamily.GRAPH_ADJACENCY_IN.value not in present:
            raise MissingTwoWayAdjacencyError(
                "release missing graph_adjacency_in"
            )

    out_seq = _as_sequence(out_pages, "out_pages")
    in_seq = _as_sequence(in_pages, "in_pages")
    edge_seq = _as_sequence(edges, "edges")
    if out_pages is None and in_pages is None and edges is None:
        return {"reconciled": True, "checked": "families-only"}
    if not out_seq:
        raise MissingTwoWayAdjacencyError("outgoing adjacency pages are missing")
    if not in_seq:
        raise MissingTwoWayAdjacencyError("incoming adjacency pages are missing")

    out_edges: set[str] = set()
    in_edges: set[str] = set()
    for page in out_seq:
        record = _coerce_adjacency_record(page)
        if record.direction != "out":
            raise MissingTwoWayAdjacencyError(
                f"outgoing page has direction {record.direction!r}"
            )
        out_edges.update(record.edge_cids)
    for page in in_seq:
        record = _coerce_adjacency_record(page)
        if record.direction != "in":
            raise MissingTwoWayAdjacencyError(
                f"incoming page has direction {record.direction!r}"
            )
        in_edges.update(record.edge_cids)

    expected: set[str]
    if edge_seq:
        expected = {
            _coerce_graph_edge_record(edge).edge_cid for edge in edge_seq
        }
    else:
        expected = out_edges | in_edges

    if out_edges != expected:
        raise MissingTwoWayAdjacencyError(
            f"outgoing adjacency does not cover every durable edge "
            f"(missing={sorted(expected - out_edges)[:5]!r} "
            f"extra={sorted(out_edges - expected)[:5]!r})"
        )
    if in_edges != expected:
        raise MissingTwoWayAdjacencyError(
            f"incoming adjacency does not cover every durable edge "
            f"(missing={sorted(expected - in_edges)[:5]!r} "
            f"extra={sorted(in_edges - expected)[:5]!r})"
        )
    if out_edges != in_edges:
        raise MissingTwoWayAdjacencyError(
            "incoming and outgoing adjacency edge coverage differs"
        )
    return {
        "edge_count": len(expected),
        "in_pages": len(in_seq),
        "out_pages": len(out_seq),
        "reconciled": True,
    }


def assert_no_unsafe_lineage_duplication(payload: Mapping[str, Any]) -> None:
    """Reject per-posting / per-adjacency copies of official source lineage."""

    lineage = _as_sequence(payload.get("source_lineage"), "source_lineage")
    lineage_cids = [
        _as_mapping(row, "source_lineage[]").get("source_cid") for row in lineage
    ]
    lineage_cids = [cid for cid in lineage_cids if cid]
    if len(lineage_cids) != len(set(lineage_cids)):
        raise UnsafeLineageDuplicationError("source_cid lineage is not unique")

    for family_name in (
        "postings",
        "bm25_postings",
        "adjacency",
        "adjacency_out",
        "adjacency_in",
        "locators",
    ):
        for row in _as_sequence(payload.get(family_name), family_name):
            project_writer_row(
                row,
                "bm25_postings"
                if family_name in {"postings", "bm25_postings"}
                else (
                    "locator_index"
                    if family_name == "locators"
                    else "graph_adjacency_out"
                ),
            )

    for chunk in _as_sequence(payload.get("chunks"), "chunks"):
        row = _as_mapping(chunk, "chunk")
        leaked = LINEAGE_FORBIDDEN_ON_INDEX_FAMILIES.intersection(row)
        if row.get("duplicate_lineage") is True or leaked == LINEAGE_FORBIDDEN_ON_INDEX_FAMILIES:
            raise UnsafeLineageDuplicationError(
                "chunk duplicates the full source-lineage payload"
            )


def assert_relative_paths(payload: Mapping[str, Any] | Sequence[Any]) -> None:
    """Reject absolute, home, or traversal artifact paths."""

    def _walk(value: Any, *, key: str | None = None) -> None:
        if isinstance(value, Mapping):
            for child_key, child in value.items():
                _walk(child, key=str(child_key))
            return
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for item in value:
                _walk(item, key=key)
            return
        if not isinstance(value, str):
            return
        key_l = (key or "").lower()
        if key_l in {
            "relative_path",
            "path",
            "artifact_path",
            "data_dir",
            "index_path",
        } or key_l.endswith("_path"):
            require_relative_artifact_path(value, name=key or "path")

    _walk(payload if not isinstance(payload, Sequence) else {"items": payload})


def assert_not_subset_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Reject a default Viewer/release config that is not the exact 51-set."""

    if not isinstance(config, Mapping):
        raise SubsetConfigError("config must be a mapping")
    name = str(config.get("name") or config.get("config_name") or "").strip()
    folded = _fold_token(name)
    is_default = bool(
        config.get("is_default")
        or config.get("default")
        or config.get("default_config")
        or folded in {DEFAULT_VIEWER_CONFIG, "default", "combined"}
    )
    jurisdictions = config.get("jurisdictions") or config.get("states") or ()
    split = str(config.get("split") or "").strip()

    if folded in SUBSET_CONFIG_MARKERS or _fold_token(split) in SUBSET_CONFIG_MARKERS:
        if is_default:
            raise SubsetConfigError(
                f"subset/sample/IA config {name or split!r} cannot be the default"
            )

    if is_default:
        if jurisdictions:
            try:
                validate_jurisdiction_set(jurisdictions, name="jurisdictions")
            except Exception as exc:
                raise SubsetConfigError(
                    "default config must cover the exact 51-jurisdiction set "
                    "(50 states + DC)"
                ) from exc
        elif folded and folded not in {DEFAULT_VIEWER_CONFIG, "default", "combined"}:
            raise SubsetConfigError(
                f"default config {name!r} is not {DEFAULT_VIEWER_CONFIG}"
            )
        families = config.get("families") or config.get("semantic_families")
        if families:
            assert_semantic_families_present({"families": families})
        if _fold_token(split) in {"ia", "sample"}:
            raise SubsetConfigError(
                "default Viewer split must not be the IA-only/sample subset"
            )
    elif jurisdictions:
        codes = {validate_jurisdiction(item) for item in jurisdictions}
        if codes != CANONICAL_JURISDICTIONS and is_default:
            raise SubsetConfigError("default config jurisdictions are a subset")

    return {
        "config_name": name or DEFAULT_VIEWER_CONFIG,
        "default": is_default,
        "exact_51": True if is_default else bool(
            jurisdictions and set(jurisdictions) >= CANONICAL_JURISDICTIONS
            if False
            else not is_default
        ),
        "rejected_as_subset": False,
    }


def assert_no_descriptor_drift(
    descriptor: StateArtifactDescriptor
    | SharedArtifactDescriptor
    | ResolverArtifactDescriptor
    | Mapping[str, Any],
    *,
    payload_bytes: bytes | None = None,
    size_bytes: int | None = None,
    sha256: str | None = None,
    row_count: int | None = None,
    other: Mapping[str, Any]
    | StateArtifactDescriptor
    | SharedArtifactDescriptor
    | None = None,
) -> None:
    """Reject SHA-256 / size / row-count disagreement."""

    if isinstance(descriptor, (StateArtifactDescriptor, SharedArtifactDescriptor)):
        declared = descriptor.to_dict()
    elif isinstance(descriptor, ResolverArtifactDescriptor):
        declared = descriptor.to_dict()
    else:
        declared = _as_mapping(descriptor, "descriptor")
    require_relative_artifact_path(declared.get("relative_path") or "")
    declared_sha = normalize_sha256(declared.get("sha256") or "", name="sha256")
    declared_size = int(declared.get("size_bytes") or 0)
    declared_rows = declared.get("row_count")

    if payload_bytes is not None:
        actual_sha = hashlib.sha256(payload_bytes).hexdigest()
        actual_size = len(payload_bytes)
        if actual_sha != declared_sha or actual_size != declared_size:
            raise DescriptorDriftError(
                f"descriptor drifted from observed bytes for "
                f"{declared.get('relative_path')!r}"
            )
    if size_bytes is not None and int(size_bytes) != declared_size:
        raise DescriptorDriftError(
            f"size_bytes drifted: declared={declared_size} observed={size_bytes}"
        )
    if sha256 is not None:
        observed = normalize_sha256(sha256, name="observed_sha256")
        if observed != declared_sha:
            raise DescriptorDriftError(
                f"sha256 drifted for {declared.get('relative_path')!r}"
            )
    if row_count is not None and declared_rows is not None:
        if int(row_count) != int(declared_rows):
            raise DescriptorDriftError(
                f"row_count drifted: declared={declared_rows} observed={row_count}"
            )
    if other is not None:
        if isinstance(other, (StateArtifactDescriptor, SharedArtifactDescriptor)):
            other_payload = other.to_dict()
        else:
            other_payload = _as_mapping(other, "other descriptor")
        if require_relative_artifact_path(
            other_payload.get("relative_path") or ""
        ) != declared.get("relative_path"):
            raise DescriptorDriftError("descriptor paths do not match")
        if normalize_sha256(other_payload.get("sha256") or "") != declared_sha:
            raise DescriptorDriftError("descriptor sha256 pair drifted")
        if int(other_payload.get("size_bytes") or 0) != declared_size:
            raise DescriptorDriftError("descriptor size pair drifted")


# ---------------------------------------------------------------------------
# Adapter façade
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AdapterReceipt:
    """Result of mapping a compact state-law payload onto the substrate."""

    families: tuple[str, ...]
    descriptors: tuple[dict[str, Any], ...]
    locators: Optional[dict[str, Any]] = None
    adjacency: Optional[dict[str, Any]] = None
    filters: Optional[dict[str, Any]] = None
    writer_plans: tuple[dict[str, Any], ...] = ()
    schema_version: str = SCHEMA_VERSION
    task_id: str = TASK_ID
    profile: str = RELEASE_PROFILE

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "descriptors": list(self.descriptors),
            "families": list(self.families),
            "goal_id": GOAL_ID,
            "profile": self.profile,
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "writer_plans": list(self.writer_plans),
        }
        if self.locators is not None:
            payload["locators"] = self.locators
        if self.adjacency is not None:
            payload["adjacency"] = self.adjacency
        if self.filters is not None:
            payload["filters"] = self.filters
        return payload


def adapt_state_release(payload: Mapping[str, Any]) -> AdapterReceipt:
    """Map and fail-closed-validate a compact state-law release payload.

    This is the software-contract surface used by hermetic tests. It does
    not write Parquet, contact the Hub, or authorize publication.
    """

    if not isinstance(payload, Mapping):
        raise StateLawsGraphragAdapterError("release payload must be a mapping")
    assert_relative_paths(payload)
    closure = assert_semantic_families_present(payload)
    assert_centroid_placement_is_real(payload)
    assert_no_unsafe_lineage_duplication(payload)

    adjacency_receipt = None
    if any(key in payload for key in ("edges", "out_pages", "in_pages", "adjacency_out", "adjacency_in")):
        adjacency_receipt = assert_two_way_adjacency(
            edges=payload.get("edges"),
            out_pages=payload.get("out_pages") or payload.get("adjacency_out"),
            in_pages=payload.get("in_pages") or payload.get("adjacency_in"),
            families=payload,
        )
    else:
        assert_two_way_adjacency(families=payload)

    configs = _as_sequence(payload.get("configs") or payload.get("viewer_configs"), "configs")
    for config in configs:
        assert_not_subset_config(_as_mapping(config, "config"))
    if payload.get("default_config") is not None:
        assert_not_subset_config(_as_mapping(payload["default_config"], "default_config"))

    descriptors = []
    for item in _as_sequence(payload.get("artifacts") or payload.get("descriptors"), "artifacts"):
        shared = to_shared_artifact_descriptor(item)
        assert_no_descriptor_drift(shared)
        descriptors.append(shared.to_dict())

    locators_payload = None
    corpus_locs = payload.get("corpus_locators")
    vector_locs = payload.get("vector_locators")
    if corpus_locs is not None and vector_locs is not None:
        dual = build_state_dual_locators(
            corpus_records=corpus_locs,
            vector_records=vector_locs,
        )
        locators_payload = dual.to_dict()

    plans: list[dict[str, Any]] = []
    family_rows = payload.get("family_rows") or {}
    if isinstance(family_rows, Mapping):
        for family_name, rows in family_rows.items():
            jurisdiction = None
            if map_state_family_to_shared(family_name).value in JURISDICTION_PARTITIONED_FAMILIES:
                jurisdiction = payload.get("jurisdiction") or "OR"
            planned = plan_bounded_shards(
                _as_sequence(rows, f"family_rows[{family_name}]"),
                family=family_name,
                jurisdiction=jurisdiction,
            )
            plans.extend(item.to_dict() for item in planned)

    filters = None
    if payload.get("filters"):
        filters = StateLawsFilters.from_mapping(payload["filters"]).to_dict()

    receipt = AdapterReceipt(
        families=tuple(sorted(closure["present"])),
        descriptors=tuple(descriptors),
        locators=locators_payload,
        adjacency=adjacency_receipt,
        filters=filters,
        writer_plans=tuple(plans),
    )
    assert_no_home_paths_or_tokens(receipt.to_dict())
    return receipt


@dataclass
class StateLawsGraphragAdapter:
    """Facade binding state-law contracts to the shared substrate."""

    dataset_repo_id: str = DEFAULT_DATASET_REPO_ID
    profile: str = RELEASE_PROFILE
    viewer_config: str = DEFAULT_VIEWER_CONFIG

    def writer_config(self) -> ArtifactWriterConfig:
        return default_writer_config()

    def map_family(self, family: Any) -> SharedArtifactFamily:
        return map_state_family_to_shared(family)

    def map_descriptor(
        self, descriptor: StateArtifactDescriptor | Mapping[str, Any]
    ) -> SharedArtifactDescriptor:
        return to_shared_artifact_descriptor(descriptor)

    def map_locator(
        self, record: LocatorRecord | Mapping[str, Any], *, shard_id: int = 0
    ) -> LocatorRow:
        return to_locator_row(record, shard_id=shard_id)

    def map_filters(self, filters: Mapping[str, Any] | None) -> StateLawsFilters:
        return StateLawsFilters.from_mapping(filters)

    def open_resolver(
        self,
        *,
        revision: str,
        local_root: PathLike | None = None,
        transport: Any = None,
        cache_dir: PathLike | None = None,
    ) -> ImmutableHubResolver:
        return build_immutable_resolver(
            repo_id=self.dataset_repo_id,
            revision=revision,
            local_root=local_root,
            transport=transport,
            cache_dir=cache_dir,
        )

    def adapt(self, payload: Mapping[str, Any]) -> AdapterReceipt:
        return adapt_state_release(payload)

    def compatibility_report(self) -> dict[str, Any]:
        return build_substrate_compatibility_report()


def open_adapter(
    *,
    dataset_repo_id: str = DEFAULT_DATASET_REPO_ID,
) -> StateLawsGraphragAdapter:
    """Construct the adapter façade (no I/O)."""

    return StateLawsGraphragAdapter(dataset_repo_id=dataset_repo_id)


# ---------------------------------------------------------------------------
# Compatibility report
# ---------------------------------------------------------------------------


def default_report_path(repo_root: PathLike | None = None) -> Path:
    if repo_root is None:
        return DEFAULT_REPORT_PATH
    return Path(repo_root) / REPORT_RELATIVE_PATH


def build_substrate_compatibility_report() -> dict[str, Any]:
    """Describe state-law ↔ shared-substrate mapping (no home paths)."""

    shared_defaults = sorted(DEFAULT_SUPPORTED_RELEASE_SCHEMAS)
    admitted = sorted(SUPPORTED_RELEASE_SCHEMAS)
    missing_from_shared_defaults = sorted(
        set(admitted) - set(shared_defaults)
    )
    payload = {
        "acceptance": {
            "adapter_rejects_absent_semantic_families": True,
            "adapter_rejects_absolute_paths": True,
            "adapter_rejects_descriptor_drift": True,
            "adapter_rejects_fake_centroid_placement": True,
            "adapter_rejects_missing_two_way_adjacency": True,
            "adapter_rejects_subset_configs": True,
            "adapter_rejects_unsafe_lineage_duplication": True,
            "authorizes_hub_upload": AUTHORIZES_HUB_UPLOAD,
            "authorizes_network": AUTHORIZES_NETWORK,
            "authorizes_publication": AUTHORIZES_PUBLICATION,
            "default_config_is_exact_51": True,
            "includes_dc": True,
            "no_absolute_home_paths": True,
            "no_hub_upload": True,
            "no_token_material": True,
            "physical_row_bound": MAX_ROWS_PER_PHYSICAL_SHARD,
            "required_centroid_assignment": REQUIRED_CENTROID_ASSIGNMENT,
        },
        "adr_path": ADR_PATH,
        "board_namespace": BOARD_NAMESPACE,
        "bundle": BUNDLE,
        "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
        "default_viewer_config": DEFAULT_VIEWER_CONFIG,
        "filter_fields": list(FILTER_FIELDS),
        "goal_id": GOAL_ID,
        "graph_ontology_version": GRAPH_ONTOLOGY_VERSION,
        "jurisdiction_count": EXPECTED_JURISDICTION_COUNT,
        "jurisdiction_order": list(CANONICAL_JURISDICTION_ORDER),
        "known_shared_substrate_gaps": [
            {
                "adapter_mitigation": (
                    "ImmutableHubResolver is constructed with explicit "
                    "supported_schemas that include state-laws-ir-graphrag/v2"
                ),
                "generated_defect": False,
                "gap": (
                    "DEFAULT_SUPPORTED_RELEASE_SCHEMAS omits "
                    "state-laws-ir-graphrag/v2"
                ),
                "module": "ipfs_datasets_py/retrieval/hf_graphrag/resolver.py",
            }
        ],
        "layout": dict(FAMILY_RELATIVE_DIRS),
        "mappings": {
            "bounded_writers": "ipfs_datasets_py/retrieval/hf_graphrag/artifacts.py",
            "external_sort": "ipfs_datasets_py/retrieval/hf_graphrag/external_sort.py",
            "graph": "ipfs_datasets_py/retrieval/hf_graphrag/graph.py",
            "immutable_resolver": "ipfs_datasets_py/retrieval/hf_graphrag/resolver.py",
            "locators": "ipfs_datasets_py/retrieval/hf_graphrag/locators.py",
            "manifest_descriptors": "ipfs_datasets_py/retrieval/hf_graphrag/schema.py",
            "state_families_to_shared": {
                family.value: map_state_family_to_shared(family).value
                for family in StateArtifactFamily
            },
            "vectors": "ipfs_datasets_py/retrieval/hf_graphrag/vectors.py",
        },
        "model_id": DEFAULT_EMBEDDING_MODEL_ID,
        "model_revision": DEFAULT_EMBEDDING_MODEL_REVISION,
        "physical_bounds": shared_physical_bounds_policy(),
        "previous_public_pin": PREVIOUS_PUBLIC_PIN,
        "primary_key": PRIMARY_KEY,
        "producer": PRODUCER,
        "profile": RELEASE_PROFILE,
        "program_id": PROGRAM_ID,
        "provenance_fields": list(PROVENANCE_FIELDS),
        "rejections": {
            "absent_semantic_families": True,
            "absolute_paths": True,
            "descriptor_drift": True,
            "fake_centroid_placement": True,
            "missing_two_way_adjacency": True,
            "subset_configs": True,
            "unsafe_lineage_duplication": True,
        },
        "required_semantic_families": list(required_semantic_families()),
        "schema_version": SCHEMA_VERSION,
        "shared_substrate_modules": list(SHARED_SUBSTRATE_MODULES),
        "supported_release_schemas": admitted,
        "task_id": TASK_ID,
    }
    payload["content_id"] = "sha256:" + digest_mapping(payload)
    assert_no_home_paths_or_tokens(payload)
    return payload


def write_substrate_compatibility_report(
    path: PathLike | None = None,
    *,
    repo_root: PathLike | None = None,
) -> Path:
    """Write the hermetic compatibility report. Never contacts the Hub."""

    target = Path(path) if path is not None else default_report_path(repo_root)
    report = build_substrate_compatibility_report()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return target


def load_substrate_compatibility_report(
    path: PathLike | None = None,
) -> dict[str, Any]:
    target = Path(path) if path is not None else default_report_path()
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise StateLawsGraphragAdapterError("compatibility report must be a mapping")
    assert_no_home_paths_or_tokens(payload)
    return dict(payload)


def example_closed_adapter_payload() -> dict[str, Any]:
    """Compact closed payload used by hermetic adapter tests."""

    manifest = example_manifest_payload(include_all_jurisdictions=True)
    digest = content_sha256("adapter-or-entry")
    other = content_sha256("adapter-or-entry-b")
    edge = content_sha256("adapter-edge-contains")
    node_a = content_sha256("adapter-node-or")
    node_b = content_sha256("adapter-node-title")
    return {
        "artifacts": manifest["artifacts"],
        "assignment": REQUIRED_CENTROID_ASSIGNMENT,
        "cluster_count": 1,
        "default_config": {
            "config_name": DEFAULT_VIEWER_CONFIG,
            "families": list(required_semantic_families()),
            "is_default": True,
            "jurisdictions": sorted(CANONICAL_JURISDICTIONS),
            "name": DEFAULT_VIEWER_CONFIG,
        },
        "edges": [
            {
                "edge_cid": edge,
                "edge_type": "CONTAINS",
                "source_node_cid": node_a,
                "target_node_cid": node_b,
            }
        ],
        "filters": {"jurisdiction": "OR", "code_family": "ors"},
        "out_pages": [
            {
                "direction": "out",
                "edge_cids": [edge],
                "node_cid": node_a,
                "page_index": 0,
            }
        ],
        "in_pages": [
            {
                "direction": "in",
                "edge_cids": [edge],
                "node_cid": node_b,
                "page_index": 0,
            }
        ],
        "vector_row_count": 2,
        "family_rows": {
            "corpus": [
                {
                    "entry_cid": digest,
                    "jurisdiction": "OR",
                    "legal_id": "state:or:ors:123:456",
                    "source_cid": content_sha256("src-or"),
                },
                {
                    "entry_cid": other,
                    "jurisdiction": "OR",
                    "legal_id": "state:or:ors:123:457",
                    "source_cid": content_sha256("src-or-b"),
                },
            ]
        },
        "jurisdiction": "OR",
    }


__all__ = [
    "AUTHORIZES_HUB_UPLOAD",
    "AUTHORIZES_NETWORK",
    "AUTHORIZES_PUBLICATION",
    "DEFAULT_VIEWER_CONFIG",
    "FAMILY_RELATIVE_DIRS",
    "FILTER_FIELDS",
    "GOAL_ID",
    "PRODUCER",
    "REPORT_RELATIVE_PATH",
    "REQUIRED_CENTROID_ASSIGNMENT",
    "SCHEMA_VERSION",
    "SUPPORTED_RELEASE_SCHEMAS",
    "TASK_ID",
    "AbsentSemanticFamilyError",
    "AbsolutePathError",
    "AdapterPinError",
    "AdapterReceipt",
    "DescriptorDriftError",
    "FakeCentroidPlacementError",
    "MissingTwoWayAdjacencyError",
    "PlannedShard",
    "StateLawsFilters",
    "StateLawsGraphragAdapter",
    "StateLawsGraphragAdapterError",
    "SubsetConfigError",
    "UnsafeLineageDuplicationError",
    "adapt_state_release",
    "assert_centroid_placement_is_real",
    "assert_no_descriptor_drift",
    "assert_no_home_paths_or_tokens",
    "assert_no_unsafe_lineage_duplication",
    "assert_not_subset_config",
    "assert_relative_paths",
    "assert_semantic_families_present",
    "assert_two_way_adjacency",
    "build_immutable_resolver",
    "build_state_corpus_locator",
    "build_state_dual_locators",
    "build_state_vector_locator",
    "build_substrate_compatibility_report",
    "default_writer_config",
    "example_closed_adapter_payload",
    "external_sort_state_family",
    "family_relative_dir",
    "iter_physical_shards",
    "load_substrate_compatibility_report",
    "map_state_family_to_shared",
    "open_adapter",
    "plan_bounded_shards",
    "project_corpus_provenance",
    "project_writer_row",
    "require_relative_artifact_path",
    "state_family_sort_key",
    "stream_state_family_partitions",
    "supported_state_release_schemas",
    "to_locator_row",
    "to_resolver_descriptor",
    "to_shared_artifact_descriptor",
    "to_shared_graph_edge",
    "to_shared_graph_node",
    "to_state_artifact_descriptor",
    "write_state_family_shards",
    "write_substrate_compatibility_report",
]
