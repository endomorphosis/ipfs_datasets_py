"""Embedding-guided knowledge-graph traversal.

This module contains the reusable traversal primitive used by GraphRAG query
engines.  It deliberately depends only on small provider protocols rather than
on a particular graph backend, vector database, or dataset layout.  Local
graphs, remote sharded graphs, and compatibility layers can therefore share
the same ranking and budget semantics.

The traversal is a bounded beam search.  At every depth it:

1. fetches graph neighbors for the current frontier;
2. requests candidate embeddings in one batch;
3. scores semantic proximity, semantic progress, direction of travel, and
   relationship weight; and
4. retains the best deterministic beam for the next depth.

Breadth-first traversal remains available in :mod:`hybrid_search`; this module
implements only the opt-in semantic strategy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    Tuple,
    runtime_checkable,
)


Vector = Sequence[float]
_VALID_DIRECTIONS = frozenset({"incoming", "outgoing", "both", "adaptive"})


def _finite_vector(vector: Optional[Vector]) -> Optional[Tuple[float, ...]]:
    """Return a finite float tuple, or ``None`` for an unusable vector."""
    if vector is None:
        return None
    try:
        result = tuple(float(value) for value in vector)
    except (TypeError, ValueError, OverflowError):
        return None
    if not result or not all(math.isfinite(value) for value in result):
        return None
    return result


def cosine_similarity(left: Optional[Vector], right: Optional[Vector]) -> float:
    """Compute cosine similarity without imposing a NumPy dependency."""
    left_vector = _finite_vector(left)
    right_vector = _finite_vector(right)
    if (
        left_vector is None
        or right_vector is None
        or len(left_vector) != len(right_vector)
    ):
        return 0.0

    dot = sum(a * b for a, b in zip(left_vector, right_vector))
    left_norm = math.sqrt(sum(value * value for value in left_vector))
    right_norm = math.sqrt(sum(value * value for value in right_vector))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (left_norm * right_norm)))


def _difference(left: Vector, right: Vector) -> Optional[Tuple[float, ...]]:
    left_vector = _finite_vector(left)
    right_vector = _finite_vector(right)
    if (
        left_vector is None
        or right_vector is None
        or len(left_vector) != len(right_vector)
    ):
        return None
    return tuple(a - b for a, b in zip(left_vector, right_vector))


@dataclass(frozen=True)
class SemanticTraversalWeights:
    """Weights for the semantic neighbor-ranking function."""

    proximity: float = 0.55
    progress: float = 0.20
    direction: float = 0.15
    relationship: float = 0.10
    depth_penalty: float = 0.05

    def __post_init__(self) -> None:
        values = (
            self.proximity,
            self.progress,
            self.direction,
            self.relationship,
            self.depth_penalty,
        )
        if any(not math.isfinite(value) or value < 0.0 for value in values):
            raise ValueError("semantic traversal weights must be finite and non-negative")
        if sum(values[:4]) <= 0.0:
            raise ValueError("at least one positive traversal score weight is required")


@dataclass(frozen=True)
class SemanticTraversalConfig:
    """Budgets and behavior for an embedding-guided traversal."""

    max_depth: int = 2
    max_nodes: int = 1000
    max_edges: int = 10_000
    max_degree: int = 256
    max_backend_calls: int = 10_000
    beam_width: int = 32
    direction: str = "outgoing"
    relationship_types: Tuple[str, ...] = ()
    minimum_score: Optional[float] = None
    include_seeds: bool = True
    fail_fast: bool = False
    weights: SemanticTraversalWeights = field(default_factory=SemanticTraversalWeights)

    def __post_init__(self) -> None:
        integer_limits = {
            "max_depth": self.max_depth,
            "max_nodes": self.max_nodes,
            "max_edges": self.max_edges,
            "max_degree": self.max_degree,
            "max_backend_calls": self.max_backend_calls,
            "beam_width": self.beam_width,
        }
        for name, value in integer_limits.items():
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"{name} must be an integer")
            minimum = 0 if name == "max_depth" else 1
            if value < minimum:
                raise ValueError(f"{name} must be at least {minimum}")
        if self.direction not in _VALID_DIRECTIONS:
            choices = ", ".join(sorted(_VALID_DIRECTIONS))
            raise ValueError(f"direction must be one of: {choices}")
        if self.minimum_score is not None and not math.isfinite(self.minimum_score):
            raise ValueError("minimum_score must be finite when provided")


@dataclass(frozen=True)
class TraversalEdge:
    """Backend-neutral directed edge returned by a neighbor provider."""

    source_id: str
    target_id: str
    relationship_type: Optional[str] = None
    weight: float = 1.0
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TraversalCandidate:
    """The selected path and score components for one visited node."""

    node_id: str
    parent_id: Optional[str]
    depth: int
    score: float
    semantic_proximity: float = 0.0
    semantic_progress: float = 0.0
    semantic_direction: float = 0.0
    relationship_score: float = 0.0
    relationship_type: Optional[str] = None
    has_embedding: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "parent_id": self.parent_id,
            "depth": self.depth,
            "score": self.score,
            "semantic_proximity": self.semantic_proximity,
            "semantic_progress": self.semantic_progress,
            "semantic_direction": self.semantic_direction,
            "relationship_score": self.relationship_score,
            "relationship_type": self.relationship_type,
            "has_embedding": self.has_embedding,
        }


@dataclass(frozen=True)
class TraversalPath:
    """A reconstructed seed-to-node path."""

    node_ids: Tuple[str, ...]
    relationship_types: Tuple[Optional[str], ...]
    score: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_ids": list(self.node_ids),
            "relationship_types": list(self.relationship_types),
            "score": self.score,
        }


@dataclass
class TraversalDiagnostics:
    """Budget, pruning, and embedding-coverage diagnostics."""

    stop_reason: str = "frontier_exhausted"
    nodes_visited: int = 0
    edges_scanned: int = 0
    backend_calls: int = 0
    embedding_calls: int = 0
    embeddings_requested: int = 0
    embeddings_found: int = 0
    embeddings_missing: int = 0
    depths_completed: int = 0
    frontier_peak: int = 0
    cycles_skipped: int = 0
    degree_pruned: int = 0
    beam_pruned: int = 0
    score_pruned: int = 0
    invalid_edges: int = 0
    provider_errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stop_reason": self.stop_reason,
            "nodes_visited": self.nodes_visited,
            "edges_scanned": self.edges_scanned,
            "backend_calls": self.backend_calls,
            "embedding_calls": self.embedding_calls,
            "embeddings_requested": self.embeddings_requested,
            "embeddings_found": self.embeddings_found,
            "embeddings_missing": self.embeddings_missing,
            "depths_completed": self.depths_completed,
            "frontier_peak": self.frontier_peak,
            "cycles_skipped": self.cycles_skipped,
            "degree_pruned": self.degree_pruned,
            "beam_pruned": self.beam_pruned,
            "score_pruned": self.score_pruned,
            "invalid_edges": self.invalid_edges,
            "provider_errors": list(self.provider_errors),
        }


@dataclass
class SemanticTraversalResult:
    """Result of an embedding-guided traversal."""

    candidates: Dict[str, TraversalCandidate]
    hop_distances: Dict[str, int]
    paths: List[TraversalPath]
    diagnostics: TraversalDiagnostics
    approximate: bool = False

    @property
    def ranked_node_ids(self) -> List[str]:
        return [
            candidate.node_id
            for candidate in sorted(
                self.candidates.values(),
                key=lambda item: (-item.score, item.depth, item.node_id),
            )
        ]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ranked_node_ids": self.ranked_node_ids,
            "hop_distances": dict(self.hop_distances),
            "candidates": {
                node_id: candidate.to_dict()
                for node_id, candidate in self.candidates.items()
            },
            "paths": [path.to_dict() for path in self.paths],
            "diagnostics": self.diagnostics.to_dict(),
            "approximate": self.approximate,
        }


@runtime_checkable
class GraphNeighborProvider(Protocol):
    """Provider protocol for backend-neutral graph expansion."""

    def get_neighbors(
        self,
        node_id: str,
        *,
        direction: str,
        relationship_types: Sequence[str],
        limit: int,
    ) -> Iterable[TraversalEdge]:
        """Return at most ``limit`` traversable edges adjacent to ``node_id``."""


@runtime_checkable
class NodeEmbeddingProvider(Protocol):
    """Provider protocol for batch node-vector retrieval."""

    def get_embeddings(self, node_ids: Sequence[str]) -> Mapping[str, Vector]:
        """Return embeddings keyed by node ID for any available IDs."""


def _read_value(value: Any, *names: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        for name in names:
            if name in value:
                return value[name]
        return default
    for name in names:
        if hasattr(value, name):
            return getattr(value, name)
    return default


def _edge_weight(value: Any) -> float:
    raw = _read_value(value, "weight", "score", default=None)
    if raw is None:
        properties = _read_value(value, "properties", "_properties", default={})
        raw = _read_value(properties, "weight", "score", default=1.0)
    try:
        result = float(raw)
    except (TypeError, ValueError, OverflowError):
        return 1.0
    if not math.isfinite(result):
        return 1.0
    return max(0.0, min(1.0, result))


class ObjectGraphNeighborProvider:
    """Adapt common graph-backend objects to :class:`GraphNeighborProvider`."""

    def __init__(self, backend: Any):
        self.backend = backend

    def get_neighbors(
        self,
        node_id: str,
        *,
        direction: str,
        relationship_types: Sequence[str],
        limit: int,
    ) -> Iterable[TraversalEdge]:
        if self.backend is None:
            return ()
        effective_direction = "both" if direction == "adaptive" else direction
        backend_direction = {
            "outgoing": "out",
            "incoming": "in",
            "both": "both",
        }[effective_direction]

        if hasattr(self.backend, "get_relationships"):
            relationships = self._relationships(
                node_id,
                backend_direction,
                relationship_types,
            )
            edges: List[TraversalEdge] = []
            allowed_types = set(relationship_types)
            for relationship in relationships:
                rel_type = _read_value(
                    relationship,
                    "type",
                    "relationship_type",
                    "_type",
                    default=None,
                )
                if allowed_types and rel_type not in allowed_types:
                    continue
                source = _read_value(
                    relationship,
                    "source",
                    "source_id",
                    "start_node",
                    "_start_node",
                    default=None,
                )
                target = _read_value(
                    relationship,
                    "target",
                    "target_id",
                    "end_node",
                    "_end_node",
                    default=None,
                )
                if source is None and target is not None:
                    source = node_id
                if target is None and source is not None and source != node_id:
                    target = source
                    source = node_id
                if source is None or target is None:
                    continue

                source_id = str(source)
                target_id = str(target)
                if effective_direction == "incoming":
                    neighbor = source_id if target_id == node_id else target_id
                elif effective_direction == "both":
                    neighbor = target_id if source_id == node_id else source_id
                else:
                    neighbor = target_id
                if not neighbor or neighbor == node_id:
                    continue
                edges.append(
                    TraversalEdge(
                        source_id=node_id,
                        target_id=neighbor,
                        relationship_type=str(rel_type) if rel_type is not None else None,
                        weight=_edge_weight(relationship),
                        metadata=_read_value(
                            relationship,
                            "properties",
                            "_properties",
                            default={},
                        )
                        or {},
                    )
                )
                if len(edges) >= limit:
                    break
            return edges

        if hasattr(self.backend, "get_neighbors"):
            neighbors = self._neighbors(
                node_id,
                effective_direction,
                relationship_types,
                limit,
            )
            edges = []
            for neighbor in neighbors:
                if isinstance(neighbor, TraversalEdge):
                    edges.append(neighbor)
                elif isinstance(neighbor, str):
                    edges.append(TraversalEdge(node_id, neighbor))
                else:
                    target = _read_value(
                        neighbor,
                        "target",
                        "target_id",
                        "node_id",
                        "id",
                        default=None,
                    )
                    if target is not None:
                        edges.append(
                            TraversalEdge(
                                node_id,
                                str(target),
                                relationship_type=_read_value(
                                    neighbor,
                                    "type",
                                    "relationship_type",
                                    default=None,
                                ),
                                weight=_edge_weight(neighbor),
                            )
                        )
                if len(edges) >= limit:
                    break
            return edges
        return ()

    def _relationships(
        self,
        node_id: str,
        direction: str,
        relationship_types: Sequence[str],
    ) -> Iterable[Any]:
        method = self.backend.get_relationships
        if len(relationship_types) == 1:
            try:
                return method(
                    node_id,
                    direction=direction,
                    rel_type=relationship_types[0],
                )
            except TypeError:
                pass
        try:
            return method(node_id, direction=direction)
        except TypeError:
            return method(node_id)

    def _neighbors(
        self,
        node_id: str,
        direction: str,
        relationship_types: Sequence[str],
        limit: int,
    ) -> Iterable[Any]:
        method = self.backend.get_neighbors
        try:
            return method(
                node_id,
                direction=direction,
                rel_types=list(relationship_types) or None,
                limit=limit,
            )
        except TypeError:
            try:
                return method(
                    node_id,
                    rel_types=list(relationship_types) or None,
                )
            except TypeError:
                return method(node_id)


class ObjectNodeEmbeddingProvider:
    """Adapt common vector-store objects to batch node-vector retrieval."""

    def __init__(self, vector_store: Any):
        self.vector_store = vector_store

    def get_embeddings(self, node_ids: Sequence[str]) -> Mapping[str, Vector]:
        store = self.vector_store
        if store is None or not node_ids:
            return {}
        unique_ids = list(dict.fromkeys(str(node_id) for node_id in node_ids))

        if hasattr(store, "get_embeddings"):
            result = store.get_embeddings(unique_ids)
            if isinstance(result, Mapping):
                return {
                    str(node_id): vector
                    for node_id, vector in result.items()
                    if _finite_vector(vector) is not None
                }

        embeddings: Dict[str, Vector] = {}
        for node_id in unique_ids:
            value = None
            if hasattr(store, "get_by_id"):
                value = store.get_by_id(node_id)
            elif hasattr(store, "get_embedding"):
                value = store.get_embedding(node_id)
            if value is None:
                continue
            vector = _read_value(value, "embedding", "vector", default=value)
            if _finite_vector(vector) is not None:
                embeddings[node_id] = vector
        return embeddings


def _coerce_edge(raw_edge: Any, source_id: str) -> Optional[TraversalEdge]:
    if isinstance(raw_edge, TraversalEdge):
        if not raw_edge.source_id:
            return TraversalEdge(
                source_id=source_id,
                target_id=raw_edge.target_id,
                relationship_type=raw_edge.relationship_type,
                weight=raw_edge.weight,
                metadata=raw_edge.metadata,
            )
        return raw_edge
    if isinstance(raw_edge, str):
        return TraversalEdge(source_id, raw_edge)
    target = _read_value(
        raw_edge,
        "target_id",
        "target",
        "end_node",
        "node_id",
        "id",
        default=None,
    )
    if target is None:
        return None
    return TraversalEdge(
        source_id=source_id,
        target_id=str(target),
        relationship_type=_read_value(
            raw_edge,
            "relationship_type",
            "type",
            default=None,
        ),
        weight=_edge_weight(raw_edge),
        metadata=_read_value(raw_edge, "metadata", "properties", default={}) or {},
    )


class EmbeddingGuidedTraversal:
    """Run deterministic, budgeted semantic beam traversal over a graph."""

    def __init__(
        self,
        neighbor_provider: GraphNeighborProvider,
        embedding_provider: NodeEmbeddingProvider,
        config: Optional[SemanticTraversalConfig] = None,
    ):
        self.neighbor_provider = neighbor_provider
        self.embedding_provider = embedding_provider
        self.config = config or SemanticTraversalConfig()

    def traverse(
        self,
        seed_nodes: Sequence[str],
        query_embedding: Vector,
        *,
        config: Optional[SemanticTraversalConfig] = None,
    ) -> SemanticTraversalResult:
        """Traverse from ``seed_nodes`` toward the supplied query vector."""
        active = config or self.config
        query_vector = _finite_vector(query_embedding)
        if query_vector is None:
            raise ValueError("query_embedding must be a non-empty finite vector")

        diagnostics = TraversalDiagnostics()
        seeds = list(dict.fromkeys(str(node_id) for node_id in seed_nodes if node_id))
        if len(seeds) > active.max_nodes:
            seeds = seeds[: active.max_nodes]
            diagnostics.stop_reason = "max_nodes"

        embedding_cache: Dict[str, Tuple[float, ...]] = {}
        seed_embeddings = self._get_embeddings(seeds, diagnostics, active)
        embedding_cache.update(seed_embeddings)

        candidates: Dict[str, TraversalCandidate] = {}
        hop_distances: Dict[str, int] = {}
        for node_id in seeds:
            vector = embedding_cache.get(node_id)
            proximity = cosine_similarity(vector, query_vector) if vector else 0.0
            candidates[node_id] = TraversalCandidate(
                node_id=node_id,
                parent_id=None,
                depth=0,
                score=proximity,
                semantic_proximity=proximity,
                has_embedding=vector is not None,
            )
            hop_distances[node_id] = 0

        visited = set(seeds)
        frontier = sorted(
            candidates.values(),
            key=lambda item: (-item.score, item.node_id),
        )[: active.beam_width]
        diagnostics.frontier_peak = len(frontier)

        for depth in range(1, active.max_depth + 1):
            if not frontier:
                diagnostics.stop_reason = "frontier_exhausted"
                break
            if len(visited) >= active.max_nodes:
                diagnostics.stop_reason = "max_nodes"
                break

            raw_candidates: List[Tuple[TraversalCandidate, TraversalEdge]] = []
            edge_budget_hit = False
            backend_budget_hit = False
            for parent in frontier:
                if diagnostics.backend_calls >= active.max_backend_calls:
                    backend_budget_hit = True
                    break
                diagnostics.backend_calls += 1
                try:
                    raw_edges = list(
                        self.neighbor_provider.get_neighbors(
                            parent.node_id,
                            direction=active.direction,
                            relationship_types=active.relationship_types,
                            limit=active.max_degree,
                        )
                    )
                except Exception as error:  # Provider errors are optionally recoverable.
                    if active.fail_fast:
                        raise
                    diagnostics.provider_errors.append(
                        f"neighbors:{parent.node_id}:{type(error).__name__}:{error}"
                    )
                    continue

                normalized_edges: List[TraversalEdge] = []
                for raw_edge in raw_edges:
                    edge = _coerce_edge(raw_edge, parent.node_id)
                    if edge is None or not edge.target_id:
                        diagnostics.invalid_edges += 1
                        continue
                    normalized_edges.append(edge)
                normalized_edges.sort(
                    key=lambda edge: (
                        edge.target_id,
                        edge.relationship_type or "",
                        -edge.weight,
                    )
                )
                if len(normalized_edges) > active.max_degree:
                    diagnostics.degree_pruned += len(normalized_edges) - active.max_degree
                    normalized_edges = normalized_edges[: active.max_degree]

                for edge in normalized_edges:
                    if diagnostics.edges_scanned >= active.max_edges:
                        edge_budget_hit = True
                        break
                    diagnostics.edges_scanned += 1
                    if edge.target_id in visited:
                        diagnostics.cycles_skipped += 1
                        continue
                    raw_candidates.append((parent, edge))
                if edge_budget_hit:
                    break

            if backend_budget_hit:
                diagnostics.stop_reason = "max_backend_calls"
            elif edge_budget_hit:
                diagnostics.stop_reason = "max_edges"

            target_ids = list(
                dict.fromkeys(edge.target_id for _, edge in raw_candidates)
            )
            missing_ids = [
                node_id for node_id in target_ids if node_id not in embedding_cache
            ]
            embedding_cache.update(
                self._get_embeddings(missing_ids, diagnostics, active)
            )

            best_by_node: Dict[str, TraversalCandidate] = {}
            for parent, edge in raw_candidates:
                target_vector = embedding_cache.get(edge.target_id)
                parent_vector = embedding_cache.get(parent.node_id)
                candidate = self._score_candidate(
                    edge=edge,
                    parent=parent,
                    depth=depth,
                    query_vector=query_vector,
                    parent_vector=parent_vector,
                    target_vector=target_vector,
                    config=active,
                )
                if (
                    active.minimum_score is not None
                    and candidate.score < active.minimum_score
                ):
                    diagnostics.score_pruned += 1
                    continue
                incumbent = best_by_node.get(candidate.node_id)
                if incumbent is None or self._candidate_key(candidate) < self._candidate_key(
                    incumbent
                ):
                    best_by_node[candidate.node_id] = candidate

            ranked = sorted(best_by_node.values(), key=self._candidate_key)
            remaining_nodes = active.max_nodes - len(visited)
            keep_count = min(active.beam_width, remaining_nodes)
            next_frontier = ranked[:keep_count]
            diagnostics.beam_pruned += max(0, len(ranked) - keep_count)

            for candidate in next_frontier:
                visited.add(candidate.node_id)
                candidates[candidate.node_id] = candidate
                hop_distances[candidate.node_id] = depth
            frontier = next_frontier
            diagnostics.frontier_peak = max(
                diagnostics.frontier_peak,
                len(frontier),
            )
            diagnostics.depths_completed = depth

            if backend_budget_hit or edge_budget_hit:
                break
            if len(visited) >= active.max_nodes:
                diagnostics.stop_reason = "max_nodes"
                break
        else:
            diagnostics.stop_reason = "max_depth"

        if not active.include_seeds:
            for seed in seeds:
                candidates.pop(seed, None)
                hop_distances.pop(seed, None)

        diagnostics.nodes_visited = len(candidates)
        paths = self._build_paths(candidates)
        approximate = bool(
            diagnostics.embeddings_missing
            or diagnostics.degree_pruned
            or diagnostics.beam_pruned
            or diagnostics.score_pruned
            or diagnostics.provider_errors
            or diagnostics.stop_reason
            in {"max_nodes", "max_edges", "max_backend_calls"}
        )
        return SemanticTraversalResult(
            candidates=candidates,
            hop_distances=hop_distances,
            paths=paths,
            diagnostics=diagnostics,
            approximate=approximate,
        )

    def _get_embeddings(
        self,
        node_ids: Sequence[str],
        diagnostics: TraversalDiagnostics,
        config: SemanticTraversalConfig,
    ) -> Dict[str, Tuple[float, ...]]:
        if not node_ids:
            return {}
        diagnostics.embedding_calls += 1
        diagnostics.embeddings_requested += len(node_ids)
        try:
            raw_embeddings = self.embedding_provider.get_embeddings(node_ids)
        except Exception as error:  # Provider errors are optionally recoverable.
            if config.fail_fast:
                raise
            diagnostics.provider_errors.append(
                f"embeddings:{type(error).__name__}:{error}"
            )
            diagnostics.embeddings_missing += len(node_ids)
            return {}

        embeddings: Dict[str, Tuple[float, ...]] = {}
        for node_id in node_ids:
            vector = _finite_vector(raw_embeddings.get(node_id))
            if vector is not None:
                embeddings[node_id] = vector
        diagnostics.embeddings_found += len(embeddings)
        diagnostics.embeddings_missing += len(node_ids) - len(embeddings)
        return embeddings

    @staticmethod
    def _score_candidate(
        *,
        edge: TraversalEdge,
        parent: TraversalCandidate,
        depth: int,
        query_vector: Tuple[float, ...],
        parent_vector: Optional[Tuple[float, ...]],
        target_vector: Optional[Tuple[float, ...]],
        config: SemanticTraversalConfig,
    ) -> TraversalCandidate:
        has_embedding = target_vector is not None
        proximity = (
            cosine_similarity(target_vector, query_vector) if has_embedding else 0.0
        )
        progress = 0.0
        direction = 0.0
        if target_vector is not None and parent_vector is not None:
            parent_proximity = cosine_similarity(parent_vector, query_vector)
            progress = max(-1.0, min(1.0, proximity - parent_proximity))
            graph_delta = _difference(target_vector, parent_vector)
            query_delta = _difference(query_vector, parent_vector)
            direction = cosine_similarity(graph_delta, query_delta)

        try:
            relationship_score = float(edge.weight)
        except (TypeError, ValueError, OverflowError):
            relationship_score = 1.0
        if not math.isfinite(relationship_score):
            relationship_score = 1.0
        relationship_score = max(0.0, min(1.0, relationship_score))
        weights = config.weights
        depth_fraction = depth / max(1, config.max_depth)
        score = (
            weights.proximity * proximity
            + weights.progress * progress
            + weights.direction * direction
            + weights.relationship * relationship_score
            - weights.depth_penalty * depth_fraction
        )
        return TraversalCandidate(
            node_id=edge.target_id,
            parent_id=parent.node_id,
            depth=depth,
            score=score,
            semantic_proximity=proximity,
            semantic_progress=progress,
            semantic_direction=direction,
            relationship_score=relationship_score,
            relationship_type=edge.relationship_type,
            has_embedding=has_embedding,
        )

    @staticmethod
    def _candidate_key(candidate: TraversalCandidate) -> Tuple[Any, ...]:
        """Sort highest score first with stable, reproducible tie breaks."""
        return (
            -candidate.score,
            candidate.node_id,
            candidate.parent_id or "",
            candidate.relationship_type or "",
        )

    @staticmethod
    def _build_paths(
        candidates: Mapping[str, TraversalCandidate],
    ) -> List[TraversalPath]:
        paths: List[TraversalPath] = []
        for candidate in sorted(
            candidates.values(),
            key=lambda item: (-item.score, item.depth, item.node_id),
        ):
            node_ids = [candidate.node_id]
            relationship_types: List[Optional[str]] = []
            cursor = candidate
            seen = {candidate.node_id}
            while cursor.parent_id is not None and cursor.parent_id not in seen:
                relationship_types.append(cursor.relationship_type)
                seen.add(cursor.parent_id)
                node_ids.append(cursor.parent_id)
                parent = candidates.get(cursor.parent_id)
                if parent is None:
                    break
                cursor = parent
            paths.append(
                TraversalPath(
                    node_ids=tuple(reversed(node_ids)),
                    relationship_types=tuple(reversed(relationship_types)),
                    score=candidate.score,
                )
            )
        return paths


__all__ = [
    "EmbeddingGuidedTraversal",
    "GraphNeighborProvider",
    "NodeEmbeddingProvider",
    "ObjectGraphNeighborProvider",
    "ObjectNodeEmbeddingProvider",
    "SemanticTraversalConfig",
    "SemanticTraversalResult",
    "SemanticTraversalWeights",
    "TraversalCandidate",
    "TraversalDiagnostics",
    "TraversalEdge",
    "TraversalPath",
    "cosine_similarity",
]
