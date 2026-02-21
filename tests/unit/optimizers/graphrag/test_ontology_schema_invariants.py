"""Golden-file / schema-invariant tests for GraphRAG ontology dict structure.

These tests verify that every public entry-point that produces an ontology dict
emits a structure that satisfies the following invariants:

    1. Top-level keys include ``'entities'`` and ``'relationships'``.
    2. Every entity has ``'id'``, ``'type'``, and ``'text'`` string fields.
    3. Every relationship has ``'id'``, ``'source_id'``, ``'target_id'``, and
       ``'type'`` string fields.
    4. All entity IDs referenced by relationships exist in the entity set.
    5. No duplicate entity IDs (dedup guarantee from _merge_ontologies).
    6. OntologyGenerator.generate_ontology() returns a dict satisfying (1–4).
    7. OntologyMediator.refine_ontology() preserves (1–4) after refinement.
    8. OntologyCritic.evaluate_ontology() returns a CriticScore with 0.0–1.0
       per-dimension scores.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_context(domain: str = "legal"):
    ctx = MagicMock()
    ctx.domain = domain
    ctx.data_source = "test_doc"
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
        ExtractionStrategy, DataType, ExtractionConfig,
    )
    ctx.data_type = DataType.TEXT
    ctx.extraction_strategy = ExtractionStrategy.RULE_BASED
    ctx.config = ExtractionConfig()
    ctx.base_ontology = None
    return ctx


def _assert_entity_schema(entity: Dict[str, Any], idx: int) -> None:
    for key in ("id", "type", "text"):
        assert key in entity, f"Entity[{idx}] missing key '{key}'"
        assert isinstance(entity[key], str), (
            f"Entity[{idx}]['{key}'] must be str, got {type(entity[key])}"
        )
    assert entity["id"], f"Entity[{idx}]['id'] must not be empty"


def _assert_relationship_schema(rel: Dict[str, Any], idx: int) -> None:
    for key in ("id", "source_id", "target_id", "type"):
        assert key in rel, f"Relationship[{idx}] missing key '{key}'"
        assert isinstance(rel[key], str), (
            f"Relationship[{idx}]['{key}'] must be str, got {type(rel[key])}"
        )


def _assert_ontology_invariants(ontology: Dict[str, Any]) -> None:
    """Assert all schema invariants on an ontology dict."""
    assert "entities" in ontology, "ontology missing 'entities' key"
    assert "relationships" in ontology, "ontology missing 'relationships' key"
    assert isinstance(ontology["entities"], list)
    assert isinstance(ontology["relationships"], list)

    entity_ids: set = set()
    for i, ent in enumerate(ontology["entities"]):
        _assert_entity_schema(ent, i)
        entity_ids.add(ent["id"])

    # No duplicate entity IDs
    assert len(entity_ids) == len(ontology["entities"]), (
        "Duplicate entity IDs detected in ontology"
    )

    for i, rel in enumerate(ontology["relationships"]):
        _assert_relationship_schema(rel, i)
        assert rel["source_id"] in entity_ids, (
            f"Relationship[{i}] source_id '{rel['source_id']}' not in entity set"
        )
        assert rel["target_id"] in entity_ids, (
            f"Relationship[{i}] target_id '{rel['target_id']}' not in entity set"
        )


# ---------------------------------------------------------------------------
# Fixture ontologies
# ---------------------------------------------------------------------------

FIXTURE_TEXT = (
    "Alice must pay Bob the sum of $500 by 2025-12-31. "
    "Acme Corp is obligated to deliver the software. "
    "The agreement was signed in New York on 2024-01-15."
)

MINIMAL_VALID_ONTOLOGY = {
    "entities": [
        {"id": "e1", "type": "Person", "text": "Alice", "properties": {}, "confidence": 0.9},
        {"id": "e2", "type": "Person", "text": "Bob", "properties": {}, "confidence": 0.9},
    ],
    "relationships": [
        {
            "id": "r1", "type": "obligates",
            "source_id": "e1", "target_id": "e2",
            "properties": {}, "confidence": 0.8,
        }
    ],
    "metadata": {"domain": "legal"},
}


# ---------------------------------------------------------------------------
# Tests: generate_ontology()
# ---------------------------------------------------------------------------

class TestGenerateOntologySchema:
    def test_generates_valid_schema_for_fixture_text(self):
        from ipfs_datasets_py.optimizers.graphrag import OntologyGenerator
        gen = OntologyGenerator()
        ctx = _make_context()
        ontology = gen.generate_ontology(FIXTURE_TEXT, ctx)
        _assert_ontology_invariants(ontology)

    def test_empty_input_produces_valid_schema(self):
        from ipfs_datasets_py.optimizers.graphrag import OntologyGenerator
        gen = OntologyGenerator()
        ctx = _make_context()
        ontology = gen.generate_ontology("", ctx)
        _assert_ontology_invariants(ontology)
        # No entities expected for empty input
        assert ontology["entities"] == []

    def test_relationships_only_reference_valid_entities(self):
        from ipfs_datasets_py.optimizers.graphrag import OntologyGenerator
        gen = OntologyGenerator()
        ctx = _make_context()
        ontology = gen.generate_ontology(FIXTURE_TEXT, ctx)
        ent_ids = {e["id"] for e in ontology["entities"]}
        for rel in ontology["relationships"]:
            assert rel["source_id"] in ent_ids
            assert rel["target_id"] in ent_ids

    def test_no_duplicate_entity_ids(self):
        from ipfs_datasets_py.optimizers.graphrag import OntologyGenerator
        gen = OntologyGenerator()
        ctx = _make_context()
        # Run extraction twice and merge: IDs should still be unique
        ontology = gen.generate_ontology(FIXTURE_TEXT + " " + FIXTURE_TEXT, ctx)
        ids = [e["id"] for e in ontology["entities"]]
        assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# Tests: refine_ontology() preserves schema
# ---------------------------------------------------------------------------

class TestRefineOntologySchema:
    def _make_mediator(self):
        from ipfs_datasets_py.optimizers.graphrag import OntologyMediator, OntologyGenerator, OntologyCritic
        return OntologyMediator(generator=OntologyGenerator(), critic=OntologyCritic())

    def _make_critic_score(self, recommendations=None):
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
        return CriticScore(
            completeness=0.7,
            consistency=0.9,
            clarity=0.6,
            granularity=0.5,
            relationship_coherence=0.8, domain_alignment=0.8,
            recommendations=recommendations or ["Add more entity properties"],
        )

    def test_refine_preserves_entity_schema(self):
        mediator = self._make_mediator()
        ontology = dict(MINIMAL_VALID_ONTOLOGY)
        ontology["entities"] = [dict(e) for e in ontology["entities"]]
        ctx = _make_context()
        refined = mediator.refine_ontology(
            ontology, feedback=self._make_critic_score(), context=ctx
        )
        _assert_ontology_invariants(refined)

    def test_refine_preserves_relationship_schema(self):
        mediator = self._make_mediator()
        ontology = dict(MINIMAL_VALID_ONTOLOGY)
        ontology["entities"] = [dict(e) for e in ontology["entities"]]
        ontology["relationships"] = [dict(r) for r in ontology["relationships"]]
        ctx = _make_context()
        refined = mediator.refine_ontology(
            ontology, feedback=self._make_critic_score(["Normalize entity names"]), context=ctx
        )
        _assert_ontology_invariants(refined)


# ---------------------------------------------------------------------------
# Tests: OntologyCritic score ranges
# ---------------------------------------------------------------------------

class TestCriticScoreInvariants:
    def test_all_dimension_scores_in_unit_interval(self):
        from ipfs_datasets_py.optimizers.graphrag import OntologyCritic
        critic = OntologyCritic()
        ctx = _make_context()
        score = critic.evaluate_ontology(MINIMAL_VALID_ONTOLOGY, ctx)
        for dim in ("completeness", "consistency", "clarity", "granularity", "domain_alignment"):
            val = getattr(score, dim, None)
            assert val is not None, f"CriticScore missing dimension '{dim}'"
            assert 0.0 <= val <= 1.0, f"CriticScore.{dim}={val} out of [0,1]"

    def test_overall_score_in_unit_interval(self):
        from ipfs_datasets_py.optimizers.graphrag import OntologyCritic
        critic = OntologyCritic()
        ctx = _make_context()
        score = critic.evaluate_ontology(MINIMAL_VALID_ONTOLOGY, ctx)
        assert 0.0 <= score.overall <= 1.0

    def test_empty_ontology_gives_low_score(self):
        from ipfs_datasets_py.optimizers.graphrag import OntologyCritic
        critic = OntologyCritic()
        ctx = _make_context()
        score = critic.evaluate_ontology({"entities": [], "relationships": []}, ctx)
        assert score.completeness < 0.5, (
            "Empty ontology should have low completeness score"
        )


# ---------------------------------------------------------------------------
# Tests: merge_ontologies dedup invariant
# ---------------------------------------------------------------------------

class TestMergeOntologiesInvariants:
    def test_merged_ontology_has_no_duplicate_ids(self):
        from ipfs_datasets_py.optimizers.graphrag import OntologyGenerator
        gen = OntologyGenerator()
        base = {
            "entities": [{"id": "e1", "type": "Person", "text": "Alice", "properties": {}, "confidence": 1.0}],
            "relationships": [],
        }
        ext = {
            "entities": [
                {"id": "e1", "type": "Person", "text": "Alice", "properties": {"age": 30}, "confidence": 0.9},
                {"id": "e2", "type": "Org", "text": "Corp", "properties": {}, "confidence": 1.0},
            ],
            "relationships": [],
        }
        merged = gen._merge_ontologies(base, ext)
        ids = [e["id"] for e in merged["entities"]]
        assert len(ids) == len(set(ids)), "Merge must deduplicate entity IDs"
        assert len(merged["entities"]) == 2  # e1 + e2 only

    def test_merged_ontology_satisfies_schema(self):
        from ipfs_datasets_py.optimizers.graphrag import OntologyGenerator
        gen = OntologyGenerator()
        base = {
            "entities": [{"id": "e1", "type": "Person", "text": "Alice", "properties": {}, "confidence": 1.0}],
            "relationships": [],
        }
        ext = {
            "entities": [{"id": "e2", "type": "Org", "text": "Corp", "properties": {}, "confidence": 1.0}],
            "relationships": [{"id": "r1", "type": "works_for", "source_id": "e1", "target_id": "e2",
                               "properties": {}, "confidence": 0.8}],
        }
        merged = gen._merge_ontologies(base, ext)
        _assert_ontology_invariants(merged)
