"""Unit tests for OntologyCritic dimension evaluators.

Tests boundary conditions for each of the five scoring dimensions:
completeness, consistency, clarity, granularity, domain_alignment.
"""

from __future__ import annotations

import pytest
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    OntologyGenerationContext,
    ExtractionStrategy,
    DataType,
)


@pytest.fixture
def critic():
    return OntologyCritic()


@pytest.fixture
def ctx():
    return OntologyGenerationContext(
        data_source="test",
        data_type=DataType.TEXT,
        domain="general",
        extraction_strategy=ExtractionStrategy.RULE_BASED,
    )


def _ents(n: int, type_cycle: list[str] | None = None, with_props: bool = False):
    types = type_cycle or ["Person", "Organization", "Concept"]
    return [
        {
            "id": f"e{i}",
            "type": types[i % len(types)],
            "text": f"entity{i}",
            "confidence": 0.8,
            **({"properties": {"k": "v"}} if with_props else {}),
        }
        for i in range(n)
    ]


def _rels(pairs: list[tuple[str, str, str]]):
    return [
        {"id": f"r{i}", "source_id": s, "target_id": t, "type": rtype}
        for i, (s, t, rtype) in enumerate(pairs)
    ]


# ──────────────────────────────────────────────────────────────────────────────
# Completeness
# ──────────────────────────────────────────────────────────────────────────────

class TestCompletenessEvaluator:
    def test_empty_ontology_returns_zero(self, critic, ctx):
        score = critic._evaluate_completeness({}, ctx, None)
        assert score == 0.0

    def test_single_entity_no_rels_is_low(self, critic, ctx):
        ontology = {"entities": _ents(1), "relationships": []}
        score = critic._evaluate_completeness(ontology, ctx, None)
        assert score < 0.5

    def test_ten_entities_with_dense_rels_is_high(self, critic, ctx):
        ents = _ents(10)
        pairs = [(ents[i]["id"], ents[(i + 1) % 10]["id"], "related_to") for i in range(10)]
        ontology = {"entities": ents, "relationships": _rels(pairs)}
        score = critic._evaluate_completeness(ontology, ctx, None)
        assert score >= 0.7

    def test_orphan_entities_penalise_score(self, critic, ctx):
        ents = _ents(10)
        # Only link first two entities
        ontology = {
            "entities": ents,
            "relationships": _rels([(ents[0]["id"], ents[1]["id"], "related_to")]),
        }
        score_orphans = critic._evaluate_completeness(ontology, ctx, None)
        # All linked
        pairs = [(ents[i]["id"], ents[(i + 1) % 10]["id"], "related_to") for i in range(10)]
        ontology_full = {"entities": ents, "relationships": _rels(pairs)}
        score_full = critic._evaluate_completeness(ontology_full, ctx, None)
        assert score_full > score_orphans

    def test_score_in_range(self, critic, ctx):
        ents = _ents(5)
        ontology = {"entities": ents, "relationships": []}
        score = critic._evaluate_completeness(ontology, ctx, None)
        assert 0.0 <= score <= 1.0


# ──────────────────────────────────────────────────────────────────────────────
# Consistency
# ──────────────────────────────────────────────────────────────────────────────

