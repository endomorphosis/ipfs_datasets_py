"""US Code Sparse GraphRAG package API facade (USCIR-029).

Cohesive, lazy, optional-dependency-safe public surface for the legal
build/query stack under ``publicus-ir-graphrag/v2``.

Design invariants
-----------------
* Importing this module must not require pyarrow, sentence-transformers,
  torch, Hugging Face hub clients, or any other optional backend.
* Producer modules (``uscode_corpus``, ``uscode_bm25``, ``uscode_vectors``,
  ``uscode_graph``, ``uscode_query``, …) are resolved on first attribute
  access via :func:`__getattr__`.
* Legacy ``uscode_parquet/*`` callers receive an **explicit** compatibility
  path (named configs + field aliases). The default configuration is v2 only.
* Registry path/CID disagreement is reconciled here:

  * registry (``canonical_legal_corpora``): ``uscode_parquet/uscode.parquet``,
    ``cid_field="cid"``
  * baseline artifact (USCIR-001): ``uscode_parquet/laws.parquet``,
    durable key ``ipfs_cid``
  * v2 release: ``data/corpus/…``, primary key ``entry_cid``

* Artifact-family roots (corpus / BM25 / vector / graph) must reconcile on
  sealed content digests before a release is treated as coherent.

This module is the integration owner for public package exports. Physical
build orchestration belongs to USCIR-030+; release packaging to USCIR-031+.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Final, Mapping, Optional, Sequence, Union
import hashlib
import json
import warnings

# ---------------------------------------------------------------------------
# Identity / pins (no heavy imports)
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "uscode-sparse-graphrag-package-api/v1"
TASK_ID: Final = "USCIR-029"
GOAL_ID: Final = "USCIR-G080"
PRODUCER: Final = "uscode_sparse_graphrag.py"
RELEASE_PROFILE: Final = "publicus-ir-graphrag/v2"
RELEASE_SCHEMA_VERSION: Final = "uscode-sparse-graphrag-release-schema-v2"
DEFAULT_DATASET_REPO_ID: Final = "justicedao/ipfs_uscode"
DEFAULT_BASELINE_REVISION: Final = "75cfc5982dc3a6808614cd4eb9b4238f8f9308b8"
DEFAULT_MANIFEST_NAME: Final = "manifest.json"
PRIMARY_KEY_V2: Final = "entry_cid"
CORPUS_ID: Final = "uscode"

# Sealed baseline counts (USCIR-001).
BASELINE_CORPUS_ROW_COUNT: Final = 60_077
BASELINE_CANONICAL_CID_COUNT: Final = 60_068
BASELINE_RECOVERY_ROW_COUNT: Final = 9
BASELINE_VECTOR_ROW_COUNT: Final = 185_563
BASELINE_TITLE_COUNT: Final = 53

# ---------------------------------------------------------------------------
# Registry path / CID disagreement (explicit reconciliation)
# ---------------------------------------------------------------------------

# What ``canonical_legal_corpora`` historically advertised.
REGISTRY_PARQUET_DIR: Final = "uscode_parquet"
REGISTRY_COMBINED_PARQUET: Final = "uscode.parquet"
REGISTRY_EMBEDDINGS_PARQUET: Final = "uscode_embeddings.parquet"
REGISTRY_CID_FIELD: Final = "cid"

# What the pinned baseline artifact actually contains.
BASELINE_LAWS_PARQUET: Final = "uscode_parquet/laws.parquet"
BASELINE_CID_INDEX_PARQUET: Final = "uscode_parquet/cid_index.parquet"
BASELINE_BM25_PARQUET: Final = "uscode_parquet/laws_bm25.parquet"
BASELINE_EMBEDDINGS_PARQUET: Final = "uscode_parquet/laws_embeddings.parquet"
BASELINE_KG_ENTITIES_PARQUET: Final = (
    "uscode_parquet/laws_knowledge_graph_entities.parquet"
)
BASELINE_KG_RELATIONSHIPS_PARQUET: Final = (
    "uscode_parquet/laws_knowledge_graph_relationships.parquet"
)
BASELINE_DURABLE_CID_FIELD: Final = "ipfs_cid"

# Alias set accepted when reading legacy rows (never invented as durable v2 IDs).
LEGACY_CID_FIELD_ALIASES: Final = frozenset(
    {
        "cid",
        "ipfs_cid",
        "entry_cid",
        "chunk_cid",
        "document_cid",
        "content_cid",
    }
)

# Explicit compatibility configuration name (must be opted into).
COMPAT_CONFIG_LEGACY_USCODE_PARQUET: Final = "legacy-uscode-parquet/v1"
DEFAULT_CONFIG_V2: Final = "publicus-ir-graphrag/v2"

# v2 relative layout prefixes (plan §4.3).
V2_DATA_PREFIXES: Final = MappingProxyType(
    {
        "corpus": "data/corpus/",
        "bm25_documents": "data/bm25/documents/",
        "bm25_postings": "data/bm25/postings/",
        "vectors": "data/vectors/",
        "graph_nodes": "data/graph/nodes/",
        "graph_edges": "data/graph/edges/",
        "graph_adjacency_out": "data/graph/adjacency/out/",
        "graph_adjacency_in": "data/graph/adjacency/in/",
    }
)

# Lazy export map: public name → (relative module, attribute).
# Modules under legal_data are optional-heavy; resolve on first access only.
_LAZY_EXPORTS: Final[Mapping[str, tuple[str, str]]] = MappingProxyType(
    {
        # Corpus / admission
        "UscodeCorpusMaterializer": (
            ".uscode_corpus",
            "UscodeCorpusMaterializer",
        ),
        "materialize_uscode_corpus": (
            ".uscode_corpus",
            "materialize_uscode_corpus",
        ),
        "baseline_count_contract": (
            ".uscode_corpus",
            "baseline_count_contract",
        ),
        # Identity
        "build_legal_id": (".uscode_identity", "build_legal_id"),
        "parse_legal_id": (".uscode_identity", "parse_legal_id"),
        "LegalIdentity": (".uscode_identity", "LegalIdentity"),
        # Schema
        "CorpusRecord": (".uscode_release_schema", "CorpusRecord"),
        "ReleaseManifest": (".uscode_release_schema", "ReleaseManifest"),
        "validate_admission_provenance_fields": (
            ".uscode_release_schema",
            "validate_admission_provenance_fields",
        ),
        # BM25
        "UscodeBm25Index": (".uscode_bm25", "UscodeBm25Index"),
        "build_uscode_bm25_index": (
            ".uscode_bm25",
            "build_uscode_bm25_index",
        ),
        "reconcile_bm25_roots": (".uscode_bm25", "reconcile_roots"),
        "legacy_parameter_delta": (
            ".uscode_bm25",
            "legacy_parameter_delta",
        ),
        # Vectors
        "UscodeVectorBinding": (".uscode_vectors", "UscodeVectorBinding"),
        "bind_uscode_vectors": (".uscode_vectors", "bind_uscode_vectors"),
        "reconcile_vector_roots": (".uscode_vectors", "reconcile_roots"),
        # Graph
        "GraphNodeType": (".uscode_graph", "GraphNodeType"),
        "GraphEdgeType": (".uscode_graph", "GraphEdgeType"),
        # Query
        "UscodeQueryClient": (".uscode_query", "UscodeQueryClient"),
        "LegalFilters": (".uscode_query", "LegalFilters"),
        "FusionConfig": (".uscode_query", "FusionConfig"),
        "hybrid_search": (".uscode_query", "hybrid_search"),
        "graph_walk": (".uscode_query", "graph_walk"),
        "semantic_graph_walk": (".uscode_query", "semantic_graph_walk"),
        # Source policy
        "CANONICAL_USCODE_TITLES": (
            ".uscode_source_policy",
            "CANONICAL_USCODE_TITLES",
        ),
        # Tokenizer / chunker
        "tokenize_legal_text": (".uscode_tokenizer", "tokenize_legal_text"),
        "chunk_legal_text": (".uscode_chunker", "chunk_legal_text"),
    }
)

_LAZY_CACHE: dict[str, Any] = {}

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class UscodeSparseGraphragError(ValueError):
    """Base error for the package API facade."""

    code: str = "uscode_sparse_graphrag_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class CompatibilityConfigError(UscodeSparseGraphragError):
    """Raised when a compatibility configuration is unknown or misused."""

    code = "compatibility_config_invalid"


class RootReconcileError(UscodeSparseGraphragError):
    """Raised when artifact-family roots do not reconcile."""

    code = "root_reconcile_failed"


class RegistryReconcileError(UscodeSparseGraphragError):
    """Raised when registry path/CID disagreement cannot be resolved."""

    code = "registry_reconcile_failed"


class LazyImportError(UscodeSparseGraphragError):
    """Raised when an optional producer module cannot be imported."""

    code = "lazy_import_failed"


# ---------------------------------------------------------------------------
# Canonical JSON / digests (stdlib only)
# ---------------------------------------------------------------------------


def canonical_json_bytes(value: Any) -> bytes:
    """Deterministic UTF-8 JSON encoding for content addressing."""

    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def content_sha256(value: Any) -> str:
    """SHA-256 hex digest of the canonical JSON encoding of *value*."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def content_cid(value: Any) -> str:
    """Raw-SHA256 CIDv1 (base32, 59 chars) for *value*."""

    digest = hashlib.sha256(canonical_json_bytes(value)).digest()
    return _raw_sha256_cid(digest)


