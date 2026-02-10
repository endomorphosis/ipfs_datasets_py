"""Consolidated logic namespace.

This package consolidates the former top-level modules:
- ipfs_datasets_py.logic.integrations
- ipfs_datasets_py.logic.tools
- ipfs_datasets_py.logic.integration

New canonical import paths live under:
- ipfs_datasets_py.logic.integrations
- ipfs_datasets_py.logic.tools
- ipfs_datasets_py.logic.integration

The legacy packages remain as deprecated shims for backward compatibility.
"""

from __future__ import annotations

__all__ = ["integrations", "tools", "integration"]
