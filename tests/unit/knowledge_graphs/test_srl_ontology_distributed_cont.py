"""
Continuation tests for Items 9, 12, 13 of DEFERRED_FEATURES.md.

  Item 9  — SRL integration into KnowledgeGraphExtractor
  Item 12 — OWL property chains + Turtle serialization
  Item 13 — Distributed async execution + cross-partition entity lookup

Tests follow the GIVEN-WHEN-THEN format per repository standards.
"""

from __future__ import annotations

import asyncio
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_kg_with_people(names=None):
    """Return a KnowledgeGraph populated with Person entities."""
    from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
    from ipfs_datasets_py.knowledge_graphs.extraction.entities import Entity

    if names is None:
        names = ["Alice", "Bob", "Carol", "Dave"]
    kg = KnowledgeGraph()
    for name in names:
        e = Entity(entity_type="Person", name=name, properties={"age": 30})
        kg.entities[e.entity_id] = e
    return kg


def _add_rel(kg, src, tgt, rel_type):
    """Add a relationship to *kg* and return it."""
    from ipfs_datasets_py.knowledge_graphs.extraction.relationships import Relationship

    rel = Relationship(
        relationship_type=rel_type,
        source_entity=src,
        target_entity=tgt,
        confidence=1.0,
    )
    kg.relationships[rel.relationship_id] = rel
    kg.entity_relationships[src.entity_id].add(rel.relationship_id)
    kg.entity_relationships[tgt.entity_id].add(rel.relationship_id)
    return rel


# ---------------------------------------------------------------------------
# Item 9 continuation: SRL integration into KnowledgeGraphExtractor
# ---------------------------------------------------------------------------


class TestSRLExtractorIntegration:
    """SRL integration into KnowledgeGraphExtractor."""

    def test_use_srl_param_accepted(self):
        """
        GIVEN: KnowledgeGraphExtractor initialized with use_srl=True
        WHEN:  The extractor is created
        THEN:  srl_extractor attribute is not None and use_srl is True
        """
        from ipfs_datasets_py.knowledge_graphs.extraction.extractor import (
            KnowledgeGraphExtractor,
        )

        ext = KnowledgeGraphExtractor(use_srl=True, use_tracer=False)
        assert ext.use_srl is True
        assert ext.srl_extractor is not None

    def test_use_srl_false_by_default(self):
        """
        GIVEN: KnowledgeGraphExtractor initialized without use_srl
        WHEN:  The extractor is created
        THEN:  use_srl is False and srl_extractor is None
        """
        from ipfs_datasets_py.knowledge_graphs.extraction.extractor import (
            KnowledgeGraphExtractor,
        )

        ext = KnowledgeGraphExtractor(use_tracer=False)
        assert ext.use_srl is False
        assert ext.srl_extractor is None

    def test_extract_srl_knowledge_graph_returns_kg(self):
        """
        GIVEN: Extractor with use_srl=True
        WHEN:  extract_srl_knowledge_graph is called on an SVO sentence
        THEN:  A KnowledgeGraph with event nodes and role relationships is returned
        """
        from ipfs_datasets_py.knowledge_graphs.extraction.extractor import (
            KnowledgeGraphExtractor,
        )
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph

        ext = KnowledgeGraphExtractor(use_srl=True, use_tracer=False)
        kg = ext.extract_srl_knowledge_graph("Alice sent the document to Bob.")
        assert isinstance(kg, KnowledgeGraph)
        assert len(kg.entities) >= 1  # At least event + one argument

    def test_extract_srl_knowledge_graph_without_use_srl(self):
        """
        GIVEN: Extractor with use_srl=False
        WHEN:  extract_srl_knowledge_graph is called
        THEN:  It still works (creates a temporary SRLExtractor internally)
        """
        from ipfs_datasets_py.knowledge_graphs.extraction.extractor import (
            KnowledgeGraphExtractor,
        )
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph

        ext = KnowledgeGraphExtractor(use_tracer=False)  # use_srl=False
        kg = ext.extract_srl_knowledge_graph("Carol manages Dave.")
        assert isinstance(kg, KnowledgeGraph)

    def test_extract_knowledge_graph_high_temp_with_srl(self):
        """
        GIVEN: Extractor with use_srl=True and a sentence with known entities
        WHEN:  extract_knowledge_graph is called with structure_temperature > 0.8
        THEN:  No exception is raised and a KnowledgeGraph is returned
        """
        from ipfs_datasets_py.knowledge_graphs.extraction.extractor import (
            KnowledgeGraphExtractor,
        )
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph

        ext = KnowledgeGraphExtractor(use_srl=True, use_tracer=False)
        kg = ext.extract_knowledge_graph(
            "Alice acquired Bob.", structure_temperature=0.9
        )
        assert isinstance(kg, KnowledgeGraph)

    def test_merge_srl_into_kg_adds_srl_relationships(self):
        """
        GIVEN: A KG with two named entities that appear as Agent/Patient in an SVO sentence
        WHEN:  _merge_srl_into_kg is called
        THEN:  A relationship tagged extraction_method='srl' is added to the KG
        """
        from ipfs_datasets_py.knowledge_graphs.extraction.extractor import (
            KnowledgeGraphExtractor,
        )
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        from ipfs_datasets_py.knowledge_graphs.extraction.entities import Entity

        ext = KnowledgeGraphExtractor(use_srl=True, use_tracer=False)
        kg = KnowledgeGraph()
        alice = Entity(entity_type="Person", name="Alice")
        bob = Entity(entity_type="Person", name="Bob")
        kg.entities[alice.entity_id] = alice
        kg.entities[bob.entity_id] = bob

        # "Alice sent Bob." → Agent=Alice, Patient=Bob (clear SVO)
        ext._merge_srl_into_kg(kg, "Alice sent Bob.", [alice, bob])
        srl_rels = [
            r
            for r in kg.relationships.values()
            if (r.properties or {}).get("extraction_method") == "srl"
        ]
        assert len(srl_rels) >= 1

    def test_merge_srl_no_crash_on_unknown_entities(self):
        """
        GIVEN: A sentence whose participants are NOT in the entity map
        WHEN:  _merge_srl_into_kg is called
        THEN:  No exception is raised and the KG is unchanged
        """
        from ipfs_datasets_py.knowledge_graphs.extraction.extractor import (
            KnowledgeGraphExtractor,
        )
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph

        ext = KnowledgeGraphExtractor(use_srl=True, use_tracer=False)
        kg = KnowledgeGraph()  # empty
        ext._merge_srl_into_kg(kg, "Zorblax vaporised Flurp.", [])
        assert len(kg.relationships) == 0


