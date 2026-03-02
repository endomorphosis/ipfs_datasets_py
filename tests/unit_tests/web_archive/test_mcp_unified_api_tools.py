#!/usr/bin/env python3

import inspect
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.mcp_server.tools.web_archive_tools import unified_api_tools


class FakeUnifiedAPI:
    def search(self, request):
        return SimpleNamespace(
            success=True,
            to_dict=lambda: {
                "query": request.query,
                "success": True,
                "results": [],
            },
        )

    def fetch(self, request):
        return SimpleNamespace(
            success=True,
            to_dict=lambda: {
                "url": request.url,
                "success": True,
            },
        )

    def search_and_fetch(self, request, max_documents=5):
        return {
            "status": "success",
            "search": {"query": request.query},
            "documents": [],
            "documents_count": 0,
            "max_documents": max_documents,
        }

    def health(self):
        return {"orchestrator": {}, "metrics_5m": {}}


def test_unified_mcp_functions_are_async() -> None:
    assert inspect.iscoroutinefunction(unified_api_tools.unified_search)
    assert inspect.iscoroutinefunction(unified_api_tools.unified_fetch)
    assert inspect.iscoroutinefunction(unified_api_tools.unified_search_and_fetch)
    assert inspect.iscoroutinefunction(unified_api_tools.unified_health)


@pytest.mark.anyio
async def test_unified_search_wrapper(monkeypatch) -> None:
    monkeypatch.setattr(unified_api_tools, "_get_api", lambda: FakeUnifiedAPI())

    result = await unified_api_tools.unified_search(
        query="indiana code",
        max_results=5,
        mode="balanced",
        provider_allowlist=["brave"],
    )

    assert result["status"] == "success"
    assert result["data"]["query"] == "indiana code"


@pytest.mark.anyio
async def test_unified_fetch_wrapper(monkeypatch) -> None:
    monkeypatch.setattr(unified_api_tools, "_get_api", lambda: FakeUnifiedAPI())

    result = await unified_api_tools.unified_fetch(
        url="https://example.com/law",
        mode="balanced",
    )

    assert result["status"] == "success"
    assert result["data"]["url"] == "https://example.com/law"


@pytest.mark.anyio
async def test_unified_search_and_fetch_wrapper(monkeypatch) -> None:
    monkeypatch.setattr(unified_api_tools, "_get_api", lambda: FakeUnifiedAPI())

    result = await unified_api_tools.unified_search_and_fetch(
        query="indiana code",
        max_results=5,
        max_documents=2,
        mode="max_throughput",
    )

    assert result["status"] == "success"
    assert result["max_documents"] == 2


@pytest.mark.anyio
async def test_unified_health_wrapper(monkeypatch) -> None:
    monkeypatch.setattr(unified_api_tools, "_get_api", lambda: FakeUnifiedAPI())

    result = await unified_api_tools.unified_health()

    assert result["status"] == "success"
    assert "orchestrator" in result["data"]
