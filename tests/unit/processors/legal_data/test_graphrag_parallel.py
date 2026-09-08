"""Public GraphRAG parallelism surface for other corpus builders."""

from __future__ import annotations

from ipfs_datasets_py.processors.legal_data import (
    IsolatedRowMutator,
    extract_document_graph,
    tokenize_indexable_batch,
    tokenize_process_pool_size,
)
from ipfs_datasets_py.processors.legal_data.graphrag_parallel import __all__ as public_names


def test_public_parallel_names_are_exported() -> None:
    assert "tokenize_process_pool_size" in public_names
    assert "tokenize_indexable_batch" in public_names
    assert "project_documents_parallel" in public_names
    assert "extract_document_graph" in public_names
    assert "map_graph_partitions" in public_names
    assert "map_neighbor_clusters" in public_names
    assert "map_adjacency_directions" in public_names
    assert "IsolatedRowMutator" in public_names
    assert "map_documents_under_pressure" in public_names


def test_lazy_legal_data_exports_resolve() -> None:
    plan = tokenize_process_pool_size(requested=1)
    assert plan.workers == 1
    assert IsolatedRowMutator is not None
    nodes, edges = extract_document_graph("fr:x", "See 40 CFR 52.21.", "2024-01-01")
    assert nodes["fr:x"] == "document"
    assert tokenize_indexable_batch(["hello world"], workers=1)


def test_sparse_graphrag_facades_reexport_parallel_apis() -> None:
    from ipfs_datasets_py.processors.legal_data import (
        open_us_law_sparse_graphrag as oul,
        state_laws_sparse_graphrag as state,
        uscode_sparse_graphrag as uscode,
    )

    names = (
        "tokenize_indexable_batch",
        "tokenize_process_pool_size",
        "project_documents_parallel",
        "extract_document_graph",
        "map_graph_partitions",
        "map_neighbor_clusters",
        "map_adjacency_directions",
        "IsolatedRowMutator",
        "map_documents_under_pressure",
    )
    for api in (uscode, state, oul):
        available = set(api.available_lazy_exports())
        for name in names:
            assert name in available, f"{api.__name__} missing {name}"
        assert api.resolve_export("tokenize_process_pool_size") is tokenize_process_pool_size
        assert api.resolve_export("extract_document_graph") is extract_document_graph
