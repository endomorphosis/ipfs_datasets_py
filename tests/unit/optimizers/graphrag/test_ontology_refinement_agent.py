"""Tests for OntologyRefinementAgent scaffolding."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.common.backend_resilience import BackendCallPolicy
from ipfs_datasets_py.optimizers.common.exceptions import RetryableBackendError
from ipfs_datasets_py.optimizers.graphrag.ontology_refinement_agent import (
    OntologyRefinementAgent,
    NoOpRefinementAgent,
    sanitize_feedback,
    validate_feedback_schema,
)


def test_parse_feedback_dict_passthrough():
    agent = OntologyRefinementAgent(llm_backend=None)
    payload = {"confidence_floor": 0.7}
    assert agent.parse_feedback(payload) == payload


def test_parse_feedback_json_string():
    agent = OntologyRefinementAgent(llm_backend=None)
    response = '{"entities_to_remove": ["e1"], "confidence_floor": 0.6}'
    parsed = agent.parse_feedback(response)
    assert parsed["entities_to_remove"] == ["e1"]
    assert parsed["confidence_floor"] == 0.6


def test_propose_feedback_with_callable_backend():
    def _backend(prompt: str):
        return {"relationships_to_remove": ["r1"]}

    agent = OntologyRefinementAgent(llm_backend=_backend)
    ontology = {"entities": [], "relationships": []}
    score = type("Score", (), {"recommendations": ["Remove weak relationships"]})()

    feedback = agent.propose_feedback(ontology, score, context=None)
    assert feedback == {"relationships_to_remove": ["r1"]}


def test_propose_feedback_backend_exception_returns_empty():
    def _backend(_prompt: str):
        raise ValueError("backend down")

    agent = OntologyRefinementAgent(llm_backend=_backend)
    ontology = {"entities": [], "relationships": []}
    score = type("Score", (), {"recommendations": ["Retry later"]})()

    feedback = agent.propose_feedback(ontology, score, context=None)
    assert feedback == {}


def test_noop_agent_returns_fixed_feedback_copy():
    payload = {"confidence_floor": 0.6}
    agent = NoOpRefinementAgent(feedback=payload)

    feedback = agent.propose_feedback(ontology={}, score=None, context=None)
    assert feedback == payload
    assert feedback is not payload


def test_noop_agent_defaults_to_empty_feedback():
    agent = NoOpRefinementAgent()
    feedback = agent.propose_feedback(ontology={}, score=None, context=None)
    assert feedback == {}


def test_sanitize_feedback_filters_invalid_entries():
    payload = {
        "entities_to_remove": ["e1"],
        "confidence_floor": "high",
        "unsupported": 123,
    }
    cleaned, errors = sanitize_feedback(payload)
    assert cleaned == {"entities_to_remove": ["e1"]}
    assert "confidence_floor must be a number" in errors
    assert "unsupported feedback key: unsupported" in errors


def test_validate_feedback_schema_reports_type_errors():
    errors = validate_feedback_schema(
        {
            "entities_to_merge": ["e1", "e2"],
            "relationships_to_add": ["rel"],
        }
    )
    assert "entities_to_merge must be a list of [id1, id2] pairs" in errors
    assert "relationships_to_add must be a list of dicts" in errors


def test_validate_feedback_schema_strict_enforces_ranges_and_fields():
    errors = validate_feedback_schema(
        {
            "relationships_to_add": [{"source_id": "e1", "target_id": "e2"}],
            "confidence_floor": 1.5,
        },
        strict=True,
    )
    assert "relationships_to_add must be a list of dicts" in errors
    assert "confidence_floor must be in [0.0, 1.0]" in errors


def test_sanitize_feedback_strict_drops_invalid_relationships():
    payload = {"relationships_to_add": [{"source_id": "e1", "target_id": "e2"}]}
    cleaned, errors = sanitize_feedback(payload, strict=True)
    assert cleaned == {}
    assert "relationships_to_add must be a list of dicts" in errors


def test_agent_strict_validation_drops_invalid_feedback():
    def _backend(prompt: str):
        return {"relationships_to_add": [{"source_id": "e1", "target_id": "e2"}]}

    agent = OntologyRefinementAgent(llm_backend=_backend, strict_validation=True)
    feedback = agent.propose_feedback(ontology={}, score=None, context=None)
    assert feedback == {}


def test_propose_feedback_uses_common_backend_resilience_wrapper(monkeypatch):
    captured = {"service_name": None, "breaker_name": None}

    def _fake_resilience_call(operation, policy, *, circuit_breaker, sleep_fn=None):
        captured["service_name"] = policy.service_name
        captured["breaker_name"] = getattr(circuit_breaker, "name", None)
        return operation()

    monkeypatch.setattr(
        "ipfs_datasets_py.optimizers.graphrag.ontology_refinement_agent.execute_with_resilience",
        _fake_resilience_call,
    )

    def _backend(prompt: str):
        return {"entities_to_remove": ["e2"]}

    agent = OntologyRefinementAgent(
        llm_backend=_backend,
        backend_call_policy=BackendCallPolicy(service_name="test_refinement_policy"),
    )

    feedback = agent.propose_feedback(ontology={}, score=None, context=None)
    assert feedback == {"entities_to_remove": ["e2"]}
    assert captured["service_name"] == "test_refinement_policy"
    assert captured["breaker_name"] == "test_refinement_policy"


def test_propose_feedback_resilience_error_returns_empty(monkeypatch):
    def _raise_resilience_error(operation, policy, *, circuit_breaker, sleep_fn=None):
        raise RetryableBackendError("backend unavailable", service=policy.service_name)

    monkeypatch.setattr(
        "ipfs_datasets_py.optimizers.graphrag.ontology_refinement_agent.execute_with_resilience",
        _raise_resilience_error,
    )

    def _backend(prompt: str):
        return {"entities_to_remove": ["e2"]}

    agent = OntologyRefinementAgent(llm_backend=_backend)
    feedback = agent.propose_feedback(ontology={}, score=None, context=None)
    assert feedback == {}