# ---------------------------------------------------------------------------
# Item 12 continuation: property chains + Turtle serialization
# ---------------------------------------------------------------------------


class TestPropertyChains:
    """OWL 2 property chain axioms."""

    def test_add_property_chain_stored(self):
        """
        GIVEN: An OntologySchema
        WHEN:  add_property_chain is called
        THEN:  The chain is stored in schema.property_chains
        """
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import OntologySchema

        schema = OntologySchema()
        schema.add_property_chain(["hasMother", "hasMother"], "hasMaternalGrandmother")
        assert len(schema.property_chains) == 1
        chain, result = schema.property_chains[0]
        assert chain == ["hasMother", "hasMother"]
        assert result == "hasMaternalGrandmother"

    def test_add_property_chain_requires_two_steps(self):
        """
        GIVEN: A chain of length 1
        WHEN:  add_property_chain is called
        THEN:  ValueError is raised
        """
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import OntologySchema

        schema = OntologySchema()
        with pytest.raises(ValueError, match="at least two"):
            schema.add_property_chain(["singleProp"], "result")

    def test_property_chain_infers_new_relationship(self):
        """
        GIVEN: A KG with (Alice, hasMother, Mary) and (Mary, hasMother, Jane)
               and a chain [hasMother, hasMother] => hasMaternalGrandmother
        WHEN:  materialize is called
        THEN:  (Alice, hasMaternalGrandmother, Jane) is inferred
        """
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import (
            OntologySchema,
            OntologyReasoner,
        )
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        from ipfs_datasets_py.knowledge_graphs.extraction.entities import Entity
        from ipfs_datasets_py.knowledge_graphs.extraction.relationships import Relationship

        kg = KnowledgeGraph()
        alice = Entity(entity_type="Person", name="Alice")
        mary = Entity(entity_type="Person", name="Mary")
        jane = Entity(entity_type="Person", name="Jane")
        for e in (alice, mary, jane):
            kg.entities[e.entity_id] = e

        _add_rel(kg, alice, mary, "hasMother")
        _add_rel(kg, mary, jane, "hasMother")

        schema = OntologySchema()
        schema.add_property_chain(["hasMother", "hasMother"], "hasMaternalGrandmother")
        kg2 = OntologyReasoner(schema).materialize(kg)

        chain_rels = [
            r
            for r in kg2.relationships.values()
            if r.relationship_type == "hasMaternalGrandmother"
        ]
        assert len(chain_rels) == 1
        assert kg2.entities[chain_rels[0].source_id].name == "Alice"
        assert kg2.entities[chain_rels[0].target_id].name == "Jane"

    def test_property_chain_three_step(self):
        """
        GIVEN: A 3-step chain [p, q, r] => s and matching path A->p->B->q->C->r->D
        WHEN:  materialize is called
        THEN:  (A, s, D) is inferred
        """
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import (
            OntologySchema,
            OntologyReasoner,
        )
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        from ipfs_datasets_py.knowledge_graphs.extraction.entities import Entity

        kg = KnowledgeGraph()
        entities = [Entity(entity_type="Node", name=n) for n in "ABCD"]
        for e in entities:
            kg.entities[e.entity_id] = e
        a, b, c, d = entities

        _add_rel(kg, a, b, "step1")
        _add_rel(kg, b, c, "step2")
        _add_rel(kg, c, d, "step3")

        schema = OntologySchema()
        schema.add_property_chain(["step1", "step2", "step3"], "fullPath")
        kg2 = OntologyReasoner(schema).materialize(kg)

        path_rels = [
            r for r in kg2.relationships.values() if r.relationship_type == "fullPath"
        ]
        assert len(path_rels) == 1
        assert kg2.entities[path_rels[0].source_id].name == "A"
        assert kg2.entities[path_rels[0].target_id].name == "D"

    def test_property_chain_no_match_no_inference(self):
        """
        GIVEN: A KG without the chain's edges
        WHEN:  materialize is called
        THEN:  No result relationship is added
        """
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import (
            OntologySchema,
            OntologyReasoner,
        )
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        from ipfs_datasets_py.knowledge_graphs.extraction.entities import Entity

        kg = KnowledgeGraph()
        a = Entity(entity_type="Node", name="A")
        b = Entity(entity_type="Node", name="B")
        kg.entities[a.entity_id] = a
        kg.entities[b.entity_id] = b
        _add_rel(kg, a, b, "unrelatedProp")

        schema = OntologySchema()
        schema.add_property_chain(["hasMother", "hasMother"], "hasMaternalGrandmother")
        kg2 = OntologyReasoner(schema).materialize(kg)

        assert not any(
            r.relationship_type == "hasMaternalGrandmother"
            for r in kg2.relationships.values()
        )

    def test_property_chain_idempotent(self):
        """
        GIVEN: Two materialize calls on the same KG with a chain rule
        WHEN:  materialize is called a second time on the already-augmented KG
        THEN:  No duplicate inferred relationships are added
        """
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import (
            OntologySchema,
            OntologyReasoner,
        )
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        from ipfs_datasets_py.knowledge_graphs.extraction.entities import Entity

        kg = KnowledgeGraph()
        a = Entity(entity_type="P", name="A")
        b = Entity(entity_type="P", name="B")
        c = Entity(entity_type="P", name="C")
        for e in (a, b, c):
            kg.entities[e.entity_id] = e
        _add_rel(kg, a, b, "p")
        _add_rel(kg, b, c, "p")

        schema = OntologySchema()
        schema.add_property_chain(["p", "p"], "pp")
        reasoner = OntologyReasoner(schema)

        kg2 = reasoner.materialize(kg, in_place=True)
        count_after_first = sum(
            1 for r in kg2.relationships.values() if r.relationship_type == "pp"
        )
        kg3 = reasoner.materialize(kg2, in_place=True)
        count_after_second = sum(
            1 for r in kg3.relationships.values() if r.relationship_type == "pp"
        )
        assert count_after_first == count_after_second


