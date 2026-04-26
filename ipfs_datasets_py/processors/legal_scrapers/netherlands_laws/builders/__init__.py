"""Builder entry points for Netherlands laws datasets and indexes."""

from .ipfs_indexes import (
    build_all_indexes,
    build_bm25_index,
    build_knowledge_graph,
    build_vector_index,
)
from .ipfs_package import build_ipfs_cid_package
from .normalized_package import build_normalized_package

__all__ = [
    "build_all_indexes",
    "build_bm25_index",
    "build_ipfs_cid_package",
    "build_knowledge_graph",
    "build_normalized_package",
    "build_vector_index",
]
