"""Tests for PipelineResult JSON/dict round-trip serialization."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import PipelineResult


def _score() -> CriticScore:
    return CriticScore(
        completeness=0.8,
        consistency=0.75,
        clarity=0.7,
        granularity=0.65,
        domain_alignment=0.9,
        strengths=["good coverage"],
        weaknesses=["naming drift"],
        recommendations=["normalize naming"],
        metadata={"source": "test"},
    )


def _result() -> PipelineResult:
    ontology = {
        "entities": [{"id": "e1", "text": "Alice", "type": "Person"}],
        "relationships": [{"id": "r1", "source_id": "e1", "target_id": "e1", "type": "related_to"}],
        "metadata": {"domain": "test"},
    }
    return PipelineResult(
        ontology=ontology,
        score=_score(),
        entities=ontology["entities"],
        relationships=ontology["relationships"],
        actions_applied=["normalize_names"],
        metadata={"domain": "test", "entity_count": 1},
    )


def test_pipeline_result_to_dict_contains_expected_keys():
    data = _result().to_dict()

    assert set(data.keys()) == {
        "ontology",
        "score",
        "entities",
        "relationships",
        "actions_applied",
        "metadata",
    }
    assert "dimensions" in data["score"]


def test_pipeline_result_from_dict_rehydrates_critic_score():
    original = _result()
    rebuilt = PipelineResult.from_dict(original.to_dict())

    assert isinstance(rebuilt.score, CriticScore)
    assert rebuilt.score.completeness == original.score.completeness
    assert rebuilt.ontology == original.ontology


def test_pipeline_result_json_roundtrip_preserves_fields():
    original = _result()

    payload = original.to_json()
    rebuilt = PipelineResult.from_json(payload)

    assert rebuilt.actions_applied == ["normalize_names"]
    assert rebuilt.entities[0]["id"] == "e1"
    assert rebuilt.metadata["entity_count"] == 1
    assert isinstance(rebuilt.score, CriticScore)
