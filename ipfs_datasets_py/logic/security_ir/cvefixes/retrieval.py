"""Bounded, integrity-bound hybrid retrieval over the CVEfixes graph.

Retrieval is deliberately separated from authorization.  The index contains
only compact, non-granting projections, every shard is content addressed, and
the index root binds the exact graph, retrieval configuration, and embedding
model configuration.  A query must name exactly one data partition and is
evaluated under a caller-supplied authority scope; neither query filters nor
approximate similarity can widen that scope.

The embedding dependency is an injected port.  This keeps accelerator/model
selection outside this module while retaining an exact model/config binding in
the persisted index.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import math
import re
from typing import Any, Final, Protocol, runtime_checkable

from ...ir_core.canonical import canonical_json_bytes
from ...ir_core.identity import canonical_identity
from .graph import CVEfixesGraph
from .schemas import GraphNode, canonical_config_cid


RETRIEVAL_SCHEMA_VERSION: Final = "cvefixes-graphrag-retrieval/v1"
RETRIEVAL_CONFIG_SCHEMA_VERSION: Final = "cvefixes-graphrag-retrieval-config/v1"
RETRIEVAL_IDENTITY_DOMAIN: Final = "cvefixes-security-ir/graphrag-retrieval"
NO_EMBEDDING_MODEL: Final = "none"
RETRIEVAL_MAX_LIST_ITEMS: Final = 128
RETRIEVAL_MAX_LIST_ITEM_LENGTH: Final = 512
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
    }
)


class RetrievalError(ValueError):
    """Base class for fail-closed retrieval errors."""


class RetrievalValidationError(RetrievalError):
    """Raised when a query or retrieval record violates the contract."""


class RetrievalIntegrityError(RetrievalError):
    """Raised when graph/index identities or shard contents do not match."""


class RetrievalScopeError(RetrievalError):
    """Raised when a query attempts to cross a partition or authority scope."""


class RetrievalAuthority(str, Enum):
    """The only authority labels admitted to retrieval results."""

    NON_AUTHORITATIVE = "non_authoritative"
    CANDIDATE = "candidate"


@runtime_checkable
class EmbeddingAcceleratorPort(Protocol):
    """Minimal adapter implemented by an existing embedding accelerator."""

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
    maximum_items: int = RETRIEVAL_MAX_LIST_ITEMS,
    maximum_length: int = RETRIEVAL_MAX_LIST_ITEM_LENGTH,
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


@dataclass(frozen=True, slots=True)
class RetrievalConfig:
    """Hard upper bounds and deterministic fusion settings."""

    max_shards: int = 8
    max_nodes: int = 512
    max_results: int = 25
    max_hops: int = 2
    max_query_terms: int = 64
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
        ):
            _positive_int(getattr(self, name), name)
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
            "max_hops": self.max_hops,
            "max_nodes": self.max_nodes,
            "max_query_terms": self.max_query_terms,
            "max_results": self.max_results,
            "max_shards": self.max_shards,
            "schema_version": self.schema_version,
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
    cwes: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    code_facts: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()
    effects: tuple[str, ...] = ()
    policies: tuple[str, ...] = ()
    embedding: tuple[float, ...] = ()
    graph_node: bool = True
    entry_id: str = ""
    grants_execution_authority: bool = False

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
            "cwes",
            "languages",
            "code_facts",
            "actions",
            "effects",
            "policies",
        ):
            object.__setattr__(self, name, _strings(getattr(self, name), name))
        object.__setattr__(self, "embedding", _vector(self.embedding, "embedding"))
        if type(self.graph_node) is not bool:
            raise RetrievalValidationError("graph_node must be a boolean")
        if self.grants_execution_authority is not False:
            raise RetrievalValidationError(
                "retrieval entries can never grant execution authority"
            )
        computed = _identity(self.deterministic_dict(), "entry")
        if self.entry_id and self.entry_id != computed:
            raise RetrievalIntegrityError(
                "entry_id does not match retrieval entry content"
            )
        object.__setattr__(self, "entry_id", computed)

    def deterministic_dict(self) -> dict[str, Any]:
        return {
            "actions": list(self.actions),
            "authority": self.authority.value,
            "code_facts": list(self.code_facts),
            "cwes": list(self.cwes),
            "effects": list(self.effects),
            "embedding": list(self.embedding),
            "grants_execution_authority": False,
            "graph_node": self.graph_node,
            "kind": self.kind,
            "languages": list(self.languages),
            "node_cid": self.node_cid,
            "partition": self.partition,
            "policies": list(self.policies),
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
                "actions",
                "authority",
                "code_facts",
                "cwes",
                "effects",
                "embedding",
                "entry_id",
                "grants_execution_authority",
                "graph_node",
                "kind",
                "languages",
                "node_cid",
                "partition",
                "policies",
                "shard_key",
                "source_cids",
                "text",
            }
        )
        _strict_fields(value, allowed, "retrieval entry")
        try:
            return cls(
                actions=tuple(value["actions"]),
                authority=value["authority"],
                code_facts=tuple(value["code_facts"]),
                cwes=tuple(value["cwes"]),
                effects=tuple(value["effects"]),
                embedding=tuple(value["embedding"]),
                entry_id=value["entry_id"],
                grants_execution_authority=value["grants_execution_authority"],
                graph_node=value["graph_node"],
                kind=value["kind"],
                languages=tuple(value["languages"]),
                node_cid=value["node_cid"],
                partition=value["partition"],
                policies=tuple(value["policies"]),
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
                entries=tuple(RetrievalEntry.from_dict(item) for item in value["entries"]),
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
    """Verified shards bound to graph, model, and producer configuration."""

    graph_root: str
    graph_config_cid: str
    retrieval_config_cid: str
    model_id: str
    model_revision: str
    model_config_cid: str
    shards: tuple[RetrievalShard, ...]
    index_root: str = ""
    schema_version: str = RETRIEVAL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in (
            "graph_root",
            "graph_config_cid",
            "retrieval_config_cid",
            "model_id",
            "model_revision",
            "model_config_cid",
        ):
            object.__setattr__(
                self, name, _clean_text(getattr(self, name), name, maximum=512)
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
        no_model = self.model_id == self.model_revision == NO_EMBEDDING_MODEL
        if has_vectors and no_model:
            raise RetrievalIntegrityError(
                "vector index must bind an embedding model and revision"
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

    @property
    def embedding_dimension(self) -> int:
        for shard in self.shards:
            for entry in shard.entries:
                if entry.embedding:
                    return len(entry.embedding)
        return 0

    def deterministic_dict(self) -> dict[str, Any]:
        return {
            "graph_config_cid": self.graph_config_cid,
            "graph_root": self.graph_root,
            "model_config_cid": self.model_config_cid,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "retrieval_config_cid": self.retrieval_config_cid,
            "schema_version": self.schema_version,
            "shards": [item.to_dict() for item in self.shards],
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
                "graph_config_cid",
                "graph_root",
                "index_root",
                "model_config_cid",
                "model_id",
                "model_revision",
                "retrieval_config_cid",
                "schema_version",
                "shards",
            }
        )
        _strict_fields(value, allowed, "retrieval index")
        try:
            return cls(
                graph_config_cid=value["graph_config_cid"],
                graph_root=value["graph_root"],
                index_root=value["index_root"],
                model_config_cid=value["model_config_cid"],
                model_id=value["model_id"],
                model_revision=value["model_revision"],
                retrieval_config_cid=value["retrieval_config_cid"],
                schema_version=value["schema_version"],
                shards=tuple(RetrievalShard.from_dict(item) for item in value["shards"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, RetrievalError):
                raise
            raise RetrievalIntegrityError(f"invalid retrieval index: {exc}") from exc

    @classmethod
    def from_json(cls, value: str | bytes | bytearray) -> "RetrievalIndex":
        if not isinstance(value, (str, bytes, bytearray)):
            raise RetrievalIntegrityError("retrieval index JSON must be text or bytes")

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
            raise RetrievalIntegrityError("retrieval index is not valid JSON") from exc
        if not isinstance(decoded, Mapping):
            raise RetrievalIntegrityError("retrieval index JSON must contain an object")
        return cls.from_dict(decoded)


@dataclass(frozen=True, slots=True)
class RetrievalScope:
    """Caller-owned scope that query fields are only allowed to narrow."""

    partition: str
    authorities: tuple[RetrievalAuthority, ...] = (
        RetrievalAuthority.NON_AUTHORITATIVE,
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "partition", _clean_text(self.partition, "partition", maximum=512)
        )
        if isinstance(self.authorities, (str, bytes, bytearray)):
            raise RetrievalScopeError("authorities must be a sequence")
        values = tuple(sorted((_authority(item) for item in self.authorities), key=str))
        if not values or len(values) != len(set(values)):
            raise RetrievalScopeError("authorities must be non-empty and unique")
        object.__setattr__(self, "authorities", values)


@dataclass(frozen=True, slots=True)
class RetrievalQuery:
    """One bounded query with optional exact categorical filters."""

    text: str = ""
    partition: str = ""
    authorities: tuple[RetrievalAuthority, ...] = ()
    cwes: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    code_facts: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()
    effects: tuple[str, ...] = ()
    policies: tuple[str, ...] = ()
    start_node_cids: tuple[str, ...] = ()
    embedding: tuple[float, ...] = ()
    max_shards: int | None = None
    max_nodes: int | None = None
    max_results: int | None = None
    max_hops: int | None = None

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
            "cwes",
            "languages",
            "code_facts",
            "actions",
            "effects",
            "policies",
            "start_node_cids",
        ):
            object.__setattr__(self, name, _strings(getattr(self, name), name))
        object.__setattr__(self, "embedding", _vector(self.embedding, "embedding"))
        for name in ("max_shards", "max_nodes", "max_results", "max_hops"):
            value = getattr(self, name)
            if value is not None:
                _positive_int(value, name)
        if not any(
            (
                self.text,
                self.cwes,
                self.languages,
                self.code_facts,
                self.actions,
                self.effects,
                self.policies,
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
    graph_distance: int | None
    authorizes_execution: bool = False
    grants_execution_authority: bool = False

    def __post_init__(self) -> None:
        if (
            self.authorizes_execution is not False
            or self.grants_execution_authority is not False
        ):
            raise RetrievalValidationError("retrieval hits cannot return a grant")

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorizes_execution": False,
            "authority": self.authority.value,
            "entry_id": self.entry_id,
            "grants_execution_authority": False,
            "graph_distance": self.graph_distance,
            "graph_score": self.graph_score,
            "kind": self.kind,
            "lexical_score": self.lexical_score,
            "matched_fields": list(self.matched_fields),
            "node_cid": self.node_cid,
            "partition": self.partition,
            "score": self.score,
            "source_cids": list(self.source_cids),
            "vector_score": self.vector_score,
        }


@dataclass(frozen=True, slots=True)
class RetrievalResponse:
    """Results plus observable resource use and truncation."""

    index_root: str
    graph_root: str
    partition: str
    results: tuple[RetrievalHit, ...]
    shards_scanned: int
    nodes_scanned: int
    graph_nodes_visited: int
    truncated_shards: bool
    truncated_nodes: bool
    truncated_results: bool
    authorizes_execution: bool = False
    grants_execution_authority: bool = False

    def __post_init__(self) -> None:
        if (
            self.authorizes_execution is not False
            or self.grants_execution_authority is not False
        ):
            raise RetrievalValidationError("retrieval responses cannot return a grant")

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorizes_execution": False,
            "grants_execution_authority": False,
            "graph_nodes_visited": self.graph_nodes_visited,
            "graph_root": self.graph_root,
            "index_root": self.index_root,
            "nodes_scanned": self.nodes_scanned,
            "partition": self.partition,
            "results": [item.to_dict() for item in self.results],
            "shards_scanned": self.shards_scanned,
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
                if isinstance(item, (str, int, float)) and not isinstance(item, bool):
                    values.append(str(item))
    return tuple(values)


def _bounded_filter_value(value: Any) -> str:
    text = str(value).strip()
    if len(text) <= RETRIEVAL_MAX_LIST_ITEM_LENGTH:
        return text
    suffix = f"[sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}]"
    prefix_length = RETRIEVAL_MAX_LIST_ITEM_LENGTH - len(suffix)
    return f"{text[:prefix_length]}{suffix}"


def _categorize_node(node: GraphNode) -> dict[str, tuple[str, ...]]:
    payload = node.payload
    node_type = node.node_type
    cwes = (
        (_bounded_filter_value(payload["cwe_id"]),)
        if node_type == "cwe" and payload.get("cwe_id")
        else ()
    )
    languages = (
        (_bounded_filter_value(payload["language"]),)
        if node_type == "language" and payload.get("language")
        else ()
    )
    predicate = _bounded_filter_value(payload.get("predicate", ""))
    code_facts = (predicate,) if predicate else ()
    actions = code_facts if node_type == "action" else ()
    effects = code_facts if node_type in {"effect", "mitigation"} else ()
    policies = (
        tuple(
            _bounded_filter_value(value)
            for key, value in sorted(payload.items())
            if key in {"policy", "policy_id", "effect"} and isinstance(value, str)
        )
        if node_type == "policy"
        else ()
    )
    return {
        "actions": actions,
        "code_facts": code_facts,
        "cwes": cwes,
        "effects": effects,
        "languages": languages,
        "policies": policies,
    }


def graph_entries(
    graph: CVEfixesGraph,
    *,
    partition_by_node: Mapping[str, str],
    shard_count: int = 8,
) -> tuple[RetrievalEntry, ...]:
    """Project verified graph nodes into deterministic partitioned shards."""

    if not isinstance(graph, CVEfixesGraph):
        raise RetrievalValidationError("graph must be CVEfixesGraph")
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
        source_cids = node.source_cids
        if len(source_cids) > RETRIEVAL_MAX_LIST_ITEMS:
            source_cids = (graph.graph_root,)
            categories["policies"] = tuple(
                sorted(
                    {
                        *categories["policies"],
                        "aggregate_provenance_via_graph_root",
                    }
                )
            )
        entries.append(
            RetrievalEntry(
                node_cid=node.cid,
                partition=partition,
                shard_key=shard_key,
                kind=node.node_type,
                text=" ".join((node.node_type, *values))[:4096],
                source_cids=source_cids,
                authority=RetrievalAuthority(node.authority.value),
                **categories,
            )
        )
    return tuple(sorted(entries, key=lambda item: item.entry_id))


def build_retrieval_index(
    graph: CVEfixesGraph,
    *,
    partition_by_node: Mapping[str, str],
    config: RetrievalConfig | None = None,
    shard_count: int = 8,
    extra_entries: Sequence[RetrievalEntry] = (),
    embedding_port: EmbeddingAcceleratorPort | None = None,
    model_id: str = NO_EMBEDDING_MODEL,
    model_revision: str = NO_EMBEDDING_MODEL,
    model_config: Mapping[str, Any] | None = None,
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
        raise RetrievalValidationError("extra_entries must contain RetrievalEntry")
    entries.extend(extra_entries)
    if len({item.entry_id for item in entries}) != len(entries):
        raise RetrievalValidationError("duplicate retrieval entry")

    if embedding_port is not None:
        model_id = _clean_text(model_id, "model_id", maximum=512)
        model_revision = _clean_text(model_revision, "model_revision", maximum=512)
        if model_id == NO_EMBEDDING_MODEL or model_revision == NO_EMBEDDING_MODEL:
            raise RetrievalValidationError(
                "embedding model_id and revision must be pinned"
            )
        try:
            vectors = tuple(embedding_port.embed_documents([item.text for item in entries]))
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
            values["embedding"] = list(_vector(vector, "embedding accelerator vector"))
            embedded.append(RetrievalEntry.from_dict({"entry_id": "", **values}))
        entries = embedded
        model_config = model_config or {}
        model_config_cid = canonical_config_cid(
            dict(model_config),
            schema_version="cvefixes-embedding-model-config/v1",
        )
    else:
        if model_id != NO_EMBEDDING_MODEL or model_revision != NO_EMBEDDING_MODEL:
            raise RetrievalValidationError(
                "model binding requires an embedding accelerator"
            )
        if any(item.embedding for item in entries):
            raise RetrievalValidationError(
                "precomputed vectors require an embedding accelerator binding"
            )
        model_config_cid = canonical_config_cid(
            {"model": NO_EMBEDDING_MODEL},
            schema_version="cvefixes-embedding-model-config/v1",
        )

    by_shard: dict[tuple[str, str], list[RetrievalEntry]] = {}
    for entry in entries:
        by_shard.setdefault((entry.partition, entry.shard_key), []).append(entry)
    shards = tuple(
        RetrievalShard(shard_id=shard_id, partition=partition, entries=tuple(items))
        for (partition, shard_id), items in sorted(by_shard.items())
    )
    return RetrievalIndex(
        graph_root=graph.graph_root,
        graph_config_cid=graph.config_cid,
        retrieval_config_cid=config.cid,
        model_id=model_id,
        model_revision=model_revision,
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


class BoundedHybridRetriever:
    """Verify and query one immutable graph/index pair."""

    def __init__(
        self,
        graph: CVEfixesGraph,
        index: RetrievalIndex,
        *,
        config: RetrievalConfig | None = None,
        embedding_port: EmbeddingAcceleratorPort | None = None,
    ) -> None:
        self.graph = graph
        self.index = index
        self.config = config or RetrievalConfig()
        self.embedding_port = embedding_port
        self._verify_bindings()

    def _verify_bindings(self) -> None:
        if not isinstance(self.graph, CVEfixesGraph):
            raise RetrievalIntegrityError("graph must be a verified CVEfixesGraph")
        if not isinstance(self.index, RetrievalIndex):
            raise RetrievalIntegrityError("index must be RetrievalIndex")
        if self.index.graph_root != self.graph.graph_root:
            raise RetrievalIntegrityError("retrieval index graph root mismatch")
        if self.index.graph_config_cid != self.graph.config_cid:
            raise RetrievalIntegrityError("retrieval index graph config mismatch")
        if self.index.retrieval_config_cid != self.config.cid:
            raise RetrievalIntegrityError("retrieval index config mismatch")
        graph_nodes = {item.cid for item in self.graph.nodes}
        for shard in self.index.shards:
            for entry in shard.entries:
                if entry.graph_node and entry.node_cid not in graph_nodes:
                    raise RetrievalIntegrityError(
                        "retrieval entry references an unknown graph node"
                    )

    def _limits(self, query: RetrievalQuery) -> tuple[int, int, int, int]:
        values = []
        for name in ("max_shards", "max_nodes", "max_results", "max_hops"):
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
    ) -> tuple[dict[str, int], int, bool]:
        if not starts:
            return {}, 0, False
        node_ids = {item.cid for item in self.graph.nodes}
        unknown = sorted(set(starts) - node_ids)
        if unknown:
            raise RetrievalValidationError("start_node_cids contains unknown node")
        edge_by_id = {item.cid: item for item in self.graph.edges}
        distances = {item: 0 for item in starts}
        queue = deque(sorted(starts))
        visited = 0
        truncated = False
        while queue:
            node_id = queue.popleft()
            if visited >= max_nodes:
                truncated = True
                break
            visited += 1
            distance = distances[node_id]
            if distance >= max_hops:
                continue
            edge_ids = (
                tuple(self.graph.outgoing[node_id])
                + tuple(self.graph.incoming[node_id])
            )
            for edge_id in sorted(set(edge_ids)):
                edge = edge_by_id[edge_id]
                # Similarity remains usable as approximate retrieval evidence,
                # but never changes authority or partition filtering.
                neighbor = (
                    edge.target_node_cid
                    if edge.source_node_cid == node_id
                    else edge.source_node_cid
                )
                if neighbor not in distances:
                    distances[neighbor] = distance + 1
                    queue.append(neighbor)
        return distances, visited, truncated

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

        max_shards, max_nodes, max_results, max_hops = self._limits(query)
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
                    f"embedding accelerator failed closed: {type(exc).__name__}: {exc}"
                ) from exc
        if query_vector and not self.index.embedding_dimension:
            raise RetrievalValidationError("query vector supplied to lexical-only index")
        if query_vector and len(query_vector) != self.index.embedding_dimension:
            raise RetrievalValidationError("query/index embedding dimensions differ")

        eligible_shards = [
            item for item in self.index.shards if item.partition == partition
        ]
        selected_shards = eligible_shards[:max_shards]
        truncated_shards = len(eligible_shards) > len(selected_shards)
        distances, graph_visited, graph_truncated = self._distances(
            query.start_node_cids, max_hops=max_hops, max_nodes=max_nodes
        )

        candidates: list[RetrievalHit] = []
        nodes_scanned = 0
        truncated_nodes = graph_truncated
        filters = {
            "actions": query.actions,
            "code_facts": query.code_facts,
            "cwes": query.cwes,
            "effects": query.effects,
            "languages": query.languages,
            "policies": query.policies,
        }
        for shard in selected_shards:
            for entry in shard.entries:
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
                            *entry.cwes,
                            *entry.languages,
                            *entry.code_facts,
                            *entry.actions,
                            *entry.effects,
                            *entry.policies,
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
                        if required and _matches_filter(required, getattr(entry, name))
                    )
                )
                if lexical == vector == graph_score == 0.0 and not matched:
                    continue
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
                        graph_distance=distance,
                    )
                )
            if nodes_scanned >= max_nodes:
                break
        candidates.sort(key=lambda item: (-item.score, item.entry_id))
        results = tuple(candidates[:max_results])
        return RetrievalResponse(
            index_root=self.index.index_root,
            graph_root=self.graph.graph_root,
            partition=partition,
            results=results,
            shards_scanned=len(selected_shards),
            nodes_scanned=nodes_scanned,
            graph_nodes_visited=graph_visited,
            truncated_shards=truncated_shards,
            truncated_nodes=truncated_nodes,
            truncated_results=len(candidates) > len(results),
        )


def retrieve_cvefixes(
    graph: CVEfixesGraph,
    index: RetrievalIndex,
    query: RetrievalQuery,
    *,
    scope: RetrievalScope,
    config: RetrievalConfig | None = None,
    embedding_port: EmbeddingAcceleratorPort | None = None,
) -> RetrievalResponse:
    """Convenience wrapper around :class:`BoundedHybridRetriever`."""

    return BoundedHybridRetriever(
        graph, index, config=config, embedding_port=embedding_port
    ).retrieve(query, scope=scope)


__all__ = [
    "NO_EMBEDDING_MODEL",
    "RETRIEVAL_CONFIG_SCHEMA_VERSION",
    "RETRIEVAL_MAX_LIST_ITEMS",
    "RETRIEVAL_MAX_LIST_ITEM_LENGTH",
    "RETRIEVAL_SCHEMA_VERSION",
    "BoundedHybridRetriever",
    "EmbeddingAcceleratorPort",
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
    "build_retrieval_index",
    "graph_entries",
    "retrieve_cvefixes",
]
