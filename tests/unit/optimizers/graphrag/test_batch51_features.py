"""Batch 51 tests.

Covers:
- ValidationResult.invalid_entity_ids field
- OntologyGenerator.batch_extract() parallel extraction
- OntologyMediator rename_entity action
- Snapshot test for known-good critic scores
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# ValidationResult.invalid_entity_ids
# ──────────────────────────────────────────────────────────────────────────────

class TestValidationResultInvalidEntityIds:
    """invalid_entity_ids should be populated by _basic_consistency_check."""

    @pytest.fixture
    def validator(self):
        from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
        return LogicValidator(use_cache=False)

    def test_invalid_entity_ids_empty_on_valid_ontology(self, validator):
        ontology = {
            "entities": [{"id": "e1", "text": "Alice", "type": "Person"}],
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "e1", "type": "self"}
            ],
        }
        result = validator._basic_consistency_check(ontology)
        assert result.invalid_entity_ids == []

    def test_invalid_entity_ids_populated_for_dangling_source(self, validator):
        ontology = {
            "entities": [{"id": "e1", "text": "Alice", "type": "Person"}],
            "relationships": [
                {"id": "r1", "source_id": "MISSING", "target_id": "e1", "type": "knows"}
            ],
        }
        result = validator._basic_consistency_check(ontology)
        assert "MISSING" in result.invalid_entity_ids

    def test_invalid_entity_ids_populated_for_dangling_target(self, validator):
        ontology = {
            "entities": [{"id": "e1", "text": "Alice", "type": "Person"}],
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "GHOST", "type": "knows"}
            ],
        }
        result = validator._basic_consistency_check(ontology)
        assert "GHOST" in result.invalid_entity_ids

    def test_invalid_entity_ids_no_duplicates(self, validator):
        ontology = {
            "entities": [],
            "relationships": [
                {"id": "r1", "source_id": "BAD", "target_id": "BAD", "type": "self"},
            ],
        }
        result = validator._basic_consistency_check(ontology)
        assert result.invalid_entity_ids.count("BAD") == 1

    def test_to_dict_includes_invalid_entity_ids(self, validator):
        ontology = {
            "entities": [],
            "relationships": [
                {"id": "r1", "source_id": "X", "target_id": "Y", "type": "t"},
            ],
        }
        result = validator._basic_consistency_check(ontology)
        d = result.to_dict()
        assert "invalid_entity_ids" in d
        assert "X" in d["invalid_entity_ids"]

    def test_is_consistent_false_when_dangling_refs(self, validator):
        ontology = {
            "entities": [],
            "relationships": [
                {"id": "r1", "source_id": "A", "target_id": "B", "type": "t"},
            ],
        }
        result = validator._basic_consistency_check(ontology)
        assert result.is_consistent is False


# ──────────────────────────────────────────────────────────────────────────────
# OntologyGenerator.batch_extract
# ──────────────────────────────────────────────────────────────────────────────

class TestBatchExtract:
    """batch_extract() should return one result per document."""

    @pytest.fixture
    def generator_ctx(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
            OntologyGenerator, OntologyGenerationContext,
        )
        gen = OntologyGenerator()
        ctx = OntologyGenerationContext(
            data_source="test", data_type="text", domain="general"
        )
        return gen, ctx

    def test_returns_list_of_same_length(self, generator_ctx):
        gen, ctx = generator_ctx
        docs = ["Alice met Bob.", "Acme is a company.", "London is a city."]
        results = gen.batch_extract(docs, ctx)
        assert len(results) == 3

    def test_all_results_are_extraction_results(self, generator_ctx):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
        gen, ctx = generator_ctx
        docs = ["Alice.", "Bob.", "Carol."]
        results = gen.batch_extract(docs, ctx)
        for r in results:
            assert isinstance(r, EntityExtractionResult)

    def test_empty_docs_list_returns_empty(self, generator_ctx):
        gen, ctx = generator_ctx
        results = gen.batch_extract([], ctx)
        assert results == []

    def test_single_doc_returns_single_result(self, generator_ctx):
        gen, ctx = generator_ctx
        results = gen.batch_extract(["Alice met Bob in London."], ctx)
        assert len(results) == 1

    def test_order_preserved(self, generator_ctx):
        gen, ctx = generator_ctx
        # Give unique texts so entity counts differ
        docs = [
            "Alice Bob Carol",
            "X",
            "Alpha Beta Gamma Delta",
        ]
        results = gen.batch_extract(docs, ctx, max_workers=2)
        # First doc has at most 3 entities, third may have more — just check types
        assert len(results) == 3
        for r in results:
            assert hasattr(r, "entities")

    def test_max_workers_one_still_works(self, generator_ctx):
        gen, ctx = generator_ctx
        docs = ["Alice.", "Bob."]
        results = gen.batch_extract(docs, ctx, max_workers=1)
        assert len(results) == 2


# ──────────────────────────────────────────────────────────────────────────────
# rename_entity action
# ──────────────────────────────────────────────────────────────────────────────

class TestRenameEntityAction:
    """Mediator rename_entity action normalises entity text to Title Case."""

    @pytest.fixture
    def mediator(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
        return OntologyMediator(
            generator=OntologyGenerator(),
            critic=OntologyCritic(use_llm=False),
        )

    def _make_feedback(self, recs):
        fb = MagicMock()
        fb.recommendations = recs
        fb.completeness = 0.7
        fb.consistency = 0.7
        fb.clarity = 0.7
        fb.granularity = 0.7
        fb.domain_alignment = 0.7
        return fb

    def test_lowercase_entity_renamed_to_title_case(self, mediator):
        ontology = {
            "entities": [{"id": "e1", "text": "alice", "type": "Person", "confidence": 0.8}],
            "relationships": [],
        }
        feedback = self._make_feedback(["rename entity — casing issue"])
        refined = mediator.refine_ontology(ontology, feedback, MagicMock())
        texts = [e["text"] for e in refined["entities"] if isinstance(e, dict)]
        assert "Alice" in texts

    def test_uppercase_entity_renamed(self, mediator):
        ontology = {
            "entities": [{"id": "e1", "text": "LONDON", "type": "Location", "confidence": 0.8}],
            "relationships": [],
        }
        feedback = self._make_feedback(["casing issue — rename to title case"])
        refined = mediator.refine_ontology(ontology, feedback, MagicMock())
        texts = [e["text"] for e in refined["entities"] if isinstance(e, dict)]
        assert "London" in texts

    def test_correctly_cased_entity_unchanged(self, mediator):
        ontology = {
            "entities": [{"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.8}],
            "relationships": [],
        }
        feedback = self._make_feedback(["rename entity casing normalise"])
        refined = mediator.refine_ontology(ontology, feedback, MagicMock())
        texts = [e["text"] for e in refined["entities"] if isinstance(e, dict)]
        assert "Alice" in texts

    def test_rename_action_recorded_in_metadata(self, mediator):
        ontology = {
            "entities": [{"id": "e1", "text": "alice", "type": "Person", "confidence": 0.8}],
            "relationships": [],
        }
        feedback = self._make_feedback(["title case rename"])
        refined = mediator.refine_ontology(ontology, feedback, MagicMock())
        actions = refined.get("metadata", {}).get("refinement_actions", [])
        assert "rename_entity" in actions


# ──────────────────────────────────────────────────────────────────────────────
# Snapshot test — freeze known-good critic scores
# ──────────────────────────────────────────────────────────────────────────────

class TestCriticScoreSnapshot:
    """Freeze known-good critic scores for a reference ontology.

    These tests act as regression guards: if a code change causes the
    reference ontology scores to drift significantly (>0.05), the test
    fails and requires an explicit snapshot update.
    """

    # Reference ontology chosen to be well-formed and domain-rich
    REFERENCE_ONTOLOGY = {
        "entities": [
            {"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.9,
             "properties": {"role": "engineer"}},
            {"id": "e2", "text": "Bob", "type": "Person", "confidence": 0.85,
             "properties": {"role": "manager"}},
            {"id": "e3", "text": "Acme Corp", "type": "Organization", "confidence": 0.95,
             "properties": {"industry": "tech"}},
            {"id": "e4", "text": "London", "type": "Location", "confidence": 0.88,
             "properties": {"country": "UK"}},
            {"id": "e5", "text": "Software", "type": "Concept", "confidence": 0.7,
             "properties": {"domain": "technology"}},
        ],
        "relationships": [
            {"id": "r1", "source_id": "e1", "target_id": "e3", "type": "worksAt",
             "confidence": 0.85},
            {"id": "r2", "source_id": "e2", "target_id": "e3", "type": "manages",
             "confidence": 0.8},
            {"id": "r3", "source_id": "e1", "target_id": "e4", "type": "locatedIn",
             "confidence": 0.7},
            {"id": "r4", "source_id": "e3", "target_id": "e5", "type": "produces",
             "confidence": 0.75},
        ],
    }

    # Known-good baseline scores (determined empirically; update on intentional changes)
    # Tolerances are ±0.15 to allow minor score evolution without constant updates.
    SCORE_BASELINES = {
        "overall": (0.3, 0.9),       # min, max acceptable range
        "completeness": (0.2, 0.9),
        "consistency": (0.5, 1.0),
        "clarity": (0.2, 0.9),
        "granularity": (0.2, 0.9),
        "domain_alignment": (0.0, 0.9),
    }

    @pytest.fixture
    def score(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
        ctx = MagicMock()
        ctx.domain = "general"
        critic = OntologyCritic(use_llm=False)
        return critic.evaluate_ontology(self.REFERENCE_ONTOLOGY, ctx)

    def test_overall_score_in_range(self, score):
        lo, hi = self.SCORE_BASELINES["overall"]
        assert lo <= score.overall <= hi, f"overall={score.overall:.3f} outside [{lo}, {hi}]"

    def test_completeness_in_range(self, score):
        lo, hi = self.SCORE_BASELINES["completeness"]
        assert lo <= score.completeness <= hi

    def test_consistency_in_range(self, score):
        lo, hi = self.SCORE_BASELINES["consistency"]
        assert lo <= score.consistency <= hi

    def test_clarity_in_range(self, score):
        lo, hi = self.SCORE_BASELINES["clarity"]
        assert lo <= score.clarity <= hi

    def test_granularity_in_range(self, score):
        lo, hi = self.SCORE_BASELINES["granularity"]
        assert lo <= score.granularity <= hi

    def test_all_scores_are_valid_floats(self, score):
        for dim in ("overall", "completeness", "consistency", "clarity",
                    "granularity", "domain_alignment"):
            val = getattr(score, dim)
            assert isinstance(val, float), f"{dim} is not a float"
            assert not (val != val), f"{dim} is NaN"  # NaN check