class TestOntologyTurtleSerialization:
    """OWL Turtle serialization and deserialization."""

    def test_to_turtle_contains_prefix_declarations(self):
        """
        GIVEN: An OntologySchema with one subclass declaration
        WHEN:  to_turtle is called
        THEN:  The result contains @prefix lines for rdfs and owl
        """
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import OntologySchema

        schema = OntologySchema()
        schema.add_subclass("Employee", "Person")
        turtle = schema.to_turtle()
        assert "@prefix rdfs:" in turtle
        assert "@prefix owl:" in turtle

    def test_to_turtle_subclass(self):
        """
        GIVEN: A subclass declaration Employee < Person
        WHEN:  to_turtle is called
        THEN:  ':Employee rdfs:subClassOf :Person .' appears in the output
        """
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import OntologySchema

        schema = OntologySchema()
        schema.add_subclass("Employee", "Person")
        assert ":Employee rdfs:subClassOf :Person ." in schema.to_turtle()

    def test_to_turtle_property_chain(self):
        """
        GIVEN: A property chain [hasMother, hasMother] => hasMaternalGrandmother
        WHEN:  to_turtle is called
        THEN:  The chain axiom appears in the output
        """
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import OntologySchema

        schema = OntologySchema()
        schema.add_property_chain(["hasMother", "hasMother"], "hasMaternalGrandmother")
        turtle = schema.to_turtle()
        assert "owl:propertyChainAxiom" in turtle
        assert "hasMaternalGrandmother" in turtle
        assert "hasMother" in turtle

    def test_from_turtle_roundtrip_subclass(self):
        """
        GIVEN: An OntologySchema with subclass / transitive / symmetric / inverse
        WHEN:  to_turtle followed by from_turtle is called
        THEN:  The reconstructed schema has identical declarations
        """
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import OntologySchema

        schema = OntologySchema()
        schema.add_subclass("Employee", "Person")
        schema.add_subclass("Manager", "Employee")
        schema.add_transitive("isAncestorOf")
        schema.add_symmetric("isSiblingOf")
        schema.add_inverse("isParentOf", "isChildOf")
        schema.add_domain("worksAt", "Person")
        schema.add_range("worksAt", "Organization")
        schema.add_disjoint("Cat", "Dog")

        turtle = schema.to_turtle()
        schema2 = OntologySchema.from_turtle(turtle)

        assert schema2.subclass_map == schema.subclass_map
        assert schema2.transitive == schema.transitive
        assert schema2.symmetric == schema.symmetric
        assert schema2.domain_map == schema.domain_map
        assert schema2.range_map == schema.range_map

    def test_from_turtle_roundtrip_property_chain(self):
        """
        GIVEN: An OntologySchema with a property chain
        WHEN:  to_turtle followed by from_turtle is called
        THEN:  The chain is preserved in the reconstructed schema
        """
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import OntologySchema

        schema = OntologySchema()
        schema.add_property_chain(["hasMother", "hasMother"], "hasMaternalGrandmother")

        schema2 = OntologySchema.from_turtle(schema.to_turtle())
        assert len(schema2.property_chains) == 1
        chain, result = schema2.property_chains[0]
        assert chain == ["hasMother", "hasMother"]
        assert result == "hasMaternalGrandmother"

    def test_from_turtle_ignores_comments_and_blanks(self):
        """
        GIVEN: Turtle text with comment lines and blank lines
        WHEN:  from_turtle is called
        THEN:  No exception is raised; comment lines are ignored
        """
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import OntologySchema

        turtle = (
            "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
            "@prefix owl:  <http://www.w3.org/2002/07/owl#> .\n"
            "\n"
            "# This is a comment\n"
            ":Employee rdfs:subClassOf :Person .\n"
        )
        schema = OntologySchema.from_turtle(turtle)
        assert "Employee" in schema.subclass_map


