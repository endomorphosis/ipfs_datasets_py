"""Reason-labeled proof dependency graph (IPS-013).

Datasets semantic authority for the directed, content-addressed dependency
graph used by invalidation and cache-key root construction.

Edges store ``(from, to, edge_type, reason_cid)`` with closed edge types.
Direction is normative: ``from`` is the prerequisite and ``to`` is the
dependent.  Invalidation walks forward from a changed prerequisite; a unit's
dependency root walks incoming edges back to every statement-relevant
prerequisite and commits to those nodes and reasons.

Rules:

* unknown edge types, duplicate contradictions, self-loops, and cycles fail
  closed;
* insertion order cannot affect adjacency, roots, or canonical identity;
* truncated / unknown frontiers never narrow a root (complete is false or
  the strict root calculator raises);
* imports have no side effects (CID minting reuses identity helpers lazily).

Interfaces: ``ProofDependencyGraph``, ``ProofDependencyEdge``,
``DependencyEdgeType``, ``compute_dependency_root``.
"""

from __future__ import annotations

import json
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final

from .identity import (
    ABSENCE_TOKEN,
    IdentityError,
    canonical_cid,
    validate_profile_cid,
)

DEPENDENCY_GRAPH_SUBSET: Final[str] = "ips/dependency-graph@1"
DEPENDENCY_GRAPH_NAMESPACE: Final[str] = (
    "ipfs_datasets_py/logic/zkp/incremental_sealing/dependency_graph"
)
SCHEMA_MAJOR: Final[int] = 1
DEPENDENCY_GRAPH_SCHEMA_VERSION: Final[str] = f"graph@{SCHEMA_MAJOR}"
DEPENDENCY_GRAPH_SCHEMA: Final[str] = (
    f"{DEPENDENCY_GRAPH_NAMESPACE}/proof-dependency-graph@{SCHEMA_MAJOR}"
)
DEPENDENCY_EDGE_SCHEMA: Final[str] = (
    f"{DEPENDENCY_GRAPH_NAMESPACE}/proof-dependency-edge@{SCHEMA_MAJOR}"
)
DEPENDENCY_NODE_SCHEMA: Final[str] = (
    f"{DEPENDENCY_GRAPH_NAMESPACE}/proof-dependency-node@{SCHEMA_MAJOR}"
)
DEPENDENCY_ROOT_SCHEMA: Final[str] = (
    f"{DEPENDENCY_GRAPH_NAMESPACE}/dependency-root@{SCHEMA_MAJOR}"
)

MAX_IDENTIFIER_BYTES: Final[int] = 512
MAX_GRAPH_NODES: Final[int] = 1 << 20
MAX_GRAPH_EDGES: Final[int] = 1 << 20
MAX_CLOSURE_NODES: Final[int] = 1 << 18
MAX_EXPLANATION_PATHS: Final[int] = 1 << 12
MAX_EXPLANATION_DEPTH: Final[int] = 256

# Closed ordered edge types (plan §6).
DEPENDENCY_EDGE_TYPES: Final[tuple[str, ...]] = (
    "source_depends_on",
    "imports",
    "calls",
    "schema_depends_on",
    "test_covers",
    "fixture_depends_on",
    "config_depends_on",
    "proof_depends_on",
    "aggregate_contains",
    "supersedes",
    "invalidates",
)

# Closed ordered node kinds for typed artifact / symbol / unit graphs.
DEPENDENCY_NODE_KINDS: Final[tuple[str, ...]] = (
    "artifact",
    "symbol",
    "unit",
    "fixture",
    "config",
    "schema",
    "aggregate",
    "environment",
    "policy",
    "unknown",
)


class DependencyGraphError(ValueError):
    """Proof dependency graph contract violation."""


class DependencyEdgeType(str, Enum):
    """Closed set of reason-labeled dependency edge kinds."""

    SOURCE_DEPENDS_ON = "source_depends_on"
    IMPORTS = "imports"
    CALLS = "calls"
    SCHEMA_DEPENDS_ON = "schema_depends_on"
    TEST_COVERS = "test_covers"
    FIXTURE_DEPENDS_ON = "fixture_depends_on"
    CONFIG_DEPENDS_ON = "config_depends_on"
    PROOF_DEPENDS_ON = "proof_depends_on"
    AGGREGATE_CONTAINS = "aggregate_contains"
    SUPERSEDES = "supersedes"
    INVALIDATES = "invalidates"


