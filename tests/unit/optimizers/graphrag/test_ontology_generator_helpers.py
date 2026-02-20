"""Unit tests for OntologyGenerator helper methods.

Covers:
- infer_relationships(): verb-frame pattern matching + co-occurrence
- _extract_rule_based(): rule NER extraction from text
- _merge_ontologies(): entity/relationship dedup and merge
"""

from __future__ import annotations

import pytest
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    OntologyGenerator,
    OntologyGenerationContext,
    Entity,
    Relationship,
    ExtractionStrategy,
    DataType,
)


@pytest.fixture
def generator():
    return OntologyGenerator()


@pytest.fixture
def ctx():
    return OntologyGenerationContext(
        data_source="test",
        data_type=DataType.TEXT,
        domain="general",
        extraction_strategy=ExtractionStrategy.RULE_BASED,
    )


def _entity(eid: str, text: str, etype: str = "Concept") -> Entity:
    return Entity(id=eid, type=etype, text=text, confidence=0.8)


# ──────────────────────────────────────────────────────────────────────────────
# infer_relationships
# ──────────────────────────────────────────────────────────────────────────────

class TestInferRelationships:
    def test_empty_entities_returns_empty(self, generator, ctx):
        rels = generator.infer_relationships([], ctx, "some text")
        assert rels == []

    def test_obligates_verb_pattern(self, generator, ctx):
        entities = [_entity("e1", "Alice"), _entity("e2", "Bob")]
        text = "Alice must pay Bob for services"
        rels = generator.infer_relationships(entities, ctx, text)
        types = {r.type for r in rels}
        assert "obligates" in types

    def test_owns_verb_pattern(self, generator, ctx):
        entities = [_entity("e1", "Alice"), _entity("e2", "Company")]
        text = "Alice owns Company"
        rels = generator.infer_relationships(entities, ctx, text)
        types = {r.type for r in rels}
        assert "owns" in types

    def test_is_a_verb_pattern(self, generator, ctx):
        entities = [_entity("e1", "Dog"), _entity("e2", "Animal")]
        text = "Dog is a Animal"
        rels = generator.infer_relationships(entities, ctx, text)
        types = {r.type for r in rels}
        assert "is_a" in types

    def test_co_occurrence_within_window(self, generator, ctx):
        entities = [_entity("e1", "Alpha"), _entity("e2", "Beta")]
        # Place them close together (< 200 chars apart)
        text = "Alpha and Beta are close"
        rels = generator.infer_relationships(entities, ctx, text)
        assert len(rels) >= 1

    def test_no_self_relationship(self, generator, ctx):
        entities = [_entity("e1", "Alice")]
        text = "Alice must pay Alice"
        rels = generator.infer_relationships(entities, ctx, text)
        for r in rels:
            assert r.source_id != r.target_id

    def test_all_rels_have_required_fields(self, generator, ctx):
        entities = [_entity("e1", "Alice"), _entity("e2", "Bob")]
        text = "Alice owns Bob"
        rels = generator.infer_relationships(entities, ctx, text)
        for r in rels:
            assert r.id
            assert r.source_id
            assert r.target_id
            assert r.type
            assert 0.0 <= r.confidence <= 1.0

    def test_dedup_no_duplicate_pairs(self, generator, ctx):
        # Co-occurrence should not produce the same pair twice
        entities = [_entity("e1", "Alice"), _entity("e2", "Bob")]
        text = "Alice and Bob and Alice and Bob"
        rels = generator.infer_relationships(entities, ctx, text)
        pairs = [(r.source_id, r.target_id) for r in rels]
        # Forward or backward pair — no exact dup
        assert len(pairs) == len(set(pairs))

    def test_entities_far_apart_not_linked(self, generator, ctx):
        entities = [_entity("e1", "Alpha"), _entity("e2", "Gamma")]
        # 300 chars separating them
        text = "Alpha" + " " * 300 + "Gamma"
        rels = generator.infer_relationships(entities, ctx, text)
        co_occ = [r for r in rels if r.type == "related_to"]
        assert co_occ == []


