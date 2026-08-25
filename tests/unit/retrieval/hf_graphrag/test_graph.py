"""Unit tests for shared graph and bounded adjacency layouts (USCIR-022).

Acceptance:

* No page exceeds 4,096 pointers.
* Forward/inverse adjacency fully reconcile.
* Key ranges are non-overlapping/complete.
* Dangling/duplicate durable edges fail.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ipfs_datasets_py.retrieval.hf_graphrag.schema import (
    MAX_ADJACENCY_POINTERS_PER_ROW,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    PhysicalBoundError,
    canonical_json_dumps,
    content_sha256,
)
from ipfs_datasets_py.retrieval.hf_graphrag.graph import (
    ADJACENCY_SORTED_BY,
    EDGES_SORTED_BY,
    GOAL_ID,
    GRAPH_FIXTURE_SCHEMA_VERSION,
    MAX_ADJACENCY_POINTERS_PER_SHARD,
    NODES_SORTED_BY,
    TASK_ID,
    GraphAdjacencyError,
    GraphEdge,
    GraphInputError,
    GraphIntegrityError,
    GraphNode,
    GraphOrderingError,
    GraphRangeError,
    adjacency_order_key,
    build_adjacency_pages,
    build_fixture_graph_rows,
    build_graph_adjacency_fixture_payload,
    build_graph_layout,
    coerce_graph_edges,
    coerce_graph_nodes,
    default_graph_adjacency_fixture_path,
    graph_bounds_policy,
    graph_part_relative_path,
    layout_from_fixture,
    load_graph_adjacency_fixture,
    normalize_direction,
    reconcile_forward_inverse_adjacency,
    validate_graph_layout,
    write_graph_layout,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "hf_graphrag"
    / "graph_adjacency.json"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sample_nodes() -> list[dict[str, object]]:
    return [
        {"node_cid": "node-a", "node_type": "SECTION", "label": "A"},
        {"node_cid": "node-b", "node_type": "SECTION", "label": "B"},
        {"node_cid": "node-c", "node_type": "SECTION", "label": "C"},
        {"node_cid": "node-d", "node_type": "NOTE", "label": "D"},
        {"node_cid": "node-e", "node_type": "SECTION", "label": "E"},
    ]


def _sample_edges() -> list[dict[str, object]]:
    return [
        {
            "edge_cid": "edge-a-b",
            "edge_type": "CONTAINS",
            "score": 0.9,
            "source_node_cid": "node-a",
            "target_node_cid": "node-b",
        },
        {
            "edge_cid": "edge-a-c",
            "edge_type": "CONTAINS",
            "score": 0.8,
            "source_node_cid": "node-a",
            "target_node_cid": "node-c",
        },
        {
            "edge_cid": "edge-a-d",
            "edge_type": "CITES",
            "score": 0.7,
            "source_node_cid": "node-a",
            "target_node_cid": "node-d",
        },
        {
            "edge_cid": "edge-b-c",
            "edge_type": "CITES",
            "score": 0.5,
            "source_node_cid": "node-b",
            "target_node_cid": "node-c",
        },
        {
            "edge_cid": "edge-c-d",
            "edge_type": "RELATED_TO",
            "score": None,
            "source_node_cid": "node-c",
            "target_node_cid": "node-d",
        },
        {
            "edge_cid": "edge-d-a",
            "edge_type": "DERIVED_FROM",
            "score": 0.1,
            "source_node_cid": "node-d",
            "target_node_cid": "node-a",
        },
    ]


# ---------------------------------------------------------------------------
# Constants / bounds
# ---------------------------------------------------------------------------


def test_graph_bounds_match_release_policy():
    bounds = graph_bounds_policy()
    assert bounds["max_rows_per_physical_shard"] == 4096
    assert bounds["max_adjacency_pointers_per_row"] == 4096
    assert bounds["max_adjacency_pointers_per_shard"] == 8192
    assert MAX_ROWS_PER_PHYSICAL_SHARD == 4096
    assert MAX_ADJACENCY_POINTERS_PER_ROW == 4096
    assert MAX_ADJACENCY_POINTERS_PER_SHARD == 8192
    assert NODES_SORTED_BY == "node_cid_asc"
    assert EDGES_SORTED_BY == "edge_cid_asc"
    assert "score_desc" in ADJACENCY_SORTED_BY
    assert TASK_ID == "USCIR-022"
    assert GOAL_ID == "USCIR-G060"


def test_part_path_contract():
    assert (
        graph_part_relative_path("data/graph/nodes", 0)
        == "data/graph/nodes/part-000000.parquet"
    )
    assert (
        graph_part_relative_path("data/graph/adjacency/out", 3)
        == "data/graph/adjacency/out/part-000003.parquet"
    )
    assert normalize_direction("outgoing") == "out"
    assert normalize_direction("incoming") == "in"


# ---------------------------------------------------------------------------
# Input validation / integrity
# ---------------------------------------------------------------------------


def test_rejects_empty_nodes_and_malformed_records():
    with pytest.raises(GraphInputError):
        build_graph_layout([])

    with pytest.raises(GraphInputError):
        coerce_graph_nodes([{"node_type": "SECTION"}])

    with pytest.raises(GraphInputError):
        coerce_graph_edges(
            [
                {
                    "edge_cid": "e1",
                    "edge_type": "CITES",
                    "source_node_cid": "a",
                    # missing target
                }
            ]
        )


def test_rejects_duplicate_and_dangling_durable_edges():
    nodes = _sample_nodes()
    edges = _sample_edges()

    with pytest.raises(GraphIntegrityError, match="duplicate durable edge_cid"):
        build_graph_layout(
            nodes,
            edges
            + [
                {
                    "edge_cid": "edge-a-b",
                    "edge_type": "CITES",
                    "source_node_cid": "node-a",
                    "target_node_cid": "node-c",
                }
            ],
        )

    with pytest.raises(GraphIntegrityError, match="duplicate durable node_cid"):
        build_graph_layout(
            nodes + [{"node_cid": "node-a", "node_type": "SECTION"}],
            edges,
        )

    with pytest.raises(GraphIntegrityError, match="dangling edge"):
        build_graph_layout(
            nodes,
            edges
            + [
                {
                    "edge_cid": "edge-missing",
                    "edge_type": "CITES",
                    "source_node_cid": "node-a",
                    "target_node_cid": "node-missing",
                }
            ],
        )

    with pytest.raises(GraphIntegrityError, match="dangling edge"):
        build_graph_layout(
            nodes,
            [
                {
                    "edge_cid": "edge-missing-source",
                    "edge_type": "CITES",
                    "source_node_cid": "node-missing",
                    "target_node_cid": "node-a",
                }
            ],
        )


def test_rejects_bounds_above_sealed_maximums():
    nodes = _sample_nodes()
    edges = _sample_edges()
    with pytest.raises(PhysicalBoundError):
        build_graph_layout(
            nodes,
            edges,
            max_rows_per_shard=MAX_ROWS_PER_PHYSICAL_SHARD + 1,
        )
    with pytest.raises(PhysicalBoundError):
        build_graph_layout(
            nodes,
            edges,
            max_pointers_per_page=MAX_ADJACENCY_POINTERS_PER_ROW + 1,
        )


# ---------------------------------------------------------------------------
# Layout: sorting, paging, ranges, reconciliation
# ---------------------------------------------------------------------------


def test_nodes_and_edges_sorted_deterministically():
    nodes = list(reversed(_sample_nodes()))
    edges = list(reversed(_sample_edges()))
    layout = build_graph_layout(
        nodes,
        edges,
        max_rows_per_shard=2,
        max_pointers_per_page=2,
        max_pointers_per_shard=4,
    )
    assert list(layout.all_node_cids()) == sorted(n["node_cid"] for n in nodes)
    assert list(layout.all_edge_cids()) == sorted(e["edge_cid"] for e in edges)
    # Input permutation must not change the layout.
    again = build_graph_layout(
        _sample_nodes(),
        _sample_edges(),
        max_rows_per_shard=2,
        max_pointers_per_page=2,
        max_pointers_per_shard=4,
    )
    assert layout.to_dict() == again.to_dict()


def test_no_page_exceeds_pointer_bound_and_high_degree_is_paged():
    nodes = _sample_nodes()
    edges = _sample_edges()
    layout = build_graph_layout(
        nodes,
        edges,
        max_rows_per_shard=2,
        max_pointers_per_page=2,
        max_pointers_per_shard=4,
    )
    # node-a has 3 outgoing edges -> at least 2 pages under max_pointers=2.
    out_a = [
        page
        for page in layout.out_adjacency_pages
        if page.node_cid == "node-a"
    ]
    assert len(out_a) == 2
    assert out_a[0].page_index == 0
    assert out_a[1].page_index == 1
    assert out_a[0].page_count == 2
    assert out_a[0].neighbor_count == 2
    assert out_a[1].neighbor_count == 1
    assert out_a[0].total_neighbor_count == 3
    for page in (*layout.out_adjacency_pages, *layout.in_adjacency_pages):
        assert 1 <= page.neighbor_count <= 2
        assert page.neighbor_count <= MAX_ADJACENCY_POINTERS_PER_ROW
        assert page.neighbor_count <= layout.max_pointers_per_page

    # Production sealed bound is 4096 even when test bounds are smaller.
    assert MAX_ADJACENCY_POINTERS_PER_ROW == 4096


def test_adjacency_score_priority_order_with_nulls_last():
    nodes = [
        {"node_cid": "n1", "node_type": "SECTION"},
        {"node_cid": "n2", "node_type": "SECTION"},
        {"node_cid": "n3", "node_type": "SECTION"},
        {"node_cid": "n4", "node_type": "SECTION"},
    ]
    edges = [
        {
            "edge_cid": "e-null",
            "edge_type": "CITES",
            "score": None,
            "source_node_cid": "n1",
            "target_node_cid": "n2",
        },
        {
            "edge_cid": "e-high",
            "edge_type": "CITES",
            "score": 0.9,
            "source_node_cid": "n1",
            "target_node_cid": "n3",
        },
        {
            "edge_cid": "e-mid",
            "edge_type": "CITES",
            "score": 0.5,
            "source_node_cid": "n1",
            "target_node_cid": "n4",
        },
    ]
    layout = build_graph_layout(nodes, edges, max_pointers_per_page=4)
    page = layout.out_adjacency_pages[0]
    assert list(page.edge_cids) == ["e-high", "e-mid", "e-null"]
    assert page.scores[0] == 0.9
    assert page.scores[1] == 0.5
    assert page.scores[2] is None

    # Explicit order key: nulls last, then score desc.
    keys = [
        adjacency_order_key(
            score=score,
            edge_type="CITES",
            neighbor_cid=neighbor,
            edge_cid=edge_cid,
        )
        for score, neighbor, edge_cid in (
            (0.9, "n3", "e-high"),
            (0.5, "n4", "e-mid"),
            (None, "n2", "e-null"),
        )
    ]
    assert keys == sorted(keys)


def test_forward_inverse_adjacency_fully_reconcile():
    layout = build_graph_layout(
        _sample_nodes(),
        _sample_edges(),
        max_rows_per_shard=2,
        max_pointers_per_page=2,
        max_pointers_per_shard=4,
    )
    reconcile_forward_inverse_adjacency(layout)
    validate_graph_layout(layout)

    out_edges = {
        edge_cid
        for page in layout.out_adjacency_pages
        for edge_cid in page.edge_cids
    }
    in_edges = {
        edge_cid
        for page in layout.in_adjacency_pages
        for edge_cid in page.edge_cids
    }
    expected = set(layout.all_edge_cids())
    assert out_edges == expected
    assert in_edges == expected
    assert layout.manifest_config()["out_adjacency_edge_count"] == layout.edge_count
    assert layout.manifest_config()["in_adjacency_edge_count"] == layout.edge_count

    # Endpoint directionality.
    for edge in layout.edges:
        out_page = next(
            page
            for page in layout.out_adjacency_pages
            if edge.edge_cid in page.edge_cids
        )
        idx = list(out_page.edge_cids).index(edge.edge_cid)
        assert out_page.node_cid == edge.source_node_cid
        assert out_page.neighbor_cids[idx] == edge.target_node_cid
        in_page = next(
            page
            for page in layout.in_adjacency_pages
            if edge.edge_cid in page.edge_cids
        )
        idx = list(in_page.edge_cids).index(edge.edge_cid)
        assert in_page.node_cid == edge.target_node_cid
        assert in_page.neighbor_cids[idx] == edge.source_node_cid


def test_node_and_edge_key_ranges_are_non_overlapping_and_complete():
    layout = build_graph_layout(
        _sample_nodes(),
        _sample_edges(),
        max_rows_per_shard=2,
        max_pointers_per_page=2,
        max_pointers_per_shard=4,
    )
    # Nodes: 5 nodes / 2 per shard => 3 shards, non-overlapping complete.
    assert len(layout.node_shards) == 3
    covered_nodes: list[str] = []
    previous_last: str | None = None
    for shard in layout.node_shards:
        assert shard.row_count <= 2
        assert shard.first_key <= shard.last_key
        if previous_last is not None:
            assert previous_last < shard.first_key
        for row in shard.rows:
            covered_nodes.append(str(row["node_cid"]))
        previous_last = shard.last_key
    assert covered_nodes == list(layout.all_node_cids())

    covered_edges: list[str] = []
    previous_last = None
    for shard in layout.edge_shards:
        assert shard.row_count <= 2
        if previous_last is not None:
            assert previous_last < shard.first_key
        for row in shard.rows:
            covered_edges.append(str(row["edge_cid"]))
        previous_last = shard.last_key
    assert covered_edges == list(layout.all_edge_cids())

    # Adjacency shards stay within pointer/row bounds and cover all pages.
    for direction in ("out", "in"):
        shards = layout.adjacency_shards(direction)
        pages = layout.adjacency_pages(direction)
        assert sum(shard.row_count for shard in shards) == len(pages)
        assert sum(shard.pointer_count for shard in shards) == sum(
            page.neighbor_count for page in pages
        )
        for shard in shards:
            assert shard.row_count <= layout.max_rows_per_shard
            assert shard.pointer_count <= layout.max_pointers_per_shard
            assert shard.pointer_count <= MAX_ADJACENCY_POINTERS_PER_SHARD


def test_validate_detects_broken_adjacency_order():
    layout = build_graph_layout(
        _sample_nodes(),
        _sample_edges(),
        max_rows_per_shard=4,
        max_pointers_per_page=4,
        max_pointers_per_shard=8,
    )
    page = layout.out_adjacency_pages[0]
    if page.neighbor_count < 2:
        pytest.skip("need multi-pointer page to reverse order")
    from ipfs_datasets_py.retrieval.hf_graphrag.graph import (
        AdjacencyPage,
        GraphLayout,
    )

    reversed_page = AdjacencyPage(
        node_cid=page.node_cid,
        direction=page.direction,
        page_index=page.page_index,
        page_count=page.page_count,
        total_neighbor_count=page.total_neighbor_count,
        edge_cids=tuple(reversed(page.edge_cids)),
        edge_types=tuple(reversed(page.edge_types)),
        neighbor_cids=tuple(reversed(page.neighbor_cids)),
        neighbor_node_types=tuple(reversed(page.neighbor_node_types)),
        scores=tuple(reversed(page.scores)),
        retrieval_methods=tuple(reversed(page.retrieval_methods)),
    )
    broken = GraphLayout(
        nodes=layout.nodes,
        edges=layout.edges,
        node_shards=layout.node_shards,
        edge_shards=layout.edge_shards,
        out_adjacency_pages=(reversed_page, *layout.out_adjacency_pages[1:]),
        in_adjacency_pages=layout.in_adjacency_pages,
        out_adjacency_shards=layout.out_adjacency_shards,
        in_adjacency_shards=layout.in_adjacency_shards,
        max_rows_per_shard=layout.max_rows_per_shard,
        max_pointers_per_page=layout.max_pointers_per_page,
        max_pointers_per_shard=layout.max_pointers_per_shard,
    )
    with pytest.raises((GraphOrderingError, GraphAdjacencyError)):
        validate_graph_layout(broken)


def test_isolated_nodes_have_no_adjacency_pages():
    layout = build_graph_layout(
        _sample_nodes(),
        _sample_edges(),
        max_rows_per_shard=4,
        max_pointers_per_page=4,
        max_pointers_per_shard=8,
    )
    # node-e is isolated.
    assert "node-e" in layout.all_node_cids()
    assert all(page.node_cid != "node-e" for page in layout.out_adjacency_pages)
    assert all(page.node_cid != "node-e" for page in layout.in_adjacency_pages)


def test_build_adjacency_pages_direct_api():
    nodes = coerce_graph_nodes(_sample_nodes())
    edges = coerce_graph_edges(_sample_edges())
    node_types = {node.node_cid: node.node_type for node in nodes}
    pages = build_adjacency_pages(
        edges,
        direction="out",
        node_types=node_types,
        max_pointers_per_page=2,
    )
    assert pages
    assert all(page.neighbor_count <= 2 for page in pages)
    assert sum(page.neighbor_count for page in pages) == len(edges)


# ---------------------------------------------------------------------------
# Fixture contract
# ---------------------------------------------------------------------------


def test_sealed_fixture_exists_and_matches_rebuild():
    assert FIXTURE_PATH.is_file()
    assert default_graph_adjacency_fixture_path() == FIXTURE_PATH
    payload = load_graph_adjacency_fixture(FIXTURE_PATH)
    assert payload["schema_version"] == GRAPH_FIXTURE_SCHEMA_VERSION
    assert payload["task_id"] == TASK_ID
    assert payload["goal_id"] == GOAL_ID
    assert payload["bounds"]["max_rows_per_physical_shard"] == 4096
    assert payload["bounds"]["max_adjacency_pointers_per_row"] == 4096
    assert payload["bounds"]["max_adjacency_pointers_per_shard"] == 8192

    expected = payload["expected"]
    assert expected["node_count"] == 5
    assert expected["edge_count"] == 6
    assert expected["max_pointers_per_page"] == 2
    assert expected["max_rows_per_shard"] == 2
    assert expected["nodes_sorted_by"] == NODES_SORTED_BY
    assert expected["edges_sorted_by"] == EDGES_SORTED_BY
    assert expected["adjacency_sorted_by"] == ADJACENCY_SORTED_BY

    layout = layout_from_fixture(payload)
    assert layout.node_count == expected["node_count"]
    assert layout.edge_count == expected["edge_count"]
    assert sorted(layout.all_node_cids()) == expected["unique_node_cids"]
    assert sorted(layout.all_edge_cids()) == expected["unique_edge_cids"]
    validate_graph_layout(layout)
    reconcile_forward_inverse_adjacency(layout)

    for page in (*layout.out_adjacency_pages, *layout.in_adjacency_pages):
        assert page.neighbor_count <= expected["max_pointers_per_page"]
    for shard in layout.node_shards:
        assert shard.row_count <= expected["max_rows_per_shard"]
    for shard in layout.edge_shards:
        assert shard.row_count <= expected["max_rows_per_shard"]

    # Recipe rebuild is byte-stable.
    again = layout_from_fixture(payload)
    assert layout.to_dict() == again.to_dict()
    digest = content_sha256(canonical_json_dumps(layout.to_dict()))
    assert digest == content_sha256(canonical_json_dumps(again.to_dict()))

    # Generator payload agrees with on-disk recipe / sealed bounds.
    generated = build_graph_adjacency_fixture_payload(
        include_realized_layout=False
    )
    assert generated["recipe"] == payload["recipe"]
    assert generated["test_bounds"] == payload["test_bounds"]
    assert generated["bounds"] == payload["bounds"]
    assert generated["expected"]["unique_node_cids"] == expected["unique_node_cids"]
    assert generated["expected"]["unique_edge_cids"] == expected["unique_edge_cids"]

    realized_a = build_graph_adjacency_fixture_payload(
        include_realized_layout=True
    )
    realized_b = build_graph_adjacency_fixture_payload(
        include_realized_layout=True
    )
    assert realized_a["expected"]["layout_digest"] == (
        realized_b["expected"]["layout_digest"]
    )
    assert realized_a["expected"]["out_page_summary"] == (
        realized_b["expected"]["out_page_summary"]
    )
    assert realized_a["expected"]["node_count"] == expected["node_count"]
    assert realized_a["expected"]["edge_count"] == expected["edge_count"]
    assert realized_a["expected"]["out_adjacency_page_count"] >= 1
    assert realized_a["expected"]["in_adjacency_page_count"] >= 1


def test_fixture_recipe_builder():
    recipe = {
        "nodes": [
            {"node_cid": "x", "node_type": "SECTION"},
            {"node_cid": "y", "node_type": "NOTE"},
        ],
        "edges": [
            {
                "edge_cid": "e1",
                "edge_type": "CITES",
                "score": 1.0,
                "source": "x",
                "target": "y",
            }
        ],
    }
    nodes, edges = build_fixture_graph_rows(recipe)
    assert nodes[0]["node_cid"] == "x"
    assert edges[0]["source_node_cid"] == "x"
    assert edges[0]["target_node_cid"] == "y"
    layout = build_graph_layout(nodes, edges)
    assert layout.edge_count == 1
    assert layout.node_count == 2


# ---------------------------------------------------------------------------
# Optional on-disk write (pyarrow)
# ---------------------------------------------------------------------------


def test_write_graph_layout_round_trip(tmp_path: Path):
    pytest.importorskip("pyarrow")
    result = write_graph_layout(
        _sample_nodes(),
        _sample_edges(),
        tmp_path,
        max_rows_per_shard=2,
        max_pointers_per_page=2,
        max_pointers_per_shard=4,
    )
    assert result.layout.node_count == 5
    assert result.layout.edge_count == 6
    assert result.data_descriptors
    for descriptor in result.data_descriptors:
        path = tmp_path / descriptor.relative_path
        assert path.is_file()
        assert path.stat().st_size == descriptor.size_bytes
    assert (tmp_path / "indexes" / "graph_node_chunks.parquet").is_file()
    assert (tmp_path / "indexes" / "graph_edge_chunks.parquet").is_file()
    assert (tmp_path / "indexes" / "graph_out_adjacency.parquet").is_file()
    assert (tmp_path / "indexes" / "graph_in_adjacency.parquet").is_file()
    assert result.routing_rows["graph_out_adjacency"]
    assert result.routing_rows["graph_in_adjacency"]


def test_coerce_accepts_typed_records():
    nodes = (
        GraphNode(node_cid="n1", node_type="SECTION"),
        GraphNode(node_cid="n2", node_type="NOTE"),
    )
    edges = (
        GraphEdge(
            edge_cid="e1",
            edge_type="CITES",
            source_node_cid="n1",
            target_node_cid="n2",
            score=0.5,
        ),
    )
    layout = build_graph_layout(nodes, edges)
    assert layout.node_count == 2
    assert layout.edge_count == 1
    validate_graph_layout(layout)
