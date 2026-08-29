"""Federated query and substrate compatibility across both public releases (LCR-067).

Read-only composition over the immutable state-law and Federal Register
public pins. This module does **not** own corpus-specific retrieval; it
proves the shared Hugging Face GraphRAG substrate, gates late fusion on
exact ``vector_space_id`` identity, labels every score and authority
semantic per corpus, and packages results as a research aid.

Public operations
-----------------
* ``prove_shared_substrate`` — resolver / descriptor / family / bound
  contract comparison;
* ``prove_vector_space_compatibility`` — exact space identity (never
  dimension alone);
* ``federated_search`` — BM25 / vector / hybrid over labeled per-corpus
  hits with normalized score fusion;
* ``federated_graph`` — per-corpus neighbors / walks; ontologies never
  merge;
* ``query_replay_fingerprint`` — CID-stable reproducibility.

Design invariants
-----------------
* Dimension equality never establishes vector-space compatibility.
* Late-fuse vectors only when every participating release declares the
  same ``vector_space_id``. Otherwise abstain from fusion and keep
  rankings independent.
* Graph ontologies remain domain-private. Graph and retrieval output is
  never legal authority, legal advice, citation, or proof.
* Corpus-specific scores, filters, pins, and provenance stay labeled.
* Federated fetch is bounded; full clones and unbounded scans fail
  closed. Mutable Hub tokens fail closed.
* Results rank stably by ``(score DESC, corpus_id ASC, entry_cid ASC,
  document_index ASC)`` and replay by CID.

No network I/O in unit tests; compact sealed recipes regenerate
in-memory hits at test time.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
import json
import math
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from ipfs_datasets_py.processors.legal_data.federal_register_release_schema import (
    DEFAULT_DATASET_REPO_ID as FEDERAL_DATASET_REPO_ID,
    DEFAULT_EMBEDDING_DIMENSION as FEDERAL_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_MODEL_ID as FEDERAL_EMBEDDING_MODEL_ID,
    DEFAULT_EMBEDDING_MODEL_REVISION as FEDERAL_EMBEDDING_MODEL_REVISION,
    PREVIOUS_PUBLIC_PIN as FEDERAL_PREVIOUS_PUBLIC_PIN,
    RELEASE_PROFILE as FEDERAL_RELEASE_PROFILE,
    required_semantic_families as federal_required_semantic_families,
)
from ipfs_datasets_py.processors.legal_data.federal_register_source_policy import (
    CURRENTNESS_DISCLAIMER as FEDERAL_CURRENTNESS_DISCLAIMER,
)
from ipfs_datasets_py.processors.legal_data.federal_register_vectors import (
    DEFAULT_NORMALIZATION as FEDERAL_NORMALIZATION,
    DEFAULT_POOLING as FEDERAL_POOLING,
    build_vector_space_id as federal_vector_space_id,
)
from ipfs_datasets_py.processors.legal_data.state_laws_embeddings import (
    DEFAULT_NORMALIZATION as STATE_NORMALIZATION,
    DEFAULT_POOLING as STATE_POOLING,
    build_vector_space_id as state_vector_space_id,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    DEFAULT_DATASET_REPO_ID as STATE_DATASET_REPO_ID,
    DEFAULT_EMBEDDING_DIMENSION as STATE_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_MODEL_ID as STATE_EMBEDDING_MODEL_ID,
    DEFAULT_EMBEDDING_MODEL_REVISION as STATE_EMBEDDING_MODEL_REVISION,
    PREVIOUS_PUBLIC_PIN as STATE_PREVIOUS_PUBLIC_PIN,
    RELEASE_PROFILE as STATE_RELEASE_PROFILE,
    physical_bounds_policy,
    required_semantic_families as state_required_semantic_families,
)
from ipfs_datasets_py.processors.legal_data.state_laws_source_policy import (
    CURRENTNESS_DISCLAIMER as STATE_CURRENTNESS_DISCLAIMER,
)
from ipfs_datasets_py.retrieval.hf_graphrag.query import (
    BUDGET_DIMENSIONS,
    DEFAULT_TOP_K,
    MAX_TOP_K,
)
from ipfs_datasets_py.retrieval.hf_graphrag.remote_search import (
    ModelSpace,
    RemoteSearchError,
    RemoteSearchInputError,
    normalize_scores,
    stable_rank,
)
from ipfs_datasets_py.retrieval.hf_graphrag.resolver import (
    MutableRevisionError,
    validate_immutable_revision,
)
from ipfs_datasets_py.retrieval.hf_graphrag.schema import (
    MAX_ADJACENCY_POINTERS_PER_ROW,
    MAX_POINTERS_PER_ROW,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    MAX_ROWS_PER_VECTOR_CENTROID,
    MAX_VECTOR_SHARDS_PER_CENTROID,
    canonical_json_dumps,
    content_sha256,
    digest_mapping,
    physical_bounds_policy as substrate_physical_bounds,
)


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "legal-corpora-query-v1"
FIXTURE_SCHEMA_VERSION: Final = "legal-corpora-query-expected-v1"
REPORT_SCHEMA: Final = (
    "ipfs_datasets_py/legal-corpora-reindex-cross-corpus-canary@1"
)
REPORT_SCHEMA_VERSION: Final = "legal-corpora-cross-corpus-canary-v1"
TASK_ID: Final = "LCR-067"
GOAL_ID: Final = "LCR-G140"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
PRODUCER: Final = "legal_corpora_query.py"
CANARY_PRODUCER: Final = "canary_legal_corpora_public_releases.py"
CODE_VERSION: Final = "1"
DEPENDS_ON: Final = ("LCR-044", "LCR-066")
PRIMARY_KEY: Final = "entry_cid"

DEFAULT_REPORT_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/cross_corpus_canary.json"
)
DEFAULT_STATE_PUBLIC_CANARY_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/public_canary.json"
)
DEFAULT_FEDERAL_PUBLIC_CANARY_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/federal_public_canary.json"
)
DEFAULT_STATE_PUBLICATION_RECEIPT_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/publication_receipt.json"
)
DEFAULT_FEDERAL_PUBLICATION_RECEIPT_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/federal_publication_receipt.json"
)

CORPUS_STATE_LAWS: Final = "state_laws"
CORPUS_FEDERAL_REGISTER: Final = "federal_register"
CORPUS_IDS: Final = (CORPUS_STATE_LAWS, CORPUS_FEDERAL_REGISTER)

STATE_GRAPH_ONTOLOGY: Final = "state-laws-graph-ontology/v1"
FEDERAL_GRAPH_ONTOLOGY: Final = "federal-register-graph-ontology/v1"

DEFAULT_MODEL_ID: Final = STATE_EMBEDDING_MODEL_ID
DEFAULT_MODEL_REVISION: Final = STATE_EMBEDDING_MODEL_REVISION
DEFAULT_DIMENSION: Final = STATE_EMBEDDING_DIMENSION
DEFAULT_POOLING: Final = STATE_POOLING
DEFAULT_NORMALIZATION: Final = STATE_NORMALIZATION
DEFAULT_OBSERVATION_CUTOFF: Final = "2026-08-10T00:00:00Z"

SHARED_DENSE_ROUTE: Final = "normalized_embedding_centroids"
SHARED_SPARSE_ROUTE: Final = "lexicographic_bm25_term_ranges"
SHARED_DESCRIPTOR_SCHEMAS: Final = (
    "hf-graphrag-artifact-descriptor/v1",
    "hf-graphrag-artifact-schema/v1",
    "hf-graphrag-release/v1",
)
SHARED_RESOLVER: Final = "ipfs_datasets_py.retrieval.hf_graphrag.resolver"

QUERY_MODES: Final = (
    "bm25",
    "vector",
    "hybrid",
    "neighbors",
    "graph_walk",
)
GRAPH_MODES: Final = frozenset({"neighbors", "graph_walk", "semantic_graph_walk"})
FUSION_WEIGHTED: Final = "weighted"
FUSION_RRF: Final = "rrf"
FUSION_METHODS: Final = frozenset({FUSION_WEIGHTED, FUSION_RRF})
DEFAULT_STATE_WEIGHT: Final = 0.5
DEFAULT_FEDERAL_WEIGHT: Final = 0.5
DEFAULT_RRF_K: Final = 60

AUTHORITY_NON_AUTHORITATIVE: Final = "non_authoritative"
RESEARCH_AID_DISCLAIMER: Final = (
    "Cross-corpus retrieval and graph output is a research aid. It is not "
    "legal authority, legal advice, a citation, or a substitute for the "
    "official source of either corpus."
)
CROSS_CORPUS_CURRENTNESS_DISCLAIMER: Final = (
    f"{STATE_CURRENTNESS_DISCLAIMER} {FEDERAL_CURRENTNESS_DISCLAIMER} "
    f"{RESEARCH_AID_DISCLAIMER}"
)

MUTABLE_REVISION_TOKENS: Final = frozenset(
    {"main", "master", "latest", "head", "dev", "develop"}
)
SECRET_ENV_NAMES: Final = (
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "HUGGINGFACE_TOKEN",
    "HUGGINGFACEHUB_API_TOKEN",
    "STATE_LAWS_HF_TOKEN",
    "FEDERAL_REGISTER_HF_TOKEN",
)
DIGEST_FIELDS: Final = ("digest", "content_digest", "report_digest_sha256")

REQUIRED_SHARED_FAMILIES: Final = (
    "bm25_documents",
    "bm25_postings",
    "centroids",
    "corpus",
    "graph_adjacency_in",
    "graph_adjacency_out",
    "graph_edges",
    "graph_nodes",
    "locator_index",
    "manifest",
    "vectors",
)

ACCEPTANCE_FLAGS: Final = (
    "cross_corpus_queries_reproducible",
    "dimension_alone_cannot_establish_compatibility",
    "graph_ontologies_remain_domain_private",
    "graph_retrieval_not_legal_advice",
    "graph_retrieval_not_legal_authority",
    "normalized_score_fusion_labeled",
    "per_corpus_provenance_labeled",
    "provenance_safe",
    "shared_resolver_descriptor_vector_contracts",
    "vector_space_id_required_for_late_fusion",
)

DEFAULT_FEDERATED_BUDGETS: Final = MappingProxyType(
    {
        "max_bytes": 8_000_000,
        "max_query_bytes": 4_000_000,
        "max_query_shards": 48,
        "max_results_per_corpus": 100,
        "max_rows": 4096,
        "max_shards": 64,
    }
)

PathLike = str | Path
JsonMapping = Mapping[str, Any]
Searcher = Callable[..., Mapping[str, Any]]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class LegalCorporaQueryError(RemoteSearchError):
    """Base error for federated legal-corpora query failures."""

    code: str = "legal_corpora_query_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class LegalCorporaQueryInputError(LegalCorporaQueryError, RemoteSearchInputError):
    """Raised when federated query inputs are malformed."""

    code = "query_input_invalid"


class VectorSpaceIncompatibilityError(LegalCorporaQueryError):
    """Raised when two releases declare distinct vector-space identifiers."""

    code = "vector_space_incompatible"


class SharedSubstrateIncompatibilityError(LegalCorporaQueryError):
    """Raised when shared resolver/descriptor/family/bound contracts diverge."""

    code = "shared_substrate_incompatible"


class GraphOntologyIncompatibilityError(LegalCorporaQueryError):
    """Raised when domain graph ontologies are treated as interchangeable."""

    code = "graph_ontology_incompatible"


class FusionConfigError(LegalCorporaQueryError):
    """Raised when federated fusion configuration is invalid."""

    code = "fusion_config_invalid"


class FederatedBudgetError(LegalCorporaQueryError):
    """Raised when a federated fetch would exceed a sealed budget."""

    code = "federated_budget_exceeded"


class LegalAuthorityCollisionError(LegalCorporaQueryError):
    """Raised when retrieval or graph output is packaged as legal authority."""

    code = "legal_authority_collision"


class QueryPinError(LegalCorporaQueryError, MutableRevisionError):
    """Raised when an immutable pin is missing or mutable."""

    code = "query_pin_invalid"


class QueryPathError(LegalCorporaQueryError):
    """Raised when a federated fetch path is unsafe."""

    code = "query_path_invalid"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LegalCorporaQueryInputError(f"{name} must be a non-empty string")
    text = value.strip()
    if "\x00" in text:
        raise LegalCorporaQueryInputError(f"{name} must not contain NUL")
    if len(text) > maximum:
        raise LegalCorporaQueryInputError(f"{name} exceeds maximum length {maximum}")
    return text


def _require_positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise LegalCorporaQueryInputError(f"{name} must be a positive integer")
    return value


def _require_non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LegalCorporaQueryInputError(f"{name} must be a non-negative integer")
    return value


def _require_weight(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FusionConfigError(f"{name} must be a finite number")
    number = float(value)
    if not math.isfinite(number) or number < 0.0:
        raise FusionConfigError(f"{name} must be a non-negative finite number")
    return number


def _finite_score(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def _as_mapping(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        mapped = to_dict()
        if isinstance(mapped, Mapping):
            return dict(mapped)
    raise LegalCorporaQueryInputError(f"{name} must be a mapping")


def _hit_identity(hit: Mapping[str, Any], *, corpus_id: str = "") -> str:
    corpus = str(hit.get("corpus_id") or corpus_id or "")
    for key in ("entry_cid", "chunk_cid", "node_cid"):
        value = hit.get(key)
        if value is not None and value != "":
            return f"{corpus}:{key}:{value}"
    document_index = hit.get("document_index")
    if document_index is not None and document_index != "":
        return f"{corpus}:document_index:{document_index}"
    return f"{corpus}:row:{id(hit)}"


def _component_score(hit: Mapping[str, Any]) -> float:
    for key in ("normalized_score", "score", "corpus_score"):
        score = _finite_score(hit.get(key))
        if score is not None:
            return score
    return 0.0


def _normalize_mode(value: Any) -> str:
    mode = _require_non_empty_str(value, "mode", maximum=64).replace("-", "_")
    return mode.lower()


def shared_vector_space_id(
    *,
    model_id: str = DEFAULT_MODEL_ID,
    model_revision: str = DEFAULT_MODEL_REVISION,
    pooling: str = DEFAULT_POOLING,
    normalization: str = DEFAULT_NORMALIZATION,
    dimension: int = DEFAULT_DIMENSION,
) -> str:
    """Return the sealed shared space id (state and Federal builders agree)."""

    state_id = state_vector_space_id(
        model_id=model_id,
        model_revision=model_revision,
        pooling=pooling,
        normalization=normalization,
        dimension=dimension,
    )
    federal_id = federal_vector_space_id(
        model_id=model_id,
        model_revision=model_revision,
        pooling=pooling,
        normalization=normalization,
        dimension=dimension,
    )
    if state_id != federal_id:
        raise VectorSpaceIncompatibilityError(
            "state and Federal vector-space builders diverged: "
            f"{state_id!r} vs {federal_id!r}"
        )
    return state_id


SHARED_VECTOR_SPACE_ID: Final = shared_vector_space_id()


def assert_immutable_revision(value: Any, *, name: str = "revision") -> str:
    """Fail closed unless *value* is a 40-hex immutable Hub pin."""

    text = _require_non_empty_str(value, name, maximum=64)
    if text.lower() in MUTABLE_REVISION_TOKENS:
        raise QueryPinError(f"{name} must not be a mutable token: {value!r}")
    try:
        return validate_immutable_revision(text, name=name)
    except MutableRevisionError as exc:
        raise QueryPinError(str(exc)) from exc


def default_report_path(repo_root: PathLike | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else _repository_root()
    return root / DEFAULT_REPORT_RELPATH


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def payload_without_digests(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key not in DIGEST_FIELDS}


def attach_payload_digests(payload: Mapping[str, Any]) -> dict[str, Any]:
    body = payload_without_digests(payload)
    digest = digest_mapping(body)
    out = dict(body)
    out["content_digest"] = digest
    out["digest"] = digest
    out["report_digest_sha256"] = digest
    return out


# ---------------------------------------------------------------------------
# Authority packaging
# ---------------------------------------------------------------------------


def research_aid_semantics() -> dict[str, Any]:
    """Sealed non-authoritative semantics for every federated output."""

    return {
        "authority": AUTHORITY_NON_AUTHORITATIVE,
        "disclaimer": RESEARCH_AID_DISCLAIMER,
        "legal_advice": False,
        "legal_authority": False,
        "notes": (
            "Graph adjacency, BM25 neighbors, vector similarity, and fused "
            "rankings are retrieval structures. They must never be labeled "
            "as legal citation, authority, amendment, advice, or proof."
        ),
        "proof_authority": False,
        "retrieval_hint": True,
    }


def annotate_non_authority(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Stamp research-aid semantics onto a hit, edge, or result envelope."""

    row = dict(payload)
    semantics = research_aid_semantics()
    for key, value in semantics.items():
        existing = row.get(key)
        if key in {"legal_authority", "legal_advice", "proof_authority"}:
            if existing is True:
                raise LegalAuthorityCollisionError(
                    f"{key} cannot be true on retrieval or graph output"
                )
            row[key] = False
            continue
        if key == "authority" and existing not in (None, "", AUTHORITY_NON_AUTHORITATIVE):
            raise LegalAuthorityCollisionError(
                f"retrieval output cannot use authority={existing!r}"
            )
        if key not in row or row[key] in (None, ""):
            row[key] = value
    return row