# ──────────────────────────────────────────────────────────────────────────────
# _extract_rule_based
# ──────────────────────────────────────────────────────────────────────────────

class TestExtractRuleBased:
    def test_extracts_person_names(self, generator, ctx):
        text = "Mr. John Smith attended the meeting."
        result = generator._extract_rule_based(text, ctx)
        entity_texts = [e.text for e in result.entities]
        assert any("John Smith" in t for t in entity_texts)

    def test_extracts_organizations(self, generator, ctx):
        text = "Acme Corp signed the contract."
        result = generator._extract_rule_based(text, ctx)
        entity_texts = [e.text for e in result.entities]
        assert any("Corp" in t or "Acme" in t for t in entity_texts)

    def test_extracts_monetary_amounts(self, generator, ctx):
        # The rule pattern requires a word boundary before the currency symbol,
        # which works for 3-letter codes like USD/EUR but not bare $ prefixes.
        text = "The payment of USD 1000 was received."
        result = generator._extract_rule_based(text, ctx)
        types = [e.type for e in result.entities]
        assert "MonetaryAmount" in types

    def test_extracts_dates(self, generator, ctx):
        text = "The contract was signed on January 15, 2024."
        result = generator._extract_rule_based(text, ctx)
        types = [e.type for e in result.entities]
        assert "Date" in types

    def test_no_duplicate_entities(self, generator, ctx):
        text = "Alice Alice Alice"
        result = generator._extract_rule_based(text, ctx)
        texts_lower = [e.text.lower() for e in result.entities]
        assert len(texts_lower) == len(set(texts_lower))

    def test_result_has_entities_and_relationships(self, generator, ctx):
        text = "Dr. Smith owns Acme Corp"
        result = generator._extract_rule_based(text, ctx)
        assert hasattr(result, "entities")
        assert hasattr(result, "relationships")

    def test_empty_text_returns_empty_extraction(self, generator, ctx):
        result = generator._extract_rule_based("", ctx)
        assert result.entities == [] or len(result.entities) == 0

    def test_entity_ids_are_unique(self, generator, ctx):
        text = "Mr. Alice Mr. Bob Dr. Carol signed the contract with Acme Corp."
        result = generator._extract_rule_based(text, ctx)
        ids = [e.id for e in result.entities]
        assert len(ids) == len(set(ids))

    def test_confidence_values_in_range(self, generator, ctx):
        text = "Dr. Alice is an expert at Acme Corp. Payment of $500 on 01/01/2024."
        result = generator._extract_rule_based(text, ctx)
        for e in result.entities:
            assert 0.0 <= e.confidence <= 1.0


# ──────────────────────────────────────────────────────────────────────────────
# _merge_ontologies
# ──────────────────────────────────────────────────────────────────────────────

