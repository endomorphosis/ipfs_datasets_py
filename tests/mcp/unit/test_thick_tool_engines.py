"""
Tests for thick tool engines extracted during refactoring.

Tests cover:
- TDFOLPerformanceEngine (tdfol_performance_engine.py)
- DataIngestionEngine (data_ingestion_engine.py)
- GeospatialAnalysisEngine (geospatial_analysis_engine.py)
- MockVectorStoreService / _AwaitableDict (vector_store_engine.py)
- Session helpers / MockSessionManager (session_engine.py)
- Storage types / MockStorageManager (storage_engine.py)
"""
import importlib.util
import os
import sys
from pathlib import Path

import anyio
import pytest

# Root of the installed package
_PKG_ROOT = Path(__file__).parent.parent.parent.parent / "ipfs_datasets_py"


def _load_module(relative_path: str, module_name: str):
    """Load a module by file path, bypassing package __init__.py imports."""
    path = _PKG_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Load engine modules directly (avoids broken __init__.py in sub-packages)
# ---------------------------------------------------------------------------
_tdfol_eng = _load_module(
    "mcp_server/tools/dashboard_tools/tdfol_performance_engine.py",
    "_tdfol_eng",
)
_di_eng = _load_module(
    "mcp_server/tools/investigation_tools/data_ingestion_engine.py",
    "_di_eng",
)
_geo_eng = _load_module(
    "mcp_server/tools/investigation_tools/geospatial_analysis_engine.py",
    "_geo_eng",
)
_vs_eng = _load_module(
    "mcp_server/tools/vector_store_tools/vector_store_engine.py",
    "_vs_eng",
)
_sess_eng = _load_module(
    "mcp_server/tools/session_tools/session_engine.py",
    "_sess_eng",
)
_stor_eng = _load_module(
    "mcp_server/tools/storage_tools/storage_engine.py",
    "_stor_eng",
)

TDFOLPerformanceEngine = _tdfol_eng.TDFOLPerformanceEngine
TDFOL_AVAILABLE = _tdfol_eng.TDFOL_AVAILABLE

DataIngestionEngine = _di_eng.DataIngestionEngine

GeospatialAnalysisEngine = _geo_eng.GeospatialAnalysisEngine
KNOWN_COORDINATES = _geo_eng.KNOWN_COORDINATES

MockVectorStoreService = _vs_eng.MockVectorStoreService
_AwaitableDict = _vs_eng._AwaitableDict

validate_session_id = _sess_eng.validate_session_id
validate_user_id = _sess_eng.validate_user_id
validate_session_type = _sess_eng.validate_session_type
MockSessionManager = _sess_eng.MockSessionManager

MockStorageManager = _stor_eng.MockStorageManager
StorageType = _stor_eng.StorageType
CompressionType = _stor_eng.CompressionType
Collection = _stor_eng.Collection
StorageItem = _stor_eng.StorageItem


# ---------------------------------------------------------------------------
# 1. TDFOLPerformanceEngine
# ---------------------------------------------------------------------------


class TestTDFOLPerformanceEngine:
    def setup_method(self):
        self.engine = TDFOLPerformanceEngine()

    def test_unavailable_fallback_get_metrics(self):
        """When TDFOL is unavailable, get_metrics returns an error dict."""
        if TDFOL_AVAILABLE:
            pytest.skip("TDFOL is available; skipping unavailability test")
        result = self.engine.get_metrics()
        assert "error" in result
        assert result["error"] == "TDFOL not available"

    def test_get_metrics_returns_dict(self):
        """get_metrics always returns a dict."""
        result = self.engine.get_metrics()
        assert isinstance(result, dict)

    def test_profile_operation_unavailable(self):
        """profile_operation returns error dict when TDFOL unavailable."""
        if TDFOL_AVAILABLE:
            pytest.skip("TDFOL is available")
        result = self.engine.profile_operation("P(x) -> Q(x)")
        assert "error" in result

    def test_compare_strategies_unavailable(self):
        """compare_strategies returns error when TDFOL unavailable."""
        if TDFOL_AVAILABLE:
            pytest.skip("TDFOL is available")
        result = self.engine.compare_strategies("P(x) -> Q(x)")
        assert "error" in result

    def test_reset_metrics_unavailable(self):
        """reset_metrics returns error when TDFOL unavailable."""
        if TDFOL_AVAILABLE:
            pytest.skip("TDFOL is available")
        result = self.engine.reset_metrics()
        assert "error" in result


