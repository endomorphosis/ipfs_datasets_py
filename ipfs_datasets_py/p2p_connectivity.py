"""Backward-compatible import shim for P2P connectivity.

Historically, some callers imported P2P connectivity helpers from
`ipfs_datasets_py.p2p_connectivity`. The implementation now lives in
`ipfs_datasets_py.p2p_networking.p2p_connectivity`.

This module preserves the old import path without duplicating logic.
"""

from __future__ import annotations

from ipfs_datasets_py.p2p_networking.p2p_connectivity import *  # noqa: F403

# Re-export the public API of the new module.
from ipfs_datasets_py.p2p_networking import p2p_connectivity as _impl

__all__ = getattr(_impl, "__all__", [name for name in globals() if not name.startswith("_")])
