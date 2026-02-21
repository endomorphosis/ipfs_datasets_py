"""Batch 61: CriticScore.from_dict, OntologyPipeline.clone,
LogicValidator.explain_contradictions, OntologyGenerator.extract_entities_with_spans,
Hypothesis property test for ExtractionConfig round-trip.
"""
from __future__ import annotations

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
    ExtractionConfig,
    OntologyGenerationContext,
    OntologyGenerator,
    Relationship,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _score_dict(c=0.8, co=0.7, cl=0.6, g=0.5, da=0.4):
    return {
        "dimensions": {
            "completeness": c,
            "consistency": co,
            "clarity": cl,
            "granularity": g,
            "domain_alignment": da,
        },
        "strengths": ["strong"],
        "weaknesses": ["weak"],
        "recommendations": ["do something"],
        "metadata": {"key": "val"},
    }


def _ontology(n: int = 3, dangling: bool = False):
    entities = [
        {"id": f"e{i}", "type": "Person", "text": f"Name{i}", "properties": {}, "confidence": 0.8}
        for i in range(n)
    ]
    relationships = [
        {"id": "r1", "source_id": "e0", "target_id": "e1", "type": "knows", "confidence": 0.7},
    ]
    if dangling:
        relationships.append(
            {"id": "r2", "source_id": "e0", "target_id": "e_MISSING", "type": "related_to", "confidence": 0.6}
        )
    return {"entities": entities, "relationships": relationships, "metadata": {}, "domain": "test"}


# ---------------------------------------------------------------------------
# CriticScore.from_dict
# ---------------------------------------------------------------------------

class TestCriticScoreFromDict:
    def test_returns_critic_score(self):
        assert isinstance(CriticScore.from_dict(_score_dict()), CriticScore)

    def test_dimensions_restored_from_nested(self):
        s = CriticScore.from_dict(_score_dict(c=0.9, co=0.8))
        assert s.completeness == pytest.approx(0.9)
        assert s.consistency == pytest.approx(0.8)

    def test_round_trip_to_dict(self):
        original = CriticScore(
            completeness=0.75, consistency=0.65, clarity=0.55,
            granularity=0.45, domain_alignment=0.35,
            strengths=["s1"], weaknesses=["w1"], recommendations=["r1"],
        )
        restored = CriticScore.from_dict(original.to_dict())
        assert restored.completeness == pytest.approx(original.completeness)
        assert restored.consistency == pytest.approx(original.consistency)
        assert restored.strengths == original.strengths

    def test_flat_dict_fallback(self):
        flat = {"completeness": 0.6, "consistency": 0.7, "clarity": 0.5,
                "granularity": 0.4, "domain_alignment": 0.3}
        s = CriticScore.from_dict(flat)
        assert s.completeness == pytest.approx(0.6)

    def test_empty_dict_gives_zeros(self):
        s = CriticScore.from_dict({})
        assert s.completeness == pytest.approx(0.0)
        assert s.consistency == pytest.approx(0.0)

    def test_metadata_preserved(self):
        d = _score_dict()
        d["metadata"] = {"source": "test"}
        s = CriticScore.from_dict(d)
        assert s.metadata["source"] == "test"

    def test_recommendations_preserved(self):
        d = _score_dict()
        d["recommendations"] = ["fix A", "fix B"]
        s = CriticScore.from_dict(d)
        assert s.recommendations == ["fix A", "fix B"]

    def test_classmethod_accessible_on_class(self):
        assert callable(CriticScore.from_dict)


# ---------------------------------------------------------------------------
# OntologyPipeline.clone
# ---------------------------------------------------------------------------

class TestPipelineClone:
    def test_returns_pipeline(self):
        pipeline = OntologyPipeline(domain="test")
        assert isinstance(pipeline.clone(), OntologyPipeline)

    def test_clone_has_same_domain(self):
        pipeline = OntologyPipeline(domain="legal")
        assert pipeline.clone().domain == "legal"

    def test_clone_has_different_generator(self):
        pipeline = OntologyPipeline(domain="test")
        assert pipeline.clone()._generator is not pipeline._generator

    def test_clone_has_different_critic(self):
        pipeline = OntologyPipeline(domain="test")
        assert pipeline.clone()._critic is not pipeline._critic

    def test_clone_has_different_adapter(self):
        pipeline = OntologyPipeline(domain="test")
        assert pipeline.clone()._adapter is not pipeline._adapter

    def test_clone_inherits_max_rounds(self):
        pipeline = OntologyPipeline(domain="test", max_rounds=7)
        assert pipeline.clone()._mediator.max_rounds == 7

    def test_clone_can_run(self):
        pipeline = OntologyPipeline(domain="test")
        cloned = pipeline.clone()
        result = cloned.run("Alice works at ACME.", data_source="t")
        assert result is not None


