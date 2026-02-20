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


# ──────────────────────────────────────────────────────────────────────────────
# Domain-specific and custom rules
# ──────────────────────────────────────────────────────────────────────────────

class TestDomainSpecificExtraction:
    def test_legal_domain_extracts_legal_party(self, generator):
        legal_ctx = OntologyGenerationContext(
            data_source="test",
            data_type=DataType.TEXT,
            domain="legal",
            extraction_strategy=ExtractionStrategy.RULE_BASED,
        )
        text = "The plaintiff filed a motion against the defendant."
        result = generator._extract_rule_based(text, legal_ctx)
        types = [e.type for e in result.entities]
        assert "LegalParty" in types

    def test_medical_domain_extracts_dosage(self, generator):
        med_ctx = OntologyGenerationContext(
            data_source="test",
            data_type=DataType.TEXT,
            domain="medical",
            extraction_strategy=ExtractionStrategy.RULE_BASED,
        )
        text = "Administer 500 mg twice daily."
        result = generator._extract_rule_based(text, med_ctx)
        types = [e.type for e in result.entities]
        assert "Dosage" in types

    def test_technical_domain_extracts_protocol(self, generator):
        tech_ctx = OntologyGenerationContext(
            data_source="test",
            data_type=DataType.TEXT,
            domain="technical",
            extraction_strategy=ExtractionStrategy.RULE_BASED,
        )
        text = "The service exposes a REST API over HTTP."
        result = generator._extract_rule_based(text, tech_ctx)
        types = [e.type for e in result.entities]
        assert "Protocol" in types

    def test_custom_rules_pluggable(self, generator):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
        cfg = ExtractionConfig(custom_rules=[(r'\b(?:Widget|Gadget)\b', 'Product')])
        custom_ctx = OntologyGenerationContext(
            data_source="test",
            data_type=DataType.TEXT,
            domain="general",
            extraction_strategy=ExtractionStrategy.RULE_BASED,
            config=cfg,
        )
        text = "The Widget is sold alongside the Gadget."
        result = generator._extract_rule_based(text, custom_ctx)
        types = [e.type for e in result.entities]
        assert "Product" in types

    def test_unknown_domain_falls_back_to_base_patterns(self, generator):
        unknown_ctx = OntologyGenerationContext(
            data_source="test",
            data_type=DataType.TEXT,
            domain="unknown_xyz",
            extraction_strategy=ExtractionStrategy.RULE_BASED,
        )
        text = "Dr. Alice signed the agreement on 01/15/2024."
        result = generator._extract_rule_based(text, unknown_ctx)
        types = [e.type for e in result.entities]
        assert "Person" in types or "Date" in types


class TestMergeEntitiesTypeConflict:
    def test_type_conflict_emits_warning(self, generator):
        base = {
            "entities": [{"id": "e0", "type": "Person", "text": "Alice", "confidence": 0.5}],
            "relationships": [],
            "metadata": {},
        }
        ext = {
            "entities": [{"id": "e0", "type": "Organization", "text": "Alice", "confidence": 0.3}],
            "relationships": [],
            "metadata": {},
        }
        # Should not raise; type conflict is logged at WARNING, not raised
        merged = generator._merge_ontologies(base, ext)
        e0 = next(e for e in merged["entities"] if e["id"] == "e0")
        # lower-confidence extension does not override type
        assert e0["type"] == "Person"

    def test_higher_confidence_extension_type_wins(self, generator):
        base = {
            "entities": [{"id": "e0", "type": "Person", "text": "Alice", "confidence": 0.3}],
            "relationships": [],
            "metadata": {},
        }
        ext = {
            "entities": [{"id": "e0", "type": "Organization", "text": "Alice", "confidence": 0.9}],
            "relationships": [],
            "metadata": {},
        }
        merged = generator._merge_ontologies(base, ext)
        e0 = next(e for e in merged["entities"] if e["id"] == "e0")
        assert e0["type"] == "Organization"
        assert e0["confidence"] == 0.9


# ---------------------------------------------------------------------------
# Property-based test: _merge_ontologies is idempotent
# ---------------------------------------------------------------------------

