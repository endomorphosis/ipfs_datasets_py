"""Source-bound, deterministic explanations for semantic-index records.

The explanation layer deliberately reports the graph facts it was given.  It
does not turn lexical, heuristic, or opaque observations into a claim about
runtime behaviour.  In particular, a path through opaque evidence always
contains a raw-source requirement.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable

from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    AnalysisConfidence,
    ArtifactRecord,
    ImpactExplanation,
    RepositoryState,
    SymbolExplanation,
    SymbolRecord,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.symbol_graph import (
    SymbolGraph,
    build_symbol_graph,
)


DEFAULT_MAX_DEPTH = 8
DEFAULT_MAX_NODES = 1_000


class UnknownSymbolError(LookupError):
    """Raised when an explanation names no declared symbol in a state.

    ``symbol_id`` and ``state_cid`` make this a machine-actionable lookup
    failure instead of a string-only error; callers can retain it in an API
    response without guessing which immutable state was queried.
    """

    def __init__(self, symbol_id: str, state_cid: str) -> None:
        self.symbol_id = symbol_id
        self.state_cid = state_cid
        super().__init__(f"unknown symbol {symbol_id!r} in state {state_cid}")


def _graph(state: RepositoryState) -> SymbolGraph:
    if not isinstance(state, RepositoryState):
        raise TypeError("state must be a RepositoryState")
    return build_symbol_graph(state)


def _confidence_limitations(
    node_id: str,
    confidence: AnalysisConfidence | str,
    metadata: object = None,
) -> set[str]:
    """Return only declared confidence degraders, never inferred semantics."""
    value = AnalysisConfidence(confidence).value
    limitations: set[str] = set()
    if value != AnalysisConfidence.EXACT.value:
        limitations.add(f"confidence:{node_id}:{value}")
    if value == AnalysisConfidence.OPAQUE.value:
        limitations.add(f"raw_source_required:{node_id}")
    if isinstance(metadata, dict):
        reasons = metadata.get("confidence_reasons", ())
        if isinstance(reasons, (list, tuple)):
            limitations.update(
                f"confidence_reason:{node_id}:{reason}"
                for reason in reasons
                if isinstance(reason, str) and reason
            )
        resolution = metadata.get("resolution")
        if resolution == "unresolved":
            target = metadata.get("unresolved_target", node_id)
            if isinstance(target, str) and target:
                limitations.add(f"unresolved_target:{target}")
        elif resolution == "finite_may":
            limitations.add(f"finite_may_target:{node_id}")
    return limitations


def _edge_limitations(edge: object) -> set[str]:
    # Kept separate so the caller never has to manufacture a source fact from
    # a relation name.  All values come from the durable edge record.
    return _confidence_limitations(edge.edge_id, edge.confidence, dict(edge.metadata))


def _node_limitations(graph: SymbolGraph, node_id: str) -> set[str]:
    symbol = next((item for item in graph.symbols if item.stable_id == node_id), None)
    if symbol is not None:
        return _confidence_limitations(node_id, symbol.confidence, dict(symbol.metadata))
    artifact = next((item for item in graph.artifacts if item.artifact_id == node_id), None)
    if artifact is not None:
        return _confidence_limitations(node_id, artifact.confidence, dict(artifact.metadata))
    # Explicit unresolved targets are not silently treated as declarations.
    return {f"unresolved_target:{node_id}"}


def explain_symbol(state: RepositoryState, symbol_id: str) -> SymbolExplanation:
    """Explain one declared symbol using its direct, resolved graph facts.

    The returned edges retain their extraction method, span, confidence, and
    metadata.  They are canonicalized by :class:`SymbolExplanation`; no edge
    is ranked or promoted by this function.
    """
    graph = _graph(state)
    symbol = next((item for item in graph.symbols if item.stable_id == symbol_id), None)
    if symbol is None:
        raise UnknownSymbolError(symbol_id, state.state_cid)
    outgoing = graph.outgoing(symbol_id)
    incoming = graph.incoming(symbol_id)
    limitations = _node_limitations(graph, symbol_id)
    for edge in (*outgoing, *incoming):
        limitations.update(_edge_limitations(edge))
        limitations.update(_node_limitations(graph, edge.source_id))
        limitations.update(_node_limitations(graph, edge.target_id))
    return SymbolExplanation(symbol_id, state.state_cid, symbol, outgoing, incoming, sorted(limitations))


def _path_members(state: RepositoryState, path: str) -> tuple[str, ...]:
    """Find stable symbols belonging to a tracked source artifact path."""
    normalized = path.replace("\\", "/")
    artifacts = tuple(item for item in state.artifacts if item.path == normalized)
    source_cids = {item.source_cid for item in artifacts if item.source_cid is not None}
    members = {
        item.stable_id for item in state.symbols
        if item.module_path == normalized
        or (item.source_cid is not None and item.source_cid in source_cids)
    }
    return tuple(sorted(members))


def _impact_starts(state: RepositoryState, changed: Iterable[str]) -> tuple[str, ...]:
    symbols = {item.stable_id for item in state.symbols}
    artifacts = {item.artifact_id: item for item in state.artifacts}
    starts: set[str] = set()
    for item in changed:
        if not isinstance(item, str) or not item:
            raise TypeError("changed identifiers must be nonempty strings")
        if item in symbols:
            starts.add(item)
        elif item in artifacts:
            starts.add(item)
            starts.update(_path_members(state, artifacts[item].path))
        else:
            members = _path_members(state, item)
            if not members:
                raise UnknownSymbolError(item, state.state_cid)
            starts.update(members)
    return tuple(sorted(starts))


def explain_impact(
    state: RepositoryState,
    changed_symbol_ids: str | Iterable[str],
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_nodes: int = DEFAULT_MAX_NODES,
) -> ImpactExplanation:
    """Report bounded reverse dependency impact for symbols, artifacts, or paths.

    A supplied artifact ID or repository-relative path expands through stable
    artifact membership (artifact path/source CID to symbol records), then
    follows incoming edges: an incoming edge's source is the record that
    depends on the changed target.  The output lists every edge actually
    traversed, while limitations state depth/node truncation and confidence
    boundaries.  It intentionally creates no invalidation obligations; that
    policy belongs to the invalidation engine.
    """
    if type(max_depth) is not int or max_depth < 0:
        raise ValueError("max_depth must be a nonnegative integer")
    if type(max_nodes) is not int or max_nodes < 1:
        raise ValueError("max_nodes must be a positive integer")
    if isinstance(changed_symbol_ids, str):
        changed = (changed_symbol_ids,)
    else:
        changed = tuple(changed_symbol_ids)
    if not changed:
        raise ValueError("changed_symbol_ids must not be empty")

    graph = _graph(state)
    starts = _impact_starts(state, changed)
    seen = set(starts)
    queue = deque((node_id, 0) for node_id in starts)
    traversed = []
    limitations: set[str] = set()
    for node_id in starts:
        limitations.update(_node_limitations(graph, node_id))

    truncated_depth = False
    truncated_nodes = False
    while queue:
        node_id, depth = queue.popleft()
        if depth >= max_depth:
            if graph.incoming(node_id):
                truncated_depth = True
            continue
        for edge in graph.incoming(node_id):
            traversed.append(edge)
            limitations.update(_edge_limitations(edge))
            limitations.update(_node_limitations(graph, edge.source_id))
            limitations.update(_node_limitations(graph, edge.target_id))
            dependent_id = edge.source_id
            if dependent_id in seen:
                continue
            if len(seen) >= max_nodes:
                truncated_nodes = True
                continue
            seen.add(dependent_id)
            queue.append((dependent_id, depth + 1))
    if truncated_depth:
        limitations.add(f"truncated:max_depth:{max_depth}")
    if truncated_nodes:
        limitations.add(f"truncated:max_nodes:{max_nodes}")
    return ImpactExplanation(
        state.state_cid,
        tuple(sorted(seen)),
        traversed_edge_ids=tuple(edge.edge_id for edge in traversed),
        limitations=tuple(sorted(limitations)),
    )


__all__ = [
    "DEFAULT_MAX_DEPTH",
    "DEFAULT_MAX_NODES",
    "UnknownSymbolError",
    "explain_impact",
    "explain_symbol",
]
