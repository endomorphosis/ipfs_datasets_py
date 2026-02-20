"""
Tests for the pluggable format registry and streaming export (Workstreams H2, F2).

Tests follow GIVEN-WHEN-THEN format per repository standards.
"""

import json
import os
import pytest

from ipfs_datasets_py.knowledge_graphs.migration.formats import (
    GraphData,
    NodeData,
    RelationshipData,
    SchemaData,
    MigrationFormat,
    register_format,
    registered_formats,
    _format_registry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_small_graph(n_nodes: int = 5, n_rels: int = 4) -> GraphData:
    nodes = [
        NodeData(id=f"n{i}", labels=["Person"], properties={"name": f"User{i}", "age": 20 + i})
        for i in range(n_nodes)
    ]
    rels = [
        RelationshipData(
            id=f"r{i}", type="KNOWS",
            start_node=f"n{i}", end_node=f"n{i+1}",
            properties={"since": 2020 + i},
        )
        for i in range(n_rels)
    ]
    return GraphData(nodes=nodes, relationships=rels, metadata={"source": "test"})


# ---------------------------------------------------------------------------
# H2: Format registry
# ---------------------------------------------------------------------------

class TestFormatRegistry:
    """The format registry must support registration, lookup, and listing."""

    def test_builtin_formats_are_registered(self):
        """
        GIVEN: Module has been imported
        WHEN: registered_formats() is called
        THEN: All built-in formats are in the list
        """
        # GIVEN / WHEN
        fmts = registered_formats()

        # THEN
        assert MigrationFormat.DAG_JSON in fmts
        assert MigrationFormat.JSON_LINES in fmts
        assert MigrationFormat.GRAPHML in fmts
        assert MigrationFormat.GEXF in fmts
        assert MigrationFormat.PAJEK in fmts
        assert MigrationFormat.CAR in fmts

    def test_register_custom_format(self, tmp_path):
        """
        GIVEN: A custom MigrationFormat value (simulated via patching)
        WHEN: register_format() is called and then save/load is used
        THEN: The custom handlers are invoked correctly
        """
        # GIVEN – use JSON_LINES as a proxy to register a second "custom" handler
        save_calls = []
        load_calls = []

        def _save(graph, filepath):
            save_calls.append(filepath)
            with open(filepath, "w") as f:
                json.dump({"nodes": len(graph.nodes)}, f)

        def _load(filepath):
            load_calls.append(filepath)
            with open(filepath) as f:
                data = json.load(f)
            return GraphData(
                nodes=[NodeData(id=str(i), labels=[], properties={}) for i in range(data["nodes"])]
            )

        # Re-register DAG_JSON with custom handlers just for this test scope
        original_save = _format_registry._save.get(MigrationFormat.DAG_JSON)
        original_load = _format_registry._load.get(MigrationFormat.DAG_JSON)
        try:
            register_format(MigrationFormat.DAG_JSON, _save, _load)

            graph = _make_small_graph(3)
            out = str(tmp_path / "custom.json")
            graph.save_to_file(out, MigrationFormat.DAG_JSON)
            loaded = GraphData.load_from_file(out, MigrationFormat.DAG_JSON)

            assert out in save_calls
            assert out in load_calls
            assert loaded.node_count == 3
        finally:
            # Restore original handlers
            if original_save and original_load:
                register_format(MigrationFormat.DAG_JSON, original_save, original_load)

    def test_unregistered_format_raises_not_implemented(self, tmp_path):
        """
        GIVEN: A MigrationFormat that has been un-registered
        WHEN: save_to_file is called
        THEN: NotImplementedError is raised
        """
        # GIVEN – temporarily remove DAG_JSON handler
        original = _format_registry._save.pop(MigrationFormat.DAG_JSON, None)
        try:
            graph = _make_small_graph(2)
            with pytest.raises(NotImplementedError):
                graph.save_to_file(str(tmp_path / "out.json"), MigrationFormat.DAG_JSON)
        finally:
            if original:
                _format_registry._save[MigrationFormat.DAG_JSON] = original

    def test_car_save_roundtrip(self, tmp_path):
        """
        GIVEN: CAR format is now implemented via libipld + ipld-car
        WHEN: save_to_file is called with CAR format
        THEN: File is created and can be loaded back
        """
        pytest.importorskip("libipld")
        # GIVEN
        graph = _make_small_graph(2)

        # WHEN
        out = str(tmp_path / "out.car")
        graph.save_to_file(out, MigrationFormat.CAR)

        # THEN
        loaded = GraphData.load_from_file(out, MigrationFormat.CAR)
        assert loaded.node_count == graph.node_count

    def test_dag_json_roundtrip_via_registry(self, tmp_path):
        """
        GIVEN: A graph saved via the registry DAG_JSON handler
        WHEN: Loaded back via the registry DAG_JSON handler
        THEN: Node and relationship counts match
        """
        graph = _make_small_graph(6, 5)
        out = str(tmp_path / "graph.json")
        graph.save_to_file(out, MigrationFormat.DAG_JSON)
        loaded = GraphData.load_from_file(out, MigrationFormat.DAG_JSON)
        assert loaded.node_count == 6
        assert loaded.relationship_count == 5

    def test_json_lines_roundtrip_via_registry(self, tmp_path):
        """
        GIVEN: A graph saved via the registry JSON_LINES handler
        WHEN: Loaded back
        THEN: Node and relationship counts match
        """
        graph = _make_small_graph(4, 3)
        out = str(tmp_path / "graph.jsonl")
        graph.save_to_file(out, MigrationFormat.JSON_LINES)
        loaded = GraphData.load_from_file(out, MigrationFormat.JSON_LINES)
        assert loaded.node_count == 4
        assert loaded.relationship_count == 3


# ---------------------------------------------------------------------------
# F2: Streaming export
# ---------------------------------------------------------------------------

class TestStreamingExport:
    """GraphData.export_streaming() must produce correct JSON-Lines output."""

    def test_export_streaming_writes_correct_counts(self, tmp_path):
        """
        GIVEN: A graph with 10 nodes and 9 relationships
        WHEN: export_streaming() is called
        THEN: Returns (10, 9) and file has correct content
        """
        # GIVEN
        graph = _make_small_graph(10, 9)
        out = str(tmp_path / "large.jsonl")

        # WHEN
        nodes_written, rels_written = graph.export_streaming(out)

        # THEN
        assert nodes_written == 10
        assert rels_written == 9
        assert os.path.exists(out)

    def test_export_streaming_roundtrip(self, tmp_path):
        """
        GIVEN: A graph exported via export_streaming()
        WHEN: Loaded back via load_from_file(..., JSON_LINES)
        THEN: Node and relationship data matches the original
        """
        # GIVEN
        graph = _make_small_graph(8, 7)
        out = str(tmp_path / "stream.jsonl")
        graph.export_streaming(out)

        # WHEN
        loaded = GraphData.load_from_file(out, MigrationFormat.JSON_LINES)

        # THEN
        assert loaded.node_count == 8
        assert loaded.relationship_count == 7
        assert loaded.nodes[0].id == "n0"
        assert loaded.nodes[0].properties["name"] == "User0"

    def test_export_streaming_with_schema(self, tmp_path):
        """
        GIVEN: A graph with schema data
        WHEN: export_streaming() is called
        THEN: Schema row is present in the output file
        """
        # GIVEN
        graph = _make_small_graph(3, 2)
        graph.schema = SchemaData(
            node_labels=["Person"],
            relationship_types=["KNOWS"],
        )
        out = str(tmp_path / "with_schema.jsonl")

        # WHEN
        graph.export_streaming(out)

        # THEN
        lines = [json.loads(l) for l in open(out) if l.strip()]
        types = [l["type"] for l in lines]
        assert "schema" in types

    def test_export_streaming_custom_chunk_size(self, tmp_path):
        """
        GIVEN: A graph with 50 nodes
        WHEN: export_streaming() is called with chunk_size=10
        THEN: All 50 nodes are written (chunking is transparent to the output)
        """
        # GIVEN
        graph = _make_small_graph(50, 49)
        out = str(tmp_path / "chunked.jsonl")

        # WHEN
        nodes_written, rels_written = graph.export_streaming(out, chunk_size=10)

        # THEN
        assert nodes_written == 50
        assert rels_written == 49

    def test_iter_nodes_chunked(self):
        """
        GIVEN: A graph with 17 nodes
        WHEN: iter_nodes_chunked(chunk_size=5) is called
        THEN: Yields 4 chunks (5, 5, 5, 2 nodes)
        """
        # GIVEN
        graph = _make_small_graph(17, 0)

        # WHEN
        chunks = list(graph.iter_nodes_chunked(5))

        # THEN
        assert len(chunks) == 4
        assert len(chunks[0]) == 5
        assert len(chunks[-1]) == 2

    def test_iter_relationships_chunked(self):
        """
        GIVEN: A graph with 11 relationships
        WHEN: iter_relationships_chunked(chunk_size=4) is called
        THEN: Yields 3 chunks (4, 4, 3 relationships)
        """
        # GIVEN
        graph = _make_small_graph(12, 11)

        # WHEN
        chunks = list(graph.iter_relationships_chunked(4))

        # THEN
        assert len(chunks) == 3
        assert len(chunks[0]) == 4
        assert len(chunks[-1]) == 3

    def test_export_streaming_empty_graph(self, tmp_path):
        """
        GIVEN: An empty graph
        WHEN: export_streaming() is called
        THEN: Returns (0, 0) and file is created (possibly empty or whitespace only)
        """
        # GIVEN
        graph = GraphData()
        out = str(tmp_path / "empty.jsonl")

        # WHEN
        nodes_written, rels_written = graph.export_streaming(out)

        # THEN
        assert nodes_written == 0
        assert rels_written == 0
        assert os.path.exists(out)
