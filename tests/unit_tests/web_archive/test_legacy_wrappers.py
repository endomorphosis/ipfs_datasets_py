#!/usr/bin/env python3

import warnings
from types import SimpleNamespace

from ipfs_datasets_py.processors.web_archiving.compat import legacy_wrappers


class FakeUnifiedAPI:
    def search(self, request):
        return SimpleNamespace(
            success=True,
            to_dict=lambda: {
                "query": request.query,
                "max_results": request.max_results,
                "mode": request.mode.value,
            },
        )

    def fetch(self, request):
        return SimpleNamespace(
            success=True,
            to_dict=lambda: {
                "url": request.url,
                "mode": request.mode.value,
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


def test_legacy_search_web_routes_to_unified_api(monkeypatch) -> None:
    monkeypatch.setattr(legacy_wrappers, "_get_api", lambda: FakeUnifiedAPI())

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        result = legacy_wrappers.legacy_search_web(
            query="indiana code",
            max_results=7,
            mode="balanced",
            provider_allowlist=["brave"],
        )

    assert result["status"] == "success"
    assert result["data"]["query"] == "indiana code"
    assert result["data"]["max_results"] == 7
    assert any(issubclass(w.category, DeprecationWarning) for w in captured)


def test_legacy_fetch_url_routes_to_unified_api(monkeypatch) -> None:
    monkeypatch.setattr(legacy_wrappers, "_get_api", lambda: FakeUnifiedAPI())

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        result = legacy_wrappers.legacy_fetch_url(
            url="https://example.com/law",
            mode="balanced",
        )

    assert result["status"] == "success"
    assert result["data"]["url"] == "https://example.com/law"
    assert any(issubclass(w.category, DeprecationWarning) for w in captured)


def test_legacy_search_and_fetch_routes_to_unified_api(monkeypatch) -> None:
    monkeypatch.setattr(legacy_wrappers, "_get_api", lambda: FakeUnifiedAPI())

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        result = legacy_wrappers.legacy_search_and_fetch(
            query="indiana code",
            max_results=10,
            max_documents=2,
            mode="max_throughput",
            provider_allowlist=["brave", "duckduckgo"],
        )

    assert result["status"] == "success"
    assert result["max_documents"] == 2
    assert any(issubclass(w.category, DeprecationWarning) for w in captured)
