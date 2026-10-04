from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class ExecutionBudgets:
    """Hard budgets to keep graph queries safe on large graphs."""

    timeout_ms: int = 10_000

    # Result shaping
    max_results: int = 100

    # Optional: cap approximate size (in bytes) of returned items.
    # 0 means unlimited.
    max_output_bytes: int = 0

    # Work bounds
    max_depth: int = 3
    max_nodes_visited: int = 50_000
    max_edges_scanned: int = 250_000

    # Optional: cap how large the intermediate working set (entity IDs) may grow
    # at any step (after SeedEntities/ScanType/Expand). Set to a value aligned
    # with node/edge budgets to prevent accidental memory blow-ups.
    max_working_set_entities: int = 50_000

    # Local blow-up control
    max_degree_per_node: int = 10_000

    # Sharded-CAR routing bound (v1)
    max_shards_touched: int = 64

    # Optional executor-level paging hints.
    # When >0, the executor will request at most this many items per backend call,
    # forcing cursor pagination and reducing per-call payload size.
    page_size_scan_type: int = 0
    page_size_neighbors: int = 0

    # Optional: header materialization batch size.
    # When >0, the executor will call get_entity_headers() in batches of this size.
    page_size_headers: int = 0

    # Optional: cap how many entity IDs the executor will attempt to materialize
    # headers for (across all batches) while building the final result set.
    # 0 means unlimited.
    max_header_entities: int = 0

    # Policy: reject global scans unless graph is "small".
    allow_unanchored_scan: bool = False

    # Optional: cap the total number of backend calls the executor may make
    # (scan_type pages + neighbors pages + get_entity_headers batches).
    # 0 means unlimited.
    max_backend_calls: int = 0

    # Optional: more targeted caps (0 means unlimited).
    # These are enforced in addition to max_backend_calls.
    max_scan_pages: int = 0
    max_neighbor_pages: int = 0
    max_header_batches: int = 0


@dataclass
class ExecutionCounters:
    nodes_visited: int = 0
    edges_scanned: int = 0
    shards_touched: int = 0
    depth: int = 0


def budgets_from_preset(
    preset: Optional[str],
    *,
    max_results: int = 100,
    overrides: Optional[Mapping[str, Any]] = None,
) -> ExecutionBudgets:
    """Create ExecutionBudgets from a named preset plus optional overrides.

    Presets are intended to be stable, human-friendly profiles for configuring
    safe graph-query execution.

    Supported presets:
    - None / "default" / "safe": current safe-by-default settings.
    - "strict": tighter bounds for highly untrusted inputs.
    - "debug": more permissive bounds for controlled environments.
    """

    name = (preset or "safe").strip().lower()

    if name in {"safe", "default", ""}:
        base = ExecutionBudgets(max_results=int(max_results))
    elif name == "strict":
        base = ExecutionBudgets(
            timeout_ms=5_000,
            max_results=int(max_results),
            max_depth=3,
            max_nodes_visited=10_000,
            max_edges_scanned=50_000,
            max_working_set_entities=10_000,
            max_degree_per_node=500,
            max_shards_touched=32,
            page_size_scan_type=1_000,
            page_size_neighbors=200,
            max_backend_calls=500,
            max_scan_pages=50,
            max_neighbor_pages=200,
            max_header_batches=100,
        )
    elif name == "debug":
        base = ExecutionBudgets(
            timeout_ms=30_000,
            max_results=int(max_results),
            max_depth=5,
            max_nodes_visited=200_000,
            max_edges_scanned=1_000_000,
            max_working_set_entities=200_000,
            max_degree_per_node=50_000,
            max_shards_touched=256,
        )
    else:
        raise ValueError(f"Unknown graph-query budget preset: {preset!r}")

    if overrides:
        # Note: unknown keys should raise TypeError from dataclass construction;
        # this helps catch typos early.
        return replace(base, **dict(overrides))
    return base
