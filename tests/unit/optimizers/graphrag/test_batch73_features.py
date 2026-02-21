"""Batch-73 feature tests.

Covers:
- OntologyCritic.compare_batch(ontologies, ctx)
- OntologyCritic.weighted_overall(score, weights)
- OntologyPipeline.clone_with(domain, max_rounds, use_llm)
- OntologyPipeline.get_stage_names()
- ExtractionConfig.validate()
"""

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    ExtractionConfig,
    OntologyGenerationContext,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic, CriticScore
from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ctx():
    return OntologyGenerationContext(
        data_source="test", data_type="text", domain="general"
    )


def _ont(n=2):
    return {
        "entities": [{"id": f"e{i}", "type": "Person", "text": f"Alice{i}"} for i in range(n)],
        "relationships": [],
    }


def _score(**overrides):
    defaults = dict(
        completeness=0.7, consistency=0.8, clarity=0.6, granularity=0.5, relationship_coherence=0.9
    , domain_alignment=0.9
    )
    defaults.update(overrides)
    return CriticScore(**defaults)


# ---------------------------------------------------------------------------
# OntologyCritic.compare_batch
# ---------------------------------------------------------------------------

class TestCompareBatch:
    def test_returns_list(self):
        critic = OntologyCritic(use_llm=False)
        result = critic.compare_batch([_ont(), _ont(3)], _ctx())
        assert isinstance(result, list)

    def test_length_matches(self):
        critic = OntologyCritic(use_llm=False)
        assert len(critic.compare_batch([_ont(), _ont(), _ont()], _ctx())) == 3

    def test_empty_batch(self):
        critic = OntologyCritic(use_llm=False)
        assert critic.compare_batch([], _ctx()) == []

    def test_rank_starts_at_one(self):
        critic = OntologyCritic(use_llm=False)
        ranked = critic.compare_batch([_ont()], _ctx())
        assert ranked[0]["rank"] == 1

    def test_has_required_keys(self):
        critic = OntologyCritic(use_llm=False)
        entry = critic.compare_batch([_ont()], _ctx())[0]
        for key in ("rank", "index", "overall", "completeness", "consistency"):
            assert key in entry

    def test_sorted_desc_by_overall(self):
        critic = OntologyCritic(use_llm=False)
        ranked = critic.compare_batch([_ont(0), _ont(5)], _ctx())
        assert ranked[0]["overall"] >= ranked[1]["overall"]

    def test_index_preserved(self):
        critic = OntologyCritic(use_llm=False)
        ranked = critic.compare_batch([_ont(1), _ont(1)], _ctx())
        indices = {e["index"] for e in ranked}
        assert indices == {0, 1}


# ---------------------------------------------------------------------------
# OntologyCritic.weighted_overall
# ---------------------------------------------------------------------------

class TestWeightedOverall:
    def test_returns_float(self):
        critic = OntologyCritic(use_llm=False)
        assert isinstance(critic.weighted_overall(_score()), float)

    def test_default_weights(self):
        critic = OntologyCritic(use_llm=False)
        # With default weights should be close to score.overall
        s = _score()
        val = critic.weighted_overall(s)
        assert abs(val - s.overall) < 1e-6

    def test_single_dimension_weight(self):
        critic = OntologyCritic(use_llm=False)
        s = _score(completeness=0.8)
        val = critic.weighted_overall(s, {"completeness": 1.0})
        assert abs(val - 0.8) < 1e-6

    def test_zero_weights_raise(self):
        critic = OntologyCritic(use_llm=False)
        with pytest.raises(ValueError):
            critic.weighted_overall(_score(), {})

    def test_result_in_range(self):
        critic = OntologyCritic(use_llm=False)
        val = critic.weighted_overall(_score(), {"completeness": 0.5, "consistency": 0.5})
        assert 0.0 <= val <= 1.0

    def test_weights_normalised(self):
        critic = OntologyCritic(use_llm=False)
        s = _score(completeness=1.0, consistency=0.0)
        # 100-weight vs 1-weight on completeness: result ~= 1.0
        val = critic.weighted_overall(s, {"completeness": 100.0, "consistency": 1.0})
        assert val > 0.9


# ---------------------------------------------------------------------------
# OntologyPipeline.clone_with
# ---------------------------------------------------------------------------

class TestCloneWith:
    def test_returns_pipeline(self):
        p = OntologyPipeline(domain="legal")
        assert isinstance(p.clone_with(), OntologyPipeline)

    def test_different_object(self):
        p = OntologyPipeline()
        assert p.clone_with() is not p

    def test_domain_override(self):
        p = OntologyPipeline(domain="medical")
        clone = p.clone_with(domain="legal")
        assert clone.domain == "legal"

    def test_max_rounds_override(self):
        p = OntologyPipeline(max_rounds=3)
        clone = p.clone_with(max_rounds=7)
        assert clone.as_dict()["max_rounds"] == 7

    def test_original_unchanged(self):
        p = OntologyPipeline(domain="original", max_rounds=2)
        p.clone_with(domain="new", max_rounds=5)
        assert p.domain == "original"
        assert p.as_dict()["max_rounds"] == 2

    def test_unspecified_fields_inherited(self):
        p = OntologyPipeline(domain="science", max_rounds=4)
        clone = p.clone_with(domain="art")
        assert clone.as_dict()["max_rounds"] == 4


# ---------------------------------------------------------------------------
# OntologyPipeline.get_stage_names
# ---------------------------------------------------------------------------

class TestGetStageNames:
    def test_returns_list(self):
        assert isinstance(OntologyPipeline().get_stage_names(), list)

    def test_nonempty(self):
        assert len(OntologyPipeline().get_stage_names()) > 0

    def test_all_strings(self):
        for s in OntologyPipeline().get_stage_names():
            assert isinstance(s, str)

    def test_contains_extraction(self):
        assert "extraction" in OntologyPipeline().get_stage_names()

    def test_contains_evaluation(self):
        assert "evaluation" in OntologyPipeline().get_stage_names()


# ---------------------------------------------------------------------------
# ExtractionConfig.validate
# ---------------------------------------------------------------------------

class TestExtractionConfigValidate:
    def test_default_config_valid(self):
        ExtractionConfig().validate()  # should not raise

    def test_bad_confidence_threshold(self):
        cfg = ExtractionConfig(confidence_threshold=1.5)
        with pytest.raises(ValueError, match="confidence_threshold"):
            cfg.validate()

    def test_negative_threshold(self):
        cfg = ExtractionConfig(confidence_threshold=-0.1)
        with pytest.raises(ValueError, match="confidence_threshold"):
            cfg.validate()

    def test_max_confidence_below_threshold(self):
        cfg = ExtractionConfig(confidence_threshold=0.9, max_confidence=0.5)
        with pytest.raises(ValueError):
            cfg.validate()

    def test_bad_min_entity_length(self):
        cfg = ExtractionConfig(min_entity_length=0)
        with pytest.raises(ValueError, match="min_entity_length"):
            cfg.validate()

    def test_returns_none_on_valid(self):
        result = ExtractionConfig().validate()
        assert result is None

    def test_max_confidence_zero_invalid(self):
        cfg = ExtractionConfig(max_confidence=0.0)
        with pytest.raises(ValueError, match="max_confidence"):
            cfg.validate()
