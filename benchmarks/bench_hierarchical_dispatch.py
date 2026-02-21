"""Phase E1: Benchmark — HierarchicalToolManager.dispatch() latency.

Measures the round-trip time for:
- A warm-cache dispatch to a valid category/tool.
- A cold-cache dispatch (first call, triggers discovery).
- A dispatch to an invalid category (fast error path).
- dispatch_parallel() fanning out N calls concurrently (Phase F1).

Run with::

    pytest benchmarks/bench_hierarchical_dispatch.py -v
"""
from __future__ import annotations

import anyio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import (
    HierarchicalToolManager,
    ToolCategory,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def manager_with_mock_category() -> HierarchicalToolManager:
    """Return a manager whose ``dataset_tools`` category is pre-populated with
    a fast async mock tool — no filesystem I/O required."""
    mgr = HierarchicalToolManager.__new__(HierarchicalToolManager)
    mgr.tools_root = Path("/dev/null")
    mgr.categories = {}
    mgr._category_metadata = {}
    mgr._discovered_categories = True
    mgr._lazy_loaders = {}
    mgr._shutting_down = False

    # Build a minimal ToolCategory with one async tool.
    cat = ToolCategory.__new__(ToolCategory)
    cat.name = "dataset_tools"
    cat.path = Path("/dev/null")
    cat.description = ""
    cat._tools = {"load_dataset": AsyncMock(return_value={"status": "ok", "rows": 100})}
    cat._tool_metadata = {}
    cat._discovered = True
    cat._schema_cache = {}
    cat._cache_hits = 0
    cat._cache_misses = 0

    mgr.categories["dataset_tools"] = cat
    return mgr


# ---------------------------------------------------------------------------
# Benchmarks
# ---------------------------------------------------------------------------

@pytest.mark.benchmark(group="dispatch")
def test_dispatch_warm_cache(benchmark, manager_with_mock_category):
    """dispatch() on a pre-loaded category (warm cache)."""

    async def _run():
        return await manager_with_mock_category.dispatch(
            "dataset_tools", "load_dataset", {"source": "squad"}
        )

    result = benchmark(lambda: anyio.from_thread.run_sync(_run) if False else anyio.run(_run))
    assert result.get("status") == "ok"


@pytest.mark.benchmark(group="dispatch")
def test_dispatch_invalid_category(benchmark, manager_with_mock_category):
    """dispatch() on a non-existent category (error fast-path)."""

    async def _run():
        return await manager_with_mock_category.dispatch(
            "nonexistent_category", "some_tool", {}
        )

    result = benchmark(lambda: anyio.run(_run))
    assert result.get("status") == "error"


@pytest.mark.benchmark(group="dispatch_parallel")
def test_dispatch_parallel_4_calls(benchmark, manager_with_mock_category):
    """dispatch_parallel() with 4 concurrent calls."""
    calls = [
        {"category": "dataset_tools", "tool": "load_dataset", "params": {"source": f"dataset_{i}"}}
        for i in range(4)
    ]

    async def _run():
        return await manager_with_mock_category.dispatch_parallel(calls)

    results = benchmark(lambda: anyio.run(_run))
    assert len(results) == 4
    assert all(r.get("status") == "ok" for r in results)


@pytest.mark.benchmark(group="dispatch_parallel")
def test_dispatch_parallel_16_calls(benchmark, manager_with_mock_category):
    """dispatch_parallel() with 16 concurrent calls (throughput test)."""
    calls = [
        {"category": "dataset_tools", "tool": "load_dataset", "params": {"source": f"dataset_{i}"}}
        for i in range(16)
    ]

    async def _run():
        return await manager_with_mock_category.dispatch_parallel(calls)

    results = benchmark(lambda: anyio.run(_run))
    assert len(results) == 16
