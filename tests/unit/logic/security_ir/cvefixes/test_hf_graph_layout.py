"""Conformance tests for the CVEfixes Hugging Face graph layout."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import io

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.ir_core.identity import (
    canonical_identity,
    cid_v1_from_digest,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.graph import (
    CVEfixesGraph,
    GraphConfig,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.hf_graph_layout import (
    CVEFIXES_HF_GRAPH_ADJACENCY_SCHEMA_VERSION,
    CVEFIXES_HF_SHARD_META_SCHEMA_VERSION,
    GRAPH_HF_CONFIG_PATHS,
    HuggingFaceGraphArtifact,
    HuggingFaceGraphLayoutConfig,
    HuggingFaceGraphLayoutIntegrityError,
    _validate_adjacency_rows,
    build_cvefixes_hf_graph_layout,
    validate_cvefixes_hf_graph_layout,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.schemas import (
    GraphEdge,
    GraphNode,
)


def _cid(label: str) -> str:
    return canonical_identity(
        {"label": label}, domain="test", schema_version="test/v1"
    ).cid


def _graph(*, with_edges: bool = True) -> CVEfixesGraph:
    source_cid = _cid("source")
    projection_cid = _cid("projection")
    config_cid = GraphConfig().cid

    def node(node_type: str, label: str, **payload: object) -> GraphNode:
        return GraphNode(
            source_cids=(source_cid,),
            parent_cids=(projection_cid,),
            config_cid=config_cid,
            node_type=node_type,
            payload={
                "grants_execution_authority": False,
                "retrieval_only": True,
                label: str(payload.pop(label, label)),
                **payload,
            },
        )

    source = node("source", "source_cid", source_cid=source_cid)
    if not with_edges:
        return CVEfixesGraph(
            nodes=(source,),
            edges=(),
            source_cids=(source_cid,),
            projection_cids=(projection_cid,),
            config_cid=config_cid,
        )

    cve = node("cve", "cve_id", cve_id="CVE-2026-0042")
    repository = node(
        "repository",
        "repository",
        repository="https://github.com/example/project",
    )
    commit = node("commit", "commit_hash", commit_hash="a" * 40)
    isolated = node("language", "language", language="python")

    def edge(
        edge_type: str,
        source_node: GraphNode,
        target_node: GraphNode,
    ) -> GraphEdge:
        return GraphEdge(
            source_cids=(source_cid,),
            parent_cids=(source_node.cid, target_node.cid),
            config_cid=config_cid,
            edge_type=edge_type,
            source_node_cid=source_node.cid,
            target_node_cid=target_node.cid,
            payload={
                "authoritative": False,
                "edge_class": "structural",
                "grants_execution_authority": False,
                "retrieval_only": True,
            },
        )

    edges = (
        edge("DESCRIBES", source, cve),
        edge("AFFECTS", cve, repository),
        edge("FIXED_BY", cve, commit),
        edge("CONTAINS", repository, commit),
    )
    return CVEfixesGraph(
        nodes=(isolated, commit, repository, cve, source),
        edges=tuple(reversed(edges)),
        source_cids=(source_cid,),
        projection_cids=(projection_cid,),
        config_cid=config_cid,
    )


def _config() -> HuggingFaceGraphLayoutConfig:
    return HuggingFaceGraphLayoutConfig(
        max_rows_per_shard=2,
        max_shards_per_config=32,
        max_shard_bytes=1_000_000,
        row_group_size=1,
        adjacency_pointers_per_row=1,
        adjacency_pointers_per_shard=2,
    )


def _rows(layout, config_name: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for artifact in layout.artifacts:
        if artifact.config_name == config_name:
            rows.extend(
                pq.read_table(io.BytesIO(artifact.content)).to_pylist()
            )
    return rows


class _CountingEdgeRows(dict[str, dict[str, object]]):
    def __init__(self, rows: list[dict[str, object]]) -> None:
        super().__init__((str(row["edge_cid"]), row) for row in rows)
        self.values_calls = 0

    def values(self):
        self.values_calls += 1
        return super().values()


def test_adjacency_validation_indexes_edges_once_per_direction() -> None:
    graph = _graph()
    config = _config()
    layout = build_cvefixes_hf_graph_layout(graph, config=config)
    node_rows = _rows(layout, "graph_nodes")
    edge_rows = _CountingEdgeRows(_rows(layout, "graph_edges"))

    _validate_adjacency_rows(
        _rows(layout, "graph_outgoing_adjacency"),
        direction="outgoing",
        node_types={
            str(row["node_cid"]): str(row["node_type"])
            for row in node_rows
        },
        edge_ids=set(edge_rows),
        edge_rows=edge_rows,
        config=config,
    )

    assert edge_rows.values_calls == 1


def _rewrite_parquet(
    rows: list[dict[str, object]],
    *,
    schema: pa.Schema,
) -> bytes:
    output = io.BytesIO()
    pq.write_table(
        pa.Table.from_pylist(rows, schema=schema),
        output,
        compression="zstd",
        compression_level=6,
        data_page_version="1.0",
        row_group_size=1,
        use_dictionary=True,
        version="2.6",
        write_statistics=True,
    )
    return output.getvalue()


def test_layout_matches_skillcenter_paths_and_meta_pointer_contract() -> None:
    graph = _graph()
    layout = build_cvefixes_hf_graph_layout(graph, config=_config())
    validation = validate_cvefixes_hf_graph_layout(layout, graph=graph)

    assert validation.valid
    assert validation.node_count == len(graph.nodes)
    assert validation.edge_count == len(graph.edges)
    assert {item.config_name for item in layout.artifacts} == set(
        GRAPH_HF_CONFIG_PATHS
    )
    assert {item.path for item in layout.index_artifacts} == {
        "indexes/graph_edge_chunks.parquet",
        "indexes/graph_incoming_adjacency.parquet",
        "indexes/graph_node_chunks.parquet",
        "indexes/graph_outgoing_adjacency.parquet",
    }

    covered: set[str] = set()
    for index in layout.index_artifacts:
        table = pq.read_table(io.BytesIO(index.content))
        metadata = table.schema.metadata or {}
        assert (
            metadata[b"schema_version"].decode()
            == CVEFIXES_HF_SHARD_META_SCHEMA_VERSION
        )
        expected_columns = [
            "cid",
            "end_document_index",
            "first_key",
            "kind",
            "last_key",
            "relative_path",
            "row_count",
            "schema_version",
            "sha256",
            "shard_id",
            "size_bytes",
            "start_document_index",
        ]
        if "adjacency" in index.config_name:
            expected_columns.extend(
                [
                    "adjacency_count",
                    "direction",
                    "first_page_index",
                    "last_page_index",
                    "node_count",
                ]
            )
        assert table.schema.names == expected_columns
        for pointer in table.to_pylist():
            target = layout.artifact(pointer["relative_path"])
            digest = hashlib.sha256(target.content).digest()
            assert pointer["cid"] == cid_v1_from_digest(digest)
            assert pointer["cid"] == target.cid
            assert pointer["sha256"] == digest.hex() == target.sha256
            assert pointer["size_bytes"] == len(target.content)
            assert pointer["row_count"] == target.row_count
            assert pointer["start_document_index"] == -1
            assert pointer["end_document_index"] == -1
            covered.add(pointer["relative_path"])
    assert covered == {item.path for item in layout.data_artifacts}


def test_graph_node_rows_can_bind_the_shared_corpus_entry_cids() -> None:
    graph = _graph()
    entry_cids = {
        node.cid: _cid(f"retrieval-entry-{index}")
        for index, node in enumerate(graph.nodes)
    }

    layout = build_cvefixes_hf_graph_layout(
        graph,
        config=_config(),
        entry_cid_by_node=entry_cids,
    )
    validation = validate_cvefixes_hf_graph_layout(layout, graph=graph)

    assert validation.valid
    assert {
        str(row["node_cid"]): str(row["entry_cid"])
        for row in _rows(layout, "graph_nodes")
    } == entry_cids


def test_adjacency_is_paged_aligned_and_covers_edges_and_isolated_nodes() -> None:
    graph = _graph()
    layout = build_cvefixes_hf_graph_layout(graph, config=_config())
    isolated_cid = next(
        node.cid for node in graph.nodes if node.node_type == "language"
    )

    for direction in ("outgoing", "incoming"):
        rows = _rows(layout, f"graph_{direction}_adjacency")
        assert {row["node_cid"] for row in rows} == {
            node.cid for node in graph.nodes
        }
        assert {
            edge_cid
            for row in rows
            for edge_cid in row["edge_cids"]
        } == {edge.cid for edge in graph.edges}
        assert all(
            row["schema_version"]
            == CVEFIXES_HF_GRAPH_ADJACENCY_SCHEMA_VERSION
            for row in rows
        )
        for row in rows:
            lengths = {
                len(row[column])
                for column in (
                    "edge_cids",
                    "edge_types",
                    "neighbor_cids",
                    "neighbor_node_types",
                    "retrieval_methods",
                    "scores",
                )
            }
            assert lengths == {row["neighbor_count"]}

        isolated_rows = [
            row for row in rows if row["node_cid"] == isolated_cid
        ]
        assert len(isolated_rows) == 1
        assert isolated_rows[0]["neighbor_count"] == 0
        assert isolated_rows[0]["page_count"] == 1
        assert isolated_rows[0]["page_index"] == 0

    cve_cid = next(
        node.cid for node in graph.nodes if node.node_type == "cve"
    )
    cve_outgoing = [
        row
        for row in _rows(layout, "graph_outgoing_adjacency")
        if row["node_cid"] == cve_cid
    ]
    assert [row["page_index"] for row in cve_outgoing] == [0, 1]
    assert {row["page_count"] for row in cve_outgoing} == {2}
    assert {row["total_neighbor_count"] for row in cve_outgoing} == {2}


def test_build_is_byte_deterministic() -> None:
    graph = _graph()
    first = build_cvefixes_hf_graph_layout(graph, config=_config())
    second = build_cvefixes_hf_graph_layout(graph, config=_config())

    assert first.graph_root == second.graph_root
    assert [
        (item.path, item.cid, item.sha256, item.content)
        for item in first.artifacts
    ] == [
        (item.path, item.cid, item.sha256, item.content)
        for item in second.artifacts
    ]


def test_meta_pointer_tampering_fails_closed() -> None:
    graph = _graph()
    layout = build_cvefixes_hf_graph_layout(graph, config=_config())
    target = layout.artifact("indexes/graph_node_chunks.parquet")
    table = pq.read_table(io.BytesIO(target.content))
    rows = table.to_pylist()
    rows[0]["sha256"] = "0" * 64
    tampered = HuggingFaceGraphArtifact(
        path=target.path,
        config_name=target.config_name,
        content=_rewrite_parquet(rows, schema=table.schema),
        row_count=target.row_count,
    )
    modified = replace(
        layout,
        artifacts=tuple(
            tampered if item.path == target.path else item
            for item in layout.artifacts
        ),
    )

    with pytest.raises(
        HuggingFaceGraphLayoutIntegrityError,
        match="meta-index pointer mismatch",
    ):
        validate_cvefixes_hf_graph_layout(modified, graph=graph)


def test_zero_edge_graph_still_has_remote_configs_and_node_adjacency() -> None:
    graph = _graph(with_edges=False)
    layout = build_cvefixes_hf_graph_layout(graph, config=_config())
    validation = validate_cvefixes_hf_graph_layout(layout, graph=graph)

    assert validation.node_count == 1
    assert validation.edge_count == 0
    edge_shards = [
        item
        for item in layout.data_artifacts
        if item.config_name == "graph_edges"
    ]
    assert len(edge_shards) == 1
    assert edge_shards[0].row_count == 0
    for direction in ("outgoing", "incoming"):
        rows = _rows(layout, f"graph_{direction}_adjacency")
        assert len(rows) == 1
        assert rows[0]["neighbor_count"] == 0