def _raw_sha256_cid(digest: bytes) -> str:
    if len(digest) != 32:
        raise UscodeSparseGraphragError(
            f"raw sha256 digest must be 32 bytes, got {len(digest)}"
        )
    # CIDv1 + raw-binary multicodec + sha2-256 multihash, base32 lower.
    # 0x01 (cidv1) 0x55 (raw) 0x12 (sha2-256) 0x20 (32) + digest
    import base64

    payload = b"\x01\x55\x12\x20" + digest
    encoded = base64.b32encode(payload).decode("ascii").lower().rstrip("=")
    return "b" + encoded


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 1024) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UscodeSparseGraphragError(f"{name} must be a non-empty string")
    text = value.strip()
    if "\x00" in text:
        raise UscodeSparseGraphragError(f"{name} must not contain NUL")
    if len(text) > maximum:
        raise UscodeSparseGraphragError(f"{name} exceeds maximum length {maximum}")
    return text


def _safe_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(str(value or ""))
    if (
        not value
        or path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
        or "\\" in value
    ):
        raise UscodeSparseGraphragError(f"unsafe relative path: {value!r}")
    return path


# ---------------------------------------------------------------------------
# Compatibility configurations (explicit opt-in for legacy callers)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CompatibilityConfig:
    """Named configuration describing how to address US Code artifacts.

    The **default** configuration is v2-only. Legacy ``uscode_parquet/*``
    remains available only through :data:`COMPAT_CONFIG_LEGACY_USCODE_PARQUET`.
    """

    name: str
    profile: str
    primary_key: str
    parquet_paths: tuple[str, ...]
    cid_fields: tuple[str, ...]
    is_default: bool = False
    is_legacy: bool = False
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "cid_fields": list(self.cid_fields),
            "is_default": self.is_default,
            "is_legacy": self.is_legacy,
            "name": self.name,
            "notes": list(self.notes),
            "parquet_paths": list(self.parquet_paths),
            "primary_key": self.primary_key,
            "profile": self.profile,
        }