class TestConsistencyEvaluator:
    def test_empty_ontology_is_perfect(self, critic, ctx):
        score = critic._evaluate_consistency({}, ctx)
        assert score == 1.0

    def test_valid_refs_give_high_score(self, critic, ctx):
        ents = _ents(4)
        pairs = [(ents[0]["id"], ents[1]["id"], "related_to")]
        ontology = {"entities": ents, "relationships": _rels(pairs)}
        score = critic._evaluate_consistency(ontology, ctx)
        assert score >= 0.85

    def test_dangling_refs_penalise_score(self, critic, ctx):
        ents = _ents(2)
        bad_rels = [{"id": "r0", "source_id": "MISSING_1", "target_id": "MISSING_2", "type": "related_to"}]
        ontology = {"entities": ents, "relationships": bad_rels}
        score = critic._evaluate_consistency(ontology, ctx)
        assert score < 0.8

    def test_duplicate_ids_penalise_score(self, critic, ctx):
        ents = [
            {"id": "e0", "type": "Person", "text": "Alice"},
            {"id": "e0", "type": "Person", "text": "Bob"},  # duplicate
        ]
        ontology = {"entities": ents, "relationships": []}
        score = critic._evaluate_consistency(ontology, ctx)
        assert score < 1.0

    def test_cycle_penalises_score(self, critic, ctx):
        ents = _ents(3)
        # A is_a B is_a C is_a A
        cycle_rels = [
            {"id": "r0", "source_id": ents[0]["id"], "target_id": ents[1]["id"], "type": "is_a"},
            {"id": "r1", "source_id": ents[1]["id"], "target_id": ents[2]["id"], "type": "is_a"},
            {"id": "r2", "source_id": ents[2]["id"], "target_id": ents[0]["id"], "type": "is_a"},
        ]
        ontology_cycle = {"entities": ents, "relationships": cycle_rels}
        score_cycle = critic._evaluate_consistency(ontology_cycle, ctx)
        straight_rels = [
            {"id": "r0", "source_id": ents[0]["id"], "target_id": ents[1]["id"], "type": "is_a"},
            {"id": "r1", "source_id": ents[1]["id"], "target_id": ents[2]["id"], "type": "is_a"},
        ]
        ontology_straight = {"entities": ents, "relationships": straight_rels}
        score_straight = critic._evaluate_consistency(ontology_straight, ctx)
        assert score_straight > score_cycle

    def test_score_in_range(self, critic, ctx):
        ents = _ents(5)
        ontology = {"entities": ents, "relationships": []}
        score = critic._evaluate_consistency(ontology, ctx)
        assert 0.0 <= score <= 1.0


# ──────────────────────────────────────────────────────────────────────────────
# Clarity
# ──────────────────────────────────────────────────────────────────────────────

class TestClarityEvaluator:
    def test_empty_ontology_returns_zero(self, critic, ctx):
        score = critic._evaluate_clarity({}, ctx)
        assert score == 0.0

    def test_entities_with_props_and_text_is_high(self, critic, ctx):
        ents = [
            {"id": f"e{i}", "type": "Person", "text": f"alice{i}", "properties": {"age": 30}}
            for i in range(5)
        ]
        ontology = {"entities": ents}
        score = critic._evaluate_clarity(ontology, ctx)
        assert score >= 0.6

    def test_entities_without_props_or_text_is_low(self, critic, ctx):
        ents = [{"id": f"e{i}", "type": "X"} for i in range(5)]
        ontology = {"entities": ents}
        score = critic._evaluate_clarity(ontology, ctx)
        assert score < 0.4

    def test_score_in_range(self, critic, ctx):
        ents = _ents(5)
        ontology = {"entities": ents}
        score = critic._evaluate_clarity(ontology, ctx)
        assert 0.0 <= score <= 1.0


# ──────────────────────────────────────────────────────────────────────────────
# Granularity
# ──────────────────────────────────────────────────────────────────────────────

class TestGranularityEvaluator:
    def test_empty_ontology_returns_zero(self, critic, ctx):
        score = critic._evaluate_granularity({}, ctx)
        assert score == 0.0

    def test_entities_with_many_props_score_high(self, critic, ctx):
        ents = [
            {"id": f"e{i}", "type": "X", "text": f"e{i}", "properties": {"a": 1, "b": 2, "c": 3, "d": 4}}
            for i in range(5)
        ]
        pairs = [(f"e{i}", f"e{(i + 1) % 5}", "related_to") for i in range(5)]
        ontology = {"entities": ents, "relationships": _rels(pairs)}
        score = critic._evaluate_granularity(ontology, ctx)
        assert score >= 0.7

    def test_entities_with_no_props_score_low(self, critic, ctx):
        ents = [{"id": f"e{i}", "type": "X", "text": f"e{i}"} for i in range(5)]
        ontology = {"entities": ents, "relationships": []}
        score = critic._evaluate_granularity(ontology, ctx)
        assert score < 0.4

    def test_score_in_range(self, critic, ctx):
        ents = _ents(5, with_props=True)
        ontology = {"entities": ents, "relationships": []}
        score = critic._evaluate_granularity(ontology, ctx)
        assert 0.0 <= score <= 1.0