# ---------------------------------------------------------------------------
# 2. DataIngestionEngine
# ---------------------------------------------------------------------------


class TestDataIngestionEngine:
    def setup_method(self):
        self.engine = DataIngestionEngine()

    def test_ingest_article_basic(self):
        """ingest_article returns a completed result with required keys."""
        result = self.engine.ingest_article("https://example.com/article")
        assert result["status"] == "completed"
        assert "ingestion_id" in result
        assert result["url"] == "https://example.com/article"

    def test_ingest_article_with_metadata(self):
        """ingest_article passes metadata through correctly."""
        result = self.engine.ingest_article(
            "https://example.com/article2",
            metadata={"author": "Test Author"},
        )
        assert result["metadata"].get("author") == "Test Author"

    def test_ingest_website(self):
        """ingest_website returns crawl statistics."""
        result = self.engine.ingest_website("https://example.com", max_pages=5, max_depth=2)
        assert result["status"] == "completed"
        assert "crawl_statistics" in result
        assert result["crawl_statistics"]["total_pages_crawled"] > 0

    def test_ingest_document_collection(self):
        """ingest_document_collection processes supported file types."""
        paths = ["/tmp/test_doc.pdf", "/tmp/test_doc.txt"]
        result = self.engine.ingest_document_collection(paths, collection_name="test_col")
        assert result["status"] == "completed"
        assert result["collection_name"] == "test_col"
        assert result["collection_statistics"]["total_documents"] == 2

    def test_build_sitemap_helper(self):
        """_build_sitemap constructs correct structure."""
        pages = [
            {"url": "https://example.com/", "depth": 0, "title": "Home",
             "status": "processed", "content_length": 1000},
            {"url": "https://example.com/about", "depth": 1, "title": "About",
             "status": "processed", "content_length": 500},
        ]
        sitemap = self.engine._build_sitemap(pages, max_depth=2)
        assert "root" in sitemap
        assert sitemap["root"]["url"] == "https://example.com/"
        assert "depth_1" in sitemap["root"]["children"]


# ---------------------------------------------------------------------------
# 3. GeospatialAnalysisEngine
# ---------------------------------------------------------------------------


class TestGeospatialAnalysisEngine:
    def setup_method(self):
        self.engine = GeospatialAnalysisEngine()

    def test_extract_entities_returns_dict(self):
        """extract_geographic_entities handles empty corpus gracefully."""
        corpus = {"documents": []}
        result = self.engine.extract_geographic_entities(corpus)
        assert "total_entities" in result
        assert result["total_entities"] == 0

    def test_extract_entities_with_content(self):
        """extract_geographic_entities finds known location keywords."""
        corpus = {"documents": [{"id": "d1", "content": "The meeting was in london and paris."}]}
        result = self.engine.extract_geographic_entities(corpus, confidence_threshold=0.0)
        entity_names = [e["entity"].lower() for e in result["entities"]]
        assert any(loc in entity_names for loc in ["london", "paris"])

    def test_map_events_returns_dict(self):
        """map_spatiotemporal_events returns a dict with events key."""
        entities: list = []
        result = self.engine.map_spatiotemporal_events(entities)
        assert "total_events" in result
        assert result["total_events"] == 0

    def test_query_geographic_context(self):
        """query_geographic_context returns results with correct shape."""
        entities = [
            {"entity": "London", "entity_type": "LOCATION",
             "coordinates": (51.5074, -0.1278), "confidence": 0.9,
             "context_snippet": "Meeting in London"},
        ]
        result = self.engine.query_geographic_context("london meeting", entities)
        assert "total_results" in result
        assert result["total_results"] >= 1

    def test_geocode_location(self):
        """_geocode_location returns known coordinates for major cities."""
        coords = self.engine._geocode_location("london")
        assert coords is not None
        lat, lng = coords
        assert 50 < lat < 53
        assert -2 < lng < 1

    def test_calculate_distance(self):
        """_calculate_distance computes reasonable haversine distance."""
        # London to Paris: ~340 km
        dist = self.engine._calculate_distance(51.5074, -0.1278, 48.8566, 2.3522)
        assert 300 < dist < 400


# ---------------------------------------------------------------------------
# 4. VectorStoreEngine
# ---------------------------------------------------------------------------