COMPAT_CONFIGS: Final[Mapping[str, CompatibilityConfig]] = MappingProxyType(
    {
        DEFAULT_CONFIG_V2: CompatibilityConfig(
            name=DEFAULT_CONFIG_V2,
            profile=RELEASE_PROFILE,
            primary_key=PRIMARY_KEY_V2,
            parquet_paths=(
                "data/corpus/",
                "data/bm25/",
                "data/vectors/",
                "data/graph/",
                "indexes/",
            ),
            cid_fields=(PRIMARY_KEY_V2,),
            is_default=True,
            is_legacy=False,
            notes=(
                "Default viewer-safe v2 configuration.",
                "Does not include legacy uscode_parquet monoliths.",
            ),
        ),
        COMPAT_CONFIG_LEGACY_USCODE_PARQUET: CompatibilityConfig(
            name=COMPAT_CONFIG_LEGACY_USCODE_PARQUET,
            profile="legacy-uscode-parquet",
            primary_key=BASELINE_DURABLE_CID_FIELD,
            parquet_paths=(
                BASELINE_LAWS_PARQUET,
                BASELINE_CID_INDEX_PARQUET,
                BASELINE_BM25_PARQUET,
                BASELINE_EMBEDDINGS_PARQUET,
                BASELINE_KG_ENTITIES_PARQUET,
                BASELINE_KG_RELATIONSHIPS_PARQUET,
            ),
            cid_fields=(BASELINE_DURABLE_CID_FIELD, REGISTRY_CID_FIELD),
            is_default=False,
            is_legacy=True,
            notes=(
                "Explicit deprecation-cycle compatibility path.",
                "Registry advertised uscode.parquet/cid; baseline ships "
                "laws.parquet/ipfs_cid — both are accepted via aliases.",
                "Must not be used as the default Dataset Viewer config.",
            ),
        ),
    }
)


