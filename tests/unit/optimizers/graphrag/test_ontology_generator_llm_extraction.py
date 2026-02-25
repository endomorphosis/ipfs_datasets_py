"""Tests for LLM-based extraction flow in OntologyGenerator."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.common.exceptions import RetryableBackendError
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    ExtractionStrategy,
    OntologyGenerationContext,
    OntologyGenerator,
)


def test_llm_based_extraction_uses_injected_backend_without_accelerate() -> None:
    def llm_backend(_prompt: str):
        return {
            "entities": [
                {"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.92},
                {"id": "e2", "text": "Acme Corp", "type": "Organization", "confidence": 0.89},
            ],
            "relationships": [
                {
                    "id": "r1",
                    "source_id": "e1",
                    "target_id": "e2",
                    "type": "worksFor",
                    "confidence": 0.88,
                }
            ],
            "confidence": 0.9,
        }

    generator = OntologyGenerator(use_ipfs_accelerate=False, llm_backend=llm_backend)
    context = OntologyGenerationContext(
        data_source="unit-test",
        data_type="text",
        domain="general",
        extraction_strategy=ExtractionStrategy.LLM_BASED,
    )

    result = generator.extract_entities("Alice works for Acme Corp.", context)

    assert result.metadata.get("method") == "llm_based"
    assert len(result.entities) == 2
    assert len(result.relationships) == 1
    assert result.entities[0].id == "e1"
    assert result.relationships[0].type == "worksFor"


def test_llm_based_extraction_falls_back_on_backend_parse_error() -> None:
    def broken_backend(_prompt: str):
        return "not-json"

    generator = OntologyGenerator(use_ipfs_accelerate=False, llm_backend=broken_backend)
    context = OntologyGenerationContext(
        data_source="unit-test",
        data_type="text",
        domain="general",
        extraction_strategy=ExtractionStrategy.LLM_BASED,
    )

    result = generator.extract_entities("Alice met Bob in Seattle.", context)

    assert result.metadata.get("method") == "llm_fallback_rule_based"
    assert len(result.entities) >= 1


def test_llm_backend_invocation_uses_common_resilience_wrapper(monkeypatch) -> None:
    captured = {"service_name": None, "breaker_name": None}

    def _fake_resilience_call(operation, policy, *, circuit_breaker, sleep_fn=None):
        captured["service_name"] = policy.service_name
        captured["breaker_name"] = getattr(circuit_breaker, "name", None)
        return operation()

    monkeypatch.setattr(
        "ipfs_datasets_py.optimizers.graphrag.ontology_generator.execute_with_resilience",
        _fake_resilience_call,
    )

    def llm_backend(_prompt: str):
        return {"entities": [], "relationships": [], "confidence": 0.8}

    generator = OntologyGenerator(use_ipfs_accelerate=False, llm_backend=llm_backend)
    raw = generator._invoke_llm_extraction_backend("prompt")

    assert isinstance(raw, dict)
    assert captured["service_name"] == "graphrag_ontology_generator_llm"
    assert captured["breaker_name"] == "graphrag_ontology_generator_llm"


def test_llm_based_extraction_falls_back_on_resilience_error(monkeypatch) -> None:
    def _raise_retryable(operation, policy, *, circuit_breaker, sleep_fn=None):
        raise RetryableBackendError("llm unavailable", service=policy.service_name)

    monkeypatch.setattr(
        "ipfs_datasets_py.optimizers.graphrag.ontology_generator.execute_with_resilience",
        _raise_retryable,
    )

    def llm_backend(_prompt: str):
        return {"entities": [], "relationships": [], "confidence": 0.9}

    generator = OntologyGenerator(use_ipfs_accelerate=False, llm_backend=llm_backend)
    context = OntologyGenerationContext(
        data_source="unit-test",
        data_type="text",
        domain="general",
        extraction_strategy=ExtractionStrategy.LLM_BASED,
    )

    result = generator.extract_entities("Alice met Bob in Seattle.", context)

    assert result.metadata.get("method") == "llm_fallback_rule_based"
