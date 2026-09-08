"""Shared Hugging Face GraphRAG substrate.

Domain builders import search-engine methods from ``.engine`` (or via
``graphrag_parallel``) and overlay schema-specific columns. This package
``__init__`` stays lazy so BM25/external-sort imports do not load writers.
"""

from .schema import (
    MAX_ADJACENCY_POINTERS_PER_ROW,
    MAX_POINTERS_PER_ROW,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    MAX_ROWS_PER_VECTOR_CENTROID,
    MAX_VECTOR_SHARDS_PER_CENTROID,
    ArtifactFamily,
)

_ENGINE_EXPORTS = {
    "BM25_TERM_NODE",
    "CONTAINS_TERM_EDGE",
    "ENGINE_SCHEMA_VERSION",
    "GRAPHRAG_BYTES_PER_WORKER",
    "PRIMARY_KEY",
    "RANGE_ROUTED_FAMILIES",
    "SIMILARITY_EDGE_TYPES",
    "STANDARD_VIEWER_CONFIGS",
    "CompactIndexWriteResult",
    "GraphragEngineError",
    "RangeRepairResult",
    "RangeRoutingDiagnosis",
    "assign_document_identities",
    "build_contains_term_graph",
    "build_digest_manifest",
    "bundle_query_assets",
    "write_hub_search_pack",
    "convert_json_routing_to_parquet",
    "covering_locator_rows",
    "dataset_card_configs",
    "diagnose_range_routing",
    "edge_establishes_legal_authority",
    "graphrag_process_pool_plan",
    "index_parquet_family",
    "is_cidv1_key",
    "list_family_parquet_files",
    "nest_exploded_postings",
    "pack_range_routed_family",
    "posting_cell_sort_key",
    "remap_sha256_identity_fields",
    "repair_graphrag_range_routing",
    "sha256_key_to_cidv1",
    "retrieval_method_for_edge_type",
    "rewrite_range_routed_family",
    "write_standard_compact_indexes",
    "write_term_sorted_posting_shards",
    "diagnose_release_identities",
    "prepare_hf_graphrag_release",
    "release_needs_sha256_upgrade",
    "upgrade_wrapped_graphrag_release",
}

__all__ = [
    "MAX_ADJACENCY_POINTERS_PER_ROW",
    "MAX_POINTERS_PER_ROW",
    "MAX_ROWS_PER_PHYSICAL_SHARD",
    "MAX_ROWS_PER_VECTOR_CENTROID",
    "MAX_VECTOR_SHARDS_PER_CENTROID",
    "ArtifactFamily",
    *sorted(_ENGINE_EXPORTS),
]


def __getattr__(name: str):
    if name in _ENGINE_EXPORTS:
        from . import engine

        if hasattr(engine, name):
            return getattr(engine, name)
        from . import upgrade

        return getattr(upgrade, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