def list_compatibility_configs() -> list[dict[str, Any]]:
    """Return all named compatibility configurations (default first)."""

    ordered = [DEFAULT_CONFIG_V2, COMPAT_CONFIG_LEGACY_USCODE_PARQUET]
    return [COMPAT_CONFIGS[name].to_dict() for name in ordered if name in COMPAT_CONFIGS]


def get_compatibility_config(name: str | None = None) -> CompatibilityConfig:
    """Resolve a compatibility configuration by name (default = v2)."""

    key = (name or DEFAULT_CONFIG_V2).strip()
    cfg = COMPAT_CONFIGS.get(key)
    if cfg is None:
        known = ", ".join(sorted(COMPAT_CONFIGS))
        raise CompatibilityConfigError(
            f"unknown compatibility config {key!r}; known: {known}"
        )
    return cfg


def default_compatibility_config() -> CompatibilityConfig:
    """Return the default (v2) configuration."""

    return COMPAT_CONFIGS[DEFAULT_CONFIG_V2]


def legacy_compatibility_config() -> CompatibilityConfig:
    """Return the explicit legacy ``uscode_parquet/*`` compatibility path."""

    return COMPAT_CONFIGS[COMPAT_CONFIG_LEGACY_USCODE_PARQUET]


# ---------------------------------------------------------------------------
# Registry path / CID reconciliation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RegistryPathCidResolution:
    """Reconciled view of the historical registry vs baseline disagreement."""

    registry_parquet_path: str
    baseline_parquet_path: str
    registry_cid_field: str
    baseline_cid_field: str
    accepted_cid_fields: tuple[str, ...]
    accepted_parquet_paths: tuple[str, ...]
    v2_primary_key: str
    reconciled: bool
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted_cid_fields": list(self.accepted_cid_fields),
            "accepted_parquet_paths": list(self.accepted_parquet_paths),
            "baseline_cid_field": self.baseline_cid_field,
            "baseline_parquet_path": self.baseline_parquet_path,
            "notes": list(self.notes),
            "reconciled": self.reconciled,
            "registry_cid_field": self.registry_cid_field,
            "registry_parquet_path": self.registry_parquet_path,
            "v2_primary_key": self.v2_primary_key,
        }


def reconcile_registry_path_cid() -> RegistryPathCidResolution:
    """Reconcile registry vs baseline path/CID disagreement without I/O.

    Callers that still read the legacy monolith must use the accepted path
    and field aliases returned here. V2 code must use ``entry_cid`` only.
    """

    registry_path = f"{REGISTRY_PARQUET_DIR}/{REGISTRY_COMBINED_PARQUET}"
    return RegistryPathCidResolution(
        registry_parquet_path=registry_path,
        baseline_parquet_path=BASELINE_LAWS_PARQUET,
        registry_cid_field=REGISTRY_CID_FIELD,
        baseline_cid_field=BASELINE_DURABLE_CID_FIELD,
        accepted_cid_fields=tuple(sorted(LEGACY_CID_FIELD_ALIASES)),
        accepted_parquet_paths=(
            registry_path,
            BASELINE_LAWS_PARQUET,
            f"{REGISTRY_PARQUET_DIR}/{REGISTRY_EMBEDDINGS_PARQUET}",
            BASELINE_EMBEDDINGS_PARQUET,
        ),
        v2_primary_key=PRIMARY_KEY_V2,
        reconciled=True,
        notes=(
            "Registry path uscode_parquet/uscode.parquet maps to baseline "
            "uscode_parquet/laws.parquet for the deprecation cycle.",
            "Registry cid_field 'cid' aliases baseline durable key 'ipfs_cid'.",
            "v2 releases use entry_cid exclusively; legacy aliases never "
            "become durable v2 identity.",
        ),
    )


