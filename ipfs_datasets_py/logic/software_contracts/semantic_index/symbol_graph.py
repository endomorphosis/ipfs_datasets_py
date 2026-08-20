"""Deterministic, bounded resolution and traversal of semantic-index edges.

The frontends deliberately record lexical observations.  This module joins
those observations only against the supplied closed symbol/artifact set: a
unique match is exact, multiple finite matches are retained as conservative
may-targets, and no match remains an explicit typed target.  It never imports
or executes repository code.

Resolution statuses reuse the closed vocabulary shared with
``software_contracts.resolver`` (definite, finite_may, unresolved).  The
public repository state must commit these resolved edges before its state
root is computed.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Iterable, Literal, Mapping, Sequence

from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    AnalysisConfidence,
    ArtifactRecord,
    DependencyEdge,
    RelationType,
    RepositoryState,
    SymbolKind,
    SymbolRecord,
)


SYMBOL_GRAPH_SCHEMA = "ipfs-datasets.software-contracts.typed-symbol-graph@1"
EXTRACTOR_VERSION = "1"
_CONFIDENCE_RANK = {"exact": 0, "conservative": 1, "heuristic": 2, "opaque": 3}
_DIRECTIONS = frozenset({"outgoing", "incoming", "both"})

# Bounded resolution statuses aligned with software_contracts.resolver.
STATUS_DEFINITE = "definite"
STATUS_FINITE_MAY = "finite_may"
STATUS_UNRESOLVED = "unresolved"


def _degrade(*values: AnalysisConfidence | str) -> str:
    """Return the least certain member of the closed confidence vocabulary."""
    return max((AnalysisConfidence(value).value for value in values), key=_CONFIDENCE_RANK.__getitem__)


def _lexical_name(target_id: str) -> str | None:
    for prefix in ("lexical:", "module:", "pytest-fixture:"):
        if target_id.startswith(prefix):
            return target_id[len(prefix):]
    return None


def _module_name(symbol: SymbolRecord) -> str:
    path = symbol.module_path
    if path.endswith((".py", ".pyi")):
        path = path.rsplit(".", 1)[0]
    parts = path.split("/")
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) or "__main__"


def _fixture_name(symbol: SymbolRecord) -> str | None:
    if symbol.kind != SymbolKind.FIXTURE.value:
        return None
    meta = symbol.metadata.get("fixture_name")
    if isinstance(meta, str) and meta:
        return meta
    pytest_meta = symbol.metadata.get("pytest")
    if isinstance(pytest_meta, Mapping):
        name = pytest_meta.get("name")
        if isinstance(name, str) and name:
            return name
    annotations = symbol.annotations.get("pytest")
    if isinstance(annotations, Mapping):
        name = annotations.get("name")
        if isinstance(name, str) and name:
            return name
    return symbol.qualified_name.rsplit(".", 1)[-1]


def _candidate_ids(edge: DependencyEdge, symbols: Sequence[SymbolRecord], artifacts: Sequence[ArtifactRecord]) -> tuple[str, ...]:
    """Find only statically justified candidates for one frontend target."""
    known_ids = {item.stable_id for item in symbols} | {item.artifact_id for item in artifacts}
    if edge.target_id in known_ids:
        return (edge.target_id,)
    name = _lexical_name(edge.target_id)
    if not name:
        return ()
    source = next((item for item in symbols if item.stable_id == edge.source_id), None)
    candidates: set[str] = set()
    if edge.target_id.startswith("module:"):
        # An import can designate a module itself or a declared member of it.
        candidates.update(
            item.stable_id for item in symbols
            if item.kind == SymbolKind.MODULE.value and item.qualified_name == name
        )
        # Also match imported member names when a unique symbol shares the tail.
        member = name.rsplit(".", 1)[-1]
        if "." in name:
            candidates.update(
                item.stable_id for item in symbols
                if item.qualified_name == name or item.qualified_name.endswith("." + member)
            )
            # Prefer exact qualified matches over bare suffix when both exist.
            exact = {
                item.stable_id for item in symbols
                if item.qualified_name == name
            }
            if exact:
                candidates = exact
    elif edge.target_id.startswith("pytest-fixture:"):
        for item in symbols:
            if item.kind != SymbolKind.FIXTURE.value:
                continue
            fixture_name = _fixture_name(item)
            if fixture_name == name or item.qualified_name.rsplit(".", 1)[-1] == name:
                candidates.add(item.stable_id)
    else:
        # Qualified lexical expressions can be matched directly.  A bare name
        # is additionally scoped to its declaring module, never globally
        # guessed by suffix alone.
        candidates.update(item.stable_id for item in symbols if item.qualified_name == name)
        if source is not None and "." not in name:
            local = f"{_module_name(source)}.{name}"
            candidates.update(item.stable_id for item in symbols if item.qualified_name == local)
        elif source is not None and name.count(".") >= 1:
            # module.attr form: match symbols whose qualified name equals the
            # expanded alias or ends with the attribute under a known module.
            candidates.update(
                item.stable_id for item in symbols
                if item.qualified_name.endswith("." + name.rsplit(".", 1)[-1])
                and (
                    item.qualified_name == name
                    or item.qualified_name.endswith("." + name)
                    or _module_name(item) + "." + name.rsplit(".", 1)[-1] == item.qualified_name
                )
            )
            # Prefer exact qualified_name equality when present.
            exact = {item.stable_id for item in symbols if item.qualified_name == name}
            if exact:
                candidates = exact
            else:
                # For lexical:module.target match module.target or pkg.module.target.
                tail = name
                tail_matches = {
                    item.stable_id for item in symbols
                    if item.qualified_name == tail or item.qualified_name.endswith("." + tail)
                }
                if len(tail_matches) == 1:
                    candidates = tail_matches
                elif tail_matches:
                    candidates = tail_matches
    return tuple(sorted(candidates))


def resolve_edge_targets(
    edges: Iterable[DependencyEdge],
    symbols: Iterable[SymbolRecord] = (),
    artifacts: Iterable[ArtifactRecord] = (),
) -> tuple[DependencyEdge, ...]:
    """Resolve edge targets against a finite inventory without dropping facts.

    Ambiguous candidates become one edge per candidate with ``finite_may``
    metadata and conservative confidence.  A target with no candidate remains
    unchanged with ``unresolved`` metadata, so later stages can explain the
    missing source rather than treating it as absent.

    Already-inventory targets (including frontend-resolved stable CIDs) are
    annotated with ``resolution=definite`` so public state and explanations
    share one committed resolution vocabulary.
    """
    symbol_items = tuple(sorted(symbols, key=lambda item: item.stable_id))
    artifact_items = tuple(sorted(artifacts, key=lambda item: item.artifact_id))
    resolved: list[DependencyEdge] = []
    for edge in sorted(edges, key=lambda item: item.edge_id):
        candidates = _candidate_ids(edge, symbol_items, artifact_items)
        if len(candidates) == 1:
            metadata = dict(edge.metadata)
            metadata["resolution"] = STATUS_DEFINITE
            if candidates[0] != edge.target_id:
                metadata["unresolved_target"] = edge.target_id
            resolved.append(DependencyEdge(
                edge.source_id, candidates[0], edge.relation, edge.extraction_method,
                edge.confidence, edge.extractor_version, edge.span, metadata,
            ))
        elif candidates:
            for candidate in candidates:
                metadata = dict(edge.metadata)
                metadata.update({
                    "resolution": STATUS_FINITE_MAY,
                    "unresolved_target": edge.target_id,
                    "candidate_count": len(candidates),
                })
                resolved.append(DependencyEdge(
                    edge.source_id, candidate, edge.relation, edge.extraction_method,
                    _degrade(edge.confidence, "conservative"), edge.extractor_version,
                    edge.span, metadata,
                ))
        else:
            metadata = dict(edge.metadata)
            # Preserve explicit unresolved markers from frontends; otherwise set.
            metadata.setdefault("resolution", STATUS_UNRESOLVED)
            metadata.setdefault("unresolved_target", edge.target_id)
            # Already-stable non-inventory targets (exception:, state:, global:)
            # keep confidence; pure lexical misses degrade.
            confidence = edge.confidence
            if edge.target_id.startswith(("lexical:", "module:", "pytest-fixture:")):
                confidence = _degrade(edge.confidence, "conservative")
            resolved.append(DependencyEdge(
                edge.source_id, edge.target_id, edge.relation, edge.extraction_method,
                confidence, edge.extractor_version, edge.span, metadata,
            ))
    return tuple(sorted({edge.edge_id: edge for edge in resolved}.values(), key=lambda item: item.edge_id))


@dataclass(frozen=True, slots=True)
class SymbolGraph:
    """Closed graph indexes with stable, bounded, cycle-safe traversal."""

    symbols: Sequence[SymbolRecord] = ()
    artifacts: Sequence[ArtifactRecord] = ()
    edges: Sequence[DependencyEdge] = ()
    schema: str = SYMBOL_GRAPH_SCHEMA
    _outgoing: Mapping[str, tuple[DependencyEdge, ...]] = field(init=False, repr=False, compare=False)
    _incoming: Mapping[str, tuple[DependencyEdge, ...]] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.schema != SYMBOL_GRAPH_SCHEMA:
            raise ValueError("unsupported SymbolGraph schema")
        if any(not isinstance(item, SymbolRecord) for item in self.symbols):
            raise TypeError("symbols must contain SymbolRecord values")
        if any(not isinstance(item, ArtifactRecord) for item in self.artifacts):
            raise TypeError("artifacts must contain ArtifactRecord values")
        if any(not isinstance(item, DependencyEdge) for item in self.edges):
            raise TypeError("edges must contain DependencyEdge values")
        symbols = tuple(sorted(self.symbols, key=lambda item: item.stable_id))
        artifacts = tuple(sorted(self.artifacts, key=lambda item: item.artifact_id))
        if len({item.stable_id for item in symbols}) != len(symbols):
            raise ValueError("symbols must not contain duplicate stable IDs")
        if len({item.artifact_id for item in artifacts}) != len(artifacts):
            raise ValueError("artifacts must not contain duplicate artifact IDs")
        edges = tuple(sorted({item.edge_id: item for item in self.edges}.values(), key=lambda item: item.edge_id))
        outgoing: dict[str, list[DependencyEdge]] = {}
        incoming: dict[str, list[DependencyEdge]] = {}
        for edge in edges:
            outgoing.setdefault(edge.source_id, []).append(edge)
            incoming.setdefault(edge.target_id, []).append(edge)
        object.__setattr__(self, "symbols", symbols)
        object.__setattr__(self, "artifacts", artifacts)
        object.__setattr__(self, "edges", edges)
        object.__setattr__(self, "_outgoing", {key: tuple(sorted(value, key=lambda item: item.edge_id)) for key, value in sorted(outgoing.items())})
        object.__setattr__(self, "_incoming", {key: tuple(sorted(value, key=lambda item: item.edge_id)) for key, value in sorted(incoming.items())})

    @property
    def node_ids(self) -> tuple[str, ...]:
        """All declared and explicit unresolved nodes, in canonical order."""
        return tuple(sorted({
            *(item.stable_id for item in self.symbols),
            *(item.artifact_id for item in self.artifacts),
            *(edge.source_id for edge in self.edges),
            *(edge.target_id for edge in self.edges),
        }))

    def outgoing(self, node_id: str, *, relation: RelationType | str | None = None) -> tuple[DependencyEdge, ...]:
        return self._filter(self._outgoing.get(node_id, ()), relation)

    def incoming(self, node_id: str, *, relation: RelationType | str | None = None) -> tuple[DependencyEdge, ...]:
        return self._filter(self._incoming.get(node_id, ()), relation)

    def neighbors(
        self,
        node_id: str,
        *,
        direction: Literal["outgoing", "incoming", "both"] = "outgoing",
        relation: RelationType | str | None = None,
    ) -> tuple[DependencyEdge, ...]:
        if direction not in _DIRECTIONS:
            raise ValueError("direction must be outgoing, incoming, or both")
        edges = (
            (() if direction == "incoming" else self.outgoing(node_id, relation=relation))
            + (() if direction == "outgoing" else self.incoming(node_id, relation=relation))
        )
        return tuple(sorted({edge.edge_id: edge for edge in edges}.values(), key=lambda item: item.edge_id))

    def traverse(
        self,
        start_ids: str | Iterable[str],
        *,
        direction: Literal["outgoing", "incoming", "both"] = "outgoing",
        relation: RelationType | str | None = None,
        max_depth: int = 1,
        max_nodes: int = 1_000,
    ) -> tuple[str, ...]:
        """Breadth-first node traversal, bounded before expanding a cycle."""
        if max_depth < 0 or max_nodes < 1:
            raise ValueError("max_depth must be nonnegative and max_nodes must be positive")
        starts = (start_ids,) if isinstance(start_ids, str) else tuple(start_ids)
        if any(not isinstance(item, str) or not item for item in starts):
            raise ValueError("start_ids must be nonempty strings")
        seen = set(sorted(starts))
        queue = deque((item, 0) for item in sorted(seen))
        result = list(sorted(seen))[:max_nodes]
        while queue and len(result) < max_nodes:
            node, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for edge in self.neighbors(node, direction=direction, relation=relation):
                other = edge.target_id if edge.source_id == node else edge.source_id
                if other not in seen:
                    seen.add(other)
                    result.append(other)
                    queue.append((other, depth + 1))
                    if len(result) == max_nodes:
                        break
        return tuple(result)

    @staticmethod
    def _filter(edges: Sequence[DependencyEdge], relation: RelationType | str | None) -> tuple[DependencyEdge, ...]:
        if relation is None:
            return tuple(edges)
        relation_value = RelationType(relation).value
        return tuple(edge for edge in edges if edge.relation == relation_value)


def build_symbol_graph(
    symbols: Iterable[SymbolRecord] | RepositoryState = (),
    artifacts: Iterable[ArtifactRecord] = (),
    edges: Iterable[DependencyEdge] = (),
) -> SymbolGraph:
    """Build a resolved graph from inventory records or a repository state.

    Existing edges are retained where already typed; only lexical and missing
    targets are rewritten through the bounded resolver.  Calls from a
    statically identified test also produce a reverse ``tested_by`` receipt.
    Protocol inheritance emits ``implements`` when the base is a Protocol.
    """
    if isinstance(symbols, RepositoryState):
        if artifacts or edges:
            raise ValueError("RepositoryState cannot be combined with artifacts or edges")
        state = symbols
        symbols, artifacts, edges = state.symbols, state.artifacts, state.edges
    symbol_items = tuple(symbols)
    artifact_items = tuple(artifacts)
    resolved = list(resolve_edge_targets(edges, symbol_items, artifact_items))
    tests = {item.stable_id for item in symbol_items if item.kind == SymbolKind.TEST.value}
    known_symbols = {item.stable_id for item in symbol_items}
    by_id = {item.stable_id: item for item in symbol_items}
    derived: list[DependencyEdge] = []
    for edge in tuple(resolved):
        if edge.relation == RelationType.CALLS.value and edge.source_id in tests and edge.target_id in known_symbols:
            metadata = dict(edge.metadata)
            metadata.update({
                "derived_from_edge": edge.edge_id,
                "resolution": metadata.get("resolution", STATUS_DEFINITE),
                "source_bound": True,
            })
            derived.append(DependencyEdge(
                edge.target_id, edge.source_id, RelationType.TESTED_BY,
                "static-test-call-reversal", edge.confidence, EXTRACTOR_VERSION,
                edge.span, metadata,
            ))
        if edge.relation == RelationType.INHERITS.value and edge.target_id in known_symbols:
            target = by_id[edge.target_id]
            bases = target.annotations.get("bases", ())
            if isinstance(bases, list) and any(str(base).rsplit(".", 1)[-1] == "Protocol" for base in bases):
                metadata = dict(edge.metadata)
                metadata.update({
                    "derived_from_edge": edge.edge_id,
                    "resolution": metadata.get("resolution", STATUS_DEFINITE),
                })
                derived.append(DependencyEdge(
                    edge.source_id, edge.target_id, RelationType.IMPLEMENTS,
                    "static-protocol-inheritance",
                    _degrade(edge.confidence, target.confidence), EXTRACTOR_VERSION,
                    edge.span, metadata,
                ))
    if derived:
        # Re-resolve derived edges so they carry definite resolution against inventory.
        resolved.extend(resolve_edge_targets(derived, symbol_items, artifact_items))
    return SymbolGraph(symbol_items, artifact_items, resolved)


__all__ = [
    "EXTRACTOR_VERSION",
    "STATUS_DEFINITE",
    "STATUS_FINITE_MAY",
    "STATUS_UNRESOLVED",
    "SYMBOL_GRAPH_SCHEMA",
    "SymbolGraph",
    "build_symbol_graph",
    "resolve_edge_targets",
]