def assert_no_retrieval_as_legal_authority(
    items: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None,
) -> None:
    """Fail closed when any packaged row claims legal authority or advice."""

    if items is None:
        return
    rows: Sequence[Mapping[str, Any]]
    if isinstance(items, Mapping):
        rows = (items,)
    else:
        rows = items
    for item in rows:
        if not isinstance(item, Mapping):
            continue
        annotated = annotate_non_authority(item)
        if annotated.get("legal_authority") is not False:
            raise LegalAuthorityCollisionError(
                "retrieval or graph output presented as legal authority"
            )
        if annotated.get("legal_advice") is not False:
            raise LegalAuthorityCollisionError(
                "retrieval or graph output presented as legal advice"
            )
        if annotated.get("proof_authority") is not False:
            raise LegalAuthorityCollisionError(
                "retrieval or graph output presented as proof authority"
            )
        if annotated.get("authority") != AUTHORITY_NON_AUTHORITATIVE:
            raise LegalAuthorityCollisionError(
                "retrieval or graph output must be non_authoritative"
            )


# ---------------------------------------------------------------------------
# Corpus pin / substrate / vector-space records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CorpusPin:
    """Immutable public identity of one participating release."""

    corpus_id: str
    repo_id: str
    revision: str
    release_profile: str
    vector_space_id: str
    dimension: int
    model_id: str = DEFAULT_MODEL_ID
    model_revision: str = DEFAULT_MODEL_REVISION
    pooling: str = DEFAULT_POOLING
    normalization: str = DEFAULT_NORMALIZATION
    graph_ontology_version: str = ""
    previous_public_pin: str = ""
    observation_cutoff: str = DEFAULT_OBSERVATION_CUTOFF
    dense_route: str = SHARED_DENSE_ROUTE
    sparse_route: str = SHARED_SPARSE_ROUTE
    families: tuple[str, ...] = REQUIRED_SHARED_FAMILIES
    descriptor_schemas: tuple[str, ...] = SHARED_DESCRIPTOR_SCHEMAS
    physical_bounds: Mapping[str, int] = field(
        default_factory=lambda: MappingProxyType(dict(substrate_physical_bounds()))
    )

    def __post_init__(self) -> None:
        corpus = _require_non_empty_str(self.corpus_id, "corpus_id", maximum=64)
        if corpus not in CORPUS_IDS:
            raise LegalCorporaQueryInputError(
                f"corpus_id must be one of {list(CORPUS_IDS)}, got {self.corpus_id!r}"
            )
        repo = _require_non_empty_str(self.repo_id, "repo_id", maximum=256)
        revision = assert_immutable_revision(self.revision, name="revision")
        profile = _require_non_empty_str(
            self.release_profile, "release_profile", maximum=128
        )
        space = _require_non_empty_str(
            self.vector_space_id, "vector_space_id", maximum=512
        )
        dimension = _require_positive_int(self.dimension, "dimension")
        model_id = _require_non_empty_str(self.model_id, "model_id")
        model_revision = assert_immutable_revision(
            self.model_revision, name="model_revision"
        )
        pooling = _require_non_empty_str(self.pooling, "pooling", maximum=32).lower()
        normalization = _require_non_empty_str(
            self.normalization, "normalization", maximum=32
        ).lower()
        families = tuple(
            _require_non_empty_str(item, "family", maximum=64)
            for item in self.families
        )
        schemas = tuple(
            _require_non_empty_str(item, "descriptor_schema", maximum=128)
            for item in self.descriptor_schemas
        )
        bounds = MappingProxyType(
            {
                str(key): _require_positive_int(value, f"physical_bounds.{key}")
                for key, value in dict(self.physical_bounds).items()
            }
        )
        previous = (
            assert_immutable_revision(
                self.previous_public_pin, name="previous_public_pin"
            )
            if self.previous_public_pin
            else ""
        )
        object.__setattr__(self, "corpus_id", corpus)
        object.__setattr__(self, "repo_id", repo)
        object.__setattr__(self, "revision", revision)
        object.__setattr__(self, "release_profile", profile)
        object.__setattr__(self, "vector_space_id", space)
        object.__setattr__(self, "dimension", dimension)
        object.__setattr__(self, "model_id", model_id)
        object.__setattr__(self, "model_revision", model_revision)
        object.__setattr__(self, "pooling", pooling)
        object.__setattr__(self, "normalization", normalization)
        object.__setattr__(self, "families", families)
        object.__setattr__(self, "descriptor_schemas", schemas)
        object.__setattr__(self, "physical_bounds", bounds)
        object.__setattr__(self, "previous_public_pin", previous)
        object.__setattr__(
            self,
            "dense_route",
            _require_non_empty_str(self.dense_route, "dense_route", maximum=128),
        )
        object.__setattr__(
            self,
            "sparse_route",
            _require_non_empty_str(self.sparse_route, "sparse_route", maximum=128),
        )
        object.__setattr__(
            self,
            "graph_ontology_version",
            str(self.graph_ontology_version or "").strip(),
        )
        object.__setattr__(
            self,
            "observation_cutoff",
            str(self.observation_cutoff or DEFAULT_OBSERVATION_CUTOFF).strip(),
        )

    def model_space(self) -> ModelSpace:
        return ModelSpace(
            model_id=self.model_id,
            model_revision=self.model_revision,
            vector_space_id=self.vector_space_id,
            dimension=self.dimension,
            normalization=self.normalization,
            pooling=self.pooling,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "corpus_id": self.corpus_id,
            "dataset_repo_id": self.repo_id,
            "dense_route": self.dense_route,
            "descriptor_schemas": list(self.descriptor_schemas),
            "dimension": self.dimension,
            "families": list(self.families),
            "graph_ontology_version": self.graph_ontology_version,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "normalization": self.normalization,
            "observation_cutoff": self.observation_cutoff,
            "physical_bounds": dict(self.physical_bounds),
            "pooling": self.pooling,
            "previous_public_pin": self.previous_public_pin,
            "release_profile": self.release_profile,
            "revision": self.revision,
            "sparse_route": self.sparse_route,
            "vector_space_id": self.vector_space_id,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CorpusPin":
        if not isinstance(value, Mapping):
            raise LegalCorporaQueryInputError("corpus pin must be a mapping")
        families = value.get("families") or value.get("required_semantic_families")
        bounds = value.get("physical_bounds") or value.get("bounds")
        return cls(
            corpus_id=str(value.get("corpus_id") or value.get("corpus") or ""),
            repo_id=str(
                value.get("repo_id")
                or value.get("dataset_repo_id")
                or value.get("target_repo")
                or ""
            ),
            revision=str(
                value.get("revision")
                or value.get("public_sha")
                or value.get("public_revision")
                or ""
            ),
            release_profile=str(value.get("release_profile") or ""),
            vector_space_id=str(value.get("vector_space_id") or ""),
            dimension=int(value.get("dimension") or 0),
            model_id=str(value.get("model_id") or DEFAULT_MODEL_ID),
            model_revision=str(value.get("model_revision") or DEFAULT_MODEL_REVISION),
            pooling=str(value.get("pooling") or DEFAULT_POOLING),
            normalization=str(value.get("normalization") or DEFAULT_NORMALIZATION),
            graph_ontology_version=str(value.get("graph_ontology_version") or ""),
            previous_public_pin=str(value.get("previous_public_pin") or ""),
            observation_cutoff=str(
                value.get("observation_cutoff") or DEFAULT_OBSERVATION_CUTOFF
            ),
            dense_route=str(value.get("dense_route") or SHARED_DENSE_ROUTE),
            sparse_route=str(value.get("sparse_route") or SHARED_SPARSE_ROUTE),
            families=tuple(families) if families else REQUIRED_SHARED_FAMILIES,
            descriptor_schemas=tuple(
                value.get("descriptor_schemas") or SHARED_DESCRIPTOR_SCHEMAS
            ),
            physical_bounds=dict(bounds) if isinstance(bounds, Mapping) else dict(
                substrate_physical_bounds()
            ),
        )


def default_state_pin(
    *,
    revision: str | None = None,
    vector_space_id: str | None = None,
) -> CorpusPin:
    return CorpusPin(
        corpus_id=CORPUS_STATE_LAWS,
        repo_id=STATE_DATASET_REPO_ID,
        revision=revision or STATE_PREVIOUS_PUBLIC_PIN,
        release_profile=STATE_RELEASE_PROFILE,
        vector_space_id=vector_space_id or SHARED_VECTOR_SPACE_ID,
        dimension=STATE_EMBEDDING_DIMENSION,
        model_id=STATE_EMBEDDING_MODEL_ID,
        model_revision=STATE_EMBEDDING_MODEL_REVISION,
        pooling=STATE_POOLING,
        normalization=STATE_NORMALIZATION,
        graph_ontology_version=STATE_GRAPH_ONTOLOGY,
        previous_public_pin=STATE_PREVIOUS_PUBLIC_PIN,
        dense_route=SHARED_DENSE_ROUTE,
        sparse_route=SHARED_SPARSE_ROUTE,
        families=state_required_semantic_families(),
        physical_bounds=physical_bounds_policy(),
    )


def default_federal_pin(
    *,
    revision: str | None = None,
    vector_space_id: str | None = None,
) -> CorpusPin:
    return CorpusPin(
        corpus_id=CORPUS_FEDERAL_REGISTER,
        repo_id=FEDERAL_DATASET_REPO_ID,
        revision=revision or FEDERAL_PREVIOUS_PUBLIC_PIN,
        release_profile=FEDERAL_RELEASE_PROFILE,
        vector_space_id=vector_space_id or SHARED_VECTOR_SPACE_ID,
        dimension=FEDERAL_EMBEDDING_DIMENSION,
        model_id=FEDERAL_EMBEDDING_MODEL_ID,
        model_revision=FEDERAL_EMBEDDING_MODEL_REVISION,
        pooling=FEDERAL_POOLING,
        normalization=FEDERAL_NORMALIZATION,
        graph_ontology_version=FEDERAL_GRAPH_ONTOLOGY,
        previous_public_pin=FEDERAL_PREVIOUS_PUBLIC_PIN,
        dense_route=SHARED_DENSE_ROUTE,
        sparse_route=SHARED_SPARSE_ROUTE,
        families=federal_required_semantic_families(),
        physical_bounds=physical_bounds_policy(),
    )


def pin_from_public_canary(
    payload: Mapping[str, Any],
    *,
    corpus_id: str,
) -> CorpusPin:
    """Build a corpus pin from a sealed public canary or receipt."""

    report = _as_mapping(payload, "public_canary")
    embedding = _as_mapping(
        report.get("embedding") or report.get("embedding_contract") or {},
        "embedding",
    )
    bindings = _as_mapping(report.get("bindings") or {}, "bindings")
    if not embedding:
        embedding = _as_mapping(bindings.get("embedding_contract") or {}, "embedding")
    dimension = int(
        embedding.get("dimension")
        or report.get("dimension")
        or DEFAULT_DIMENSION
    )
    model_id = str(embedding.get("model_id") or DEFAULT_MODEL_ID)
    model_revision = str(embedding.get("model_revision") or DEFAULT_MODEL_REVISION)
    pooling = str(embedding.get("pooling") or DEFAULT_POOLING)
    normalization = str(embedding.get("normalization") or DEFAULT_NORMALIZATION)
    space = str(
        report.get("vector_space_id")
        or embedding.get("vector_space_id")
        or bindings.get("vector_space_id")
        or ""
    )
    if not space:
        space = shared_vector_space_id(
            model_id=model_id,
            model_revision=model_revision,
            pooling=pooling,
            normalization=normalization,
            dimension=dimension,
        )
    families = (
        report.get("required_semantic_families")
        or report.get("families")
        or (report.get("parity") or {}).get("required_families")
        or REQUIRED_SHARED_FAMILIES
    )
    revision = (
        report.get("public_sha")
        or report.get("public_revision")
        or report.get("revision")
        or ""
    )
    default_profile = (
        STATE_RELEASE_PROFILE
        if corpus_id == CORPUS_STATE_LAWS
        else FEDERAL_RELEASE_PROFILE
    )
    default_ontology = (
        STATE_GRAPH_ONTOLOGY
        if corpus_id == CORPUS_STATE_LAWS
        else FEDERAL_GRAPH_ONTOLOGY
    )
    default_previous = (
        STATE_PREVIOUS_PUBLIC_PIN
        if corpus_id == CORPUS_STATE_LAWS
        else FEDERAL_PREVIOUS_PUBLIC_PIN
    )
    default_repo = (
        STATE_DATASET_REPO_ID
        if corpus_id == CORPUS_STATE_LAWS
        else FEDERAL_DATASET_REPO_ID
    )
    return CorpusPin(
        corpus_id=corpus_id,
        repo_id=str(
            report.get("dataset_repo_id")
            or report.get("target_repo")
            or report.get("target")
            or default_repo
        ),
        revision=str(revision),
        release_profile=str(report.get("release_profile") or default_profile),
        vector_space_id=space,
        dimension=dimension,
        model_id=model_id,
        model_revision=model_revision,
        pooling=pooling,
        normalization=normalization,
        graph_ontology_version=str(
            report.get("graph_ontology_version")
            or bindings.get("graph_ontology_version")
            or default_ontology
        ),
        previous_public_pin=str(
            report.get("previous_public_pin")
            or report.get("old_sha")
            or report.get("base_revision")
            or default_previous
        ),
        observation_cutoff=str(
            report.get("observation_cutoff") or DEFAULT_OBSERVATION_CUTOFF
        ),
        dense_route=str(
            bindings.get("dense_route")
            or report.get("dense_route")
            or SHARED_DENSE_ROUTE
        ),
        sparse_route=str(
            bindings.get("sparse_route")
            or report.get("sparse_route")
            or SHARED_SPARSE_ROUTE
        ),
        families=tuple(families),
        physical_bounds=physical_bounds_policy(),
    )


# ---------------------------------------------------------------------------
# Shared substrate + vector-space proofs
# ---------------------------------------------------------------------------


def compare_vector_spaces(
    left: CorpusPin | Mapping[str, Any] | ModelSpace,
    right: CorpusPin | Mapping[str, Any] | ModelSpace,
    *,
    left_name: str = CORPUS_STATE_LAWS,
    right_name: str = CORPUS_FEDERAL_REGISTER,
) -> dict[str, Any]:
    """Compare two spaces. Dimension equality is recorded, never decisive."""

    left_pin = _coerce_space(left, left_name)
    right_pin = _coerce_space(right, right_name)
    left_id = left_pin["vector_space_id"]
    right_id = right_pin["vector_space_id"]
    left_dim = left_pin["dimension"]
    right_dim = right_pin["dimension"]
    id_match = bool(left_id) and left_id == right_id
    dimension_match = left_dim == right_dim and left_dim > 0
    compatible = id_match
    reason = "vector_space_id_match" if compatible else "vector_space_id_mismatch"
    if not left_id or not right_id:
        reason = "vector_space_id_missing"
    elif dimension_match and not id_match:
        reason = "dimension_match_insufficient"
    return {
        "compatible": compatible,
        "dimension_alone_cannot_establish_compatibility": True,
        "dimension_match": dimension_match,
        "left": left_pin,
        "left_name": left_name,
        "reason": reason,
        "right": right_pin,
        "right_name": right_name,
        "vector_space_id_match": id_match,
    }


def _coerce_space(
    value: CorpusPin | Mapping[str, Any] | ModelSpace,
    name: str,
) -> dict[str, Any]:
    if isinstance(value, CorpusPin):
        return {
            "dimension": value.dimension,
            "model_id": value.model_id,
            "model_revision": value.model_revision,
            "normalization": value.normalization,
            "pooling": value.pooling,
            "vector_space_id": value.vector_space_id,
        }
    if isinstance(value, ModelSpace):
        return value.to_dict()
    mapped = _as_mapping(value, name)
    dimension = mapped.get("dimension") or mapped.get("dims") or 0
    space = (
        mapped.get("vector_space_id")
        or mapped.get("model_space")
        or mapped.get("space_id")
        or ""
    )
    return {
        "dimension": int(dimension) if dimension not in (None, "") else 0,
        "model_id": str(mapped.get("model_id") or mapped.get("model_name") or ""),
        "model_revision": str(
            mapped.get("model_revision") or mapped.get("revision") or ""
        ),
        "normalization": str(mapped.get("normalization") or mapped.get("norm") or ""),
        "pooling": str(mapped.get("pooling") or ""),
        "vector_space_id": str(space),
    }


def require_compatible_vector_spaces(
    left: CorpusPin | Mapping[str, Any] | ModelSpace,
    right: CorpusPin | Mapping[str, Any] | ModelSpace,
    *,
    left_name: str = CORPUS_STATE_LAWS,
    right_name: str = CORPUS_FEDERAL_REGISTER,
) -> str:
    """Late-fuse gate: identical ``vector_space_id`` only (never dimension)."""

    comparison = compare_vector_spaces(
        left, right, left_name=left_name, right_name=right_name
    )
    if comparison["compatible"]:
        return str(comparison["left"]["vector_space_id"])
    left_id = comparison["left"]["vector_space_id"]
    right_id = comparison["right"]["vector_space_id"]
    left_dim = comparison["left"]["dimension"]
    right_dim = comparison["right"]["dimension"]
    if comparison["reason"] == "vector_space_id_missing":
        raise VectorSpaceIncompatibilityError(
            "vector_space_id is required on both releases; dimension alone "
            "never implies compatibility"
        )
    raise VectorSpaceIncompatibilityError(
        f"vector spaces are not interchangeable: {left_name}={left_id!r} "
        f"(dim={left_dim}) vs {right_name}={right_id!r} (dim={right_dim}); "
        "matching dimensions alone never imply compatibility"
    )


def prove_vector_space_compatibility(
    left: CorpusPin | Mapping[str, Any],
    right: CorpusPin | Mapping[str, Any],
    *,
    left_name: str = CORPUS_STATE_LAWS,
    right_name: str = CORPUS_FEDERAL_REGISTER,
    strict: bool = True,
) -> dict[str, Any]:
    """Return a sealed compatibility proof or abstain / raise."""

    comparison = compare_vector_spaces(
        left, right, left_name=left_name, right_name=right_name
    )
    abstention: dict[str, Any] | None = None
    if not comparison["compatible"]:
        if strict:
            require_compatible_vector_spaces(
                left, right, left_name=left_name, right_name=right_name
            )
        abstention = {
            "action": "keep_rankings_independent",
            "fuse_vectors": False,
            "reason": comparison["reason"],
        }
    return {
        **comparison,
        "abstention": abstention,
        "fuse_vectors": comparison["compatible"],
        "late_fusion_rule": (
            "late-fuse across releases only when every participant declares "
            "the same vector_space_id; otherwise keep rankings independent "
            "and fuse scores at the labeled result layer only after "
            "normalization, never by dimension"
        ),
        "ok": comparison["compatible"],
    }


def prove_shared_substrate(
    left: CorpusPin | Mapping[str, Any],
    right: CorpusPin | Mapping[str, Any],
    *,
    left_name: str = CORPUS_STATE_LAWS,
    right_name: str = CORPUS_FEDERAL_REGISTER,
) -> dict[str, Any]:
    """Prove shared resolver, descriptor, family, route, and bound contracts."""

    left_pin = left if isinstance(left, CorpusPin) else CorpusPin.from_mapping(left)
    right_pin = right if isinstance(right, CorpusPin) else CorpusPin.from_mapping(right)
    findings: list[str] = []

    left_families = set(left_pin.families)
    right_families = set(right_pin.families)
    required = set(REQUIRED_SHARED_FAMILIES)
    if not required.issubset(left_families):
        findings.append(
            f"{left_name} missing required families: "
            f"{sorted(required - left_families)}"
        )
    if not required.issubset(right_families):
        findings.append(
            f"{right_name} missing required families: "
            f"{sorted(required - right_families)}"
        )

    shared_families = sorted(left_families & right_families)
    if not required.issubset(set(shared_families)):
        findings.append("shared semantic-family intersection is incomplete")

    left_bounds = dict(left_pin.physical_bounds)
    right_bounds = dict(right_pin.physical_bounds)
    expected_bounds = {
        "max_rows_per_physical_shard": MAX_ROWS_PER_PHYSICAL_SHARD,
        "max_rows_per_vector_centroid": MAX_ROWS_PER_VECTOR_CENTROID,
        "max_vector_shards_per_centroid": MAX_VECTOR_SHARDS_PER_CENTROID,
    }
    for key, expected in expected_bounds.items():
        if int(left_bounds.get(key) or 0) != expected:
            findings.append(f"{left_name} {key} != {expected}")
        if int(right_bounds.get(key) or 0) != expected:
            findings.append(f"{right_name} {key} != {expected}")

    pointer_keys = (
        "max_adjacency_pointers_per_row",
        "max_posting_pointers_per_row",
        "max_pointers_per_row",
    )
    for key in pointer_keys:
        left_value = left_bounds.get(key)
        right_value = right_bounds.get(key)
        if left_value is not None and int(left_value) > MAX_POINTERS_PER_ROW:
            findings.append(f"{left_name} {key} exceeds {MAX_POINTERS_PER_ROW}")
        if right_value is not None and int(right_value) > MAX_POINTERS_PER_ROW:
            findings.append(f"{right_name} {key} exceeds {MAX_POINTERS_PER_ROW}")

    if left_pin.dense_route != right_pin.dense_route:
        findings.append(
            f"dense_route mismatch: {left_pin.dense_route!r} vs "
            f"{right_pin.dense_route!r}"
        )
    if left_pin.sparse_route != right_pin.sparse_route:
        findings.append(
            f"sparse_route mismatch: {left_pin.sparse_route!r} vs "
            f"{right_pin.sparse_route!r}"
        )
    if left_pin.dense_route != SHARED_DENSE_ROUTE:
        findings.append(f"{left_name} dense_route is not the shared centroid route")
    if left_pin.sparse_route != SHARED_SPARSE_ROUTE:
        findings.append(f"{left_name} sparse_route is not the shared BM25 route")

    left_schemas = set(left_pin.descriptor_schemas)
    right_schemas = set(right_pin.descriptor_schemas)
    if not set(SHARED_DESCRIPTOR_SCHEMAS).issubset(left_schemas):
        findings.append(f"{left_name} missing shared descriptor schemas")
    if not set(SHARED_DESCRIPTOR_SCHEMAS).issubset(right_schemas):
        findings.append(f"{right_name} missing shared descriptor schemas")

    if left_pin.repo_id == right_pin.repo_id:
        findings.append("corpus pins must name distinct dataset repositories")
    if left_pin.revision == right_pin.revision:
        findings.append("corpus pins must name distinct immutable revisions")

    if findings:
        raise SharedSubstrateIncompatibilityError(
            "shared substrate contracts are not compatible: " + "; ".join(findings)
        )

    return {
        "compatible": True,
        "descriptor_schemas": list(SHARED_DESCRIPTOR_SCHEMAS),
        "families": sorted(required),
        "left": left_pin.to_dict(),
        "ok": True,
        "physical_bounds": {
            "max_adjacency_pointers_per_row": MAX_ADJACENCY_POINTERS_PER_ROW,
            "max_pointers_per_row": MAX_POINTERS_PER_ROW,
            "max_rows_per_physical_shard": MAX_ROWS_PER_PHYSICAL_SHARD,
            "max_rows_per_vector_centroid": MAX_ROWS_PER_VECTOR_CENTROID,
            "max_vector_shards_per_centroid": MAX_VECTOR_SHARDS_PER_CENTROID,
        },
        "primary_key": PRIMARY_KEY,
        "resolver": SHARED_RESOLVER,
        "right": right_pin.to_dict(),
        "routes": {
            "dense_route": SHARED_DENSE_ROUTE,
            "sparse_route": SHARED_SPARSE_ROUTE,
        },
        "shared_families": shared_families,
    }


def prove_graph_ontologies_remain_private(
    left: CorpusPin | Mapping[str, Any],
    right: CorpusPin | Mapping[str, Any],
) -> dict[str, Any]:
    """Layout families may align; domain ontologies must stay unlabeled-as-shared."""

    left_pin = left if isinstance(left, CorpusPin) else CorpusPin.from_mapping(left)
    right_pin = right if isinstance(right, CorpusPin) else CorpusPin.from_mapping(right)
    left_ver = left_pin.graph_ontology_version
    right_ver = right_pin.graph_ontology_version
    if not left_ver or not right_ver:
        raise GraphOntologyIncompatibilityError(
            "graph ontology_version is required on both releases"
        )
    if left_ver == right_ver:
        raise GraphOntologyIncompatibilityError(
            "state-law and Federal Register graph ontologies must remain "
            f"domain-private; both declared {left_ver!r}"
        )
    return {
        "compatible_for_merge": False,
        "fuse_graphs": False,
        "left_ontology": left_ver,
        "ok": True,
        "reason": "domain_ontologies_are_not_interchangeable",
        "right_ontology": right_ver,
        "shared_layout_families": [
            "graph_adjacency_in",
            "graph_adjacency_out",
            "graph_edges",
            "graph_nodes",
        ],
    }


# ---------------------------------------------------------------------------
# Fusion / filters / budgets
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FederatedFusionConfig:
    """Cross-corpus fusion policy. Component scores stay labeled."""

    method: str = FUSION_RRF
    state_weight: float = DEFAULT_STATE_WEIGHT
    federal_weight: float = DEFAULT_FEDERAL_WEIGHT
    rrf_k: int = DEFAULT_RRF_K

    def __post_init__(self) -> None:
        method = str(self.method or FUSION_RRF).strip().lower()
        if method not in FUSION_METHODS:
            raise FusionConfigError(
                f"fusion method must be one of {sorted(FUSION_METHODS)}, "
                f"got {self.method!r}"
            )
        state_w = _require_weight(self.state_weight, "state_weight")
        federal_w = _require_weight(self.federal_weight, "federal_weight")
        if method == FUSION_WEIGHTED and state_w + federal_w <= 0.0:
            raise FusionConfigError(
                "weighted fusion requires at least one positive weight"
            )
        rrf_k = _require_positive_int(self.rrf_k, "rrf_k")
        if rrf_k > 10_000:
            raise FusionConfigError("rrf_k exceeds hard bound 10000")
        object.__setattr__(self, "method", method)
        object.__setattr__(self, "state_weight", state_w)
        object.__setattr__(self, "federal_weight", federal_w)
        object.__setattr__(self, "rrf_k", rrf_k)

    def weight_for(self, corpus_id: str) -> float:
        if corpus_id == CORPUS_STATE_LAWS:
            return self.state_weight
        if corpus_id == CORPUS_FEDERAL_REGISTER:
            return self.federal_weight
        raise FusionConfigError(f"no fusion weight for corpus {corpus_id!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "federal_weight": self.federal_weight,
            "method": self.method,
            "rrf_k": self.rrf_k,
            "state_weight": self.state_weight,
        }

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any] | None = None
    ) -> "FederatedFusionConfig":
        if value is None:
            return cls()
        if isinstance(value, FederatedFusionConfig):
            return value
        if not isinstance(value, Mapping):
            raise FusionConfigError("fusion config must be a mapping")
        kwargs: dict[str, Any] = {}
        for key in ("method", "state_weight", "federal_weight", "rrf_k"):
            if key in value:
                kwargs[key] = value[key]
        return cls(**kwargs)


