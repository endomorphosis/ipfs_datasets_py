"""
Tests for session-8 engine modules:
- embedding_analysis_engine.py
- biomolecule_engine.py
- background_task_engine.py
- HierarchicalToolManager lazy-loading (Phase 7)
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest


# ── EmbeddingAnalysisEngine ────────────────────────────────────────────────

class TestVectorEmbeddingAnalyzerUnavailable:
    """Tests that run without numpy / ML libraries installed (graceful degradation)."""

    def setup_method(self):
        from ipfs_datasets_py.mcp_server.tools.finance_data_tools.embedding_analysis_engine import (
            VectorEmbeddingAnalyzer,
        )
        self.VEA = VectorEmbeddingAnalyzer

    def test_init_without_ml_libraries(self):
        """GIVEN no ML libs; WHEN instantiating; THEN no exception."""
        analyzer = self.VEA()
        assert hasattr(analyzer, "embeddings")
        assert hasattr(analyzer, "correlations")

    def test_generate_text_embedding_returns_vector(self):
        """GIVEN text; WHEN generating embedding; THEN returns non-empty list."""
        analyzer = self.VEA()
        emb = analyzer.generate_text_embedding("Hello world", "doc1")
        assert isinstance(emb, (list,))
        assert len(emb) > 0

    def test_embed_document_stores_result(self):
        """GIVEN an article dict; WHEN embed_document; THEN stored in analyzer.embeddings."""
        from datetime import datetime
        analyzer = self.VEA()
        article = {
            "article_id": "art001",
            "title": "Markets rally",
            "content": "Stocks up 3%",
            "source": "reuters",
            "url": "https://example.com/art001",
            "published_date": datetime.now().isoformat(),
        }
        emb = analyzer.embed_document(article)
        assert emb.doc_id == "art001"
        assert "art001" in analyzer.embeddings

    def test_correlate_with_market(self):
        """GIVEN embedded doc and stock data; WHEN correlate; THEN correlation added."""
        from datetime import datetime
        analyzer = self.VEA()
        article = {
            "article_id": "art002",
            "title": "Tech stocks surge",
            "content": "AAPL up",
            "source": "bloomberg",
            "url": "https://example.com/art002",
            "published_date": datetime.now().isoformat(),
        }
        doc_emb = analyzer.embed_document(article)
        stock = {
            "symbol": "AAPL",
            "price_before": 150.0,
            "price_after": 154.5,
            "volume_before": 5_000_000,
            "volume_after": 7_500_000,
        }
        corr = analyzer.correlate_with_market(doc_emb, stock)
        assert corr.symbol == "AAPL"
        assert isinstance(corr.price_change, float)
        assert len(analyzer.correlations) == 1

    def test_cluster_embeddings_returns_dict(self):
        """GIVEN multiple embeddings; WHEN cluster; THEN returns dict of clusters."""
        from datetime import datetime
        analyzer = self.VEA()
        for i in range(5):
            article = {
                "article_id": f"doc{i}",
                "title": f"Article {i}",
                "content": f"Content {i}",
                "source": "ap",
                "url": f"https://example.com/{i}",
                "published_date": datetime.now().isoformat(),
            }
            analyzer.embed_document(article)
        clusters = analyzer.cluster_embeddings(n_clusters=3)
        assert isinstance(clusters, dict)

    def test_to_dict_serialisable(self):
        """GIVEN a MarketEmbeddingCorrelation; WHEN to_dict; THEN JSON-serialisable."""
        from datetime import datetime
        analyzer = self.VEA()
        article = {
            "article_id": "art003",
            "title": "Oil prices drop",
            "content": "Crude down",
            "source": "ap",
            "url": "https://example.com/art003",
            "published_date": datetime.now().isoformat(),
        }
        doc_emb = analyzer.embed_document(article)
        stock = {"symbol": "XOM", "price_before": 80.0, "price_after": 78.0}
        corr = analyzer.correlate_with_market(doc_emb, stock)
        d = corr.to_dict()
        json.dumps(d)  # Should not raise


class TestEmbeddingCorrelationMCPTools:
    """Tests for the MCP tool wrapper (thin module)."""

    def test_analyze_returns_json(self):
        """GIVEN valid JSON inputs; WHEN analyzing; THEN returns valid JSON string."""
        from datetime import datetime
        from ipfs_datasets_py.mcp_server.tools.finance_data_tools.embedding_correlation import (
            analyze_embedding_market_correlation,
        )
        articles = json.dumps([
            {
                "article_id": "a1",
                "title": "Market news",
                "content": "Stocks up",
                "source": "ap",
                "url": "http://example.com",
                "published_date": datetime.now().isoformat(),
            }
        ])
        stocks = json.dumps([{"symbol": "AAPL", "price_before": 100, "price_after": 102}])
        result_str = analyze_embedding_market_correlation(articles, stocks)
        result = json.loads(result_str)
        assert result["success"] is True

    def test_find_patterns_returns_json(self):
        """GIVEN valid JSON; WHEN finding patterns; THEN placeholder JSON returned."""
        from ipfs_datasets_py.mcp_server.tools.finance_data_tools.embedding_correlation import (
            find_predictive_embedding_patterns,
        )
        result_str = find_predictive_embedding_patterns("{}", 0.6, 30)
        result = json.loads(result_str)
        assert result["success"] is True

    def test_backward_compat_reexport(self):
        """GIVEN old import path; THEN engine types still importable."""
        from ipfs_datasets_py.mcp_server.tools.finance_data_tools.embedding_correlation import (
            DocumentEmbedding, MarketEmbeddingCorrelation, VectorEmbeddingAnalyzer,
        )
        assert DocumentEmbedding is not None
        assert VectorEmbeddingAnalyzer is not None


# ── BiomoleculeEngine ──────────────────────────────────────────────────────

class TestBiomoleculeEngineBasic:
    """Basic tests for BiomoleculeDiscoveryEngine."""

    def setup_method(self):
        from ipfs_datasets_py.mcp_server.tools.medical_research_scrapers.biomolecule_engine import (
            BiomoleculeDiscoveryEngine, BiomoleculeType, InteractionType,
        )
        self.Engine = BiomoleculeDiscoveryEngine
        self.BioType = BiomoleculeType
        self.IntType = InteractionType

    def test_init(self):
        """GIVEN no args; WHEN init; THEN engine has expected attributes."""
        engine = self.Engine()
        assert engine.use_rag is True
        assert isinstance(engine.discovered_biomolecules, dict)

    def test_discover_protein_binders_returns_list(self):
        """GIVEN target protein; WHEN discovering binders (no scrapers); THEN returns list."""
        engine = self.Engine()
        candidates = engine.discover_protein_binders("SARS-CoV-2 spike", max_results=5)
        assert isinstance(candidates, list)

    def test_discover_enzyme_inhibitors_returns_list(self):
        """GIVEN target enzyme; WHEN discovering inhibitors; THEN returns list."""
        engine = self.Engine()
        candidates = engine.discover_enzyme_inhibitors("ACE2", max_results=5)
        assert isinstance(candidates, list)

    def test_mock_binders_structure(self):
        """GIVEN mock binders; WHEN generated; THEN each has name and confidence_score."""
        engine = self.Engine()
        binders = engine._generate_mock_binders("IL-6", 3)
        assert len(binders) == 3
        for b in binders:
            assert hasattr(b, "name")
            assert 0.0 <= b.confidence_score <= 1.0

    def test_classify_biomolecule_antibody(self):
        """GIVEN antibody context; WHEN classifying; THEN returns ANTIBODY type."""
        from ipfs_datasets_py.mcp_server.tools.medical_research_scrapers.biomolecule_engine import BiomoleculeType
        engine = self.Engine()
        result = engine._classify_biomolecule("PD-L1mAb", "antibody therapy anti-cancer")
        assert result == BiomoleculeType.ANTIBODY


class TestDiscoverBiomoleculesWrapper:
    """Tests for the thin MCP wrapper function."""

    def test_binders_discovery(self):
        """GIVEN binders request; WHEN discovering; THEN returns list of dicts."""
        from ipfs_datasets_py.mcp_server.tools.medical_research_scrapers.biomolecule_discovery import (
            discover_biomolecules_for_target,
        )
        results = discover_biomolecules_for_target("HER2", discovery_type="binders", max_results=3)
        assert isinstance(results, list)

    def test_invalid_discovery_type_raises(self):
        """GIVEN invalid discovery_type; WHEN discovering; THEN ValueError raised."""
        from ipfs_datasets_py.mcp_server.tools.medical_research_scrapers.biomolecule_discovery import (
            discover_biomolecules_for_target,
        )
        with pytest.raises(ValueError, match="Unknown discovery_type"):
            discover_biomolecules_for_target("target", discovery_type="invalid")

    def test_backward_compat_reexport(self):
        """GIVEN import from wrapper; THEN engine types still available."""
        from ipfs_datasets_py.mcp_server.tools.medical_research_scrapers.biomolecule_discovery import (
            BiomoleculeDiscoveryEngine, BiomoleculeType, InteractionType,
        )
        assert BiomoleculeDiscoveryEngine is not None
        assert BiomoleculeType is not None


# ── BackgroundTaskEngine ───────────────────────────────────────────────────

class TestMockBackgroundTask:
    """Tests for the MockBackgroundTask dataclass."""

    def setup_method(self):
        from ipfs_datasets_py.mcp_server.tools.background_task_tools.background_task_engine import (
            MockBackgroundTask, TaskStatus,
        )
        self.Task = MockBackgroundTask
        self.Status = TaskStatus

    def test_initial_state(self):
        """GIVEN new task; THEN status is PENDING and progress 0."""
        task = self.Task("task-001", "create_embeddings")
        assert task.status == self.Status.PENDING
        assert task.progress == 0.0

    def test_complete(self):
        """GIVEN running task; WHEN complete called; THEN status COMPLETED."""
        task = self.Task("task-002", "data_processing")
        task.complete({"items": 100})
        assert task.status == self.Status.COMPLETED
        assert task.result == {"items": 100}

    def test_fail(self):
        """GIVEN running task; WHEN fail called; THEN status FAILED."""
        task = self.Task("task-003", "cleanup")
        task.fail("disk full")
        assert task.status == self.Status.FAILED
        assert "disk full" in task.error

    def test_cancel(self):
        """GIVEN pending task; WHEN cancel; THEN status CANCELLED."""
        task = self.Task("task-004", "backup")
        task.cancel()
        assert task.status == self.Status.CANCELLED

    def test_to_dict_json_serialisable(self):
        """GIVEN task; WHEN to_dict; THEN result is JSON-serialisable."""
        task = self.Task("task-005", "general", metadata={"key": "val"})
        d = task.to_dict()
        json.dumps(d)  # Should not raise
        assert d["task_id"] == "task-005"


class TestMockTaskManager:
    """Tests for the MockTaskManager async methods."""

    def setup_method(self):
        from ipfs_datasets_py.mcp_server.tools.background_task_tools.background_task_engine import (
            MockTaskManager, TaskStatus, TaskType,
        )
        self.Manager = MockTaskManager
        self.Status = TaskStatus
        self.TaskType = TaskType

    def test_init(self):
        """GIVEN new manager; THEN has empty tasks dict."""
        mgr = self.Manager()
        assert isinstance(mgr.tasks, dict)
        assert len(mgr.tasks) == 0

    def test_create_task(self):
        """GIVEN manager; WHEN creating task; THEN task_id returned and stored."""
        mgr = self.Manager()
        task_id = asyncio.run(
            mgr.create_task("create_embeddings")
        )
        assert isinstance(task_id, str)
        assert task_id in mgr.tasks

    def test_get_task(self):
        """GIVEN created task; WHEN get_task; THEN returns task object."""
        mgr = self.Manager()
        task_id = asyncio.run(
            mgr.create_task("data_processing")
        )
        task = asyncio.run(mgr.get_task(task_id))
        assert task is not None
        assert task.task_id == task_id

    def test_cancel_task(self):
        """GIVEN pending task; WHEN cancel; THEN returns True."""
        mgr = self.Manager()
        mgr.max_concurrent_tasks = 0  # Keep tasks pending
        task_id = asyncio.run(
            mgr.create_task("backup")
        )
        result = asyncio.run(mgr.cancel_task(task_id))
        assert result is True

    def test_get_stats(self):
        """GIVEN manager with tasks; WHEN get_stats; THEN returns dict with expected keys."""
        mgr = self.Manager()
        asyncio.run(mgr.create_task("general"))
        stats = asyncio.run(mgr.get_stats())
        assert "total_tasks" in stats
        assert stats["total_tasks"] >= 1

    def test_backward_compat_import_from_engine(self):
        """GIVEN import from background_task_engine; THEN all types available."""
        from ipfs_datasets_py.mcp_server.tools.background_task_tools.background_task_engine import (
            MockBackgroundTask, MockTaskManager, TaskStatus, TaskType,
        )
        assert MockBackgroundTask is not None
        assert MockTaskManager is not None
        assert TaskStatus is not None
        assert TaskType is not None


# ── Phase 7: Lazy Loading ─────────────────────────────────────────────────

class TestHierarchicalToolManagerLazyLoading:
    """Tests for the Phase-7 lazy-loading feature."""

    def setup_method(self):
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import (
            HierarchicalToolManager, ToolCategory,
        )
        self.HTM = HierarchicalToolManager
        self.TC = ToolCategory

    def test_lazy_register_does_not_call_loader(self):
        """GIVEN registered lazy category; THEN loader NOT called at registration."""
        mgr = self.HTM()
        calls = []
        mgr.lazy_register_category("lazy_cat", lambda: calls.append(1) or self.TC("lazy_cat", Path("/tmp")))
        assert len(calls) == 0

    def test_get_category_triggers_lazy_load(self):
        """GIVEN lazy category; WHEN get_category; THEN loader IS called."""
        mgr = self.HTM()
        calls = []
        def loader():
            calls.append(1)
            return self.TC("on_demand", Path("/tmp"), "On demand tools")
        mgr.lazy_register_category("on_demand", loader)
        cat = mgr.get_category("on_demand")
        assert cat is not None
        assert len(calls) == 1

    def test_get_category_called_twice_loads_once(self):
        """GIVEN lazy category; WHEN get_category called twice; THEN loader called once."""
        mgr = self.HTM()
        calls = []
        def loader():
            calls.append(1)
            return self.TC("once", Path("/tmp"), "loaded once")
        mgr.lazy_register_category("once", loader)
        mgr.get_category("once")
        mgr.get_category("once")
        assert len(calls) == 1

    def test_get_category_unknown_returns_none(self):
        """GIVEN non-existent category; WHEN get_category; THEN returns None."""
        mgr = self.HTM()
        result = mgr.get_category("does_not_exist_xyz")
        assert result is None

    def test_lazy_category_appears_in_metadata(self):
        """GIVEN lazy category; WHEN checking _category_metadata; THEN name present."""
        mgr = self.HTM()
        mgr.lazy_register_category("meta_check", lambda: self.TC("meta_check", Path("/tmp")))
        assert "meta_check" in mgr._category_metadata

    def test_list_categories_includes_lazy(self):
        """GIVEN lazy category; WHEN list_categories; THEN it appears in listing."""
        mgr = self.HTM()
        # Prevent filesystem discovery for isolation
        mgr._discovered_categories = True
        mgr.lazy_register_category("my_lazy", lambda: self.TC("my_lazy", Path("/tmp"), "lazy desc"))
        categories = asyncio.run(mgr.list_categories())
        names = [c["name"] for c in categories]
        assert "my_lazy" in names