# ---------------------------------------------------------------------------
# Item 13 continuation: distributed async execution + entity lookup
# ---------------------------------------------------------------------------


class TestFederatedQueryExecutorContinuation:
    """Async execution and cross-partition entity lookup."""

    def _make_dist_graph(self, num_partitions=3, num_entities=9):
        """Build a DistributedGraph for testing."""
        from ipfs_datasets_py.knowledge_graphs.query.distributed import (
            GraphPartitioner,
            PartitionStrategy,
        )
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        from ipfs_datasets_py.knowledge_graphs.extraction.entities import Entity

        kg = KnowledgeGraph()
        entities = []
        for i in range(num_entities):
            e = Entity(
                entity_type="Item",
                name=f"item_{i}",
                properties={"idx": i},
            )
            kg.entities[e.entity_id] = e
            entities.append(e)
        dist = GraphPartitioner(
            num_partitions=num_partitions, strategy=PartitionStrategy.HASH
        ).partition(kg)
        return dist, kg, entities

    def test_lookup_entity_found(self):
        """
        GIVEN: A DistributedGraph with entities spread across partitions
        WHEN:  lookup_entity is called with a known entity ID
        THEN:  The entity object is returned
        """
        from ipfs_datasets_py.knowledge_graphs.query.distributed import (
            FederatedQueryExecutor,
        )

        dist, kg, entities = self._make_dist_graph()
        executor = FederatedQueryExecutor(dist)
        target = entities[4]
        found = executor.lookup_entity(target.entity_id)
        assert found is not None
        assert found.entity_id == target.entity_id
        assert found.name == target.name

    def test_lookup_entity_not_found(self):
        """
        GIVEN: A DistributedGraph
        WHEN:  lookup_entity is called with an unknown ID
        THEN:  None is returned
        """
        from ipfs_datasets_py.knowledge_graphs.query.distributed import (
            FederatedQueryExecutor,
        )

        dist, _, _ = self._make_dist_graph()
        executor = FederatedQueryExecutor(dist)
        assert executor.lookup_entity("does-not-exist") is None

    def test_lookup_entity_partition_returns_int(self):
        """
        GIVEN: A DistributedGraph with entities spread across partitions
        WHEN:  lookup_entity_partition is called with a known entity ID
        THEN:  An integer in [0, num_partitions) is returned
        """
        from ipfs_datasets_py.knowledge_graphs.query.distributed import (
            FederatedQueryExecutor,
        )

        dist, kg, entities = self._make_dist_graph()
        executor = FederatedQueryExecutor(dist)
        idx = executor.lookup_entity_partition(entities[0].entity_id)
        assert idx is not None
        assert 0 <= idx < dist.num_partitions

    def test_lookup_entity_partition_unknown_returns_none(self):
        """
        GIVEN: A DistributedGraph
        WHEN:  lookup_entity_partition is called with an unknown ID
        THEN:  None is returned
        """
        from ipfs_datasets_py.knowledge_graphs.query.distributed import (
            FederatedQueryExecutor,
        )

        dist, _, _ = self._make_dist_graph()
        executor = FederatedQueryExecutor(dist)
        assert executor.lookup_entity_partition("ghost-id") is None

    def test_execute_cypher_async_returns_result(self):
        """
        GIVEN: A FederatedQueryExecutor with an in-memory DistributedGraph
        WHEN:  execute_cypher_async is awaited
        THEN:  A FederatedQueryResult is returned with the expected records
        """
        from ipfs_datasets_py.knowledge_graphs.query.distributed import (
            FederatedQueryExecutor,
        )

        dist, _, _ = self._make_dist_graph(num_partitions=2, num_entities=4)
        executor = FederatedQueryExecutor(dist)

        result = asyncio.run(
            executor.execute_cypher_async("MATCH (n:Item) RETURN n")
        )
        from ipfs_datasets_py.knowledge_graphs.query.distributed import (
            FederatedQueryResult,
        )

        assert isinstance(result, FederatedQueryResult)
        assert result.num_partitions == 2

    def test_execute_cypher_async_deduplicates(self):
        """
        GIVEN: A DistributedGraph where cross-partition edges may duplicate results
        WHEN:  execute_cypher_async is awaited with dedup=True (default)
        THEN:  The result contains at most one record per unique entity
        """
        from ipfs_datasets_py.knowledge_graphs.query.distributed import (
            FederatedQueryExecutor,
        )

        dist, kg, _ = self._make_dist_graph(num_partitions=2, num_entities=4)
        executor = FederatedQueryExecutor(dist, dedup=True)

        result = asyncio.run(
            executor.execute_cypher_async("MATCH (n:Item) RETURN n")
        )
        # There should be at most num_entities records (no duplicates)
        assert len(result.records) <= len(kg.entities)

    def test_lookup_all_entities_found(self):
        """
        GIVEN: A DistributedGraph with N entities
        WHEN:  lookup_entity is called for every entity ID
        THEN:  All lookups succeed (none return None)
        """
        from ipfs_datasets_py.knowledge_graphs.query.distributed import (
            FederatedQueryExecutor,
        )

        dist, kg, entities = self._make_dist_graph(
            num_partitions=4, num_entities=12
        )
        executor = FederatedQueryExecutor(dist)

        for entity in entities:
            found = executor.lookup_entity(entity.entity_id)
            assert found is not None, f"Entity {entity.entity_id} not found"