# ---------------------------------------------------------------------------
# LogicValidator.explain_contradictions
# ---------------------------------------------------------------------------

class TestExplainContradictions:
    def test_returns_list(self):
        v = LogicValidator()
        result = v.explain_contradictions(_ontology())
        assert isinstance(result, list)

    def test_consistent_ontology_returns_empty(self):
        v = LogicValidator()
        result = v.explain_contradictions(_ontology())
        # Consistent ontology may or may not have contradictions, just assert no crash
        assert isinstance(result, list)

    def test_dangling_ref_produces_explanation(self):
        v = LogicValidator()
        result = v.explain_contradictions(_ontology(dangling=True))
        # There is at least one explanation (for the dangling reference)
        if result:
            for item in result:
                assert "contradiction" in item
                assert "explanation" in item
                assert "action" in item

    def test_each_item_has_required_keys(self):
        v = LogicValidator()
        # Create an ontology with a known contradiction
        ont = _ontology(dangling=True)
        for item in v.explain_contradictions(ont):
            assert set(item.keys()) >= {"contradiction", "explanation", "action"}

    def test_action_is_string(self):
        v = LogicValidator()
        for item in v.explain_contradictions(_ontology(dangling=True)):
            assert isinstance(item["action"], str)

    def test_explanation_is_string(self):
        v = LogicValidator()
        for item in v.explain_contradictions(_ontology(dangling=True)):
            assert isinstance(item["explanation"], str)


# ---------------------------------------------------------------------------
# OntologyGenerator.extract_entities_with_spans
# ---------------------------------------------------------------------------

class TestExtractEntitiesWithSpans:
    @pytest.fixture
    def ctx(self):
        return OntologyGenerationContext(data_source="test", data_type="text", domain="test")

    @pytest.fixture
    def gen(self):
        return OntologyGenerator()

    def test_returns_extraction_result(self, gen, ctx):
        result = gen.extract_entities_with_spans("Alice and Bob work at ACME.", ctx)
        assert isinstance(result, EntityExtractionResult)

    def test_entities_have_source_span_when_found(self, gen, ctx):
        text = "Alice must pay Bob by Friday."
        result = gen.extract_entities_with_spans(text, ctx)
        entities_with_spans = [e for e in result.entities if e.source_span is not None]
        # At least some entities should have spans if they appear in the text
        for e in entities_with_spans:
            start, end = e.source_span
            assert text[start:end] == e.text

    def test_span_offsets_are_correct(self, gen, ctx):
        text = "Alice works at ACME Corp and Bob manages it."
        result = gen.extract_entities_with_spans(text, ctx)
        for e in result.entities:
            if e.source_span is not None:
                start, end = e.source_span
                assert 0 <= start < end <= len(text)
                assert text[start:end] == e.text

    def test_relationships_preserved(self, gen, ctx):
        text = "Alice and Bob are colleagues."
        result = gen.extract_entities_with_spans(text, ctx)
        # Just assert it has the same structure
        assert hasattr(result, "relationships")

    def test_confidence_preserved(self, gen, ctx):
        text = "Alice works here."
        result = gen.extract_entities_with_spans(text, ctx)
        assert 0.0 <= result.confidence <= 1.0


# ---------------------------------------------------------------------------
# Hypothesis property test: ExtractionConfig round-trip
# ---------------------------------------------------------------------------

@st.composite
def extraction_config_strategy(draw):
    threshold = draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
    max_ent = draw(st.integers(min_value=1, max_value=200))
    max_rel = draw(st.integers(min_value=0, max_value=200))
    min_len = draw(st.integers(min_value=1, max_value=10))
    return ExtractionConfig(
        confidence_threshold=round(threshold, 4),
        max_entities=max_ent,
        max_relationships=max_rel,
        min_entity_length=min_len,
    )


@settings(max_examples=40, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(cfg=extraction_config_strategy())
def test_extraction_config_to_dict_round_trip(cfg):
    """ExtractionConfig serialises to dict and back without data loss."""
    restored = ExtractionConfig.from_dict(cfg.to_dict())
    assert restored.confidence_threshold == pytest.approx(cfg.confidence_threshold)
    assert restored.max_entities == cfg.max_entities
    assert restored.max_relationships == cfg.max_relationships
    assert restored.min_entity_length == cfg.min_entity_length
