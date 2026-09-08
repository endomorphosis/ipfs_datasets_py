"""Public GraphRAG parallelism for corpus builds.

Other GraphRAG consumers should import from this module rather than
copying per-corpus loops. Query-time tokenization and walks stay serial.

Example::

    from ipfs_datasets_py.processors.legal_data.graphrag_parallel import (
        tokenize_process_pool_size,
        tokenize_indexable_batch,
        project_documents_parallel,
        extract_document_graph,
        map_graph_partitions,
        map_neighbor_clusters,
        map_adjacency_directions,
        map_documents_under_pressure,
        IsolatedRowMutator,
    )
"""

from __future__ import annotations

from ipfs_datasets_py.processors.legal_data.host_worker_budget import (
    TOKENIZE_BYTES_PER_WORKER,
    TOKENIZE_WORKERS_ENV,
    TokenizePoolPlan,
    tokenize_process_pool_size,
)
from ipfs_datasets_py.processors.legal_data.legal_graph_projection_runtime import (
    IsolatedRowMutator,
    mutating_row_worker,
    run_projection_pass,
)
from ipfs_datasets_py.processors.legal_data.lexical_neighbor_runtime import (
    map_documents_under_pressure,
)
from ipfs_datasets_py.processors.legal_data.parallel_graph import (
    ADJ_SCHEMA_VERSION,
    bm25_neighbor_group,
    embedding_neighbor_cluster,
    extract_document_graph,
    extract_partition_graph,
    map_adjacency_directions,
    map_bm25_neighbor_groups,
    map_graph_partitions,
    map_neighbor_clusters,
    write_adjacency_direction,
)
from ipfs_datasets_py.processors.legal_data.parallel_tokenize import (
    MIN_PARALLEL_ITEMS,
    chunk_items,
    ordered_process_map,
    project_documents_parallel,
    tokenize_indexable_batch,
)

__all__ = [
    "ADJ_SCHEMA_VERSION",
    "IsolatedRowMutator",
    "MIN_PARALLEL_ITEMS",
    "TOKENIZE_BYTES_PER_WORKER",
    "TOKENIZE_WORKERS_ENV",
    "TokenizePoolPlan",
    "bm25_neighbor_group",
    "chunk_items",
    "embedding_neighbor_cluster",
    "extract_document_graph",
    "extract_partition_graph",
    "map_adjacency_directions",
    "map_bm25_neighbor_groups",
    "map_documents_under_pressure",
    "map_graph_partitions",
    "map_neighbor_clusters",
    "mutating_row_worker",
    "ordered_process_map",
    "project_documents_parallel",
    "run_projection_pass",
    "tokenize_indexable_batch",
    "tokenize_process_pool_size",
    "write_adjacency_direction",
]