class TestVectorStoreEngine:
    def setup_method(self):
        self.service = MockVectorStoreService()

    def test_create_index(self):
        """create_index stores index with correct config."""
        async def _run():
            return await self.service.create_index("test_idx", {"dimension": 128})
        result = anyio.run(_run)
        assert result["status"] == "created"
        assert "test_idx" in self.service.indexes

    def test_add_and_search_vectors(self):
        """add_vectors and search_vectors work end-to-end."""
        async def _run():
            await self.service.create_index("col1", {"dimension": 3})
            await self.service.add_vectors("col1", [
                {"id": "v1", "vector": [0.1, 0.2, 0.3], "metadata": {"label": "a"}},
                {"id": "v2", "vector": [0.4, 0.5, 0.6], "metadata": {"label": "b"}},
            ])
            return await self.service.search_vectors("col1", [0.1, 0.2, 0.3], top_k=2)
        result = anyio.run(_run)
        assert len(result["results"]) == 2
        assert result["results"][0]["id"] == "v1"

    def test_delete_index(self):
        """delete_index removes the index from the service."""
        async def _run():
            await self.service.create_index("del_idx", {})
            return await self.service.delete_index("del_idx")
        result = anyio.run(_run)
        assert result["status"] == "deleted"
        assert "del_idx" not in self.service.indexes

    def test_awaitable_dict(self):
        """_AwaitableDict can be awaited to return itself."""
        async def _run():
            d = _AwaitableDict({"key": "value"})
            return await d
        result = anyio.run(_run)
        assert result["key"] == "value"


# ---------------------------------------------------------------------------
# 5. SessionEngine
# ---------------------------------------------------------------------------


class TestSessionEngine:
    def test_validate_functions(self):
        """Validation helpers return correct booleans."""
        assert validate_session_id("123e4567-e89b-12d3-a456-426614174000") is True
        assert validate_session_id("not-a-uuid") is False
        assert validate_session_id("") is False

        assert validate_user_id("alice") is True
        assert validate_user_id("") is False
        assert validate_user_id("x" * 101) is False

        assert validate_session_type("interactive") is True
        assert validate_session_type("batch") is True
        assert validate_session_type("invalid_type") is False

    def test_mock_session_manager_create_and_get(self):
        """MockSessionManager can create and retrieve sessions."""
        manager = MockSessionManager()

        async def _run():
            session = await manager.create_session(
                session_name="test-session",
                user_id="user1",
                session_type="interactive",
            )
            fetched = await manager.get_session(session["session_id"])
            return session, fetched

        session, fetched = anyio.run(_run)
        assert session["status"] == "active"
        assert fetched["session_id"] == session["session_id"]
        assert fetched["user_id"] == "user1"

    def test_mock_session_manager_delete(self):
        """MockSessionManager delete removes session."""
        manager = MockSessionManager()

        async def _run():
            session = await manager.create_session(session_name="to-delete")
            sid = session["session_id"]
            deleted = await manager.delete_session(sid)
            fetched = await manager.get_session(sid)
            return deleted, fetched

        deleted, fetched = anyio.run(_run)
        assert deleted["status"] == "terminated"
        assert fetched is None


# ---------------------------------------------------------------------------
# 6. StorageEngine
# ---------------------------------------------------------------------------


class TestStorageEngine:
    def test_storage_type_enum(self):
        """StorageType enum has expected values."""
        assert StorageType.MEMORY.value == "memory"
        assert StorageType.IPFS.value == "ipfs"
        assert StorageType.LOCAL.value == "local"

    def test_collection_dataclass(self):
        """Collection dataclass instantiates correctly."""
        from datetime import datetime
        c = Collection(
            name="test", description="desc", items=[], metadata={},
            created_at=datetime.now(), updated_at=datetime.now()
        )
        assert c.name == "test"
        assert c.items == []

    def test_mock_storage_manager_store_and_retrieve(self):
        """MockStorageManager can store and retrieve items."""
        manager = MockStorageManager()
        item = manager.store_item(
            content="Hello, world!",
            storage_type=StorageType.MEMORY,
            compression=CompressionType.NONE,
            tags=["test"],
        )
        assert item.id is not None
        retrieved = manager.retrieve_item(item.id)
        assert retrieved is not None
        assert retrieved["id"] == item.id
        assert retrieved["tags"] == ["test"]
        assert retrieved["storage_type"] == "memory"



# ---------------------------------------------------------------------------
# 7. CodebaseSearchEngine
# ---------------------------------------------------------------------------

