"""
Performance benchmarks for the knowledge_graphs module (Workstream F1).

This module provides a small benchmark harness that measures baseline
performance for the three core operations: extraction, query, and migration.

Run directly:
    python tests/unit/knowledge_graphs/test_benchmarks.py

Or via pytest (marked as slow):
    pytest -m slow tests/unit/knowledge_graphs/test_benchmarks.py -v

Targets (all measured on a single-core Python 3.12 environment):
    - Entity extraction  : < 5 ms per 100-word document
    - Cypher parse+compile: < 1 ms per query
    - GraphEngine CRUD   : < 0.5 ms per node/relationship
    - DAG-JSON roundtrip : < 50 ms per 100-node graph
"""

import time
import pytest

from ipfs_datasets_py.knowledge_graphs.extraction.extractor import KnowledgeGraphExtractor
from ipfs_datasets_py.knowledge_graphs.core.graph_engine import GraphEngine
from ipfs_datasets_py.knowledge_graphs.core.query_executor import QueryExecutor
from ipfs_datasets_py.knowledge_graphs.cypher.parser import CypherParser
from ipfs_datasets_py.knowledge_graphs.cypher.compiler import CypherCompiler
from ipfs_datasets_py.knowledge_graphs.migration.formats import (
    GraphData, NodeData, RelationshipData, MigrationFormat,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_TEXT = (
    "Marie Curie was born in Warsaw, Poland in 1867. She studied at the "
    "University of Paris and discovered polonium and radium. She received "
    "two Nobel Prizes: Physics in 1903 and Chemistry in 1911. Her husband "
    "Pierre Curie collaborated with her on radioactivity research."
)

CYPHER_QUERIES = [
    "MATCH (n:Person) RETURN n",
    "MATCH (n:Person) WHERE n.age > 30 RETURN n",
    "MATCH (a:Person)-[r:KNOWS]->(b:Person) RETURN a, b",
    "MATCH (n:Person) RETURN n.name AS name ORDER BY name LIMIT 10",
    "CREATE (n:Person {name: 'Alice', age: 30}) RETURN n",
    "MATCH (n:Person) WHERE n.name = 'Bob' AND n.age < 50 RETURN n",
]


def _build_graph_data(n_nodes: int = 100) -> GraphData:
    """Create a synthetic GraphData with *n_nodes* nodes and n_nodes-1 edges."""
    nodes = [
        NodeData(id=str(i), labels=["Node"], properties={"value": i, "name": f"node_{i}"})
        for i in range(n_nodes)
    ]
    rels = [
        RelationshipData(id=str(i), type="NEXT", start_node=str(i), end_node=str(i + 1))
        for i in range(n_nodes - 1)
    ]
    return GraphData(nodes=nodes, relationships=rels)


# ---------------------------------------------------------------------------
# B1. Extraction benchmarks
# ---------------------------------------------------------------------------

@pytest.mark.slow
class TestExtractionBenchmarks:
    """Benchmark entity/relationship extraction performance."""

    def test_rule_based_extraction_speed(self):
        """
        GIVEN: A ~100-word document
        WHEN: Rule-based extraction is run 50 times
        THEN: Average time is < 5 ms per document
        """
        extractor = KnowledgeGraphExtractor(use_spacy=False, use_transformers=False)
        iterations = 50

        start = time.perf_counter()
        for _ in range(iterations):
            extractor.extract_knowledge_graph(SAMPLE_TEXT)
        elapsed = time.perf_counter() - start

        avg_ms = (elapsed / iterations) * 1000
        assert avg_ms < 5.0, (
            f"Rule-based extraction too slow: {avg_ms:.2f} ms/doc (target < 5 ms)"
        )

    def test_extraction_returns_entities(self):
        """
        GIVEN: A document about Marie Curie
        WHEN: Extracted with rule-based extractor
        THEN: Returns a KnowledgeGraph with at least one entity
        """
        extractor = KnowledgeGraphExtractor(use_spacy=False, use_transformers=False)
        result = extractor.extract_knowledge_graph(SAMPLE_TEXT)
        # Accept both dict-with-knowledge_graph and direct KnowledgeGraph returns
        kg = result.get("knowledge_graph") if isinstance(result, dict) else result
        assert kg is not None
        assert len(kg.entities) > 0


# ---------------------------------------------------------------------------
# B2. Cypher parse + compile benchmarks
# ---------------------------------------------------------------------------

@pytest.mark.slow
class TestCypherBenchmarks:
    """Benchmark Cypher parsing and compilation performance."""

    def test_parse_and_compile_speed(self):
        """
        GIVEN: 6 representative Cypher queries
        WHEN: Each is parsed + compiled 200 times
        THEN: Average time per query is < 1 ms
        """
        parser = CypherParser()
        compiler = CypherCompiler()
        iterations = 200

        total = 0.0
        for query in CYPHER_QUERIES:
            start = time.perf_counter()
            for _ in range(iterations):
                ast = parser.parse(query)
                compiler.compile(ast)
            total += time.perf_counter() - start

        avg_ms = (total / (len(CYPHER_QUERIES) * iterations)) * 1000
        assert avg_ms < 1.0, (
            f"Cypher parse+compile too slow: {avg_ms:.3f} ms/query (target < 1 ms)"
        )

    def test_parse_produces_ir(self):
        """
        GIVEN: A simple MATCH query
        WHEN: Parsed and compiled
        THEN: IR contains at least one operation
        """
        parser = CypherParser()
        compiler = CypherCompiler()
        ast = parser.parse("MATCH (n:Person) RETURN n")
        ir = compiler.compile(ast)
        assert len(ir) > 0


# ---------------------------------------------------------------------------
# B3. GraphEngine CRUD benchmarks
# ---------------------------------------------------------------------------

@pytest.mark.slow
class TestGraphEngineBenchmarks:
    """Benchmark GraphEngine create/read operations."""

    def test_node_creation_speed(self):
        """
        GIVEN: An in-memory GraphEngine
        WHEN: 500 nodes are created
        THEN: Average time per node is < 0.5 ms
        """
        engine = GraphEngine()
        iterations = 500

        start = time.perf_counter()
        for i in range(iterations):
            engine.create_node(
                labels=["Person"],
                properties={"name": f"person_{i}", "age": i % 100}
            )
        elapsed = time.perf_counter() - start

        avg_ms = (elapsed / iterations) * 1000
        assert avg_ms < 0.5, (
            f"Node creation too slow: {avg_ms:.3f} ms/node (target < 0.5 ms)"
        )

    def test_relationship_creation_speed(self):
        """
        GIVEN: An in-memory GraphEngine with 2 nodes
        WHEN: 200 relationships are created between random node pairs
        THEN: Average time per relationship is < 0.5 ms
        """
        engine = GraphEngine()
        # Create a pool of nodes
        nodes = [
            engine.create_node(labels=["X"], properties={"id": i})
            for i in range(20)
        ]
        iterations = 200

        start = time.perf_counter()
        for i in range(iterations):
            src = nodes[i % len(nodes)]
            dst = nodes[(i + 1) % len(nodes)]
            engine.create_relationship("LINK", src.id, dst.id, {"weight": i})
        elapsed = time.perf_counter() - start

        avg_ms = (elapsed / iterations) * 1000
        assert avg_ms < 0.5, (
            f"Relationship creation too slow: {avg_ms:.3f} ms/rel (target < 0.5 ms)"
        )

    def test_cypher_query_on_loaded_graph(self):
        """
        GIVEN: A graph with 50 Person nodes and 200 KNOWS relationships
        WHEN: A simple MATCH (n:Person) RETURN n is executed
        THEN: Completes in < 50 ms total
        """
        engine = GraphEngine()
        executor = QueryExecutor(graph_engine=engine)

        # Populate graph
        nodes = [
            engine.create_node(labels=["Person"], properties={"name": f"p{i}", "age": i})
            for i in range(50)
        ]
        for i in range(min(200, len(nodes) - 1)):
            engine.create_relationship("KNOWS", nodes[i].id, nodes[i + 1].id)

        start = time.perf_counter()
        result = list(executor.execute("MATCH (n:Person) RETURN n"))
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 50, (
            f"Cypher query on 50-node graph too slow: {elapsed_ms:.1f} ms (target < 50 ms)"
        )
        assert len(result) == 50


# ---------------------------------------------------------------------------
# B4. Migration format benchmarks
# ---------------------------------------------------------------------------

@pytest.mark.slow
class TestMigrationBenchmarks:
    """Benchmark import/export roundtrip performance."""

    def test_dag_json_roundtrip_speed_100_nodes(self, tmp_path):
        """
        GIVEN: A GraphData with 100 nodes and 99 relationships
        WHEN: Saved to DAG-JSON and loaded back
        THEN: Roundtrip completes in < 50 ms
        """
        import os
        graph = _build_graph_data(100)
        filepath = str(tmp_path / "bench.json")

        start = time.perf_counter()
        graph.save_to_file(filepath, MigrationFormat.DAG_JSON)
        loaded = GraphData.load_from_file(filepath, MigrationFormat.DAG_JSON)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert len(loaded.nodes) == 100
        assert elapsed_ms < 50, (
            f"DAG-JSON roundtrip (100 nodes) too slow: {elapsed_ms:.1f} ms (target < 50 ms)"
        )

    def test_json_lines_roundtrip_speed_100_nodes(self, tmp_path):
        """
        GIVEN: A GraphData with 100 nodes and 99 relationships
        WHEN: Saved to JSON_LINES and loaded back
        THEN: Roundtrip completes in < 10 ms
        """
        graph = _build_graph_data(100)
        filepath = str(tmp_path / "bench.jsonl")

        start = time.perf_counter()
        graph.save_to_file(filepath, MigrationFormat.JSON_LINES)
        loaded = GraphData.load_from_file(filepath, MigrationFormat.JSON_LINES)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert len(loaded.nodes) == 100
        assert elapsed_ms < 10, (
            f"JSON-Lines roundtrip (100 nodes) too slow: {elapsed_ms:.1f} ms (target < 10 ms)"
        )

    def test_graph_data_serialization_to_dict(self):
        """
        GIVEN: A 50-node GraphData
        WHEN: Converted to dict 100 times
        THEN: Average time is < 1 ms per conversion
        """
        graph = _build_graph_data(50)
        iterations = 100

        start = time.perf_counter()
        for _ in range(iterations):
            graph.to_dict()
        elapsed = time.perf_counter() - start

        avg_ms = (elapsed / iterations) * 1000
        assert avg_ms < 1.0, (
            f"to_dict() too slow: {avg_ms:.3f} ms/call (target < 1 ms)"
        )


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    print("=" * 60)
    print("Knowledge Graphs — Performance Benchmark")
    print("=" * 60)

    # Quick inline timing (no pytest required)
    benchmarks = [
        ("Cypher parse+compile (100 iterations)", lambda: [
            CypherCompiler().compile(CypherParser().parse(q))
            for q in CYPHER_QUERIES
            for _ in range(100)
        ]),
        ("GraphEngine: 200 node creates", lambda: [
            GraphEngine().create_node(labels=["P"], properties={"i": i})
            for i in range(200)
        ]),
        ("GraphData.to_dict() (50 nodes, 100 calls)", lambda: [
            _build_graph_data(50).to_dict()
            for _ in range(100)
        ]),
    ]

    for name, fn in benchmarks:
        t0 = time.perf_counter()
        fn()
        ms = (time.perf_counter() - t0) * 1000
        print(f"  {name}: {ms:.1f} ms")

    print("=" * 60)
    print("Run 'pytest -m slow tests/unit/knowledge_graphs/test_benchmarks.py -v' for full suite")
