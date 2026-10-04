#!/usr/bin/env python3

import importlib.util
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load_unified_api_tools_module():
    module_path = (
        Path(__file__).resolve().parents[3]
        / "ipfs_datasets_py"
        / "mcp_server"
        / "tools"
        / "web_archive_tools"
        / "unified_api_tools.py"
    )
    spec = importlib.util.spec_from_file_location("web_archive_unified_api_tools", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


unified_api_tools = _load_unified_api_tools_module()


class FakeUnifiedAPI:
    def __init__(self):
        self.last_search_request = None
        self.last_fetch_request = None

    def search(self, request):
        self.last_search_request = request
        return SimpleNamespace(
            success=True,
            to_dict=lambda: {
                "query": request.query,
                "domain": request.domain,
                "success": True,
                "results": [],
            },
        )

    def fetch(self, request):
        self.last_fetch_request = request
        return SimpleNamespace(
            success=True,
            to_dict=lambda: {
                "url": request.url,
                "domain": request.domain,
                "success": True,
            },
        )

    def search_and_fetch(self, request, max_documents=5):
        self.last_search_request = request
        return {
            "status": "success",
            "search": {"query": request.query},
            "documents": [],
            "documents_count": 0,
            "max_documents": max_documents,
        }

    def health(self):
        return {"orchestrator": {}, "metrics_5m": {}}

    def agentic_discover_and_fetch(self, **kwargs):
        return {
            "status": "success",
            "visited_count": 1,
            "results": [],
            "kwargs": kwargs,
        }


def test_unified_mcp_functions_are_async() -> None:
    assert inspect.iscoroutinefunction(unified_api_tools.unified_search)
    assert inspect.iscoroutinefunction(unified_api_tools.unified_fetch)
    assert inspect.iscoroutinefunction(unified_api_tools.unified_search_and_fetch)
    assert inspect.iscoroutinefunction(unified_api_tools.unified_health)


@pytest.mark.anyio
async def test_unified_search_wrapper(monkeypatch) -> None:
    fake_api = FakeUnifiedAPI()
    monkeypatch.setattr(unified_api_tools, "_get_api", lambda: fake_api)

    result = await unified_api_tools.unified_search(
        query="indiana code",
        max_results=5,
        mode="balanced",
        provider_allowlist=["brave"],
        domain="legal",
    )

    assert result["status"] == "success"
    assert result["data"]["query"] == "indiana code"
    assert result["data"]["domain"] == "legal"
    assert fake_api.last_search_request.domain == "legal"


@pytest.mark.anyio
async def test_unified_fetch_wrapper(monkeypatch) -> None:
    fake_api = FakeUnifiedAPI()
    monkeypatch.setattr(unified_api_tools, "_get_api", lambda: fake_api)

    result = await unified_api_tools.unified_fetch(
        url="https://example.com/law",
        mode="balanced",
        domain="medical",
    )

    assert result["status"] == "success"
    assert result["data"]["url"] == "https://example.com/law"
    assert result["data"]["domain"] == "medical"
    assert fake_api.last_fetch_request.domain == "medical"


@pytest.mark.anyio
async def test_unified_search_and_fetch_wrapper(monkeypatch) -> None:
    fake_api = FakeUnifiedAPI()
    monkeypatch.setattr(unified_api_tools, "_get_api", lambda: fake_api)

    result = await unified_api_tools.unified_search_and_fetch(
        query="indiana code",
        max_results=5,
        max_documents=2,
        mode="max_throughput",
        domain="finance",
    )

    assert result["status"] == "success"
    assert result["max_documents"] == 2
    assert fake_api.last_search_request.domain == "finance"


@pytest.mark.anyio
async def test_unified_health_wrapper(monkeypatch) -> None:
    monkeypatch.setattr(unified_api_tools, "_get_api", lambda: FakeUnifiedAPI())

    result = await unified_api_tools.unified_health()

    assert result["status"] == "success"
    assert "orchestrator" in result["data"]


@pytest.mark.anyio
async def test_unified_agentic_discover_wrapper(monkeypatch) -> None:
    monkeypatch.setattr(unified_api_tools, "_get_api", lambda: FakeUnifiedAPI())

    result = await unified_api_tools.unified_agentic_discover_and_fetch(
        seed_urls=["https://example.com"],
        target_terms=["statute"],
        max_hops=1,
        max_pages=3,
        mode="balanced",
    )

    assert result["status"] == "success"
    assert result["visited_count"] == 1
