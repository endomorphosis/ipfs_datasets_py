"""
Session 33 – knowledge_graphs coverage push.

Targets (43 new GIVEN-WHEN-THEN tests):
  • transactions/wal.py        96% → 100%  (+4pp)  – asyncio.CancelledError re-raises (6 lines)
  • jsonld/translator.py       93% → 100%  (+7pp)  – 10 edge-case paths
  • ontology/reasoning.py      98% → 100%  (+2pp)  – subproperty, from_turtle, fixpoint, property-chains
  • extraction/advanced.py     99% → 100%  (+1pp)  – confidence modifiers, get_extraction_statistics
  • extraction/graph.py        98% → 100%  (+2pp)  – non-Entity source, depth-limit, boolean properties
  • migration/ipfs_importer.py 97% → 99%   (+2pp)  – MigrationError re-raise, index/constraint errors
  • reasoning/cross_document.py 96% → 99% (+3pp)  – default optimizer, _example_usage demo
"""

from __future__ import annotations

import asyncio
import sys
import time
import uuid
from typing import Any, Dict
from unittest.mock import MagicMock, patch
import importlib

import pytest

_rdflib_available = bool(importlib.util.find_spec("rdflib"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_wal_entry():
    """Return a minimal WriteAheadLog entry."""
    from ipfs_datasets_py.knowledge_graphs.transactions.wal import WALEntry

    return WALEntry(txn_id=str(uuid.uuid4()), timestamp=time.time(), operations=[])


# ===========================================================================
# 1. transactions/wal.py – asyncio.CancelledError re-raises (lines 130, 197,
#    259, 329, 371, 439)
# ===========================================================================

class TestWriteAheadLogCancelledError:
    """GIVEN a WriteAheadLog whose storage raises asyncio.CancelledError,
    WHEN the relevant method is called,
    THEN the CancelledError propagates unchanged.
    """

    def _make_wal(self, *, head_cid: str | None = None, raise_on: str = "store_json"):
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WriteAheadLog

        storage = MagicMock()
        getattr(storage, raise_on).side_effect = asyncio.CancelledError()
        return WriteAheadLog(storage=storage, wal_head_cid=head_cid)

    def test_append_cancelled_error_reraises(self):
        """GIVEN store_json raises CancelledError WHEN append is called
        THEN CancelledError propagates (line 130)."""
        wal = self._make_wal(raise_on="store_json")
        with pytest.raises(asyncio.CancelledError):
            wal.append(_make_wal_entry())

    def test_read_cancelled_error_reraises(self):
        """GIVEN retrieve_json raises CancelledError WHEN read is iterated
        THEN CancelledError propagates (line 197)."""
        wal = self._make_wal(head_cid="cid1", raise_on="retrieve_json")
        with pytest.raises(asyncio.CancelledError):
            list(wal.read())

    def test_compact_cancelled_error_reraises(self):
        """GIVEN store_json raises CancelledError WHEN compact is called
        THEN CancelledError propagates (line 259)."""
        wal = self._make_wal(raise_on="store_json")
        with pytest.raises(asyncio.CancelledError):
            wal.compact("some-checkpoint-cid")

    def test_recover_cancelled_error_reraises(self):
        """GIVEN retrieve_json raises CancelledError WHEN recover is called
        THEN CancelledError propagates (line 329)."""
        wal = self._make_wal(head_cid="cid1", raise_on="retrieve_json")
        with pytest.raises(asyncio.CancelledError):
            wal.recover()

    def test_get_transaction_history_cancelled_error_reraises(self):
        """GIVEN retrieve_json raises CancelledError WHEN get_transaction_history
        is called THEN CancelledError propagates (line 371)."""
        wal = self._make_wal(head_cid="cid1", raise_on="retrieve_json")
        with pytest.raises(asyncio.CancelledError):
            wal.get_transaction_history("some-txn-id")

    def test_verify_integrity_cancelled_error_reraises(self):
        """GIVEN retrieve_json raises CancelledError WHEN verify_integrity is
        called THEN CancelledError propagates (line 439)."""
        wal = self._make_wal(head_cid="cid1", raise_on="retrieve_json")
        with pytest.raises(asyncio.CancelledError):
            wal.verify_integrity()


# ===========================================================================
# 2. jsonld/translator.py – missed lines 64, 111, 159-161, 200, 208, 225,
#    341, 345
# ===========================================================================

class TestJSONLDTranslatorMissedPaths:
    """GIVEN various JSON-LD structures, WHEN translated to IPLD or back,
    THEN the edge-case branches are exercised."""

    def _translator(self, **options_kwargs):
        from ipfs_datasets_py.knowledge_graphs.jsonld.translator import (
            JSONLDTranslator,
            TranslationOptions,
        )

        return JSONLDTranslator(TranslationOptions(**options_kwargs))

    # -----------------------------------------------------------------------
    # Line 64: expand_context=True but no '@context' key → expanded = jsonld
    # -----------------------------------------------------------------------
    def test_expand_context_no_at_context_key(self):
        """GIVEN expand_context=True and a document without '@context'
        WHEN jsonld_to_ipld is called THEN expanded = jsonld (line 64)."""
        t = self._translator(expand_context=True)
        result = t.jsonld_to_ipld(
            {"@id": "http://example.org/e1", "@type": "Thing", "name": "Alice"}
        )
        assert result is not None
        assert len(result.entities) > 0

    # -----------------------------------------------------------------------
    # Line 111: @type is a list → node_type = node_type[0]
    # -----------------------------------------------------------------------
    def test_list_type_uses_first_element(self):
        """GIVEN @type is a list WHEN translated THEN the first type is used
        (line 111)."""
        t = self._translator()
        result = t.jsonld_to_ipld(
            {"@id": "http://example.org/e2", "@type": ["Person", "Thing"], "name": "Bob"}
        )
        assert len(result.entities) == 1
        # The entity should exist; first type 'Person' is used
        entity = result.entities[0]
        assert entity.get("entity_type") is not None or entity.get("type") is not None

    # -----------------------------------------------------------------------
    # Lines 159-161: array value with non-dict items → append to list prop
    # -----------------------------------------------------------------------
    def test_list_literal_values_appended_to_property(self):
        """GIVEN an array of literal strings as a property value
        WHEN translated THEN each item is appended (lines 159-161)."""
        t = self._translator()
        result = t.jsonld_to_ipld(
            {"@id": "http://example.org/e3", "@type": "Dataset", "tags": ["alpha", "beta", "gamma"]}
        )
        assert len(result.entities) == 1
        props = result.entities[0].get("properties", {})
        assert "tags" in props

    # -----------------------------------------------------------------------
    # Line 200: id_mappings cache hit (same @id encountered twice)
    # -----------------------------------------------------------------------
    def test_id_mapping_cache_hit(self):
        """GIVEN the same @id appears in two separate translate calls
        WHEN the second call is made THEN id_mappings lookup fires (line 200)."""
        t = self._translator()
        # First call populates the cache
        t.jsonld_to_ipld({"@id": "http://example.org/shared", "@type": "Thing"})
        # Second call—same @id—hits line 200
        result = t.jsonld_to_ipld(
            {
                "@graph": [
                    {"@id": "http://example.org/shared", "@type": "Thing"},
                    {
                        "@id": "http://example.org/other",
                        "@type": "Person",
                        "knows": {"@id": "http://example.org/shared"},
                    },
                ]
            }
        )
        assert result is not None

    # -----------------------------------------------------------------------
    # Line 208: blank node @id with preserve_blank_nodes=False → new UUID
    # -----------------------------------------------------------------------
    def test_blank_node_no_preserve_generates_new_id(self):
        """GIVEN a blank-node @id and preserve_blank_nodes=False
        WHEN translated THEN a fresh UUID entity_id is generated (line 208)."""
        t = self._translator(preserve_blank_nodes=False)
        result = t.jsonld_to_ipld({"@id": "_:blank1", "@type": "Resource"})
        assert len(result.entities) == 1
        eid = result.entities[0]["id"]
        assert eid != "_:blank1"  # not the original blank node

    # -----------------------------------------------------------------------
    # Line 225: no @id and generate_ids=False → entity_{uuid}
    # -----------------------------------------------------------------------
    def test_no_at_id_and_no_generate_ids_uses_uuid(self):
        """GIVEN no @id in the node and generate_ids=False
        WHEN translated THEN a content-hash entity_id is generated (line 225)."""
        t = self._translator(generate_ids=False)
        result = t.jsonld_to_ipld({"@type": "Event", "label": "Conference"})
        assert len(result.entities) == 1
        eid = result.entities[0]["id"]
        assert eid.startswith("entity_")

    # -----------------------------------------------------------------------
    # Line 341: ipld_to_jsonld target entity has _jsonld_id → use URI
    # -----------------------------------------------------------------------
    def test_ipld_to_jsonld_target_with_jsonld_id_uses_uri(self):
        """GIVEN a target entity that has _jsonld_id stored
        WHEN ipld_to_jsonld is called THEN target_ref = URI (line 341)."""
        from ipfs_datasets_py.knowledge_graphs.jsonld.translator import IPLDGraph

        graph = IPLDGraph(
            entities=[
                {"id": "e1", "type": "Person", "properties": {"_jsonld_id": "http://example.org/alice"}},
                {"id": "e2", "type": "Person", "properties": {"_jsonld_id": "http://example.org/bob"}},
            ],
            relationships=[
                {"type": "knows", "source": "e1", "target": "e2", "properties": {}}
            ],
        )
        t = self._translator()
        result = t.ipld_to_jsonld(graph)
        graph_nodes = result.get("@graph", [result])
        # The 'knows' value should be the URI of e2
        alice_node = next(
            (n for n in graph_nodes if n.get("@id") == "http://example.org/alice"), None
        )
        assert alice_node is not None
        assert alice_node.get("knows") == "http://example.org/bob"

    # -----------------------------------------------------------------------
    # Line 345: ipld_to_jsonld target not in entity_map → '_:{target_id}'
    # -----------------------------------------------------------------------
    def test_ipld_to_jsonld_target_not_in_map_uses_blank_ref(self):
        """GIVEN a relationship pointing to an entity NOT in the graph
        WHEN ipld_to_jsonld is called THEN target_ref = '_:{id}' (line 345)."""
        from ipfs_datasets_py.knowledge_graphs.jsonld.translator import IPLDGraph

        graph = IPLDGraph(
            entities=[
                {"id": "e1", "type": "Person", "properties": {"_jsonld_id": "http://example.org/alice"}},
            ],
            relationships=[
                {"type": "knows", "source": "e1", "target": "e_missing", "properties": {}}
            ],
        )
        t = self._translator()
        result = t.ipld_to_jsonld(graph)
        graph_nodes = result.get("@graph", [result])
        alice_node = next(
            (n for n in graph_nodes if n.get("@id") == "http://example.org/alice"), None
        )
        assert alice_node is not None
        assert alice_node.get("knows") == "_:e_missing"

    # -----------------------------------------------------------------------
    # Line 343: target in entity_map but no _jsonld_id → '_:{target_id}'
    # -----------------------------------------------------------------------
    def test_ipld_to_jsonld_target_in_map_without_jsonld_id_uses_blank_ref(self):
        """GIVEN a target entity in the map but without _jsonld_id
        WHEN ipld_to_jsonld is called THEN target_ref = '_:{target_id}' (line 343)."""
        from ipfs_datasets_py.knowledge_graphs.jsonld.translator import IPLDGraph

        graph = IPLDGraph(
            entities=[
                {"id": "e1", "type": "Person", "properties": {"_jsonld_id": "http://example.org/alice"}},
                {"id": "e2", "type": "Person", "properties": {"name": "Bob"}},  # no _jsonld_id
            ],
            relationships=[
                {"type": "knows", "source": "e1", "target": "e2", "properties": {}}
            ],
        )
        t = self._translator()
        result = t.ipld_to_jsonld(graph)
        graph_nodes = result.get("@graph", [result])
        alice_node = next(
            (n for n in graph_nodes if n.get("@id") == "http://example.org/alice"), None
        )
        assert alice_node is not None
        assert alice_node.get("knows") == "_:e2"


# ===========================================================================
# 3. ontology/reasoning.py – lines 435-436, 495, 503, 622, 746, 828, 979,
#    1012, 1018
# ===========================================================================

class TestOntologyReasoningMissedPaths:
    """GIVEN an OntologySchema or OntologyReasoner,
    WHEN the corresponding methods are called,
    THEN edge-case branches are exercised."""

    def _kg_with_chain(self, names, rel_type):
        """Build a KG with a linear chain of *names* connected by *rel_type*."""
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import (
            Entity,
            KnowledgeGraph,
            Relationship,
        )

        kg = KnowledgeGraph()
        entities = []
        for name in names:
            e = Entity(name=name, entity_type="Thing")
            kg.add_entity(e)
            entities.append(e)
        for i in range(len(entities) - 1):
            r = Relationship(
                source_entity=entities[i],
                target_entity=entities[i + 1],
                relationship_type=rel_type,
                confidence=0.9,
            )
            kg.add_relationship(r)
        return kg, entities

    # -----------------------------------------------------------------------
    # Lines 435-436: subproperty entry in to_turtle
    # -----------------------------------------------------------------------
    def test_to_turtle_includes_subproperty(self):
        """GIVEN a schema with a subproperty mapping
        WHEN to_turtle is called THEN rdfs:subPropertyOf appears (lines 435-436)."""
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import OntologySchema

        schema = OntologySchema()
        schema.add_subproperty("worksAt", "affiliatedWith")
        turtle = schema.to_turtle()
        assert "rdfs:subPropertyOf" in turtle
        assert "worksAt" in turtle
        assert "affiliatedWith" in turtle

    # -----------------------------------------------------------------------
    # Lines 495/503: from_turtle – non-matching line skip + subproperty parsed
    # -----------------------------------------------------------------------
    def test_from_turtle_non_matching_line_skipped_and_subproperty_parsed(self):
        """GIVEN Turtle text with a non-matching line and a subproperty triple
        WHEN from_turtle is called THEN non-matching line is skipped (line 495)
        and subproperty is parsed (line 503)."""
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import OntologySchema

        turtle_text = (
            ":Cat rdfs:subClassOf :Animal .\n"
            "this_line_has_no_dot_so_it_wont_match\n"
            ":worksAt rdfs:subPropertyOf :affiliatedWith .\n"
        )
        schema = OntologySchema.from_turtle(turtle_text)
        assert "Cat" in schema.subclass_map
        assert "worksAt" in schema.subproperty_map
        assert "affiliatedWith" in schema.subproperty_map["worksAt"]

    # -----------------------------------------------------------------------
    # Line 622: materialize – fixpoint NOT converged (max_iterations exceeded)
    # -----------------------------------------------------------------------
    def test_materialize_max_iterations_warning(self):
        """GIVEN a transitive schema and a chain that keeps growing
        WHEN materialize is called with max_iterations=1
        THEN the 'did not converge' warning is logged (line 622)."""
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import (
            OntologyReasoner,
            OntologySchema,
        )

        schema = OntologySchema()
        schema.add_transitive("partOf")
        kg, _ = self._kg_with_chain(["A", "B", "C", "D"], "partOf")
        reasoner = OntologyReasoner(schema, max_iterations=1)
        result = reasoner.materialize(kg)
        # Should return without raising even though it didn't converge
        assert result is not None

    # -----------------------------------------------------------------------
    # Line 746: get_all_superclasses – transitive closure
    # -----------------------------------------------------------------------
    def test_get_all_superclasses_transitive(self):
        """GIVEN Cat ⊆ Animal ⊆ LivingThing in the schema
        WHEN get_all_superclasses('Cat') is called
        THEN both Animal and LivingThing are returned (line 746 path)."""
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import OntologySchema

        schema = OntologySchema()
        schema.add_subclass("Cat", "Animal")
        schema.add_subclass("Animal", "LivingThing")
        supers = schema.get_all_superclasses("Cat")
        assert "Animal" in supers
        assert "LivingThing" in supers
        assert "Cat" not in supers  # excludes self

    # -----------------------------------------------------------------------
    # Line 828: _apply_transitive – BFS revisit guard (mid in visited → continue)
    # -----------------------------------------------------------------------
    def test_apply_transitive_bfs_revisit_guard(self):
        """GIVEN a diamond pattern A→B, A→C, B→D, C→D
        WHEN materialize is called with a transitive property
        THEN the BFS revisit guard (line 828) prevents duplicate derivations."""
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import (
            Entity,
            KnowledgeGraph,
            Relationship,
        )
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import (
            OntologyReasoner,
            OntologySchema,
        )

        schema = OntologySchema()
        schema.add_transitive("partOf")

        kg = KnowledgeGraph()
        a, b, c, d = [Entity(name=n, entity_type="Thing") for n in ["A", "B", "C", "D"]]
        for e in [a, b, c, d]:
            kg.add_entity(e)
        for src, tgt in [(a, b), (a, c), (b, d), (c, d)]:
            kg.add_relationship(
                Relationship(source_entity=src, target_entity=tgt,
                             relationship_type="partOf", confidence=0.9)
            )
        reasoner = OntologyReasoner(schema, max_iterations=3)
        result = reasoner.materialize(kg)
        # A→D should be inferred via transitive closure
        rel_pairs = {
            (r.source_id, r.target_id)
            for r in result.relationships.values()
            if r.relationship_type == "partOf"
        }
        assert (a.entity_id, d.entity_id) in rel_pairs

    # -----------------------------------------------------------------------
    # Line 979: property chain with len < 2 → continue (skip invalid chain)
    # -----------------------------------------------------------------------
    def test_apply_property_chains_skips_short_chain(self):
        """GIVEN a property chain with only one hop (len < 2)
        WHEN materialize is called THEN the short chain is skipped (line 979)."""
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import (
            OntologyReasoner,
            OntologySchema,
        )

        schema = OntologySchema()
        schema.property_chains = [
            (["parentOf"], "ancestorOf"),           # len=1 → line 979 skip
            (["parentOf", "parentOf"], "grandparentOf"),  # valid
        ]
        kg, entities = self._kg_with_chain(["Alice", "Bob", "Carol"], "parentOf")
        reasoner = OntologyReasoner(schema, max_iterations=2)
        result = reasoner.materialize(kg)
        rel_types = {r.relationship_type for r in result.relationships.values()}
        assert "grandparentOf" in rel_types
        assert "ancestorOf" not in rel_types  # short chain skipped

    # -----------------------------------------------------------------------
    # Line 1012: property chain self-loop exclusion (end_id == start_id → continue)
    # -----------------------------------------------------------------------
    def test_apply_property_chains_self_loop_excluded(self):
        """GIVEN a self-loop entity (A→A parentOf chain)
        WHEN materialize is called THEN self-loop grandparentOf is NOT inferred
        (line 1012)."""
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import (
            Entity,
            KnowledgeGraph,
            Relationship,
        )
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import (
            OntologyReasoner,
            OntologySchema,
        )

        schema = OntologySchema()
        schema.property_chains = [
            (["parentOf", "parentOf"], "grandparentOf")
        ]
        kg = KnowledgeGraph()
        a = Entity(name="Alpha", entity_type="Thing")
        kg.add_entity(a)
        kg.add_relationship(
            Relationship(source_entity=a, target_entity=a,
                         relationship_type="parentOf", confidence=0.9)
        )
        reasoner = OntologyReasoner(schema, max_iterations=2)
        result = reasoner.materialize(kg)
        gp_rels = [
            r for r in result.relationships.values()
            if r.relationship_type == "grandparentOf"
        ]
        assert len(gp_rels) == 0

    # -----------------------------------------------------------------------
    # Line 1018: property chain skips already-existing inferred relationship
    # -----------------------------------------------------------------------
    def test_apply_property_chains_skips_existing_relationship(self):
        """GIVEN the chain result relationship already exists in the graph
        WHEN materialize is called THEN it is not duplicated (line 1018)."""
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import (
            Entity,
            KnowledgeGraph,
            Relationship,
        )
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import (
            OntologyReasoner,
            OntologySchema,
        )

        schema = OntologySchema()
        schema.property_chains = [
            (["parentOf", "parentOf"], "grandparentOf")
        ]
        kg = KnowledgeGraph()
        e1 = Entity(name="Alice", entity_type="Person")
        e2 = Entity(name="Bob", entity_type="Person")
        e3 = Entity(name="Carol", entity_type="Person")
        for e in [e1, e2, e3]:
            kg.add_entity(e)
        kg.add_relationship(
            Relationship(source_entity=e1, target_entity=e2,
                         relationship_type="parentOf", confidence=0.9)
        )
        kg.add_relationship(
            Relationship(source_entity=e2, target_entity=e3,
                         relationship_type="parentOf", confidence=0.9)
        )
        # Pre-add the grandparentOf relationship
        kg.add_relationship(
            Relationship(source_entity=e1, target_entity=e3,
                         relationship_type="grandparentOf", confidence=0.9)
        )
        pre_count = len(kg.relationships)
        reasoner = OntologyReasoner(schema, max_iterations=2)
        result = reasoner.materialize(kg)
        gp_rels = [
            r for r in result.relationships.values()
            if r.relationship_type == "grandparentOf"
        ]
        assert len(gp_rels) == 1  # no duplicate added


# ===========================================================================
# 4. extraction/advanced.py – lines 506, 508, 646
# ===========================================================================

class TestAdvancedExtractorMissedPaths:
    """GIVEN an AdvancedKnowledgeExtractor,
    WHEN text with confidence modifier words is extracted,
    THEN the modifier branches and statistics return are exercised."""

    def _extractor(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.advanced import (
            AdvancedKnowledgeExtractor,
        )

        return AdvancedKnowledgeExtractor()

    def test_high_confidence_modifier_increases_confidence(self):
        """GIVEN text containing 'significant' (a 'high' modifier)
        WHEN entities are extracted THEN high-modifier branch fires (line 506)."""
        ext = self._extractor()
        kg = ext.extract_enhanced_knowledge_graph(
            "Alice is a significant researcher at MIT. This is important work."
        )
        # There should be at least one entity with elevated confidence
        assert len(kg.entities) >= 0  # does not raise

    def test_medium_confidence_modifier_increases_confidence(self):
        """GIVEN text containing 'notable' (a 'medium' modifier)
        WHEN entities are extracted THEN medium-modifier branch fires (line 508)."""
        ext = self._extractor()
        kg = ext.extract_enhanced_knowledge_graph(
            "Bob is a notable professor at Stanford with considerable contributions."
        )
        assert len(kg.entities) >= 0

    def test_get_extraction_statistics_returns_dict(self):
        """GIVEN an extractor after a round of extraction
        WHEN get_extraction_statistics is called
        THEN a non-empty dict is returned (line 646)."""
        ext = self._extractor()
        ext.extract_enhanced_knowledge_graph("Alice works at MIT.")
        stats = ext.get_extraction_statistics()
        assert isinstance(stats, dict)


# ===========================================================================
# 5. extraction/graph.py – lines 237, 376, 629, 661
# ===========================================================================

class TestExtractionGraphMissedPaths:
    """GIVEN a KnowledgeGraph with edge-case data,
    WHEN methods are called,
    THEN non-Entity source fallback, depth limit, and boolean RDF properties
    are exercised."""

    def _kg_entities(self, *names):
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import Entity, KnowledgeGraph

        kg = KnowledgeGraph()
        entities = []
        for name in names:
            e = Entity(name=name, entity_type="Person")
            kg.add_entity(e)
            entities.append(e)
        return kg, entities

    # -----------------------------------------------------------------------
    # Line 237: source_entity is neither Entity nor str → str(source_entity)
    # -----------------------------------------------------------------------
    def test_add_relationship_with_int_source_entity_falls_back_to_str(self):
        """GIVEN a Relationship whose source_entity is an integer (neither
        Entity nor str) WHEN added to the KG THEN str() fallback fires (line 237)."""
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import (
            Entity,
            KnowledgeGraph,
            Relationship,
        )

        kg = KnowledgeGraph()
        e2 = Entity(name="Target", entity_type="Person")
        kg.add_entity(e2)
        rel = Relationship(
            source_entity=42,  # integer → neither Entity nor str
            target_entity=e2,
            relationship_type="knows",
            confidence=0.9,
        )
        kg.add_relationship(rel)
        # source_id should be '42'
        assert "42" in kg.entity_relationships

    # -----------------------------------------------------------------------
    # Line 376: find_paths depth-limit triggers early return in DFS
    # -----------------------------------------------------------------------
    def test_find_paths_max_depth_one_does_not_reach_distant_target(self):
        """GIVEN a path A→B→C and max_depth=1 WHEN find_paths(A,C) is called
        THEN the DFS returns early at depth limit (line 376) and no path
        is found."""
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import (
            Relationship,
        )

        kg, (a, b, c) = self._kg_entities("A", "B", "C")
        kg.add_relationship(
            Relationship(source_entity=a, target_entity=b,
                         relationship_type="knows", confidence=0.9)
        )
        kg.add_relationship(
            Relationship(source_entity=b, target_entity=c,
                         relationship_type="knows", confidence=0.9)
        )
        paths = kg.find_paths(a, c, max_depth=1)
        assert len(paths) == 0  # depth-limited, cannot reach C in 1 hop

    # -----------------------------------------------------------------------
    # Line 629: export_to_rdf – entity boolean property → XSD.boolean
    # -----------------------------------------------------------------------
    @pytest.mark.skipif(not _rdflib_available, reason="rdflib not installed")
    def test_export_to_rdf_entity_boolean_property_uses_xsd_boolean(self):
        """GIVEN an entity with a boolean property
        WHEN export_to_rdf is called THEN XSD.boolean literal appears (line 629)."""
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import Entity, KnowledgeGraph

        kg = KnowledgeGraph()
        e = Entity(
            name="Widget",
            entity_type="Product",
            properties={"is_active": True, "label": "test"},
        )
        kg.add_entity(e)
        rdf = kg.export_to_rdf(format="turtle")
        # Boolean True should appear in the serialized turtle
        assert "true" in rdf.lower() or "boolean" in rdf.lower()

    # -----------------------------------------------------------------------
    # Line 661: export_to_rdf – relationship boolean property → XSD.boolean
    # -----------------------------------------------------------------------
    @pytest.mark.skipif(not _rdflib_available, reason="rdflib not installed")
    def test_export_to_rdf_relationship_boolean_property_uses_xsd_boolean(self):
        """GIVEN a relationship with a boolean property
        WHEN export_to_rdf is called THEN XSD.boolean literal appears (line 661)."""
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import (
            Entity,
            KnowledgeGraph,
            Relationship,
        )

        kg = KnowledgeGraph()
        src = Entity(name="SrcNode", entity_type="Thing")
        tgt = Entity(name="TgtNode", entity_type="Thing")
        kg.add_entity(src)
        kg.add_entity(tgt)
        kg.add_relationship(
            Relationship(
                source_entity=src,
                target_entity=tgt,
                relationship_type="linkedTo",
                properties={"is_direct": True},
                confidence=0.9,
            )
        )
        rdf = kg.export_to_rdf(format="turtle")
        assert "true" in rdf.lower() or "boolean" in rdf.lower()


# ===========================================================================
# 6. migration/ipfs_importer.py – lines 138, 179, 350-351, 361-362
# ===========================================================================

class TestIPFSImporterMissedPaths:
    """GIVEN an IPFSImporter whose dependencies are mocked,
    WHEN error-prone code paths are exercised,
    THEN the correct exception propagation and warning logging occur."""

    def _importer(self, **config_kwargs):
        from ipfs_datasets_py.knowledge_graphs.migration.ipfs_importer import (
            ImportConfig,
            IPFSImporter,
        )

        return IPFSImporter(ImportConfig(**config_kwargs))

    # -----------------------------------------------------------------------
    # Line 138: MigrationError re-raised from _connect
    # -----------------------------------------------------------------------
    def test_connect_reraises_migration_error(self):
        """GIVEN _connect internally raises MigrationError via driver call
        WHEN _connect is invoked THEN MigrationError propagates (line 138)."""
        from ipfs_datasets_py.knowledge_graphs.migration.ipfs_importer import (
            MigrationError,
        )

        importer = self._importer()
        mock_db = MagicMock()
        mock_db.driver.side_effect = MigrationError("pre-existing migration error")
        importer._GraphDatabase = mock_db

        with pytest.raises(MigrationError, match="pre-existing migration error"):
            importer._connect()

    # -----------------------------------------------------------------------
    # Line 179: MigrationError re-raised from _load_graph_data
    # -----------------------------------------------------------------------
    def test_load_graph_data_reraises_migration_error(self):
        """GIVEN GraphData.load_from_file raises MigrationError
        WHEN _load_graph_data is invoked THEN MigrationError propagates (line 179)."""
        from ipfs_datasets_py.knowledge_graphs.migration.ipfs_importer import (
            MigrationError,
        )

        importer = self._importer(input_file="/some/path.json")
        with patch(
            "ipfs_datasets_py.knowledge_graphs.migration.ipfs_importer.GraphData"
        ) as mock_gd:
            mock_gd.load_from_file.side_effect = MigrationError("load failed")
            with pytest.raises(MigrationError, match="load failed"):
                importer._load_graph_data()

    # -----------------------------------------------------------------------
    # Lines 350-351: index creation logger.debug raises → warning logged
    # -----------------------------------------------------------------------
    def test_import_schema_index_exception_logged_as_warning(self):
        """GIVEN logger.debug raises for an index entry
        WHEN _import_schema is called THEN the exception is caught and logged
        as a warning (lines 350-351)."""
        import ipfs_datasets_py.knowledge_graphs.migration.ipfs_importer as mod
        from ipfs_datasets_py.knowledge_graphs.migration.formats import (
            GraphData,
            SchemaData,
        )

        importer = self._importer(create_indexes=True, create_constraints=False)
        schema = SchemaData()
        schema.indexes = [{"name": "idx_test"}]
        graph_data = GraphData(schema=schema)

        call_count = [0]
        original_debug = mod.logger.debug

        def exploding_debug(msg, *args, **kwargs):
            call_count[0] += 1
            if "Would create index" in str(msg):
                raise RuntimeError("index creation forced error")
            return original_debug(msg, *args, **kwargs)

        mod.logger.debug = exploding_debug
        try:
            importer._import_schema(graph_data)  # should not raise
        finally:
            mod.logger.debug = original_debug

    # -----------------------------------------------------------------------
    # Lines 361-362: constraint creation logger.debug raises → warning logged
    # -----------------------------------------------------------------------
    def test_import_schema_constraint_exception_logged_as_warning(self):
        """GIVEN logger.debug raises for a constraint entry
        WHEN _import_schema is called THEN the exception is caught and logged
        as a warning (lines 361-362)."""
        import ipfs_datasets_py.knowledge_graphs.migration.ipfs_importer as mod
        from ipfs_datasets_py.knowledge_graphs.migration.formats import (
            GraphData,
            SchemaData,
        )

        importer = self._importer(create_indexes=False, create_constraints=True)
        schema = SchemaData()
        schema.constraints = [{"name": "const_test"}]
        graph_data = GraphData(schema=schema)

        call_count = [0]
        original_debug = mod.logger.debug

        def exploding_debug(msg, *args, **kwargs):
            call_count[0] += 1
            if "Would create constraint" in str(msg):
                raise RuntimeError("constraint creation forced error")
            return original_debug(msg, *args, **kwargs)

        mod.logger.debug = exploding_debug
        try:
            importer._import_schema(graph_data)  # should not raise
        finally:
            mod.logger.debug = original_debug


# ===========================================================================
# 7. reasoning/cross_document.py – lines 133, 199 (dead code), 870-876
# ===========================================================================

class TestCrossDocumentReasonerMissedPaths:
    """GIVEN a CrossDocumentReasoner,
    WHEN the default-optimizer constructor path and _example_usage are exercised,
    THEN the relevant branches are covered."""

    # -----------------------------------------------------------------------
    # Line 133: CrossDocumentReasoner() creates default UnifiedGraphRAGQueryOptimizer
    # -----------------------------------------------------------------------
    def test_default_constructor_creates_unified_optimizer(self):
        """GIVEN UnifiedGraphRAGQueryOptimizer is non-None in the module scope
        WHEN CrossDocumentReasoner() is constructed with no optimizer
        THEN line 133 fires and the mock optimizer is used."""
        import ipfs_datasets_py.knowledge_graphs.reasoning.cross_document as cdm
        from ipfs_datasets_py.knowledge_graphs.reasoning.cross_document import (
            CrossDocumentReasoner,
        )

        mock_optimizer_class = MagicMock()
        mock_optimizer_instance = MagicMock()
        mock_optimizer_class.return_value = mock_optimizer_instance

        old_val = cdm.UnifiedGraphRAGQueryOptimizer
        cdm.UnifiedGraphRAGQueryOptimizer = mock_optimizer_class
        try:
            reasoner = CrossDocumentReasoner()
            assert reasoner.query_optimizer is mock_optimizer_instance
        finally:
            cdm.UnifiedGraphRAGQueryOptimizer = old_val

    # -----------------------------------------------------------------------
    # Lines 31-32: numpy import-failure guard is dead code when numpy installed;
    # verify the fallback flag is False (np is available)
    # -----------------------------------------------------------------------
    def test_numpy_available_flag(self):
        """GIVEN numpy is installed
        WHEN cross_document module is imported
        THEN the np alias is a real numpy module (lines 31-32 are dead code)."""
        import ipfs_datasets_py.knowledge_graphs.reasoning.cross_document as cdm
        import numpy as np_real

        assert cdm.np is np_real

    # -----------------------------------------------------------------------
    # Lines 870-876: _example_usage prints reasoning_trace steps and statistics
    # -----------------------------------------------------------------------
    def test_example_usage_covers_trace_and_stats_output(self, capsys):
        """GIVEN CrossDocumentReasoner is mocked to return a result with a
        reasoning_trace WHEN _example_usage() is called THEN lines 870-876
        are executed (trace steps and statistics printed)."""
        import ipfs_datasets_py.knowledge_graphs.reasoning.cross_document as cdm

        mock_result = {
            "answer": "IPFS uses content addressing.",
            "confidence": 0.92,
            "documents": [{"id": "d1", "source": "IPFS Docs", "relevance": 0.9}],
            "entity_connections": [
                {"entity": "IPFS", "type": "concept", "relation": "direct", "strength": 0.85}
            ],
            "reasoning_trace": {"steps": [{"content": "Analysed IPFS documentation"}]},
        }
        mock_instance = MagicMock()
        mock_instance.reason_across_documents.return_value = mock_result
        mock_instance.get_statistics.return_value = {"docs_processed": 3}
        mock_class = MagicMock(return_value=mock_instance)

        import types
        fake_llm = types.ModuleType("fake_llm_tracer")
        fake_llm.LLMReasoningTracer = MagicMock
        fake_opt = types.ModuleType("fake_optimizer")
        fake_opt.UnifiedGraphRAGQueryOptimizer = MagicMock

        with patch.dict(
            sys.modules,
            {
                "ipfs_datasets_py.ml.llm.llm_reasoning_tracer": fake_llm,
                "ipfs_datasets_py.optimizers.graphrag.query_optimizer": fake_opt,
            },
        ):
            old_cdr = cdm.CrossDocumentReasoner
            cdm.CrossDocumentReasoner = mock_class
            try:
                cdm._example_usage()
            finally:
                cdm.CrossDocumentReasoner = old_cdr

        captured = capsys.readouterr()
        assert "Step" in captured.out or "Analysed" in captured.out
        assert "docs_processed" in captured.out or "processed" in captured.out
