"""Bounded AST impact / conflict / dependency closure queries (DQK-033).

Provides reverse-reference, call, import, effect, and semantic-dependency
closures bound to an exact source revision, with depth/row/time budgets.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Final, Iterable, Mapping, Sequence

__all__ = [
    "DUCKDB_IMPACT_SCHEMA",
    "BudgetExceeded",
    "ImpactBudget",
    "ImpactEdge",
    "ImpactGraph",
    "ImpactQueryError",
    "ImpactResult",
    "closure",
]


DUCKDB_IMPACT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/logic-software-contracts-duckdb-impact@1"
)


class ImpactQueryError(ValueError):
    pass


class BudgetExceeded(ImpactQueryError):
    def __init__(self, kind: str, limit: int | float) -> None:
        super().__init__(f"budget exceeded: {kind} limit={limit}")
        self.kind = kind
        self.limit = limit


@dataclass(frozen=True)
class ImpactBudget:
    max_depth: int = 8
    max_rows: int = 10_000
    max_seconds: float = 2.0

    def __post_init__(self) -> None:
        if self.max_depth < 0:
            raise ImpactQueryError("max_depth must be non-negative")
        if self.max_rows < 1:
            raise ImpactQueryError("max_rows must be >= 1")
        if self.max_seconds <= 0:
            raise ImpactQueryError("max_seconds must be positive")


@dataclass(frozen=True)
class ImpactEdge:
    source: str
    target: str
    kind: str  # call | import | reference | effect | dependency


@dataclass
class ImpactGraph:
    """In-memory adjacency for hermetic fixtures and analyzer agreement."""

    source_revision: str
    edges: list[ImpactEdge] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.source_revision.strip():
            raise ImpactQueryError("source_revision is required")

    def add(
        self, source: str, target: str, kind: str = "dependency"
    ) -> None:
        self.edges.append(ImpactEdge(source=source, target=target, kind=kind))

    def neighbors(
        self, node: str, *, kinds: frozenset[str] | None = None
    ) -> list[str]:
        out: list[str] = []
        for edge in self.edges:
            if edge.source != node:
                continue
            if kinds is not None and edge.kind not in kinds:
                continue
            out.append(edge.target)
        return out

    def reverse_neighbors(
        self, node: str, *, kinds: frozenset[str] | None = None
    ) -> list[str]:
        out: list[str] = []
        for edge in self.edges:
            if edge.target != node:
                continue
            if kinds is not None and edge.kind not in kinds:
                continue
            out.append(edge.source)
        return out


@dataclass(frozen=True)
class ImpactResult:
    source_revision: str
    roots: tuple[str, ...]
    nodes: tuple[str, ...]
    edges: tuple[ImpactEdge, ...]
    depth_reached: int
    truncated: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": DUCKDB_IMPACT_SCHEMA,
            "source_revision": self.source_revision,
            "roots": list(self.roots),
            "nodes": list(self.nodes),
            "edges": [
                {"source": e.source, "target": e.target, "kind": e.kind}
                for e in self.edges
            ],
            "depth_reached": self.depth_reached,
            "truncated": self.truncated,
        }


def closure(
    graph: ImpactGraph,
    roots: Sequence[str],
    *,
    direction: str = "forward",
    kinds: Iterable[str] | None = None,
    budget: ImpactBudget | None = None,
) -> ImpactResult:
    """Compute a bounded closure bound to ``graph.source_revision``."""

    if direction not in {"forward", "reverse"}:
        raise ImpactQueryError("direction must be forward or reverse")
    bud = budget or ImpactBudget()
    kind_set = frozenset(kinds) if kinds is not None else None
    started = time.monotonic()
    seen: set[str] = set()
    ordered: list[str] = []
    used_edges: list[ImpactEdge] = []
    frontier = [(root, 0) for root in roots]
    depth_reached = 0
    truncated = False

    while frontier:
        if time.monotonic() - started > bud.max_seconds:
            raise BudgetExceeded("time", bud.max_seconds)
        node, depth = frontier.pop(0)
        if node in seen:
            continue
        if len(ordered) >= bud.max_rows:
            truncated = True
            break
        seen.add(node)
        ordered.append(node)
        depth_reached = max(depth_reached, depth)
        if depth >= bud.max_depth:
            continue
        if direction == "forward":
            nxt = graph.neighbors(node, kinds=kind_set)
            edge_iter = (
                e
                for e in graph.edges
                if e.source == node and (kind_set is None or e.kind in kind_set)
            )
        else:
            nxt = graph.reverse_neighbors(node, kinds=kind_set)
            edge_iter = (
                e
                for e in graph.edges
                if e.target == node and (kind_set is None or e.kind in kind_set)
            )
        for edge in edge_iter:
            used_edges.append(edge)
        for child in nxt:
            if child not in seen:
                if len(ordered) + len(frontier) >= bud.max_rows:
                    truncated = True
                    break
                frontier.append((child, depth + 1))
        if truncated:
            break

    return ImpactResult(
        source_revision=graph.source_revision,
        roots=tuple(roots),
        nodes=tuple(ordered),
        edges=tuple(used_edges),
        depth_reached=depth_reached,
        truncated=truncated,
    )
