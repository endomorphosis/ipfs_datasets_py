"""Tests for typed exception handling in prover integration adapter."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.prover_integration import (
    ProverIntegrationAdapter,
    ProverStatus,
)


class _FailingProver:
    def prove(self, formula, timeout=5.0):
        raise ValueError("bad proof input")


class _BadCacheGet:
    def get(self, *args, **kwargs):
        raise KeyError("cache get failure")


class _BadCacheSet:
    def set(self, *args, **kwargs):
        raise RuntimeError("cache set failure")


class _ClosableFail:
    def close(self):
        raise RuntimeError("close failed")


def test_verify_with_prover_returns_error_result_on_typed_exception() -> None:
    adapter = ProverIntegrationAdapter(use_provers=[], enable_cache=False)
    adapter.provers["failing"] = _FailingProver()

    result = adapter.verify_statement("P(x)")

    assert adapter.stats["errors"] == 1
    assert len(result.prover_results) == 1
    assert result.prover_results[0].status == ProverStatus.ERROR
    assert result.prover_results[0].is_valid is False


def test_check_cache_swallow_typed_error_returns_none() -> None:
    adapter = ProverIntegrationAdapter(use_provers=[], enable_cache=False)
    adapter.cache = _BadCacheGet()

    cached = adapter._check_cache("P(x)")

    assert cached is None


def test_cache_result_swallow_typed_error() -> None:
    adapter = ProverIntegrationAdapter(use_provers=[], enable_cache=False)
    adapter.cache = _BadCacheSet()

    # Should not raise.
    adapter._cache_result("P(x)", adapter._aggregate_results([]))


def test_close_swallow_typed_error() -> None:
    adapter = ProverIntegrationAdapter(use_provers=[], enable_cache=False)
    adapter.provers["closer"] = _ClosableFail()

    # Should not raise.
    adapter.close()