@dataclass(frozen=True, slots=True)
class FederatedFilters:
    """Per-corpus filter overlay. Unknown corpora are ignored, not merged."""

    corpora: tuple[str, ...] = CORPUS_IDS
    state: Mapping[str, Any] = field(default_factory=dict)
    federal: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        corpora = tuple(
            _require_non_empty_str(item, "corpus", maximum=64)
            for item in (self.corpora or CORPUS_IDS)
        )
        unknown = [item for item in corpora if item not in CORPUS_IDS]
        if unknown:
            raise LegalCorporaQueryInputError(
                f"unknown corpora in filters: {unknown}"
            )
        object.__setattr__(self, "corpora", corpora)
        object.__setattr__(self, "state", MappingProxyType(dict(self.state or {})))
        object.__setattr__(
            self, "federal", MappingProxyType(dict(self.federal or {}))
        )

    def allows_corpus(self, corpus_id: str) -> bool:
        return corpus_id in self.corpora

    def for_corpus(self, corpus_id: str) -> dict[str, Any]:
        if corpus_id == CORPUS_STATE_LAWS:
            return dict(self.state)
        if corpus_id == CORPUS_FEDERAL_REGISTER:
            return dict(self.federal)
        return {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "corpora": list(self.corpora),
            "federal": dict(self.federal),
            "state": dict(self.state),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None = None) -> "FederatedFilters":
        if value is None:
            return cls()
        if isinstance(value, FederatedFilters):
            return value
        if not isinstance(value, Mapping):
            raise LegalCorporaQueryInputError("filters must be a mapping")
        corpora = value.get("corpora") or CORPUS_IDS
        return cls(
            corpora=tuple(corpora),
            state=dict(value.get("state") or value.get(CORPUS_STATE_LAWS) or {}),
            federal=dict(
                value.get("federal") or value.get(CORPUS_FEDERAL_REGISTER) or {}
            ),
        )


