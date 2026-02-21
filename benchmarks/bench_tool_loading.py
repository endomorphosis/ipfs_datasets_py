"""Phase E1: Benchmark — lazy vs. eager tool category startup.

Measures:
- The time to ``discover_categories()`` on a real tools directory.
- The time for the lazy-loading path to serve the first tool from a category.
- The time for a fully warm (already-discovered) category.

Run with::

    pytest benchmarks/bench_tool_loading.py -v
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import (
    HierarchicalToolManager,
    ToolCategory,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def fresh_manager() -> HierarchicalToolManager:
    """Return a fresh HierarchicalToolManager that has NOT yet discovered categories."""
    mgr = HierarchicalToolManager()
    # Force a reset so each benchmark iteration starts from scratch.
    mgr._discovered_categories = False
    mgr.categories.clear()
    return mgr


@pytest.fixture()
def warm_manager() -> HierarchicalToolManager:
    """Return a manager that has already run discover_categories()."""
    mgr = HierarchicalToolManager()
    mgr.discover_categories()
    return mgr


# ---------------------------------------------------------------------------
# Benchmarks
# ---------------------------------------------------------------------------

@pytest.mark.benchmark(group="tool_loading")
def test_discover_categories(benchmark, fresh_manager):
    """Full category discovery from the real tools directory."""

    def _run():
        fresh_manager._discovered_categories = False
        fresh_manager.categories.clear()
        fresh_manager.discover_categories()

    benchmark(_run)
    assert fresh_manager._discovered_categories


@pytest.mark.benchmark(group="tool_loading")
def test_discover_single_category(benchmark, fresh_manager):
    """Discover only the dataset_tools category."""
    cat_path = fresh_manager.tools_root / "dataset_tools"
    if not cat_path.exists():
        pytest.skip("dataset_tools category not found")

    def _run():
        cat = ToolCategory("dataset_tools", cat_path)
        cat.discover_tools()
        return cat

    discovered_cat = benchmark(_run)
    assert discovered_cat._discovered


@pytest.mark.benchmark(group="tool_loading")
def test_list_categories_warm(benchmark, warm_manager):
    """list_categories() on an already-warm manager — measures pure dict look-up."""
    import anyio

    async def _run():
        return await warm_manager.list_categories()

    result = benchmark(lambda: anyio.run(_run))
    assert isinstance(result, list)
    assert len(result) > 0


@pytest.mark.benchmark(group="tool_loading")
def test_list_tools_in_category(benchmark, warm_manager):
    """list_tools() for the graph_tools category (already warm)."""
    import anyio

    cat_name = next(
        (name for name in warm_manager.categories if "graph" in name),
        next(iter(warm_manager.categories), None),
    )
    if cat_name is None:
        pytest.skip("No categories available")

    async def _run():
        return await warm_manager.list_tools(cat_name)

    result = benchmark(lambda: anyio.run(_run))
    assert "tools" in result or isinstance(result, dict)
