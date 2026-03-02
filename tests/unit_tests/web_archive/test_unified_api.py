#!/usr/bin/env python3

from types import SimpleNamespace

from ipfs_datasets_py.processors.web_archiving.contracts import OperationMode, UnifiedSearchRequest
from ipfs_datasets_py.processors.web_archiving.unified_api import UnifiedWebArchivingAPI


class FakeOrchestratorSuccess:
    def search(self, query, max_results, offset, engines):
        assert query == "indiana code"
        assert max_results == 5
        assert offset == 0
        assert engines == ["brave", "duckduckgo"]
        return SimpleNamespace(
            results=[
                SimpleNamespace(
                    title="Indiana Code",
                    url="https://example.com/indiana",
                    snippet="law text",
                    engine="brave",
                    score=0.9,
                    metadata={"rank": 1},
                )
            ],
            took_ms=123.4,
            metadata={"engines_used": ["brave", "duckduckgo"]},
        )

    def get_stats(self):
        return {"engines": {"brave": {"requests": 1}}}


class FakeOrchestratorFailure:
    def search(self, query, max_results, offset, engines):
        raise RuntimeError("all providers failed")

    def get_stats(self):
        return {"engines": {}}


class FakeOrchestratorCapture:
    def __init__(self):
        self.last_engines = []

    def search(self, query, max_results, offset, engines):
        self.last_engines = list(engines)
        return SimpleNamespace(
            results=[],
            took_ms=20.0,
            metadata={"engines_used": list(engines)},
        )

    def get_stats(self):
        return {"engines": {}}


def test_unified_api_search_success_maps_results() -> None:
    api = UnifiedWebArchivingAPI(orchestrator=FakeOrchestratorSuccess())
    request = UnifiedSearchRequest(
        query="indiana code",
        mode=OperationMode.MAX_THROUGHPUT,
        max_results=5,
        provider_allowlist=["brave", "duckduckgo"],
    )

    response = api.search(request)

    assert response.success is True
    assert response.total_results == 1
    assert response.results[0].title == "Indiana Code"
    assert response.results[0].url == "https://example.com/indiana"
    assert response.trace is not None
    assert response.trace.provider_selected == "brave"
    assert response.trace.fallback_count == 0
    assert response.trace.providers_attempted == ["brave"]
    assert response.metadata["planned_provider_order"] == ["brave", "duckduckgo"]

    metrics = api.metrics_registry.snapshot("brave", "search", window_seconds=300)
    assert metrics["successes"] == 1.0
    assert metrics["items_processed"] == 1.0


def test_unified_api_search_failure_returns_error_contract() -> None:
    api = UnifiedWebArchivingAPI(orchestrator=FakeOrchestratorFailure())
    request = UnifiedSearchRequest(
        query="indiana code",
        max_results=5,
        provider_allowlist=["brave"],
    )

    response = api.search(request)

    assert response.success is False
    assert response.total_results == 0
    assert len(response.errors) == 1
    assert response.errors[0].code == "search_failed"
    assert "all providers failed" in response.errors[0].message
    assert response.trace is not None


def test_unified_api_string_request_input() -> None:
    api = UnifiedWebArchivingAPI(orchestrator=FakeOrchestratorSuccess())

    response = api.search(
        "indiana code",
        max_results=5,
        provider_allowlist=["brave", "duckduckgo"],
    )

    assert response.success is True
    assert response.query == "indiana code"


def test_unified_api_health_snapshot_contains_metrics() -> None:
    api = UnifiedWebArchivingAPI(orchestrator=FakeOrchestratorSuccess())
    api.search(
        UnifiedSearchRequest(
            query="indiana code",
            max_results=5,
            provider_allowlist=["brave", "duckduckgo"],
        )
    )

    health = api.health()

    assert "orchestrator" in health
    assert "metrics_5m" in health
    assert "brave:search" in health["metrics_5m"]


def test_unified_api_search_uses_throughput_ranked_provider_order() -> None:
    orchestrator = FakeOrchestratorCapture()
    api = UnifiedWebArchivingAPI(orchestrator=orchestrator)

    # Seed provider performance so planner prefers duckduckgo over brave.
    api.metrics_registry.record_event(
        provider="duckduckgo",
        operation="search",
        success=True,
        latency_ms=100,
        items_processed=60,
        timestamp=100.0,
    )
    api.metrics_registry.record_event(
        provider="brave",
        operation="search",
        success=True,
        latency_ms=100,
        items_processed=8,
        timestamp=100.0,
    )

    response = api.search(
        UnifiedSearchRequest(
            query="indiana code",
            mode=OperationMode.MAX_THROUGHPUT,
            provider_allowlist=["brave", "duckduckgo"],
        )
    )

    assert response.success is True
    assert orchestrator.last_engines[0] == "duckduckgo"
    assert response.metadata["planned_provider_order"][0] == "duckduckgo"
    assert response.trace is not None
    assert response.trace.providers_attempted == ["duckduckgo"]
