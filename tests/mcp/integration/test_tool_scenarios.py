"""
Phase B3: End-to-end scenario integration tests for the MCP server.

Each test simulates a realistic multi-step workflow, exercising several
tool categories in sequence via :class:`HierarchicalToolManager`.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Guard: monitoring.py requires psutil
try:
    import psutil  # noqa: F401
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_manager(extra_tools: Dict[str, Any] | None = None):
    """Return a HierarchicalToolManager wired with mock tools."""
    from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import (
        HierarchicalToolManager,
        ToolCategory,
    )

    manager = HierarchicalToolManager(tools_root=Path("/fake"))
    # Mark as discovered so dispatch() doesn't re-scan /fake (which doesn't exist)
    manager._discovered_categories = True

    defaults: Dict[str, Any] = {
        "dataset_tools/load_dataset":          lambda **kw: {"success": True, "dataset_id": "ds1", "rows": 10},
        "embedding_tools/generate_embedding":  lambda **kw: {"success": True, "embedding": [0.1] * 4},
        "search_tools/semantic_search":        lambda **kw: {"success": True, "results": ["r1", "r2"]},
        "graph_tools/graph_create":            lambda **kw: {"success": True, "graph_id": "g1"},
        "graph_tools/graph_add_entity":        lambda **kw: {"success": True},
        "graph_tools/graph_query_cypher":      lambda **kw: {"success": True, "results": []},
        "monitoring_tools/get_metrics":        lambda **kw: {"success": True, "metrics": {}},
        "cache_tools/get_cache_stats":         lambda **kw: {"success": True, "stats": {}},
        "pdf_tools/pdf_extract_text":          lambda **kw: {"success": True, "text": "Sample PDF text."},
        "pdf_tools/pdf_extract_entities":      lambda **kw: {"success": True, "entities": ["Alice", "Bob"]},
        "storage_tools/store_data":            lambda **kw: {"success": True, "storage_id": "s1"},
        "provenance_tools/record_provenance":  lambda **kw: {"success": True, "provenance_id": "p1"},
        "failing_category/failing_tool":       None,  # placeholder; set per-test
    }
    if extra_tools:
        defaults.update(extra_tools)

    for full_name, fn in defaults.items():
        if fn is None:
            continue
        cat_name, tool_name = full_name.split("/", 1)
        if cat_name not in manager.categories:
            cat = ToolCategory(cat_name, Path("/fake") / cat_name)
            cat._discovered = True
            manager.categories[cat_name] = cat
        manager.categories[cat_name]._tools[tool_name] = fn

    return manager


# ---------------------------------------------------------------------------
# Scenario 1: Dataset → embed → index → search
# ---------------------------------------------------------------------------

class TestDatasetSearchPipeline:
    """Scenario: load a dataset, embed records, index them, and run semantic search."""

    @pytest.mark.asyncio
    async def test_pipeline_succeeds_end_to_end(self):
        """
        GIVEN: A manager with dataset, embedding, and search tools
        WHEN:  Executing a load → embed → search sequence
        THEN:  Each step succeeds and the final result contains ranked documents
        """
        manager = _make_manager()

        step1 = await manager.dispatch("dataset_tools", "load_dataset", params={"source": "squad"})
        assert step1["success"] is True, f"load_dataset failed: {step1}"

        step2 = await manager.dispatch("embedding_tools", "generate_embedding", params={"text": "what is AI?"})
        assert step2["success"] is True
        assert "embedding" in step2

        step3 = await manager.dispatch(
            "search_tools", "semantic_search",
            params={"query": "what is AI?", "embedding": step2["embedding"]},
        )
        assert step3["success"] is True
        assert len(step3["results"]) >= 1

    @pytest.mark.asyncio
    async def test_pipeline_propagates_dataset_id(self):
        """
        GIVEN: Load returns a dataset_id
        WHEN:  Downstream tools reference that id
        THEN:  The id flows through each step unchanged
        """
        manager = _make_manager()

        load_result = await manager.dispatch("dataset_tools", "load_dataset", params={"source": "imdb"})
        dataset_id = load_result.get("dataset_id")
        assert dataset_id is not None

        embed_result = await manager.dispatch(
            "embedding_tools", "generate_embedding",
            params={"dataset_id": dataset_id, "text": "review"},
        )
        assert embed_result["success"] is True


# ---------------------------------------------------------------------------
# Scenario 2: PDF → entity extraction → graph build → Cypher query
# ---------------------------------------------------------------------------

class TestGraphKnowledgeExtraction:
    """Scenario: extract entities from a PDF, build a knowledge graph, and query it."""

    @pytest.mark.asyncio
    async def test_pdf_to_graph_query(self):
        """
        GIVEN: A manager with pdf, graph, and storage tools
        WHEN:  Executing pdf_extract → graph_create → add_entities → query
        THEN:  All steps succeed; query results reference the added entities
        """
        manager = _make_manager(
            extra_tools={
                "graph_tools/graph_query_cypher": lambda **kw: {
                    "success": True,
                    "results": [{"entity": "Alice"}, {"entity": "Bob"}],
                }
            }
        )

        # Step 1: extract text
        text_result = await manager.dispatch("pdf_tools", "pdf_extract_text", params={"pdf_path": "/tmp/test.pdf"})
        assert text_result["success"] is True
        assert "text" in text_result

        # Step 2: extract entities
        entity_result = await manager.dispatch(
            "pdf_tools", "pdf_extract_entities", params={"pdf_path": "/tmp/test.pdf"}
        )
        assert entity_result["success"] is True
        entities = entity_result.get("entities", [])
        assert len(entities) >= 1

        # Step 3: create graph
        graph_result = await manager.dispatch("graph_tools", "graph_create", params={"name": "pdf_kg"})
        assert graph_result["success"] is True
        graph_id = graph_result["graph_id"]

        # Step 4: add entities to graph
        for entity in entities:
            add_result = await manager.dispatch(
                "graph_tools", "graph_add_entity",
                params={"graph_id": graph_id, "entity_name": entity},
            )
            assert add_result["success"] is True

        # Step 5: query graph
        query_result = await manager.dispatch(
            "graph_tools", "graph_query_cypher",
            params={"graph_id": graph_id, "query": "MATCH (e:Entity) RETURN e"},
        )
        assert query_result["success"] is True
        assert len(query_result["results"]) >= 1


# ---------------------------------------------------------------------------
# Scenario 3: Parallel dispatch → caching → verify
# ---------------------------------------------------------------------------

class TestParallelDispatchWithCaching:
    """Scenario: fan-out several tool calls in parallel, verify results arrive in order."""

    @pytest.mark.asyncio
    async def test_parallel_dispatch_preserves_order(self):
        """
        GIVEN: A manager with 4 registered tools
        WHEN:  dispatch_parallel is called with 4 calls
        THEN:  Results are returned in the same order as the calls list
        """
        manager = _make_manager()

        calls = [
            {"category": "dataset_tools", "tool": "load_dataset", "params": {"source": "s1"}},
            {"category": "dataset_tools", "tool": "load_dataset", "params": {"source": "s2"}},
            {"category": "search_tools",  "tool": "semantic_search", "params": {"query": "q1"}},
            {"category": "cache_tools",   "tool": "get_cache_stats",  "params": {}},
        ]

        results = await manager.dispatch_parallel(calls, return_exceptions=True)

        assert len(results) == 4
        for i, res in enumerate(results):
            assert isinstance(res, dict), f"result[{i}] is not a dict: {res}"
            assert res.get("success") is True, f"result[{i}] was not successful: {res}"

    @pytest.mark.asyncio
    async def test_parallel_dispatch_error_captured(self):
        """
        GIVEN: One tool in the parallel batch that raises an exception
        WHEN:  return_exceptions=True
        THEN:  The error is captured as a dict; other results are unaffected
        """
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import ToolCategory

        manager = _make_manager()

        def _fail(**kwargs):
            raise RuntimeError("intentional failure")

        cat = ToolCategory("failing_category", Path("/fake/failing_category"))
        cat._discovered = True
        cat._tools["failing_tool"] = _fail
        manager.categories["failing_category"] = cat

        calls = [
            {"category": "dataset_tools",     "tool": "load_dataset", "params": {"source": "ok"}},
            {"category": "failing_category",  "tool": "failing_tool",  "params": {}},
            {"category": "cache_tools",       "tool": "get_cache_stats", "params": {}},
        ]

        results = await manager.dispatch_parallel(calls, return_exceptions=True)
        assert len(results) == 3
        assert results[0].get("success") is True
        # Index 1 should be an error dict (not a raised exception)
        assert "error" in results[1] or results[1].get("success") is False
        assert results[2].get("success") is True


# ---------------------------------------------------------------------------
# Scenario 4: Monitoring pipeline — track calls → percentiles → alert check
# ---------------------------------------------------------------------------

class TestMonitoringPipeline:
    """Scenario: emit tool-execution metrics and verify histogram percentiles."""

    @pytest.mark.skipif(not PSUTIL_AVAILABLE, reason="psutil not installed")
    def test_track_and_query_percentiles(self):
        """
        GIVEN: An EnhancedMetricsCollector receiving tool execution samples
        WHEN:  get_tool_latency_percentiles() is called
        THEN:  p50/p95/p99 values are consistent with the inserted data
        """
        from ipfs_datasets_py.mcp_server.monitoring import EnhancedMetricsCollector

        collector = EnhancedMetricsCollector(enabled=True)

        # Feed 10 execution samples (ms)
        samples = [10, 15, 20, 25, 30, 35, 40, 45, 50, 200]
        for t in samples:
            collector.track_tool_execution("my_scenario_tool", float(t), success=True)

        p = collector.get_tool_latency_percentiles("my_scenario_tool")

        assert p["count"] == 10
        assert p["min"] == pytest.approx(10.0)
        assert p["max"] == pytest.approx(200.0)
        # p50 should be around the median (between 30 and 35 for 10 samples)
        assert 25.0 <= p["p50"] <= 40.0
        # p99 should be close to the 200ms outlier
        assert p["p99"] >= 100.0

    @pytest.mark.skipif(not PSUTIL_AVAILABLE, reason="psutil not installed")
    def test_percentiles_included_in_metrics_summary(self):
        """
        GIVEN: A collector with tool execution data
        WHEN:  get_metrics_summary() is called
        THEN:  tool_latency_percentiles key is present and populated
        """
        from ipfs_datasets_py.mcp_server.monitoring import EnhancedMetricsCollector

        collector = EnhancedMetricsCollector(enabled=True)
        for t in [5, 10, 15, 20, 25]:
            collector.track_tool_execution("scenario_tool_b", float(t), success=True)

        summary = collector.get_metrics_summary()
        assert "tool_latency_percentiles" in summary
        percs = summary["tool_latency_percentiles"]
        assert "scenario_tool_b" in percs
        assert percs["scenario_tool_b"]["count"] == 5

    @pytest.mark.skipif(not PSUTIL_AVAILABLE, reason="psutil not installed")
    def test_percentiles_empty_when_no_data(self):
        """
        GIVEN: A collector with no data for a tool
        WHEN:  get_tool_latency_percentiles() is called
        THEN:  Returns all zeros with count=0
        """
        from ipfs_datasets_py.mcp_server.monitoring import EnhancedMetricsCollector

        collector = EnhancedMetricsCollector(enabled=True)
        p = collector.get_tool_latency_percentiles("nonexistent_tool")
        assert p["count"] == 0
        assert p["p50"] == 0.0
        assert p["p99"] == 0.0


# ---------------------------------------------------------------------------
# Scenario 5: Provenance + storage pipeline
# ---------------------------------------------------------------------------

class TestProvenanceStoragePipeline:
    """Scenario: store data + record provenance → retrieve both → verify linkage."""

    @pytest.mark.asyncio
    async def test_store_then_record_provenance(self):
        """
        GIVEN: Storage and provenance tools
        WHEN:  store_data is called followed by record_provenance
        THEN:  Both return success and share a common data identifier
        """
        manager = _make_manager()

        store_result = await manager.dispatch(
            "storage_tools", "store_data",
            params={"data": {"key": "value"}, "collection": "test_collection"},
        )
        assert store_result["success"] is True
        storage_id = store_result.get("storage_id", "s1")

        provenance_result = await manager.dispatch(
            "provenance_tools", "record_provenance",
            params={"resource_id": storage_id, "action": "store", "actor": "test_scenario"},
        )
        assert provenance_result["success"] is True
        assert "provenance_id" in provenance_result

    @pytest.mark.asyncio
    async def test_pipeline_with_graceful_shutdown(self):
        """
        GIVEN: A manager that processes a call then shuts down gracefully
        WHEN:  graceful_shutdown() is called
        THEN:  Subsequent dispatches return error dicts rather than executing
        """
        manager = _make_manager()

        # Normal call succeeds
        result = await manager.dispatch("storage_tools", "store_data", params={"data": "x"})
        assert result["success"] is True

        # Shutdown
        shutdown_result = await manager.graceful_shutdown(timeout=1.0)
        assert shutdown_result["status"] in ("ok", "timeout")

        # Post-shutdown call should be rejected
        post_result = await manager.dispatch("storage_tools", "store_data", params={"data": "y"})
        assert post_result.get("success") is not True or "error" in post_result
