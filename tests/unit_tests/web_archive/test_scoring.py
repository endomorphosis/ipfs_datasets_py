#!/usr/bin/env python3

import time

import pytest

from ipfs_datasets_py.processors.web_archiving.contracts import OperationMode
from ipfs_datasets_py.processors.web_archiving.metrics.registry import MetricsRegistry
from ipfs_datasets_py.processors.web_archiving.orchestration.scoring import ProviderScorer


def _seed_metrics(registry: MetricsRegistry) -> None:
    now = time.time()
    # Fast and reliable provider.
    registry.record_event(
        provider="common_crawl",
        operation="fetch",
        success=True,
        latency_ms=120,
        items_processed=20,
        quality_score=0.8,
        timestamp=now - 30,
    )
    registry.record_event(
        provider="common_crawl",
        operation="fetch",
        success=True,
        latency_ms=150,
        items_processed=18,
        quality_score=0.85,
        timestamp=now - 20,
    )

    # Slower provider with lower throughput.
    registry.record_event(
        provider="wayback",
        operation="fetch",
        success=True,
        latency_ms=700,
        items_processed=4,
        quality_score=0.75,
        timestamp=now - 25,
    )
    registry.record_event(
        provider="wayback",
        operation="fetch",
        success=False,
        latency_ms=900,
        items_processed=0,
        timestamp=now - 10,
    )


def test_provider_scorer_prefers_high_throughput_in_max_throughput_mode() -> None:
    registry = MetricsRegistry(default_windows_seconds=(300,))
    _seed_metrics(registry)

    scorer = ProviderScorer(metrics_registry=registry, default_window_seconds=300)
    ranked = scorer.rank_providers(
        providers=["wayback", "common_crawl"],
        operation="fetch",
        mode=OperationMode.MAX_THROUGHPUT,
        window_seconds=300,
    )

    assert ranked[0].provider == "common_crawl"
    assert ranked[0].score > ranked[1].score
    assert ranked[0].components["throughput_norm"] >= ranked[1].components["throughput_norm"]


def test_provider_scorer_low_cost_mode_penalizes_cost_hint() -> None:
    registry = MetricsRegistry(default_windows_seconds=(300,))
    _seed_metrics(registry)

    scorer = ProviderScorer(metrics_registry=registry)
    ranked = scorer.rank_providers(
        providers=["common_crawl", "wayback"],
        operation="fetch",
        mode=OperationMode.LOW_COST,
        window_seconds=300,
        cost_hints={"common_crawl": 0.9, "wayback": 0.1},
    )

    assert ranked[0].provider == "wayback"
    assert ranked[0].components["cost_norm"] > ranked[1].components["cost_norm"]


def test_provider_scorer_validation_errors() -> None:
    registry = MetricsRegistry(default_windows_seconds=(300,))
    scorer = ProviderScorer(metrics_registry=registry)

    with pytest.raises(ValueError):
        scorer.score_provider(provider="", operation="search")

    with pytest.raises(ValueError):
        scorer.score_provider(provider="brave", operation="")

    with pytest.raises(ValueError):
        scorer.score_provider(provider="brave", operation="search", cost_hint=-1)
