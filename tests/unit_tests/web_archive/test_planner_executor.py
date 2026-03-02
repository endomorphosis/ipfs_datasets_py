#!/usr/bin/env python3

from types import SimpleNamespace

from ipfs_datasets_py.processors.web_archiving.contracts import OperationMode, UnifiedSearchRequest
from ipfs_datasets_py.processors.web_archiving.metrics.registry import MetricsRegistry
from ipfs_datasets_py.processors.web_archiving.orchestration.executor import SearchExecutor
from ipfs_datasets_py.processors.web_archiving.orchestration.planner import SearchPlanner
from ipfs_datasets_py.processors.web_archiving.orchestration.scoring import ProviderScorer


class FakeOrchestrator:
    def __init__(self):
        self.calls = []

    def search(self, query, max_results, offset, engines):
        self.calls.append(list(engines))
        return SimpleNamespace(
            results=[],
            took_ms=10.0,
            metadata={"engines_used": list(engines)},
        )


def test_search_planner_orders_by_throughput_metrics() -> None:
    registry = MetricsRegistry(default_windows_seconds=(300,))
    registry.record_event(
        provider="duckduckgo",
        operation="search",
        success=True,
        latency_ms=100,
        items_processed=60,
        timestamp=100.0,
    )
    registry.record_event(
        provider="brave",
        operation="search",
        success=True,
        latency_ms=100,
        items_processed=10,
        timestamp=100.0,
    )

    planner = SearchPlanner(
        scorer=ProviderScorer(metrics_registry=registry),
        default_search_engines=["brave", "duckduckgo"],
    )

    plan = planner.plan(
        UnifiedSearchRequest(
            query="indiana code",
            mode=OperationMode.MAX_THROUGHPUT,
            provider_allowlist=["brave", "duckduckgo"],
        )
    )

    assert plan.providers_ordered[0] == "duckduckgo"
    assert plan.providers_ordered[1] == "brave"


def test_search_executor_uses_ranked_order() -> None:
    orchestrator = FakeOrchestrator()
    executor = SearchExecutor(orchestrator)

    registry = MetricsRegistry(default_windows_seconds=(300,))
    planner = SearchPlanner(
        scorer=ProviderScorer(metrics_registry=registry),
        default_search_engines=["brave", "duckduckgo"],
    )
    plan = planner.plan(
        UnifiedSearchRequest(
            query="indiana code",
            provider_allowlist=["brave", "duckduckgo"],
        )
    )

    result = executor.execute(plan)

    assert orchestrator.calls[0] == [plan.providers_ordered[0]]
    assert result.providers_attempted == [plan.providers_ordered[0]]
    assert result.providers_skipped == []
    assert result.provider_selected == plan.providers_ordered[0]


def test_search_executor_falls_back_when_first_provider_fails() -> None:
    class FailFirstOrchestrator:
        def __init__(self):
            self.calls = []

        def search(self, query, max_results, offset, engines):
            self.calls.append(list(engines))
            if engines == ["brave"]:
                raise RuntimeError("brave failed")
            return SimpleNamespace(
                results=[],
                took_ms=12.0,
                metadata={"engines_used": list(engines)},
            )

    orchestrator = FailFirstOrchestrator()
    executor = SearchExecutor(orchestrator)
    registry = MetricsRegistry(default_windows_seconds=(300,))
    planner = SearchPlanner(
        scorer=ProviderScorer(metrics_registry=registry),
        default_search_engines=["brave", "duckduckgo"],
    )
    plan = planner.plan(
        UnifiedSearchRequest(
            query="indiana code",
            provider_allowlist=["brave", "duckduckgo"],
        )
    )

    result = executor.execute(plan)

    assert orchestrator.calls[0] == ["brave"]
    assert orchestrator.calls[1] == ["duckduckgo"]
    assert result.providers_attempted == ["brave", "duckduckgo"]
    assert result.provider_selected == "duckduckgo"
    assert result.fallback_count == 1
