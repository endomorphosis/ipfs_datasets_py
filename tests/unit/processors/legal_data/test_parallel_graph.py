"""Determinism for process-pool graph extraction helpers."""

from __future__ import annotations

from ipfs_datasets_py.processors.legal_data.parallel_graph import (
    bm25_neighbor_group,
    extract_document_graph,
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
