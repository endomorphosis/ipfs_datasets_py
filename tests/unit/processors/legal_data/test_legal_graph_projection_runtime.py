"""Unit tests for shared durable graph projection helpers."""

from __future__ import annotations

from types import SimpleNamespace

import pickle

from ipfs_datasets_py.processors.legal_data.legal_graph_projection_runtime import (
    IsolatedRowMutator,
    group_rows_by_jurisdiction,
    merge_graph_projections,
    merge_local_graph_delta,
    mutating_row_worker,
    neighbors_for_legal_ids,
    same_jurisdiction_candidates,
)


def _mutator(nodes: dict[str, str], edges: list[tuple[str, str]], row: str) -> None:
    nodes[row] = "document"
    edges.append((row, f"date:{row}", "PUBLISHED_ON"))


def test_isolated_row_mutator_is_picklable_and_local() -> None:
    worker = mutating_row_worker(_mutator)
    clone = pickle.loads(pickle.dumps(worker))
    nodes, edges = clone("doc-1")
    assert nodes == {"doc-1": "document"}
    assert edges == [("doc-1", "date:doc-1", "PUBLISHED_ON")]
    assert isinstance(worker, IsolatedRowMutator)


def test_group_rows_by_jurisdiction_sorts_and_partitions() -> None:
    rows = [
        SimpleNamespace(jurisdiction_code="WA", legal_id="wa-1"),
        SimpleNamespace(jurisdiction_code="or", legal_id="or-1"),
        {"jurisdiction_code": "OR", "legal_id": "or-2"},
        SimpleNamespace(jurisdiction_code="WA", legal_id="wa-2"),
    ]
    grouped = group_rows_by_jurisdiction(rows)
    assert list(grouped) == ["OR", "WA"]
    assert [row.legal_id if hasattr(row, "legal_id") else row["legal_id"] for row in grouped["OR"]] == [
        "or-1",
        "or-2",
    ]
    assert [row.legal_id for row in grouped["WA"]] == ["wa-1", "wa-2"]


def test_neighbors_for_legal_ids_drops_cross_state_endpoints() -> None:
    kept = neighbors_for_legal_ids(
        [
            {"source_legal_id": "or-1", "target_legal_id": "or-2"},
            {"source_legal_id": "or-1", "target_legal_id": "wa-1"},
        ],
        {"or-1", "or-2"},
    )
    assert len(kept) == 1
    assert kept[0]["target_legal_id"] == "or-2"


def test_same_jurisdiction_candidates_keeps_only_matching_state() -> None:
    source = SimpleNamespace(jurisdiction_code="OR", filters={"jurisdiction": "OR"})
    by_cid = {
        "in": SimpleNamespace(jurisdiction_code="OR", filters={"jurisdiction": "OR"}),
        "out": SimpleNamespace(jurisdiction_code="WA", filters={"jurisdiction": "WA"}),
    }
    kept = same_jurisdiction_candidates(
        {"in": ["term"], "out": ["term"]},
        source=source,
        by_cid=by_cid,
    )
    assert list(kept) == ["in"]


class _Node:
    def __init__(self, node_key: str, node_cid: str) -> None:
        self.node_key = node_key
        self.node_cid = node_cid


class _Edge:
    def __init__(
        self,
        *,
        source_node_cid: str,
        target_node_cid: str,
        edge_cid: str = "",
        edge_type: str = "cites",
        edge_class: str = "citation",
        payload: dict | None = None,
    ) -> None:
        self.edge_type = edge_type
        self.source_node_cid = source_node_cid
        self.target_node_cid = target_node_cid
        self.edge_class = edge_class
        self.source_span = None
        self.resolution_status = None
        self.weight = None
        self.payload = dict(payload or {})
        self.edge_cid = edge_cid or f"edge:{source_node_cid}->{target_node_cid}"


def test_merge_local_graph_delta_remaps_edges_onto_first_writer_cid() -> None:
    kept = _Node("public_law:pl:us:112:29", "cid-first")
    discarded = _Node("public_law:pl:us:112:29", "cid-second")
    source = _Node("section:or", "cid-src")
    nodes = {"section:or": source, kept.node_key: kept}
    edges: dict[str, _Edge] = {}
    dangling = _Edge(source_node_cid="cid-src", target_node_cid="cid-second")
    merge_local_graph_delta(
        {discarded.node_key: discarded},
        [dangling],
        nodes,
        edges,
    )
    assert nodes[kept.node_key] is kept
    assert list(edges) == ["edge:cid-src->cid-first"]
    assert edges["edge:cid-src->cid-first"].target_node_cid == "cid-first"


def test_merge_graph_projections_remaps_cross_partition_first_writer_cids() -> None:
    kept = _Node("public_law:pl:us:112:29", "cid-first")
    discarded = _Node("public_law:pl:us:112:29", "cid-second")
    or_src = _Node("section:or", "cid-or")
    wa_src = _Node("section:wa", "cid-wa")
    first = SimpleNamespace(
        nodes=(or_src, kept),
        edges=(_Edge(source_node_cid="cid-or", target_node_cid="cid-first"),),
    )
    second = SimpleNamespace(
        nodes=(wa_src, discarded),
        edges=(_Edge(source_node_cid="cid-wa", target_node_cid="cid-second"),),
    )

    def factory(*, nodes, edges, skipped_row_count=0):
        return SimpleNamespace(
            nodes=nodes, edges=edges, skipped_row_count=skipped_row_count
        )

    merged = merge_graph_projections((first, second), factory=factory)
    by_key = {node.node_key: node.node_cid for node in merged.nodes}
    assert by_key["public_law:pl:us:112:29"] == "cid-first"
    assert {edge.target_node_cid for edge in merged.edges} == {"cid-first"}
    assert {edge.source_node_cid for edge in merged.edges} == {"cid-or", "cid-wa"}
