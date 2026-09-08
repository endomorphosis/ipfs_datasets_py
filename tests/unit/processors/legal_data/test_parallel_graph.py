"""Determinism for process-pool graph extraction helpers."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from ipfs_datasets_py.processors.legal_data.parallel_graph import (
    bm25_neighbor_group,
    extract_document_graph,
    map_adjacency_directions,
    remap_graph_edge_file,
    split_adjacency_key_ranges,
    write_adjacency_direction,
)


def test_extract_document_graph_emits_typed_sparse_edges() -> None:
    nodes, edges = extract_document_graph(
        "fr:2024-12345:2024-06-01",
        "The Environmental Protection Agency amends 40 CFR 52.21 and 5 U.S.C. 552. "
        "Docket No. EPA-HQ-OAR-2024-0001. RIN 2060-AV00.",
        "2024-06-01",
    )
    types = {etype for _src, _dst, etype in edges}
    assert "PUBLISHED_ON" in types
    assert "HAS_PROVENANCE" in types
    assert "CITES" in types
    assert nodes["fr:2024-12345:2024-06-01"] == "document"
    from ipfs_datasets_py.processors.legal_data.federal_register_graph import sha256_cid

    cid = sha256_cid({"kind": "federal_register_graph_node", "node_key": "fr:x"})
    assert cid.startswith("bafkrei")
    assert any(key.startswith("citation:cfr:40:") for key in nodes)
    assert any(etype == "HAS_DOCKET" for _s, _d, etype in edges)


def test_bm25_neighbor_group_links_shared_terms() -> None:
    rec = bm25_neighbor_group(
        {
            "cid": 0,
            "legal_ids": ["a", "b", "c"],
            "texts": [
                "clean air act section one hundred eleven",
                "clean air act section one hundred eleven implementation plan",
                "unrelated fishing quota harvest specification",
            ],
            "neighbor_k": 1,
        }
    )
    pairs = set(zip(rec["src"], rec["dst"]))
    assert ("a", "b") in pairs or ("b", "a") in pairs
    assert rec["n"] == 3


def _tiny_graph(tmp: Path) -> tuple[Path, Path]:
    nodes = tmp / "nodes"
    edges = tmp / "edges"
    nodes.mkdir()
    edges.mkdir()
    pq.write_table(
        pa.table(
            {
                "node_id": ["a", "b", "c", "d"],
                "node_type": ["document", "document", "document", "citation_cfr"],
            }
        ),
        nodes / "part-000000.parquet",
    )
    pq.write_table(
        pa.table(
            {
                "src": ["a", "a", "b", "c"],
                "dst": ["d", "b", "d", "d"],
                "type": ["CITES", "EMBEDDING_NEIGHBOR_OF", "CITES", "BM25_NEIGHBOR_OF"],
            }
        ),
        edges / "part-000000.parquet",
    )
    return nodes, edges


def test_split_adjacency_key_ranges_are_contiguous() -> None:
    ranges = split_adjacency_key_ranges(["d", "a", "c", "b"], 2)
    assert ranges == [("a", "c"), ("c", None)]
    assert split_adjacency_key_ranges(["a"], 8) == [(None, None)]


def test_write_adjacency_direction_respects_key_range(tmp_path: Path) -> None:
    nodes, edges = _tiny_graph(tmp_path)
    left = tmp_path / "out-left"
    right = tmp_path / "out-right"
    payload = {
        "clear_dest": True,
        "dest": str(left),
        "direction": "outgoing",
        "edge_files": [str(path) for path in sorted(edges.glob("*.parquet"))],
        "key_hi": "c",
        "key_lo": "a",
        "neighbor_col": "dst",
        "node_col": "src",
        "node_files": [str(path) for path in sorted(nodes.glob("*.parquet"))],
        "part_id": 0,
        "shard_rows": 4096,
    }
    rec_left = write_adjacency_direction(payload)
    payload["dest"] = str(right)
    payload["key_lo"] = "c"
    payload["key_hi"] = None
    payload["part_id"] = 1
    rec_right = write_adjacency_direction(payload)
    assert rec_left["pointer_total"] + rec_right["pointer_total"] == 4
    assert rec_left["nodes_with_edges"] == 2
    assert rec_right["nodes_with_edges"] == 1


def test_map_adjacency_directions_shards_with_process_pool(tmp_path: Path) -> None:
    nodes, edges = _tiny_graph(tmp_path)
    outgoing, incoming = map_adjacency_directions(
        edge_files=sorted(edges.glob("*.parquet")),
        node_files=sorted(nodes.glob("*.parquet")),
        outgoing_dest=tmp_path / "outgoing",
        incoming_dest=tmp_path / "incoming",
        workers=2,
    )
    assert outgoing["pointer_total"] == 4
    assert incoming["pointer_total"] == 4
    assert outgoing["shards"] >= 1
    assert incoming["shards"] >= 1
    assert list((tmp_path / "outgoing").glob("*.parquet"))
    assert list((tmp_path / "incoming").glob("*.parquet"))


def test_map_adjacency_directions_uses_requested_single_worker(tmp_path: Path) -> None:
    nodes, edges = _tiny_graph(tmp_path)
    outgoing, incoming = map_adjacency_directions(
        edge_files=sorted(edges.glob("*.parquet")),
        node_files=sorted(nodes.glob("*.parquet")),
        outgoing_dest=tmp_path / "outgoing",
        incoming_dest=tmp_path / "incoming",
        workers=1,
    )
    assert outgoing["pointer_total"] == 4
    assert incoming["pointer_total"] == 4
    assert outgoing["nodes_with_edges"] == 3
    assert incoming["nodes_with_edges"] == 2
    table = pq.read_table(next((tmp_path / "outgoing").glob("*.parquet")))
    methods = {tuple(row) for row in table.column("retrieval_methods").to_pylist()}
    assert ("graph", "embedding") in methods or ("embedding", "graph") in methods
    assert any("bm25" in row for row in table.column("retrieval_methods").to_pylist())


def test_remap_graph_edge_file_writes_cidv1(tmp_path: Path) -> None:
    src = tmp_path / "edges.parquet"
    dest = tmp_path / "edges_cid.parquet"
    pq.write_table(
        pa.table({"src": ["a"], "dst": ["b"], "type": ["CITES"]}),
        src,
    )
    rec = remap_graph_edge_file(
        {
            "path": str(src),
            "dest": str(dest),
            "key_to_cid": {"a": "bafkreiabc", "b": "bafkreidef"},
        }
    )
    assert rec["kept"] == 1
    assert rec["missing"] == 0
    table = pq.read_table(dest)
    assert table.column("src")[0].as_py() == "bafkreiabc"
    assert table.column("dst")[0].as_py() == "bafkreidef"
    assert str(table.column("edge_cid")[0].as_py()).startswith("bafkrei")