class DependencyNodeKind(str, Enum):
    """Closed set of typed graph node kinds."""

    ARTIFACT = "artifact"
    SYMBOL = "symbol"
    UNIT = "unit"
    FIXTURE = "fixture"
    CONFIG = "config"
    SCHEMA = "schema"
    AGGREGATE = "aggregate"
    ENVIRONMENT = "environment"
    POLICY = "policy"
    UNKNOWN = "unknown"


def closed_dependency_edge_types() -> frozenset[str]:
    return frozenset(DEPENDENCY_EDGE_TYPES)


def closed_dependency_node_kinds() -> frozenset[str]:
    return frozenset(DEPENDENCY_NODE_KINDS)


def parse_dependency_edge_type(value: Any) -> DependencyEdgeType:
    """Parse a closed dependency edge type."""

    if isinstance(value, DependencyEdgeType):
        return value
    if not isinstance(value, str) or not value.strip():
        raise DependencyGraphError("edge_type must be a non-empty closed string")
    text = value.strip()
    try:
        return DependencyEdgeType(text)
    except ValueError as exc:
        raise DependencyGraphError(
            f"unknown DependencyEdgeType {value!r}; "
            f"closed set is {list(DEPENDENCY_EDGE_TYPES)}"
        ) from exc


def parse_dependency_node_kind(value: Any) -> DependencyNodeKind:
    """Parse a closed dependency node kind."""

    if isinstance(value, DependencyNodeKind):
        return value
    if not isinstance(value, str) or not value.strip():
        raise DependencyGraphError("node kind must be a non-empty closed string")
    text = value.strip()
    try:
        return DependencyNodeKind(text)
    except ValueError as exc:
        raise DependencyGraphError(
            f"unknown DependencyNodeKind {value!r}; "
            f"closed set is {list(DEPENDENCY_NODE_KINDS)}"
        ) from exc


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DependencyGraphError(f"{field} must be a non-empty string")
    text = value.strip()
    if text != value:
        raise DependencyGraphError(f"{field} must not have surrounding whitespace")
    if len(text.encode("utf-8")) > MAX_IDENTIFIER_BYTES:
        raise DependencyGraphError(f"{field} exceeds {MAX_IDENTIFIER_BYTES} bytes")
    return text


def _require_cid(value: Any, field: str) -> str:
    text = _require_text(value, field)
    try:
        return validate_profile_cid(text, domain="any")
    except IdentityError as exc:
        raise DependencyGraphError(f"{field}: {exc}") from exc


def _require_bool(value: Any, field: str) -> bool:
    if type(value) is not bool:
        raise DependencyGraphError(f"{field} must be a boolean")
    return value


def _node_cid(payload: Mapping[str, Any]) -> str:
    try:
        return canonical_cid(dict(payload))
    except IdentityError as exc:
        raise DependencyGraphError(str(exc)) from exc


def mint_reason_cid(payload: Mapping[str, Any] | None = None, **fields: Any) -> str:
    """Mint a content-addressed reason CID for an edge explanation."""

    body: dict[str, Any]
    if payload is None:
        body = dict(fields)
    else:
        if not isinstance(payload, Mapping):
            raise DependencyGraphError("reason payload must be a mapping")
        body = dict(payload)
        body.update(fields)
    if "schema" not in body:
        body = {
            "schema": f"{DEPENDENCY_GRAPH_NAMESPACE}/reason@{SCHEMA_MAJOR}",
            **body,
        }
    return _node_cid(body)