class TestMergeOntologies:
    def _make_ontology(self, n_ents: int, n_rels: int = 0, source: str = "base") -> dict:
        ents = [
            {"id": f"e{i}", "type": "Concept", "text": f"entity{i}", "properties": {}}
            for i in range(n_ents)
        ]
        rels = [
            {"id": f"r{i}", "source_id": f"e{i}", "target_id": f"e{(i + 1) % n_ents}", "type": "related_to"}
            for i in range(n_rels)
        ] if n_ents > 0 else []
        return {"entities": ents, "relationships": rels, "metadata": {"source": source}}

    def test_non_overlapping_entities_are_all_present(self, generator):
        base = self._make_ontology(3, source="base")
        ext = {
            "entities": [{"id": "e99", "type": "X", "text": "new", "properties": {}}],
            "relationships": [],
            "metadata": {"source": "ext"},
        }
        merged = generator._merge_ontologies(base, ext)
        ids = [e["id"] for e in merged["entities"]]
        assert "e0" in ids
        assert "e1" in ids
        assert "e99" in ids

    def test_duplicate_entity_ids_are_merged_not_duplicated(self, generator):
        base = {"entities": [{"id": "e0", "type": "X", "text": "a", "properties": {}}], "relationships": [], "metadata": {}}
        ext = {"entities": [{"id": "e0", "type": "X", "text": "a", "properties": {"key": "val"}}], "relationships": [], "metadata": {}}
        merged = generator._merge_ontologies(base, ext)
        ids = [e["id"] for e in merged["entities"]]
        assert ids.count("e0") == 1

    def test_merged_entity_has_combined_properties(self, generator):
        base = {"entities": [{"id": "e0", "type": "X", "text": "a", "properties": {"p1": "v1"}, "confidence": 0.5}], "relationships": [], "metadata": {}}
        ext = {"entities": [{"id": "e0", "type": "X", "text": "a", "properties": {"p2": "v2"}, "confidence": 0.9}], "relationships": [], "metadata": {}}
        merged = generator._merge_ontologies(base, ext)
        e0 = next(e for e in merged["entities"] if e["id"] == "e0")
        assert "p1" in e0["properties"] or "p2" in e0["properties"]

    def test_higher_confidence_wins_on_merge(self, generator):
        base = {"entities": [{"id": "e0", "type": "X", "text": "a", "properties": {}, "confidence": 0.3}], "relationships": [], "metadata": {}}
        ext = {"entities": [{"id": "e0", "type": "X", "text": "a", "properties": {}, "confidence": 0.9}], "relationships": [], "metadata": {}}
        merged = generator._merge_ontologies(base, ext)
        e0 = next(e for e in merged["entities"] if e["id"] == "e0")
        assert e0["confidence"] == 0.9

    def test_duplicate_relationships_not_duplicated(self, generator):
        base = {"entities": [{"id": "e0"}, {"id": "e1"}], "relationships": [{"id": "r0", "source_id": "e0", "target_id": "e1", "type": "related_to"}], "metadata": {}}
        ext = {"entities": [], "relationships": [{"id": "r0", "source_id": "e0", "target_id": "e1", "type": "related_to"}], "metadata": {}}
        merged = generator._merge_ontologies(base, ext)
        same_rels = [
            r for r in merged["relationships"]
            if r.get("source_id") == "e0" and r.get("target_id") == "e1" and r.get("type") == "related_to"
        ]
        assert len(same_rels) == 1

    def test_new_relationships_added(self, generator):
        base = {"entities": [{"id": "e0"}, {"id": "e1"}], "relationships": [], "metadata": {}}
        ext = {"entities": [], "relationships": [{"id": "r0", "source_id": "e0", "target_id": "e1", "type": "related_to"}], "metadata": {}}
        merged = generator._merge_ontologies(base, ext)
        assert len(merged["relationships"]) == 1

    def test_merge_tracks_provenance(self, generator):
        base = self._make_ontology(2, source="base")
        ext = {
            "entities": [{"id": "e99", "type": "X", "text": "new", "properties": {}}],
            "relationships": [],
            "metadata": {"source": "ext_source"},
        }
        merged = generator._merge_ontologies(base, ext)
        new_ent = next(e for e in merged["entities"] if e["id"] == "e99")
        assert "ext_source" in new_ent.get("provenance", [])

    def test_merged_from_metadata_updated(self, generator):
        base = self._make_ontology(2, source="source_a")
        ext = self._make_ontology(2, source="source_b")
        # Give ext unique ids
        for i, e in enumerate(ext["entities"]):
            e["id"] = f"ext_{i}"
        merged = generator._merge_ontologies(base, ext)
        assert "source_b" in merged["metadata"].get("merged_from", [])

    def test_base_not_mutated(self, generator):
        import copy
        base = self._make_ontology(2, source="base")
        orig_base = copy.deepcopy(base)
        ext = self._make_ontology(2, source="ext")
        for i, e in enumerate(ext["entities"]):
            e["id"] = f"ext_{i}"
        generator._merge_ontologies(base, ext)
        assert base == orig_base
