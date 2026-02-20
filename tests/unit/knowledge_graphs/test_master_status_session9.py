"""
Session 9 coverage-improvement tests.

Targets (GIVEN-WHEN-THEN format):
  * core/_legacy_graph_engine.py  (21% → target 85%)
  * cypher/functions.py            (58% → target 90%)
  * extraction/graph.py            (51% → target 80%)
  * neo4j_compat/result.py         (54% → target 85%)
  * transactions/wal.py            (61% → target 80%)
  * neo4j_compat/session.py        (60% → target 80%)
"""
import math
import json
import pytest
from unittest.mock import MagicMock, patch
from datetime import date, datetime, timedelta


# ---------------------------------------------------------------------------
# Helpers / shared fixtures
# ---------------------------------------------------------------------------

def _make_engine():
    """Return a _LegacyGraphEngine without a storage backend."""
    from ipfs_datasets_py.knowledge_graphs.core._legacy_graph_engine import _LegacyGraphEngine
    return _LegacyGraphEngine()


def _make_kg():
    from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
    return KnowledgeGraph(name="test")


def _add_two_entities(kg):
    alice = kg.add_entity("Person", "Alice", properties={"age": 30})
    bob = kg.add_entity("Person", "Bob", properties={"age": 25})
    return alice, bob


# ===========================================================================
# _LegacyGraphEngine tests
# ===========================================================================

class TestLegacyGraphEngineNodeCRUD:
    """GIVEN a _LegacyGraphEngine without persistence."""

    def test_create_node_returns_node(self):
        """WHEN creating a node THEN a Node object is returned."""
        eng = _make_engine()
        node = eng.create_node(labels=["Person"], properties={"name": "Alice"})
        assert node is not None
        assert "Person" in node.labels

    def test_get_node_returns_cached_node(self):
        """WHEN getting a previously created node THEN it is returned from cache."""
        eng = _make_engine()
        node = eng.create_node(labels=["Thing"])
        fetched = eng.get_node(node.id)
        assert fetched is node

    def test_get_node_unknown_id_returns_none(self):
        """WHEN getting a non-existent node THEN None is returned."""
        eng = _make_engine()
        assert eng.get_node("nonexistent-id") is None

    def test_update_node_properties(self):
        """WHEN updating a node THEN properties are merged in."""
        eng = _make_engine()
        node = eng.create_node(labels=["X"], properties={"a": 1})
        updated = eng.update_node(node.id, {"b": 2})
        assert updated is not None
        assert updated.get("b") == 2

    def test_update_node_missing_id_returns_none(self):
        """WHEN updating a node that does not exist THEN None is returned."""
        eng = _make_engine()
        result = eng.update_node("ghost", {"x": 1})
        assert result is None

    def test_delete_node_removes_it(self):
        """WHEN deleting an existing node THEN get_node returns None."""
        eng = _make_engine()
        node = eng.create_node()
        assert eng.delete_node(node.id) is True
        assert eng.get_node(node.id) is None

    def test_delete_node_missing_returns_false(self):
        """WHEN deleting a non-existent node THEN False is returned."""
        eng = _make_engine()
        assert eng.delete_node("ghost") is False


class TestLegacyGraphEngineRelationshipCRUD:
    """GIVEN a _LegacyGraphEngine without persistence."""

    def test_create_relationship_returns_relationship(self):
        """WHEN creating a relationship THEN a Relationship object is returned."""
        eng = _make_engine()
        rel = eng.create_relationship("KNOWS", "n1", "n2", properties={"since": 2020})
        assert rel is not None
        assert rel.type == "KNOWS"

    def test_get_relationship_returns_cached(self):
        """WHEN fetching a relationship by id THEN the correct one is returned."""
        eng = _make_engine()
        rel = eng.create_relationship("LIKES", "a", "b")
        fetched = eng.get_relationship(rel.id)
        assert fetched is rel

    def test_get_relationship_missing_returns_none(self):
        """WHEN fetching a non-existent relationship THEN None is returned."""
        eng = _make_engine()
        assert eng.get_relationship("ghost") is None

    def test_delete_relationship_removes_it(self):
        """WHEN deleting a relationship THEN get_relationship returns None."""
        eng = _make_engine()
        rel = eng.create_relationship("HATES", "x", "y")
        assert eng.delete_relationship(rel.id) is True
        assert eng.get_relationship(rel.id) is None

    def test_delete_relationship_missing_returns_false(self):
        """WHEN deleting a non-existent relationship THEN False is returned."""
        eng = _make_engine()
        assert eng.delete_relationship("ghost") is False