# ---------------------------------------------------------------------------
# Node and edge records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProofDependencyNode:
    """Typed node in the proof dependency graph."""

    node_id: str
    kind: DependencyNodeKind
    label: str = ABSENCE_TOKEN
    truncated: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_id", _require_text(self.node_id, "node_id"))
        object.__setattr__(self, "kind", parse_dependency_node_kind(self.kind))
        label = self.label
        if label == ABSENCE_TOKEN:
            object.__setattr__(self, "label", ABSENCE_TOKEN)
        else:
            object.__setattr__(self, "label", _require_text(label, "label"))
        object.__setattr__(
            self, "truncated", _require_bool(self.truncated, "truncated")
        )

    def to_canonical(self) -> dict[str, Any]:
        return {
            "schema": DEPENDENCY_NODE_SCHEMA,
            "node_id": self.node_id,
            "kind": self.kind.value,
            "label": self.label,
            "truncated": self.truncated,
        }

    def to_canonical_json(self) -> str:
        return json.dumps(
            self.to_canonical(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )

    @classmethod
    def from_canonical(cls, payload: Mapping[str, Any]) -> ProofDependencyNode:
        if not isinstance(payload, Mapping):
            raise DependencyGraphError("node payload must be a mapping")
        if "truncated" in payload:
            truncated = payload["truncated"]
        else:
            truncated = False
        return cls(
            node_id=str(payload.get("node_id") or ""),
            kind=payload.get("kind") or DependencyNodeKind.UNKNOWN,
            label=payload.get("label", ABSENCE_TOKEN),
            truncated=truncated,
        )


@dataclass(frozen=True, slots=True)
class ProofDependencyEdge:
    """Reason-labeled directed edge: prerequisite ``from_id`` -> dependent ``to_id``."""

    from_id: str
    to_id: str
    edge_type: DependencyEdgeType
    reason_cid: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "from_id", _require_text(self.from_id, "from_id"))
        object.__setattr__(self, "to_id", _require_text(self.to_id, "to_id"))
        object.__setattr__(
            self, "edge_type", parse_dependency_edge_type(self.edge_type)
        )
        object.__setattr__(
            self, "reason_cid", _require_cid(self.reason_cid, "reason_cid")
        )
        if self.from_id == self.to_id:
            raise DependencyGraphError(
                f"self-loop edges are rejected: {self.from_id!r}"
            )

    @property
    def prerequisite_id(self) -> str:
        return self.from_id

    @property
    def dependent_id(self) -> str:
        return self.to_id

    def sort_key(self) -> tuple[str, str, str, str]:
        return (
            self.from_id,
            self.to_id,
            self.edge_type.value,
            self.reason_cid,
        )

    def to_canonical(self) -> dict[str, Any]:
        return {
            "schema": DEPENDENCY_EDGE_SCHEMA,
            "from_id": self.from_id,
            "to_id": self.to_id,
            "edge_type": self.edge_type.value,
            "reason_cid": self.reason_cid,
        }

    def to_canonical_json(self) -> str:
        return json.dumps(
            self.to_canonical(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )

    def edge_cid(self) -> str:
        return _node_cid(self.to_canonical())

    @classmethod
    def from_canonical(cls, payload: Mapping[str, Any]) -> ProofDependencyEdge:
        if not isinstance(payload, Mapping):
            raise DependencyGraphError("edge payload must be a mapping")
        return cls(
            from_id=str(payload.get("from_id") or payload.get("from") or ""),
            to_id=str(payload.get("to_id") or payload.get("to") or ""),
            edge_type=payload.get("edge_type") or "",
            reason_cid=str(payload.get("reason_cid") or ""),
        )


@dataclass(frozen=True, slots=True)
class DependencyRoot:
    """Transitive prerequisite root for one dependent unit.

    Commits to every transitive prerequisite node and reason relevant to the
    statement.  Insertion order of the source graph cannot affect identity.
    """

    unit_id: str
    prerequisite_node_ids: tuple[str, ...]
    reason_cids: tuple[str, ...]
    edge_cids: tuple[str, ...]
    complete: bool
    dependency_graph_schema_version: str = DEPENDENCY_GRAPH_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "unit_id", _require_text(self.unit_id, "unit_id"))
        prereqs = tuple(
            _require_text(item, "prerequisite_node_ids")
            for item in self.prerequisite_node_ids
        )
        if list(prereqs) != sorted(prereqs):
            raise DependencyGraphError(
                "prerequisite_node_ids must be canonically sorted"
            )
        if len(set(prereqs)) != len(prereqs):
            raise DependencyGraphError(
                "prerequisite_node_ids must not contain duplicates"
            )
        object.__setattr__(self, "prerequisite_node_ids", prereqs)
        reasons = tuple(
            _require_cid(item, "reason_cids") for item in self.reason_cids
        )
        if list(reasons) != sorted(reasons):
            raise DependencyGraphError("reason_cids must be canonically sorted")
        if len(set(reasons)) != len(reasons):
            raise DependencyGraphError("reason_cids must not contain duplicates")
        object.__setattr__(self, "reason_cids", reasons)
        edge_cids = tuple(_require_cid(item, "edge_cids") for item in self.edge_cids)
        if list(edge_cids) != sorted(edge_cids):
            raise DependencyGraphError("edge_cids must be canonically sorted")
        if len(set(edge_cids)) != len(edge_cids):
            raise DependencyGraphError("edge_cids must not contain duplicates")
        object.__setattr__(self, "edge_cids", edge_cids)
        object.__setattr__(
            self, "complete", _require_bool(self.complete, "complete")
        )
        object.__setattr__(
            self,
            "dependency_graph_schema_version",
            _require_text(
                self.dependency_graph_schema_version,
                "dependency_graph_schema_version",
            ),
        )

    def to_canonical(self) -> dict[str, Any]:
        return {
            "schema": DEPENDENCY_ROOT_SCHEMA,
            "unit_id": self.unit_id,
            "prerequisite_node_ids": list(self.prerequisite_node_ids),
            "reason_cids": list(self.reason_cids),
            "edge_cids": list(self.edge_cids),
            "complete": self.complete,
            "dependency_graph_schema_version": self.dependency_graph_schema_version,
        }

    def to_canonical_json(self) -> str:
        return json.dumps(
            self.to_canonical(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )

    def root_cid(self) -> str:
        if not self.complete:
            raise DependencyGraphError(
                "truncated dependency roots fail closed; complete must be true"
            )
        return _node_cid(self.to_canonical())


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------


class ProofDependencyGraph:
    """Directed reason-labeled dependency graph.

    Stores prerequisite -> dependent edges with closed types and content-
    addressed reasons.  Adjacency and roots are deterministic regardless of
    insertion order.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, ProofDependencyNode] = {}
        # Keyed by (from_id, to_id, edge_type) -> edge (reason must agree).
        self._edges: dict[tuple[str, str, str], ProofDependencyEdge] = {}
        self._outgoing: dict[str, set[str]] = defaultdict(set)
        self._incoming: dict[str, set[str]] = defaultdict(set)
        # Full edge multiset index by endpoint for typed adjacency.
        self._out_edges: dict[str, list[ProofDependencyEdge]] = defaultdict(list)
        self._in_edges: dict[str, list[ProofDependencyEdge]] = defaultdict(list)

    # -- mutation -----------------------------------------------------------

    def add_node(
        self,
        node_id: str,
        kind: DependencyNodeKind | str = DependencyNodeKind.UNIT,
        *,
        label: str = ABSENCE_TOKEN,
        truncated: bool = False,
    ) -> ProofDependencyNode:
        """Register or reaffirm a typed node.

        Reaffirmation with identical fields is idempotent.  Contradictory
        kind/label/truncated flags fail closed.
        """

        node = ProofDependencyNode(
            node_id=node_id,
            kind=kind,
            label=label,
            truncated=truncated,
        )
        if len(self._nodes) >= MAX_GRAPH_NODES and node.node_id not in self._nodes:
            raise DependencyGraphError(
                f"graph exceeds MAX_GRAPH_NODES={MAX_GRAPH_NODES}"
            )
        existing = self._nodes.get(node.node_id)
        if existing is not None and existing != node:
            raise DependencyGraphError(
                f"duplicate node contradiction for {node.node_id!r}: "
                f"{existing.to_canonical()} vs {node.to_canonical()}"
            )
        self._nodes[node.node_id] = node
        return node

    def mark_truncated(self, node_id: str) -> ProofDependencyNode:
        """Mark a node as an unknown / truncated discovery frontier."""

        node_id = _require_text(node_id, "node_id")
        existing = self._nodes.get(node_id)
        if existing is None:
            return self.add_node(
                node_id, DependencyNodeKind.UNKNOWN, truncated=True
            )
        if existing.truncated:
            return existing
        updated = ProofDependencyNode(
            node_id=existing.node_id,
            kind=existing.kind,
            label=existing.label,
            truncated=True,
        )
        self._nodes[node_id] = updated
        return updated

    def add_edge(
        self,
        from_id: str,
        to_id: str,
        edge_type: DependencyEdgeType | str,
        reason_cid: str,
        *,
        from_kind: DependencyNodeKind | str | None = None,
        to_kind: DependencyNodeKind | str | None = None,
    ) -> ProofDependencyEdge:
        """Add a prerequisite -> dependent edge with a content-addressed reason.

        Unknown edge types, self-loops, cycles, and reason contradictions fail
        closed.  Endpoints are registered when ``from_kind`` / ``to_kind`` are
        supplied; otherwise they must already exist.
        """

        edge = ProofDependencyEdge(
            from_id=from_id,
            to_id=to_id,
            edge_type=edge_type,
            reason_cid=reason_cid,
        )
        if from_kind is not None:
            self.add_node(edge.from_id, from_kind)
        if to_kind is not None:
            self.add_node(edge.to_id, to_kind)
        if edge.from_id not in self._nodes:
            raise DependencyGraphError(
                f"unknown from_id node {edge.from_id!r}; add_node first"
            )
        if edge.to_id not in self._nodes:
            raise DependencyGraphError(
                f"unknown to_id node {edge.to_id!r}; add_node first"
            )
        if len(self._edges) >= MAX_GRAPH_EDGES:
            key = (edge.from_id, edge.to_id, edge.edge_type.value)
            if key not in self._edges:
                raise DependencyGraphError(
                    f"graph exceeds MAX_GRAPH_EDGES={MAX_GRAPH_EDGES}"
                )

        key = (edge.from_id, edge.to_id, edge.edge_type.value)
        existing = self._edges.get(key)
        if existing is not None:
            if existing.reason_cid != edge.reason_cid:
                raise DependencyGraphError(
                    "duplicate edge contradiction for "
                    f"{key}: reason {existing.reason_cid!r} vs {edge.reason_cid!r}"
                )
            return existing

        # Cycle check on the directed prerequisite -> dependent relation.
        if self._would_create_cycle(edge.from_id, edge.to_id):
            raise DependencyGraphError(
                f"illegal cycle: adding {edge.from_id!r} -> {edge.to_id!r} "
                f"({edge.edge_type.value})"
            )

        self._edges[key] = edge
        self._outgoing[edge.from_id].add(edge.to_id)
        self._incoming[edge.to_id].add(edge.from_id)
        self._out_edges[edge.from_id].append(edge)
        self._in_edges[edge.to_id].append(edge)
        return edge

    def _would_create_cycle(self, from_id: str, to_id: str) -> bool:
        """Return True if adding from_id -> to_id would create a directed cycle.

        A cycle exists if ``from_id`` is already reachable from ``to_id`` via
        existing forward (dependent) edges.
        """

        if from_id == to_id:
            return True
        seen: set[str] = set()
        queue: deque[str] = deque([to_id])
        while queue:
            current = queue.popleft()
            if current == from_id:
                return True
            if current in seen:
                continue
            seen.add(current)
            for nxt in self._outgoing.get(current, ()):
                if nxt not in seen:
                    queue.append(nxt)
        return False

    # -- inspection ---------------------------------------------------------

    def has_node(self, node_id: str) -> bool:
        return node_id in self._nodes

    def get_node(self, node_id: str) -> ProofDependencyNode:
        try:
            return self._nodes[node_id]
        except KeyError as exc:
            raise DependencyGraphError(f"unknown node {node_id!r}") from exc

    def nodes(self) -> tuple[ProofDependencyNode, ...]:
        return tuple(
            self._nodes[node_id] for node_id in sorted(self._nodes)
        )

    def node_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._nodes))

    def edges(self) -> tuple[ProofDependencyEdge, ...]:
        return tuple(
            sorted(self._edges.values(), key=lambda edge: edge.sort_key())
        )

    def edge_count(self) -> int:
        return len(self._edges)

    def node_count(self) -> int:
        return len(self._nodes)

    def outgoing_edges(self, node_id: str) -> tuple[ProofDependencyEdge, ...]:
        node_id = _require_text(node_id, "node_id")
        return tuple(
            sorted(
                self._out_edges.get(node_id, ()),
                key=lambda edge: edge.sort_key(),
            )
        )

    def incoming_edges(self, node_id: str) -> tuple[ProofDependencyEdge, ...]:
        node_id = _require_text(node_id, "node_id")
        return tuple(
            sorted(
                self._in_edges.get(node_id, ()),
                key=lambda edge: edge.sort_key(),
            )
        )

    def dependents(self, node_id: str) -> tuple[str, ...]:
        """Direct dependents of a prerequisite (forward one hop)."""

        node_id = _require_text(node_id, "node_id")
        return tuple(sorted(self._outgoing.get(node_id, ())))

    def prerequisites(self, node_id: str) -> tuple[str, ...]:
        """Direct prerequisites of a dependent (backward one hop)."""

        node_id = _require_text(node_id, "node_id")
        return tuple(sorted(self._incoming.get(node_id, ())))

    # -- traversal ----------------------------------------------------------

    def transitive_prerequisites(
        self,
        node_id: str,
        *,
        include_self: bool = True,
    ) -> tuple[str, ...]:
        """Walk incoming edges to every transitive prerequisite.

        Result is sorted so insertion order cannot affect identity.
        """

        node_id = _require_text(node_id, "node_id")
        if node_id not in self._nodes:
            raise DependencyGraphError(f"unknown node {node_id!r}")
        found: set[str] = set()
        queue: deque[str] = deque([node_id])
        visited: set[str] = set()
        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            if current != node_id or include_self:
                found.add(current)
            if len(found) > MAX_CLOSURE_NODES:
                raise DependencyGraphError(
                    f"prerequisite closure exceeds MAX_CLOSURE_NODES="
                    f"{MAX_CLOSURE_NODES}"
                )
            for pred in sorted(self._incoming.get(current, ())):
                if pred not in visited:
                    queue.append(pred)
        return tuple(sorted(found))

    def forward_dependents(
        self,
        node_ids: str | Iterable[str],
        *,
        include_seeds: bool = True,
    ) -> tuple[str, ...]:
        """Walk forward from changed prerequisites to every dependent.

        Aggregate nodes reached via ``aggregate_contains`` (child -> aggregate)
        are included.  Unrelated nodes remain outside the closure.  Result is
        sorted for determinism.
        """

        if isinstance(node_ids, str):
            seeds = (_require_text(node_ids, "node_ids"),)
        else:
            seeds = tuple(
                _require_text(item, "node_ids") for item in node_ids
            )
        if not seeds:
            return ()
        seed_set = set(seeds)
        for seed in seed_set:
            if seed not in self._nodes:
                raise DependencyGraphError(f"unknown node {seed!r}")
        found: set[str] = set()
        queue: deque[str] = deque(sorted(seed_set))
        visited: set[str] = set()
        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            if include_seeds or current not in seed_set:
                found.add(current)
            if len(found) > MAX_CLOSURE_NODES:
                raise DependencyGraphError(
                    f"forward closure exceeds MAX_CLOSURE_NODES="
                    f"{MAX_CLOSURE_NODES}"
                )
            for dep in sorted(self._outgoing.get(current, ())):
                if dep not in visited:
                    queue.append(dep)
        if not include_seeds:
            found -= seed_set
        return tuple(sorted(found))

    def invalidation_closure(
        self,
        changed_node_ids: str | Iterable[str],
    ) -> tuple[str, ...]:
        """Forward invalidation from changed prerequisites (includes seeds)."""

        return self.forward_dependents(changed_node_ids, include_seeds=True)

    def explanation_paths(
        self,
        prerequisite_id: str,
        dependent_id: str,
        *,
        max_paths: int = MAX_EXPLANATION_PATHS,
        max_depth: int = MAX_EXPLANATION_DEPTH,
    ) -> tuple[tuple[ProofDependencyEdge, ...], ...]:
        """Return deterministic simple paths from prerequisite to dependent.

        Paths are ordered by their edge sort keys so insertion order of the
        graph cannot affect the explanation record.
        """

        prerequisite_id = _require_text(prerequisite_id, "prerequisite_id")
        dependent_id = _require_text(dependent_id, "dependent_id")
        if prerequisite_id not in self._nodes:
            raise DependencyGraphError(f"unknown node {prerequisite_id!r}")
        if dependent_id not in self._nodes:
            raise DependencyGraphError(f"unknown node {dependent_id!r}")
        if max_paths < 1 or max_paths > MAX_EXPLANATION_PATHS:
            raise DependencyGraphError(
                f"max_paths must be in [1, {MAX_EXPLANATION_PATHS}]"
            )
        if max_depth < 1 or max_depth > MAX_EXPLANATION_DEPTH:
            raise DependencyGraphError(
                f"max_depth must be in [1, {MAX_EXPLANATION_DEPTH}]"
            )
        if prerequisite_id == dependent_id:
            return ()

        paths: list[tuple[ProofDependencyEdge, ...]] = []
        # DFS with explicit stack: (current, path_edges, visited_nodes)
        stack: list[
            tuple[str, tuple[ProofDependencyEdge, ...], frozenset[str]]
        ] = [(prerequisite_id, (), frozenset({prerequisite_id}))]
        while stack:
            current, path_edges, visited = stack.pop()
            if len(path_edges) >= max_depth:
                continue
            # Iterate reverse-sorted so stack pop yields ascending order.
            out = sorted(
                self._out_edges.get(current, ()),
                key=lambda edge: edge.sort_key(),
                reverse=True,
            )
            for edge in out:
                nxt = edge.to_id
                if nxt in visited:
                    continue
                new_path = path_edges + (edge,)
                if nxt == dependent_id:
                    paths.append(new_path)
                    if len(paths) >= max_paths:
                        paths.sort(key=lambda p: tuple(e.sort_key() for e in p))
                        return tuple(paths)
                    continue
                stack.append((nxt, new_path, visited | {nxt}))
        paths.sort(key=lambda p: tuple(e.sort_key() for e in p))
        return tuple(paths)

    def closure_is_complete(self, node_ids: Iterable[str]) -> bool:
        """Return False if any node in the set is marked truncated/unknown."""

        for node_id in node_ids:
            node = self._nodes.get(node_id)
            if node is None or node.truncated or node.kind is DependencyNodeKind.UNKNOWN:
                return False
        return True

    # -- canonical identity -------------------------------------------------

    def to_canonical(self) -> dict[str, Any]:
        return {
            "schema": DEPENDENCY_GRAPH_SCHEMA,
            "dependency_graph_schema_version": DEPENDENCY_GRAPH_SCHEMA_VERSION,
            "nodes": [node.to_canonical() for node in self.nodes()],
            "edges": [edge.to_canonical() for edge in self.edges()],
        }

    def to_canonical_json(self) -> str:
        return json.dumps(
            self.to_canonical(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )

    def graph_cid(self) -> str:
        return _node_cid(self.to_canonical())

    @classmethod
    def from_canonical(cls, payload: Mapping[str, Any]) -> ProofDependencyGraph:
        if not isinstance(payload, Mapping):
            raise DependencyGraphError("graph payload must be a mapping")
        graph = cls()
        nodes = payload.get("nodes") or ()
        edges = payload.get("edges") or ()
        if not isinstance(nodes, Sequence) or isinstance(nodes, (str, bytes)):
            raise DependencyGraphError("nodes must be a sequence")
        if not isinstance(edges, Sequence) or isinstance(edges, (str, bytes)):
            raise DependencyGraphError("edges must be a sequence")
        for raw in nodes:
            if not isinstance(raw, Mapping):
                raise DependencyGraphError("each node must be a mapping")
            node = ProofDependencyNode.from_canonical(raw)
            graph.add_node(
                node.node_id,
                node.kind,
                label=node.label,
                truncated=node.truncated,
            )
        for raw in edges:
            if not isinstance(raw, Mapping):
                raise DependencyGraphError("each edge must be a mapping")
            edge = ProofDependencyEdge.from_canonical(raw)
            graph.add_edge(
                edge.from_id,
                edge.to_id,
                edge.edge_type,
                edge.reason_cid,
            )
        return graph


def compute_dependency_root(
    graph: ProofDependencyGraph,
    unit_id: str,
    *,
    require_complete: bool = True,
) -> DependencyRoot:
    """Compute the transitive prerequisite root for one unit.

    Walks incoming edges back to all statement-relevant prerequisites and
    commits to every transitive node and reason.  Insertion order of edges
    cannot affect the resulting root CID.  Truncated roots fail closed when
    ``require_complete`` is true.
    """

    if not isinstance(graph, ProofDependencyGraph):
        raise DependencyGraphError("graph must be a ProofDependencyGraph")
    unit_id = _require_text(unit_id, "unit_id")
    if not graph.has_node(unit_id):
        raise DependencyGraphError(f"unknown unit {unit_id!r}")

    prereq_ids = graph.transitive_prerequisites(unit_id, include_self=True)
    complete = graph.closure_is_complete(prereq_ids)

    # Collect edges whose dependent endpoint is inside the prerequisite set
    # and whose prerequisite is also inside (closure-internal edges).
    prereq_set = set(prereq_ids)
    reason_cids: set[str] = set()
    edge_cids: set[str] = set()
    for node_id in prereq_ids:
        for edge in graph.incoming_edges(node_id):
            if edge.from_id in prereq_set and edge.to_id in prereq_set:
                reason_cids.add(edge.reason_cid)
                edge_cids.add(edge.edge_cid())

    root = DependencyRoot(
        unit_id=unit_id,
        prerequisite_node_ids=prereq_ids,
        reason_cids=tuple(sorted(reason_cids)),
        edge_cids=tuple(sorted(edge_cids)),
        complete=complete,
        dependency_graph_schema_version=DEPENDENCY_GRAPH_SCHEMA_VERSION,
    )
    if require_complete and not complete:
        raise DependencyGraphError(
            f"truncated dependency root for {unit_id!r}; "
            "unknown or truncated frontier cannot narrow reuse"
        )
    return root


# ---------------------------------------------------------------------------
# Samples and known vectors
# ---------------------------------------------------------------------------


def sample_reason(label: str = "default") -> str:
    return mint_reason_cid({"reason": label, "v": 1})


def sample_dependency_graph() -> ProofDependencyGraph:
    """Build a small multi-edge sample covering the normative chain.

    Chain: artifact -> symbol -> unit -> test -> obligation -> aggregate,
    plus an unrelated unit that must stay outside invalidation closures.
    """

    graph = ProofDependencyGraph()
    graph.add_node("artifact/mod.py", DependencyNodeKind.ARTIFACT, label="mod.py")
    graph.add_node("symbol/mod.fn", DependencyNodeKind.SYMBOL, label="fn")
    graph.add_node("unit/static", DependencyNodeKind.UNIT, label="static-analysis")
    graph.add_node("unit/test", DependencyNodeKind.UNIT, label="unit-test")
    graph.add_node("unit/formal", DependencyNodeKind.UNIT, label="formal-obligation")
    graph.add_node("aggregate/receipt", DependencyNodeKind.AGGREGATE, label="receipt")
    graph.add_node("fixture/data", DependencyNodeKind.FIXTURE, label="fixture")
    graph.add_node("config/env", DependencyNodeKind.CONFIG, label="config")
    graph.add_node("schema/api", DependencyNodeKind.SCHEMA, label="schema")
    graph.add_node("unit/unrelated", DependencyNodeKind.UNIT, label="unrelated")
    graph.add_node(
        "aggregate/unrelated", DependencyNodeKind.AGGREGATE, label="agg-unrelated"
    )

    graph.add_edge(
        "artifact/mod.py",
        "symbol/mod.fn",
        DependencyEdgeType.SOURCE_DEPENDS_ON,
        sample_reason("source-symbol"),
    )
    graph.add_edge(
        "symbol/mod.fn",
        "unit/static",
        DependencyEdgeType.CALLS,
        sample_reason("symbol-static"),
    )
    graph.add_edge(
        "symbol/mod.fn",
        "unit/test",
        DependencyEdgeType.TEST_COVERS,
        sample_reason("symbol-test"),
    )
    graph.add_edge(
        "unit/static",
        "unit/formal",
        DependencyEdgeType.PROOF_DEPENDS_ON,
        sample_reason("static-formal"),
    )
    graph.add_edge(
        "unit/test",
        "unit/formal",
        DependencyEdgeType.PROOF_DEPENDS_ON,
        sample_reason("test-formal"),
    )
    graph.add_edge(
        "fixture/data",
        "unit/test",
        DependencyEdgeType.FIXTURE_DEPENDS_ON,
        sample_reason("fixture-test"),
    )
    graph.add_edge(
        "config/env",
        "unit/test",
        DependencyEdgeType.CONFIG_DEPENDS_ON,
        sample_reason("config-test"),
    )
    graph.add_edge(
        "schema/api",
        "unit/static",
        DependencyEdgeType.SCHEMA_DEPENDS_ON,
        sample_reason("schema-static"),
    )
    graph.add_edge(
        "artifact/mod.py",
        "unit/static",
        DependencyEdgeType.IMPORTS,
        sample_reason("import-static"),
    )
    graph.add_edge(
        "unit/formal",
        "aggregate/receipt",
        DependencyEdgeType.AGGREGATE_CONTAINS,
        sample_reason("formal-aggregate"),
    )
    graph.add_edge(
        "unit/test",
        "aggregate/receipt",
        DependencyEdgeType.AGGREGATE_CONTAINS,
        sample_reason("test-aggregate"),
    )
    graph.add_edge(
        "unit/unrelated",
        "aggregate/unrelated",
        DependencyEdgeType.AGGREGATE_CONTAINS,
        sample_reason("unrelated-aggregate"),
    )
    return graph


def known_vectors() -> dict[str, Any]:
    """Deterministic vectors for the dependency-graph evidence subset."""

    graph = sample_dependency_graph()
    # Build the same logical graph with reversed insertion order.
    reversed_graph = ProofDependencyGraph()
    for node in reversed(graph.nodes()):
        reversed_graph.add_node(
            node.node_id,
            node.kind,
            label=node.label,
            truncated=node.truncated,
        )
    for edge in reversed(graph.edges()):
        reversed_graph.add_edge(
            edge.from_id,
            edge.to_id,
            edge.edge_type,
            edge.reason_cid,
        )

    formal_root = compute_dependency_root(graph, "unit/formal")
    reversed_root = compute_dependency_root(reversed_graph, "unit/formal")
    invalidation = graph.invalidation_closure("artifact/mod.py")
    unrelated = graph.invalidation_closure("unit/unrelated")

    return {
        "schema": f"{DEPENDENCY_GRAPH_NAMESPACE}/known-vectors@{SCHEMA_MAJOR}",
        "subset": DEPENDENCY_GRAPH_SUBSET,
        "dependency_graph_schema_version": DEPENDENCY_GRAPH_SCHEMA_VERSION,
        "closed_edge_types": list(DEPENDENCY_EDGE_TYPES),
        "closed_node_kinds": list(DEPENDENCY_NODE_KINDS),
        "graph_cid": graph.graph_cid(),
        "reversed_graph_cid": reversed_graph.graph_cid(),
        "formal_root_cid": formal_root.root_cid(),
        "reversed_formal_root_cid": reversed_root.root_cid(),
        "formal_prerequisites": list(formal_root.prerequisite_node_ids),
        "invalidation_from_artifact": list(invalidation),
        "invalidation_from_unrelated": list(unrelated),
        "edge_count": graph.edge_count(),
        "node_count": graph.node_count(),
    }
