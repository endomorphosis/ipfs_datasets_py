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


def test_core_backend_call_sites_define_policy_and_breaker_wiring() -> None:
    expected_markers = {
        "graphrag/ontology_generator.py": [
            "_llm_call_policy = BackendCallPolicy(",
            "_llm_call_circuit_breaker",
            "circuit_breaker=self._llm_call_circuit_breaker",
        ],
        "graphrag/ontology_refinement_agent.py": [
            "_backend_call_policy",
            "_backend_circuit_breaker",
            "circuit_breaker=self._backend_circuit_breaker",
        ],
        "logic_theorem_optimizer/logic_extractor.py": [
            "_llm_call_policy = BackendCallPolicy(",
            "_llm_call_circuit_breaker",
            "circuit_breaker=self._llm_call_circuit_breaker",
        ],
        "logic_theorem_optimizer/llm_backend.py": [
            "_backend_call_policy = BackendCallPolicy(",
            "CircuitBreaker(",
            "circuit_breaker=circuit_breaker",
        ],
        "logic_theorem_optimizer/formula_translation.py": [
            "_parse_policy = BackendCallPolicy(",
            "_nl_generate_policy = BackendCallPolicy(",
            "circuit_breaker=self._parse_circuit_breaker",
            "circuit_breaker=self._nl_generate_circuit_breaker",
        ],
        "agentic/llm_integration.py": [
            "return BackendCallPolicy(",
            "self._resilience_breakers",
            "circuit_breaker=self._resilience_breakers[current_provider]",
        ],
    }

    for module_path, markers in expected_markers.items():
        src = _source(module_path)
        for marker in markers:
            assert marker in src, f"Missing marker '{marker}' in {module_path}"


def test_backend_policy_service_names_follow_module_conventions() -> None:
    expected_service_markers = {
        "graphrag/ontology_generator.py": ['service_name="graphrag_ontology_generator_llm"'],
        "graphrag/ontology_refinement_agent.py": ['service_name="graphrag_refinement_llm"'],
        "logic_theorem_optimizer/logic_extractor.py": ['service_name="logic_extractor_llm"'],
        "logic_theorem_optimizer/llm_backend.py": [
            'service_name="logic_theorem_optimizer_backend"',
            'service_name=f"{self._backend_call_policy.service_name}_{backend_name}"',
        ],
        "logic_theorem_optimizer/formula_translation.py": [
            'service_name="tdfol_reasoner_parse"',
            'service_name="tdfol_reasoner_nl_generate"',
        ],
        "agentic/llm_integration.py": ['service_name=f"agentic_{provider.value}"'],
        "llm_lazy_loader.py": ['service_name=f"lazy_llm_backend_{backend_type}"'],
    }

    for module_path, markers in expected_service_markers.items():
        src = _source(module_path)
        for marker in markers:
            assert marker in src, f"Missing service-name marker '{marker}' in {module_path}"


def test_backend_policy_defaults_include_timeout_retry_backoff_and_circuit_fields() -> None:
    expected_policy_fields = {
        "graphrag/ontology_generator.py": [
            "timeout_seconds=20.0",
            "max_retries=2",
            "initial_backoff_seconds=0.1",
            "backoff_multiplier=2.0",
            "circuit_failure_threshold=5",
        ],
        "graphrag/ontology_refinement_agent.py": [
            "timeout_seconds=15.0",
            "max_retries=2",
            "initial_backoff_seconds=0.1",
            "backoff_multiplier=2.0",
            "circuit_failure_threshold=5",
        ],
        "logic_theorem_optimizer/logic_extractor.py": [
            "timeout_seconds=20.0",
            "max_retries=2",
            "initial_backoff_seconds=0.1",
            "backoff_multiplier=2.0",
            "circuit_failure_threshold=5",
        ],
        "logic_theorem_optimizer/llm_backend.py": [
            "timeout_seconds=30.0",
            "max_retries=2",
            "initial_backoff_seconds=0.1",
            "backoff_multiplier=2.0",
            "circuit_failure_threshold=5",
        ],
        "logic_theorem_optimizer/formula_translation.py": [
            "timeout_seconds=20.0",
            "max_retries=1",
            "initial_backoff_seconds=0.1",
            "backoff_multiplier=2.0",
            "circuit_failure_threshold=5",
        ],
        "agentic/llm_integration.py": [
            "timeout_seconds=30.0",
            "max_retries=0",
            "initial_backoff_seconds=0.0",
            "backoff_multiplier=2.0",
            "circuit_failure_threshold=3",
        ],
        "llm_lazy_loader.py": [
            "timeout_seconds=30.0",
            "max_retries=2",
            "initial_backoff_seconds=0.1",
            "backoff_multiplier=2.0",
            "circuit_failure_threshold=max(1, int(failure_threshold))",
        ],
    }

    for module_path, markers in expected_policy_fields.items():
        src = _source(module_path)
        for marker in markers:
            assert marker in src, f"Missing policy default marker '{marker}' in {module_path}"


def test_resilience_outcomes_map_to_fallback_or_error_accounting_paths() -> None:
    outcome_markers = {
        "graphrag/ontology_generator.py": [
            "CircuitBreakerOpenError",
            "RetryableBackendError",
            "LLM extraction failed, falling back to rule-based",
            'fallback.metadata["method"] = "llm_fallback_rule_based"',
        ],
        "graphrag/ontology_refinement_agent.py": [
            "except (CircuitBreakerOpenError, RetryableBackendError) as exc:",
            "LLM backend invocation failed",
            "return {}",
        ],
        "logic_theorem_optimizer/logic_extractor.py": [
            "CircuitBreakerOpenError",
            "RetryableBackendError",
            "LLM backend error: %s, using fallback",
            "return self._mock_llm_response(context)",
        ],
        "logic_theorem_optimizer/llm_backend.py": [
            "CircuitBreakerOpenError",
            "RetryableBackendError",
            "self.stats['errors'] += 1",
            "Falling back to mock backend",
        ],
        "logic_theorem_optimizer/formula_translation.py": [
            "CircuitBreakerOpenError",
            "RetryableBackendError",
            "TDFOL translation error:",
            "success=False",
        ],
        "agentic/llm_integration.py": [
            "CircuitBreakerOpenError",
            "OptimizerTimeoutError",
            "RetryableBackendError",
            "self.error_count[provider_name] = self.error_count.get(provider_name, 0) + 1",
            "continue",
        ],
        "llm_lazy_loader.py": [
            "except (CircuitBreakerOpen, CircuitBreakerOpenError) as e:",
            "LLM backend temporarily unavailable",
            "except RetryableBackendError as e:",
            "LLM backend error:",
        ],
    }

    for module_path, markers in outcome_markers.items():
        src = _source(module_path)
        for marker in markers:
            assert marker in src, f"Missing outcome-mapping marker '{marker}' in {module_path}"


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
