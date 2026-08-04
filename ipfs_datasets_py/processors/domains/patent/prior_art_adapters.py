"""Citation, family, foreign-patent, and NPL adapters for prior-art coverage (PATLAW-150).

Expands public-patent search beyond keyword/classification queries:

* Backward and forward citation traversal (cycle-safe)
* Priority and continuation family expansion with identifier normalization
  and family-level deduplication
* Approved foreign-patent metadata/search adapters (must run to claim search)
* NPL metadata/search adapters with explicit rights status; unlicensed body
  text is never redistributed and cannot enter a public release without
  separate rights approval

Design invariants
-----------------
* Traversal of citations and families is cycle-safe (visited-set + depth bound).
* Identifiers are normalized before graph edges are added or compared.
* Family members are deduplicated by normalized document id.
* Foreign-patent and NPL adapters never claim coverage without an actual run.
* NPL adapters expose rights status on every hit; body text is stripped unless
  ``rights_status`` is licensed/approved for redistribution.
* Failures, inaccessible, and unlicensed sources remain explicit outcomes.
* Never asserts novelty, obviousness, or patentability.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
from types import MappingProxyType
from typing import Any, Callable, Final, Iterable, Mapping, Protocol, Sequence

from .prior_art import (
    PRIOR_ART_DISCLAIMER,
    PriorArtError,
    QueryFamily,
    SearchCorpus,
)
from .prior_art_runtime import (
    AdapterSearchResult,
    PublicSearchQuery,
)
from .retrieval_contracts import PreRankingFilters
from .search_journal import (
    AdapterKind,
    JournalHit,
    NamedAdapterIdentity,
    QueryOutcomeKind,
    RetryAttemptRecord,
    SearchDatabase,
    make_source_link,
    outcome_claims_search,
)

# ---------------------------------------------------------------------------
# Schema / identity pins
# ---------------------------------------------------------------------------

PRIOR_ART_ADAPTERS_SCHEMA_VERSION: Final = "patent.prior_art_adapters.v1"
PRIOR_ART_ADAPTERS_INTERFACE: Final = "PriorArtCoverageAdapters@1"
PRIOR_ART_ADAPTERS_CODE_VERSION: Final = "1.0.0"

CITATION_ADAPTER_NAME: Final = "citation_expansion.v1"
FAMILY_ADAPTER_NAME: Final = "family_expansion.v1"
FOREIGN_PATENT_ADAPTER_NAME: Final = "foreign_patent_metadata.v1"
NPL_ADAPTER_NAME: Final = "npl_metadata.v1"

DEFAULT_TRAVERSAL_MAX_DEPTH: Final = 3
DEFAULT_TRAVERSAL_MAX_NODES: Final = 256
DEFAULT_RANK_CUTOFF: Final = 25
DEFAULT_MAX_HITS: Final = 128

_NONEMPTY_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
_ISO_UTC_RE = re.compile(
    r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})\Z"
)
_ISO_DATE_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")
_CID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9+=/_-]{7,255}\Z")

# Patent/publication-like tokens: US10123456B2, EP0999991A1, WO2019123456A1, etc.
_DOC_ID_RE = re.compile(
    r"\A\s*(?P<cc>[A-Za-z]{2})?\s*(?P<body>[A-Za-z]{0,3}\d[\d,]{2,14})\s*"
    r"(?P<kind>[A-Za-z]\d?)?\s*\Z"
)
_APP_LIKE_RE = re.compile(r"\A\s*(?P<body>\d{2}[/\-]?\d{6,7})\s*\Z")

# Synthetic stable CID prefix for adapter-local graph edges.
_ADAPTER_SOURCE_CID_PREFIX: Final = "bafybeigpriorartadapter"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PriorArtAdapterError(PriorArtError):
    """Base error for prior-art coverage adapters."""

    code: str = "prior_art_adapter_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class IdentifierNormalizationError(PriorArtAdapterError):
    """Raised when a document identifier cannot be normalized."""

    code = "identifier_normalization"


class TraversalCycleError(PriorArtAdapterError):
    """Raised when cycle detection aborts an unsafe expansion (optional hard mode)."""

    code = "traversal_cycle"


class NplRightsError(PriorArtAdapterError):
    """Raised when NPL body content is requested without rights approval."""

    code = "npl_rights"


class AdapterConfigError(PriorArtAdapterError):
    """Raised when adapter configuration is invalid."""

    code = "adapter_config_invalid"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RightsStatus(str, Enum):
    """Redistribution / license status for adapter results (esp. NPL)."""

    PUBLIC = "public"
    LICENSED = "licensed"
    UNLICENSED = "unlicensed"
    UNKNOWN = "unknown"
    REQUIRES_APPROVAL = "requires_approval"
    INACCESSIBLE = "inaccessible"


class CitationDirection(str, Enum):
    """Direction of a citation edge relative to the seed document."""

    BACKWARD = "backward"  # seed cites target (prior art cited by seed)
    FORWARD = "forward"  # target cites seed (later citations of seed)
    UNKNOWN = "unknown"


class FamilyRelationKind(str, Enum):
    """How a family member relates to the seed application/patent."""

    SEED = "seed"
    CONTINUATION = "continuation"
    CONTINUATION_IN_PART = "continuation_in_part"
    DIVISIONAL = "divisional"
    PRIORITY = "priority"
    FOREIGN_PRIORITY = "foreign_priority"
    PARENT = "parent"
    CHILD = "child"
    SIBLING = "sibling"
    UNKNOWN = "unknown"


class ExpansionMode(str, Enum):
    """What an expansion adapter emits."""

    CITATIONS = "citations"
    FAMILIES = "families"
    FOREIGN = "foreign"
    NPL = "npl"


# Rights statuses that permit body text in adapter hits.
_BODY_TEXT_ALLOWED_RIGHTS: Final[frozenset[RightsStatus]] = frozenset(
    {
        RightsStatus.PUBLIC,
        RightsStatus.LICENSED,
    }
)

# Rights that block NPL from public release without separate approval.
_PUBLIC_RELEASE_BLOCKED_RIGHTS: Final[frozenset[RightsStatus]] = frozenset(
    {
        RightsStatus.UNLICENSED,
        RightsStatus.UNKNOWN,
        RightsStatus.REQUIRES_APPROVAL,
        RightsStatus.INACCESSIBLE,
    }
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def canonical_json(value: Any) -> str:
    """Deterministic compact JSON with sorted keys."""
    import json

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def content_digest(value: Any) -> str:
    """SHA-256 hex digest of canonical JSON (no ``sha256:`` prefix)."""
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def content_cid(value: Any, *, prefix: str = _ADAPTER_SOURCE_CID_PREFIX) -> str:
    digest = content_digest(value)
    return f"{prefix}{digest[:48]}"


def _require_str(value: Any, field: str, *, max_len: int = 4096) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be str, got {type(value).__name__}")
    text = value.strip()
    if not text:
        raise ValueError(f"{field} must be non-empty")
    if len(text) > max_len:
        raise ValueError(f"{field} exceeds max length {max_len}")
    return text


def _optional_str(value: Any, field: str, *, max_len: int = 4096) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field} must be str or None")
    text = value.strip()
    if not text:
        return None
    if len(text) > max_len:
        raise ValueError(f"{field} exceeds max length {max_len}")
    return text


def _identifier(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=256)
    if not _NONEMPTY_ID_RE.match(text):
        raise ValueError(f"{field} is not a valid identifier: {text!r}")
    return text


def _iso_utc(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=64)
    if not _ISO_UTC_RE.match(text):
        raise ValueError(f"{field} must be ISO-8601 UTC timestamp, got {text!r}")
    return text


def _iso_date_or_utc(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=64)
    if not (_ISO_DATE_RE.match(text) or _ISO_UTC_RE.match(text)):
        raise ValueError(f"{field} must be YYYY-MM-DD or ISO-8601 UTC, got {text!r}")
    return text


def _nonneg_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be int")
    if value < 0:
        raise ValueError(f"{field} must be >= 0")
    return value


def _positive_int(value: Any, field: str) -> int:
    n = _nonneg_int(value, field)
    if n < 1:
        raise ValueError(f"{field} must be >= 1")
    return n


def _coerce_enum(enum_cls: type[Enum], value: Any, field: str) -> Enum:
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        try:
            return enum_cls(value.strip())
        except ValueError as exc:
            raise ValueError(f"invalid {field}: {value!r}") from exc
    raise TypeError(f"{field} must be {enum_cls.__name__} or str")


def _frozen_str_map(value: Any, field: str, *, max_items: int = 64) -> Mapping[str, str]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be a mapping")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    out: dict[str, str] = {}
    for key, raw in value.items():
        k = _require_str(key, f"{field}.key", max_len=128)
        v = _require_str(raw, f"{field}[{k}]", max_len=2048)
        out[k] = v
    return MappingProxyType(dict(sorted(out.items())))


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping, got {type(value).__name__}")
    return value


def rights_allows_body_text(status: RightsStatus | str) -> bool:
    """True when NPL/source body text may be retained in adapter hits."""
    s = _coerce_enum(RightsStatus, status, "rights_status")
    assert isinstance(s, RightsStatus)
    return s in _BODY_TEXT_ALLOWED_RIGHTS


def rights_blocks_public_release(status: RightsStatus | str) -> bool:
    """True when content with this rights status cannot enter a public release."""
    s = _coerce_enum(RightsStatus, status, "rights_status")
    assert isinstance(s, RightsStatus)
    return s in _PUBLIC_RELEASE_BLOCKED_RIGHTS


# ---------------------------------------------------------------------------
# Identifier normalization
# ---------------------------------------------------------------------------


def normalize_document_id(
    value: str,
    *,
    default_country: str | None = "US",
    strict: bool = False,
) -> str:
    """Normalize a patent, publication, or application-like document id.

    Produces an uppercase compact form (e.g. ``US10123456B2``, ``EP0999991A1``,
    ``16123456``). Commas and whitespace are stripped. Kind codes are uppercased.

    When *strict* is True, unrecognized values raise
    :class:`IdentifierNormalizationError`. Otherwise the stripped uppercased
    input is returned so traversal can still key on it.
    """
    if not isinstance(value, str):
        raise TypeError("document id must be str")
    raw = value.strip()
    if not raw:
        if strict:
            raise IdentifierNormalizationError("empty document id")
        return ""

    # Application-like 02/123456 or 02123456
    app_m = _APP_LIKE_RE.match(raw)
    if app_m:
        digits = re.sub(r"[^\d]", "", app_m.group("body"))
        if len(digits) >= 8:
            return digits[:8] if len(digits) == 8 else digits

    m = _DOC_ID_RE.match(raw)
    if not m:
        # Fallback: strip non-alnum except keep leading country-ish letters+digits
        compact = re.sub(r"[\s,./\-]+", "", raw).upper()
        if not compact:
            if strict:
                raise IdentifierNormalizationError(f"empty after normalize: {value!r}")
            return ""
        if strict and not re.match(r"\A[A-Z0-9]{4,32}\Z", compact):
            raise IdentifierNormalizationError(f"unrecognized document id: {value!r}")
        return compact

    cc = (m.group("cc") or default_country or "").upper()
    body = re.sub(r"[^\dA-Za-z]", "", m.group("body") or "").upper()
    kind = (m.group("kind") or "").upper()
    if not body:
        if strict:
            raise IdentifierNormalizationError(f"unrecognized document id: {value!r}")
        return raw.upper().replace(" ", "").replace(",", "")
    # Prefer country code when body is pure digits
    if cc and body and body[0].isdigit():
        return f"{cc}{body}{kind}"
    if cc and body and body[0].isalpha():
        # Prefixed body like D123456 already has type letter — still prefix country
        # only when body does not already start with country.
        if body.startswith(cc):
            return f"{body}{kind}"
        return f"{cc}{body}{kind}"
    return f"{body}{kind}"


def normalize_identifier_map(
    identifiers: Mapping[str, str] | None,
) -> Mapping[str, str]:
    """Normalize common patent identifier keys in a metadata map."""
    if not identifiers:
        return MappingProxyType({})
    out: dict[str, str] = {}
    for key, raw in identifiers.items():
        k = str(key).strip()
        v = str(raw).strip()
        if not k or not v:
            continue
        if k in {
            "document_id",
            "documentId",
            "publicationNumber",
            "publication_number",
            "patentNumber",
            "patent_number",
            "applicationNumber",
            "application_number",
            "cited_id",
            "citing_id",
        }:
            out[k] = normalize_document_id(v)
        else:
            out[k] = v
    return MappingProxyType(dict(sorted(out.items())))


# ---------------------------------------------------------------------------
# Graph edges / members
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CitationEdge:
    """One directed citation relationship between normalized document ids."""

    citing_id: str
    cited_id: str
    direction: CitationDirection = CitationDirection.BACKWARD
    category: str | None = None
    rights_status: RightsStatus = RightsStatus.PUBLIC
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "citing_id", normalize_document_id(_require_str(self.citing_id, "citing_id"))
        )
        object.__setattr__(
            self, "cited_id", normalize_document_id(_require_str(self.cited_id, "cited_id"))
        )
        if not self.citing_id or not self.cited_id:
            raise IdentifierNormalizationError("citation edge requires non-empty ids")
        object.__setattr__(
            self,
            "direction",
            _coerce_enum(CitationDirection, self.direction, "direction"),
        )
        object.__setattr__(
            self, "category", _optional_str(self.category, "category", max_len=64)
        )
        object.__setattr__(
            self,
            "rights_status",
            _coerce_enum(RightsStatus, self.rights_status, "rights_status"),
        )
        object.__setattr__(
            self, "metadata", _frozen_str_map(self.metadata, "metadata", max_items=32)
        )

    @property
    def edge_key(self) -> tuple[str, str, str]:
        return (self.citing_id, self.cited_id, self.direction.value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "cited_id": self.cited_id,
            "citing_id": self.citing_id,
            "direction": self.direction.value,
            "metadata": dict(self.metadata),
            "rights_status": self.rights_status.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CitationEdge":
        value = _mapping(value, "CitationEdge")
        return cls(
            citing_id=value.get("citing_id", ""),
            cited_id=value.get("cited_id", ""),
            direction=value.get("direction", CitationDirection.BACKWARD.value),
            category=value.get("category"),
            rights_status=value.get("rights_status", RightsStatus.PUBLIC.value),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class FamilyMember:
    """One family member (continuation, priority, sibling, …) with normalized id."""

    document_id: str
    relation: FamilyRelationKind = FamilyRelationKind.UNKNOWN
    related_to: str | None = None
    filing_date: str | None = None
    priority_date: str | None = None
    country: str | None = None
    rights_status: RightsStatus = RightsStatus.PUBLIC
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "document_id",
            normalize_document_id(_require_str(self.document_id, "document_id")),
        )
        if not self.document_id:
            raise IdentifierNormalizationError("family member requires non-empty document_id")
        object.__setattr__(
            self, "relation", _coerce_enum(FamilyRelationKind, self.relation, "relation")
        )
        related = _optional_str(self.related_to, "related_to", max_len=64)
        if related is not None:
            related = normalize_document_id(related)
        object.__setattr__(self, "related_to", related)
        object.__setattr__(
            self, "filing_date", _optional_str(self.filing_date, "filing_date", max_len=32)
        )
        object.__setattr__(
            self,
            "priority_date",
            _optional_str(self.priority_date, "priority_date", max_len=32),
        )
        object.__setattr__(
            self, "country", _optional_str(self.country, "country", max_len=8)
        )
        object.__setattr__(
            self,
            "rights_status",
            _coerce_enum(RightsStatus, self.rights_status, "rights_status"),
        )
        object.__setattr__(
            self, "metadata", _frozen_str_map(self.metadata, "metadata", max_items=32)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "country": self.country,
            "document_id": self.document_id,
            "filing_date": self.filing_date,
            "metadata": dict(self.metadata),
            "priority_date": self.priority_date,
            "related_to": self.related_to,
            "relation": self.relation.value,
            "rights_status": self.rights_status.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FamilyMember":
        value = _mapping(value, "FamilyMember")
        return cls(
            document_id=value.get("document_id", ""),
            relation=value.get("relation", FamilyRelationKind.UNKNOWN.value),
            related_to=value.get("related_to"),
            filing_date=value.get("filing_date"),
            priority_date=value.get("priority_date"),
            country=value.get("country"),
            rights_status=value.get("rights_status", RightsStatus.PUBLIC.value),
            metadata=value.get("metadata") or {},
        )


# ---------------------------------------------------------------------------
# Cycle-safe citation / family traversal
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CitationTraversalResult:
    """Result of a cycle-safe citation expansion from one or more seeds."""

    seed_ids: tuple[str, ...]
    edges: tuple[CitationEdge, ...]
    visited_ids: tuple[str, ...]
    cycles_skipped: tuple[str, ...]
    max_depth: int
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycles_skipped": list(self.cycles_skipped),
            "edges": [e.to_dict() for e in self.edges],
            "max_depth": self.max_depth,
            "seed_ids": list(self.seed_ids),
            "truncated": self.truncated,
            "visited_ids": list(self.visited_ids),
        }


@dataclass(frozen=True, slots=True)
class FamilyTraversalResult:
    """Result of a cycle-safe family expansion with deduplicated members."""

    seed_ids: tuple[str, ...]
    members: tuple[FamilyMember, ...]
    visited_ids: tuple[str, ...]
    cycles_skipped: tuple[str, ...]
    max_depth: int
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycles_skipped": list(self.cycles_skipped),
            "max_depth": self.max_depth,
            "members": [m.to_dict() for m in self.members],
            "seed_ids": list(self.seed_ids),
            "truncated": self.truncated,
            "visited_ids": list(self.visited_ids),
        }


def traverse_citations(
    seeds: Sequence[str],
    edges: Sequence[CitationEdge | Mapping[str, Any]],
    *,
    directions: Sequence[CitationDirection | str] = (
        CitationDirection.BACKWARD,
        CitationDirection.FORWARD,
    ),
    max_depth: int = DEFAULT_TRAVERSAL_MAX_DEPTH,
    max_nodes: int = DEFAULT_TRAVERSAL_MAX_NODES,
) -> CitationTraversalResult:
    """BFS citation expansion that never revisits a document id (cycle-safe).

    Edges that would re-enter a node already on the active path or already
    visited at equal-or-shallower depth are recorded in ``cycles_skipped``
    and do not expand further.
    """
    depth_limit = _positive_int(max_depth, "max_depth")
    node_limit = _positive_int(max_nodes, "max_nodes")
    allowed_dirs = {
        _coerce_enum(CitationDirection, d, "directions") for d in directions
    }

    seed_norm = tuple(
        normalize_document_id(_require_str(s, f"seeds[{i}]"))
        for i, s in enumerate(seeds)
        if str(s).strip()
    )
    if not seed_norm:
        raise AdapterConfigError("traverse_citations requires at least one seed id")

    # Adjacency: from_id -> list of (to_id, edge)
    adj: dict[str, list[tuple[str, CitationEdge]]] = {}
    parsed_edges: list[CitationEdge] = []
    for i, raw in enumerate(edges):
        edge = raw if isinstance(raw, CitationEdge) else CitationEdge.from_dict(raw)
        parsed_edges.append(edge)
        if edge.direction is CitationDirection.BACKWARD:
            # seed (citing) -> cited prior art
            adj.setdefault(edge.citing_id, []).append((edge.cited_id, edge))
        elif edge.direction is CitationDirection.FORWARD:
            # seed (cited) -> later citing docs
            adj.setdefault(edge.cited_id, []).append((edge.citing_id, edge))
        else:
            # unknown: both directions for connectivity, still cycle-safe
            adj.setdefault(edge.citing_id, []).append((edge.cited_id, edge))
            adj.setdefault(edge.cited_id, []).append((edge.citing_id, edge))

    # Filter adjacency by requested directions
    filtered_adj: dict[str, list[tuple[str, CitationEdge]]] = {}
    for src, targets in adj.items():
        kept = [(t, e) for t, e in targets if e.direction in allowed_dirs or e.direction is CitationDirection.UNKNOWN]
        if kept:
            filtered_adj[src] = kept

    visited: dict[str, int] = {}  # id -> depth first seen
    cycles: list[str] = []
    collected: dict[tuple[str, str, str], CitationEdge] = {}
    truncated = False

    # Queue: (node, depth, path_set)
    queue: list[tuple[str, int, frozenset[str]]] = [
        (s, 0, frozenset({s})) for s in seed_norm
    ]
    for s in seed_norm:
        visited[s] = 0

    while queue:
        node, depth, path = queue.pop(0)
        if depth >= depth_limit:
            continue
        for target, edge in filtered_adj.get(node, ()):
            if target in path:
                cycles.append(f"{node}->{target}")
                continue
            if target in visited and visited[target] <= depth + 1:
                # Already expanded from an equal-or-shallower path — skip re-entry
                cycles.append(f"{node}->{target}")
                collected.setdefault(edge.edge_key, edge)
                continue
            if len(visited) >= node_limit:
                truncated = True
                break
            visited[target] = depth + 1
            collected[edge.edge_key] = edge
            queue.append((target, depth + 1, path | {target}))
        if truncated:
            break

    ordered_edges = tuple(
        sorted(collected.values(), key=lambda e: (e.citing_id, e.cited_id, e.direction.value))
    )
    ordered_visited = tuple(sorted(visited.keys()))
    ordered_cycles = tuple(sorted(set(cycles)))
    return CitationTraversalResult(
        seed_ids=seed_norm,
        edges=ordered_edges,
        visited_ids=ordered_visited,
        cycles_skipped=ordered_cycles,
        max_depth=depth_limit,
        truncated=truncated,
    )


def traverse_families(
    seeds: Sequence[str],
    members: Sequence[FamilyMember | Mapping[str, Any]],
    *,
    max_depth: int = DEFAULT_TRAVERSAL_MAX_DEPTH,
    max_nodes: int = DEFAULT_TRAVERSAL_MAX_NODES,
) -> FamilyTraversalResult:
    """BFS family expansion with cycle safety and document-id deduplication.

    Members form an undirected graph via ``related_to`` links. Seeds that
    appear as members are always included. Duplicate document ids collapse
    to a single member (first relation wins, then SEED preferred).
    """
    depth_limit = _positive_int(max_depth, "max_depth")
    node_limit = _positive_int(max_nodes, "max_nodes")

    seed_norm = tuple(
        normalize_document_id(_require_str(s, f"seeds[{i}]"))
        for i, s in enumerate(seeds)
        if str(s).strip()
    )
    if not seed_norm:
        raise AdapterConfigError("traverse_families requires at least one seed id")

    # Dedup members by document_id (prefer SEED relation)
    by_id: dict[str, FamilyMember] = {}
    for i, raw in enumerate(members):
        member = raw if isinstance(raw, FamilyMember) else FamilyMember.from_dict(raw)
        existing = by_id.get(member.document_id)
        if existing is None:
            by_id[member.document_id] = member
        elif (
            member.relation is FamilyRelationKind.SEED
            and existing.relation is not FamilyRelationKind.SEED
        ):
            by_id[member.document_id] = member

    # Ensure seeds exist as members
    for s in seed_norm:
        if s not in by_id:
            by_id[s] = FamilyMember(
                document_id=s,
                relation=FamilyRelationKind.SEED,
            )
        elif by_id[s].relation is not FamilyRelationKind.SEED and s in seed_norm:
            # Keep existing relation but ensure connectivity
            pass

    # Undirected adjacency from related_to
    adj: dict[str, set[str]] = {doc_id: set() for doc_id in by_id}
    for member in by_id.values():
        if member.related_to:
            adj.setdefault(member.document_id, set()).add(member.related_to)
            adj.setdefault(member.related_to, set()).add(member.document_id)
            # Ensure related_to exists as a placeholder member if missing
            if member.related_to not in by_id:
                by_id[member.related_to] = FamilyMember(
                    document_id=member.related_to,
                    relation=FamilyRelationKind.UNKNOWN,
                    related_to=member.document_id,
                )
                adj.setdefault(member.related_to, set())

    visited: dict[str, int] = {}
    cycles: list[str] = []
    truncated = False
    queue: list[tuple[str, int, frozenset[str]]] = [
        (s, 0, frozenset({s})) for s in seed_norm
    ]
    for s in seed_norm:
        visited[s] = 0

    while queue:
        node, depth, path = queue.pop(0)
        if depth >= depth_limit:
            continue
        for target in sorted(adj.get(node, ())):
            if target in path:
                cycles.append(f"{node}->{target}")
                continue
            if target in visited:
                cycles.append(f"{node}->{target}")
                continue
            if len(visited) >= node_limit:
                truncated = True
                break
            visited[target] = depth + 1
            queue.append((target, depth + 1, path | {target}))
        if truncated:
            break

    # Deduplicated members in the connected component (visited only)
    result_members = tuple(
        sorted(
            (by_id[doc_id] for doc_id in visited if doc_id in by_id),
            key=lambda m: (m.document_id, m.relation.value),
        )
    )
    return FamilyTraversalResult(
        seed_ids=seed_norm,
        members=result_members,
        visited_ids=tuple(sorted(visited.keys())),
        cycles_skipped=tuple(sorted(set(cycles))),
        max_depth=depth_limit,
        truncated=truncated,
    )


def deduplicate_family_members(
    members: Sequence[FamilyMember | Mapping[str, Any]],
) -> tuple[FamilyMember, ...]:
    """Collapse members that share a normalized document id (SEED preferred)."""
    by_id: dict[str, FamilyMember] = {}
    for raw in members:
        member = raw if isinstance(raw, FamilyMember) else FamilyMember.from_dict(raw)
        existing = by_id.get(member.document_id)
        if existing is None:
            by_id[member.document_id] = member
        elif (
            member.relation is FamilyRelationKind.SEED
            and existing.relation is not FamilyRelationKind.SEED
        ):
            by_id[member.document_id] = member
    return tuple(sorted(by_id.values(), key=lambda m: m.document_id))


# ---------------------------------------------------------------------------
# NPL record (rights-gated body text)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NplRecord:
    """NPL metadata hit with explicit rights status (body text rights-gated)."""

    document_id: str
    title: str | None = None
    identifier: str | None = None  # DOI, ISBN, URL, etc.
    rights_status: RightsStatus = RightsStatus.UNLICENSED
    body_text: str | None = None
    rights_approval_id: str | None = None
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "document_id", _identifier(self.document_id, "document_id")
        )
        object.__setattr__(
            self, "title", _optional_str(self.title, "title", max_len=2048)
        )
        object.__setattr__(
            self, "identifier", _optional_str(self.identifier, "identifier", max_len=512)
        )
        status = _coerce_enum(RightsStatus, self.rights_status, "rights_status")
        assert isinstance(status, RightsStatus)
        object.__setattr__(self, "rights_status", status)
        approval = _optional_str(
            self.rights_approval_id, "rights_approval_id", max_len=256
        )
        object.__setattr__(self, "rights_approval_id", approval)
        object.__setattr__(
            self, "metadata", _frozen_str_map(self.metadata, "metadata", max_items=32)
        )

        # Strip body text unless rights allow it.
        body = _optional_str(self.body_text, "body_text", max_len=16384)
        if body is not None and not rights_allows_body_text(status):
            # Fail closed: drop body rather than retain unlicensed content.
            body = None
        # Separate rights approval is required for REQUIRES_APPROVAL even with body.
        if (
            status is RightsStatus.REQUIRES_APPROVAL
            and body is not None
            and not approval
        ):
            body = None
        object.__setattr__(self, "body_text", body)

    @property
    def may_enter_public_release(self) -> bool:
        """True only when rights explicitly allow public redistribution."""
        if self.rights_status is RightsStatus.PUBLIC:
            return True
        if self.rights_status is RightsStatus.LICENSED:
            # Licensed NPL still needs a separate rights approval id for public release.
            return bool(self.rights_approval_id)
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "body_text": self.body_text,
            "document_id": self.document_id,
            "identifier": self.identifier,
            "metadata": dict(self.metadata),
            "rights_approval_id": self.rights_approval_id,
            "rights_status": self.rights_status.value,
            "title": self.title,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "NplRecord":
        value = _mapping(value, "NplRecord")
        return cls(
            document_id=value.get("document_id", ""),
            title=value.get("title"),
            identifier=value.get("identifier"),
            rights_status=value.get("rights_status", RightsStatus.UNLICENSED.value),
            body_text=value.get("body_text"),
            rights_approval_id=value.get("rights_approval_id"),
            metadata=value.get("metadata") or {},
        )


def assert_npl_records_safe_for_public_release(
    records: Sequence[NplRecord | Mapping[str, Any]],
) -> None:
    """Fail closed if any NPL record would enter public release without rights.

    Public release is allowed only for:

    * ``rights_status=public`` (no body restriction beyond existing strip), or
    * ``rights_status=licensed`` **and** a non-empty ``rights_approval_id``.

    Unlicensed, unknown, inaccessible, or requires-approval-without-id records
    raise :class:`NplRightsError`.
    """
    for i, raw in enumerate(records):
        rec = raw if isinstance(raw, NplRecord) else NplRecord.from_dict(raw)
        if not rec.may_enter_public_release:
            raise NplRightsError(
                f"NPL record {rec.document_id!r} (index {i}) cannot enter a "
                f"public release with rights_status={rec.rights_status.value!r}"
                + (
                    " without rights_approval_id"
                    if rec.rights_status is RightsStatus.LICENSED
                    else ""
                ),
                code="npl_public_release_blocked",
            )
        # Body text must never ship for blocked rights (defense in depth).
        if rec.body_text and rights_blocks_public_release(rec.rights_status):
            raise NplRightsError(
                f"NPL record {rec.document_id!r} retains body_text under "
                f"rights_status={rec.rights_status.value!r}",
                code="npl_body_text_blocked",
            )


# ---------------------------------------------------------------------------
# Adapter protocol (compatible with PriorArtSearchAdapter)
# ---------------------------------------------------------------------------


class CoverageSearchAdapter(Protocol):
    """Named adapter that can search and declare rights for coverage records."""

    @property
    def identity(self) -> NamedAdapterIdentity: ...

    @property
    def default_rights_status(self) -> RightsStatus: ...

    def supports_database(self, database: SearchDatabase) -> bool: ...

    def search(
        self,
        query: PublicSearchQuery,
        *,
        search_time_utc: str,
        corpus_cutoff: str,
        pre_ranking_filters: PreRankingFilters | None = None,
    ) -> AdapterSearchResult: ...


# ---------------------------------------------------------------------------
# Concrete adapters
# ---------------------------------------------------------------------------


def _seed_ids_from_query(query: PublicSearchQuery) -> tuple[str, ...]:
    """Extract seed document ids from query text, keywords, and filters."""
    seeds: list[str] = []
    filters = dict(query.filters or {})
    for key in (
        "seed_document_id",
        "seed_document_ids",
        "document_id",
        "publication_number",
        "patent_number",
        "application_number",
    ):
        raw = filters.get(key)
        if not raw:
            continue
        # Allow comma-separated multi-seeds
        for part in str(raw).split(","):
            part = part.strip()
            if part:
                seeds.append(normalize_document_id(part))
    if not seeds:
        # Last resort: treat first keyword-like token from query_text as seed
        for token in re.findall(r"[A-Za-z]{0,2}\d[\d,]{3,14}[A-Za-z]?\d?", query.query_text):
            seeds.append(normalize_document_id(token))
            break
    # Dedupe preserve order
    seen: set[str] = set()
    out: list[str] = []
    for s in seeds:
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return tuple(out)


def _hit_from_document(
    *,
    document_id: str,
    rank: int,
    score: float,
    rights_status: RightsStatus,
    source_cid: str | None = None,
    artifact_id: str | None = None,
    identifiers: Mapping[str, str] | None = None,
    passage_excerpt: str | None = None,
    metadata: Mapping[str, str] | None = None,
) -> JournalHit:
    cid = source_cid or content_cid({"document_id": document_id, "rank": rank})
    art = artifact_id or f"artifact:{document_id}"
    meta = dict(metadata or {})
    meta.setdefault("rights_status", rights_status.value)
    ids = dict(identifiers or {})
    ids.setdefault("document_id", document_id)
    return JournalHit(
        document_id=document_id,
        rank=rank,
        score=score,
        source_links=(
            make_source_link(
                source_cid=cid if _CID_RE.match(cid) else content_cid({"d": document_id}),
                artifact_id=art,
                end=max(1, min(len(document_id), 40)),
            ),
        ),
        passage_excerpt=passage_excerpt,
        identifiers=normalize_identifier_map(ids),
        metadata=meta,
    )


@dataclass
class CitationExpansionAdapter:
    """Expand backward/forward citations from a seed (cycle-safe).

    Provide a static edge list or a ``lookup_fn`` that returns edges for a
    document id. Without edges, empty success is recorded (searched, zero hits)
    so coverage still captures the adapter run.
    """

    edges: Sequence[CitationEdge | Mapping[str, Any]] = ()
    lookup_fn: Callable[[str], Sequence[CitationEdge | Mapping[str, Any]]] | None = None
    adapter_name: str = CITATION_ADAPTER_NAME
    adapter_version: str = "1.0.0"
    max_depth: int = DEFAULT_TRAVERSAL_MAX_DEPTH
    max_nodes: int = DEFAULT_TRAVERSAL_MAX_NODES
    default_rights_status: RightsStatus = RightsStatus.PUBLIC
    directions: tuple[CitationDirection, ...] = (
        CitationDirection.BACKWARD,
        CitationDirection.FORWARD,
    )
    accessible: bool = True

    def __post_init__(self) -> None:
        self.adapter_name = _identifier(self.adapter_name, "adapter_name")
        self.adapter_version = _require_str(
            self.adapter_version, "adapter_version", max_len=32
        )
        self.max_depth = _positive_int(self.max_depth, "max_depth")
        self.max_nodes = _positive_int(self.max_nodes, "max_nodes")
        self.default_rights_status = _coerce_enum(  # type: ignore[assignment]
            RightsStatus, self.default_rights_status, "default_rights_status"
        )
        dirs = tuple(
            _coerce_enum(CitationDirection, d, "directions") for d in self.directions
        )
        if not dirs:
            raise AdapterConfigError("directions must be non-empty")
        self.directions = dirs  # type: ignore[assignment]
        parsed: list[CitationEdge] = []
        for item in self.edges or ():
            if isinstance(item, CitationEdge):
                parsed.append(item)
            elif isinstance(item, Mapping):
                parsed.append(CitationEdge.from_dict(item))
            else:
                raise TypeError("edges items must be CitationEdge or mapping")
        self.edges = tuple(parsed)

    @property
    def identity(self) -> NamedAdapterIdentity:
        return NamedAdapterIdentity(
            adapter_name=self.adapter_name,
            adapter_kind=AdapterKind.OTHER,
            supported_corpora=(SearchCorpus.US_PATENTS, SearchCorpus.US_PUBLICATIONS),
            adapter_version=self.adapter_version,
            metadata={
                "expansion_mode": ExpansionMode.CITATIONS.value,
                "schema": PRIOR_ART_ADAPTERS_SCHEMA_VERSION,
            },
        )

    def supports_database(self, database: SearchDatabase) -> bool:
        return database in (
            SearchDatabase.US_PATENTS,
            SearchDatabase.US_PUBLICATIONS,
            SearchDatabase.LOCAL_PUBLIC_SNAPSHOT,
            SearchDatabase.ODP_PATENT_FILE_WRAPPER,
        )

    def search(
        self,
        query: PublicSearchQuery,
        *,
        search_time_utc: str,
        corpus_cutoff: str,
        pre_ranking_filters: PreRankingFilters | None = None,
    ) -> AdapterSearchResult:
        del pre_ranking_filters
        _iso_utc(search_time_utc, "search_time_utc")
        _iso_date_or_utc(corpus_cutoff, "corpus_cutoff")

        if not self.accessible:
            return AdapterSearchResult(
                outcome=QueryOutcomeKind.FAILURE,
                error_code="source_inaccessible",
                error_message=f"citation source {self.adapter_name} is inaccessible",
                metadata={
                    "rights_status": RightsStatus.INACCESSIBLE.value,
                    "expansion_mode": ExpansionMode.CITATIONS.value,
                },
            )

        if not self.supports_database(query.database):
            return AdapterSearchResult(
                outcome=QueryOutcomeKind.ADAPTER_NOT_REGISTERED,
                error_code="database_unsupported",
                error_message=f"{self.adapter_name} does not support {query.database.value}",
            )

        seeds = _seed_ids_from_query(query)
        if not seeds:
            return AdapterSearchResult(
                outcome=QueryOutcomeKind.MALFORMED,
                error_code="missing_seed_document",
                error_message="citation expansion requires seed_document_id filter or id in query",
                metadata={"rights_status": self.default_rights_status.value},
            )

        edge_pool: list[CitationEdge | Mapping[str, Any]] = list(self.edges)
        if self.lookup_fn is not None:
            for seed in seeds:
                try:
                    edge_pool.extend(self.lookup_fn(seed))
                except Exception as exc:  # noqa: BLE001 — record as failure
                    return AdapterSearchResult(
                        outcome=QueryOutcomeKind.UPSTREAM_ERROR,
                        error_code="citation_lookup_failed",
                        error_message=str(exc)[:512],
                        metadata={"rights_status": self.default_rights_status.value},
                    )

        result = traverse_citations(
            seeds,
            edge_pool,
            directions=self.directions,
            max_depth=self.max_depth,
            max_nodes=self.max_nodes,
        )

        hits: list[JournalHit] = []
        # Emit non-seed visited documents as hits
        seed_set = set(result.seed_ids)
        rank = 0
        for edge in result.edges:
            for doc_id, direction in (
                (edge.cited_id, CitationDirection.BACKWARD),
                (edge.citing_id, CitationDirection.FORWARD),
            ):
                if doc_id in seed_set:
                    continue
                if edge.direction is not direction and edge.direction is not CitationDirection.UNKNOWN:
                    # Only emit the target of the directed edge once
                    if edge.direction is CitationDirection.BACKWARD and doc_id != edge.cited_id:
                        continue
                    if edge.direction is CitationDirection.FORWARD and doc_id != edge.citing_id:
                        continue
                rank += 1
                if rank > query.rank_cutoff:
                    break
                hits.append(
                    _hit_from_document(
                        document_id=doc_id,
                        rank=rank,
                        score=float(max(0.0, 100.0 - rank)),
                        rights_status=edge.rights_status,
                        identifiers={
                            "document_id": doc_id,
                            "citing_id": edge.citing_id,
                            "cited_id": edge.cited_id,
                        },
                        metadata={
                            "citation_direction": edge.direction.value,
                            "expansion_mode": ExpansionMode.CITATIONS.value,
                            "cycles_skipped_count": str(len(result.cycles_skipped)),
                        },
                    )
                )
            if rank > query.rank_cutoff:
                break

        # Dedupe hits by document_id keeping best rank
        dedup: dict[str, JournalHit] = {}
        for hit in hits:
            prev = dedup.get(hit.document_id)
            if prev is None or hit.rank < prev.rank:
                dedup[hit.document_id] = hit
        final_hits = tuple(
            sorted(dedup.values(), key=lambda h: h.rank)[: query.rank_cutoff]
        )
        # Re-rank densely
        renumbered = tuple(
            JournalHit(
                document_id=h.document_id,
                rank=i + 1,
                score=h.score,
                source_links=h.source_links,
                passage_excerpt=h.passage_excerpt,
                identifiers=h.identifiers,
                metadata=h.metadata,
            )
            for i, h in enumerate(final_hits)
        )

        outcome = (
            QueryOutcomeKind.SUCCESS if renumbered else QueryOutcomeKind.EMPTY
        )
        return AdapterSearchResult(
            outcome=outcome,
            hits=renumbered,
            result_count=len(renumbered),
            source_snapshot_cid=content_cid(
                {
                    "adapter": self.adapter_name,
                    "seeds": list(result.seed_ids),
                    "visited": list(result.visited_ids),
                }
            ),
            metadata={
                "rights_status": self.default_rights_status.value,
                "expansion_mode": ExpansionMode.CITATIONS.value,
                "cycles_skipped_count": str(len(result.cycles_skipped)),
                "visited_count": str(len(result.visited_ids)),
                "truncated": "true" if result.truncated else "false",
                "max_depth": str(result.max_depth),
            },
        )


@dataclass
class FamilyExpansionAdapter:
    """Expand priority/continuation families (cycle-safe, deduplicated)."""

    members: Sequence[FamilyMember | Mapping[str, Any]] = ()
    lookup_fn: Callable[[str], Sequence[FamilyMember | Mapping[str, Any]]] | None = None
    adapter_name: str = FAMILY_ADAPTER_NAME
    adapter_version: str = "1.0.0"
    max_depth: int = DEFAULT_TRAVERSAL_MAX_DEPTH
    max_nodes: int = DEFAULT_TRAVERSAL_MAX_NODES
    default_rights_status: RightsStatus = RightsStatus.PUBLIC
    accessible: bool = True

    def __post_init__(self) -> None:
        self.adapter_name = _identifier(self.adapter_name, "adapter_name")
        self.adapter_version = _require_str(
            self.adapter_version, "adapter_version", max_len=32
        )
        self.max_depth = _positive_int(self.max_depth, "max_depth")
        self.max_nodes = _positive_int(self.max_nodes, "max_nodes")
        self.default_rights_status = _coerce_enum(  # type: ignore[assignment]
            RightsStatus, self.default_rights_status, "default_rights_status"
        )
        parsed: list[FamilyMember] = []
        for item in self.members or ():
            if isinstance(item, FamilyMember):
                parsed.append(item)
            elif isinstance(item, Mapping):
                parsed.append(FamilyMember.from_dict(item))
            else:
                raise TypeError("members items must be FamilyMember or mapping")
        self.members = deduplicate_family_members(parsed)

    @property
    def identity(self) -> NamedAdapterIdentity:
        return NamedAdapterIdentity(
            adapter_name=self.adapter_name,
            adapter_kind=AdapterKind.OTHER,
            supported_corpora=(SearchCorpus.US_PATENTS, SearchCorpus.US_PUBLICATIONS),
            adapter_version=self.adapter_version,
            metadata={
                "expansion_mode": ExpansionMode.FAMILIES.value,
                "schema": PRIOR_ART_ADAPTERS_SCHEMA_VERSION,
            },
        )

    def supports_database(self, database: SearchDatabase) -> bool:
        return database in (
            SearchDatabase.US_PATENTS,
            SearchDatabase.US_PUBLICATIONS,
            SearchDatabase.LOCAL_PUBLIC_SNAPSHOT,
            SearchDatabase.ODP_PATENT_FILE_WRAPPER,
        )

    def search(
        self,
        query: PublicSearchQuery,
        *,
        search_time_utc: str,
        corpus_cutoff: str,
        pre_ranking_filters: PreRankingFilters | None = None,
    ) -> AdapterSearchResult:
        del pre_ranking_filters
        _iso_utc(search_time_utc, "search_time_utc")
        _iso_date_or_utc(corpus_cutoff, "corpus_cutoff")

        if not self.accessible:
            return AdapterSearchResult(
                outcome=QueryOutcomeKind.FAILURE,
                error_code="source_inaccessible",
                error_message=f"family source {self.adapter_name} is inaccessible",
                metadata={
                    "rights_status": RightsStatus.INACCESSIBLE.value,
                    "expansion_mode": ExpansionMode.FAMILIES.value,
                },
            )

        if not self.supports_database(query.database):
            return AdapterSearchResult(
                outcome=QueryOutcomeKind.ADAPTER_NOT_REGISTERED,
                error_code="database_unsupported",
                error_message=f"{self.adapter_name} does not support {query.database.value}",
            )

        seeds = _seed_ids_from_query(query)
        if not seeds:
            return AdapterSearchResult(
                outcome=QueryOutcomeKind.MALFORMED,
                error_code="missing_seed_document",
                error_message="family expansion requires seed_document_id filter or id in query",
                metadata={"rights_status": self.default_rights_status.value},
            )

        member_pool: list[FamilyMember | Mapping[str, Any]] = list(self.members)
        if self.lookup_fn is not None:
            for seed in seeds:
                try:
                    member_pool.extend(self.lookup_fn(seed))
                except Exception as exc:  # noqa: BLE001
                    return AdapterSearchResult(
                        outcome=QueryOutcomeKind.UPSTREAM_ERROR,
                        error_code="family_lookup_failed",
                        error_message=str(exc)[:512],
                        metadata={"rights_status": self.default_rights_status.value},
                    )

        result = traverse_families(
            seeds,
            member_pool,
            max_depth=self.max_depth,
            max_nodes=self.max_nodes,
        )

        seed_set = set(result.seed_ids)
        hits: list[JournalHit] = []
        rank = 0
        for member in result.members:
            if member.document_id in seed_set and member.relation is FamilyRelationKind.SEED:
                continue
            rank += 1
            if rank > query.rank_cutoff:
                break
            hits.append(
                _hit_from_document(
                    document_id=member.document_id,
                    rank=rank,
                    score=float(max(0.0, 100.0 - rank)),
                    rights_status=member.rights_status,
                    identifiers={
                        "document_id": member.document_id,
                        "related_to": member.related_to or "",
                    },
                    metadata={
                        "family_relation": member.relation.value,
                        "expansion_mode": ExpansionMode.FAMILIES.value,
                        "cycles_skipped_count": str(len(result.cycles_skipped)),
                        **(
                            {"country": member.country}
                            if member.country
                            else {}
                        ),
                    },
                )
            )

        outcome = QueryOutcomeKind.SUCCESS if hits else QueryOutcomeKind.EMPTY
        return AdapterSearchResult(
            outcome=outcome,
            hits=tuple(hits),
            result_count=len(hits),
            source_snapshot_cid=content_cid(
                {
                    "adapter": self.adapter_name,
                    "seeds": list(result.seed_ids),
                    "members": [m.document_id for m in result.members],
                }
            ),
            metadata={
                "rights_status": self.default_rights_status.value,
                "expansion_mode": ExpansionMode.FAMILIES.value,
                "cycles_skipped_count": str(len(result.cycles_skipped)),
                "visited_count": str(len(result.visited_ids)),
                "member_count": str(len(result.members)),
                "truncated": "true" if result.truncated else "false",
                "max_depth": str(result.max_depth),
            },
        )


@dataclass
class ForeignPatentAdapter:
    """Named foreign-patent metadata/search adapter (must run to claim coverage).

    Provide static foreign hits or a ``search_fn``. Without a backend and
    without static hits, returns failure so the corpus stays unsearched.
    """

    hits: Sequence[JournalHit | Mapping[str, Any]] = ()
    search_fn: Callable[
        [PublicSearchQuery, str, str, PreRankingFilters | None], AdapterSearchResult
    ] | None = None
    adapter_name: str = FOREIGN_PATENT_ADAPTER_NAME
    adapter_version: str = "1.0.0"
    default_rights_status: RightsStatus = RightsStatus.PUBLIC
    accessible: bool = True
    licensed: bool = True

    def __post_init__(self) -> None:
        self.adapter_name = _identifier(self.adapter_name, "adapter_name")
        self.adapter_version = _require_str(
            self.adapter_version, "adapter_version", max_len=32
        )
        self.default_rights_status = _coerce_enum(  # type: ignore[assignment]
            RightsStatus, self.default_rights_status, "default_rights_status"
        )
        parsed: list[JournalHit] = []
        for item in self.hits or ():
            if isinstance(item, JournalHit):
                parsed.append(item)
            elif isinstance(item, Mapping):
                parsed.append(JournalHit.from_dict(item))
            else:
                raise TypeError("hits items must be JournalHit or mapping")
        self.hits = tuple(parsed)

    @property
    def identity(self) -> NamedAdapterIdentity:
        return NamedAdapterIdentity(
            adapter_name=self.adapter_name,
            adapter_kind=AdapterKind.FOREIGN_PATENT,
            supported_corpora=(SearchCorpus.FOREIGN_PATENTS,),
            adapter_version=self.adapter_version,
            metadata={
                "expansion_mode": ExpansionMode.FOREIGN.value,
                "schema": PRIOR_ART_ADAPTERS_SCHEMA_VERSION,
                "licensed": "true" if self.licensed else "false",
            },
        )

    def supports_database(self, database: SearchDatabase) -> bool:
        return database is SearchDatabase.FOREIGN_PATENTS

    def search(
        self,
        query: PublicSearchQuery,
        *,
        search_time_utc: str,
        corpus_cutoff: str,
        pre_ranking_filters: PreRankingFilters | None = None,
    ) -> AdapterSearchResult:
        _iso_utc(search_time_utc, "search_time_utc")
        _iso_date_or_utc(corpus_cutoff, "corpus_cutoff")

        if not self.supports_database(query.database):
            return AdapterSearchResult(
                outcome=QueryOutcomeKind.ADAPTER_NOT_REGISTERED,
                error_code="database_unsupported",
                error_message=f"{self.adapter_name} does not support {query.database.value}",
            )

        if not self.accessible:
            return AdapterSearchResult(
                outcome=QueryOutcomeKind.FAILURE,
                error_code="source_inaccessible",
                error_message=f"foreign-patent source {self.adapter_name} is inaccessible",
                metadata={
                    "rights_status": RightsStatus.INACCESSIBLE.value,
                    "named_gap": self.adapter_name,
                },
            )

        if not self.licensed:
            return AdapterSearchResult(
                outcome=QueryOutcomeKind.FAILURE,
                error_code="source_unlicensed",
                error_message=(
                    f"foreign-patent source {self.adapter_name} is unlicensed; "
                    f"corpus remains a named gap"
                ),
                metadata={
                    "rights_status": RightsStatus.UNLICENSED.value,
                    "named_gap": self.adapter_name,
                },
            )

        if self.search_fn is not None:
            result = self.search_fn(
                query, search_time_utc, corpus_cutoff, pre_ranking_filters
            )
            # Ensure rights metadata is present
            meta = dict(result.metadata)
            meta.setdefault("rights_status", self.default_rights_status.value)
            meta.setdefault("expansion_mode", ExpansionMode.FOREIGN.value)
            return AdapterSearchResult(
                outcome=result.outcome,
                hits=result.hits,
                retries=result.retries,
                source_snapshot_cid=result.source_snapshot_cid,
                transport_receipt_id=result.transport_receipt_id,
                status_code=result.status_code,
                error_code=result.error_code,
                error_message=result.error_message,
                result_count=result.result_count,
                metadata=meta,
            )

        if not self.hits:
            return AdapterSearchResult(
                outcome=QueryOutcomeKind.FAILURE,
                error_code="adapter_backend_unavailable",
                error_message=(
                    f"named adapter {self.adapter_name} has no search backend; "
                    f"corpus remains unsearched"
                ),
                retries=(
                    RetryAttemptRecord(
                        attempt=1,
                        outcome=QueryOutcomeKind.FAILURE,
                        error_code="adapter_backend_unavailable",
                    ),
                ),
                metadata={
                    "rights_status": self.default_rights_status.value,
                    "named_gap": self.adapter_name,
                },
            )

        # Static hits: filter by rank cutoff, normalize identifiers
        limited = []
        for i, hit in enumerate(self.hits[: query.rank_cutoff]):
            meta = dict(hit.metadata)
            meta.setdefault("rights_status", self.default_rights_status.value)
            meta.setdefault("expansion_mode", ExpansionMode.FOREIGN.value)
            limited.append(
                JournalHit(
                    document_id=normalize_document_id(hit.document_id),
                    rank=i + 1,
                    score=hit.score,
                    source_links=hit.source_links,
                    passage_excerpt=hit.passage_excerpt,
                    identifiers=normalize_identifier_map(dict(hit.identifiers)),
                    metadata=meta,
                )
            )
        outcome = QueryOutcomeKind.SUCCESS if limited else QueryOutcomeKind.EMPTY
        return AdapterSearchResult(
            outcome=outcome,
            hits=tuple(limited),
            result_count=len(limited),
            source_snapshot_cid=content_cid(
                {"adapter": self.adapter_name, "hits": [h.document_id for h in limited]}
            ),
            metadata={
                "rights_status": self.default_rights_status.value,
                "expansion_mode": ExpansionMode.FOREIGN.value,
            },
        )


@dataclass
class NplAdapter:
    """Named NPL metadata/search adapter with rights-gated body text.

    Unlicensed NPL body text is never retained. Public release of NPL content
    requires :meth:`assert_npl_records_safe_for_public_release` approval.
    """

    records: Sequence[NplRecord | Mapping[str, Any]] = ()
    search_fn: Callable[
        [PublicSearchQuery, str, str, PreRankingFilters | None], AdapterSearchResult
    ] | None = None
    adapter_name: str = NPL_ADAPTER_NAME
    adapter_version: str = "1.0.0"
    default_rights_status: RightsStatus = RightsStatus.UNLICENSED
    accessible: bool = True
    licensed: bool = False

    def __post_init__(self) -> None:
        self.adapter_name = _identifier(self.adapter_name, "adapter_name")
        self.adapter_version = _require_str(
            self.adapter_version, "adapter_version", max_len=32
        )
        self.default_rights_status = _coerce_enum(  # type: ignore[assignment]
            RightsStatus, self.default_rights_status, "default_rights_status"
        )
        parsed: list[NplRecord] = []
        for item in self.records or ():
            if isinstance(item, NplRecord):
                parsed.append(item)
            elif isinstance(item, Mapping):
                parsed.append(NplRecord.from_dict(item))
            else:
                raise TypeError("records items must be NplRecord or mapping")
        self.records = tuple(parsed)

    @property
    def identity(self) -> NamedAdapterIdentity:
        return NamedAdapterIdentity(
            adapter_name=self.adapter_name,
            adapter_kind=AdapterKind.NPL,
            supported_corpora=(SearchCorpus.NPL,),
            adapter_version=self.adapter_version,
            metadata={
                "expansion_mode": ExpansionMode.NPL.value,
                "schema": PRIOR_ART_ADAPTERS_SCHEMA_VERSION,
                "licensed": "true" if self.licensed else "false",
                "default_rights_status": self.default_rights_status.value,
            },
        )

    def supports_database(self, database: SearchDatabase) -> bool:
        return database is SearchDatabase.NPL

    def search(
        self,
        query: PublicSearchQuery,
        *,
        search_time_utc: str,
        corpus_cutoff: str,
        pre_ranking_filters: PreRankingFilters | None = None,
    ) -> AdapterSearchResult:
        _iso_utc(search_time_utc, "search_time_utc")
        _iso_date_or_utc(corpus_cutoff, "corpus_cutoff")

        if not self.supports_database(query.database):
            return AdapterSearchResult(
                outcome=QueryOutcomeKind.ADAPTER_NOT_REGISTERED,
                error_code="database_unsupported",
                error_message=f"{self.adapter_name} does not support {query.database.value}",
            )

        if not self.accessible:
            return AdapterSearchResult(
                outcome=QueryOutcomeKind.FAILURE,
                error_code="source_inaccessible",
                error_message=f"NPL source {self.adapter_name} is inaccessible",
                metadata={
                    "rights_status": RightsStatus.INACCESSIBLE.value,
                    "named_gap": self.adapter_name,
                },
            )

        if not self.licensed and self.search_fn is None and not self.records:
            return AdapterSearchResult(
                outcome=QueryOutcomeKind.FAILURE,
                error_code="source_unlicensed",
                error_message=(
                    f"NPL source {self.adapter_name} is unlicensed and has no "
                    f"approved records; corpus remains a named gap"
                ),
                metadata={
                    "rights_status": RightsStatus.UNLICENSED.value,
                    "named_gap": self.adapter_name,
                },
            )

        if self.search_fn is not None:
            result = self.search_fn(
                query, search_time_utc, corpus_cutoff, pre_ranking_filters
            )
            # Strip any body-like excerpts unless rights allow
            safe_hits: list[JournalHit] = []
            for hit in result.hits:
                meta = dict(hit.metadata)
                rights_raw = meta.get("rights_status", self.default_rights_status.value)
                try:
                    rights = _coerce_enum(RightsStatus, rights_raw, "rights_status")
                except (TypeError, ValueError):
                    rights = self.default_rights_status
                assert isinstance(rights, RightsStatus)
                meta["rights_status"] = rights.value
                meta.setdefault("expansion_mode", ExpansionMode.NPL.value)
                excerpt = hit.passage_excerpt
                if excerpt is not None and not rights_allows_body_text(rights):
                    excerpt = None
                safe_hits.append(
                    JournalHit(
                        document_id=hit.document_id,
                        rank=hit.rank,
                        score=hit.score,
                        source_links=hit.source_links,
                        passage_excerpt=excerpt,
                        identifiers=hit.identifiers,
                        metadata=meta,
                    )
                )
            meta = dict(result.metadata)
            meta.setdefault("rights_status", self.default_rights_status.value)
            meta.setdefault("expansion_mode", ExpansionMode.NPL.value)
            return AdapterSearchResult(
                outcome=result.outcome,
                hits=tuple(safe_hits),
                retries=result.retries,
                source_snapshot_cid=result.source_snapshot_cid,
                transport_receipt_id=result.transport_receipt_id,
                status_code=result.status_code,
                error_code=result.error_code,
                error_message=result.error_message,
                result_count=len(safe_hits) if outcome_claims_search(result.outcome) else result.result_count,
                metadata=meta,
            )

        if not self.records:
            return AdapterSearchResult(
                outcome=QueryOutcomeKind.FAILURE,
                error_code="adapter_backend_unavailable",
                error_message=(
                    f"named adapter {self.adapter_name} has no NPL backend; "
                    f"corpus remains unsearched"
                ),
                retries=(
                    RetryAttemptRecord(
                        attempt=1,
                        outcome=QueryOutcomeKind.FAILURE,
                        error_code="adapter_backend_unavailable",
                    ),
                ),
                metadata={
                    "rights_status": self.default_rights_status.value,
                    "named_gap": self.adapter_name,
                },
            )

        q_lower = query.query_text.lower()
        matched: list[NplRecord] = []
        for rec in self.records:
            hay = " ".join(
                filter(
                    None,
                    [
                        rec.document_id,
                        rec.title or "",
                        rec.identifier or "",
                        " ".join(rec.metadata.values()),
                    ],
                )
            ).lower()
            if not q_lower or any(tok in hay for tok in q_lower.split() if len(tok) > 2):
                matched.append(rec)
            if len(matched) >= query.rank_cutoff:
                break

        hits: list[JournalHit] = []
        for i, rec in enumerate(matched[: query.rank_cutoff]):
            excerpt = rec.body_text if rights_allows_body_text(rec.rights_status) else None
            hits.append(
                _hit_from_document(
                    document_id=rec.document_id,
                    rank=i + 1,
                    score=float(max(0.0, 100.0 - i)),
                    rights_status=rec.rights_status,
                    identifiers={
                        "document_id": rec.document_id,
                        **({"doi": rec.identifier} if rec.identifier else {}),
                    },
                    passage_excerpt=excerpt,
                    metadata={
                        "expansion_mode": ExpansionMode.NPL.value,
                        "rights_status": rec.rights_status.value,
                        **(
                            {"rights_approval_id": rec.rights_approval_id}
                            if rec.rights_approval_id
                            else {}
                        ),
                        **({"title": rec.title} if rec.title else {}),
                    },
                )
            )

        outcome = QueryOutcomeKind.SUCCESS if hits else QueryOutcomeKind.EMPTY
        return AdapterSearchResult(
            outcome=outcome,
            hits=tuple(hits),
            result_count=len(hits),
            source_snapshot_cid=content_cid(
                {
                    "adapter": self.adapter_name,
                    "records": [r.document_id for r in matched],
                }
            ),
            metadata={
                "rights_status": self.default_rights_status.value,
                "expansion_mode": ExpansionMode.NPL.value,
                "licensed": "true" if self.licensed else "false",
            },
        )


# ---------------------------------------------------------------------------
# Registry / builders
# ---------------------------------------------------------------------------


@dataclass
class PriorArtAdapterRegistry:
    """Register coverage adapters for runtime composition."""

    adapters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized: dict[str, Any] = {}
        for key, adapter in dict(self.adapters).items():
            identity = adapter.identity
            normalized[identity.adapter_name] = adapter
            if str(key) != identity.adapter_name:
                normalized[str(key)] = adapter
        self.adapters = MappingProxyType(normalized)  # type: ignore[assignment]

    def register(self, adapter: Any) -> "PriorArtAdapterRegistry":
        merged = dict(self.adapters)
        merged[adapter.identity.adapter_name] = adapter
        return PriorArtAdapterRegistry(adapters=merged)

    def get(self, name: str) -> Any | None:
        return self.adapters.get(name)

    def as_runtime_adapters(self) -> Mapping[str, Any]:
        """Return adapters suitable for :class:`PriorArtSearchRuntime`."""
        return dict(self.adapters)

    def names(self) -> tuple[str, ...]:
        # Unique identity names
        seen: set[str] = set()
        out: list[str] = []
        for adapter in self.adapters.values():
            name = adapter.identity.adapter_name
            if name not in seen:
                seen.add(name)
                out.append(name)
        return tuple(sorted(out))


def build_coverage_adapters(
    *,
    citation: CitationExpansionAdapter | None = None,
    family: FamilyExpansionAdapter | None = None,
    foreign: ForeignPatentAdapter | None = None,
    npl: NplAdapter | None = None,
) -> PriorArtAdapterRegistry:
    """Assemble a registry from optional coverage adapters."""
    adapters: dict[str, Any] = {}
    for adapter in (citation, family, foreign, npl):
        if adapter is not None:
            adapters[adapter.identity.adapter_name] = adapter
    return PriorArtAdapterRegistry(adapters=adapters)


__all__ = [
    "PRIOR_ART_ADAPTERS_CODE_VERSION",
    "PRIOR_ART_ADAPTERS_INTERFACE",
    "PRIOR_ART_ADAPTERS_SCHEMA_VERSION",
    "CITATION_ADAPTER_NAME",
    "FAMILY_ADAPTER_NAME",
    "FOREIGN_PATENT_ADAPTER_NAME",
    "NPL_ADAPTER_NAME",
    "DEFAULT_TRAVERSAL_MAX_DEPTH",
    "DEFAULT_TRAVERSAL_MAX_NODES",
    "AdapterConfigError",
    "CitationDirection",
    "CitationEdge",
    "CitationExpansionAdapter",
    "CitationTraversalResult",
    "CoverageSearchAdapter",
    "ExpansionMode",
    "FamilyExpansionAdapter",
    "FamilyMember",
    "FamilyRelationKind",
    "FamilyTraversalResult",
    "ForeignPatentAdapter",
    "IdentifierNormalizationError",
    "NplAdapter",
    "NplRecord",
    "NplRightsError",
    "PriorArtAdapterError",
    "PriorArtAdapterRegistry",
    "RightsStatus",
    "TraversalCycleError",
    "assert_npl_records_safe_for_public_release",
    "build_coverage_adapters",
    "canonical_json",
    "content_cid",
    "content_digest",
    "deduplicate_family_members",
    "normalize_document_id",
    "normalize_identifier_map",
    "rights_allows_body_text",
    "rights_blocks_public_release",
    "traverse_citations",
    "traverse_families",
]