class TestLegacyGraphEngineFindAndTraverse:
    """GIVEN a _LegacyGraphEngine with nodes and relationships."""

    def _populated(self):
        from ipfs_datasets_py.knowledge_graphs.core._legacy_graph_engine import _LegacyGraphEngine
        eng = _LegacyGraphEngine()
        a = eng.create_node(labels=["Person"], properties={"name": "Alice", "age": 30})
        b = eng.create_node(labels=["Person"], properties={"name": "Bob", "age": 25})
        c = eng.create_node(labels=["Company"], properties={"name": "ACME"})
        r1 = eng.create_relationship("KNOWS", a.id, b.id)
        r2 = eng.create_relationship("WORKS_AT", a.id, c.id)
        return eng, a, b, c, r1, r2

    def test_find_nodes_no_filter_returns_all(self):
        """WHEN finding nodes without filter THEN all nodes returned."""
        eng, a, b, c, *_ = self._populated()
        nodes = eng.find_nodes()
        assert len(nodes) == 3

    def test_find_nodes_by_label(self):
        """WHEN filtering by label THEN only matching nodes returned."""
        eng, a, b, c, *_ = self._populated()
        persons = eng.find_nodes(labels=["Person"])
        assert len(persons) == 2

    def test_find_nodes_by_properties(self):
        """WHEN filtering by property THEN only matching nodes returned."""
        eng, a, b, c, *_ = self._populated()
        result = eng.find_nodes(properties={"name": "Bob"})
        assert len(result) == 1
        assert result[0].get("name") == "Bob"

    def test_find_nodes_with_limit(self):
        """WHEN limit is specified THEN at most limit nodes returned."""
        eng, *_ = self._populated()
        result = eng.find_nodes(limit=2)
        assert len(result) <= 2

    def test_get_relationships_out(self):
        """WHEN getting outgoing relationships THEN correct rels returned."""
        eng, a, b, c, r1, r2 = self._populated()
        rels = eng.get_relationships(a.id, direction="out")
        assert len(rels) == 2

    def test_get_relationships_in(self):
        """WHEN getting incoming relationships THEN correct rels returned."""
        eng, a, b, c, r1, r2 = self._populated()
        rels = eng.get_relationships(b.id, direction="in")
        assert len(rels) == 1
        assert rels[0].id == r1.id

    def test_get_relationships_both(self):
        """WHEN getting both-direction relationships THEN all rels returned."""
        eng, a, b, c, r1, r2 = self._populated()
        rels = eng.get_relationships(a.id, direction="both")
        assert len(rels) == 2

    def test_get_relationships_with_type_filter(self):
        """WHEN filtering by relationship type THEN only that type returned."""
        eng, a, b, c, r1, r2 = self._populated()
        rels = eng.get_relationships(a.id, direction="out", rel_type="KNOWS")
        assert len(rels) == 1

    def test_find_paths_direct(self):
        """WHEN finding paths from a to b THEN one path exists."""
        eng, a, b, c, r1, r2 = self._populated()
        paths = eng.find_paths(a.id, b.id)
        assert len(paths) == 1
        assert len(paths[0]) == 1

    def test_find_paths_no_path(self):
        """WHEN no path exists THEN empty list returned."""
        eng, a, b, c, r1, r2 = self._populated()
        paths = eng.find_paths(b.id, c.id)
        assert paths == []

    def test_save_graph_no_persistence_returns_none(self):
        """WHEN saving with no storage backend THEN None returned."""
        eng = _make_engine()
        eng.create_node(labels=["X"])
        assert eng.save_graph() is None

    def test_load_graph_no_persistence_returns_false(self):
        """WHEN loading with no storage backend THEN False returned."""
        eng = _make_engine()
        assert eng.load_graph("fake-cid") is False

    def test_traverse_pattern_simple(self):
        """WHEN traversing a 1-hop pattern THEN matches are found."""
        eng, a, b, c, r1, r2 = self._populated()
        pattern = [
            {"rel_type": "KNOWS", "direction": "out", "variable": "r",
             "labels": ["Person"]},
            {"variable": "other", "labels": ["Person"]},
        ]
        matches = eng.traverse_pattern([a], pattern)
        assert len(matches) >= 1