# ──────────────────────────────────────────────────────────────────────────────
# Domain Alignment
# ──────────────────────────────────────────────────────────────────────────────

class TestDomainAlignmentEvaluator:
    def test_empty_entities_returns_half(self, critic, ctx):
        ontology = {"entities": [], "relationships": []}
        score = critic._evaluate_domain_alignment(ontology, ctx)
        assert score == 0.5

    def test_legal_domain_with_legal_types_scores_high(self, critic):
        legal_ctx = OntologyGenerationContext(
            data_source="test",
            data_type=DataType.TEXT,
            domain="legal",
            extraction_strategy=ExtractionStrategy.RULE_BASED,
        )
        ents = [
            {"id": "e0", "type": "party"},
            {"id": "e1", "type": "contract"},
            {"id": "e2", "type": "obligation"},
        ]
        rels = [{"id": "r0", "source_id": "e0", "target_id": "e1", "type": "agreement"}]
        ontology = {"entities": ents, "relationships": rels, "domain": "legal"}
        score = critic._evaluate_domain_alignment(ontology, legal_ctx)
        assert score >= 0.6

    def test_wrong_domain_types_score_low(self, critic):
        legal_ctx = OntologyGenerationContext(
            data_source="test",
            data_type=DataType.TEXT,
            domain="legal",
            extraction_strategy=ExtractionStrategy.RULE_BASED,
        )
        ents = [{"id": f"e{i}", "type": f"xyztype{i}"} for i in range(5)]
        ontology = {"entities": ents, "relationships": [], "domain": "legal"}
        score = critic._evaluate_domain_alignment(ontology, legal_ctx)
        assert score < 0.4

    def test_score_in_range(self, critic, ctx):
        ents = _ents(5)
        ontology = {"entities": ents, "relationships": [], "domain": "general"}
        score = critic._evaluate_domain_alignment(ontology, ctx)
        assert 0.0 <= score <= 1.0

    def test_unknown_domain_falls_back_to_general(self, critic):
        unknown_ctx = OntologyGenerationContext(
            data_source="test",
            data_type=DataType.TEXT,
            domain="unknown_xyz",
            extraction_strategy=ExtractionStrategy.RULE_BASED,
        )
        ents = [{"id": "e0", "type": "person"}, {"id": "e1", "type": "organization"}]
        ontology = {"entities": ents, "relationships": []}
        score = critic._evaluate_domain_alignment(ontology, unknown_ctx)
        assert 0.0 <= score <= 1.0


# ──────────────────────────────────────────────────────────────────────────────
# Full evaluate_ontology smoke test
# ──────────────────────────────────────────────────────────────────────────────

class TestEvaluateOntologySmoke:
    def test_full_evaluation_returns_score_in_range(self, critic, ctx):
        ents = _ents(6, with_props=True)
        pairs = [(ents[i]["id"], ents[(i + 1) % 6]["id"], "related_to") for i in range(6)]
        ontology = {"entities": ents, "relationships": _rels(pairs), "domain": "general"}
        result = critic.evaluate_ontology(ontology, ctx)
        assert 0.0 <= result.overall <= 1.0

    def test_full_evaluation_has_all_dimensions(self, critic, ctx):
        ontology = {"entities": _ents(3), "relationships": []}
        result = critic.evaluate_ontology(ontology, ctx)
        for dim in ("completeness", "consistency", "clarity", "granularity", "domain_alignment"):
            assert hasattr(result, dim), f"Missing dimension: {dim}"

    def test_evaluate_returns_critic_result(self, critic, ctx):
        from ipfs_datasets_py.optimizers.common import CriticResult
        ontology = {"entities": _ents(3), "relationships": []}
        result = critic.evaluate(ontology, ctx)
        assert isinstance(result, CriticResult)
        assert 0.0 <= result.score <= 1.0
        assert set(result.dimensions.keys()) == {
            "completeness", "consistency", "clarity", "granularity", "domain_alignment"
        }
