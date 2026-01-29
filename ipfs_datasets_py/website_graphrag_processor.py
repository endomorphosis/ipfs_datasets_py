"""Backward-compatible import shim.

The implementation was moved to `ipfs_datasets_py.processors.website_graphrag_processor`.
"""

from ipfs_datasets_py.processors.website_graphrag_processor import (  # noqa: F401
    WebsiteGraphRAGProcessor,
    WebsiteProcessingConfig,
)

__all__ = [
    "WebsiteGraphRAGProcessor",
    "WebsiteProcessingConfig",
]
