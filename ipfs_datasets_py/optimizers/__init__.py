"""
IPFS Datasets Python — Optimizers sub-package.

Provides GraphRAG, Logic Theorem, and Agentic optimizer modules.
"""

try:
    from ipfs_datasets_py import __version__  # type: ignore[import]
except Exception:
    __version__ = "unknown"

__all__ = ["__version__"]