_cs_eng = _load_module(
    "mcp_server/tools/development_tools/codebase_search_engine.py",
    "_cs_eng",
)
CodebaseSearchEngine = _cs_eng.CodebaseSearchEngine
CodebaseSearchResult = _cs_eng.CodebaseSearchResult
SearchMatch = _cs_eng.SearchMatch


class TestCodebaseSearchEngine:
    def setup_method(self):
        self.engine = CodebaseSearchEngine()

    def test_search_nonexistent_path(self):
        """Searching a non-existent path raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            self.engine.search_codebase("anything", path="/no/such/path/xyz123")

    def test_search_returns_result(self, tmp_path):
        """Searching a directory with a match returns CodebaseSearchResult."""
        (tmp_path / "sample.py").write_text("def hello_world():\n    pass\n")
        result = self.engine.search_codebase("hello_world", path=str(tmp_path))
        assert isinstance(result, CodebaseSearchResult)
        assert result.summary.total_matches >= 1

    def test_search_no_match(self, tmp_path):
        """Searching with no match returns zero matches but valid summary."""
        (tmp_path / "empty.py").write_text("# nothing here\n")
        result = self.engine.search_codebase("xyz_does_not_exist", path=str(tmp_path))
        assert result.summary.total_matches == 0

    def test_compile_pattern_invalid_regex(self):
        """Invalid regex raises ValueError."""
        with pytest.raises(ValueError):
            self.engine._compile_search_pattern("[invalid", False, False, True)

    def test_format_results_json(self, tmp_path):
        """format_results with json returns valid JSON string."""
        import json
        (tmp_path / "code.py").write_text("x = 42\n")
        result = self.engine.search_codebase("42", path=str(tmp_path))
        output = self.engine.format_results(result, format_type="json")
        parsed = json.loads(output)
        assert "summary" in parsed

    def test_dataset_patterns_attribute(self):
        """Engine has dataset_patterns dict with expected keys."""
        assert "ipfs_hash" in self.engine.dataset_patterns
        assert "ml_imports" in self.engine.dataset_patterns

    def test_backward_compat_import(self):
        """codebase_search_engine.py exports expected names."""
        assert hasattr(_cs_eng, "CodebaseSearchEngine")
        assert hasattr(_cs_eng, "CodebaseSearchResult")
        assert hasattr(_cs_eng, "SearchMatch")
        assert hasattr(_cs_eng, "FileSearchResult")
        assert hasattr(_cs_eng, "SearchSummary")


# ---------------------------------------------------------------------------
# 8. VectorStoreManagementEngine
# ---------------------------------------------------------------------------

_vsm_eng = _load_module(
    "mcp_server/tools/vector_tools/vector_store_management_engine.py",
    "_vsm_eng",
)
VectorStoreManager = _vsm_eng.VectorStoreManager


class TestVectorStoreManagementEngine:
    def setup_method(self, tmp_path=None):
        import tempfile
        self.tmp_dir = tempfile.mkdtemp()
        self.manager = VectorStoreManager(indexes_dir=self.tmp_dir)

    def test_list_indexes_empty(self):
        """list_indexes on empty dir returns success with empty faiss list."""
        result = self.manager.list_indexes("faiss")
        assert result["status"] == "success"
        assert result["indexes"]["faiss"] == []

    def test_delete_nonexistent_faiss(self):
        """Deleting a non-existent FAISS index returns error."""
        result = self.manager.delete_index("no_such_index", backend="faiss")
        assert result["status"] == "error"
        assert "not found" in result["error"]

    def test_delete_unsupported_backend(self):
        """Deleting with unsupported backend returns error."""
        result = self.manager.delete_index("idx", backend="unknown")
        assert result["status"] == "error"
        assert "Unsupported" in result["error"]

    def test_search_unavailable_backends(self):
        """Search against qdrant/elasticsearch returns 'not implemented' error."""

        async def _run():
            return await self.manager.search_index("idx", "query", backend="qdrant")

        result = anyio.run(_run)
        assert result["status"] == "error"
        assert "not implemented" in result["error"]

    def test_backward_compat_import(self):
        """vector_store_management_engine.py exports expected names."""
        assert hasattr(_vsm_eng, "VectorStoreManager")
        assert hasattr(_vsm_eng, "FAISS_AVAILABLE")
        assert hasattr(_vsm_eng, "QDRANT_AVAILABLE")
        assert hasattr(_vsm_eng, "ELASTICSEARCH_AVAILABLE")
