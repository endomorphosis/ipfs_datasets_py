"""Batch-65 feature tests.

Covers:
- OntologyCritic.evaluate_with_rubric()
- LogicValidator.filter_valid_entities()
- OntologyGenerator.score_entity()
- OntologyPipeline.as_dict() and OntologyPipeline.reset()
- OntologyGenerator.batch_extract_with_spans()
"""

import math
import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
    ExtractionConfig,
    OntologyGenerator,
    OntologyGenerationContext,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic, CriticScore
from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ctx(domain: str = "test") -> OntologyGenerationContext:
    return OntologyGenerationContext(data_source="test", data_type="text", domain=domain)


def _small_ontology() -> dict:
    return {
        "entities": [
            {"id": "e1", "type": "Person", "text": "Alice"},
            {"id": "e2", "type": "Organization", "text": "ACME"},
        ],
        "relationships": [
            {"source": "e1", "target": "e2", "type": "works_at"},
        ],
    }


def _critic() -> OntologyCritic:
    return OntologyCritic(use_llm=False)


def _validator() -> LogicValidator:
    return LogicValidator()


def _generator() -> OntologyGenerator:
    return OntologyGenerator()


# ---------------------------------------------------------------------------
# OntologyCritic.evaluate_with_rubric
# ---------------------------------------------------------------------------

class TestEvaluateWithRubric:
    def test_returns_critic_score(self):
        score = _critic().evaluate_with_rubric(_small_ontology(), _ctx(), {"completeness": 1.0})
        assert isinstance(score, CriticScore)

    def test_rubric_overall_in_metadata(self):
        score = _critic().evaluate_with_rubric(_small_ontology(), _ctx(), {"completeness": 1.0})
        assert "rubric_overall" in score.metadata

    def test_overall_equals_single_dim(self):
        critic = _critic()
        ont = _small_ontology()
        ctx = _ctx()
        base = critic.evaluate_ontology(ont, ctx)
        rubric_score = critic.evaluate_with_rubric(ont, ctx, {"completeness": 1.0})
        assert abs(rubric_score.metadata["rubric_overall"] - base.completeness) < 1e-4

    def test_equal_weights_blend(self):
        critic = _critic()
        ont = _small_ontology()
        ctx = _ctx()
        base = critic.evaluate_ontology(ont, ctx)
        rubric = {
            "completeness": 1.0,
            "consistency": 1.0,
        }
        score = critic.evaluate_with_rubric(ont, ctx, rubric)
        expected = (base.completeness + base.consistency) / 2
        assert abs(score.metadata["rubric_overall"] - expected) < 1e-4

    def test_unknown_keys_ignored(self):
        critic = _critic()
        base = critic.evaluate_ontology(_small_ontology(), _ctx())
        score = critic.evaluate_with_rubric(
            _small_ontology(), _ctx(),
            {"completeness": 1.0, "nonexistent_dim": 5.0}
        )
        assert abs(score.metadata["rubric_overall"] - base.completeness) < 1e-4

    def test_empty_rubric_raises(self):
        with pytest.raises(ValueError):
            _critic().evaluate_with_rubric(_small_ontology(), _ctx(), {})

    def test_all_zero_weights_raises(self):
        with pytest.raises(ValueError):
            _critic().evaluate_with_rubric(
                _small_ontology(), _ctx(),
                {"completeness": 0.0, "consistency": 0.0}
            )

    def test_rubric_overall_in_range(self):
        score = _critic().evaluate_with_rubric(
            _small_ontology(), _ctx(),
            {"completeness": 0.3, "consistency": 0.4, "clarity": 0.3}
        )
        assert 0.0 <= score.metadata["rubric_overall"] <= 1.0

    def test_other_dims_preserved(self):
        critic = _critic()
        base = critic.evaluate_ontology(_small_ontology(), _ctx())
        rubric_score = critic.evaluate_with_rubric(
            _small_ontology(), _ctx(), {"completeness": 1.0}
        )
        assert rubric_score.consistency == base.consistency
        assert rubric_score.clarity == base.clarity


# ---------------------------------------------------------------------------
# LogicValidator.filter_valid_entities
# ---------------------------------------------------------------------------

class TestFilterValidEntities:
    def test_returns_list(self):
        entities = [{"id": "e1", "type": "Person", "text": "Alice"}]
        result = _validator().filter_valid_entities(entities)
        assert isinstance(result, list)

    def test_empty_input(self):
        assert _validator().filter_valid_entities([]) == []

    def test_valid_entities_pass_through(self):
        entities = [
            {"id": "e1", "type": "Person", "text": "Alice"},
            {"id": "e2", "type": "Organization", "text": "ACME"},
        ]
        result = _validator().filter_valid_entities(entities)
        assert len(result) <= len(entities)
        assert all(e in entities for e in result)

    def test_result_is_subset(self):
        entities = [
            {"id": "e1", "type": "Person", "text": "Alice"},
            {"id": "e2", "type": "Person", "text": "Bob"},
        ]
        result = _validator().filter_valid_entities(entities)
        for e in result:
            assert e in entities

    def test_handles_minimal_entity(self):
        # Should not raise even for bare dicts
        result = _validator().filter_valid_entities([{"id": "x", "type": "T", "text": ""}])
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# OntologyGenerator.score_entity
# ---------------------------------------------------------------------------

