"""Focused tests for the corpus-scale shared graph physical writer."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import replace
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.retrieval.hf_graphrag.artifacts import (
    ArtifactIntegrityError,
)
from ipfs_datasets_py.retrieval.hf_graphrag.graph import GraphEdge, GraphNode
from ipfs_datasets_py.retrieval.hf_graphrag.schema import ArtifactFamily
from ipfs_datasets_py.retrieval.hf_graphrag.streaming_graph import (
    AUTHORIZES_HUB_UPLOAD,
    AUTHORIZES_PUBLICATION,
    CANONICAL_GRAPH_INDEX_PATHS,
    LEGACY_MATERIALIZED_GRAPH_WRITER_PRODUCTION_READY,
    PERFORMS_NETWORK_IO,
    STREAMING_GRAPH_WRITER_PRODUCTION_READY,
    StreamingGraphConfig,
    StreamingGraphCoverageError,
    StreamingGraphDuplicateError,
    StreamingGraphEndpointError,
    StreamingGraphProofError,
    write_streaming_graph_layout,
)


class OneShot[T](Iterable[T]):
    """Iterable that makes a second source traversal observable."""

    def __init__(self, values: list[T]) -> None:
        self.values = values
        self.iterations = 0

    def __iter__(self) -> Iterator[T]:
        self.iterations += 1
        if self.iterations > 1:
            raise AssertionError("one-shot source was traversed more than once")
        yield from self.values


def _nodes() -> list[GraphNode]:
    return [
        GraphNode("node-e", "SECTION", label="E", entry_cid="entry-e"),
        GraphNode("node-a", "SECTION", label="A", entry_cid="entry-a"),
        GraphNode("node-d", "NOTE", label="D"),
        GraphNode("node-b", "SECTION", label="B", entry_cid="entry-b"),
        GraphNode("node-c", "SECTION", label="C", entry_cid="entry-c"),
    ]


def _edges() -> list[GraphEdge]:
    return [
        GraphEdge("edge-d-a", "DERIVED_FROM", "node-d", "node-a", score=0.1),
        GraphEdge("edge-a-d", "CITES", "node-a", "node-d", score=0.7),
        GraphEdge("edge-a-b", "CONTAINS", "node-a", "node-b", score=0.9),
        GraphEdge("edge-c-d", "RELATED_TO", "node-c", "node-d"),
        GraphEdge("edge-a-c", "CONTAINS", "node-a", "node-c", score=0.8),
        GraphEdge("edge-b-c", "CITES", "node-b", "node-c", score=0.5),
    ]


def _config(*, overwrite: bool = False) -> StreamingGraphConfig:
    return StreamingGraphConfig(
        max_rows_per_shard=2,
        max_pointers_per_page=2,
        max_pointers_per_shard=2,
        max_records_in_memory=2,
        overwrite=overwrite,
    )


def _bm25_proof() -> dict[str, object]:
    return {
        "document_frequency_sha256": "d" * 64,
        "durable_term_document_edge_count": 0,
        "full_term_document_expansion_performed": False,
        "optional_neighbor_edges_production_ready": True,
        "production_ready": True,
        "term_count": 12,
        "term_document_edges_are_virtual": True,
        "vocabulary_sha256": "a" * 64,
    }


def test_streams_one_shot_inputs_into_bounded_query_layout(tmp_path: Path) -> None:
    nodes = OneShot(_nodes())
    edges = OneShot(_edges())
    result = write_streaming_graph_layout(
        nodes,
        edges,
        tmp_path,
        config=_config(),
        bm25_vocabulary_proof=_bm25_proof(),
    )

    assert nodes.iterations == 1
    assert edges.iterations == 1
    assert result.production_ready is True
    assert STREAMING_GRAPH_WRITER_PRODUCTION_READY is True
    assert LEGACY_MATERIALIZED_GRAPH_WRITER_PRODUCTION_READY is False
    assert AUTHORIZES_PUBLICATION is False
    assert AUTHORIZES_HUB_UPLOAD is False
    assert PERFORMS_NETWORK_IO is False
    assert result.counts["nodes"] == 5
    assert result.counts["edges"] == 6
    assert result.counts["verified_endpoints"] == 12
    assert result.counts["outgoing_adjacency_pointers"] == 6
    assert result.counts["incoming_adjacency_pointers"] == 6
    assert result.manifest_fragment()["graph"]["node_count"] == 5
    assert result.manifest_fragment()["graph"]["edge_count"] == 6
    assert result.manifest_fragment()["graph"]["streaming"] is True
    assert (
        result.identity_proofs["edge_cids_sha256"]
        == result.identity_proofs["outgoing_edge_cids_sha256"]
    )
    assert (
        result.identity_proofs["edge_cids_sha256"]
        == result.identity_proofs["incoming_edge_cids_sha256"]
    )
    assert set(result.index_descriptors) == set(CANONICAL_GRAPH_INDEX_PATHS)
    assert {
        name: descriptor.relative_path
        for name, descriptor in result.index_descriptors.items()
    } == dict(CANONICAL_GRAPH_INDEX_PATHS)
    assert all(descriptor.row_count <= 2 for descriptor in result.data_descriptors)
    assert all(
        int(descriptor.metadata.get("pointer_count") or 0) <= 2
        for descriptor in result.data_descriptors
        if descriptor.family
        in {
            ArtifactFamily.GRAPH_ADJACENCY_IN,
            ArtifactFamily.GRAPH_ADJACENCY_OUT,
        }
    )
    assert all(
        receipt["peak_resident_records"] <= receipt["max_records_in_memory"]
        for receipt in result.sort_receipts.values()
    )
    assert "vocabulary" not in result.compact_proofs["bm25_vocabulary"]
    assert (
        result.compact_proofs["bm25_vocabulary"]["term_document_edges_are_virtual"]
        is True
    )
    assert list(result.key_evidence["node_cids"]) == [
        "node-a",
        "node-b",
        "node-c",
        "node-d",
        "node-e",
    ]
    assert list(result.key_evidence["entry_cids"]) == [
        "entry-a",
        "entry-b",
        "entry-c",
        "entry-e",
    ]

    result.verify()

    for direction, family in (
        ("out", ArtifactFamily.GRAPH_ADJACENCY_OUT),
        ("in", ArtifactFamily.GRAPH_ADJACENCY_IN),
    ):
        edge_cids: list[str] = []
        for descriptor in result.data_descriptors:
            if descriptor.family is not family:
                continue
            rows = pq.read_table(tmp_path / descriptor.relative_path).to_pylist()
            assert all(row["direction"] == direction for row in rows)
            assert all(row["neighbor_count"] <= 2 for row in rows)
            edge_cids.extend(edge_cid for row in rows for edge_cid in row["edge_cids"])
        assert sorted(edge_cids) == sorted(edge.edge_cid for edge in _edges())


@pytest.mark.parametrize("kind", ["node", "edge"])
def test_rejects_duplicate_durable_identities(tmp_path: Path, kind: str) -> None:
    nodes = _nodes()
    edges = _edges()
    if kind == "node":
        nodes.append(GraphNode("node-a", "SECTION", label="duplicate"))
    else:
        edges.append(GraphEdge("edge-a-b", "CITES", "node-a", "node-c"))

    with pytest.raises(StreamingGraphDuplicateError, match="duplicate durable"):
        write_streaming_graph_layout(
            iter(nodes),
            iter(edges),
            tmp_path / kind,
            config=_config(),
        )


def test_disk_backed_endpoint_join_rejects_dangling_edge(tmp_path: Path) -> None:
    edges = _edges() + [GraphEdge("edge-missing", "CITES", "node-a", "node-missing")]
    with pytest.raises(StreamingGraphEndpointError, match="missing target node"):
        write_streaming_graph_layout(
            iter(_nodes()),
            iter(edges),
            tmp_path,
            config=_config(),
        )


@pytest.mark.parametrize(
    "expanded",
    [
        {"vocabulary": ["law", "court"]},
        {"postings": [{"term": "law", "entry_cid": "chunk"}]},
        {"durable_term_document_edge_count": 1},
        {"full_term_document_expansion_performed": True},
    ],
)
def test_rejects_expanded_bm25_metadata(
    tmp_path: Path,
    expanded: dict[str, object],
) -> None:
    proof = {**_bm25_proof(), **expanded}
    with pytest.raises(StreamingGraphProofError):
        write_streaming_graph_layout(
            iter(_nodes()),
            iter(_edges()),
            tmp_path,
            config=_config(),
            bm25_vocabulary_proof=proof,
        )


def test_descriptor_reverification_detects_tampering(tmp_path: Path) -> None:
    result = write_streaming_graph_layout(
        iter(_nodes()),
        iter(_edges()),
        tmp_path,
        config=_config(),
    )
    target = tmp_path / result.data_descriptors[0].relative_path
    with target.open("ab") as handle:
        handle.write(b"tampered")

    with pytest.raises(ArtifactIntegrityError, match="size/sha256"):
        result.verify()


def test_equal_counts_cannot_mask_adjacency_identity_drift(tmp_path: Path) -> None:
    result = write_streaming_graph_layout(
        iter(_nodes()),
        iter(_edges()),
        tmp_path,
        config=_config(),
    )
    drifted = replace(
        result,
        identity_proofs={
            **result.identity_proofs,
            "incoming_edge_cids_sha256": "0" * 64,
        },
    )

    assert drifted.counts["incoming_adjacency_pointers"] == drifted.counts["edges"]
    with pytest.raises(StreamingGraphCoverageError, match="identity coverage"):
        drifted.verify()
