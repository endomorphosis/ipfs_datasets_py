#!/usr/bin/env python3

import time
from types import SimpleNamespace

from ipfs_datasets_py.processors.web_archiving.contracts import OperationMode, UnifiedSearchRequest
from ipfs_datasets_py.processors.web_archiving.unified_api import UnifiedWebArchivingAPI


class FakeOrchestratorSuccess:
    def search(self, query, max_results, offset, engines):
        assert query == "indiana code"
        assert max_results == 5
        assert offset == 0
        assert len(engines) == 1
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


class FakeScraper:
    def scrape_sync(self, url):
        return SimpleNamespace(
            success=True,
            title="Fetched Title",
            text="Fetched Text",
            html="<html></html>",
            metadata={"content_type": "text/html"},
            method_used=SimpleNamespace(value="beautifulsoup"),
            extraction_time=0.1,
            links=[{"url": "https://example.com/law-2", "text": "Law 2"}],
            errors=[],
        )


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
    now = time.time()

    # Seed provider performance so planner prefers duckduckgo over brave.
    api.metrics_registry.record_event(
        provider="duckduckgo",
        operation="search",
        success=True,
        latency_ms=100,
        items_processed=60,
        timestamp=now - 20,
    )
    api.metrics_registry.record_event(
        provider="brave",
        operation="search",
        success=True,
        latency_ms=100,
        items_processed=8,
        timestamp=now - 20,
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


def test_unified_api_fetch_success_with_injected_scraper() -> None:
    api = UnifiedWebArchivingAPI(orchestrator=FakeOrchestratorSuccess(), scraper=FakeScraper())

    response = api.fetch("https://example.com/law")

    assert response.success is True
    assert response.document is not None
    assert response.document.title == "Fetched Title"
    assert response.quality_score > 0
    assert response.document.metadata.get("source_type") in {"html", "pdf"}
    assert isinstance(response.document.metadata.get("entities"), list)
    assert isinstance(response.document.metadata.get("structured_fields"), dict)
    assert response.document.metadata.get("structured_fields_version")
    assert response.document.metadata.get("domain") == "general"
    assert response.metadata.get("requested_domain") == "general"


def test_unified_api_fetch_respects_domain_for_structured_schema() -> None:
    api = UnifiedWebArchivingAPI(orchestrator=FakeOrchestratorSuccess(), scraper=FakeScraper())

    response = api.fetch(
        "https://example.com/law",
        domain="legal",
    )

    assert response.success is True
    assert response.document is not None
    assert response.document.metadata.get("structured_fields", {}).get("schema") == "legal_v1"
    assert response.document.metadata.get("structured_fields_version") == "legal_v1"
    assert response.document.metadata.get("domain") == "legal"
    assert response.metadata.get("requested_domain") == "legal"


def test_unified_api_fetch_normalizes_domain_alias_and_migration_meta() -> None:
    api = UnifiedWebArchivingAPI(orchestrator=FakeOrchestratorSuccess(), scraper=FakeScraper())

    response = api.fetch(
        "https://example.com/law",
        domain="laws",
    )

    assert response.success is True
    assert response.document is not None
    assert response.document.metadata.get("domain") == "legal"
    assert response.document.metadata.get("structured_fields_version") == "legal_v1"
    assert response.document.metadata.get("structured_fields_contract") == "v1"
    assert response.document.metadata.get("requested_domain") == "legal"
    assert response.document.metadata.get("schema_migration_applied") in {True, False}
    assert response.metadata.get("requested_domain") == "legal"


def test_unified_api_search_and_fetch_returns_document_envelope() -> None:
    api = UnifiedWebArchivingAPI(orchestrator=FakeOrchestratorSuccess(), scraper=FakeScraper())

    result = api.search_and_fetch(
        UnifiedSearchRequest(
            query="indiana code",
            max_results=5,
            provider_allowlist=["brave", "duckduckgo"],
        ),
        max_documents=1,
    )

    assert result["status"] == "success"
    assert result["documents_count"] == 1


def test_unified_api_search_and_fetch_propagates_domain_to_fetch() -> None:
    api = UnifiedWebArchivingAPI(orchestrator=FakeOrchestratorSuccess(), scraper=FakeScraper())

    result = api.search_and_fetch(
        UnifiedSearchRequest(
            query="indiana code",
            max_results=5,
            provider_allowlist=["brave", "duckduckgo"],
            domain="legal",
        ),
        max_documents=1,
    )

    assert result["status"] == "success"
    assert result["documents_count"] == 1
    doc_meta = result["documents"][0]["document"]["metadata"]
    assert doc_meta["domain"] == "legal"
    assert doc_meta["structured_fields"]["schema"] == "legal_v1"


def test_unified_api_agentic_discover_and_fetch() -> None:
    api = UnifiedWebArchivingAPI(orchestrator=FakeOrchestratorSuccess(), scraper=FakeScraper())

    result = api.agentic_discover_and_fetch(
        seed_urls=["https://example.com/law"],
        target_terms=["law"],
        max_hops=1,
        max_pages=2,
    )

    assert result["status"] == "success"
    assert result["visited_count"] >= 1
    assert isinstance(result["results"], list)
