"""Additional helper coverage for GraphRAG utility methods."""

from __future__ import annotations

from types import SimpleNamespace

from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore, OntologyCritic
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
    ExtractionConfig,
    OntologyGenerator,
    Relationship,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import (
    OntologyLearningAdapter,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline


def _result() -> EntityExtractionResult:
    return EntityExtractionResult(
        entities=[
            Entity(id="e1", type="Person", text="Alice", confidence=0.9),
            Entity(id="e2", type="Organization", text="Acme", confidence=0.3),
            Entity(id="e3", type="Person", text="Bob", confidence=0.6),
        ],
        relationships=[
            Relationship(id="r1", source_id="e1", target_id="e2", type="worksFor", confidence=0.8),
            Relationship(id="r2", source_id="e3", target_id="e2", type="worksFor", confidence=0.7),
        ],
        confidence=0.7,
    )


def test_generator_sorted_entities_and_relationships_for_entity() -> None:
    gen = OntologyGenerator(use_ipfs_accelerate=False)
    result = _result()

    sorted_ids = [e.id for e in gen.sorted_entities(result, key="confidence", reverse=True)]
    assert sorted_ids == ["e1", "e3", "e2"]

    rels = gen.relationships_for_entity(result, "e2")
    assert {r.id for r in rels} == {"r1", "r2"}


def test_entity_extraction_result_text_and_confidence_helpers() -> None:
    result = _result()

    assert result.entity_texts() == ["Alice", "Acme", "Bob"]
    assert result.max_confidence() == 0.9
    assert result.min_confidence() == 0.3
    hist = result.confidence_histogram(bins=3)
    assert sum(hist) == result.entity_count


def test_extraction_config_to_dict_shape() -> None:
    cfg = ExtractionConfig(confidence_threshold=0.61, max_entities=17)
    payload = cfg.to_dict()
    assert payload["confidence_threshold"] == 0.61
    assert payload["max_entities"] == 17
    assert "domain_vocab" in payload


def test_learning_adapter_clear_feedback_and_threshold_filters() -> None:
    adapter = OntologyLearningAdapter()
    adapter.apply_feedback(0.9, actions=[{"action": "normalize"}])
    adapter.apply_feedback(0.2, actions=[{"action": "drop_noise"}])
    adapter.apply_feedback(0.6, actions=[])

    assert len(adapter.feedback_below(0.5)) == 1
    assert len(adapter.feedback_above(0.7)) == 1
    assert adapter.clear_feedback() == 3
    assert adapter.feedback_count() == 0


def test_logic_validator_contradiction_aliases_and_summary() -> None:
    validator = LogicValidator(use_cache=False)

    # Use monkeypatched consistency to avoid depending on heavy prover behavior.
    validator.check_consistency = lambda ontology: SimpleNamespace(  # type: ignore[method-assign]
        contradictions=[{"kind": "x"}] if ontology.get("has_issue") else []
    )
    validator.count_contradictions = lambda ontology: len(  # type: ignore[method-assign]
        validator.check_consistency(ontology).contradictions
    )

    clean = {"entities": [{"id": "e1"}], "relationships": []}
    bad = {"entities": [{"id": "e1"}], "relationships": [], "has_issue": True}

    assert validator.contradiction_count(clean) == 0
    assert validator.has_contradictions(clean) is False
    assert validator.has_contradictions(bad) is True
    assert validator.summary_dict(bad) == {
        "entity_count": 1,
        "relationship_count": 0,
        "has_contradictions": True,
    }


def test_pipeline_warmup_preserves_existing_history() -> None:
    pipeline = OntologyPipeline(domain="general", use_llm=False, max_rounds=1)
    sentinel = [SimpleNamespace(score=SimpleNamespace(overall=0.42))]
    pipeline._run_history = list(sentinel)  # type: ignore[attr-defined]

    def _fake_run(_text: str):
        pipeline._run_history.append(SimpleNamespace(score=SimpleNamespace(overall=1.0)))  # type: ignore[attr-defined]
        return SimpleNamespace(score=SimpleNamespace(overall=1.0))

    pipeline.run = _fake_run  # type: ignore[method-assign]
    pipeline.warmup(3)

    assert len(pipeline._run_history) == 1  # type: ignore[attr-defined]
    assert pipeline._run_history[0].score.overall == 0.42  # type: ignore[attr-defined]


def test_critic_best_and_worst_dimension_helpers() -> None:
    critic = OntologyCritic(use_llm=False)
    score = CriticScore(
        completeness=0.3,
        consistency=0.9,
        clarity=0.6,
        granularity=0.4,
        relationship_coherence=0.7,
        domain_alignment=0.5,
    )
    assert critic.best_dimension(score) == "consistency"
    assert critic.worst_dimension(score) == "completeness"
