"""Batch 310: LLM fallback evaluator tests for ambiguous OntologyCritic scores."""

from __future__ import annotations

from types import SimpleNamespace

from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic


def _ontology() -> dict:
    return {
        "entities": [
            {"id": "e1", "type": "Person", "text": "Alice", "confidence": 0.8},
            {"id": "e2", "type": "Person", "text": "Bob", "confidence": 0.8},
        ],
        "relationships": [
            {"id": "r1", "source_id": "e1", "target_id": "e2", "type": "knows", "confidence": 0.7}
        ],
        "metadata": {},
    }


def _context() -> SimpleNamespace:
    return SimpleNamespace(domain="general")


def test_llm_fallback_applies_dimension_overrides_and_recommendations() -> None:
    critic = OntologyCritic(use_llm=True)
    critic._llm_available = True

    class _Client:
        def evaluate_ontology(self, ontology, context, base_score):
            return {
                "dimensions": {"clarity": 0.93, "consistency": 0.89},
                "recommendations": ["LLM fallback: improve edge labeling consistency"],
                "confidence": 0.84,
            }

    critic._llm_client = _Client()
    critic._is_score_ambiguous = lambda score: True

    score = critic.evaluate_ontology(_ontology(), _context(), source_data="bypass-cache")

    assert score.metadata.get("llm_fallback_used") is True
    assert score.metadata.get("llm_fallback_confidence") == 0.84
    assert score.clarity == 0.93
    assert score.consistency == 0.89
    assert any("LLM fallback" in rec for rec in score.recommendations)


def test_llm_fallback_not_called_when_score_not_ambiguous() -> None:
    critic = OntologyCritic(use_llm=True)
    critic._llm_available = True

    class _Client:
        def __init__(self):
            self.called = False

        def evaluate_ontology(self, ontology, context, base_score):
            self.called = True
            return {"dimensions": {"clarity": 0.95}}

    client = _Client()
    critic._llm_client = client
    critic._is_score_ambiguous = lambda score: False

    score = critic.evaluate_ontology(_ontology(), _context(), source_data="bypass-cache")

    assert client.called is False
    assert score.metadata.get("llm_fallback_used") is False


def test_llm_fallback_errors_are_non_fatal() -> None:
    critic = OntologyCritic(use_llm=True)
    critic._llm_available = True

    class _Client:
        def evaluate_ontology(self, ontology, context, base_score):
            raise RuntimeError("simulated llm outage")

    critic._llm_client = _Client()
    critic._is_score_ambiguous = lambda score: True

    score = critic.evaluate_ontology(_ontology(), _context(), source_data="bypass-cache")

    assert score.metadata.get("llm_fallback_used") is False
    assert score.metadata.get("llm_fallback_error") == "RuntimeError"
