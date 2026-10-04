"""Compatibility shim for HuggingFace upload pipeline.

Tests and some integrations reference this module path under the MCP tools
namespace. The canonical implementation lives in:

    ipfs_datasets_py.processors.legal_scrapers.municipal_law_database_scrapers.hugging_face_pipeline

This module re-exports that implementation when available, and falls back
to the local engine module (``hugging_face_pipeline_engine``) otherwise.
"""

from __future__ import annotations

import warnings

warnings.warn(
    "ipfs_datasets_py.mcp_server.tools.legal_dataset_tools"
    ".municipal_law_database_scrapers.hugging_face_pipeline is deprecated; "
    "import ipfs_datasets_py.processors.legal_scrapers"
    ".municipal_law_database_scrapers.hugging_face_pipeline instead.",
    DeprecationWarning,
    stacklevel=2,
)

# Prefer the canonical implementation.
try:  # pragma: no cover
    from ipfs_datasets_py.processors.legal_scrapers.municipal_law_database_scrapers.hugging_face_pipeline import (  # noqa: F401
        CommitInfo,
        HfApi,
        HfHubHTTPError,
        RateLimiter,
        UploadToHuggingFaceInParallel,
        login,
    )

except (ImportError, ModuleNotFoundError):  # pragma: no cover
    # Canonical location unavailable — use the local engine module.
    from .hugging_face_pipeline_engine import (  # noqa: F401
        CommitInfo,
        HfApi,
        HfHubHTTPError,
        RateLimiter,
        UploadToHuggingFaceInParallel,
        login,
    )

__all__ = [
    "CommitInfo",
    "HfApi",
    "HfHubHTTPError",
    "RateLimiter",
    "UploadToHuggingFaceInParallel",
    "login",
]
