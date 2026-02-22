"""
Phase B2 unit tests — bespoke_tools category.

Tests: system_health, system_status, cache_stats, list_indices,
       create_vector_store, delete_index

bespoke_tools requires psutil, which may not be installed.
All tools are patched at module load time via sys.modules stubs.
All functions are async.
"""
from __future__ import annotations

import asyncio
import sys
import types
import unittest.mock as m
import pytest


# ---------------------------------------------------------------------------
# Ensure psutil stub is present before importing bespoke_tools
# ---------------------------------------------------------------------------

def _stub_psutil() -> None:
    """Insert a minimal psutil stub if the real module is absent."""
    if "psutil" not in sys.modules:
        mock = m.MagicMock()
        mock.cpu_percent.return_value = 42.0
        mock.virtual_memory.return_value = m.MagicMock(
            percent=55.0, total=int(8e9), available=int(3.6e9)
        )
        mock.disk_usage.return_value = m.MagicMock(
            percent=65.0, total=int(500e9), free=int(175e9)
        )
        mock.net_io_counters.return_value = m.MagicMock(
            bytes_sent=1024, bytes_recv=2048
        )
        mock.Process.return_value = m.MagicMock(memory_info=lambda: m.MagicMock(rss=int(50e6)))
        mock.pids.return_value = list(range(100))
        sys.modules["psutil"] = mock


_stub_psutil()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# system_health
# ---------------------------------------------------------------------------

class TestSystemHealth:
    """Tests for bespoke_tools.system_health.system_health()."""

    def setup_method(self) -> None:
        _stub_psutil()
        from ipfs_datasets_py.mcp_server.tools.bespoke_tools.system_health import system_health
        self.fn = system_health

    def test_returns_dict(self) -> None:
        result = _run(self.fn())
        assert isinstance(result, dict)

    def test_has_success_key(self) -> None:
        result = _run(self.fn())
        assert "success" in result

    def test_has_timestamp(self) -> None:
        result = _run(self.fn())
        assert "timestamp" in result


# ---------------------------------------------------------------------------
# system_status
# ---------------------------------------------------------------------------

class TestSystemStatus:
    """Tests for bespoke_tools.system_status.system_status()."""

    def setup_method(self) -> None:
        _stub_psutil()
        from ipfs_datasets_py.mcp_server.tools.bespoke_tools.system_status import system_status
        self.fn = system_status

    def test_returns_dict(self) -> None:
        result = _run(self.fn())
        assert isinstance(result, dict)

    def test_has_success_key(self) -> None:
        result = _run(self.fn())
        assert "success" in result

    def test_has_timestamp(self) -> None:
        result = _run(self.fn())
        assert "timestamp" in result


# ---------------------------------------------------------------------------
# cache_stats
# ---------------------------------------------------------------------------

class TestCacheStats:
    """Tests for bespoke_tools.cache_stats.cache_stats()."""

    def setup_method(self) -> None:
        _stub_psutil()
        from ipfs_datasets_py.mcp_server.tools.bespoke_tools.cache_stats import cache_stats
        self.fn = cache_stats

    def test_returns_dict(self) -> None:
        result = _run(self.fn())
        assert isinstance(result, dict)

    def test_has_success_key(self) -> None:
        result = _run(self.fn())
        assert "success" in result

    def test_namespace_param(self) -> None:
        result = _run(self.fn(namespace="test_ns"))
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# list_indices
# ---------------------------------------------------------------------------

class TestListIndices:
    """Tests for bespoke_tools.list_indices.list_indices()."""

    def setup_method(self) -> None:
        _stub_psutil()
        from ipfs_datasets_py.mcp_server.tools.bespoke_tools.list_indices import list_indices
        self.fn = list_indices

    def test_returns_dict(self) -> None:
        result = _run(self.fn())
        assert isinstance(result, dict)

    def test_has_indices_key(self) -> None:
        result = _run(self.fn())
        assert "indices" in result

    def test_store_type_filter(self) -> None:
        result = _run(self.fn(store_type="faiss"))
        assert isinstance(result, dict)

    def test_include_stats_param(self) -> None:
        result = _run(self.fn(include_stats=True))
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# create_vector_store
# ---------------------------------------------------------------------------

class TestCreateVectorStore:
    """Tests for bespoke_tools.create_vector_store.create_vector_store()."""

    def setup_method(self) -> None:
        _stub_psutil()
        from ipfs_datasets_py.mcp_server.tools.bespoke_tools.create_vector_store import create_vector_store
        self.fn = create_vector_store

    def test_returns_dict(self) -> None:
        result = _run(self.fn("my_store", "faiss"))
        assert isinstance(result, dict)

    def test_has_success_key(self) -> None:
        result = _run(self.fn("my_store", "faiss"))
        assert "success" in result

    def test_dimension_param(self) -> None:
        result = _run(self.fn("my_store", "faiss", dimension=512))
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# delete_index
# ---------------------------------------------------------------------------

class TestDeleteIndex:
    """Tests for bespoke_tools.delete_index.delete_index()."""

    def setup_method(self) -> None:
        _stub_psutil()
        from ipfs_datasets_py.mcp_server.tools.bespoke_tools.delete_index import delete_index
        self.fn = delete_index

    def test_returns_dict(self) -> None:
        result = _run(self.fn("test_index_id"))
        assert isinstance(result, dict)

    def test_has_index_id_in_response(self) -> None:
        result = _run(self.fn("test_index_id"))
        assert "index_id" in result

    def test_store_type_param(self) -> None:
        result = _run(self.fn("test_id", store_type="qdrant"))
        assert isinstance(result, dict)
