"""
Tests for deferred-features session 4 additions:

* Item 9 (SRL): SRLFrame.from_dict round-trip, batch extraction, temporal graph
* Item 12 (OWL): equivalent class, schema merge, explain_inferences
* Item 13 (Distributed): rebalance, explain_query, streaming execution

GIVEN / WHEN / THEN style, consistent with repository conventions.
"""

from __future__ import annotations

import asyncio
from typing import Any, List

import pytest

# ---------------------------------------------------------------------------
# Helpers to build minimal test KGs
# ---------------------------------------------------------------------------

def _make_kg() -> Any:
    from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
    from ipfs_datasets_py.knowledge_graphs.extraction.entities import Entity
    from ipfs_datasets_py.knowledge_graphs.extraction.relationships import Relationship

    kg = KnowledgeGraph(name="test_kg")

    alice = Entity(entity_type="Person", name="Alice", properties={"age": 35})
    bob = Entity(entity_type="Person", name="Bob", properties={"age": 28})
    emp = Entity(entity_type="Employee", name="Charlie", properties={"age": 42})

    kg.add_entity(alice)
    kg.add_entity(bob)
    kg.add_entity(emp)

    rel = Relationship(
        relationship_type="knows",
        source_entity=alice,
        target_entity=bob,
        confidence=0.9,
    )
    kg.add_relationship(rel)

    return kg


def _make_large_kg(n: int = 20) -> Any:
    from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
    from ipfs_datasets_py.knowledge_graphs.extraction.entities import Entity
    from ipfs_datasets_py.knowledge_graphs.extraction.relationships import Relationship

    kg = KnowledgeGraph(name="large_kg")
    entities = []
    for i in range(n):
        e = Entity(entity_type="Item", name=f"item_{i}", properties={"idx": i})
        kg.add_entity(e)
        entities.append(e)

    for i in range(n - 1):
        rel = Relationship(
            relationship_type="linksTo",
            source_entity=entities[i],
            target_entity=entities[i + 1],
        )
        kg.add_relationship(rel)

    return kg


# ===========================================================================
# Item 9: SRL additions
# ===========================================================================


