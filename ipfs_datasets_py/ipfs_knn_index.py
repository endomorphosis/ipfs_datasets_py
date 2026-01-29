"""Backwards-compatible import shim for the IPFS KNN index.

The implementation lives in :mod:`ipfs_datasets_py.embeddings.ipfs_knn_index`.
This module preserves the historical import path used by tests and downstream code.
"""

from ipfs_datasets_py.embeddings.ipfs_knn_index import IPFSKnnIndex  # noqa: F401

__all__ = ["IPFSKnnIndex"]