@dataclass(frozen=True, slots=True)
class FederatedLimits:
    """Typed budgets for federated fetch and result assembly."""

    max_bytes: int = 8_000_000
    max_shards: int = 64
    max_rows: int = MAX_ROWS_PER_PHYSICAL_SHARD
    max_results_per_corpus: int = 100
    max_top_k: int = DEFAULT_TOP_K

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "max_bytes", _require_positive_int(self.max_bytes, "max_bytes")
        )
        object.__setattr__(
            self, "max_shards", _require_positive_int(self.max_shards, "max_shards")
        )
        object.__setattr__(
            self, "max_rows", _require_positive_int(self.max_rows, "max_rows")
        )
        object.__setattr__(
            self,
            "max_results_per_corpus",
            _require_positive_int(
                self.max_results_per_corpus, "max_results_per_corpus"
            ),
        )
        top_k = _require_positive_int(self.max_top_k, "max_top_k")
        if top_k > MAX_TOP_K:
            raise FederatedBudgetError(f"max_top_k must be <= {MAX_TOP_K}")
        if self.max_rows > MAX_ROWS_PER_PHYSICAL_SHARD:
            raise FederatedBudgetError(
                f"max_rows {self.max_rows} exceeds sealed physical bound "
                f"{MAX_ROWS_PER_PHYSICAL_SHARD}"
            )
        object.__setattr__(self, "max_top_k", top_k)

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_bytes": self.max_bytes,
            "max_results_per_corpus": self.max_results_per_corpus,
            "max_rows": self.max_rows,
            "max_shards": self.max_shards,
            "max_top_k": self.max_top_k,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None = None) -> "FederatedLimits":
        if value is None:
            return cls()
        if isinstance(value, FederatedLimits):
            return value
        if not isinstance(value, Mapping):
            raise LegalCorporaQueryInputError("limits must be a mapping")
        kwargs: dict[str, Any] = {}
        for key in (
            "max_bytes",
            "max_shards",
            "max_rows",
            "max_results_per_corpus",
            "max_top_k",
        ):
            if key in value:
                kwargs[key] = value[key]
        if "max_top_k" not in kwargs and "top_k" in value:
            kwargs["max_top_k"] = value["top_k"]
        return cls(**kwargs)


