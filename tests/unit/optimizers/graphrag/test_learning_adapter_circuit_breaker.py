"""Tests for learning_adapter circuit breaker behavior."""

import time

from ipfs_datasets_py.optimizers.graphrag.learning_adapter import (
    check_learning_cycle,
    increment_failure_counter,
)


class DummyMetricsCollector:
    def __init__(self) -> None:
        self.events = []

    def record_additional_metric(self, name, value, category) -> None:
        self.events.append((name, value, category))


class DummyLearningMetricsCollector:
    def __init__(self) -> None:
        self.learning_cycles = []
        self.circuit_breaker_events = []

    def record_learning_cycle(self, **kwargs) -> None:
        self.learning_cycles.append(kwargs)

    def record_circuit_breaker_event(self, **kwargs) -> None:
        self.circuit_breaker_events.append(kwargs)


class DummyQueryStats:
    def __init__(self, count: int = 0) -> None:
        self.query_count = count


class DummyHost:
    def __init__(self) -> None:
        self._learning_enabled = True
        self._learning_cycle = 10
        self._learning_failure_count = 0
        self._circuit_breaker_threshold = 2
        self._traversal_stats = {"relation_usefulness": {}}
        self.metrics_collector = DummyMetricsCollector()
        self.learning_metrics_collector = DummyLearningMetricsCollector()
        self.query_stats = DummyQueryStats(0)
        self._last_learning_query_count = 0

    def _learn_from_query_statistics(self, recent_queries_count):
        return {}


def test_increment_failure_counter_trips_circuit_breaker() -> None:
    host = DummyHost()

    increment_failure_counter(host, "first failure")
    increment_failure_counter(host, "second failure")

    assert host._learning_circuit_breaker_tripped is True
    assert host._circuit_breaker_retry_time >= time.time()

    event_names = [event[0] for event in host.metrics_collector.events]
    assert "learning_failure" in event_names
    assert "learning_failure_count" in event_names
    assert "circuit_breaker_tripped" in event_names


def test_check_learning_cycle_resets_circuit_breaker_after_timeout() -> None:
    host = DummyHost()
    host._learning_circuit_breaker_tripped = True
    host._circuit_breaker_retry_time = time.time() - 1
    host._learning_failure_count = 2

    check_learning_cycle(host)

    assert host._learning_circuit_breaker_tripped is False
    assert host._learning_failure_count == 0

    event_names = [event[0] for event in host.metrics_collector.events]
    assert "circuit_breaker_reset" in event_names


def test_check_learning_cycle_skips_when_circuit_breaker_active() -> None:
    host = DummyHost()
    host._learning_circuit_breaker_tripped = True
    host._circuit_breaker_retry_time = time.time() + 60

    check_learning_cycle(host)

    assert host._learning_circuit_breaker_tripped is True
    event_names = [event[0] for event in host.metrics_collector.events]
    assert "circuit_breaker_reset" not in event_names
