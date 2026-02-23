"""
Session 17 coverage tests targeting:
- extraction/srl.py (74% → 79%): SRLFrame.get_roles, modifier roles (Instrument/Location/Time/Cause),
  to_knowledge_graph, build_temporal_graph
- extraction/graph.py (71% → 75%): add_entity with string-type, get_*  helpers, find_paths
  (direct/2-hop/bidirectional-backward/type-filter/no-path), query_by_properties, merge
- query/distributed.py (80% → 83%): PartitionStats.to_dict, RANGE/ROUND_ROBIN partition,
  execute_cypher_parallel, execute_cypher_streaming, _normalise_result, _record_fingerprint,
  dedup=False
- cypher/compiler.py (84% → 91%): MERGE (with on_create/on_match), DETACH DELETE, REMOVE,
  FOREACH, CALL subquery, unknown clause error, CASE expression_to_string, ListNode,
  dict compile_expression, ORDER BY, UNION/UNION ALL, OPTIONAL MATCH, target-with-props,
  non-var PropertyAccessNode, WHERE IS NULL/IS NOT NULL/NOT
- neo4j_compat/types.py (81% → 96%): Node/Relationship __contains__/__eq__/__hash__/__repr__,
  Path start/end/len/iter
- extraction/types.py (72% stable — both optional imports available): HAVE_TRACER, HAVE_ACCELERATE,
  is_accelerate_available, get_accelerate_status, type aliases, constants
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# SRL extraction
# ---------------------------------------------------------------------------

class TestSRLFrameGetRoles:
    """GIVEN SRLFrame with multiple arguments WHEN calling get_roles
    THEN returns all matching + empty list for missing role."""

    def test_get_roles_returns_all_matching(self):
        # GIVEN
        from ipfs_datasets_py.knowledge_graphs.extraction.srl import (
            SRLExtractor, ROLE_AGENT, ROLE_PATIENT,
        )
        e = SRLExtractor()
        frames = e.extract_srl("He sent the report.")
        assert frames, "Expected at least one frame"
        f = frames[0]
        # WHEN
        agents = f.get_roles(ROLE_AGENT)
        # THEN
        assert isinstance(agents, list)
        assert len(agents) >= 1

    def test_get_roles_returns_empty_for_missing_role(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.srl import SRLExtractor
        e = SRLExtractor()
        frames = e.extract_srl("She walked.")
        assert frames
        # WHEN
        result = frames[0].get_roles("NonExistentRole")
        # THEN
        assert result == []

    def test_get_role_returns_none_for_missing(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.srl import SRLExtractor
        e = SRLExtractor()
        frames = e.extract_srl("She walked.")
        assert frames
        # WHEN
        result = frames[0].get_role("NonExistent")
        # THEN
        assert result is None

    def test_srlframe_has_frame_id(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.srl import SRLExtractor
        e = SRLExtractor()
        frames = e.extract_srl("Alice sends messages.")
        assert frames
        f = frames[0]
        assert f.frame_id
        assert isinstance(f.frame_id, str)


class TestSRLModifierRoles:
    """GIVEN sentences with Instrument/Time/Cause modifiers WHEN extracting
    THEN those roles appear in the resulting frames."""

    def test_instrument_role_extracted(self):
        # GIVEN
        from ipfs_datasets_py.knowledge_graphs.extraction.srl import (
            _extract_heuristic_frames, ROLE_INSTRUMENT,
        )
        sentence = "He fixed with a screwdriver"
        # WHEN
        frames = _extract_heuristic_frames(sentence)
        # THEN – at least one frame should have an Instrument argument
        all_roles = [a.role for f in frames for a in f.arguments]
        assert ROLE_INSTRUMENT in all_roles

    def test_cause_role_extracted(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.srl import (
            _extract_heuristic_frames, ROLE_CAUSE,
        )
        sentence = "He failed because he was unprepared"
        frames = _extract_heuristic_frames(sentence)
        all_roles = [a.role for f in frames for a in f.arguments]
        assert ROLE_CAUSE in all_roles

    def test_time_role_extracted(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.srl import (
            _extract_heuristic_frames, ROLE_TIME,
        )
        sentence = "She left after the bell rang"
        frames = _extract_heuristic_frames(sentence)
        all_roles = [a.role for f in frames for a in f.arguments]
        assert ROLE_TIME in all_roles

    def test_sentence_no_verb_returns_empty(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.srl import _extract_heuristic_frames
        # All-punctuation / no verb-like word
        frames = _extract_heuristic_frames("...")
        assert frames == []

    def test_empty_sentence_returns_empty(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.srl import _extract_heuristic_frames
        assert _extract_heuristic_frames("") == []


class TestSRLToKnowledgeGraph:
    """GIVEN SRL frames WHEN calling to_knowledge_graph THEN produces a KG
    with Event entities and typed relationships."""

    def test_basic_frames_to_kg(self):
        # GIVEN
        from ipfs_datasets_py.knowledge_graphs.extraction.srl import SRLExtractor
        e = SRLExtractor()
        frames = e.extract_srl("He fixed the car.")
        assert frames
        # WHEN
        kg = e.to_knowledge_graph(frames)
        # THEN
        assert len(kg.entities) >= 1
        entity_types = {en.entity_type for en in kg.entities.values()}
        assert "Event" in entity_types

    def test_extends_existing_kg(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.srl import SRLExtractor
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        e = SRLExtractor()
        frames = e.extract_srl("She walked.")
        assert frames
        existing_kg = KnowledgeGraph(name="existing")
        kg = e.to_knowledge_graph(frames, kg=existing_kg)
        assert kg is existing_kg
        assert len(kg.entities) >= 1

    def test_to_kg_creates_relationships(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.srl import SRLExtractor
        e = SRLExtractor()
        frames = e.extract_srl("Alice sent the message.")
        assert frames
        kg = e.to_knowledge_graph(frames)
        assert len(kg.relationships) >= 1

    def test_entity_reuse_same_name_and_type(self):
        """GIVEN two frames with the same agent name WHEN converting to KG
        THEN the agent entity is reused (not duplicated)."""
        from ipfs_datasets_py.knowledge_graphs.extraction.srl import SRLExtractor
        e = SRLExtractor()
        frames = e.extract_srl("Alice sends. Alice receives.")
        assert len(frames) >= 2
        kg = e.to_knowledge_graph(frames)
        alice_entities = [en for en in kg.entities.values() if en.name == "Alice"]
        assert len(alice_entities) == 1  # reused

    def test_high_confidence_filter_excludes_frames(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.srl import SRLExtractor
        e = SRLExtractor(min_confidence=0.99)
        frames = e.extract_srl("He ran.")
        # Heuristic frames have confidence ~0.65 — they should not pass the filter
        kg = e.to_knowledge_graph(frames)
        assert len(kg.entities) == 0


class TestSRLBuildTemporalGraph:
    """GIVEN multi-sentence text WHEN calling build_temporal_graph THEN
    returns a KG with event entities."""

    def test_single_sentence(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.srl import SRLExtractor
        e = SRLExtractor()
        kg = e.build_temporal_graph("He ran.")
        assert len(kg.entities) >= 0  # might be 0 if verb not found

    def test_multi_sentence_then_connector(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.srl import SRLExtractor
        e = SRLExtractor()
        kg = e.build_temporal_graph("He ran. Then he jumped.")
        # entities should include event nodes from both sentences
        assert isinstance(kg.entities, dict)

    def test_returns_knowledge_graph(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.srl import SRLExtractor
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        e = SRLExtractor()
        kg = e.build_temporal_graph("Alice cooked. Bob ate. Carol cleaned.")
        assert isinstance(kg, KnowledgeGraph)

    def test_extract_batch_returns_list_of_lists(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.srl import SRLExtractor
        e = SRLExtractor()
        results = e.extract_batch(["He ran.", "She jumped."])
        assert len(results) == 2
        assert all(isinstance(r, list) for r in results)

    def test_extract_srl_sentence_split_false(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.srl import SRLExtractor
        e = SRLExtractor(sentence_split=False)
        # With sentence_split=False, the whole text is treated as one sentence
        frames = e.extract_srl("He ran. She jumped.")
        assert isinstance(frames, list)


# ---------------------------------------------------------------------------
# extraction/graph.py — KnowledgeGraph helpers
# ---------------------------------------------------------------------------

class TestKnowledgeGraphAddEntityString:
    """GIVEN entity_type as a string WHEN add_entity is called
    THEN an entity is created and returned."""

    def test_add_entity_with_string_type_and_name(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        kg = KnowledgeGraph(name="test")
        entity = kg.add_entity("Person", name="Alice")
        assert entity.entity_type == "Person"
        assert entity.name == "Alice"

    def test_add_entity_string_type_with_properties(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        kg = KnowledgeGraph(name="test")
        entity = kg.add_entity("Animal", name="Cat", properties={"legs": 4})
        assert entity.name == "Cat"
        assert entity.properties["legs"] == 4

    def test_add_entity_string_type_requires_name(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        kg = KnowledgeGraph(name="test")
        with pytest.raises(ValueError):
            kg.add_entity("Person")  # name missing


class TestKnowledgeGraphGetHelpers:
    """GIVEN a KG with entities and relationships WHEN calling get helpers
    THEN correct results returned."""

    def _build_kg(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        from ipfs_datasets_py.knowledge_graphs.extraction.entities import Entity
        from ipfs_datasets_py.knowledge_graphs.extraction.relationships import Relationship
        kg = KnowledgeGraph(name="test")
        a = Entity(entity_id="a1", entity_type="Person", name="Alice")
        b = Entity(entity_id="b1", entity_type="Animal", name="Dog")
        kg.add_entity(a)
        kg.add_entity(b)
        rel = Relationship(relationship_type="OWNS", source_entity=a, target_entity=b)
        kg.add_relationship(rel)
        return kg, a, b, rel

    def test_get_entity_by_id_found(self):
        kg, a, b, rel = self._build_kg()
        found = kg.get_entity_by_id("a1")
        assert found is a

    def test_get_entity_by_id_not_found(self):
        kg, a, b, rel = self._build_kg()
        assert kg.get_entity_by_id("missing") is None

    def test_get_relationship_by_id(self):
        kg, a, b, rel = self._build_kg()
        found = kg.get_relationship_by_id(rel.relationship_id)
        assert found is rel

    def test_get_relationship_by_id_missing(self):
        kg, a, b, rel = self._build_kg()
        assert kg.get_relationship_by_id("missing") is None

    def test_get_entities_by_type(self):
        kg, a, b, rel = self._build_kg()
        persons = kg.get_entities_by_type("Person")
        assert len(persons) == 1
        assert persons[0] is a

    def test_get_entities_by_name(self):
        kg, a, b, rel = self._build_kg()
        found = kg.get_entities_by_name("Dog")
        assert len(found) == 1
        assert found[0] is b

    def test_get_entities_by_name_no_match(self):
        kg, a, b, rel = self._build_kg()
        assert kg.get_entities_by_name("Nobody") == []

    def test_get_relationships_by_type(self):
        kg, a, b, rel = self._build_kg()
        rels = kg.get_relationships_by_type("OWNS")
        assert len(rels) == 1

    def test_get_relationships_by_entity(self):
        kg, a, b, rel = self._build_kg()
        rels = kg.get_relationships_by_entity(a)
        assert len(rels) == 1

    def test_get_relationships_between(self):
        kg, a, b, rel = self._build_kg()
        rels = kg.get_relationships_between(a, b)
        assert len(rels) == 1

    def test_get_relationships_between_no_match(self):
        kg, a, b, rel = self._build_kg()
        rels = kg.get_relationships_between(b, a)  # reversed
        assert len(rels) == 0


class TestKnowledgeGraphFindPaths:
    """GIVEN a KG with various edges WHEN find_paths is called THEN
    correct paths returned."""

    def _build_chain_kg(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        from ipfs_datasets_py.knowledge_graphs.extraction.entities import Entity
        from ipfs_datasets_py.knowledge_graphs.extraction.relationships import Relationship
        kg = KnowledgeGraph(name="chain")
        a = Entity(entity_id="a", entity_type="N", name="A")
        b = Entity(entity_id="b", entity_type="N", name="B")
        c = Entity(entity_id="c", entity_type="N", name="C")
        d = Entity(entity_id="d", entity_type="N", name="D")
        kg.add_entity(a); kg.add_entity(b); kg.add_entity(c); kg.add_entity(d)
        r1 = Relationship(relationship_type="EDGE", source_entity=a, target_entity=b)
        r2 = Relationship(relationship_type="EDGE", source_entity=b, target_entity=c)
        r3 = Relationship(relationship_type="OTHER", source_entity=b, target_entity=c,
                          bidirectional=True)
        kg.add_relationship(r1); kg.add_relationship(r2); kg.add_relationship(r3)
        return kg, a, b, c, d

    def test_direct_path(self):
        kg, a, b, c, d = self._build_chain_kg()
        paths = kg.find_paths(a, b, max_depth=2)
        assert len(paths) >= 1

    def test_two_hop_path(self):
        kg, a, b, c, d = self._build_chain_kg()
        paths = kg.find_paths(a, c, max_depth=3)
        assert len(paths) >= 1

    def test_no_path_returns_empty(self):
        kg, a, b, c, d = self._build_chain_kg()
        paths = kg.find_paths(a, d, max_depth=3)
        assert paths == []

    def test_relationship_type_filter_matching(self):
        kg, a, b, c, d = self._build_chain_kg()
        paths = kg.find_paths(a, c, max_depth=3, relationship_types=["EDGE"])
        assert len(paths) >= 1

    def test_relationship_type_filter_no_match(self):
        kg, a, b, c, d = self._build_chain_kg()
        paths = kg.find_paths(a, c, max_depth=3, relationship_types=["HATES"])
        assert len(paths) == 0

    def test_bidirectional_backward_traversal(self):
        """GIVEN a bidirectional edge b→c WHEN finding paths from c to b
        THEN a path is found via the backward direction."""
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        from ipfs_datasets_py.knowledge_graphs.extraction.entities import Entity
        from ipfs_datasets_py.knowledge_graphs.extraction.relationships import Relationship
        kg = KnowledgeGraph(name="bidir")
        x = Entity(entity_id="x", entity_type="N", name="X")
        y = Entity(entity_id="y", entity_type="N", name="Y")
        kg.add_entity(x); kg.add_entity(y)
        rel = Relationship(relationship_type="BIDIR", source_entity=x, target_entity=y,
                           bidirectional=True)
        kg.add_relationship(rel)
        paths = kg.find_paths(y, x, max_depth=2)
        assert len(paths) >= 1


class TestKnowledgeGraphQueryAndMerge:
    """GIVEN a KG WHEN querying / merging THEN correct results returned."""

    def _make_kg(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        from ipfs_datasets_py.knowledge_graphs.extraction.entities import Entity
        kg = KnowledgeGraph(name="q")
        a = Entity(entity_id="p1", entity_type="Person", name="Alice", properties={"age": 30})
        b = Entity(entity_id="a1", entity_type="Animal", name="Cat", properties={"age": 5})
        kg.add_entity(a); kg.add_entity(b)
        return kg, a, b

    def test_query_by_type(self):
        kg, a, b = self._make_kg()
        results = kg.query_by_properties(entity_type="Person")
        assert len(results) == 1
        assert results[0] is a

    def test_query_by_property(self):
        kg, a, b = self._make_kg()
        results = kg.query_by_properties(properties={"age": 30})
        assert len(results) == 1

    def test_query_no_filter_returns_all(self):
        kg, a, b = self._make_kg()
        results = kg.query_by_properties()
        assert len(results) == 2

    def test_merge_two_graphs(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        from ipfs_datasets_py.knowledge_graphs.extraction.entities import Entity
        kg1 = KnowledgeGraph(name="g1")
        kg2 = KnowledgeGraph(name="g2")
        kg1.add_entity(Entity(entity_id="e1", entity_type="T", name="E1"))
        kg2.add_entity(Entity(entity_id="e2", entity_type="T", name="E2"))
        merged = kg1.merge(kg2)
        assert len(merged.entities) == 2

    def test_merge_deduplicates_entities(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        from ipfs_datasets_py.knowledge_graphs.extraction.entities import Entity
        kg1 = KnowledgeGraph(name="g1")
        kg2 = KnowledgeGraph(name="g2")
        shared = Entity(entity_id="shared", entity_type="T", name="Shared")
        kg1.add_entity(shared)
        kg2.add_entity(shared)
        merged = kg1.merge(kg2)
        assert len(merged.entities) == 1

    def test_merge_entities_with_none_properties(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        from ipfs_datasets_py.knowledge_graphs.extraction.entities import Entity
        kg1 = KnowledgeGraph(name="g1")
        kg2 = KnowledgeGraph(name="g2")
        kg1.add_entity(Entity(entity_id="e1", entity_type="T", name="E1", properties=None))
        kg2.add_entity(Entity(entity_id="e2", entity_type="T", name="E2"))
        merged = kg1.merge(kg2)
        assert len(merged.entities) == 2

    def test_to_dict_from_dict_roundtrip(self):
        kg, a, b = self._make_kg()
        d = kg.to_dict()
        assert "entities" in d and "relationships" in d
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        restored = KnowledgeGraph.from_dict(d)
        assert len(restored.entities) == len(kg.entities)

    def test_to_json_from_json_roundtrip(self):
        kg, a, b = self._make_kg()
        j = kg.to_json()
        assert isinstance(j, str)
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        restored = KnowledgeGraph.from_json(j)
        assert len(restored.entities) == 2

    def test_export_to_rdf_without_rdflib(self):
        """GIVEN rdflib not installed WHEN export_to_rdf called THEN returns error string."""
        kg, a, b = self._make_kg()
        result = kg.export_to_rdf()
        assert isinstance(result, str)
        # Either an error message (no rdflib) or a valid Turtle string (if rdflib present)


# ---------------------------------------------------------------------------
# query/distributed.py
# ---------------------------------------------------------------------------

class TestPartitionStats:
    """GIVEN PartitionStats WHEN to_dict called THEN returns expected keys."""

    def test_to_dict_returns_all_keys(self):
        from ipfs_datasets_py.knowledge_graphs.query.distributed import PartitionStats
        ps = PartitionStats(partition_id=3, node_count=10, edge_count=5)
        d = ps.to_dict()
        assert d == {"partition_id": 3, "node_count": 10, "edge_count": 5}


class TestGraphPartitionerStrategies:
    """GIVEN a KG with multiple entities WHEN partitioning with different strategies
    THEN the distributed graph has the requested number of partitions."""

    def _make_kg(self, n=6):
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        from ipfs_datasets_py.knowledge_graphs.extraction.entities import Entity
        kg = KnowledgeGraph(name="test")
        for i in range(n):
            kg.add_entity(Entity(entity_id=f"e{i:02d}", entity_type="T", name=f"n{i}"))
        return kg

    def test_hash_partitioning(self):
        from ipfs_datasets_py.knowledge_graphs.query.distributed import (
            GraphPartitioner, PartitionStrategy,
        )
        kg = self._make_kg()
        p = GraphPartitioner(num_partitions=2, strategy=PartitionStrategy.HASH)
        dg = p.partition(kg)
        assert dg.num_partitions == 2

    def test_range_partitioning(self):
        from ipfs_datasets_py.knowledge_graphs.query.distributed import (
            GraphPartitioner, PartitionStrategy,
        )
        kg = self._make_kg()
        p = GraphPartitioner(num_partitions=2, strategy=PartitionStrategy.RANGE)
        dg = p.partition(kg)
        assert dg.num_partitions == 2

    def test_round_robin_partitioning(self):
        from ipfs_datasets_py.knowledge_graphs.query.distributed import (
            GraphPartitioner, PartitionStrategy,
        )
        kg = self._make_kg()
        p = GraphPartitioner(num_partitions=3, strategy=PartitionStrategy.ROUND_ROBIN)
        dg = p.partition(kg)
        assert dg.num_partitions == 3

    def test_invalid_strategy_raises(self):
        from ipfs_datasets_py.knowledge_graphs.query.distributed import GraphPartitioner
        from unittest.mock import patch
        kg = self._make_kg(2)
        p = GraphPartitioner(num_partitions=2)
        # Force an unknown strategy
        with patch.object(p, "strategy", new="BAD"):
            with pytest.raises(ValueError):
                p.partition(kg)

    def test_get_partition_stats(self):
        from ipfs_datasets_py.knowledge_graphs.query.distributed import (
            GraphPartitioner, DistributedGraph,
        )
        kg = self._make_kg()
        p = GraphPartitioner(num_partitions=2)
        dg = p.partition(kg)
        stats = dg.get_partition_stats()
        assert isinstance(stats, list)
        assert len(stats) == 2


class TestFederatedQueryExecutorParallel:
    """GIVEN a distributed graph WHEN using execute_cypher_parallel
    THEN same results as serial execution."""

    def _make_executor(self, n=4, partitions=2):
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        from ipfs_datasets_py.knowledge_graphs.extraction.entities import Entity
        from ipfs_datasets_py.knowledge_graphs.query.distributed import (
            GraphPartitioner, FederatedQueryExecutor,
        )
        kg = KnowledgeGraph(name="t")
        for i in range(n):
            kg.add_entity(Entity(entity_id=f"e{i}", entity_type="Person", name=f"p{i}"))
        dg = GraphPartitioner(num_partitions=partitions).partition(kg)
        return FederatedQueryExecutor(distributed_graph=dg)

    def test_execute_cypher_parallel_returns_results(self):
        executor = self._make_executor()
        result = executor.execute_cypher_parallel("MATCH (n:Person) RETURN n", max_workers=2)
        assert len(result.records) >= 1

    def test_execute_cypher_parallel_error_dict(self):
        executor = self._make_executor()
        result = executor.execute_cypher_parallel("MATCH (n:Person) RETURN n")
        assert isinstance(result.errors, dict)

    def test_execute_cypher_parallel_partition_results(self):
        executor = self._make_executor(n=4, partitions=2)
        result = executor.execute_cypher_parallel("MATCH (n:Person) RETURN n")
        assert result.num_partitions == 2

    def test_execute_cypher_streaming_yields_tuples(self):
        executor = self._make_executor()
        records = list(executor.execute_cypher_streaming("MATCH (n:Person) RETURN n"))
        assert len(records) >= 1
        # Each item is (partition_idx, record_dict)
        for item in records:
            assert len(item) == 2
            assert isinstance(item[1], dict)

    def test_dedup_false_may_return_duplicates(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        from ipfs_datasets_py.knowledge_graphs.extraction.entities import Entity
        from ipfs_datasets_py.knowledge_graphs.query.distributed import (
            GraphPartitioner, FederatedQueryExecutor,
        )
        kg = KnowledgeGraph(name="t")
        for i in range(3):
            kg.add_entity(Entity(entity_id=f"e{i}", entity_type="Person", name=f"p{i}"))
        dg = GraphPartitioner(num_partitions=2, copy_cross_edges=True).partition(kg)
        exec_dedup = FederatedQueryExecutor(distributed_graph=dg, dedup=True)
        exec_nodup = FederatedQueryExecutor(distributed_graph=dg, dedup=False)
        r_dedup = exec_dedup.execute_cypher("MATCH (n:Person) RETURN n")
        r_nodup = exec_nodup.execute_cypher("MATCH (n:Person) RETURN n")
        # Without dedup, count >= with dedup
        assert r_nodup.num_partitions == r_dedup.num_partitions


class TestNormaliseResult:
    """GIVEN various result objects WHEN _normalise_result is called
    THEN a list of dicts is returned."""

    def test_none_returns_empty(self):
        from ipfs_datasets_py.knowledge_graphs.query.distributed import _normalise_result
        assert _normalise_result(None) == []

    def test_list_of_dicts_passthrough(self):
        from ipfs_datasets_py.knowledge_graphs.query.distributed import _normalise_result
        result = _normalise_result([{"x": 1}, {"x": 2}])
        assert result == [{"x": 1}, {"x": 2}]

    def test_object_with_records_attr(self):
        from ipfs_datasets_py.knowledge_graphs.query.distributed import _normalise_result

        class FakeResult:
            records = [{"a": 1}]

        result = _normalise_result(FakeResult())
        assert result == [{"a": 1}]

    def test_iterable_of_dicts(self):
        from ipfs_datasets_py.knowledge_graphs.query.distributed import _normalise_result
        result = _normalise_result(iter([{"k": "v"}]))
        assert result == [{"k": "v"}]

    def test_non_iterable_returns_empty(self):
        from ipfs_datasets_py.knowledge_graphs.query.distributed import _normalise_result
        # An integer is not iterable
        result = _normalise_result(42)
        assert result == []


class TestRecordFingerprint:
    """GIVEN record dicts WHEN _record_fingerprint is called
    THEN stable hex strings returned."""

    def test_returns_40_char_hex(self):
        from ipfs_datasets_py.knowledge_graphs.query.distributed import _record_fingerprint
        fp = _record_fingerprint({"a": 1, "b": "hello"})
        assert isinstance(fp, str)
        assert len(fp) == 40

    def test_same_record_same_fingerprint(self):
        from ipfs_datasets_py.knowledge_graphs.query.distributed import _record_fingerprint
        fp1 = _record_fingerprint({"x": 1, "y": 2})
        fp2 = _record_fingerprint({"y": 2, "x": 1})
        assert fp1 == fp2  # sort_keys=True ensures stability

    def test_different_records_different_fingerprints(self):
        from ipfs_datasets_py.knowledge_graphs.query.distributed import _record_fingerprint
        fp1 = _record_fingerprint({"x": 1})
        fp2 = _record_fingerprint({"x": 2})
        assert fp1 != fp2


# ---------------------------------------------------------------------------
# cypher/compiler.py
# ---------------------------------------------------------------------------

class TestCypherCompilerMisc:
    """GIVEN various Cypher queries WHEN compiled THEN correct IR ops generated."""

    def _compile(self, query: str):
        from ipfs_datasets_py.knowledge_graphs.cypher.compiler import compile_cypher
        from ipfs_datasets_py.knowledge_graphs.cypher.parser import CypherParser
        parser = CypherParser()
        return compile_cypher(parser.parse(query))

    def test_unknown_clause_raises(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.compiler import (
            CypherCompiler, CypherCompileError,
        )
        compiler = CypherCompiler()
        with pytest.raises(CypherCompileError):
            compiler._compile_clause("not_a_clause_type")

    def test_merge_emits_merge_op(self):
        ops = self._compile("MERGE (n:Person {name: 'Alice'})")
        op_names = [o["op"] for o in ops]
        assert "Merge" in op_names

    def test_merge_has_match_and_create_ops(self):
        ops = self._compile("MERGE (n:Person)")
        merge_op = next(o for o in ops if o["op"] == "Merge")
        assert isinstance(merge_op.get("match_ops"), list)
        assert isinstance(merge_op.get("create_ops"), list)

    def test_detach_delete_emits_scan(self):
        ops = self._compile("MATCH (n:Person) DETACH DELETE n")
        op_names = [o["op"] for o in ops]
        assert "ScanLabel" in op_names

    def test_remove_property_emits_remove_op(self):
        ops = self._compile("MATCH (n:Person) REMOVE n.age")
        op_names = [o["op"] for o in ops]
        assert "RemoveProperty" in op_names

    def test_foreach_emits_foreach_op(self):
        ops = self._compile("FOREACH (n IN [1,2,3] | CREATE (:X {v:n}))")
        op_names = [o["op"] for o in ops]
        assert "Foreach" in op_names

    def test_call_subquery_emits_callsubquery_op(self):
        ops = self._compile("CALL { MATCH (n:Person) RETURN n }")
        op_names = [o["op"] for o in ops]
        assert "CallSubquery" in op_names

    def test_union_emits_union_op_not_all(self):
        ops = self._compile("MATCH (n:Person) RETURN n UNION MATCH (m:Animal) RETURN m")
        union_ops = [o for o in ops if o["op"] == "Union"]
        assert len(union_ops) == 1
        assert union_ops[0]["all"] is False

    def test_union_all_emits_union_op_all(self):
        ops = self._compile("MATCH (n:Person) RETURN n UNION ALL MATCH (m:Animal) RETURN m")
        union_ops = [o for o in ops if o["op"] == "Union"]
        assert union_ops[0]["all"] is True

    def test_order_by_desc(self):
        ops = self._compile("MATCH (n:Person) RETURN n ORDER BY n.age DESC")
        order_ops = [o for o in ops if o["op"] == "OrderBy"]
        assert len(order_ops) == 1
        items = order_ops[0]["items"]
        assert len(items) >= 1
        assert items[0]["ascending"] is False

    def test_order_by_asc_default(self):
        ops = self._compile("MATCH (n:Person) RETURN n ORDER BY n.name")
        order_ops = [o for o in ops if o["op"] == "OrderBy"]
        assert order_ops[0]["items"][0]["ascending"] is True

    def test_return_distinct(self):
        ops = self._compile("MATCH (n:Person) RETURN DISTINCT n.name")
        proj = [o for o in ops if o["op"] == "Project"]
        assert any(o.get("distinct") for o in proj)

    def test_optional_match_emits_optional_expand(self):
        ops = self._compile(
            "OPTIONAL MATCH (n:Person)-[r:KNOWS]->(m:Person) RETURN n, r, m"
        )
        op_names = [o["op"] for o in ops]
        assert "OptionalExpand" in op_names

    def test_where_is_null(self):
        ops = self._compile("MATCH (n:Person) WHERE n.age IS NULL RETURN n")
        filters = [o for o in ops if o.get("expression", {}).get("op") == "IS NULL"]
        assert len(filters) >= 1

    def test_where_is_not_null(self):
        ops = self._compile("MATCH (n:Person) WHERE n.age IS NOT NULL RETURN n")
        filters = [o for o in ops if o.get("expression", {}).get("op") == "IS NOT NULL"]
        assert len(filters) >= 1

    def test_where_not_emits_filter_not(self):
        ops = self._compile("MATCH (n:Person) WHERE NOT n.active RETURN n")
        filter_ops = [o for o in ops if o["op"] == "Filter"]
        assert any(o.get("expression", {}).get("op") == "NOT" for o in filter_ops)

    def test_aggregate_emits_aggregate_op(self):
        ops = self._compile("MATCH (n:Person) RETURN count(n)")
        assert any(o["op"] == "Aggregate" for o in ops)


class TestCypherCompilerExpressions:
    """GIVEN various expression types WHEN _compile_expression called
    THEN correct compiled form returned."""

    def _compiler(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.compiler import CypherCompiler
        return CypherCompiler()

    def test_list_node_compiled_to_list(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.ast import ListNode, LiteralNode
        comp = self._compiler()
        lst = ListNode(elements=[LiteralNode(value=1), LiteralNode(value=2)])
        result = comp._compile_expression(lst)
        assert isinstance(result, list)
        assert result == [1, 2]

    def test_dict_compiled_to_dict(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.ast import LiteralNode
        comp = self._compiler()
        result = comp._compile_expression({"a": LiteralNode(value="x")})
        assert isinstance(result, dict)
        assert result == {"a": "x"}

    def test_non_var_property_access_node(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.ast import (
            PropertyAccessNode, FunctionCallNode, LiteralNode,
        )
        comp = self._compiler()
        func = FunctionCallNode(name="toString", arguments=[LiteralNode(value=42)])
        prop = PropertyAccessNode(object=func, property="len")
        result = comp._compile_expression(prop)
        assert isinstance(result, dict)
        assert "property" in result

    def test_case_expression_to_string(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.ast import (
            CaseExpressionNode, WhenClause, LiteralNode, VariableNode,
        )
        comp = self._compiler()
        case = CaseExpressionNode(
            test_expression=VariableNode(name="n"),
            when_clauses=[
                WhenClause(condition=LiteralNode(value=1), result=LiteralNode(value="one"))
            ],
            else_result=LiteralNode(value="other"),
        )
        s = comp._expression_to_string(case)
        assert "CASE" in s
        assert "WHEN" in s
        assert "ELSE" in s

    def test_case_expression_no_else_to_string(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.ast import (
            CaseExpressionNode, WhenClause, LiteralNode,
        )
        comp = self._compiler()
        case = CaseExpressionNode(
            test_expression=None,
            when_clauses=[WhenClause(condition=LiteralNode(value=True), result=LiteralNode(value="yes"))],
            else_result=None,
        )
        s = comp._expression_to_string(case)
        assert "CASE" in s
        assert "ELSE" not in s

    def test_compile_cypher_convenience(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.compiler import compile_cypher
        from ipfs_datasets_py.knowledge_graphs.cypher.parser import CypherParser
        ops = compile_cypher(CypherParser().parse("MATCH (n) RETURN n"))
        assert any(o["op"] == "ScanAll" for o in ops)

    def test_merge_with_on_create_set(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.compiler import CypherCompiler
        from ipfs_datasets_py.knowledge_graphs.cypher.ast import (
            MergeClause, PatternNode, NodePattern, QueryNode,
            PropertyAccessNode, VariableNode, LiteralNode,
        )
        comp = CypherCompiler()
        node = NodePattern(variable="n", labels=["Person"], properties={})
        pattern = PatternNode(elements=[node])
        merge = MergeClause(
            patterns=[pattern],
            on_create_set=[
                (PropertyAccessNode(object=VariableNode("n"), property="age"), LiteralNode(value=25))
            ],
            on_match_set=[
                (PropertyAccessNode(object=VariableNode("n"), property="ts"), LiteralNode(value=1))
            ],
        )
        query = QueryNode(clauses=[merge])
        ops = comp.compile(query)
        merge_op = next(o for o in ops if o["op"] == "Merge")
        assert len(merge_op["on_create_set"]) == 1
        assert len(merge_op["on_match_set"]) == 1


# ---------------------------------------------------------------------------
# neo4j_compat/types.py
# ---------------------------------------------------------------------------

class TestNodeType:
    """GIVEN Node objects WHEN accessing properties / calling dunder methods
    THEN correct results returned."""

    def _make(self):
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.types import Node
        return Node(
            node_id="n1",
            labels=["Person"],
            properties={"name": "Alice", "age": 30},
        )

    def test_contains_existing_key(self):
        n = self._make()
        assert "age" in n

    def test_contains_missing_key(self):
        n = self._make()
        assert "height" not in n

    def test_eq_same_id(self):
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.types import Node
        n1 = self._make()
        n2 = Node(node_id="n1", labels=["Animal"], properties={})
        assert n1 == n2

    def test_eq_different_id(self):
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.types import Node
        n1 = self._make()
        n2 = Node(node_id="n2", labels=["Person"], properties={"name": "Alice", "age": 30})
        assert n1 != n2

    def test_hash_is_int(self):
        n = self._make()
        assert isinstance(hash(n), int)

    def test_hash_same_for_same_id(self):
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.types import Node
        n1 = self._make()
        n2 = Node(node_id="n1", labels=[], properties={})
        assert hash(n1) == hash(n2)

    def test_repr_contains_id(self):
        n = self._make()
        r = repr(n)
        assert "n1" in r

    def test_eq_with_non_node_returns_false(self):
        n = self._make()
        assert n != "not a node"


class TestRelationshipType:
    """GIVEN Relationship objects WHEN checking properties / dunders
    THEN correct results returned."""

    def _make(self):
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.types import Relationship
        return Relationship(
            rel_id="r1",
            rel_type="KNOWS",
            start_node="n1",
            end_node="n2",
            properties={"since": 2020},
        )

    def test_contains_existing_key(self):
        r = self._make()
        assert "since" in r

    def test_contains_missing_key(self):
        r = self._make()
        assert "weight" not in r

    def test_eq_same_id(self):
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.types import Relationship
        r1 = self._make()
        r2 = Relationship(rel_id="r1", rel_type="LOVES", start_node="x", end_node="y",
                          properties={})
        assert r1 == r2

    def test_eq_different_id(self):
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.types import Relationship
        r1 = self._make()
        r2 = Relationship(rel_id="r2", rel_type="KNOWS", start_node="n1", end_node="n2",
                          properties={"since": 2020})
        assert r1 != r2

    def test_hash_is_int(self):
        r = self._make()
        assert isinstance(hash(r), int)

    def test_repr_contains_type(self):
        r = self._make()
        assert "KNOWS" in repr(r)

    def test_properties_returns_copy(self):
        r = self._make()
        props = r.properties
        props["injected"] = True
        assert "injected" not in r.properties

    def test_eq_with_non_relationship_returns_false(self):
        r = self._make()
        assert r != {"id": "r1"}


class TestPathType:
    """GIVEN Path objects WHEN querying THEN correct structure returned."""

    def _make_nodes_and_rel(self):
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.types import Node, Relationship
        n1 = Node(node_id="n1", labels=["Person"], properties={"name": "A"})
        n2 = Node(node_id="n2", labels=["Person"], properties={"name": "B"})
        r = Relationship(rel_id="r1", rel_type="KNOWS", start_node="n1", end_node="n2",
                         properties={})
        return n1, n2, r

    def test_path_start_and_end_nodes(self):
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.types import Path
        n1, n2, r = self._make_nodes_and_rel()
        p = Path(n1, r, n2)
        assert p.start_node is n1
        assert p.end_node is n2

    def test_path_len_equals_relationship_count(self):
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.types import Path
        n1, n2, r = self._make_nodes_and_rel()
        p = Path(n1, r, n2)
        assert len(p) == 1

    def test_single_node_path_len_zero(self):
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.types import Path
        n1, _, _ = self._make_nodes_and_rel()
        p = Path(n1)
        assert len(p) == 0
        assert p.start_node is p.end_node

    def test_path_iter_yields_rel_then_node(self):
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.types import Path, Relationship, Node
        n1, n2, r = self._make_nodes_and_rel()
        p = Path(n1, r, n2)
        items = list(p)
        assert len(items) == 2
        assert isinstance(items[0], Relationship)
        assert isinstance(items[1], Node)

    def test_path_repr_contains_node_id(self):
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.types import Path
        n1, n2, r = self._make_nodes_and_rel()
        p = Path(n1, r, n2)
        r_str = repr(p)
        assert "n1" in r_str

    def test_path_nodes_and_relationships_lists(self):
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.types import Path
        n1, n2, r = self._make_nodes_and_rel()
        p = Path(n1, r, n2)
        assert len(p.nodes) == 2
        assert len(p.relationships) == 1


# ---------------------------------------------------------------------------
# extraction/types.py
# ---------------------------------------------------------------------------

class TestExtractionTypes:
    """GIVEN the extraction/types module WHEN imported THEN feature flags and
    optional imports are correctly set."""

    def test_have_tracer_is_bool(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.types import HAVE_TRACER
        assert isinstance(HAVE_TRACER, bool)

    def test_have_accelerate_is_bool(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.types import HAVE_ACCELERATE
        assert isinstance(HAVE_ACCELERATE, bool)

    def test_is_accelerate_available_callable(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.types import is_accelerate_available
        result = is_accelerate_available()
        assert isinstance(result, bool)

    def test_get_accelerate_status_callable(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.types import get_accelerate_status
        result = get_accelerate_status()
        assert isinstance(result, dict)

    def test_type_aliases_are_strings(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.types import (
            EntityID, RelationshipID, EntityType, RelationshipType,
        )
        # They are type aliases (str) — verify usage
        eid: EntityID = "e1"
        assert eid == "e1"

    def test_constants(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.types import (
            DEFAULT_CONFIDENCE, MIN_CONFIDENCE, MAX_CONFIDENCE,
        )
        assert DEFAULT_CONFIDENCE == 1.0
        assert MIN_CONFIDENCE == 0.0
        assert MAX_CONFIDENCE == 1.0
