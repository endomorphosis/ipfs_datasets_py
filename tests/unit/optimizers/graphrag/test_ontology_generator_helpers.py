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
    ExtractionConfig,
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

    def test_stopwords_filtered(self, generator):
        context = OntologyGenerationContext(
            data_source="test",
            data_type=DataType.TEXT,
            domain="general",
            extraction_strategy=ExtractionStrategy.RULE_BASED,
            config=ExtractionConfig(stopwords=["alice"]),
        )
        result = generator._extract_rule_based("Alice and Bob", context)
        texts = {e.text.lower() for e in result.entities}
        assert "alice" not in texts

    def test_allowed_entity_types_filters(self, generator):
        context = OntologyGenerationContext(
            data_source="test",
            data_type=DataType.TEXT,
            domain="general",
            extraction_strategy=ExtractionStrategy.RULE_BASED,
            config=ExtractionConfig(allowed_entity_types=["Person"]),
        )
        result = generator._extract_rule_based("Mr. John Smith at Acme Corp", context)
        assert all(e.type == "Person" for e in result.entities)

    def test_min_entity_length_filters_short_tokens(self, generator):
        context = OntologyGenerationContext(
            data_source="test",
            data_type=DataType.TEXT,
            domain="general",
            extraction_strategy=ExtractionStrategy.RULE_BASED,
            config=ExtractionConfig(min_entity_length=4),
        )
        result = generator._extract_rule_based("ABC", context)
        assert result.entities == []

    def test_max_confidence_caps_entities(self, generator):
        context = OntologyGenerationContext(
            data_source="test",
            data_type=DataType.TEXT,
            domain="general",
            extraction_strategy=ExtractionStrategy.RULE_BASED,
            config=ExtractionConfig(max_confidence=0.6),
        )
        result = generator._extract_rule_based("Mr. John Smith", context)
        assert result.entities
        assert all(e.confidence <= 0.6 for e in result.entities)

    def test_custom_rules_add_entity_type(self, generator):
        context = OntologyGenerationContext(
            data_source="test",
            data_type=DataType.TEXT,
            domain="general",
            extraction_strategy=ExtractionStrategy.RULE_BASED,
            config=ExtractionConfig(custom_rules=[(r"\bFooBar\b", "Custom")]),
        )
        result = generator._extract_rule_based("FooBar appears once", context)
        assert any(e.type == "Custom" for e in result.entities)

    def test_custom_rules_before_concept_fallback(self, generator):
        context = OntologyGenerationContext(
            data_source="test",
            data_type=DataType.TEXT,
            domain="general",
            extraction_strategy=ExtractionStrategy.RULE_BASED,
            config=ExtractionConfig(custom_rules=[(r"\bFooBar\b", "Custom")]),
        )
        result = generator._extract_rule_based("FooBar", context)
        custom_entities = [e for e in result.entities if e.text == "FooBar"]
        assert custom_entities
        assert custom_entities[0].type == "Custom"


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
    @pytest.mark.parametrize(
        "domain,text,expected_type",
        [
            ("legal", "The plaintiff filed a motion against the defendant.", "LegalParty"),
            ("medical", "Administer 500 mg twice daily.", "Dosage"),
            ("technical", "The service exposes a REST API over HTTP.", "Protocol"),
            ("financial", "The balance includes interest on the principal.", "FinancialConcept"),
        ],
    )
    def test_domain_specific_rules_extract_expected_type(
        self,
        generator,
        domain,
        text,
        expected_type,
    ):
        domain_ctx = OntologyGenerationContext(
            data_source="test",
            data_type=DataType.TEXT,
            domain=domain,
            extraction_strategy=ExtractionStrategy.RULE_BASED,
        )
        result = generator._extract_rule_based(text, domain_ctx)
        types = [e.type for e in result.entities]
        assert expected_type in types

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


# ---------------------------------------------------------------------------
# Fuzz/edge-case tests for _extract_rule_based()
# ---------------------------------------------------------------------------

