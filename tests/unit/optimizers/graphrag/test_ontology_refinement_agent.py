"""Tests for OntologyRefinementAgent scaffolding."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.graphrag.ontology_refinement_agent import (
    OntologyRefinementAgent,
    NoOpRefinementAgent,
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