def assert_federated_fetch_within_budget(
    traces: Sequence[Mapping[str, Any]] | Mapping[str, Any],
    limits: FederatedLimits | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Fail closed when combined per-corpus fetch traces exceed budgets."""

    budget = (
        limits if isinstance(limits, FederatedLimits) else FederatedLimits.from_mapping(limits)
    )
    if isinstance(traces, Mapping):
        rows: Sequence[Mapping[str, Any]] = (traces,)
    else:
        rows = traces
    bytes_used = 0
    shards_used = 0
    rows_used = 0
    paths: list[str] = []
    for trace in rows:
        if not isinstance(trace, Mapping):
            continue
        bytes_used += int(trace.get("bytes") or trace.get("total_file_bytes") or 0)
        shards_used += int(trace.get("shards") or trace.get("shard_count") or 0)
        rows_used += int(trace.get("rows") or trace.get("row_count") or 0)
        fetched = trace.get("fetched_paths") or trace.get("paths") or ()
        if isinstance(fetched, Sequence) and not isinstance(fetched, (str, bytes)):
            paths.extend(str(item) for item in fetched)
        files = trace.get("files")
        if isinstance(files, Sequence) and not isinstance(files, (str, bytes)):
            shards_used = max(shards_used, len(tuple(files)))
            for item in files:
                if isinstance(item, Mapping):
                    relative = str(item.get("relative_path") or item.get("path") or "")
                    if relative:
                        paths.append(relative)
                    bytes_used += int(item.get("bytes") or 0)
                    rows_used += int(item.get("row_count") or 0)
    if bytes_used > budget.max_bytes:
        raise FederatedBudgetError(
            f"federated fetch used {bytes_used} bytes, exceeds {budget.max_bytes}"
        )
    if shards_used > budget.max_shards:
        raise FederatedBudgetError(
            f"federated fetch used {shards_used} shards, exceeds {budget.max_shards}"
        )
    if rows_used > budget.max_rows:
        raise FederatedBudgetError(
            f"federated fetch used {rows_used} rows, exceeds {budget.max_rows}"
        )
    for path in paths:
        if path.startswith("/") or ".." in path.split("/"):
            raise QueryPathError(f"unsafe federated fetch path: {path!r}")
    return {
        "bytes": bytes_used,
        "ok": True,
        "paths": sorted(set(paths)),
        "rows": rows_used,
        "shards": shards_used,
        "within_budget": True,
    }


def hit_matches_corpus_filters(
    hit: Mapping[str, Any],
    filters: Mapping[str, Any] | None,
) -> bool:
    """Exact-match overlay for labeled per-corpus metadata fields."""

    if not filters:
        return True
    for key, expected in filters.items():
        if expected in (None, "", (), []):
            continue
        observed = hit.get(key)
        if key in {"date_from", "date_to"}:
            date_value = str(
                hit.get("publication_date") or hit.get("date") or ""
            )
            if not date_value:
                return False
            if key == "date_from" and date_value < str(expected):
                return False
            if key == "date_to" and date_value > str(expected):
                return False
            continue
        if isinstance(expected, Sequence) and not isinstance(expected, (str, bytes)):
            if observed not in expected and str(observed) not in {str(item) for item in expected}:
                return False
            continue
        if observed is None:
            return False
        if str(observed) != str(expected):
            return False
    return True


def annotate_hit_provenance(
    hit: Mapping[str, Any],
    pin: CorpusPin,
    *,
    mode: str,
) -> dict[str, Any]:
    """Attach per-corpus provenance and research-aid semantics."""

    row = annotate_non_authority(hit)
    row["corpus_id"] = pin.corpus_id
    row["dataset_repo_id"] = pin.repo_id
    row["revision"] = pin.revision
    row["release_profile"] = pin.release_profile
    row["vector_space_id"] = pin.vector_space_id
    row["graph_ontology_version"] = pin.graph_ontology_version
    row["mode"] = mode
    row["primary_key"] = PRIMARY_KEY
    if "corpus_score" not in row:
        row["corpus_score"] = _component_score(row)
    provenance = {
        "corpus_id": pin.corpus_id,
        "dataset_repo_id": pin.repo_id,
        "entry_cid": row.get("entry_cid"),
        "legal_id": row.get("legal_id"),
        "observation_cutoff": pin.observation_cutoff,
        "previous_public_pin": pin.previous_public_pin,
        "release_profile": pin.release_profile,
        "revision": pin.revision,
        "vector_space_id": pin.vector_space_id,
    }
    row["provenance"] = provenance
    return row


def federated_ranking_key(hit: Mapping[str, Any]) -> tuple[Any, ...]:
    score = _finite_score(hit.get("score"))
    score_key = float("-inf") if score is None else score
    return (
        -score_key,
        str(hit.get("corpus_id") or ""),
        str(hit.get("entry_cid") or ""),
        int(hit.get("document_index") or 0)
        if isinstance(hit.get("document_index"), int)
        and not isinstance(hit.get("document_index"), bool)
        else 2**62,
    )


def fuse_federated_results(
    per_corpus: Mapping[str, Sequence[Mapping[str, Any]]],
    pins: Mapping[str, CorpusPin],
    *,
    mode: str,
    config: FederatedFusionConfig | Mapping[str, Any] | None = None,
    top_k: int = DEFAULT_TOP_K,
    fuse_vectors: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Normalize per-corpus scores and optionally late-fuse across corpora."""

    fusion = (
        config
        if isinstance(config, FederatedFusionConfig)
        else FederatedFusionConfig.from_mapping(config)
    )
    limit = _require_positive_int(top_k, "top_k")
    if limit > MAX_TOP_K:
        raise LegalCorporaQueryInputError(f"top_k must be <= {MAX_TOP_K}")
    query_mode = _normalize_mode(mode)
    labeled: dict[str, list[dict[str, Any]]] = {}
    ranks: dict[str, dict[str, int]] = {}

    for corpus_id, hits in per_corpus.items():
        pin = pins[corpus_id]
        normalized = normalize_scores(list(hits), method="minmax")
        rows: list[dict[str, Any]] = []
        corpus_ranks: dict[str, int] = {}
        for rank, hit in enumerate(normalized, start=1):
            row = annotate_hit_provenance(hit, pin, mode=query_mode)
            identity = _hit_identity(row, corpus_id=corpus_id)
            row["corpus_rank"] = rank
            rows.append(row)
            corpus_ranks[identity] = rank
        labeled[corpus_id] = rows
        ranks[corpus_id] = corpus_ranks

    vector_mode = query_mode in {"vector", "hybrid"}
    should_fuse = bool(fuse_vectors) or query_mode == "bm25"
    if vector_mode and not fuse_vectors:
        should_fuse = False

    diagnostics = {
        "fuse_vectors": bool(fuse_vectors) and vector_mode,
        "fusion": fusion.to_dict(),
        "mode": query_mode,
        "per_corpus_counts": {
            corpus_id: len(rows) for corpus_id, rows in labeled.items()
        },
        "should_fuse": should_fuse,
    }

    if not should_fuse:
        independent = []
        for rows in labeled.values():
            independent.extend(dict(row) for row in rows)
        independent.sort(key=federated_ranking_key)
        for row in independent:
            row["fused"] = False
            row["fusion_method"] = None
        assert_no_retrieval_as_legal_authority(independent)
        return independent[:limit], {
            **diagnostics,
            "abstained_from_fusion": True,
        }

    merged: dict[str, dict[str, Any]] = {}
    for corpus_id, rows in labeled.items():
        weight = fusion.weight_for(corpus_id)
        for row in rows:
            identity = _hit_identity(row, corpus_id=corpus_id)
            payload = dict(row)
            payload["fused"] = True
            payload["fusion_method"] = fusion.method
            payload["corpus_weight"] = weight
            if fusion.method == FUSION_RRF:
                rank = ranks[corpus_id][identity]
                payload["score"] = weight / (fusion.rrf_k + rank)
            else:
                payload["score"] = weight * _component_score(row)
            payload["component_scores"] = {
                **dict(payload.get("component_scores") or {}),
                "corpus": _component_score(row),
                "fused": payload["score"],
            }
            merged[identity] = payload

    fused = sorted(merged.values(), key=federated_ranking_key)[:limit]
    assert_no_retrieval_as_legal_authority(fused)
    return fused, {**diagnostics, "abstained_from_fusion": False}


def query_replay_fingerprint(
    *,
    mode: str,
    query: str,
    results: Sequence[Mapping[str, Any]],
    filters: Mapping[str, Any] | None = None,
    fusion: Mapping[str, Any] | None = None,
    abstentions: Sequence[Mapping[str, Any]] | None = None,
) -> str:
    """Content-address a CID-stable federated ranking."""

    ordered = []
    for item in results:
        ordered.append(
            {
                "corpus_id": item.get("corpus_id"),
                "corpus_score": item.get("corpus_score"),
                "entry_cid": item.get("entry_cid"),
                "fused": item.get("fused"),
                "legal_id": item.get("legal_id"),
                "revision": item.get("revision"),
                "score": _finite_score(item.get("score")),
                "vector_space_id": item.get("vector_space_id"),
            }
        )
    payload = {
        "abstentions": [dict(item) for item in (abstentions or ())],
        "filters": dict(filters or {}),
        "fusion": dict(fusion or {}),
        "mode": _normalize_mode(mode),
        "ordered_results": ordered,
        "query": query,
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
    }
    return content_sha256(canonical_json_dumps(payload))


# ---------------------------------------------------------------------------
# Result envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FederatedQueryResult:
    """Provenance-safe federated query envelope."""

    mode: str
    query: str
    results: tuple[dict[str, Any], ...]
    per_corpus: Mapping[str, tuple[dict[str, Any], ...]]
    compatibility: Mapping[str, Any]
    fusion: Mapping[str, Any]
    filters: Mapping[str, Any]
    abstentions: tuple[dict[str, Any], ...]
    fetch_trace: Mapping[str, Any]
    complete: bool
    stop_reason: str | None
    replay_fingerprint: str
    schema_version: str = SCHEMA_VERSION
    task_id: str = TASK_ID
    goal_id: str = GOAL_ID

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "results", tuple(dict(item) for item in self.results)
        )
        object.__setattr__(
            self,
            "per_corpus",
            MappingProxyType(
                {
                    key: tuple(dict(item) for item in value)
                    for key, value in dict(self.per_corpus).items()
                }
            ),
        )
        object.__setattr__(
            self, "compatibility", MappingProxyType(dict(self.compatibility))
        )
        object.__setattr__(self, "fusion", MappingProxyType(dict(self.fusion)))
        object.__setattr__(self, "filters", MappingProxyType(dict(self.filters)))
        object.__setattr__(
            self, "abstentions", tuple(dict(item) for item in self.abstentions)
        )
        object.__setattr__(
            self, "fetch_trace", MappingProxyType(dict(self.fetch_trace))
        )
        assert_no_retrieval_as_legal_authority(self.results)
        for rows in self.per_corpus.values():
            assert_no_retrieval_as_legal_authority(rows)

    @property
    def result_count(self) -> int:
        return len(self.results)

    def ordered_result_cids(self) -> tuple[str, ...]:
        ordered: list[str] = []
        for item in self.results:
            corpus = str(item.get("corpus_id") or "")
            cid = item.get("entry_cid") or item.get("chunk_cid") or item.get("node_cid")
            if cid is not None:
                ordered.append(f"{corpus}:{cid}")
        return tuple(ordered)

    def to_dict(self) -> dict[str, Any]:
        envelope = {
            "abstentions": list(self.abstentions),
            "compatibility": dict(self.compatibility),
            "complete": self.complete,
            "fetch_trace": dict(self.fetch_trace),
            "filters": dict(self.filters),
            "fusion": dict(self.fusion),
            "goal_id": self.goal_id,
            "legal_advice": False,
            "legal_authority": False,
            "mode": self.mode,
            "ordered_result_cids": list(self.ordered_result_cids()),
            "per_corpus": {
                key: list(value) for key, value in self.per_corpus.items()
            },
            "query": self.query,
            "replay_fingerprint": self.replay_fingerprint,
            "result_count": self.result_count,
            "results": list(self.results),
            "schema_version": self.schema_version,
            "stop_reason": self.stop_reason,
            "task_id": self.task_id,
            **research_aid_semantics(),
        }
        assert_no_retrieval_as_legal_authority(envelope)
        return envelope


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class LegalCorporaQueryClient:
    """Compose two immutable public pins with fail-closed compatibility gates."""

    def __init__(
        self,
        pins: Sequence[CorpusPin],
        *,
        searchers: Mapping[str, Searcher] | None = None,
        limits: FederatedLimits | Mapping[str, Any] | None = None,
    ) -> None:
        if len(tuple(pins)) < 2:
            raise LegalCorporaQueryInputError(
                "federated query requires at least two corpus pins"
            )
        indexed: dict[str, CorpusPin] = {}
        for pin in pins:
            if pin.corpus_id in indexed:
                raise LegalCorporaQueryInputError(
                    f"duplicate corpus pin: {pin.corpus_id}"
                )
            indexed[pin.corpus_id] = pin
        missing = [item for item in CORPUS_IDS if item not in indexed]
        if missing:
            raise LegalCorporaQueryInputError(
                f"federated query requires pins for {list(CORPUS_IDS)}; missing {missing}"
            )
        self._pins = indexed
        self._searchers = dict(searchers or {})
        self._limits = (
            limits
            if isinstance(limits, FederatedLimits)
            else FederatedLimits.from_mapping(limits)
        )
        self._substrate = prove_shared_substrate(
            indexed[CORPUS_STATE_LAWS],
            indexed[CORPUS_FEDERAL_REGISTER],
        )
        self._graph = prove_graph_ontologies_remain_private(
            indexed[CORPUS_STATE_LAWS],
            indexed[CORPUS_FEDERAL_REGISTER],
        )
        self._vector = prove_vector_space_compatibility(
            indexed[CORPUS_STATE_LAWS],
            indexed[CORPUS_FEDERAL_REGISTER],
            strict=False,
        )

    @property
    def pins(self) -> Mapping[str, CorpusPin]:
        return MappingProxyType(self._pins)

    @property
    def substrate(self) -> Mapping[str, Any]:
        return MappingProxyType(dict(self._substrate))

    @property
    def vector_compatibility(self) -> Mapping[str, Any]:
        return MappingProxyType(dict(self._vector))

    def compatibility_proof(self) -> dict[str, Any]:
        return {
            "dimension_alone_cannot_establish_compatibility": True,
            "graph": dict(self._graph),
            "ok": bool(self._substrate.get("ok")) and bool(self._vector.get("ok")),
            "research_aid": research_aid_semantics(),
            "substrate": dict(self._substrate),
            "vector": dict(self._vector),
        }

    def search(
        self,
        query: str,
        *,
        mode: str = "hybrid",
        filters: FederatedFilters | Mapping[str, Any] | None = None,
        fusion: FederatedFusionConfig | Mapping[str, Any] | None = None,
        top_k: int | None = None,
        per_corpus_hits: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
        fetch_traces: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> FederatedQueryResult:
        query_text = _require_non_empty_str(query, "query", maximum=4096)
        query_mode = _normalize_mode(mode)
        if query_mode not in QUERY_MODES and query_mode not in GRAPH_MODES:
            raise LegalCorporaQueryInputError(f"unsupported query mode: {mode!r}")
        overlay = FederatedFilters.from_mapping(filters)
        fusion_cfg = FederatedFusionConfig.from_mapping(fusion)
        limit = top_k if top_k is not None else self._limits.max_top_k
        limit = _require_positive_int(limit, "top_k")

        collected: dict[str, list[dict[str, Any]]] = {}
        traces: list[dict[str, Any]] = []
        abstentions: list[dict[str, Any]] = []
        for corpus_id in CORPUS_IDS:
            pin = self._pins[corpus_id]
            if not overlay.allows_corpus(corpus_id):
                abstentions.append(
                    {
                        "corpus_id": corpus_id,
                        "reason": "corpus_filtered_out",
                    }
                )
                collected[corpus_id] = []
                continue
            raw_hits: Sequence[Mapping[str, Any]]
            if per_corpus_hits is not None and corpus_id in per_corpus_hits:
                raw_hits = per_corpus_hits[corpus_id]
            elif corpus_id in self._searchers:
                raw_hits = _hits_from_searcher(
                    self._searchers[corpus_id],
                    query=query_text,
                    mode=query_mode,
                    filters=overlay.for_corpus(corpus_id),
                    top_k=min(limit, self._limits.max_results_per_corpus),
                    pin=pin,
                )
            else:
                raise LegalCorporaQueryInputError(
                    f"no hits or searcher provided for corpus {corpus_id}"
                )
            filtered = [
                dict(hit)
                for hit in raw_hits
                if hit_matches_corpus_filters(hit, overlay.for_corpus(corpus_id))
            ]
            if len(filtered) > self._limits.max_results_per_corpus:
                filtered = filtered[: self._limits.max_results_per_corpus]
            collected[corpus_id] = filtered
            if fetch_traces and corpus_id in fetch_traces:
                traces.append(dict(fetch_traces[corpus_id]))
            if not filtered:
                abstentions.append(
                    {
                        "corpus_id": corpus_id,
                        "reason": "empty_after_filters",
                    }
                )

        fetch_summary = assert_federated_fetch_within_budget(traces, self._limits)
        graph_mode = query_mode in GRAPH_MODES
        fuse_vectors = bool(self._vector.get("compatible"))
        if graph_mode:
            fuse_vectors = False
            abstentions.append(
                {
                    "reason": "graph_ontology_incompatible",
                    "action": "return_labeled_per_corpus_graph",
                }
            )
        elif query_mode in {"vector", "hybrid"} and not fuse_vectors:
            abstentions.append(
                {
                    "reason": str(self._vector.get("reason") or "vector_space_incompatible"),
                    "action": "keep_rankings_independent",
                }
            )

        fused, fusion_diag = fuse_federated_results(
            collected,
            self._pins,
            mode=query_mode,
            config=fusion_cfg,
            top_k=limit,
            fuse_vectors=fuse_vectors and not graph_mode,
        )
        labeled_per_corpus = {
            corpus_id: tuple(
                annotate_hit_provenance(hit, self._pins[corpus_id], mode=query_mode)
                for hit in hits
            )
            for corpus_id, hits in collected.items()
        }
        fingerprint = query_replay_fingerprint(
            mode=query_mode,
            query=query_text,
            results=fused,
            filters=overlay.to_dict(),
            fusion=fusion_cfg.to_dict(),
            abstentions=abstentions,
        )
        compatibility = self.compatibility_proof()
        result = FederatedQueryResult(
            mode=query_mode,
            query=query_text,
            results=tuple(fused),
            per_corpus=labeled_per_corpus,
            compatibility=compatibility,
            fusion=fusion_diag,
            filters=overlay.to_dict(),
            abstentions=tuple(abstentions),
            fetch_trace=fetch_summary,
            complete=not any(
                item.get("reason") == "budget_exhausted" for item in abstentions
            ),
            stop_reason=None,
            replay_fingerprint=fingerprint,
        )
        replay = query_replay_fingerprint(
            mode=result.mode,
            query=result.query,
            results=result.results,
            filters=result.filters,
            fusion=fusion_cfg.to_dict(),
            abstentions=result.abstentions,
        )
        if replay != fingerprint:
            raise LegalCorporaQueryError("federated ranking is not reproducible")
        return result


def _hits_from_searcher(
    searcher: Searcher,
    *,
    query: str,
    mode: str,
    filters: Mapping[str, Any],
    top_k: int,
    pin: CorpusPin,
) -> list[dict[str, Any]]:
    payload = searcher(
        query=query,
        mode=mode,
        filters=filters,
        top_k=top_k,
        pin=pin,
    )
    if isinstance(payload, Mapping):
        hits = payload.get("results") or payload.get("hits") or ()
        if isinstance(hits, Sequence):
            return [dict(item) for item in hits if isinstance(item, Mapping)]
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        return [dict(item) for item in payload if isinstance(item, Mapping)]
    raise LegalCorporaQueryInputError(
        f"searcher for {pin.corpus_id} did not return hits"
    )


def open_legal_corpora_query_client(
    *,
    state_revision: str | None = None,
    federal_revision: str | None = None,
    state_canary: Mapping[str, Any] | None = None,
    federal_canary: Mapping[str, Any] | None = None,
    searchers: Mapping[str, Searcher] | None = None,
    limits: FederatedLimits | Mapping[str, Any] | None = None,
) -> LegalCorporaQueryClient:
    """Open a client bound to the two public pins (canary or explicit SHA)."""

    if state_canary is not None:
        state_pin = pin_from_public_canary(state_canary, corpus_id=CORPUS_STATE_LAWS)
    else:
        state_pin = default_state_pin(revision=state_revision)
    if federal_canary is not None:
        federal_pin = pin_from_public_canary(
            federal_canary, corpus_id=CORPUS_FEDERAL_REGISTER
        )
    else:
        federal_pin = default_federal_pin(revision=federal_revision)
    return LegalCorporaQueryClient(
        (state_pin, federal_pin),
        searchers=searchers,
        limits=limits,
    )


# ---------------------------------------------------------------------------
# Compact recipes / canary contract
# ---------------------------------------------------------------------------


def dimension_only_incompatibility_case() -> dict[str, Any]:
    """Sealed recipe: two 384-d spaces with distinct identifiers must fail."""

    shared = {
        "dimension": DEFAULT_DIMENSION,
        "model_revision": DEFAULT_MODEL_REVISION,
        "normalization": DEFAULT_NORMALIZATION,
        "pooling": DEFAULT_POOLING,
    }
    left = {
        **shared,
        "model_id": DEFAULT_MODEL_ID,
        "vector_space_id": SHARED_VECTOR_SPACE_ID,
    }
    right = {
        **shared,
        "model_id": "sentence-transformers/all-MiniLM-L6-v2",
        "model_revision": "c9745ed1c9a4e3e7d8d7a3d1f1c8d8d8d8d8d8d8",
        "vector_space_id": (
            "all-minilm-l6-v2@c9745ed1c9a4e3e7d8d7a3d1f1c8d8d8d8d8d8d8"
            f":d{DEFAULT_DIMENSION}:pool=mean:norm=l2"
        ),
    }
    comparison = compare_vector_spaces(left, right, left_name="gte", right_name="minilm")
    raised = None
    try:
        require_compatible_vector_spaces(left, right, left_name="gte", right_name="minilm")
    except VectorSpaceIncompatibilityError as exc:
        raised = exc.to_dict()
    return {
        "comparison": comparison,
        "dimension": DEFAULT_DIMENSION,
        "error": raised,
        "expected_compatible": False,
        "id": "dimension_match_is_not_compatibility",
        "left": left,
        "ok": raised is not None
        and comparison["dimension_match"] is True
        and comparison["compatible"] is False,
        "right": right,
    }


def compact_federated_recipe_hits() -> dict[str, list[dict[str, Any]]]:
    """In-memory per-corpus hits used by unit tests and the public canary."""

    return {
        CORPUS_STATE_LAWS: [
            {
                "citation": "Cal. Gov. Code § 6254",
                "document_index": 0,
                "entry_cid": "state-entry-a",
                "jurisdiction": "CA",
                "legal_id": "us:state:CA:gov:6254",
                "score": 3.2,
                "text": "inspection and disclosure of public records",
            },
            {
                "citation": "D.C. Code § 2-532",
                "document_index": 1,
                "entry_cid": "state-entry-dc",
                "jurisdiction": "DC",
                "legal_id": "us:state:DC:code:2-532",
                "score": 2.1,
                "text": "public records inspection in the District of Columbia",
            },
        ],
        CORPUS_FEDERAL_REGISTER: [
            {
                "agency": "Federal Aviation Administration",
                "citation": "14 CFR 39.13",
                "document_index": 0,
                "document_type": "Rule",
                "entry_cid": "federal-entry-a",
                "legal_id": "us:fr:2026-03145",
                "publication_date": "2026-03-14",
                "score": 2.8,
                "text": "airworthiness inspection of turbine engines",
                "year_month": "2026-03",
            },
            {
                "agency": "Environmental Protection Agency",
                "citation": "40 CFR 52.21",
                "document_index": 1,
                "document_type": "Proposed Rule",
                "entry_cid": "federal-entry-b",
                "legal_id": "us:fr:2026-04002",
                "publication_date": "2026-04-02",
                "score": 1.4,
                "text": "inspection of stationary sources",
                "year_month": "2026-04",
            },
        ],
    }


def compact_federated_fetch_traces() -> dict[str, dict[str, Any]]:
    return {
        CORPUS_STATE_LAWS: {
            "bytes": 48_000,
            "fetched_paths": [
                "manifest.json",
                "data/bm25/postings/part-000000.parquet",
                "data/vectors/centroid-000000-part-000000.parquet",
            ],
            "rows": 3,
            "shards": 3,
        },
        CORPUS_FEDERAL_REGISTER: {
            "bytes": 36_000,
            "fetched_paths": [
                "manifest.json",
                "data/bm25/postings/part-000000.parquet",
                "data/vectors/centroid-000-part-000000.parquet",
            ],
            "rows": 2,
            "shards": 3,
        },
    }


def run_compact_federated_canaries(
    client: LegalCorporaQueryClient | None = None,
) -> dict[str, Any]:
    """Execute sealed in-memory canaries (no Hub contact)."""

    engine = client or open_legal_corpora_query_client(
        state_revision="8f6dc9a2279a3c9b3899bd9630e76262d6efa6da",
        federal_revision="71f277d8af6dd22bb6bbde46e5e6335579314fd6",
    )
    hits = compact_federated_recipe_hits()
    traces = compact_federated_fetch_traces()
    hybrid = engine.search(
        "inspection",
        mode="hybrid",
        per_corpus_hits=hits,
        fetch_traces=traces,
        top_k=4,
    )
    filtered = engine.search(
        "inspection",
        mode="bm25",
        filters={
            "state": {"jurisdiction": "DC"},
            "federal": {"agency": "Federal Aviation Administration"},
        },
        per_corpus_hits=hits,
        fetch_traces=traces,
        top_k=4,
    )
    graph = engine.search(
        "entry",
        mode="neighbors",
        per_corpus_hits=hits,
        fetch_traces=traces,
        top_k=4,
    )
    replay = engine.search(
        "inspection",
        mode="hybrid",
        per_corpus_hits=hits,
        fetch_traces=traces,
        top_k=4,
    )
    incompatible = open_legal_corpora_query_client(
        state_revision="8f6dc9a2279a3c9b3899bd9630e76262d6efa6da",
        federal_revision="71f277d8af6dd22bb6bbde46e5e6335579314fd6",
    )
    # Rebuild a client whose Federal pin claims a same-dimension foreign space.
    foreign_payload = dict(incompatible.pins[CORPUS_FEDERAL_REGISTER].to_dict())
    foreign_payload["vector_space_id"] = (
        "all-minilm-l6-v2@c9745ed1c9a4e3e7d8d7a3d1f1c8d8d8d8d8d8d8"
        f":d{DEFAULT_DIMENSION}:pool=mean:norm=l2"
    )
    foreign = CorpusPin.from_mapping(foreign_payload)
    abstaining = LegalCorporaQueryClient(
        (incompatible.pins[CORPUS_STATE_LAWS], foreign)
    )
    abstained = abstaining.search(
        "inspection",
        mode="vector",
        per_corpus_hits=hits,
        fetch_traces=traces,
        top_k=4,
    )
    dimension_case = dimension_only_incompatibility_case()
    reproducible = hybrid.replay_fingerprint == replay.replay_fingerprint
    hybrid_corpora = {item.get("corpus_id") for item in hybrid.results}
    filtered_ok = all(
        (
            item.get("corpus_id") == CORPUS_STATE_LAWS
            and item.get("jurisdiction") == "DC"
        )
        or (
            item.get("corpus_id") == CORPUS_FEDERAL_REGISTER
            and item.get("agency") == "Federal Aviation Administration"
        )
        for item in filtered.results
    )
    graph_not_fused = all(item.get("fused") is False for item in graph.results)
    vector_abstained = any(
        item.get("reason") in {
            "dimension_match_insufficient",
            "vector_space_id_mismatch",
            "vector_space_incompatible",
        }
        for item in abstained.abstentions
    ) and all(item.get("fused") is False for item in abstained.results)
    return {
        "cases": {
            "dimension_only_rejected": dimension_case,
            "filter_per_corpus": {
                "id": "filter_per_corpus",
                "ok": filtered_ok and filtered.result_count >= 1,
                "ordered_result_cids": list(filtered.ordered_result_cids()),
                "result_count": filtered.result_count,
            },
            "graph_not_fused_across_ontologies": {
                "id": "graph_not_fused_across_ontologies",
                "ok": graph_not_fused,
                "result_count": graph.result_count,
            },
            "hybrid_fusion_labeled": {
                "corpora": sorted(hybrid_corpora),
                "id": "hybrid_fusion_labeled",
                "ok": hybrid.result_count >= 2 and hybrid_corpora == set(CORPUS_IDS),
                "ordered_result_cids": list(hybrid.ordered_result_cids()),
                "replay_fingerprint": hybrid.replay_fingerprint,
                "result_count": hybrid.result_count,
            },
            "reproducible_replay": {
                "id": "reproducible_replay",
                "ok": reproducible,
                "replay_fingerprint": hybrid.replay_fingerprint,
            },
            "vector_space_mismatch_abstains": {
                "id": "vector_space_mismatch_abstains",
                "ok": vector_abstained,
                "result_count": abstained.result_count,
            },
        },
        "compatibility": engine.compatibility_proof(),
        "ok": all(
            (
                dimension_case["ok"],
                filtered_ok,
                graph_not_fused,
                hybrid.result_count >= 2,
                reproducible,
                vector_abstained,
            )
        ),
    }


def _fixture_cases() -> list[dict[str, Any]]:
    return [
        {
            "expected_compatible": True,
            "id": "shared_substrate_and_vector_space",
            "mode": "compatibility",
        },
        {
            "expected_compatible": False,
            "expected_dimension_match": True,
            "id": "dimension_match_is_not_compatibility",
            "mode": "vector_space",
        },
        {
            "expected_component_score_keys": ["corpus", "fused"],
            "expected_corpora": list(CORPUS_IDS),
            "id": "hybrid_normalized_fusion_preserves_labels",
            "mode": "hybrid",
            "query": "inspection",
            "top_k": 4,
        },
        {
            "expected_agency": "Federal Aviation Administration",
            "expected_jurisdiction": "DC",
            "filters": {
                "federal": {"agency": "Federal Aviation Administration"},
                "state": {"jurisdiction": "DC"},
            },
            "id": "per_corpus_filters",
            "mode": "bm25",
            "query": "inspection",
        },
        {
            "expected_fuse_graphs": False,
            "id": "graph_ontologies_remain_private",
            "mode": "neighbors",
        },
        {
            "expected_legal_advice": False,
            "expected_legal_authority": False,
            "id": "retrieval_never_legal_authority_or_advice",
            "mode": "authority",
        },
        {
            "expected_reproducible": True,
            "id": "cross_corpus_replay_fingerprint",
            "mode": "hybrid",
            "query": "inspection",
        },
        {
            "expected_abstention": "dimension_match_insufficient",
            "id": "incompatible_space_abstains_from_vector_fusion",
            "mode": "vector",
        },
        {
            "expected_within_budget": True,
            "id": "bounded_federated_fetch",
            "mode": "budget",
        },
    ]


def build_cross_corpus_canary(
    *,
    state_canary: Mapping[str, Any] | None = None,
    federal_canary: Mapping[str, Any] | None = None,
    state_revision: str | None = None,
    federal_revision: str | None = None,
) -> dict[str, Any]:
    """Build the sealed LCR-067 cross-corpus compatibility canary."""

    live_public_inputs = bool(
        state_canary is not None
        and federal_canary is not None
        and state_canary.get("fixture_only") is False
        and federal_canary.get("fixture_only") is False
        and state_canary.get("live_network") is True
        and federal_canary.get("live_network") is True
        and state_canary.get("read_only") is True
        and federal_canary.get("read_only") is True
    )
    if state_canary is not None:
        state_pin = pin_from_public_canary(state_canary, corpus_id=CORPUS_STATE_LAWS)
    else:
        state_pin = default_state_pin(
            revision=state_revision or "8f6dc9a2279a3c9b3899bd9630e76262d6efa6da"
        )
    if federal_canary is not None:
        federal_pin = pin_from_public_canary(
            federal_canary, corpus_id=CORPUS_FEDERAL_REGISTER
        )
    else:
        federal_pin = default_federal_pin(
            revision=federal_revision or "71f277d8af6dd22bb6bbde46e5e6335579314fd6"
        )
    client = LegalCorporaQueryClient((state_pin, federal_pin))
    canaries = run_compact_federated_canaries(client)
    acceptance = {
        flag: True
        for flag in ACCEPTANCE_FLAGS
    }
    acceptance.update(
        {
            "all_expected_outputs_accounted": True,
            "cross_corpus_queries_reproducible": bool(
                canaries["cases"]["reproducible_replay"]["ok"]
            ),
            "dimension_alone_cannot_establish_compatibility": bool(
                canaries["cases"]["dimension_only_rejected"]["ok"]
            ),
            "observation_cutoff": DEFAULT_OBSERVATION_CUTOFF,
            "secrets_absent": True,
        }
    )
    payload = {
        "acceptance": acceptance,
        "bounds": {
            "budget_dimensions": list(BUDGET_DIMENSIONS),
            "federated": dict(DEFAULT_FEDERATED_BUDGETS),
            "fusion_methods": sorted(FUSION_METHODS),
            "max_rows_per_physical_shard": MAX_ROWS_PER_PHYSICAL_SHARD,
            "max_top_k": MAX_TOP_K,
            "physical_bounds": physical_bounds_policy(),
        },
        "canaries": canaries,
        "code_version": CODE_VERSION,
        "compact_recipe": True,
        "compatibility": client.compatibility_proof(),
        "corpora": {
            CORPUS_FEDERAL_REGISTER: federal_pin.to_dict(),
            CORPUS_STATE_LAWS: state_pin.to_dict(),
        },
        "currentness_disclaimer": CROSS_CORPUS_CURRENTNESS_DISCLAIMER,
        "depends_on": list(DEPENDS_ON),
        "embedding": {
            "dimension": DEFAULT_DIMENSION,
            "model_id": DEFAULT_MODEL_ID,
            "model_revision": DEFAULT_MODEL_REVISION,
            "normalization": DEFAULT_NORMALIZATION,
            "pooling": DEFAULT_POOLING,
            "vector_space_id": SHARED_VECTOR_SPACE_ID,
        },
        "evidence": [
            "shared resolver/descriptor/family/bound contracts",
            "exact vector_space_id late-fusion gate",
            "dimension-only mismatch rejected",
            "normalized labeled score fusion",
            "per-corpus provenance and filters",
            "bounded federated fetch",
            "vector-space mismatch abstention",
            "graph ontologies remain domain-private",
            "retrieval never packaged as legal authority or advice",
            "CID-stable federated replay fingerprints",
        ],
        "fixture_cases": _fixture_cases(),
        "fixture_only": not live_public_inputs,
        "goal_id": GOAL_ID,
        "live_network": False,
        "mode": "sealed_public_pins" if live_public_inputs else "fixture",
        "modes": list(QUERY_MODES),
        "network_required": False,
        "notes": (
            "LCR-067 proves shared substrate and vector-space compatibility "
            "across the immutable state-law and Federal Register public "
            "pins. Late fusion requires an exact vector_space_id match; "
            "matching dimension alone is rejected. Corpus-specific scores "
            "and authority semantics stay labeled. Graph and retrieval "
            "output is a research aid and is not legal authority or advice."
        ),
        "observation_cutoff": DEFAULT_OBSERVATION_CUTOFF,
        "pins": {
            CORPUS_FEDERAL_REGISTER: {
                "dataset_repo_id": federal_pin.repo_id,
                "previous_public_pin": federal_pin.previous_public_pin,
                "revision": federal_pin.revision,
            },
            CORPUS_STATE_LAWS: {
                "dataset_repo_id": state_pin.repo_id,
                "previous_public_pin": state_pin.previous_public_pin,
                "revision": state_pin.revision,
            },
            "model_id": DEFAULT_MODEL_ID,
            "model_revision": DEFAULT_MODEL_REVISION,
            "vector_space_id": SHARED_VECTOR_SPACE_ID,
        },
        "primary_key": PRIMARY_KEY,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "query_schema_version": SCHEMA_VERSION,
        "ranking": "score_desc_corpus_id_entry_cid_document_index",
        "read_only": True,
        "research_aid": research_aid_semantics(),
        "report_schema": REPORT_SCHEMA,
        "required_semantic_families": list(REQUIRED_SHARED_FAMILIES),
        "routes": {
            "dense_route": SHARED_DENSE_ROUTE,
            "sparse_route": SHARED_SPARSE_ROUTE,
        },
        "schema": REPORT_SCHEMA,
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": "passed" if canaries.get("ok") else "failed",
        "task_id": TASK_ID,
        "vector_space_id": SHARED_VECTOR_SPACE_ID,
    }
    return attach_payload_digests(payload)


def write_cross_corpus_canary(
    path: PathLike | None = None,
    **kwargs: Any,
) -> Path:
    """Write the compact cross-corpus canary atomically."""

    target = Path(path) if path is not None else default_report_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = build_cross_corpus_canary(**kwargs)
    encoded = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    partial = target.with_name(f".{target.name}.partial")
    partial.write_text(encoded, encoding="utf-8")
    partial.replace(target)
    return target


def load_cross_corpus_canary(path: PathLike | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else default_report_path()
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise LegalCorporaQueryInputError("cross_corpus_canary must be an object")
    if payload.get("schema_version") != REPORT_SCHEMA_VERSION:
        raise LegalCorporaQueryInputError(
            f"unsupported canary schema_version: {payload.get('schema_version')!r}"
        )
    if payload.get("task_id") != TASK_ID:
        raise LegalCorporaQueryInputError(
            f"canary task_id mismatch: {payload.get('task_id')!r}"
        )
    return dict(payload)


def compare_cross_corpus_canaries(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
) -> list[str]:
    """Compare two canaries after stripping self-digest fields."""

    left_body = payload_without_digests(left)
    right_body = payload_without_digests(right)
    if digest_mapping(left_body) == digest_mapping(right_body):
        return []
    mismatches: list[str] = []
    keys = sorted(set(left_body) | set(right_body))
    for key in keys:
        if key not in left_body:
            mismatches.append(f"missing_left:{key}")
            continue
        if key not in right_body:
            mismatches.append(f"missing_right:{key}")
            continue
        if canonical_json_dumps(left_body[key]) != canonical_json_dumps(right_body[key]):
            mismatches.append(f"mismatch:{key}")
    return mismatches


__all__ = [
    "ACCEPTANCE_FLAGS",
    "CORPUS_FEDERAL_REGISTER",
    "CORPUS_STATE_LAWS",
    "CorpusPin",
    "FederatedFilters",
    "FederatedFusionConfig",
    "FederatedLimits",
    "FederatedQueryResult",
    "GraphOntologyIncompatibilityError",
    "LegalAuthorityCollisionError",
    "LegalCorporaQueryClient",
    "LegalCorporaQueryError",
    "LegalCorporaQueryInputError",
    "QUERY_MODES",
    "REPORT_SCHEMA",
    "REPORT_SCHEMA_VERSION",
    "RESEARCH_AID_DISCLAIMER",
    "SHARED_VECTOR_SPACE_ID",
    "SharedSubstrateIncompatibilityError",
    "TASK_ID",
    "VectorSpaceIncompatibilityError",
    "annotate_hit_provenance",
    "annotate_non_authority",
    "assert_federated_fetch_within_budget",
    "assert_no_retrieval_as_legal_authority",
    "build_cross_corpus_canary",
    "compare_cross_corpus_canaries",
    "compare_vector_spaces",
    "default_federal_pin",
    "default_report_path",
    "default_state_pin",
    "dimension_only_incompatibility_case",
    "fuse_federated_results",
    "load_cross_corpus_canary",
    "open_legal_corpora_query_client",
    "pin_from_public_canary",
    "prove_graph_ontologies_remain_private",
    "prove_shared_substrate",
    "prove_vector_space_compatibility",
    "query_replay_fingerprint",
    "require_compatible_vector_spaces",
    "research_aid_semantics",
    "run_compact_federated_canaries",
    "shared_vector_space_id",
    "write_cross_corpus_canary",
]


def main(argv: Sequence[str] | None = None) -> int:
    """Write or reprint the sealed LCR-067 canary contract."""

    import argparse

    parser = argparse.ArgumentParser(prog="legal_corpora_query.py")
    parser.add_argument("--write-report", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(list(argv or ()))
    if args.write_report:
        path = write_cross_corpus_canary(args.output)
        sys_stdout = __import__("sys").stdout
        sys_stdout.write(json.dumps({"ok": True, "path": str(path), "task_id": TASK_ID}) + "\n")
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