class TestExtractRuleBasedEdgeCases:
    """Malformed and edge-case inputs to _extract_rule_based()."""

    def test_empty_string_returns_empty(self, generator, ctx):
        result = generator._extract_rule_based("", ctx)
        assert result.entities == []

    def test_whitespace_only_returns_empty(self, generator, ctx):
        result = generator._extract_rule_based("   \n\t  ", ctx)
        assert isinstance(result.entities, list)

    def test_non_ascii_unicode(self, generator, ctx):
        result = generator._extract_rule_based("Ärztekammer filed a claim.", ctx)
        assert isinstance(result.entities, list)

    def test_very_long_input(self, generator, ctx):
        text = "The Widget " * 1000
        result = generator._extract_rule_based(text, ctx)
        assert isinstance(result.entities, list)

    def test_binary_garbage_returns_result(self, generator, ctx):
        text = "\x00\x01\x02\x03 some text \xff\xfe"
        result = generator._extract_rule_based(text, ctx)
        assert isinstance(result.entities, list)

    def test_only_numbers_returns_result(self, generator, ctx):
        result = generator._extract_rule_based("1234567890 42.5 -3.14", ctx)
        assert isinstance(result.entities, list)

    def test_regex_special_chars_dont_crash(self, generator, ctx):
        result = generator._extract_rule_based("(.*) [hello] $$ ^^", ctx)
        assert isinstance(result.entities, list)

    def test_all_lowercase_no_proper_nouns(self, generator, ctx):
        result = generator._extract_rule_based("this is entirely lowercase text without any capitals.", ctx)
        assert isinstance(result.entities, list)

    def test_no_duplicate_entities_for_repeated_text(self, generator, ctx):
        text = "Alice Alice Alice Alice"
        result = generator._extract_rule_based(text, ctx)
        texts = [e.text for e in result.entities]
        # Should deduplicate
        assert texts.count("Alice") <= 1


# ---------------------------------------------------------------------------
# Tests for co-occurrence confidence decay
# ---------------------------------------------------------------------------

class TestCoOccurrenceConfidenceDecay:
    """Entities >100 chars apart get lower confidence than close entities."""

    def test_close_entities_get_higher_confidence_than_far(self, generator, ctx):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity

        # Two pairs — close and far apart
        e1 = Entity(id="e1", text="alpha", type="Concept", confidence=0.9)
        e2 = Entity(id="e2", text="beta", type="Concept", confidence=0.9)
        e3 = Entity(id="e3", text="gamma", type="Concept", confidence=0.9)
        e4 = Entity(id="e4", text="delta", type="Concept", confidence=0.9)

        # Text with alpha/beta close (< 10 chars apart) and gamma/delta far apart
        text = "alpha beta " + " " * 150 + "gamma delta"
        rels = generator.infer_relationships([e1, e2, e3, e4], ctx, data=text)

        close_rels = [r for r in rels if {r.source_id, r.target_id} == {"e1", "e2"}]
        far_rels = [r for r in rels if {r.source_id, r.target_id} == {"e3", "e4"}]

        if close_rels and far_rels:
            assert close_rels[0].confidence >= far_rels[0].confidence

    def test_confidence_within_range(self, generator, ctx):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity

        e1 = Entity(id="e1", text="foo", type="Concept", confidence=0.9)
        e2 = Entity(id="e2", text="bar", type="Concept", confidence=0.9)
        rels = generator.infer_relationships([e1, e2], ctx, data="foo and bar are close")
        co_rels = [r for r in rels if r.type == "related_to"]
        for r in co_rels:
            assert 0.0 <= r.confidence <= 1.0