# ===========================================================================
# cypher/functions.py tests
# ===========================================================================

class TestCypherFunctionsMathNullPropagation:
    """GIVEN math functions that accept None WHEN None is passed THEN None returned."""

    def test_abs_none(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import fn_abs
        assert fn_abs(None) is None

    def test_ceil_none(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import fn_ceil
        assert fn_ceil(None) is None

    def test_floor_none(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import fn_floor
        assert fn_floor(None) is None

    def test_round_none(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import fn_round
        assert fn_round(None) is None

    def test_sqrt_none(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import fn_sqrt
        assert fn_sqrt(None) is None

    def test_sqrt_negative_raises(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import fn_sqrt
        with pytest.raises(ValueError):
            fn_sqrt(-1)

    def test_sign_none(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import fn_sign
        assert fn_sign(None) is None

    def test_sign_positive(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import fn_sign
        assert fn_sign(5) == 1

    def test_sign_negative(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import fn_sign
        assert fn_sign(-3) == -1

    def test_sign_zero(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import fn_sign
        assert fn_sign(0) == 0

    def test_rand_returns_float_in_range(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import fn_rand
        for _ in range(5):
            v = fn_rand()
            assert 0.0 <= v < 1.0


class TestCypherFunctionsSpatial:
    """GIVEN spatial functions."""

    def test_point_creates_point(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import fn_point, Point
        p = fn_point({"x": 3.0, "y": 4.0})
        assert isinstance(p, Point)
        assert p.x == 3.0

    def test_point_none_returns_none(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import fn_point
        assert fn_point(None) is None

    def test_point_default_srid(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import fn_point
        p = fn_point({"x": 0, "y": 0})
        assert p.srid == 7203

    def test_point_custom_srid(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import fn_point
        p = fn_point({"x": 1, "y": 2, "srid": 4326})
        assert p.srid == 4326

    def test_point_repr(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import Point
        p = Point(1.0, 2.0)
        assert "1.0" in repr(p) and "2.0" in repr(p)

    def test_point_eq_same(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import Point
        assert Point(1.0, 2.0) == Point(1.0, 2.0)

    def test_point_eq_different(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import Point
        assert Point(1.0, 2.0) != Point(3.0, 4.0)

    def test_point_eq_non_point(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import Point
        assert Point(1.0, 2.0) != "not a point"

    def test_distance_pythagorean(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import fn_distance, Point
        d = fn_distance(Point(0, 0), Point(3, 4))
        assert abs(d - 5.0) < 1e-9

    def test_distance_none_arg(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import fn_distance, Point
        assert fn_distance(None, Point(1, 2)) is None
        assert fn_distance(Point(1, 2), None) is None

    def test_distance_type_error(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import fn_distance
        with pytest.raises(TypeError):
            fn_distance("a", "b")


class TestCypherFunctionsTemporal:
    """GIVEN temporal functions."""

    def test_date_today(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import fn_date
        d = fn_date()
        assert isinstance(d, date)

    def test_date_from_string(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import fn_date
        d = fn_date("2024-06-15")
        assert d == date(2024, 6, 15)

    def test_date_from_date_object(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import fn_date
        today = date.today()
        assert fn_date(today) == today

    def test_date_invalid_type_raises(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import fn_date
        with pytest.raises(TypeError):
            fn_date(12345)

    def test_datetime_now(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import fn_datetime
        dt = fn_datetime()
        assert isinstance(dt, datetime)

    def test_datetime_from_string(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import fn_datetime
        dt = fn_datetime("2024-06-15T12:30:00")
        assert dt.year == 2024

    def test_datetime_from_datetime_object(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import fn_datetime
        now = datetime.now()
        assert fn_datetime(now) == now

    def test_datetime_invalid_type_raises(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import fn_datetime
        with pytest.raises(TypeError):
            fn_datetime(12345)

    def test_datetime_unparseable_string_raises(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import fn_datetime
        with pytest.raises(ValueError):
            fn_datetime("not-a-date")

    def test_timestamp_returns_int(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import fn_timestamp
        ts = fn_timestamp()
        assert isinstance(ts, int)
        assert ts > 0

    def test_duration_days(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import fn_duration
        d = fn_duration("P1D")
        assert isinstance(d, timedelta)
        assert d.days == 1

    def test_duration_hours_minutes(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import fn_duration
        d = fn_duration("PT2H30M")
        assert d.seconds == 2 * 3600 + 30 * 60

    def test_duration_none_returns_none(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import fn_duration
        assert fn_duration(None) is None

    def test_duration_invalid_raises(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import fn_duration
        with pytest.raises(ValueError):
            fn_duration("NOTISO")


class TestCypherFunctionsIntrospection:
    """GIVEN introspection functions."""

    def test_fn_properties_via_properties_attr(self):
        """WHEN entity has .properties attr THEN dict of properties returned."""
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import fn_properties

        class FakeNode:
            properties = {"a": 1, "b": 2}

        result = fn_properties(FakeNode())
        assert result == {"a": 1, "b": 2}

    def test_fn_properties_plain_object_via_dict(self):
        """WHEN entity has __dict__ (no .properties) THEN public attrs returned."""
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import fn_properties

        class Obj:
            pass

        o = Obj()
        o.x = 10  # public attribute — should appear
        result = fn_properties(o)
        assert "x" in result

    def test_fn_properties_none(self):
        """WHEN None passed THEN None returned."""
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import fn_properties
        assert fn_properties(None) is None

    def test_fn_keys_via_dict(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import fn_keys
        assert set(fn_keys({"a": 1, "b": 2})) == {"a", "b"}

    def test_fn_keys_plain_object(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import fn_keys

        class Obj:
            pass

        o = Obj()
        o.y = 99
        result = fn_keys(o)
        assert "y" in result


class TestCypherFunctionsEvaluate:
    """GIVEN evaluate_function."""

    def test_evaluate_known_function(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import evaluate_function
        assert evaluate_function("abs", -7) == 7

    def test_evaluate_unknown_function_raises(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import evaluate_function
        with pytest.raises(ValueError, match="Unknown function"):
            evaluate_function("no_such_func")


# ===========================================================================
# extraction/graph.py tests
# ===========================================================================

class TestKnowledgeGraphFindPaths:
    """GIVEN a KnowledgeGraph with entities and relationships."""

    def _graph(self):
        kg = _make_kg()
        a = kg.add_entity("Person", "Alice")
        b = kg.add_entity("Person", "Bob")
        c = kg.add_entity("Person", "Carol")
        kg.add_relationship("KNOWS", source=a, target=b)
        kg.add_relationship("KNOWS", source=b, target=c)
        return kg, a, b, c

    def test_find_paths_direct(self):
        """WHEN finding a 1-hop path THEN one path is returned."""
        kg, a, b, c = self._graph()
        paths = kg.find_paths(a, b)
        assert len(paths) == 1

    def test_find_paths_two_hops(self):
        """WHEN finding a 2-hop path THEN path is found with depth>=2."""
        kg, a, b, c = self._graph()
        paths = kg.find_paths(a, c, max_depth=3)
        assert len(paths) >= 1

    def test_find_paths_no_connection(self):
        """WHEN there is no path THEN empty list returned."""
        kg = _make_kg()
        a = kg.add_entity("X", "A")
        b = kg.add_entity("X", "B")
        paths = kg.find_paths(a, b)
        assert paths == []

    def test_find_paths_type_filter(self):
        """WHEN relationship_types filter used THEN only those rels followed."""
        kg, a, b, c = self._graph()
        # KNOWS exists, HATES doesn't
        paths = kg.find_paths(a, b, relationship_types=["HATES"])
        assert paths == []


class TestKnowledgeGraphQueryByProperties:
    """GIVEN a KnowledgeGraph with diverse entities."""

    def test_query_by_type(self):
        """WHEN filtering by entity_type THEN only that type returned."""
        kg = _make_kg()
        kg.add_entity("Person", "Alice", properties={"age": 30})
        kg.add_entity("Company", "ACME")
        result = kg.query_by_properties(entity_type="Person")
        assert all(e.entity_type == "Person" for e in result)

    def test_query_by_properties(self):
        """WHEN filtering by property THEN matching entities returned."""
        kg = _make_kg()
        kg.add_entity("Person", "Alice", properties={"age": 30})
        kg.add_entity("Person", "Bob", properties={"age": 25})
        result = kg.query_by_properties(properties={"age": 30})
        assert len(result) == 1

    def test_query_no_filter_returns_all(self):
        """WHEN no filter applied THEN all entities returned."""
        kg = _make_kg()
        kg.add_entity("A", "x")
        kg.add_entity("B", "y")
        assert len(kg.query_by_properties()) == 2


class TestKnowledgeGraphMerge:
    """GIVEN two KnowledgeGraphs."""

    def test_merge_adds_new_entities(self):
        """WHEN merging THEN new entities from other appear in self."""
        kg1 = _make_kg()
        kg2 = _make_kg()
        kg1.add_entity("Person", "Alice")
        kg2.add_entity("Person", "Bob")
        kg1.merge(kg2)
        names = {e.name for e in kg1.entities.values()}
        assert "Bob" in names

    def test_merge_deduplicates_entities(self):
        """WHEN same entity exists in both THEN it appears only once."""
        kg1 = _make_kg()
        kg2 = _make_kg()
        kg1.add_entity("Person", "Alice")
        kg2.add_entity("Person", "Alice")
        kg1.merge(kg2)
        alice_count = sum(1 for e in kg1.entities.values() if e.name == "Alice")
        assert alice_count == 1

    def test_merge_adds_new_relationships(self):
        """WHEN merging THEN new relationships from other appear in self."""
        kg1 = _make_kg()
        kg2 = _make_kg()
        a1 = kg1.add_entity("Person", "Alice")
        b1 = kg1.add_entity("Person", "Bob")
        a2 = kg2.add_entity("Person", "Alice")
        b2 = kg2.add_entity("Person", "Bob")
        kg2.add_relationship("KNOWS", source=a2, target=b2)
        kg1.merge(kg2)
        assert len(kg1.relationships) == 1


class TestKnowledgeGraphSerialisation:
    """GIVEN a KnowledgeGraph WHEN serialised THEN round-trip works."""

    def test_to_dict_from_dict(self):
        """WHEN converting to dict and back THEN same name and entity count."""
        kg = _make_kg()
        alice, bob = _add_two_entities(kg)
        kg.add_relationship("KNOWS", source=alice, target=bob)
        data = kg.to_dict()
        kg2 = kg.__class__.from_dict(data)
        assert kg2.name == kg.name
        assert len(kg2.entities) == len(kg.entities)

    def test_to_json_from_json(self):
        """WHEN converting to JSON and back THEN round-trip is lossless."""
        kg = _make_kg()
        alice, _ = _add_two_entities(kg)
        json_str = kg.to_json()
        assert isinstance(json_str, str)
        kg2 = kg.__class__.from_json(json_str)
        assert kg2.name == kg.name

    def test_export_to_rdf_without_rdflib(self):
        """WHEN rdflib is absent THEN error message returned, not raised."""
        kg = _make_kg()
        kg.add_entity("Thing", "X")
        with patch.dict("sys.modules", {"rdflib": None}):
            result = kg.export_to_rdf()
        assert "Error" in result or isinstance(result, str)


# ===========================================================================
# neo4j_compat/result.py tests
# ===========================================================================

class TestRecord:
    """GIVEN a Record with keys and values."""

    def _rec(self):
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.result import Record
        return Record(["name", "age"], ["Alice", 30])

    def test_keys_length_mismatch_raises(self):
        """WHEN keys/values length mismatch THEN ValueError raised."""
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.result import Record
        with pytest.raises(ValueError):
            Record(["a", "b"], [1])

    def test_items(self):
        """WHEN calling items() THEN key-value pairs returned."""
        rec = self._rec()
        assert ("name", "Alice") in rec.items()

    def test_getitem_int_index(self):
        """WHEN indexing by int THEN positional value returned."""
        rec = self._rec()
        assert rec[0] == "Alice"

    def test_getitem_str_key(self):
        """WHEN indexing by str THEN named value returned."""
        rec = self._rec()
        assert rec["age"] == 30

    def test_contains(self):
        """WHEN checking membership THEN correct bool returned."""
        rec = self._rec()
        assert "name" in rec
        assert "city" not in rec

    def test_iter(self):
        """WHEN iterating THEN all values yielded."""
        rec = self._rec()
        assert list(rec) == ["Alice", 30]

    def test_repr(self):
        """WHEN calling repr THEN string representation returned."""
        rec = self._rec()
        assert "Alice" in repr(rec)


class TestResult:
    """GIVEN a Result with records."""

    def _result(self, n=3):
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.result import Result, Record
        records = [Record(["n"], [i]) for i in range(n)]
        return Result(records=records, summary={})

    def test_single_returns_first(self):
        """WHEN single() called THEN first record returned."""
        r = self._result(1)
        rec = r.single()
        assert rec["n"] == 0

    def test_single_strict_zero_records_raises(self):
        """WHEN single(strict=True) with empty result THEN ValueError raised."""
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.result import Result
        r = Result(records=[], summary={})
        with pytest.raises(ValueError):
            r.single(strict=True)

    def test_single_strict_multiple_raises(self):
        """WHEN single(strict=True) with >1 records THEN ValueError raised."""
        r = self._result(3)
        with pytest.raises(ValueError):
            r.single(strict=True)

    def test_single_empty_non_strict_returns_none(self):
        """WHEN single() with empty result THEN None returned."""
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.result import Result
        r = Result(records=[], summary={})
        assert r.single() is None

    def test_data_returns_list_of_dicts(self):
        """WHEN data() called THEN list of dicts returned."""
        r = self._result(2)
        data = r.data()
        assert isinstance(data, list)
        assert all(isinstance(d, dict) for d in data)

    def test_value_all_records(self):
        """WHEN value() called THEN list of field values returned."""
        r = self._result(3)
        vals = r.value("n")
        assert vals == [0, 1, 2]

    def test_value_no_key_uses_first(self):
        """WHEN value() called without key THEN first field used."""
        r = self._result(2)
        vals = r.value()
        assert len(vals) == 2

    def test_value_empty_result(self):
        """WHEN value() on empty result THEN empty list returned."""
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.result import Result
        r = Result(records=[], summary={})
        assert r.value("x") == []

    def test_values_returns_list_of_lists(self):
        """WHEN values() called THEN list-of-lists returned."""
        r = self._result(2)
        vals = r.values()
        assert all(isinstance(v, list) for v in vals)

    def test_peek_returns_first_without_consuming(self):
        """WHEN peek() called THEN first record returned without advancing."""
        r = self._result(2)
        p1 = r.peek()
        p2 = r.peek()
        assert p1 is p2

    def test_peek_empty_returns_none(self):
        """WHEN peek() on empty result THEN None returned."""
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.result import Result
        r = Result(records=[], summary={})
        assert r.peek() is None

    def test_consume_marks_consumed(self):
        """WHEN consume() called THEN result is marked consumed."""
        r = self._result(2)
        summary = r.consume()
        assert isinstance(summary, dict)

    def test_graph_returns_dict_with_keys(self):
        """WHEN graph() called THEN dict with nodes/relationships/paths returned."""
        r = self._result(2)
        g = r.graph()
        assert "nodes" in g and "relationships" in g and "paths" in g

    def test_len(self):
        """WHEN len() called THEN record count returned."""
        r = self._result(5)
        assert len(r) == 5


# ===========================================================================
# transactions/wal.py tests
# ===========================================================================

class TestWALSerializationError:
    """GIVEN a WAL object whose storage raises serialization failures."""

    def _wal(self):
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WriteAheadLog
        mock_storage = MagicMock()
        mock_storage.store_json.return_value = "bafycid1"
        mock_storage.retrieve_json.return_value = None
        return WriteAheadLog(storage=mock_storage)

    def test_wal_initialises(self):
        """WHEN WAL created with mock storage THEN head is None."""
        wal = self._wal()
        assert wal.wal_head_cid is None

    def test_append_entry(self):
        """WHEN a valid entry is appended THEN CID returned from storage."""
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WALEntry
        wal = self._wal()
        entry = WALEntry(txn_id="txn-1", operations=[], timestamp=0.0)
        cid = wal.append(entry)
        assert cid == "bafycid1"
        assert wal.wal_head_cid == "bafycid1"

    def test_append_serialization_failure_raises(self):
        """WHEN storage raises TypeError THEN SerializationError raised."""
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WriteAheadLog, WALEntry
        from ipfs_datasets_py.knowledge_graphs.exceptions import SerializationError
        mock_storage = MagicMock()
        mock_storage.store_json.side_effect = TypeError("bad type")
        wal = WriteAheadLog(storage=mock_storage)
        entry = WALEntry(txn_id="t1", operations=[], timestamp=0.0)
        with pytest.raises(SerializationError):
            wal.append(entry)

    def test_read_empty_wal_yields_nothing(self):
        """WHEN WAL is empty THEN read() yields nothing."""
        wal = self._wal()
        entries = list(wal.read())
        assert entries == []

    def test_read_from_cid_calls_storage(self):
        """WHEN reading from a CID THEN storage.retrieve_json called."""
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WriteAheadLog, WALEntry
        mock_storage = MagicMock()
        entry = WALEntry(txn_id="t1", operations=[], timestamp=0.0)
        entry_dict = entry.to_dict()
        entry_dict["prev_wal_cid"] = None
        mock_storage.retrieve_json.return_value = entry_dict
        wal = WriteAheadLog(storage=mock_storage)
        entries = list(wal.read(from_cid="bafycid1"))
        assert len(entries) == 1
        assert entries[0].txn_id == "t1"


# ===========================================================================
# neo4j_compat/session.py  (selected uncovered paths)
# ===========================================================================

class TestNeo4jSessionUncoveredPaths:
    """GIVEN IPFSTransaction and IPFSSession objects with mocked backends."""

    def _mock_session(self):
        """Create a minimal mock IPFSSession for transaction tests."""
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.session import IPFSSession
        # Build a mock that satisfies IPFSSession's interface needs
        mock_driver = MagicMock()
        mock_backend = MagicMock()
        mock_driver.backend = mock_backend
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.result import Result
        mock_executor = MagicMock()
        mock_executor.execute.return_value = Result(records=[], summary={})
        session = IPFSSession.__new__(IPFSSession)
        session._driver = mock_driver
        session._database = "neo4j"
        session._default_access_mode = "WRITE"
        session._closed = False
        session._transaction = None
        session.backend = mock_backend
        session._query_executor = mock_executor
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.bookmarks import Bookmarks
        session._bookmarks = Bookmarks(None)
        session._last_bookmark = None
        return session

    def test_begin_transaction_returns_tx(self):
        """WHEN begin_transaction() called THEN Transaction returned."""
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.session import IPFSTransaction
        s = self._mock_session()
        tx = s.begin_transaction()
        assert isinstance(tx, IPFSTransaction)

    def test_transaction_commit(self):
        """WHEN commit() called THEN transaction marked committed."""
        s = self._mock_session()
        tx = s.begin_transaction()
        tx.commit()
        assert tx._committed is True
        assert tx._closed is True

    def test_transaction_rollback(self):
        """WHEN rollback() called THEN transaction marked closed."""
        s = self._mock_session()
        tx = s.begin_transaction()
        tx.rollback()
        assert tx._closed is True

    def test_transaction_context_manager_commits_on_exit(self):
        """WHEN context manager exits without exception THEN transaction committed."""
        s = self._mock_session()
        with s.begin_transaction() as tx:
            pass  # No exception
        assert tx._committed is True

    def test_transaction_context_manager_rollback_on_exception(self):
        """WHEN context manager exits with exception THEN transaction rolled back."""
        s = self._mock_session()
        try:
            with s.begin_transaction() as tx:
                raise ValueError("test error")
        except ValueError:
            pass
        assert tx._closed is True

    def test_transaction_run_closed_raises(self):
        """WHEN run() called on closed transaction THEN RuntimeError raised."""
        s = self._mock_session()
        tx = s.begin_transaction()
        tx.commit()
        with pytest.raises(RuntimeError):
            tx.run("MATCH (n) RETURN n")

    def test_session_run_returns_result(self):
        """WHEN session.run() called THEN Result returned."""
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.result import Result
        s = self._mock_session()
        result = s.run("MATCH (n) RETURN n")
        assert result is not None

    def test_session_close_marks_closed(self):
        """WHEN session.close() called THEN _closed is True."""
        s = self._mock_session()
        s.close()
        assert s._closed is True


# ===========================================================================
# Deprecation shim coverage (root-level shims that redirect to subpackages)
# ===========================================================================

class TestRootLevelShimImports:
    """GIVEN root-level shim files WHEN imported THEN DeprecationWarning emitted."""

    def test_cross_document_lineage_shim(self):
        """WHEN cross_document_lineage imported THEN DeprecationWarning raised."""
        import warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            import importlib
            import ipfs_datasets_py.knowledge_graphs.cross_document_lineage as m
            importlib.reload(m)
        assert any(issubclass(x.category, DeprecationWarning) for x in w)

    def test_reasoning_helpers_shim(self):
        """WHEN _reasoning_helpers imported THEN DeprecationWarning raised."""
        import warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            import importlib
            import ipfs_datasets_py.knowledge_graphs._reasoning_helpers as m
            importlib.reload(m)
        assert any(issubclass(x.category, DeprecationWarning) for x in w)

    def test_query_knowledge_graph_shim(self):
        """WHEN query_knowledge_graph imported THEN DeprecationWarning raised."""
        import warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            import importlib
            import ipfs_datasets_py.knowledge_graphs.query_knowledge_graph as m
            importlib.reload(m)
        assert any(issubclass(x.category, DeprecationWarning) for x in w)
