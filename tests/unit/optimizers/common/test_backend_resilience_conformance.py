"""Conformance checks for backend resilience coverage in optimizer modules."""

from __future__ import annotations

from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[4]
_OPTIMIZERS_ROOT = _REPO_ROOT / "ipfs_datasets_py" / "optimizers"


def _source(path: str) -> str:
    return (_OPTIMIZERS_ROOT / path).read_text(encoding="utf-8")


def test_core_backend_call_sites_use_shared_resilience_wrapper() -> None:
    expected = {
        "graphrag/ontology_generator.py": "execute_with_resilience(",
        "graphrag/ontology_refinement_agent.py": "execute_with_resilience(",
        "logic_theorem_optimizer/logic_extractor.py": "execute_with_resilience(",
        "logic_theorem_optimizer/llm_backend.py": "execute_with_resilience(",
        "logic_theorem_optimizer/formula_translation.py": "execute_with_resilience(",
        "agentic/llm_integration.py": "execute_with_resilience(",
    }

    for module_path, marker in expected.items():
        assert marker in _source(module_path), f"Missing resilience marker in {module_path}"


def test_lazy_loader_retains_circuit_breaker_protection() -> None:
    src = _source("llm_lazy_loader.py")
    assert "CircuitBreaker(" in src
    assert "CircuitBreakerOpen" in src
    assert "BackendCallPolicy(" in src
    assert "execute_with_resilience(" in src


def test_lazy_loader_uses_shared_resilience_wrapper_with_policy_and_breaker() -> None:
    src = _source("llm_lazy_loader.py")
    assert "_backend_call_policy = BackendCallPolicy(" in src
    assert "circuit_breaker=self._circuit_breaker" in src
    assert "if not hasattr(self._circuit_breaker, \"call\")" in src
