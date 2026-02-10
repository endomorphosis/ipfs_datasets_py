"""Legacy shim for DAG-PB helpers.

Deprecated import path:
    `ipfs_datasets_py.ipld.dag_pb`

Canonical import path:
    `ipfs_datasets_py.data_transformation.ipld.dag_pb`
"""

from __future__ import annotations

import warnings


warnings.warn(
    "ipfs_datasets_py.ipld.dag_pb is deprecated; use ipfs_datasets_py.data_transformation.ipld.dag_pb instead.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.data_transformation.ipld.dag_pb import *  # noqa: F403

__all__ = [name for name in globals().keys() if not name.startswith("_")]
