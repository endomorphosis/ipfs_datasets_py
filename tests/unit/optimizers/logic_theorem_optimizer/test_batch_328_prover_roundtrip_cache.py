"""Batch 328: Prover round-trip profiling and formula-hash cache tests."""

from __future__ import annotations

import hashlib
import time

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.prover_integration import (
    ProverIntegrationAdapter,
)


class _DummyStatement:
    def __init__(self, formula: str):
        self.formula = formula


class _DummyProver:
    def __init__(self):
        self.calls = 0

    def prove(self, formula, timeout=5.0):
        self.calls += 1
        return True


class _CachedEntry:
    def __init__(self, result):
        self.result = result


class _InMemoryCache:
    def __init__(self):
        self.store = {}
        self.last_set_key = None

    def get(self, key, prover_name="aggregated"):
        value = self.store.get((key, prover_name))
        if value is None:
            return None
        return _CachedEntry(value)

    def set(self, key, result, prover_name="aggregated"):
        self.last_set_key = key
        self.store[(key, prover_name)] = result


def test_verify_statement_uses_formula_hash_cache_key_and_hits_cache():
    adapter = ProverIntegrationAdapter(use_provers=[], enable_cache=False)
    prover = _DummyProver()
    cache = _InMemoryCache()

    adapter.provers["dummy"] = prover
    adapter.cache = cache

    stmt = _DummyStatement("P(x) -> Q(x)")
    expected_key = "sha256:" + hashlib.sha256(stmt.formula.encode("utf-8")).hexdigest()

    first = adapter.verify_statement(stmt)
    second = adapter.verify_statement(stmt)

    assert first.overall_valid is True
    assert second.overall_valid is True
    assert prover.calls == 1  # second call served from cache
    assert adapter.stats["cache_hits"] == 1
    assert adapter.stats["cache_misses"] == 1
    assert cache.last_set_key == expected_key


def test_get_statistics_includes_round_trip_profile_metrics():
    adapter = ProverIntegrationAdapter(use_provers=[], enable_cache=False)
    prover = _DummyProver()
    adapter.provers["dummy"] = prover

    adapter.verify_statement(_DummyStatement("A(x)"))
    time.sleep(0.001)
    adapter.verify_statement(_DummyStatement("B(x)"))

    stats = adapter.get_statistics()

    assert stats["round_trip_count"] == 2
    assert stats["round_trip_total_ms"] > 0.0
    assert stats["round_trip_max_ms"] > 0.0
    assert stats["round_trip_avg_ms"] > 0.0
    assert stats["num_provers"] == 1