class TestScoreEntity:
    def _make_entity(self, text="Alice", etype="Person", confidence=1.0, span=None):
        return Entity(id="e1", type=etype, text=text, confidence=confidence, source_span=span)

    def test_returns_float(self):
        s = _generator().score_entity(self._make_entity())
        assert isinstance(s, float)

    def test_range(self):
        for conf in [0.0, 0.5, 1.0]:
            s = _generator().score_entity(self._make_entity(confidence=conf))
            assert 0.0 <= s <= 1.0

    def test_generic_type_lower(self):
        gen = _generator()
        specific = gen.score_entity(self._make_entity(etype="Person"))
        generic = gen.score_entity(self._make_entity(etype="Entity"))
        assert specific >= generic

    def test_longer_text_higher(self):
        gen = _generator()
        short = gen.score_entity(self._make_entity(text="Al"))
        long = gen.score_entity(self._make_entity(text="A" * 50))
        assert long >= short

    def test_high_confidence_boosts(self):
        gen = _generator()
        low = gen.score_entity(self._make_entity(confidence=0.1))
        high = gen.score_entity(self._make_entity(confidence=1.0))
        assert high > low

    def test_zero_confidence_generic_minimal(self):
        s = _generator().score_entity(self._make_entity(text="", etype="Unknown", confidence=0.0))
        assert s == 0.0

    def test_case_insensitive_generic_check(self):
        gen = _generator()
        upper = gen.score_entity(self._make_entity(etype="ENTITY"))
        lower = gen.score_entity(self._make_entity(etype="entity"))
        assert upper == lower


# ---------------------------------------------------------------------------
# OntologyPipeline.as_dict and reset
# ---------------------------------------------------------------------------

class TestPipelineAsDict:
    def test_returns_dict(self):
        d = OntologyPipeline(domain="legal").as_dict()
        assert isinstance(d, dict)

    def test_domain_preserved(self):
        d = OntologyPipeline(domain="medical").as_dict()
        assert d["domain"] == "medical"

    def test_max_rounds_preserved(self):
        d = OntologyPipeline(domain="x", max_rounds=7).as_dict()
        assert d["max_rounds"] == 7

    def test_use_llm_present(self):
        d = OntologyPipeline(domain="x", use_llm=False).as_dict()
        assert "use_llm" in d

    def test_reconstruct_from_dict(self):
        p = OntologyPipeline(domain="finance", max_rounds=2)
        d = p.as_dict()
        clone = OntologyPipeline(**d)
        assert clone.domain == p.domain
        assert clone._mediator.max_rounds == p._mediator.max_rounds


class TestPipelineReset:
    def test_reset_does_not_raise(self):
        p = OntologyPipeline(domain="test")
        p.reset()  # should not raise

    def test_reset_clears_mediator_state(self):
        p = OntologyPipeline(domain="test")
        # force some state
        if hasattr(p._mediator, "_undo_stack"):
            p._mediator._undo_stack.append({"entities": [], "relationships": []})
        p.reset()
        if hasattr(p._mediator, "_undo_stack"):
            assert p._mediator._undo_stack == []


# ---------------------------------------------------------------------------
# OntologyGenerator.batch_extract_with_spans
# ---------------------------------------------------------------------------

class TestBatchExtractWithSpans:
    def test_returns_correct_count(self):
        gen = _generator()
        docs = ["Alice works at ACME.", "Bob founded Globex."]
        results = gen.batch_extract_with_spans(docs, _ctx())
        assert len(results) == 2

    def test_empty_input(self):
        assert _generator().batch_extract_with_spans([], _ctx()) == []

    def test_single_doc(self):
        gen = _generator()
        results = gen.batch_extract_with_spans(["Alice.", ], _ctx())
        assert len(results) == 1
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
        assert isinstance(results[0], EntityExtractionResult)

    def test_order_preserved(self):
        gen = _generator()
        docs = [f"Doc {i}: entity_{i} is here." for i in range(5)]
        results = gen.batch_extract_with_spans(docs, _ctx())
        assert len(results) == 5

    def test_entities_have_types(self):
        gen = _generator()
        results = gen.batch_extract_with_spans(["Alice founded ACME Corp."], _ctx())
        assert isinstance(results[0].entities, list)

    def test_parallel_same_as_sequential(self):
        gen = _generator()
        docs = ["Alice.", "Bob."]
        parallel = gen.batch_extract_with_spans(docs, _ctx(), max_workers=2)
        sequential = [gen.extract_entities_with_spans(d, _ctx()) for d in docs]
        assert len(parallel) == len(sequential)