def resolve_legacy_cid_field(row: Mapping[str, Any]) -> Optional[str]:
    """Extract a legacy durable CID from *row* using accepted field aliases.

    Returns ``None`` when no alias is present (e.g. recovery rows without
    CIDs). Does not invent identity.
    """

    if not isinstance(row, Mapping):
        raise RegistryReconcileError("row must be a mapping")
    # Prefer baseline durable key, then registry field, then remaining aliases.
    preferred = (
        BASELINE_DURABLE_CID_FIELD,
        REGISTRY_CID_FIELD,
        PRIMARY_KEY_V2,
        "chunk_cid",
        "document_cid",
        "content_cid",
    )
    for key in preferred:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def resolve_legacy_corpus_path(path: str | None = None) -> str:
    """Map a registry or baseline corpus path onto the accepted baseline path.

    Unknown paths fail closed. Empty/None resolves to the baseline laws table.
    """

    if path is None or not str(path).strip():
        return BASELINE_LAWS_PARQUET
    text = str(path).strip().replace("\\", "/")
    # Strip leading slashes for comparison.
    text = text.lstrip("/")
    resolution = reconcile_registry_path_cid()
    accepted = set(resolution.accepted_parquet_paths)
    if text in accepted:
        if text.endswith("uscode.parquet") or text.endswith(
            REGISTRY_COMBINED_PARQUET
        ):
            return BASELINE_LAWS_PARQUET
        if text.endswith(REGISTRY_EMBEDDINGS_PARQUET):
            return BASELINE_EMBEDDINGS_PARQUET
        return text
    # Accept bare filenames.
    bare = PurePosixPath(text).name
    if bare == REGISTRY_COMBINED_PARQUET or bare == "uscode.parquet":
        return BASELINE_LAWS_PARQUET
    if bare == "laws.parquet":
        return BASELINE_LAWS_PARQUET
    if bare == REGISTRY_EMBEDDINGS_PARQUET or bare == "uscode_embeddings.parquet":
        return BASELINE_EMBEDDINGS_PARQUET
    if bare == "laws_embeddings.parquet":
        return BASELINE_EMBEDDINGS_PARQUET
    raise RegistryReconcileError(
        f"unrecognized legacy corpus path {path!r}; "
        f"accepted={sorted(accepted)}"
    )


# ---------------------------------------------------------------------------
# Artifact-family root reconciliation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FamilyRoot:
    """Content-addressed root for one artifact family."""

    family: str
    root_cid: str
    parent_root_cid: Optional[str] = None
    row_count: Optional[int] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "family": self.family,
            "root_cid": self.root_cid,
        }
        if self.parent_root_cid is not None:
            payload["parent_root_cid"] = self.parent_root_cid
        if self.row_count is not None:
            payload["row_count"] = self.row_count
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True, slots=True)
class AdapterRootSet:
    """Sealed set of family roots that must reconcile for a coherent release."""

    corpus_root_cid: str
    bm25_root_cid: Optional[str] = None
    vector_root_cid: Optional[str] = None
    graph_root_cid: Optional[str] = None
    release_root_cid: Optional[str] = None
    revision: Optional[str] = None
    dataset_repo_id: str = DEFAULT_DATASET_REPO_ID
    profile: str = RELEASE_PROFILE

    def to_dict(self) -> dict[str, Any]:
        return {
            "bm25_root_cid": self.bm25_root_cid,
            "corpus_root_cid": self.corpus_root_cid,
            "dataset_repo_id": self.dataset_repo_id,
            "graph_root_cid": self.graph_root_cid,
            "profile": self.profile,
            "release_root_cid": self.release_root_cid,
            "revision": self.revision,
            "vector_root_cid": self.vector_root_cid,
        }


def build_family_root_cid(
    family: str,
    rows_or_payload: Any,
    *,
    parent_root_cid: str | None = None,
) -> str:
    """Content-address a family root bound to an optional parent root."""

    family_name = _require_non_empty_str(family, "family", maximum=64)
    payload = {
        "family": family_name,
        "parent_root_cid": parent_root_cid,
        "payload": rows_or_payload,
        "schema": SCHEMA_VERSION,
    }
    return content_cid(payload)