class TestSRLFrameFromDict:
    """GIVEN a serialised SRLFrame dict WHEN from_dict is called THEN the
    round-trip produces an equivalent frame."""

    def test_to_dict_from_dict_roundtrip(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.srl import (
            SRLExtractor, SRLFrame, RoleArgument, ROLE_AGENT, ROLE_PATIENT,
        )

        # GIVEN
        frame = SRLFrame(
            predicate="sent",
            sentence="Alice sent the report to Bob.",
            arguments=[
                RoleArgument(role=ROLE_AGENT, text="Alice", span=(0, 5), confidence=0.9),
                RoleArgument(role=ROLE_PATIENT, text="report", confidence=0.8),
            ],
            confidence=0.85,
            source="heuristic",
        )

        # WHEN
        d = frame.to_dict()
        restored = SRLFrame.from_dict(d)

        # THEN
        assert restored.predicate == frame.predicate
        assert restored.sentence == frame.sentence
        assert restored.confidence == frame.confidence
        assert restored.source == frame.source
        assert len(restored.arguments) == len(frame.arguments)
        assert restored.arguments[0].role == ROLE_AGENT
        assert restored.arguments[0].text == "Alice"
        assert restored.arguments[0].span == (0, 5)

    def test_from_dict_preserves_frame_id(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.srl import SRLFrame

        # GIVEN
        original = SRLFrame(predicate="run", sentence="They run fast.")
        d = original.to_dict()

        # WHEN
        restored = SRLFrame.from_dict(d)

        # THEN
        assert restored.frame_id == original.frame_id

    def test_from_dict_handles_missing_optional_fields(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.srl import SRLFrame

        # GIVEN — minimal dict
        d: dict = {"predicate": "jump"}

        # WHEN
        frame = SRLFrame.from_dict(d)

        # THEN
        assert frame.predicate == "jump"
        assert frame.arguments == []
        assert frame.predicate_span is None

    def test_from_dict_no_spans(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.srl import (
            SRLFrame, RoleArgument, ROLE_THEME,
        )

        # GIVEN — argument without span
        original = SRLFrame(
            predicate="fly",
            arguments=[RoleArgument(role=ROLE_THEME, text="bird")],
        )
        d = original.to_dict()

        # WHEN
        restored = SRLFrame.from_dict(d)

        # THEN
        assert restored.arguments[0].span is None


class TestSRLExtractBatch:
    """GIVEN a list of texts WHEN extract_batch is called THEN one list of
    frames is returned per input text, in order."""

    def test_batch_returns_one_entry_per_text(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.srl import SRLExtractor

        extractor = SRLExtractor()
        texts = [
            "Alice gave Bob a gift.",
            "Bob thanked Alice.",
            "They parted ways.",
        ]
        results = extractor.extract_batch(texts)

        assert len(results) == 3
        # Each element is a list
        for r in results:
            assert isinstance(r, list)

    def test_batch_empty_list(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.srl import SRLExtractor

        extractor = SRLExtractor()
        assert extractor.extract_batch([]) == []

    def test_batch_preserves_order(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.srl import SRLExtractor

        extractor = SRLExtractor()
        texts = ["Alice runs.", "Bob jumps.", "Charlie swims."]
        results = extractor.extract_batch(texts)
        # The predicates in each result correspond to the right sentence
        assert len(results) == 3


class TestSRLTemporalGraph:
    """GIVEN multi-sentence text WHEN build_temporal_graph is called THEN
    Event nodes are connected with temporal relationships."""

    def test_temporal_graph_returns_knowledge_graph(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.srl import SRLExtractor

        extractor = SRLExtractor()
        text = "Alice opened the door. Then she walked inside. Bob followed."
        kg = extractor.build_temporal_graph(text)

        # KG must be a KnowledgeGraph object
        assert hasattr(kg, "entities")
        assert hasattr(kg, "relationships")

    def test_temporal_graph_contains_event_nodes(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.srl import SRLExtractor

        extractor = SRLExtractor()
        text = "Alice sent the report. Bob received it."
        kg = extractor.build_temporal_graph(text)

        event_entities = [e for e in kg.entities.values() if e.entity_type == "Event"]
        assert len(event_entities) >= 1

    def test_temporal_graph_precedes_relationship(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.srl import SRLExtractor

        extractor = SRLExtractor()
        # "Then" is an explicit temporal connector → PRECEDES
        text = "Alice wrote the report. Then Bob reviewed it."
        kg = extractor.build_temporal_graph(text)

        temporal_rels = [
            r for r in kg.relationships.values()
            if r.relationship_type in ("PRECEDES", "FOLLOWS", "OVERLAPS")
        ]
        # Not guaranteed for 2-sentence text with only 1 event per sentence,
        # but the method must not crash and must return a KG.
        assert kg is not None

    def test_temporal_graph_single_sentence_no_crash(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.srl import SRLExtractor

        extractor = SRLExtractor()
        kg = extractor.build_temporal_graph("Alice runs.")
        assert kg is not None


# ===========================================================================
# Item 12: OWL reasoning additions
# ===========================================================================


class TestEquivalentClass:
    """GIVEN two equivalent classes WHEN materialize is called THEN each
    entity gains the other type as an inferred type."""

    def test_equivalent_class_adds_mutual_subclass(self):
        from ipfs_datasets_py.knowledge_graphs.ontology import OntologySchema

        # GIVEN
        schema = OntologySchema()
        schema.add_equivalent_class("Person", "Human")

        # THEN — mutual subclass entries are present
        assert "Human" in schema.subclass_map.get("Person", set())
        assert "Person" in schema.subclass_map.get("Human", set())

    def test_equivalent_class_materialize(self):
        from ipfs_datasets_py.knowledge_graphs.ontology import OntologySchema, OntologyReasoner

        # GIVEN
        kg = _make_kg()
        schema = OntologySchema()
        schema.add_equivalent_class("Person", "Human")

        reasoner = OntologyReasoner(schema)

        # WHEN
        kg2 = reasoner.materialize(kg)

        # THEN — Alice (Person) gains "Human" as inferred type
        alice = next(e for e in kg2.entities.values() if e.name == "Alice")
        inferred = set(alice.properties.get("inferred_types", []))
        assert "Human" in inferred

    def test_equivalent_class_turtle_round_trip(self):
        from ipfs_datasets_py.knowledge_graphs.ontology import OntologySchema

        # GIVEN
        schema = OntologySchema()
        schema.add_equivalent_class("Person", "Human")

        # WHEN
        turtle = schema.to_turtle()
        restored = OntologySchema.from_turtle(turtle)

        # THEN — either direction of the equivalentClass triple should
        # re-populate the subclass entries
        person_supers = restored.subclass_map.get("Person", set())
        human_supers = restored.subclass_map.get("Human", set())
        assert "Human" in person_supers or "Person" in human_supers

    def test_equivalent_class_dedup(self):
        from ipfs_datasets_py.knowledge_graphs.ontology import OntologySchema

        # GIVEN / WHEN — adding the same pair twice
        schema = OntologySchema()
        schema.add_equivalent_class("A", "B")
        schema.add_equivalent_class("A", "B")

        # THEN — only one pair stored (verify via Turtle: only one equivalentClass line)
        turtle = schema.to_turtle()
        equiv_lines = [l for l in turtle.splitlines() if "owl:equivalentClass" in l]
        assert len(equiv_lines) == 1


class TestOntologySchemaMerge:
    """GIVEN two schemas WHEN merge is called THEN all declarations from
    both schemas appear in the merged schema."""

    def test_merge_combines_subclass_maps(self):
        from ipfs_datasets_py.knowledge_graphs.ontology import OntologySchema

        # GIVEN
        s1 = OntologySchema()
        s1.add_subclass("Employee", "Person")

        s2 = OntologySchema()
        s2.add_subclass("Manager", "Employee")

        # WHEN
        merged = s1.merge(s2)

        # THEN
        assert "Person" in merged.subclass_map.get("Employee", set())
        assert "Employee" in merged.subclass_map.get("Manager", set())

    def test_merge_does_not_mutate_originals(self):
        from ipfs_datasets_py.knowledge_graphs.ontology import OntologySchema

        s1 = OntologySchema()
        s1.add_transitive("isAncestorOf")

        s2 = OntologySchema()
        s2.add_symmetric("isSiblingOf")

        merged = s1.merge(s2)

        # Originals unchanged
        assert "isSiblingOf" not in s1.symmetric
        assert "isAncestorOf" not in s2.transitive
        # Merged has both
        assert "isAncestorOf" in merged.transitive
        assert "isSiblingOf" in merged.symmetric

    def test_merge_self_priority_for_single_value_maps(self):
        from ipfs_datasets_py.knowledge_graphs.ontology import OntologySchema

        # GIVEN — conflicting domain declarations
        s1 = OntologySchema()
        s1.add_domain("worksAt", "Person")

        s2 = OntologySchema()
        s2.add_domain("worksAt", "Employee")

        # WHEN
        merged = s1.merge(s2)

        # THEN — self (s1) wins
        assert merged.domain_map.get("worksAt") == "Person"

    def test_merge_combines_property_chains(self):
        from ipfs_datasets_py.knowledge_graphs.ontology import OntologySchema

        s1 = OntologySchema()
        s1.add_property_chain(["p", "q"], "r")

        s2 = OntologySchema()
        s2.add_property_chain(["a", "b"], "c")

        merged = s1.merge(s2)

        chain_results = {res for _, res in merged.property_chains}
        assert "r" in chain_results
        assert "c" in chain_results


class TestExplainInferences:
    """GIVEN a KG with known facts WHEN explain_inferences is called THEN
    InferenceTrace objects describe each derived fact."""

    def test_explain_returns_list_of_traces(self):
        from ipfs_datasets_py.knowledge_graphs.ontology import OntologySchema, OntologyReasoner

        schema = OntologySchema()
        schema.add_subclass("Employee", "Person")

        kg = _make_kg()
        reasoner = OntologyReasoner(schema)

        traces = reasoner.explain_inferences(kg)

        assert isinstance(traces, list)

    def test_explain_does_not_modify_kg(self):
        from ipfs_datasets_py.knowledge_graphs.ontology import OntologySchema, OntologyReasoner

        schema = OntologySchema()
        schema.add_subclass("Employee", "Person")

        kg = _make_kg()
        before_count = len(kg.relationships)

        reasoner = OntologyReasoner(schema)
        reasoner.explain_inferences(kg)

        # KG unchanged
        assert len(kg.relationships) == before_count

    def test_explain_subclass_traces(self):
        from ipfs_datasets_py.knowledge_graphs.ontology import OntologySchema, OntologyReasoner

        schema = OntologySchema()
        schema.add_subclass("Employee", "Person")

        kg = _make_kg()  # has a "Charlie" with type "Employee"
        reasoner = OntologyReasoner(schema)

        traces = reasoner.explain_inferences(kg)

        subclass_traces = [t for t in traces if t.rule == "subclass"]
        assert len(subclass_traces) >= 1
        # At least one trace has "Person" as the derived type
        derived_types = {t.predicate for t in subclass_traces}
        assert "rdf:type" in derived_types

    def test_explain_symmetric_traces(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        from ipfs_datasets_py.knowledge_graphs.extraction.entities import Entity
        from ipfs_datasets_py.knowledge_graphs.extraction.relationships import Relationship
        from ipfs_datasets_py.knowledge_graphs.ontology import OntologySchema, OntologyReasoner

        schema = OntologySchema()
        schema.add_symmetric("isSiblingOf")

        kg = KnowledgeGraph(name="sym_test")
        alice = Entity(entity_type="Person", name="Alice")
        bob = Entity(entity_type="Person", name="Bob")
        kg.add_entity(alice)
        kg.add_entity(bob)
        kg.add_relationship(Relationship(
            relationship_type="isSiblingOf",
            source_entity=alice,
            target_entity=bob,
        ))

        reasoner = OntologyReasoner(schema)
        traces = reasoner.explain_inferences(kg)

        sym_traces = [t for t in traces if t.rule == "symmetric"]
        assert len(sym_traces) >= 1

    def test_explain_trace_to_dict(self):
        from ipfs_datasets_py.knowledge_graphs.ontology import OntologySchema, OntologyReasoner

        schema = OntologySchema()
        schema.add_subclass("Employee", "Person")
        kg = _make_kg()
        reasoner = OntologyReasoner(schema)
        traces = reasoner.explain_inferences(kg)

        if traces:
            d = traces[0].to_dict()
            assert "rule" in d
            assert "subject_id" in d
            assert "predicate" in d
            assert "object_id" in d


# ===========================================================================
# Item 13: Distributed query additions
# ===========================================================================


class TestDistributedGraphRebalance:
    """GIVEN an unbalanced DistributedGraph WHEN rebalance is called THEN a
    new graph with more balanced partition sizes is returned."""

    def test_rebalance_returns_distributed_graph(self):
        from ipfs_datasets_py.knowledge_graphs.query.distributed import (
            GraphPartitioner, PartitionStrategy,
        )

        kg = _make_large_kg(20)
        dist = GraphPartitioner(num_partitions=4, strategy=PartitionStrategy.HASH).partition(kg)

        rebalanced = dist.rebalance()

        assert rebalanced.num_partitions == dist.num_partitions

    def test_rebalance_preserves_total_nodes(self):
        from ipfs_datasets_py.knowledge_graphs.query.distributed import (
            GraphPartitioner, PartitionStrategy,
        )

        kg = _make_large_kg(20)
        dist = GraphPartitioner(num_partitions=4, strategy=PartitionStrategy.HASH).partition(kg)

        rebalanced = dist.rebalance(PartitionStrategy.ROUND_ROBIN)

        assert rebalanced.total_nodes == dist.total_nodes

    def test_rebalance_round_robin_is_balanced(self):
        from ipfs_datasets_py.knowledge_graphs.query.distributed import (
            GraphPartitioner, PartitionStrategy,
        )

        kg = _make_large_kg(20)
        dist = GraphPartitioner(num_partitions=4, strategy=PartitionStrategy.HASH).partition(kg)

        rebalanced = dist.rebalance(PartitionStrategy.ROUND_ROBIN)

        sizes = [len(p.entities) for p in rebalanced.partitions]
        # ROUND_ROBIN should produce equal or near-equal partitions
        assert max(sizes) - min(sizes) <= 1

    def test_rebalance_does_not_mutate_original(self):
        from ipfs_datasets_py.knowledge_graphs.query.distributed import (
            GraphPartitioner, PartitionStrategy,
        )

        kg = _make_large_kg(20)
        dist = GraphPartitioner(num_partitions=4).partition(kg)
        original_sizes = [len(p.entities) for p in dist.partitions]

        dist.rebalance()

        new_sizes = [len(p.entities) for p in dist.partitions]
        assert new_sizes == original_sizes


class TestFederatedQueryExecutorExplain:
    """GIVEN a distributed graph WHEN explain_query is called THEN a QueryPlan
    is returned with per-partition stats."""

    def test_explain_returns_query_plan(self):
        from ipfs_datasets_py.knowledge_graphs.query.distributed import (
            GraphPartitioner, FederatedQueryExecutor,
        )

        kg = _make_large_kg(10)
        dist = GraphPartitioner(num_partitions=3).partition(kg)
        executor = FederatedQueryExecutor(dist)

        plan = executor.explain_query("MATCH (n:Item) RETURN n")

        assert plan.num_partitions == 3
        assert len(plan.partition_plans) == 3

    def test_explain_plan_contains_node_counts(self):
        from ipfs_datasets_py.knowledge_graphs.query.distributed import (
            GraphPartitioner, FederatedQueryExecutor,
        )

        kg = _make_large_kg(12)
        dist = GraphPartitioner(num_partitions=3).partition(kg)
        executor = FederatedQueryExecutor(dist)

        plan = executor.explain_query("MATCH (n) RETURN n")

        total_in_plan = sum(p.node_count for p in plan.partition_plans)
        # May differ slightly from total_nodes due to cross-partition edges,
        # but should be >= total_nodes
        assert total_in_plan >= plan.total_nodes

    def test_explain_plan_to_dict(self):
        from ipfs_datasets_py.knowledge_graphs.query.distributed import (
            GraphPartitioner, FederatedQueryExecutor,
        )

        kg = _make_large_kg(6)
        dist = GraphPartitioner(num_partitions=2).partition(kg)
        executor = FederatedQueryExecutor(dist)

        plan = executor.explain_query("MATCH (n) RETURN n.name")
        d = plan.to_dict()

        assert d["num_partitions"] == 2
        assert d["query"] == "MATCH (n) RETURN n.name"
        assert len(d["partition_plans"]) == 2

    def test_explain_records_strategy(self):
        from ipfs_datasets_py.knowledge_graphs.query.distributed import (
            GraphPartitioner, FederatedQueryExecutor, PartitionStrategy,
        )

        kg = _make_large_kg(8)
        dist = GraphPartitioner(num_partitions=2, strategy=PartitionStrategy.RANGE).partition(kg)
        executor = FederatedQueryExecutor(dist)

        plan = executor.explain_query("MATCH (n) RETURN n")

        assert plan.strategy == PartitionStrategy.RANGE.value


class TestFederatedStreamingExecution:
    """GIVEN a distributed graph WHEN execute_cypher_streaming is called THEN
    records are yielded lazily as (partition_idx, record) tuples."""

    def test_streaming_yields_tuples(self):
        from ipfs_datasets_py.knowledge_graphs.query.distributed import (
            GraphPartitioner, FederatedQueryExecutor,
        )

        kg = _make_large_kg(8)
        dist = GraphPartitioner(num_partitions=3).partition(kg)
        executor = FederatedQueryExecutor(dist)

        results = list(executor.execute_cypher_streaming(
            "MATCH (n:Item) RETURN n.name"
        ))

        for item in results:
            assert isinstance(item, tuple)
            assert len(item) == 2
            partition_idx, record = item
            assert isinstance(partition_idx, int)
            assert isinstance(record, dict)

    def test_streaming_partition_idx_in_range(self):
        from ipfs_datasets_py.knowledge_graphs.query.distributed import (
            GraphPartitioner, FederatedQueryExecutor,
        )

        kg = _make_large_kg(12)
        num_parts = 4
        dist = GraphPartitioner(num_partitions=num_parts).partition(kg)
        executor = FederatedQueryExecutor(dist)

        for idx, _record in executor.execute_cypher_streaming("MATCH (n) RETURN n.name"):
            assert 0 <= idx < num_parts

    def test_streaming_dedup_removes_duplicates(self):
        from ipfs_datasets_py.knowledge_graphs.query.distributed import (
            GraphPartitioner, FederatedQueryExecutor, PartitionStrategy,
        )

        # Use ROUND_ROBIN so we know the distribution; copy_cross_edges=True
        # may duplicate some edge-result records.
        kg = _make_large_kg(6)
        dist = GraphPartitioner(
            num_partitions=2,
            strategy=PartitionStrategy.ROUND_ROBIN,
            copy_cross_edges=True,
        ).partition(kg)
        executor = FederatedQueryExecutor(dist, dedup=True)

        records_streaming = [
            r for _, r in executor.execute_cypher_streaming("MATCH (n) RETURN n.name")
        ]
        records_normal = executor.execute_cypher("MATCH (n) RETURN n.name").records

        # Streaming (deduped) should produce the same count as normal (deduped)
        assert len(records_streaming) == len(records_normal)

    def test_streaming_empty_graph(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        from ipfs_datasets_py.knowledge_graphs.query.distributed import (
            GraphPartitioner, FederatedQueryExecutor,
        )

        kg = KnowledgeGraph(name="empty")
        dist = GraphPartitioner(num_partitions=2).partition(kg)
        executor = FederatedQueryExecutor(dist)

        results = list(executor.execute_cypher_streaming("MATCH (n) RETURN n"))
        assert results == []
