"""
Tests for CAR format support using libipld + ipld-car.

Validates:
1. CAR format save/load roundtrip
2. NOT operator evaluation fix (complex WHERE NOT expressions)
3. AND/OR logical operators in compiled expressions

Tests follow GIVEN-WHEN-THEN format per repository standards.
"""

import os
import tempfile

import pytest

from ipfs_datasets_py.knowledge_graphs.migration.formats import (
    GraphData,
    MigrationFormat,
    NodeData,
    RelationshipData,
    SchemaData,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_graph() -> GraphData:
    nodes = [
        NodeData(id="1", labels=["Person"], properties={"name": "Alice", "age": 30}),
        NodeData(id="2", labels=["Person"], properties={"name": "Bob", "age": 25}),
        NodeData(id="3", labels=["City"], properties={"name": "Paris"}),
    ]
    relationships = [
        RelationshipData(
            id="r1", type="KNOWS", start_node="1", end_node="2",
            properties={"since": 2020}
        ),
        RelationshipData(
            id="r2", type="LIVES_IN", start_node="1", end_node="3",
            properties={}
        ),
    ]
    return GraphData(nodes=nodes, relationships=relationships)


# ---------------------------------------------------------------------------
# CAR format roundtrip tests
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_car(tmp_path):
    pytest.importorskip("libipld")
    return str(tmp_path / "graph.car")


class TestCARFormat:
    """Tests for Content Addressable aRchive (CAR) format support."""

    def test_save_car_creates_file(self, tmp_car):
        """
        GIVEN: A graph with nodes and relationships
        WHEN: Saving to CAR format
        THEN: A non-empty .car file is created
        """
        graph = _make_graph()
        graph.save_to_file(tmp_car, format=MigrationFormat.CAR)
        assert os.path.exists(tmp_car)
        assert os.path.getsize(tmp_car) > 0

    def test_load_car_roundtrip_nodes(self, tmp_car):
        """
        GIVEN: A graph saved to CAR format
        WHEN: Loading the CAR file
        THEN: Node count and IDs are preserved
        """
        graph = _make_graph()
        graph.save_to_file(tmp_car, format=MigrationFormat.CAR)
        loaded = GraphData.load_from_file(tmp_car, format=MigrationFormat.CAR)
        assert loaded.node_count == graph.node_count
        original_ids = {n.id for n in graph.nodes}
        loaded_ids = {n.id for n in loaded.nodes}
        assert original_ids == loaded_ids

    def test_load_car_roundtrip_relationships(self, tmp_car):
        """
        GIVEN: A graph saved to CAR format
        WHEN: Loading the CAR file
        THEN: Relationship count and types are preserved
        """
        graph = _make_graph()
        graph.save_to_file(tmp_car, format=MigrationFormat.CAR)
        loaded = GraphData.load_from_file(tmp_car, format=MigrationFormat.CAR)
        assert loaded.relationship_count == graph.relationship_count
        original_types = sorted(r.type for r in graph.relationships)
        loaded_types = sorted(r.type for r in loaded.relationships)
        assert original_types == loaded_types

    def test_load_car_preserves_properties(self, tmp_car):
        """
        GIVEN: A graph with node properties saved to CAR
        WHEN: Loading the CAR file
        THEN: Node properties (name, age) are preserved
        """
        graph = _make_graph()
        graph.save_to_file(tmp_car, format=MigrationFormat.CAR)
        loaded = GraphData.load_from_file(tmp_car, format=MigrationFormat.CAR)
        by_id = {n.id: n for n in loaded.nodes}
        assert by_id["1"].properties["name"] == "Alice"
        assert by_id["2"].properties["name"] == "Bob"

    def test_load_car_preserves_labels(self, tmp_car):
        """
        GIVEN: A graph with node labels saved to CAR
        WHEN: Loading the CAR file
        THEN: Node labels are preserved
        """
        graph = _make_graph()
        graph.save_to_file(tmp_car, format=MigrationFormat.CAR)
        loaded = GraphData.load_from_file(tmp_car, format=MigrationFormat.CAR)
        by_id = {n.id: n for n in loaded.nodes}
        assert "Person" in by_id["1"].labels
        assert "City" in by_id["3"].labels

    def test_car_with_schema(self, tmp_car):
        """
        GIVEN: A graph with schema metadata
        WHEN: Saving and loading via CAR
        THEN: Schema is preserved
        """
        graph = _make_graph()
        graph.schema = SchemaData(
            node_labels=["Person", "City"],
            relationship_types=["KNOWS", "LIVES_IN"],
        )
        graph.save_to_file(tmp_car, format=MigrationFormat.CAR)
        loaded = GraphData.load_from_file(tmp_car, format=MigrationFormat.CAR)
        assert loaded.schema is not None
        assert "Person" in loaded.schema.node_labels

    def test_car_empty_graph(self, tmp_car):
        """
        GIVEN: An empty graph
        WHEN: Saving and loading via CAR
        THEN: Empty graph is preserved
        """
        graph = GraphData()
        graph.save_to_file(tmp_car, format=MigrationFormat.CAR)
        loaded = GraphData.load_from_file(tmp_car, format=MigrationFormat.CAR)
        assert loaded.node_count == 0
        assert loaded.relationship_count == 0

    def test_car_is_binary_format(self, tmp_car):
        """
        GIVEN: A graph saved to CAR format
        WHEN: Reading the raw file bytes
        THEN: File is binary (not plain JSON)
        """
        _make_graph().save_to_file(tmp_car, format=MigrationFormat.CAR)
        with open(tmp_car, "rb") as f:
            header = f.read(8)
        # CAR files start with a varint length followed by CBOR-encoded header
        # They are NOT valid UTF-8 JSON
        assert header[0] != ord("{")


# ---------------------------------------------------------------------------
# NOT operator fix tests
# ---------------------------------------------------------------------------

class TestNotOperatorFix:
    """Tests for the NOT operator evaluation fix in expression_evaluator.py."""

    @pytest.fixture()
    def executor_with_people(self):
        from ipfs_datasets_py.knowledge_graphs.core.query_executor import (
            GraphEngine, QueryExecutor,
        )
        engine = GraphEngine()
        executor = QueryExecutor(graph_engine=engine)
        engine.create_node(labels=["Person"],
                           properties={"name": "Alice", "age": 25, "city": "LA"})
        engine.create_node(labels=["Person"],
                           properties={"name": "Bob", "age": 35, "city": "NYC"})
        engine.create_node(labels=["Person"],
                           properties={"name": "Charlie", "age": 40, "city": "NYC"})
        return executor

    def test_simple_not_operator(self, executor_with_people):
        """
        GIVEN: Persons with ages 25, 35, 40
        WHEN: Query with NOT p.age > 30
        THEN: Only Alice (age 25) is returned
        """
        result = executor_with_people.execute(
            "MATCH (p:Person) WHERE NOT p.age > 30 RETURN p.name as name"
        )
        names = [r["name"] for r in result if "name" in r]
        assert names == ["Alice"]

    def test_complex_not_operator(self, executor_with_people):
        """
        GIVEN: Persons Alice (LA), Bob (NYC, 35), Charlie (NYC, 40)
        WHEN: Query with NOT (p.age > 30 AND p.city = 'NYC')
        THEN: Only Alice is returned (Bob and Charlie match the NOT'd condition)
        """
        result = executor_with_people.execute(
            "MATCH (p:Person) WHERE NOT (p.age > 30 AND p.city = 'NYC') "
            "RETURN p.name as name"
        )
        names = [r["name"] for r in result if "name" in r]
        assert names == ["Alice"]

    def test_not_with_or(self, executor_with_people):
        """
        GIVEN: Persons Alice (LA,25), Bob (NYC,35), Charlie (NYC,40)
        WHEN: Query with NOT (p.city = 'NYC' OR p.age < 0)
        THEN: Only Alice is returned
        """
        result = executor_with_people.execute(
            "MATCH (p:Person) WHERE NOT (p.city = 'NYC' OR p.age < 0) "
            "RETURN p.name as name"
        )
        names = [r["name"] for r in result if "name" in r]
        assert names == ["Alice"]


# ---------------------------------------------------------------------------
# evaluate_compiled_expression unit tests
# ---------------------------------------------------------------------------

class TestCompiledExpressionEval:
    """Unit tests for evaluate_compiled_expression with logical operators."""

    def _eval(self, expr, binding):
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import (
            evaluate_compiled_expression,
        )
        return evaluate_compiled_expression(expr, binding)

    def test_not_true(self):
        assert self._eval({"op": "NOT", "operand": True}, {}) is False

    def test_not_false(self):
        assert self._eval({"op": "NOT", "operand": False}, {}) is True

    def test_not_comparison(self):
        expr = {
            "op": "NOT",
            "operand": {"op": ">", "left": {"property": "p.age"}, "right": 30},
        }
        assert self._eval(expr, {"p": {"age": 25}}) is True
        assert self._eval(expr, {"p": {"age": 35}}) is False

    def test_and_both_true(self):
        expr = {
            "op": "AND",
            "left": {"op": ">", "left": {"property": "p.age"}, "right": 20},
            "right": {"op": "<", "left": {"property": "p.age"}, "right": 50},
        }
        assert bool(self._eval(expr, {"p": {"age": 30}})) is True

    def test_and_one_false(self):
        expr = {
            "op": "AND",
            "left": {"op": ">", "left": {"property": "p.age"}, "right": 20},
            "right": {"op": "<", "left": {"property": "p.age"}, "right": 10},
        }
        assert bool(self._eval(expr, {"p": {"age": 30}})) is False

    def test_or_one_true(self):
        expr = {
            "op": "OR",
            "left": {"op": "=", "left": {"property": "p.city"}, "right": "LA"},
            "right": {"op": "=", "left": {"property": "p.city"}, "right": "NYC"},
        }
        assert bool(self._eval(expr, {"p": {"city": "LA"}})) is True
        assert bool(self._eval(expr, {"p": {"city": "Chicago"}})) is False

    def test_not_and_compound(self):
        expr = {
            "op": "NOT",
            "operand": {
                "op": "AND",
                "left": {"op": ">", "left": {"property": "p.age"}, "right": 30},
                "right": {
                    "op": "=",
                    "left": {"property": "p.city"},
                    "right": "NYC",
                },
            },
        }
        # NOT (age>30 AND city=NYC): Alice passes, Bob fails
        assert self._eval(expr, {"p": {"age": 25, "city": "LA"}}) is True
        assert self._eval(expr, {"p": {"age": 35, "city": "NYC"}}) is False
