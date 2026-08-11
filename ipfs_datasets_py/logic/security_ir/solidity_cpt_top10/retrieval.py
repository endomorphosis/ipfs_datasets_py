"""Bounded, integrity-bound hybrid GraphRAG over the Solidity CPT security graph.

Retrieval is deliberately separated from authorization and model selection.
Index roots bind the exact graph, ontology, source set, partition shards,
embedding model/revision/tokenizer/dimension, accelerator configuration,
fusion weights, resource bounds, and authority policy.  Queries are evaluated
under a caller-supplied scope and cannot widen partition, license, or
authority.  Embedding depends on an injected :class:`EmbeddingAcceleratorPort`.

Every hit cites source CIDs, remains context-only
(``proof_authority=False``), and never grants execution authority.
Approximate rank affects ordering only.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
import json
import math
import re
import time
from typing import Any, Final, Protocol, runtime_checkable

from ...ir_core.canonical import canonical_json_bytes
from ...ir_core.identity import canonical_identity
from .graph import (
    GRAPH_ONTOLOGY_VERSION,
    GraphEdgeClass,
    GraphNodeType,
    SoliditySecurityGraph,
)
from .schemas import GraphNode, canonical_config_cid


RETRIEVAL_SCHEMA_VERSION: Final = "solidity-cpt-graphrag-retrieval/v1"
RETRIEVAL_CONFIG_SCHEMA_VERSION: Final = "solidity-cpt-graphrag-retrieval-config/v1"
RETRIEVAL_IDENTITY_DOMAIN: Final = "solidity-cpt-security-ir/graphrag-retrieval"
EMBEDDING_MODEL_CONFIG_SCHEMA: Final = "solidity-cpt-embedding-model-config/v1"
AUTHORITY_POLICY_SCHEMA: Final = "solidity-cpt-retrieval-authority-policy/v1"
NO_EMBEDDING_MODEL: Final = "none"
NO_TOKENIZER: Final = "none"
RETRIEVAL_AUTHORITY_CONTEXT: Final = "context_only"

DEFAULT_MAX_SHARDS: Final = 8
DEFAULT_MAX_NODES: Final = 512
DEFAULT_MAX_RESULTS: Final = 25
DEFAULT_MAX_HOPS: Final = 2
DEFAULT_MAX_QUERY_TERMS: Final = 64
DEFAULT_MAX_BYTES: Final = 64 * 1024
DEFAULT_TIMEOUT_MS: Final = 1_000
MAX_MAX_BYTES: Final = 16 * 1024 * 1024
MAX_TIMEOUT_MS: Final = 60_000

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:[-_./:][A-Za-z0-9]+)*")
_GRANT_KEYS = frozenset(
    {
        "allow",
        "allowed",
        "authorized",
        "authorizes_execution",
        "execution_authority",
        "grant",
        "granted",
        "grants_execution_authority",
        "permit",
        "permitted",
        "proof_authority",
        "transaction_authority",
    }
)


class RetrievalError(ValueError):
    """Base class for fail-closed retrieval errors."""


class RetrievalValidationError(RetrievalError):
    """Raised when a query or retrieval record violates the contract."""


class RetrievalIntegrityError(RetrievalError):
    """Raised when graph/index identities or shard contents do not match."""


class RetrievalScopeError(RetrievalError):
    """Raised when a query attempts to cross partition, license, or authority."""


class RetrievalAuthority(str, Enum):
    """The only authority labels admitted to retrieval results."""

    NON_AUTHORITATIVE = "non_authoritative"
    CANDIDATE = "candidate"


@runtime_checkable
class EmbeddingAcceleratorPort(Protocol):
    """Minimal adapter implemented by an existing embedding accelerator.

    Model selection stays outside Security IR; this port only supplies vectors
    for a caller-pinned model/revision/tokenizer binding.
    """

    def embed_query(self, text: str) -> Sequence[float]:
        """Return the vector for one query."""

    def embed_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        """Return vectors in the same order as ``texts``."""


def _clean_text(value: Any, label: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise RetrievalValidationError(f"{label} must be non-empty trimmed text")
    if "\x00" in value or len(value) > maximum:
        raise RetrievalValidationError(f"{label} is not bounded clean text")
    return value


def _optional_text(value: Any, label: str, *, maximum: int = 4096) -> str:
    if value == "":
        return ""
    return _clean_text(value, label, maximum=maximum)


def _positive_int(value: Any, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise RetrievalValidationError(f"{label} must be a positive integer")
    return value


def _non_negative_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise RetrievalValidationError(f"{label} must be a non-negative integer")
    return value


def _bounded_float(value: Any, label: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RetrievalValidationError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or not low <= result <= high:
        raise RetrievalValidationError(
            f"{label} must be finite and between {low} and {high}"
        )
    return result


def _strings(
    value: Any,
    label: str,
    *,
    maximum_items: int = 128,
    maximum_length: int = 512,
) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value, Sequence
    ):
        raise RetrievalValidationError(f"{label} must be a sequence of strings")
    result = tuple(
        sorted(
            (
                _clean_text(item, f"{label} item", maximum=maximum_length)
                for item in value
            ),
            key=lambda item: (item.casefold(), item),
        )
    )
    if len(result) > maximum_items:
        raise RetrievalValidationError(f"{label} exceeds {maximum_items} items")
    if len(result) != len(set(result)):
        raise RetrievalValidationError(f"{label} contains duplicate values")
    return result


def _vector(value: Any, label: str) -> tuple[float, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value, Sequence
    ):
        raise RetrievalValidationError(f"{label} must be a numeric sequence")
    if len(value) > 8192:
        raise RetrievalValidationError(f"{label} exceeds 8192 dimensions")
    result = tuple(
        _bounded_float(item, f"{label} item", -1.0e100, 1.0e100)
        for item in value
    )
    if result and not any(item != 0.0 for item in result):
        raise RetrievalValidationError(f"{label} must not be an all-zero vector")
    return result


def _tokens(value: str) -> frozenset[str]:
    result: set[str] = set()
    for match in _TOKEN_RE.findall(value.casefold()):
        result.add(match)
        result.update(part for part in re.split(r"[-_./:]", match) if part)
    return frozenset(result)


def _identity(value: Mapping[str, Any], suffix: str) -> str:
    return canonical_identity(
        value,
        domain=f"{RETRIEVAL_IDENTITY_DOMAIN}/{suffix}",
        schema_version=RETRIEVAL_SCHEMA_VERSION,
    ).cid


def _strict_fields(
    value: Mapping[str, Any], allowed: frozenset[str], label: str
) -> None:
    if not isinstance(value, Mapping):
        raise RetrievalIntegrityError(f"{label} must be a mapping")
    unknown = sorted(set(value) - allowed)
    missing = sorted(allowed - set(value))
    if unknown or missing:
        detail = []
        if unknown:
            detail.append(f"unknown fields: {', '.join(unknown)}")
        if missing:
            detail.append(f"missing fields: {', '.join(missing)}")
        raise RetrievalIntegrityError(f"{label}: {'; '.join(detail)}")


def _authority(value: Any) -> RetrievalAuthority:
    try:
        return (
            value
            if isinstance(value, RetrievalAuthority)
            else RetrievalAuthority(value)
        )
    except (TypeError, ValueError) as exc:
        raise RetrievalValidationError(
            "retrieval authority must be non_authoritative or candidate"
        ) from exc


def _source_root(source_cids: Sequence[str]) -> str:
    return _identity(
        {"source_cids": list(_strings(source_cids, "source_cids"))},
        "source-root",
    )


def _authority_policy_cid(
    authorities: Sequence[RetrievalAuthority],
) -> str:
    values = tuple(sorted((_authority(item).value for item in authorities)))
    if not values or len(values) != len(set(values)):
        raise RetrievalValidationError(
            "authority policy must be non-empty and unique"
        )
    return canonical_config_cid(
        {
            "allowed_authorities": list(values),
            "grants_execution_authority": False,
            "proof_authority": False,
            "result_authority": RETRIEVAL_AUTHORITY_CONTEXT,
        },
        schema_version=AUTHORITY_POLICY_SCHEMA,
    )


@dataclass(frozen=True, slots=True)
class RetrievalConfig:
    """Hard upper bounds and deterministic fusion settings."""

    max_shards: int = DEFAULT_MAX_SHARDS
    max_nodes: int = DEFAULT_MAX_NODES
    max_results: int = DEFAULT_MAX_RESULTS
    max_hops: int = DEFAULT_MAX_HOPS
    max_query_terms: int = DEFAULT_MAX_QUERY_TERMS
    max_bytes: int = DEFAULT_MAX_BYTES
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    lexical_weight: float = 0.50
    vector_weight: float = 0.30
    graph_weight: float = 0.20
    schema_version: str = RETRIEVAL_CONFIG_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in (
            "max_shards",
            "max_nodes",
            "max_results",
            "max_hops",
            "max_query_terms",
            "max_bytes",
            "timeout_ms",
        ):
            _positive_int(getattr(self, name), name)
        if self.max_bytes > MAX_MAX_BYTES:
            raise RetrievalValidationError(
                f"max_bytes cannot exceed {MAX_MAX_BYTES}"
            )
        if self.timeout_ms > MAX_TIMEOUT_MS:
            raise RetrievalValidationError(
                f"timeout_ms cannot exceed {MAX_TIMEOUT_MS}"
            )
        weights = tuple(
            _bounded_float(getattr(self, name), name, 0.0, 1.0)
            for name in ("lexical_weight", "vector_weight", "graph_weight")
        )
        if not math.isclose(sum(weights), 1.0, abs_tol=1e-12):
            raise RetrievalValidationError("retrieval weights must sum to 1")
        if self.schema_version != RETRIEVAL_CONFIG_SCHEMA_VERSION:
            raise RetrievalValidationError("unsupported retrieval config schema")

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_weight": self.graph_weight,
            "lexical_weight": self.lexical_weight,
            "max_bytes": self.max_bytes,
            "max_hops": self.max_hops,
            "max_nodes": self.max_nodes,
            "max_query_terms": self.max_query_terms,
            "max_results": self.max_results,
            "max_shards": self.max_shards,
            "schema_version": self.schema_version,
            "timeout_ms": self.timeout_ms,
            "vector_weight": self.vector_weight,
        }

    @property
    def cid(self) -> str:
        return canonical_config_cid(
            self.to_dict(), schema_version=self.schema_version
        )


@dataclass(frozen=True, slots=True)
class RetrievalEntry:
    """One compact searchable projection; never an authorization record."""

    node_cid: str
    partition: str
    shard_key: str
    kind: str
    text: str
    source_cids: tuple[str, ...]
    authority: RetrievalAuthority = RetrievalAuthority.NON_AUTHORITATIVE
    licenses: tuple[str, ...] = ()
    node_types: tuple[str, ...] = ()
    contracts: tuple[str, ...] = ()
    security_concepts: tuple[str, ...] = ()
    compilers: tuple[str, ...] = ()
    paths: tuple[str, ...] = ()
    embedding: tuple[float, ...] = ()
    graph_node: bool = True
    entry_id: str = ""
    grants_execution_authority: bool = False
    proof_authority: bool = False

    def __post_init__(self) -> None:
        for name in ("node_cid", "partition", "shard_key", "kind"):
            object.__setattr__(
                self, name, _clean_text(getattr(self, name), name, maximum=512)
            )
        object.__setattr__(self, "text", _optional_text(self.text, "text"))
        object.__setattr__(
            self, "source_cids", _strings(self.source_cids, "source_cids")
        )
        if not self.source_cids:
            raise RetrievalValidationError("source_cids must not be empty")
        object.__setattr__(self, "authority", _authority(self.authority))
        for name in (
            "licenses",
            "node_types",
            "contracts",
            "security_concepts",
            "compilers",
            "paths",
        ):
            object.__setattr__(self, name, _strings(getattr(self, name), name))
        object.__setattr__(self, "embedding", _vector(self.embedding, "embedding"))
        if type(self.graph_node) is not bool:
            raise RetrievalValidationError("graph_node must be a boolean")
        if self.grants_execution_authority is not False:
            raise RetrievalValidationError(
                "retrieval entries can never grant execution authority"
            )
        if self.proof_authority is not False:
            raise RetrievalValidationError(
                "retrieval entries can never have proof authority"
            )
        computed = _identity(self.deterministic_dict(), "entry")
        if self.entry_id and self.entry_id != computed:
            raise RetrievalIntegrityError(
                "entry_id does not match retrieval entry content"
            )
        object.__setattr__(self, "entry_id", computed)

    def deterministic_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority.value,
            "compilers": list(self.compilers),
            "contracts": list(self.contracts),
            "embedding": list(self.embedding),
            "grants_execution_authority": False,
            "graph_node": self.graph_node,
            "kind": self.kind,
            "licenses": list(self.licenses),
            "node_cid": self.node_cid,
            "node_types": list(self.node_types),
            "partition": self.partition,
            "paths": list(self.paths),
            "proof_authority": False,
            "security_concepts": list(self.security_concepts),
            "shard_key": self.shard_key,
            "source_cids": list(self.source_cids),
            "text": self.text,
        }

    def to_dict(self) -> dict[str, Any]:
        return {"entry_id": self.entry_id, **self.deterministic_dict()}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RetrievalEntry":
        allowed = frozenset(
            {
                "authority",
                "compilers",
                "contracts",
                "embedding",
                "entry_id",
                "grants_execution_authority",
                "graph_node",
                "kind",
                "licenses",
                "node_cid",
                "node_types",
                "partition",
                "paths",
                "proof_authority",
                "security_concepts",
                "shard_key",
                "source_cids",
                "text",
            }
        )
        _strict_fields(value, allowed, "retrieval entry")
        try:
            return cls(
                authority=value["authority"],
                compilers=tuple(value["compilers"]),
                contracts=tuple(value["contracts"]),
                embedding=tuple(value["embedding"]),
                entry_id=value["entry_id"],
                grants_execution_authority=value["grants_execution_authority"],
                graph_node=value["graph_node"],
                kind=value["kind"],
                licenses=tuple(value["licenses"]),
                node_cid=value["node_cid"],
                node_types=tuple(value["node_types"]),
                partition=value["partition"],
                paths=tuple(value["paths"]),
                proof_authority=value["proof_authority"],
                security_concepts=tuple(value["security_concepts"]),
                shard_key=value["shard_key"],
                source_cids=tuple(value["source_cids"]),
                text=value["text"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, RetrievalError):
                raise
            raise RetrievalIntegrityError(f"invalid retrieval entry: {exc}") from exc


@dataclass(frozen=True, slots=True)
class RetrievalShard:
    """A single-partition content-addressed entry shard."""

    shard_id: str
    partition: str
    entries: tuple[RetrievalEntry, ...]
    shard_root: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "shard_id", _clean_text(self.shard_id, "shard_id", maximum=512)
        )
        object.__setattr__(
            self, "partition", _clean_text(self.partition, "partition", maximum=512)
        )
        entries = tuple(sorted(self.entries, key=lambda item: item.entry_id))
        if not entries:
            raise RetrievalValidationError("retrieval shard must not be empty")
        if any(not isinstance(item, RetrievalEntry) for item in entries):
            raise RetrievalValidationError("entries must contain RetrievalEntry")
        if len({item.entry_id for item in entries}) != len(entries):
            raise RetrievalValidationError("retrieval shard has duplicate entries")
        if any(item.partition != self.partition for item in entries):
            raise RetrievalScopeError("retrieval shard crosses data partitions")
        if any(item.shard_key != self.shard_id for item in entries):
            raise RetrievalIntegrityError("entry shard binding mismatch")
        object.__setattr__(self, "entries", entries)
        computed = _identity(
            {
                "entries": [item.to_dict() for item in entries],
                "partition": self.partition,
                "shard_id": self.shard_id,
            },
            "shard",
        )
        if self.shard_root and self.shard_root != computed:
            raise RetrievalIntegrityError(
                "shard_root does not match retrieval shard content"
            )
        object.__setattr__(self, "shard_root", computed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entries": [item.to_dict() for item in self.entries],
            "partition": self.partition,
            "shard_id": self.shard_id,
            "shard_root": self.shard_root,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RetrievalShard":
        _strict_fields(
            value,
            frozenset({"entries", "partition", "shard_id", "shard_root"}),
            "retrieval shard",
        )
        try:
            return cls(
                entries=tuple(
                    RetrievalEntry.from_dict(item) for item in value["entries"]
                ),
                partition=value["partition"],
                shard_id=value["shard_id"],
                shard_root=value["shard_root"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, RetrievalError):
                raise
            raise RetrievalIntegrityError(f"invalid retrieval shard: {exc}") from exc


@dataclass(frozen=True, slots=True)
class RetrievalIndex:
    """Verified shards bound to graph, ontology, source, model, and policy."""

    graph_root: str
    ontology_version: str
    source_root: str
    graph_config_cid: str
    retrieval_config_cid: str
    authority_policy_cid: str
    model_id: str
    model_revision: str
    tokenizer_id: str
    embedding_dimension: int
    model_config_cid: str
    shards: tuple[RetrievalShard, ...]
    index_root: str = ""
    schema_version: str = RETRIEVAL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in (
            "graph_root",
            "ontology_version",
            "source_root",
            "graph_config_cid",
            "retrieval_config_cid",
            "authority_policy_cid",
            "model_id",
            "model_revision",
            "tokenizer_id",
            "model_config_cid",
        ):
            object.__setattr__(
                self, name, _clean_text(getattr(self, name), name, maximum=512)
            )
        object.__setattr__(
            self,
            "embedding_dimension",
            _non_negative_int(self.embedding_dimension, "embedding_dimension"),
        )
        if self.schema_version != RETRIEVAL_SCHEMA_VERSION:
            raise RetrievalIntegrityError("unsupported retrieval index schema")
        shards = tuple(sorted(self.shards, key=lambda item: item.shard_id))
        if any(not isinstance(item, RetrievalShard) for item in shards):
            raise RetrievalValidationError("shards must contain RetrievalShard")
        if len({item.shard_id for item in shards}) != len(shards):
            raise RetrievalIntegrityError("duplicate retrieval shard ID")
        entry_ids = [entry.entry_id for shard in shards for entry in shard.entries]
        if len(entry_ids) != len(set(entry_ids)):
            raise RetrievalIntegrityError("entry appears in multiple shards")
        dimensions = {
            len(entry.embedding)
            for shard in shards
            for entry in shard.entries
            if entry.embedding
        }
        if len(dimensions) > 1:
            raise RetrievalIntegrityError("index embeddings have mixed dimensions")
        has_vectors = bool(dimensions)
        observed_dim = next(iter(dimensions), 0)
        if has_vectors and self.embedding_dimension != observed_dim:
            raise RetrievalIntegrityError(
                "embedding_dimension does not match entry vectors"
            )
        if not has_vectors and self.embedding_dimension != 0:
            raise RetrievalIntegrityError(
                "embedding_dimension must be zero for a lexical-only index"
            )
        no_model = (
            self.model_id
            == self.model_revision
            == self.tokenizer_id
            == NO_EMBEDDING_MODEL
        )
        # tokenizer may use NO_TOKENIZER synonym; normalize check
        no_model = (
            self.model_id == NO_EMBEDDING_MODEL
            and self.model_revision == NO_EMBEDDING_MODEL
            and self.tokenizer_id in {NO_EMBEDDING_MODEL, NO_TOKENIZER}
        )
        if has_vectors and no_model:
            raise RetrievalIntegrityError(
                "vector index must bind an embedding model, revision, and tokenizer"
            )
        if not has_vectors and not no_model:
            raise RetrievalIntegrityError(
                "model binding supplied for an index without vectors"
            )
        object.__setattr__(self, "shards", shards)
        computed = _identity(self.deterministic_dict(), "index")
        if self.index_root and self.index_root != computed:
            raise RetrievalIntegrityError(
                "index_root does not match retrieval index content"
            )
        object.__setattr__(self, "index_root", computed)

    def deterministic_dict(self) -> dict[str, Any]:
        return {
            "authority_policy_cid": self.authority_policy_cid,
            "embedding_dimension": self.embedding_dimension,
            "graph_config_cid": self.graph_config_cid,
            "graph_root": self.graph_root,
            "model_config_cid": self.model_config_cid,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "ontology_version": self.ontology_version,
            "retrieval_config_cid": self.retrieval_config_cid,
            "schema_version": self.schema_version,
            "shards": [item.to_dict() for item in self.shards],
            "source_root": self.source_root,
            "tokenizer_id": self.tokenizer_id,
        }

    def to_dict(self) -> dict[str, Any]:
        return {"index_root": self.index_root, **self.deterministic_dict()}

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def to_json(self) -> str:
        return self.canonical_bytes().decode("utf-8")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RetrievalIndex":
        allowed = frozenset(
            {
                "authority_policy_cid",
                "embedding_dimension",
                "graph_config_cid",
                "graph_root",
                "index_root",
                "model_config_cid",
                "model_id",
                "model_revision",
                "ontology_version",
                "retrieval_config_cid",
                "schema_version",
                "shards",
                "source_root",
                "tokenizer_id",
            }
        )
        _strict_fields(value, allowed, "retrieval index")
        try:
            return cls(
                authority_policy_cid=value["authority_policy_cid"],
                embedding_dimension=value["embedding_dimension"],
                graph_config_cid=value["graph_config_cid"],
                graph_root=value["graph_root"],
                index_root=value["index_root"],
                model_config_cid=value["model_config_cid"],
                model_id=value["model_id"],
                model_revision=value["model_revision"],
                ontology_version=value["ontology_version"],
                retrieval_config_cid=value["retrieval_config_cid"],
                schema_version=value["schema_version"],
                shards=tuple(
                    RetrievalShard.from_dict(item) for item in value["shards"]
                ),
                source_root=value["source_root"],
                tokenizer_id=value["tokenizer_id"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, RetrievalError):
                raise
            raise RetrievalIntegrityError(f"invalid retrieval index: {exc}") from exc

    @classmethod
    def from_json(cls, value: str | bytes | bytearray) -> "RetrievalIndex":
        if not isinstance(value, (str, bytes, bytearray)):
            raise RetrievalIntegrityError(
                "retrieval index JSON must be text or bytes"
            )

        def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, item in items:
                if key in result:
                    raise RetrievalIntegrityError(
                        f"retrieval index JSON contains duplicate field {key!r}"
                    )
                result[key] = item
            return result

        def reject_constant(constant: str) -> None:
            raise RetrievalIntegrityError(
                f"retrieval index JSON contains non-finite number {constant}"
            )

        try:
            decoded = json.loads(
                value, object_pairs_hook=pairs, parse_constant=reject_constant
            )
        except RetrievalError:
            raise
        except (TypeError, ValueError, UnicodeDecodeError) as exc:
            raise RetrievalIntegrityError(
                "retrieval index is not valid JSON"
            ) from exc
        if not isinstance(decoded, Mapping):
            raise RetrievalIntegrityError(
                "retrieval index JSON must contain an object"
            )
        return cls.from_dict(decoded)


@dataclass(frozen=True, slots=True)
class RetrievalScope:
    """Caller-owned scope that query fields are only allowed to narrow."""

    partition: str
    authorities: tuple[RetrievalAuthority, ...] = (
        RetrievalAuthority.NON_AUTHORITATIVE,
    )
    licenses: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "partition", _clean_text(self.partition, "partition", maximum=512)
        )
        if isinstance(self.authorities, (str, bytes, bytearray)):
            raise RetrievalScopeError("authorities must be a sequence")
        values = tuple(
            sorted((_authority(item) for item in self.authorities), key=str)
        )
        if not values or len(values) != len(set(values)):
            raise RetrievalScopeError("authorities must be non-empty and unique")
        object.__setattr__(self, "authorities", values)
        object.__setattr__(
            self, "licenses", _strings(self.licenses, "scope licenses")
        )


@dataclass(frozen=True, slots=True)
class RetrievalQuery:
    """One bounded query with optional exact categorical filters."""

    text: str = ""
    partition: str = ""
    authorities: tuple[RetrievalAuthority, ...] = ()
    licenses: tuple[str, ...] = ()
    node_types: tuple[str, ...] = ()
    contracts: tuple[str, ...] = ()
    security_concepts: tuple[str, ...] = ()
    compilers: tuple[str, ...] = ()
    paths: tuple[str, ...] = ()
    start_node_cids: tuple[str, ...] = ()
    embedding: tuple[float, ...] = ()
    max_shards: int | None = None
    max_nodes: int | None = None
    max_results: int | None = None
    max_hops: int | None = None
    max_bytes: int | None = None
    timeout_ms: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "text", _optional_text(self.text, "text"))
        object.__setattr__(
            self,
            "partition",
            _optional_text(self.partition, "partition", maximum=512),
        )
        if isinstance(self.authorities, (str, bytes, bytearray)):
            raise RetrievalValidationError("authorities must be a sequence")
        authorities = tuple(
            sorted((_authority(item) for item in self.authorities), key=str)
        )
        if len(authorities) != len(set(authorities)):
            raise RetrievalValidationError("authorities contains duplicates")
        object.__setattr__(self, "authorities", authorities)
        for name in (
            "licenses",
            "node_types",
            "contracts",
            "security_concepts",
            "compilers",
            "paths",
            "start_node_cids",
        ):
            object.__setattr__(self, name, _strings(getattr(self, name), name))
        object.__setattr__(self, "embedding", _vector(self.embedding, "embedding"))
        for name in (
            "max_shards",
            "max_nodes",
            "max_results",
            "max_hops",
            "max_bytes",
            "timeout_ms",
        ):
            value = getattr(self, name)
            if value is not None:
                _positive_int(value, name)
        if not any(
            (
                self.text,
                self.licenses,
                self.node_types,
                self.contracts,
                self.security_concepts,
                self.compilers,
                self.paths,
                self.start_node_cids,
                self.embedding,
            )
        ):
            raise RetrievalValidationError("retrieval query must not be empty")


@dataclass(frozen=True, slots=True)
class RetrievalHit:
    """Compact ranked evidence reference with an explicit non-grant contract."""

    entry_id: str
    node_cid: str
    kind: str
    partition: str
    authority: RetrievalAuthority
    source_cids: tuple[str, ...]
    score: float
    lexical_score: float
    vector_score: float
    graph_score: float
    matched_fields: tuple[str, ...]
    graph_path: tuple[str, ...]
    graph_distance: int | None
    proof_authority: bool = False
    authorizes_execution: bool = False
    grants_execution_authority: bool = False
    result_authority: str = RETRIEVAL_AUTHORITY_CONTEXT

    def __post_init__(self) -> None:
        if (
            self.authorizes_execution is not False
            or self.grants_execution_authority is not False
            or self.proof_authority is not False
        ):
            raise RetrievalValidationError("retrieval hits cannot return a grant")
        if self.result_authority != RETRIEVAL_AUTHORITY_CONTEXT:
            raise RetrievalValidationError(
                "retrieval hits must be context_only candidates"
            )
        if not self.source_cids:
            raise RetrievalValidationError("retrieval hits must cite source CIDs")
        object.__setattr__(
            self,
            "graph_path",
            _strings(self.graph_path, "graph_path", maximum_items=64),
        )
        object.__setattr__(
            self, "source_cids", _strings(self.source_cids, "source_cids")
        )
        object.__setattr__(
            self, "matched_fields", _strings(self.matched_fields, "matched_fields")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorizes_execution": False,
            "authority": self.authority.value,
            "entry_id": self.entry_id,
            "grants_execution_authority": False,
            "graph_distance": self.graph_distance,
            "graph_path": list(self.graph_path),
            "graph_score": self.graph_score,
            "kind": self.kind,
            "lexical_score": self.lexical_score,
            "matched_fields": list(self.matched_fields),
            "node_cid": self.node_cid,
            "partition": self.partition,
            "proof_authority": False,
            "result_authority": RETRIEVAL_AUTHORITY_CONTEXT,
            "score": self.score,
            "source_cids": list(self.source_cids),
            "vector_score": self.vector_score,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


@dataclass(frozen=True, slots=True)
class RetrievalResponse:
    """Results plus observable resource use and truncation."""

    index_root: str
    graph_root: str
    ontology_version: str
    source_root: str
    partition: str
    results: tuple[RetrievalHit, ...]
    shards_scanned: int
    nodes_scanned: int
    graph_nodes_visited: int
    bytes_used: int
    truncated_shards: bool
    truncated_nodes: bool
    truncated_results: bool
    truncated_bytes: bool
    timed_out: bool
    authorizes_execution: bool = False
    grants_execution_authority: bool = False
    proof_authority: bool = False
    result_authority: str = RETRIEVAL_AUTHORITY_CONTEXT

    def __post_init__(self) -> None:
        if (
            self.authorizes_execution is not False
            or self.grants_execution_authority is not False
            or self.proof_authority is not False
        ):
            raise RetrievalValidationError(
                "retrieval responses cannot return a grant"
            )
        if self.result_authority != RETRIEVAL_AUTHORITY_CONTEXT:
            raise RetrievalValidationError(
                "retrieval responses must be context_only"
            )
        for hit in self.results:
            if not isinstance(hit, RetrievalHit):
                raise RetrievalValidationError(
                    "results must contain RetrievalHit values"
                )
            if hit.proof_authority is not False:
                raise RetrievalValidationError(
                    "response contains proof-authoritative hit"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorizes_execution": False,
            "bytes_used": self.bytes_used,
            "graph_nodes_visited": self.graph_nodes_visited,
            "graph_root": self.graph_root,
            "grants_execution_authority": False,
            "index_root": self.index_root,
            "nodes_scanned": self.nodes_scanned,
            "ontology_version": self.ontology_version,
            "partition": self.partition,
            "proof_authority": False,
            "result_authority": RETRIEVAL_AUTHORITY_CONTEXT,
            "results": [item.to_dict() for item in self.results],
            "shards_scanned": self.shards_scanned,
            "source_root": self.source_root,
            "timed_out": self.timed_out,
            "truncated_bytes": self.truncated_bytes,
            "truncated_nodes": self.truncated_nodes,
            "truncated_results": self.truncated_results,
            "truncated_shards": self.truncated_shards,
        }


def _payload_values(payload: Mapping[str, Any]) -> tuple[str, ...]:
    values: list[str] = []
    for key, value in sorted(payload.items()):
        if key.casefold() in _GRANT_KEYS:
            continue
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            text = str(value).strip()
            if text:
                values.extend((str(key), text))
        elif isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray)
        ):
            for item in value[:32]:
                if isinstance(item, (str, int, float)) and not isinstance(
                    item, bool
                ):
                    values.append(str(item))
    return tuple(values)


def _categorize_node(node: GraphNode) -> dict[str, tuple[str, ...]]:
    payload = node.payload
    node_type = node.node_type
    licenses: tuple[str, ...] = ()
    contracts: tuple[str, ...] = ()
    security_concepts: tuple[str, ...] = ()
    compilers: tuple[str, ...] = ()
    paths: tuple[str, ...] = ()

    if node_type == GraphNodeType.LICENSE.value:
        predicate = str(payload.get("predicate", "")).strip()
        if predicate.startswith("has_license:"):
            licenses = (predicate.split(":", 1)[1],)
        elif payload.get("license"):
            licenses = (str(payload["license"]),)
        elif predicate:
            licenses = (predicate,)
    if node_type in {
        GraphNodeType.CONTRACT.value,
        GraphNodeType.LIBRARY.value,
        GraphNodeType.INTERFACE.value,
    }:
        name = str(payload.get("name", "")).strip()
        if name:
            contracts = (name,)
    if node_type == GraphNodeType.SECURITY_CONCEPT.value:
        predicate = str(payload.get("predicate", payload.get("name", ""))).strip()
        if predicate:
            security_concepts = (predicate,)
    if node_type == GraphNodeType.COMPILER.value:
        predicate = str(payload.get("predicate", "")).strip()
        if predicate.startswith("has_compiler:"):
            compilers = (predicate.split(":", 1)[1],)
        elif predicate.startswith("pragma:"):
            compilers = (predicate,)
        elif payload.get("compiler"):
            compilers = (str(payload["compiler"]),)
    path = str(payload.get("path", "")).strip()
    if path:
        paths = (path,)

    return {
        "compilers": compilers,
        "contracts": contracts,
        "licenses": licenses,
        "node_types": (node_type,),
        "paths": paths,
        "security_concepts": security_concepts,
    }


def graph_entries(
    graph: SoliditySecurityGraph,
    *,
    partition_by_node: Mapping[str, str],
    shard_count: int = 8,
) -> tuple[RetrievalEntry, ...]:
    """Project verified graph nodes into deterministic partitioned shards."""

    if not isinstance(graph, SoliditySecurityGraph):
        raise RetrievalValidationError("graph must be SoliditySecurityGraph")
    _positive_int(shard_count, "shard_count")
    if not isinstance(partition_by_node, Mapping):
        raise RetrievalScopeError("partition_by_node must be a mapping")
    node_ids = {node.cid for node in graph.nodes}
    if set(partition_by_node) != node_ids:
        raise RetrievalScopeError(
            "partition_by_node must bind every and only graph node"
        )
    entries: list[RetrievalEntry] = []
    for node in graph.nodes:
        partition = _clean_text(
            partition_by_node[node.cid], f"partition for {node.cid}", maximum=512
        )
        bucket = int(node.cid[-8:].encode("ascii").hex(), 16) % shard_count
        shard_key = f"{partition}:{bucket:04d}"
        values = _payload_values(node.payload)
        categories = _categorize_node(node)
        entries.append(
            RetrievalEntry(
                node_cid=node.cid,
                partition=partition,
                shard_key=shard_key,
                kind=node.node_type,
                text=" ".join((node.node_type, *values))[:4096],
                source_cids=node.source_cids,
                authority=RetrievalAuthority(node.authority.value),
                **categories,
            )
        )
    return tuple(sorted(entries, key=lambda item: item.entry_id))


def build_retrieval_index(
    graph: SoliditySecurityGraph,
    *,
    partition_by_node: Mapping[str, str],
    config: RetrievalConfig | None = None,
    shard_count: int = 8,
    extra_entries: Sequence[RetrievalEntry] = (),
    embedding_port: EmbeddingAcceleratorPort | None = None,
    model_id: str = NO_EMBEDDING_MODEL,
    model_revision: str = NO_EMBEDDING_MODEL,
    tokenizer_id: str = NO_TOKENIZER,
    model_config: Mapping[str, Any] | None = None,
    authority_policy: Sequence[RetrievalAuthority] | None = None,
) -> RetrievalIndex:
    """Build an index bound to the supplied graph and optional accelerator."""

    config = config or RetrievalConfig()
    if not isinstance(config, RetrievalConfig):
        raise RetrievalValidationError("config must be RetrievalConfig")
    entries = list(
        graph_entries(
            graph, partition_by_node=partition_by_node, shard_count=shard_count
        )
    )
    if isinstance(extra_entries, (str, bytes, bytearray)) or not isinstance(
        extra_entries, Sequence
    ):
        raise RetrievalValidationError("extra_entries must be a sequence")
    if any(not isinstance(item, RetrievalEntry) for item in extra_entries):
        raise RetrievalValidationError(
            "extra_entries must contain RetrievalEntry"
        )
    entries.extend(extra_entries)
    if len({item.entry_id for item in entries}) != len(entries):
        raise RetrievalValidationError("duplicate retrieval entry")

    if embedding_port is not None:
        model_id = _clean_text(model_id, "model_id", maximum=512)
        model_revision = _clean_text(model_revision, "model_revision", maximum=512)
        tokenizer_id = _clean_text(tokenizer_id, "tokenizer_id", maximum=512)
        if (
            model_id == NO_EMBEDDING_MODEL
            or model_revision == NO_EMBEDDING_MODEL
            or tokenizer_id in {NO_EMBEDDING_MODEL, NO_TOKENIZER}
        ):
            raise RetrievalValidationError(
                "embedding model_id, revision, and tokenizer must be pinned"
            )
        try:
            vectors = tuple(
                embedding_port.embed_documents([item.text for item in entries])
            )
        except Exception as exc:
            raise RetrievalValidationError(
                f"embedding accelerator failed closed: {type(exc).__name__}: {exc}"
            ) from exc
        if len(vectors) != len(entries):
            raise RetrievalValidationError(
                "embedding accelerator returned the wrong vector count"
            )
        embedded: list[RetrievalEntry] = []
        for entry, vector in zip(entries, vectors, strict=True):
            values = entry.to_dict()
            values.pop("entry_id")
            values["embedding"] = list(
                _vector(vector, "embedding accelerator vector")
            )
            embedded.append(RetrievalEntry.from_dict({"entry_id": "", **values}))
        entries = embedded
        dimension = len(entries[0].embedding) if entries else 0
        model_config = dict(model_config or {})
        model_config.setdefault("dimensions", dimension)
        model_config.setdefault("tokenizer_id", tokenizer_id)
        model_config_cid = canonical_config_cid(
            model_config,
            schema_version=EMBEDDING_MODEL_CONFIG_SCHEMA,
        )
    else:
        if (
            model_id != NO_EMBEDDING_MODEL
            or model_revision != NO_EMBEDDING_MODEL
            or (
                tokenizer_id not in {NO_EMBEDDING_MODEL, NO_TOKENIZER}
            )
        ):
            raise RetrievalValidationError(
                "model binding requires an embedding accelerator"
            )
        if any(item.embedding for item in entries):
            raise RetrievalValidationError(
                "precomputed vectors require an embedding accelerator binding"
            )
        tokenizer_id = NO_TOKENIZER
        dimension = 0
        model_config_cid = canonical_config_cid(
            {
                "model": NO_EMBEDDING_MODEL,
                "tokenizer_id": NO_TOKENIZER,
                "dimensions": 0,
            },
            schema_version=EMBEDDING_MODEL_CONFIG_SCHEMA,
        )

    policy = authority_policy or (RetrievalAuthority.NON_AUTHORITATIVE,)
    authority_policy_cid = _authority_policy_cid(policy)

    by_shard: dict[tuple[str, str], list[RetrievalEntry]] = {}
    for entry in entries:
        by_shard.setdefault((entry.partition, entry.shard_key), []).append(entry)
    shards = tuple(
        RetrievalShard(shard_id=shard_id, partition=partition, entries=tuple(items))
        for (partition, shard_id), items in sorted(by_shard.items())
    )
    return RetrievalIndex(
        graph_root=graph.graph_root,
        ontology_version=graph.ontology_version,
        source_root=_source_root(graph.source_cids),
        graph_config_cid=graph.config_cid,
        retrieval_config_cid=config.cid,
        authority_policy_cid=authority_policy_cid,
        model_id=model_id,
        model_revision=model_revision,
        tokenizer_id=tokenizer_id,
        embedding_dimension=dimension,
        model_config_cid=model_config_cid,
        shards=shards,
    )


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        raise RetrievalValidationError("query/index embedding dimensions differ")
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(item * item for item in left))
    right_norm = math.sqrt(sum(item * item for item in right))
    if left_norm == 0.0 or right_norm == 0.0:
        raise RetrievalValidationError("cosine vectors must have non-zero norms")
    return max(0.0, min(1.0, (numerator / (left_norm * right_norm) + 1.0) / 2.0))


def _matches_filter(required: tuple[str, ...], actual: tuple[str, ...]) -> bool:
    return not required or bool(
        {item.casefold() for item in required}
        & {item.casefold() for item in actual}
    )


class SolidityGraphRetriever:
    """Verify and query one immutable Solidity graph/index pair.

    Approximate ranking never widens partition, license, authority, or
    execution scope.  Graph-neighborhood scoring validates every edge endpoint
    against the bound adjacency tables before admitting a path.
    """

    def __init__(
        self,
        graph: SoliditySecurityGraph,
        index: RetrievalIndex,
        *,
        config: RetrievalConfig | None = None,
        embedding_port: EmbeddingAcceleratorPort | None = None,
        monotonic: Any = time.monotonic,
    ) -> None:
        self.graph = graph
        self.index = index
        self.config = config or RetrievalConfig()
        self.embedding_port = embedding_port
        if not callable(monotonic):
            raise TypeError("monotonic must be callable")
        self._monotonic = monotonic
        self._verify_bindings()

    def _verify_bindings(self) -> None:
        if not isinstance(self.graph, SoliditySecurityGraph):
            raise RetrievalIntegrityError(
                "graph must be a verified SoliditySecurityGraph"
            )
        if not isinstance(self.index, RetrievalIndex):
            raise RetrievalIntegrityError("index must be RetrievalIndex")
        if self.index.graph_root != self.graph.graph_root:
            raise RetrievalIntegrityError("retrieval index graph root mismatch")
        if self.index.ontology_version != self.graph.ontology_version:
            raise RetrievalIntegrityError(
                "retrieval index ontology version mismatch"
            )
        if self.index.ontology_version != GRAPH_ONTOLOGY_VERSION:
            raise RetrievalIntegrityError("unsupported graph ontology version")
        if self.index.source_root != _source_root(self.graph.source_cids):
            raise RetrievalIntegrityError("retrieval index source root mismatch")
        if self.index.graph_config_cid != self.graph.config_cid:
            raise RetrievalIntegrityError(
                "retrieval index graph config mismatch"
            )
        if self.index.retrieval_config_cid != self.config.cid:
            raise RetrievalIntegrityError("retrieval index config mismatch")
        graph_nodes = {item.cid for item in self.graph.nodes}
        edge_by_id = {item.cid: item for item in self.graph.edges}
        for shard in self.index.shards:
            for entry in shard.entries:
                if entry.graph_node and entry.node_cid not in graph_nodes:
                    raise RetrievalIntegrityError(
                        "retrieval entry references an unknown graph node"
                    )
                if entry.graph_node:
                    node = next(
                        item
                        for item in self.graph.nodes
                        if item.cid == entry.node_cid
                    )
                    if set(entry.source_cids) - set(node.source_cids):
                        raise RetrievalIntegrityError(
                            "entry source_cids must be a subset of graph node sources"
                        )
        # Graph-edge validation: every adjacency edge must resolve and match
        # the endpoint tables stored on the graph.
        for node_cid, edge_ids in self.graph.outgoing.items():
            for edge_id in edge_ids:
                edge = edge_by_id.get(edge_id)
                if edge is None:
                    raise RetrievalIntegrityError(
                        "outgoing adjacency references unknown edge"
                    )
                if edge.source_node_cid != node_cid:
                    raise RetrievalIntegrityError(
                        "outgoing adjacency edge endpoint mismatch"
                    )
                if edge.target_node_cid not in graph_nodes:
                    raise RetrievalIntegrityError(
                        "edge target is not present in the bound graph"
                    )
                # Reject grant-like edge payloads at retrieval time.
                payload = edge.payload
                if payload.get("grants_execution_authority") is not False:
                    raise RetrievalIntegrityError(
                        "graph edge grants execution authority"
                    )
                if payload.get("proof_authority") is True:
                    raise RetrievalIntegrityError(
                        "graph edge claims proof authority"
                    )
                edge_class = payload.get("edge_class")
                if edge_class == GraphEdgeClass.SIMILARITY.value and (
                    payload.get("authority")
                    not in {None, "non_authoritative", "candidate"}
                    or payload.get("authoritative") is True
                ):
                    raise RetrievalIntegrityError(
                        "similarity edge cannot be authoritative"
                    )
        for node_cid, edge_ids in self.graph.incoming.items():
            for edge_id in edge_ids:
                edge = edge_by_id.get(edge_id)
                if edge is None or edge.target_node_cid != node_cid:
                    raise RetrievalIntegrityError(
                        "incoming adjacency edge endpoint mismatch"
                    )

    def _limits(
        self, query: RetrievalQuery
    ) -> tuple[int, int, int, int, int, int]:
        values = []
        for name in (
            "max_shards",
            "max_nodes",
            "max_results",
            "max_hops",
            "max_bytes",
            "timeout_ms",
        ):
            requested = getattr(query, name)
            ceiling = getattr(self.config, name)
            if requested is not None and requested > ceiling:
                raise RetrievalValidationError(
                    f"{name} exceeds configured ceiling {ceiling}"
                )
            values.append(requested or ceiling)
        return tuple(values)  # type: ignore[return-value]

    def _distances(
        self,
        starts: tuple[str, ...],
        *,
        max_hops: int,
        max_nodes: int,
        deadline: float,
    ) -> tuple[dict[str, int], dict[str, tuple[str, ...]], int, bool, bool]:
        if not starts:
            return {}, {}, 0, False, False
        node_ids = {item.cid for item in self.graph.nodes}
        unknown = sorted(set(starts) - node_ids)
        if unknown:
            raise RetrievalValidationError(
                "start_node_cids contains unknown node"
            )
        edge_by_id = {item.cid: item for item in self.graph.edges}
        distances = {item: 0 for item in starts}
        paths: dict[str, tuple[str, ...]] = {item: (item,) for item in starts}
        queue = deque(sorted(starts))
        visited = 0
        truncated = False
        timed_out = False
        while queue:
            if self._monotonic() >= deadline:
                timed_out = True
                break
            node_id = queue.popleft()
            if visited >= max_nodes:
                truncated = True
                break
            visited += 1
            distance = distances[node_id]
            if distance >= max_hops:
                continue
            edge_ids = tuple(self.graph.outgoing[node_id]) + tuple(
                self.graph.incoming[node_id]
            )
            for edge_id in sorted(set(edge_ids)):
                edge = edge_by_id.get(edge_id)
                if edge is None:
                    raise RetrievalIntegrityError(
                        "graph adjacency references missing edge"
                    )
                if edge.source_node_cid == node_id:
                    neighbor = edge.target_node_cid
                elif edge.target_node_cid == node_id:
                    neighbor = edge.source_node_cid
                else:
                    raise RetrievalIntegrityError(
                        "graph edge does not match adjacency endpoint"
                    )
                if neighbor not in node_ids:
                    raise RetrievalIntegrityError(
                        "graph edge neighbor missing from graph"
                    )
                if neighbor not in distances:
                    distances[neighbor] = distance + 1
                    paths[neighbor] = (*paths[node_id], edge_id, neighbor)
                    queue.append(neighbor)
        return distances, paths, visited, truncated, timed_out

    def retrieve(
        self, query: RetrievalQuery, *, scope: RetrievalScope
    ) -> RetrievalResponse:
        """Execute one query, failing closed on any binding or scope mismatch."""

        if not isinstance(query, RetrievalQuery):
            raise RetrievalValidationError("query must be RetrievalQuery")
        if not isinstance(scope, RetrievalScope):
            raise RetrievalScopeError("scope must be RetrievalScope")
        self._verify_bindings()
        partition = query.partition or scope.partition
        if partition != scope.partition:
            raise RetrievalScopeError("query cannot cross the caller partition")
        requested_authorities = query.authorities or scope.authorities
        if not set(requested_authorities) <= set(scope.authorities):
            raise RetrievalScopeError("query cannot broaden caller authority")
        requested_licenses = query.licenses or scope.licenses
        if scope.licenses and query.licenses:
            if not set(item.casefold() for item in query.licenses) <= set(
                item.casefold() for item in scope.licenses
            ):
                raise RetrievalScopeError(
                    "query cannot broaden caller license scope"
                )
        if scope.licenses and not requested_licenses:
            requested_licenses = scope.licenses

        (
            max_shards,
            max_nodes,
            max_results,
            max_hops,
            max_bytes,
            timeout_ms,
        ) = self._limits(query)
        deadline = self._monotonic() + (timeout_ms / 1000.0)
        query_tokens = _tokens(query.text)
        if len(query_tokens) > self.config.max_query_terms:
            raise RetrievalValidationError("query exceeds max_query_terms")
        query_vector = query.embedding
        if not query_vector and self.index.embedding_dimension:
            if self.embedding_port is None:
                raise RetrievalValidationError(
                    "vector index requires its bound embedding accelerator"
                )
            try:
                query_vector = _vector(
                    self.embedding_port.embed_query(query.text),
                    "embedding accelerator query vector",
                )
            except RetrievalError:
                raise
            except Exception as exc:
                raise RetrievalValidationError(
                    f"embedding accelerator failed closed: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc
        if query_vector and not self.index.embedding_dimension:
            raise RetrievalValidationError(
                "query vector supplied to lexical-only index"
            )
        if (
            query_vector
            and len(query_vector) != self.index.embedding_dimension
        ):
            raise RetrievalValidationError(
                "query/index embedding dimensions differ"
            )

        eligible_shards = [
            item for item in self.index.shards if item.partition == partition
        ]
        selected_shards = eligible_shards[:max_shards]
        truncated_shards = len(eligible_shards) > len(selected_shards)
        distances, paths, graph_visited, graph_truncated, graph_timed_out = (
            self._distances(
                query.start_node_cids,
                max_hops=max_hops,
                max_nodes=max_nodes,
                deadline=deadline,
            )
        )

        candidates: list[RetrievalHit] = []
        nodes_scanned = 0
        truncated_nodes = graph_truncated
        timed_out = graph_timed_out
        filters = {
            "compilers": query.compilers,
            "contracts": query.contracts,
            "licenses": requested_licenses,
            "node_types": query.node_types,
            "paths": query.paths,
            "security_concepts": query.security_concepts,
        }
        for shard in selected_shards:
            if self._monotonic() >= deadline:
                timed_out = True
                break
            for entry in shard.entries:
                if self._monotonic() >= deadline:
                    timed_out = True
                    break
                if nodes_scanned >= max_nodes:
                    truncated_nodes = True
                    break
                nodes_scanned += 1
                if entry.authority not in requested_authorities:
                    continue
                if any(
                    not _matches_filter(required, getattr(entry, name))
                    for name, required in filters.items()
                ):
                    continue
                if query.start_node_cids and entry.node_cid not in distances:
                    continue
                entry_tokens = _tokens(
                    " ".join(
                        (
                            entry.text,
                            *entry.licenses,
                            *entry.node_types,
                            *entry.contracts,
                            *entry.security_concepts,
                            *entry.compilers,
                            *entry.paths,
                        )
                    )
                )
                lexical = (
                    len(query_tokens & entry_tokens) / len(query_tokens)
                    if query_tokens
                    else 0.0
                )
                vector = (
                    _cosine(query_vector, entry.embedding)
                    if query_vector and entry.embedding
                    else 0.0
                )
                distance = distances.get(entry.node_cid)
                graph_score = (
                    1.0 / (1.0 + distance) if distance is not None else 0.0
                )
                matched = tuple(
                    sorted(
                        name
                        for name, required in filters.items()
                        if required
                        and _matches_filter(required, getattr(entry, name))
                    )
                )
                if lexical == vector == graph_score == 0.0 and not matched:
                    continue
                # Rank is approximate; it never becomes authority.
                score = (
                    lexical * self.config.lexical_weight
                    + vector * self.config.vector_weight
                    + graph_score * self.config.graph_weight
                )
                candidates.append(
                    RetrievalHit(
                        entry_id=entry.entry_id,
                        node_cid=entry.node_cid,
                        kind=entry.kind,
                        partition=entry.partition,
                        authority=entry.authority,
                        source_cids=entry.source_cids,
                        score=round(score, 12),
                        lexical_score=round(lexical, 12),
                        vector_score=round(vector, 12),
                        graph_score=round(graph_score, 12),
                        matched_fields=matched,
                        graph_path=paths.get(entry.node_cid, ()),
                        graph_distance=distance,
                    )
                )
            if nodes_scanned >= max_nodes or timed_out:
                break

        candidates.sort(key=lambda item: (-item.score, item.entry_id))
        selected: list[RetrievalHit] = []
        bytes_used = 0
        truncated_bytes = False
        for hit in candidates:
            if len(selected) >= max_results:
                break
            item_bytes = len(hit.canonical_bytes())
            if bytes_used + item_bytes > max_bytes:
                truncated_bytes = True
                break
            selected.append(hit)
            bytes_used += item_bytes

        return RetrievalResponse(
            index_root=self.index.index_root,
            graph_root=self.graph.graph_root,
            ontology_version=self.graph.ontology_version,
            source_root=self.index.source_root,
            partition=partition,
            results=tuple(selected),
            shards_scanned=len(selected_shards),
            nodes_scanned=nodes_scanned,
            graph_nodes_visited=graph_visited,
            bytes_used=bytes_used,
            truncated_shards=truncated_shards,
            truncated_nodes=truncated_nodes,
            truncated_results=len(candidates) > len(selected),
            truncated_bytes=truncated_bytes,
            timed_out=timed_out,
        )


# Compatibility alias for callers that use the CVEfixes-style name.
BoundedHybridRetriever = SolidityGraphRetriever


def retrieve_solidity_cpt(
    graph: SoliditySecurityGraph,
    index: RetrievalIndex,
    query: RetrievalQuery,
    *,
    scope: RetrievalScope,
    config: RetrievalConfig | None = None,
    embedding_port: EmbeddingAcceleratorPort | None = None,
) -> RetrievalResponse:
    """Convenience wrapper around :class:`SolidityGraphRetriever`."""

    return SolidityGraphRetriever(
        graph, index, config=config, embedding_port=embedding_port
    ).retrieve(query, scope=scope)


__all__ = [
    "AUTHORITY_POLICY_SCHEMA",
    "BoundedHybridRetriever",
    "DEFAULT_MAX_BYTES",
    "DEFAULT_TIMEOUT_MS",
    "EMBEDDING_MODEL_CONFIG_SCHEMA",
    "EmbeddingAcceleratorPort",
    "NO_EMBEDDING_MODEL",
    "NO_TOKENIZER",
    "RETRIEVAL_AUTHORITY_CONTEXT",
    "RETRIEVAL_CONFIG_SCHEMA_VERSION",
    "RETRIEVAL_SCHEMA_VERSION",
    "RetrievalAuthority",
    "RetrievalConfig",
    "RetrievalEntry",
    "RetrievalError",
    "RetrievalHit",
    "RetrievalIndex",
    "RetrievalIntegrityError",
    "RetrievalQuery",
    "RetrievalResponse",
    "RetrievalScope",
    "RetrievalScopeError",
    "RetrievalShard",
    "RetrievalValidationError",
    "SolidityGraphRetriever",
    "build_retrieval_index",
    "graph_entries",
    "retrieve_solidity_cpt",
]
