"""
IPFS Datasets Python — Optimizers sub-package.

Provides GraphRAG, Logic Theorem, and Agentic optimizer modules.
"""

try:
    from ipfs_datasets_py import __version__
except (ImportError, ModuleNotFoundError, AttributeError):
    __version__ = "unknown"

__all__ = ["__version__"]
