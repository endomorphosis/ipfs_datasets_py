"""Phase E1: Benchmark — ToolCategory.get_tool_schema() cache hit vs. miss.

Measures the overhead of:
- A schema **cache miss** (first call; runs inspect.signature()).
- A schema **cache hit** (subsequent call; returns pre-built dict).

Run with::

    pytest benchmarks/bench_schema_cache.py -v
"""
from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import ToolCategory


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def category_with_tool() -> ToolCategory:
    """Return a ToolCategory with one real async function (not a Mock)
    so that inspect.signature() exercises the normal code path."""

    async def load_dataset(source: str, split: str = "train", max_rows: int = 1000):
        """Load a dataset from a source."""
        return {"rows": max_rows, "source": source, "split": split}

    cat = ToolCategory.__new__(ToolCategory)
    cat.name = "dataset_tools"
    cat.path = Path("/dev/null")
    cat.description = ""
    cat._tools = {"load_dataset": load_dataset}
    cat._tool_metadata = {
        "load_dataset": {
            "name": "load_dataset",
            "description": "Load a dataset from a source.",
            "category": "dataset_tools",
        }
    }
    cat._discovered = True
    cat._schema_cache = {}
    cat._cache_hits = 0
    cat._cache_misses = 0
    return cat


# ---------------------------------------------------------------------------
# Benchmarks
# ---------------------------------------------------------------------------

@pytest.mark.benchmark(group="schema_cache")
def test_schema_cache_miss(benchmark, category_with_tool):
    """Schema cache miss — runs inspect.signature() on every call."""

    def _run():
        # Clear cache to force a miss each time.
        category_with_tool._schema_cache.clear()
        return category_with_tool.get_tool_schema("load_dataset")

    result = benchmark(_run)
    assert result is not None
    assert isinstance(result, dict)


@pytest.mark.benchmark(group="schema_cache")
def test_schema_cache_hit(benchmark, category_with_tool):
    """Schema cache hit — returns pre-built dict without inspect.signature()."""

    # Prime the cache with one call.
    category_with_tool.get_tool_schema("load_dataset")

    def _run():
        return category_with_tool.get_tool_schema("load_dataset")

    result = benchmark(_run)
    assert result is not None


@pytest.mark.benchmark(group="schema_cache")
def test_schema_cache_hit_ratio(benchmark, category_with_tool):
    """Read the same schema 100 times; verify cache stats are plausible."""
    # Prime cache.
    category_with_tool.get_tool_schema("load_dataset")

    def _run():
        for _ in range(100):
            category_with_tool.get_tool_schema("load_dataset")

    benchmark(_run)
    assert category_with_tool._cache_hits > 0
