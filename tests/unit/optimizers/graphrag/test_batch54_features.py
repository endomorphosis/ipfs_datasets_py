"""Batch 54 tests.

Covers:
- ExtractionConfig.from_env()
- OntologyCritic.explain_score()
- LogicValidator.suggest_fixes_for_result()
- OntologyLearningAdapter.serialize() / deserialize()
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# ExtractionConfig.from_env()
# ──────────────────────────────────────────────────────────────────────────────

class TestExtractionConfigFromEnv:
    """from_env() should populate fields from environment variables."""

    @pytest.fixture(autouse=True)
    def clean_env(self, monkeypatch):
        # Remove any lingering env vars before each test
        keys = [
            "EXTRACTION_CONFIDENCE_THRESHOLD",
            "EXTRACTION_MAX_ENTITIES",
            "EXTRACTION_MAX_RELATIONSHIPS",
            "EXTRACTION_WINDOW_SIZE",
            "EXTRACTION_INCLUDE_PROPERTIES",
            "EXTRACTION_LLM_FALLBACK_THRESHOLD",
            "EXTRACTION_MIN_ENTITY_LENGTH",
            "EXTRACTION_MAX_CONFIDENCE",
        ]
        for k in keys:
            monkeypatch.delenv(k, raising=False)

    def test_defaults_without_env(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
        cfg = ExtractionConfig.from_env()
        default = ExtractionConfig()
        assert cfg.confidence_threshold == default.confidence_threshold
        assert cfg.max_entities == default.max_entities

    def test_confidence_threshold_from_env(self, monkeypatch):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
        monkeypatch.setenv("EXTRACTION_CONFIDENCE_THRESHOLD", "0.75")
        cfg = ExtractionConfig.from_env()
        assert cfg.confidence_threshold == 0.75

    def test_max_entities_from_env(self, monkeypatch):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
        monkeypatch.setenv("EXTRACTION_MAX_ENTITIES", "42")
        cfg = ExtractionConfig.from_env()
        assert cfg.max_entities == 42

    def test_include_properties_false_from_env(self, monkeypatch):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
        monkeypatch.setenv("EXTRACTION_INCLUDE_PROPERTIES", "false")
        cfg = ExtractionConfig.from_env()
        assert cfg.include_properties is False

    def test_include_properties_true_from_env(self, monkeypatch):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
        monkeypatch.setenv("EXTRACTION_INCLUDE_PROPERTIES", "true")
        cfg = ExtractionConfig.from_env()
        assert cfg.include_properties is True

    def test_custom_prefix(self, monkeypatch):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
        monkeypatch.setenv("MY_CONFIDENCE_THRESHOLD", "0.9")
        cfg = ExtractionConfig.from_env(prefix="MY_")
        assert cfg.confidence_threshold == 0.9

    def test_max_confidence_from_env(self, monkeypatch):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
        monkeypatch.setenv("EXTRACTION_MAX_CONFIDENCE", "0.8")
        cfg = ExtractionConfig.from_env()
        assert cfg.max_confidence == 0.8

    def test_window_size_from_env(self, monkeypatch):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
        monkeypatch.setenv("EXTRACTION_WINDOW_SIZE", "10")
        cfg = ExtractionConfig.from_env()
        assert cfg.window_size == 10


# ──────────────────────────────────────────────────────────────────────────────
# OntologyCritic.explain_score()
# ──────────────────────────────────────────────────────────────────────────────

class TestExplainScore:
    """explain_score() should return one explanation per dimension."""

    @pytest.fixture
    def critic(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
        return OntologyCritic(use_llm=False)

    @pytest.fixture
    def high_score(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
        return CriticScore(
            completeness=0.9, consistency=0.9, clarity=0.9,
            granularity=0.9, relationship_coherence=0.9
        , domain_alignment=0.9
        )

    @pytest.fixture
    def low_score(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
        return CriticScore(
            completeness=0.2, consistency=0.2, clarity=0.2,
            granularity=0.2, relationship_coherence=0.2
        , domain_alignment=0.2
        )

    def test_returns_dict_with_all_dimensions(self, critic, high_score):
        explanations = critic.explain_score(high_score)
        for dim in ("completeness", "consistency", "clarity", "granularity",
                    "domain_alignment", "overall"):
            assert dim in explanations

    def test_high_score_uses_positive_language(self, critic, high_score):
        explanations = critic.explain_score(high_score)
        assert any(w in explanations["completeness"] for w in ("excellent", "most expected"))

    def test_low_score_uses_improvement_language(self, critic, low_score):
        explanations = critic.explain_score(low_score)
        assert any(w in explanations["completeness"] for w in ("missing", "poor", "weak"))

    def test_all_explanations_are_strings(self, critic, high_score):
        explanations = critic.explain_score(high_score)
        for val in explanations.values():
            assert isinstance(val, str)
            assert len(val) > 10

    def test_explanation_contains_percentage(self, critic, high_score):
        explanations = critic.explain_score(high_score)
        assert "%" in explanations["completeness"]

    def test_overall_positive_when_high_scores(self, critic, high_score):
        explanations = critic.explain_score(high_score)
        assert "ready" in explanations["overall"] or "excellent" in explanations["overall"]

    def test_overall_suggests_refinement_when_low(self, critic, low_score):
        explanations = critic.explain_score(low_score)
        assert "refinement" in explanations["overall"] or "recommended" in explanations["overall"]


# ──────────────────────────────────────────────────────────────────────────────
# LogicValidator.suggest_fixes_for_result()
# ──────────────────────────────────────────────────────────────────────────────

class TestSuggestFixesForResult:
    """suggest_fixes_for_result() should combine contradiction + dangling ID hints."""

    @pytest.fixture
    def validator(self):
        from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
        return LogicValidator(use_cache=False)

    @pytest.fixture
    def ontology(self):
        return {
            "entities": [{"id": "e1", "text": "Alice", "type": "Person"}],
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "MISSING", "type": "knows"},
            ],
        }

    def test_returns_list(self, validator, ontology):
        result = validator._basic_consistency_check(ontology)
        fixes = validator.suggest_fixes_for_result(ontology, result)
        assert isinstance(fixes, list)

    def test_fix_includes_dangling_id(self, validator, ontology):
        result = validator._basic_consistency_check(ontology)
        fixes = validator.suggest_fixes_for_result(ontology, result)
        targets = [f.get("target") for f in fixes]
        assert "MISSING" in targets

    def test_fix_type_for_dangling_id(self, validator, ontology):
        result = validator._basic_consistency_check(ontology)
        fixes = validator.suggest_fixes_for_result(ontology, result)
        for f in fixes:
            if f.get("target") == "MISSING":
                assert f["type"] == "add_entity_or_remove_relationship"

    def test_no_fixes_for_consistent_ontology(self, validator):
        good_ontology = {
            "entities": [{"id": "e1", "text": "Alice", "type": "Person"}],
            "relationships": [],
        }
        result = validator._basic_consistency_check(good_ontology)
        fixes = validator.suggest_fixes_for_result(good_ontology, result)
        assert fixes == []

    def test_all_fixes_have_required_keys(self, validator, ontology):
        result = validator._basic_consistency_check(ontology)
        fixes = validator.suggest_fixes_for_result(ontology, result)
        for fix in fixes:
            assert "description" in fix
            assert "type" in fix
            assert "target" in fix
            assert "confidence" in fix


# ──────────────────────────────────────────────────────────────────────────────
# OntologyLearningAdapter.serialize() / deserialize()
# ──────────────────────────────────────────────────────────────────────────────

class TestAdapterSerializeDeserialize:
    """serialize()/deserialize() should round-trip adapter state as bytes."""

    @pytest.fixture
    def adapter_with_feedback(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import (
            OntologyLearningAdapter,
        )
        a = OntologyLearningAdapter(domain="legal", base_threshold=0.6)
        for score in [0.8, 0.7, 0.9, 0.75]:
            a.apply_feedback(final_score=score, actions=[{"action": "merge_duplicates"}])
        return a

    def test_serialize_returns_bytes(self, adapter_with_feedback):
        data = adapter_with_feedback.serialize()
        assert isinstance(data, bytes)

    def test_serialize_is_valid_json(self, adapter_with_feedback):
        import json
        data = adapter_with_feedback.serialize()
        parsed = json.loads(data)
        assert isinstance(parsed, dict)

    def test_round_trip_domain(self, adapter_with_feedback):
        from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import (
            OntologyLearningAdapter,
        )
        data = adapter_with_feedback.serialize()
        restored = OntologyLearningAdapter.deserialize(data)
        assert restored.domain == "legal"

    def test_round_trip_threshold(self, adapter_with_feedback):
        from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import (
            OntologyLearningAdapter,
        )
        data = adapter_with_feedback.serialize()
        restored = OntologyLearningAdapter.deserialize(data)
        assert abs(restored._current_threshold - adapter_with_feedback._current_threshold) < 1e-9

    def test_round_trip_feedback_count(self, adapter_with_feedback):
        from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import (
            OntologyLearningAdapter,
        )
        data = adapter_with_feedback.serialize()
        restored = OntologyLearningAdapter.deserialize(data)
        assert len(restored._feedback) == len(adapter_with_feedback._feedback)

    def test_round_trip_action_counts(self, adapter_with_feedback):
        from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import (
            OntologyLearningAdapter,
        )
        data = adapter_with_feedback.serialize()
        restored = OntologyLearningAdapter.deserialize(data)
        assert restored._action_count == dict(adapter_with_feedback._action_count)

    def test_empty_adapter_serializes(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import (
            OntologyLearningAdapter,
        )
        a = OntologyLearningAdapter()
        data = a.serialize()
        restored = OntologyLearningAdapter.deserialize(data)
        assert restored.domain == a.domain