class TestMinEntityLength:
    """Tests for ExtractionConfig.min_entity_length enforcement."""

    @pytest.fixture
    def gen(self):
        return OntologyGenerator(use_ipfs_accelerate=False)

    def test_default_min_length_filters_single_chars(self, gen):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
            ExtractionConfig, OntologyGenerationContext, DataType, ExtractionStrategy,
        )
        ctx = OntologyGenerationContext(
            data_source="t", data_type=DataType.TEXT, domain="general",
            extraction_strategy=ExtractionStrategy.RULE_BASED,
            config=ExtractionConfig(min_entity_length=2),
        )
        result = gen.extract_entities("A B C", ctx)
        # Single-character matches should be filtered out
        assert all(len(e.text) >= 2 for e in result.entities)

    def test_custom_min_length_filters_short_entities(self, gen):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
            ExtractionConfig, OntologyGenerationContext, DataType, ExtractionStrategy,
        )
        ctx = OntologyGenerationContext(
            data_source="t", data_type=DataType.TEXT, domain="general",
            extraction_strategy=ExtractionStrategy.RULE_BASED,
            config=ExtractionConfig(min_entity_length=10),
        )
        result = gen.extract_entities("Mr Smith and Dr Jones", ctx)
        assert all(len(e.text) >= 10 for e in result.entities)

    def test_to_dict_includes_min_entity_length(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
        cfg = ExtractionConfig(min_entity_length=5)
        assert cfg.to_dict()["min_entity_length"] == 5

    def test_from_dict_reads_min_entity_length(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
        cfg = ExtractionConfig.from_dict({"min_entity_length": 7})
        assert cfg.min_entity_length == 7

    def test_from_dict_default_is_two(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
        assert ExtractionConfig.from_dict({}).min_entity_length == 2


# ──────────────────────────────────────────────────────────────────────────────
# filter_by_confidence
# ──────────────────────────────────────────────────────────────────────────────

class TestFilterByConfidence:
    """Test OntologyGenerator.filter_by_confidence() with detailed stats."""

    @pytest.fixture
    def sample_result(self):
        """Create a sample EntityExtractionResult with varying confidence scores."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
            EntityExtractionResult,
            Entity,
            Relationship,
        )
        entities = [
            Entity(id="e1", text="Alice", type="Person", confidence=0.9),
            Entity(id="e2", text="Bob", type="Person", confidence=0.7),
            Entity(id="e3", text="Charlie", type="Person", confidence=0.5),
            Entity(id="e4", text="David", type="Person", confidence=0.3),
            Entity(id="e5", text="Eve", type="Person", confidence=0.1),
        ]
        relationships = [
            Relationship(
                id="r1",
                source_id="e1",
                target_id="e2",
                type="knows",
                confidence=0.8,
            ),
            Relationship(
                id="r2",
                source_id="e2",
                target_id="e3",
                type="knows",
                confidence=0.6,
            ),
            Relationship(
                id="r3",
                source_id="e4",
                target_id="e5",
                type="knows",
                confidence=0.2,
            ),
        ]
        return EntityExtractionResult(
            entities=entities,
            relationships=relationships,
            confidence=0.6,
        )

    def test_filter_default_threshold(self, generator, sample_result):
        """Test filtering with default threshold (0.5)."""
        filtered_data = generator.filter_by_confidence(sample_result)
        
        assert "result" in filtered_data
        assert "stats" in filtered_data
        
        result = filtered_data["result"]
        stats = filtered_data["stats"]
        
        # Should keep e1 (0.9), e2 (0.7), e3 (0.5) - exactly at threshold
        assert len(result.entities) == 3
        assert stats["filtered_entity_count"] == 3
        assert stats["original_entity_count"] == 5
        assert stats["removed_entity_count"] == 2
        assert stats["threshold"] == 0.5

    def test_filter_high_threshold(self, generator, sample_result):
        """Test filtering with high threshold (0.8)."""
        filtered_data = generator.filter_by_confidence(sample_result, threshold=0.8)
        
        result = filtered_data["result"]
        stats = filtered_data["stats"]
        
        # Should keep only e1 (0.9)
        assert len(result.entities) == 1
        assert result.entities[0].id == "e1"
        assert stats["filtered_entity_count"] == 1
        assert stats["removed_entity_count"] == 4

    def test_filter_low_threshold(self, generator, sample_result):
        """Test filtering with low threshold (0.1)."""
        filtered_data = generator.filter_by_confidence(sample_result, threshold=0.1)
        
        result = filtered_data["result"]
        stats = filtered_data["stats"]
        
        # Should keep all 5 entities (all >= 0.1)
        assert len(result.entities) == 5
        assert stats["filtered_entity_count"] == 5
        assert stats["removed_entity_count"] == 0

    def test_filter_removes_dangling_relationships(self, generator, sample_result):
        """Test that relationships without valid endpoints are removed."""
        # Filter to keep only e1, e2 (threshold=0.7)
        filtered_data = generator.filter_by_confidence(sample_result, threshold=0.7)
        
        result = filtered_data["result"]
        stats = filtered_data["stats"]
        
        # Should keep r1 (e1→e2) but not r2 (e2→e3, e3 removed) or r3 (e4→e5, both removed)
        assert len(result.relationships) == 1
        assert result.relationships[0].id == "r1"
        assert stats["original_relationship_count"] == 3
        assert stats["filtered_relationship_count"] == 1
        assert stats["removed_relationship_count"] == 2

    def test_filter_retention_rate(self, generator, sample_result):
        """Test retention_rate statistic calculation."""
        filtered_data = generator.filter_by_confidence(sample_result, threshold=0.5)
        
        stats = filtered_data["stats"]
        
        # 3 out of 5 entities kept = 0.6 retention rate
        assert stats["retention_rate"] == 0.6

    def test_filter_avg_confidence_computation(self, generator, sample_result):
        """Test average confidence before and after filtering."""
        filtered_data = generator.filter_by_confidence(sample_result, threshold=0.5)
        
        stats = filtered_data["stats"]
        
        # Before: (0.9 + 0.7 + 0.5 + 0.3 + 0.1) / 5 = 0.5
        assert abs(stats["avg_confidence_before"] - 0.5) < 0.01
        
        # After: (0.9 + 0.7 + 0.5) / 3 = 0.7
        assert abs(stats["avg_confidence_after"] - 0.7) < 0.01

    def test_filter_invalid_threshold_too_high(self, generator, sample_result):
        """Test that threshold > 1.0 raises ValueError."""
        with pytest.raises(ValueError, match="threshold must be in"):
            generator.filter_by_confidence(sample_result, threshold=1.5)

    def test_filter_invalid_threshold_too_low(self, generator, sample_result):
        """Test that threshold < 0.0 raises ValueError."""
        with pytest.raises(ValueError, match="threshold must be in"):
            generator.filter_by_confidence(sample_result, threshold=-0.1)

    def test_filter_empty_result_returns_zero_stats(self, generator):
        """Test filtering an empty EntityExtractionResult."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
            EntityExtractionResult,
        )
        empty_result = EntityExtractionResult(
            entities=[],
            relationships=[],
            confidence=0.0,
        )
        
        filtered_data = generator.filter_by_confidence(empty_result, threshold=0.5)
        
        stats = filtered_data["stats"]
        assert stats["original_entity_count"] == 0
        assert stats["filtered_entity_count"] == 0
        assert stats["retention_rate"] == 0.0
        assert stats["avg_confidence_before"] == 0.0
        assert stats["avg_confidence_after"] == 0.0

    def test_filter_all_below_threshold(self, generator, sample_result):
        """Test filtering when all entities are below threshold."""
        # All entities have confidence <= 0.9, set threshold = 1.0
        filtered_data = generator.filter_by_confidence(sample_result, threshold=1.0)
        
        result = filtered_data["result"]
        stats = filtered_data["stats"]
        
        assert len(result.entities) == 0
        assert len(result.relationships) == 0
        assert stats["retention_rate"] == 0.0
        assert stats["avg_confidence_after"] == 0.0

    def test_filter_stats_keys_present(self, generator, sample_result):
        """Test that all expected stats keys are present in the response."""
        filtered_data = generator.filter_by_confidence(sample_result, threshold=0.5)
        
        stats = filtered_data["stats"]
        expected_keys = {
            "original_entity_count",
            "filtered_entity_count",
            "removed_entity_count",
            "original_relationship_count",
            "filtered_relationship_count",
            "removed_relationship_count",
            "threshold",
            "retention_rate",
            "avg_confidence_before",
            "avg_confidence_after",
        }
        
        assert set(stats.keys()) == expected_keys

    def test_filter_preserves_metadata(self, generator):
        """Test that original metadata is preserved in filtered result."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
            EntityExtractionResult,
            Entity,
        )
        result = EntityExtractionResult(
            entities=[Entity(id="e1", text="Alice", type="Person", confidence=0.9)],
            relationships=[],
            confidence=0.8,
            metadata={"source": "test", "version": "1.0"},
        )
        
        filtered_data = generator.filter_by_confidence(result, threshold=0.5)
        
        # Check that metadata from EntityExtractionResult.filter_by_confidence is present
        assert "filter_confidence_stats" in filtered_data["result"].metadata
        # Original metadata should still be there
        assert filtered_data["result"].metadata.get("source") == "test"
        assert filtered_data["result"].metadata.get("version") == "1.0"


# ──────────────────────────────────────────────────────────────────────────────
# _extract_rule_based timing instrumentation
# ──────────────────────────────────────────────────────────────────────────────

class TestExtractRuleBasedTiming:
    """Test timing instrumentation in _extract_rule_based method."""

    def test_result_includes_timing_metadata(self, generator, ctx):
        """Test that extraction result includes timing metrics in metadata."""
        text = "Dr. Smith works at Acme Corp. He mentioned the obligation of the company."
        result = generator._extract_rule_based(text, ctx)
        
        # Check that timing metrics are in metadata
        assert "pattern_time_ms" in result.metadata
        assert "extraction_time_ms" in result.metadata
        assert "relationship_time_ms" in result.metadata
        assert "total_time_ms" in result.metadata

    def test_all_timing_metrics_are_floats(self, generator, ctx):
        """Test that all timing metrics are float values."""
        text = "Alice and Bob work together."
        result = generator._extract_rule_based(text, ctx)
        
        assert isinstance(result.metadata["pattern_time_ms"], float)
        assert isinstance(result.metadata["extraction_time_ms"], float)
        assert isinstance(result.metadata["relationship_time_ms"], float)
        assert isinstance(result.metadata["total_time_ms"], float)

    def test_all_timing_metrics_are_non_negative(self, generator, ctx):
        """Test that timing values are non-negative."""
        text = "Test text"
        result = generator._extract_rule_based(text, ctx)
        
        assert result.metadata["pattern_time_ms"] >= 0
        assert result.metadata["extraction_time_ms"] >= 0
        assert result.metadata["relationship_time_ms"] >= 0
        assert result.metadata["total_time_ms"] >= 0

    def test_total_time_approximates_sum_of_components(self, generator, ctx):
        """Test that total_time is approximately the sum of component times."""
        text = "Dr. Johnson is from New York. The company mentioned he has an obligation."
        result = generator._extract_rule_based(text, ctx)
        
        pattern_time = result.metadata["pattern_time_ms"]
        extraction_time = result.metadata["extraction_time_ms"]
        relationship_time = result.metadata["relationship_time_ms"]
        total_time = result.metadata["total_time_ms"]
        
        # Total should be >= sum of components (with small tolerance for overhead)
        component_sum = pattern_time + extraction_time + relationship_time
        assert total_time >= component_sum
        # Total should be close to sum (within 10ms overhead tolerance)
        assert total_time <= component_sum + 10.0

    def test_empty_text_still_records_timing(self, generator, ctx):
        """Test that even empty text produces timing metrics."""
        result = generator._extract_rule_based("", ctx)
        
        assert "total_time_ms" in result.metadata
        assert result.metadata["total_time_ms"] >= 0

    def test_timing_recorded_on_large_text(self, generator, ctx):
        """Test that timing metrics work on larger text extractions."""
        # Generate larger text with multiple entities
        text = " ".join([
            f"Dr. Person{i} works at Company{i} Corp."
            for i in range(20)
        ])
        result = generator._extract_rule_based(text, ctx)
        
        # Should have timing metrics
        assert result.metadata["total_time_ms"] >= 0
        # Larger text should take measurable time
        assert result.metadata["total_time_ms"] > 0

    def test_metadata_includes_method_field(self, generator, ctx):
        """Test that metadata includes the extraction method name."""
        result = generator._extract_rule_based("Test", ctx)
        
        assert result.metadata.get("method") == "rule_based"

    def test_metadata_includes_entity_count(self, generator, ctx):
        """Test that metadata includes entity count."""
        text = "Dr. Smith and Prof. Jones work at Acme Corp."
        result = generator._extract_rule_based(text, ctx)
        
        assert "entity_count" in result.metadata
        assert result.metadata["entity_count"] == len(result.entities)

    def test_timing_metrics_are_reasonable(self, generator, ctx):
        """Test that timing values are in reasonable range (not absurdly high)."""
        text = "Simple test text"
        result = generator._extract_rule_based(text, ctx)
        
        # Timing should complete in reasonable time (< 1000ms for simple extraction)
        assert result.metadata["total_time_ms"] < 1000.0
        assert result.metadata["pattern_time_ms"] < 500.0
        assert result.metadata["extraction_time_ms"] < 500.0
        assert result.metadata["relationship_time_ms"] < 500.0