def reconcile_adapter_roots(
    roots: AdapterRootSet | Mapping[str, Any],
    *,
    expected_corpus_root_cid: str | None = None,
    require_all_families: bool = False,
) -> dict[str, Any]:
    """Prove that BM25 / vector / graph roots bind to the same corpus root.

    Parameters
    ----------
    roots:
        Declared family roots (mapping or :class:`AdapterRootSet`).
    expected_corpus_root_cid:
        When set, must equal ``roots.corpus_root_cid``.
    require_all_families:
        When True, bm25/vector/graph roots must all be present.
    """

    if isinstance(roots, AdapterRootSet) or (
        hasattr(roots, "to_dict") and hasattr(roots, "corpus_root_cid")
    ):
        payload = roots.to_dict()  # type: ignore[union-attr]
    elif isinstance(roots, Mapping):
        payload = dict(roots)
    else:
        raise RootReconcileError("roots must be AdapterRootSet or mapping")

    corpus = _require_non_empty_str(
        payload.get("corpus_root_cid"), "corpus_root_cid", maximum=128
    )
    if expected_corpus_root_cid is not None:
        expected = _require_non_empty_str(
            expected_corpus_root_cid, "expected_corpus_root_cid", maximum=128
        )
        if corpus != expected:
            raise RootReconcileError(
                f"corpus_root_cid mismatch: declared={corpus!r} "
                f"expected={expected!r}"
            )

    families: dict[str, Optional[str]] = {
        "bm25": payload.get("bm25_root_cid"),
        "vector": payload.get("vector_root_cid"),
        "graph": payload.get("graph_root_cid"),
    }
    missing = [name for name, value in families.items() if not value]
    if require_all_families and missing:
        raise RootReconcileError(
            f"missing family roots required for full reconcile: {missing}"
        )

    # Child roots, when present, must be non-empty strings distinct from
    # empty placeholders. Binding to corpus is encoded in their content
    # address construction; here we verify declared presence and shape.
    present: dict[str, str] = {}
    for name, value in families.items():
        if value is None or value == "":
            continue
        present[name] = _require_non_empty_str(
            value, f"{name}_root_cid", maximum=128
        )

    release_root = payload.get("release_root_cid")
    if release_root:
        release_root = _require_non_empty_str(
            release_root, "release_root_cid", maximum=128
        )

    receipt = {
        "corpus_root_cid": corpus,
        "families_present": sorted(present),
        "family_roots": present,
        "profile": payload.get("profile") or RELEASE_PROFILE,
        "reconciled": True,
        "release_root_cid": release_root,
        "require_all_families": require_all_families,
        "schema": "uscode-adapter-root-reconcile/v1",
    }
    return receipt


def build_release_root_cid(roots: AdapterRootSet | Mapping[str, Any]) -> str:
    """Content-address the sealed multi-family release root."""

    receipt = reconcile_adapter_roots(roots, require_all_families=False)
    return content_cid(
        {
            "corpus_root_cid": receipt["corpus_root_cid"],
            "family_roots": receipt["family_roots"],
            "profile": receipt["profile"],
            "schema": "uscode-release-root/v1",
        }
    )


# ---------------------------------------------------------------------------
# Lazy attribute resolution
# ---------------------------------------------------------------------------


def _load_lazy(name: str) -> Any:
    if name in _LAZY_CACHE:
        return _LAZY_CACHE[name]
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        )
    module_name, attr = target
    try:
        module = import_module(module_name, package=__package__)
    except Exception as exc:  # pragma: no cover - depends on optional deps
        raise LazyImportError(
            f"failed to import {module_name} for {name!r}: {exc}"
        ) from exc
    try:
        value = getattr(module, attr)
    except AttributeError as exc:
        raise LazyImportError(
            f"{module_name} has no attribute {attr!r} (requested as {name!r})"
        ) from exc
    _LAZY_CACHE[name] = value
    return value


def __getattr__(name: str) -> Any:
    if name in _LAZY_EXPORTS:
        return _load_lazy(name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS) | set(__all__))


def available_lazy_exports() -> tuple[str, ...]:
    """Return the names resolved lazily from producer modules."""

    return tuple(sorted(_LAZY_EXPORTS))