class TestMergeOntologiesIdempotent:
    """Merging an ontology with itself should be idempotent (same entity count)."""

    def _make_ontology(self, entity_ids, relationship_pairs=None):
        entities = [
            {"id": eid, "type": "Concept", "text": eid, "confidence": 0.7}
            for eid in entity_ids
        ]
        relationships = [
            {"source_id": s, "target_id": t, "type": "relates_to", "confidence": 0.5}
            for s, t in (relationship_pairs or [])
        ]
        return {"entities": entities, "relationships": relationships, "metadata": {}}

    def test_merge_self_entity_count_unchanged(self, generator):
        onto = self._make_ontology(["e1", "e2", "e3"])
        merged = generator._merge_ontologies(onto, onto)
        assert len(merged["entities"]) == 3

    def test_merge_self_relationship_count_unchanged(self, generator):
        onto = self._make_ontology(
            ["e1", "e2"],
            relationship_pairs=[("e1", "e2"), ("e2", "e1")]
        )
        merged = generator._merge_ontologies(onto, onto)
        assert len(merged["relationships"]) == 2

    def test_merge_self_empty_ontology(self, generator):
        onto = self._make_ontology([])
        merged = generator._merge_ontologies(onto, onto)
        assert merged["entities"] == []
        assert merged["relationships"] == []

    def test_merge_self_single_entity(self, generator):
        onto = self._make_ontology(["x"])
        merged = generator._merge_ontologies(onto, onto)
        assert len(merged["entities"]) == 1

    def test_merge_self_twice_still_idempotent(self, generator):
        """Applying merge three times (merge, then merge again) stays stable."""
        onto = self._make_ontology(["a", "b", "c"], [("a", "b"), ("b", "c")])
        m1 = generator._merge_ontologies(onto, onto)
        m2 = generator._merge_ontologies(m1, onto)
        assert len(m2["entities"]) == 3
        assert len(m2["relationships"]) == 2


# ---------------------------------------------------------------------------
# Tests for Relationship.direction field (directionality detection)
# ---------------------------------------------------------------------------

class TestRelationshipDirectionality:
    """Verb-frame relationships are subject_to_object; co-occurrence is undirected."""

    def _make_entities(self, pairs):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity, DataType
        return [
            Entity(id=f"e{i}", text=name, type="Concept", confidence=0.9)
            for i, (name, _) in enumerate(pairs)
        ]

    def test_verb_frame_rel_is_subject_to_object(self, generator, ctx):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity, DataType
        e1 = Entity(id="e1", text="Alice", type="Person", confidence=0.9)
        e2 = Entity(id="e2", text="report", type="Concept", confidence=0.9)
        rels = generator.infer_relationships([e1, e2], ctx, data="Alice causes report")
        verb_rels = [r for r in rels if r.type == "causes"]
        assert len(verb_rels) >= 1
        assert verb_rels[0].direction == "subject_to_object"

    def test_cooccurrence_rel_is_undirected(self, generator, ctx):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity, DataType
        e1 = Entity(id="e1", text="widget", type="Concept", confidence=0.9)
        e2 = Entity(id="e2", text="gadget", type="Concept", confidence=0.9)
        # No verb pattern, only co-occurrence
        rels = generator.infer_relationships([e1, e2], ctx, data="widget and gadget are close")
        co_rels = [r for r in rels if r.type == "related_to"]
        assert len(co_rels) >= 1
        assert co_rels[0].direction == "undirected"

    def test_default_relationship_direction_is_unknown(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Relationship
        r = Relationship(id="r0", source_id="s", target_id="t", type="foo")
        assert r.direction == "unknown"

    def test_direction_subject_to_object_explicit(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Relationship
        r = Relationship(
            id="r1", source_id="s", target_id="t", type="owns",
            direction="subject_to_object",
        )
        assert r.direction == "subject_to_object"

    def test_relationship_to_dict_includes_direction(self, generator):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Relationship
        r = Relationship(
            id="r2", source_id="s", target_id="t", type="causes",
            confidence=0.7, direction="subject_to_object",
        )
        d = generator._relationship_to_dict(r)
        assert d["direction"] == "subject_to_object"