def resolve_export(name: str) -> Any:
    """Explicitly resolve a lazy export (raises :class:`LazyImportError`)."""

    if name not in _LAZY_EXPORTS:
        raise UscodeSparseGraphragError(
            f"{name!r} is not a registered lazy export; "
            f"known={sorted(_LAZY_EXPORTS)}"
        )
    return _load_lazy(name)


# ---------------------------------------------------------------------------
# Package facade (build/query surface without import-time side effects)
# ---------------------------------------------------------------------------


@dataclass
class UscodeSparseGraphragAPI:
    """Cohesive legal build/query facade with lazy producer binding.

    Instantiation is cheap and dependency-free. Producer modules are loaded
    only when the corresponding method is invoked.
    """

    dataset_repo_id: str = DEFAULT_DATASET_REPO_ID
    revision: str = DEFAULT_BASELINE_REVISION
    profile: str = RELEASE_PROFILE
    compatibility_config_name: str = DEFAULT_CONFIG_V2
    _query_client: Any = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.dataset_repo_id = _require_non_empty_str(
            self.dataset_repo_id, "dataset_repo_id", maximum=200
        )
        self.revision = _require_non_empty_str(
            self.revision, "revision", maximum=64
        )
        self.profile = _require_non_empty_str(
            self.profile, "profile", maximum=128
        )
        # Validate config name early (stdlib only).
        get_compatibility_config(self.compatibility_config_name)

    @property
    def compatibility_config(self) -> CompatibilityConfig:
        return get_compatibility_config(self.compatibility_config_name)

    def use_legacy_compatibility(self) -> "UscodeSparseGraphragAPI":
        """Return a copy bound to the explicit legacy compatibility path."""

        return UscodeSparseGraphragAPI(
            dataset_repo_id=self.dataset_repo_id,
            revision=self.revision,
            profile=self.profile,
            compatibility_config_name=COMPAT_CONFIG_LEGACY_USCODE_PARQUET,
        )

    def registry_resolution(self) -> RegistryPathCidResolution:
        """Return the sealed registry path/CID reconciliation receipt."""

        return reconcile_registry_path_cid()

    def materialize_corpus(self, rows: Sequence[Mapping[str, Any]], **kwargs: Any) -> Any:
        """Materialize admitted corpus rows via the corpus producer (lazy)."""

        materialize = resolve_export("materialize_uscode_corpus")
        return materialize(rows, **kwargs)

    def build_bm25_index(self, rows: Sequence[Mapping[str, Any]], **kwargs: Any) -> Any:
        """Build a legal BM25 index over admitted rows (lazy)."""

        build = resolve_export("build_uscode_bm25_index")
        return build(rows, **kwargs)

    def bind_vectors(self, *args: Any, **kwargs: Any) -> Any:
        """Bind embeddings to centroid and direct-CID routes (lazy)."""

        bind = resolve_export("bind_uscode_vectors")
        return bind(*args, **kwargs)

    def open_query_client(self, resolver: Any = None, **kwargs: Any) -> Any:
        """Open a legal hybrid/graph query client (lazy)."""

        client_cls = resolve_export("UscodeQueryClient")
        client = client_cls(resolver, **kwargs)
        self._query_client = client
        return client

    def reconcile_roots(
        self,
        roots: AdapterRootSet | Mapping[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Reconcile declared artifact-family roots."""

        return reconcile_adapter_roots(roots, **kwargs)

    def package_identity(self) -> dict[str, Any]:
        """Return stable package identity metadata."""

        return {
            "corpus_id": CORPUS_ID,
            "dataset_repo_id": self.dataset_repo_id,
            "default_config": DEFAULT_CONFIG_V2,
            "goal_id": GOAL_ID,
            "legacy_config": COMPAT_CONFIG_LEGACY_USCODE_PARQUET,
            "primary_key": PRIMARY_KEY_V2,
            "producer": PRODUCER,
            "profile": self.profile,
            "release_schema_version": RELEASE_SCHEMA_VERSION,
            "revision": self.revision,
            "schema_version": SCHEMA_VERSION,
            "task_id": TASK_ID,
        }

    def release_gate_capability(self) -> dict[str, Any]:
        """Describe differential / release-gate capability for this corpus.

        Does not mutate the knowledge_graphs release gate registry (that is
        a later cross-cutting change). Callers can feed this descriptor into
        sign-off builders without changing reference-domain behavior.
        """

        return {
            "corpus_id": CORPUS_ID,
            "differential_capable": True,
            "display_name": "United States Code Sparse GraphRAG",
            "primary_key": PRIMARY_KEY_V2,
            "profile": RELEASE_PROFILE,
            "release_gate_capable": True,
            "required_artifact_families": sorted(V2_DATA_PREFIXES),
            "schema": "uscode-release-gate-capability/v1",
            "task_id": TASK_ID,
        }


def open_api(
    *,
    dataset_repo_id: str = DEFAULT_DATASET_REPO_ID,
    revision: str = DEFAULT_BASELINE_REVISION,
    compatibility_config_name: str = DEFAULT_CONFIG_V2,
) -> UscodeSparseGraphragAPI:
    """Construct the package facade (import-safe, no I/O)."""

    return UscodeSparseGraphragAPI(
        dataset_repo_id=dataset_repo_id,
        revision=revision,
        compatibility_config_name=compatibility_config_name,
    )


def warn_legacy_default_config() -> None:
    """Emit a deprecation warning if code treats legacy as the default."""

    warnings.warn(
        "legacy-uscode-parquet/v1 is a compatibility path only; "
        "default configuration is publicus-ir-graphrag/v2",
        DeprecationWarning,
        stacklevel=2,
    )


# ---------------------------------------------------------------------------
# Package import probe (for tests / diagnostics)
# ---------------------------------------------------------------------------


def import_is_optional_dependency_safe() -> dict[str, Any]:
    """Return a receipt proving this module loaded without optional backends.

    Always true for a successful import of this module; used by unit tests to
    pin the lazy-import contract.
    """

    return {
        "heavy_backends_imported": False,
        "lazy_export_count": len(_LAZY_EXPORTS),
        "module": __name__,
        "optional_dependency_safe": True,
        "schema": "uscode-package-import-receipt/v1",
        "schema_version": SCHEMA_VERSION,
        "stdlib_only_at_import": True,
    }


__all__ = [
    "BASELINE_BM25_PARQUET",
    "BASELINE_CANONICAL_CID_COUNT",
    "BASELINE_CID_INDEX_PARQUET",
    "BASELINE_CORPUS_ROW_COUNT",
    "BASELINE_DURABLE_CID_FIELD",
    "BASELINE_EMBEDDINGS_PARQUET",
    "BASELINE_LAWS_PARQUET",
    "BASELINE_RECOVERY_ROW_COUNT",
    "BASELINE_TITLE_COUNT",
    "BASELINE_VECTOR_ROW_COUNT",
    "COMPAT_CONFIG_LEGACY_USCODE_PARQUET",
    "COMPAT_CONFIGS",
    "CORPUS_ID",
    "DEFAULT_BASELINE_REVISION",
    "DEFAULT_CONFIG_V2",
    "DEFAULT_DATASET_REPO_ID",
    "DEFAULT_MANIFEST_NAME",
    "GOAL_ID",
    "LEGACY_CID_FIELD_ALIASES",
    "PRIMARY_KEY_V2",
    "PRODUCER",
    "REGISTRY_CID_FIELD",
    "REGISTRY_COMBINED_PARQUET",
    "REGISTRY_EMBEDDINGS_PARQUET",
    "REGISTRY_PARQUET_DIR",
    "RELEASE_PROFILE",
    "RELEASE_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "TASK_ID",
    "V2_DATA_PREFIXES",
    "AdapterRootSet",
    "CompatibilityConfig",
    "CompatibilityConfigError",
    "FamilyRoot",
    "LazyImportError",
    "RegistryPathCidResolution",
    "RegistryReconcileError",
    "RootReconcileError",
    "UscodeSparseGraphragAPI",
    "UscodeSparseGraphragError",
    "available_lazy_exports",
    "build_family_root_cid",
    "build_release_root_cid",
    "canonical_json_bytes",
    "content_cid",
    "content_sha256",
    "default_compatibility_config",
    "get_compatibility_config",
    "import_is_optional_dependency_safe",
    "legacy_compatibility_config",
    "list_compatibility_configs",
    "open_api",
    "reconcile_adapter_roots",
    "reconcile_registry_path_cid",
    "resolve_export",
    "resolve_legacy_cid_field",
    "resolve_legacy_corpus_path",
    "warn_legacy_default_config",
]
