"""Backwards-compatible import shim for IPFS multiformats helpers.

The canonical implementation lives in
:mod:`ipfs_datasets_py.data_transformation.ipfs_formats.ipfs_multiformats`.

This module preserves the historical import path used by tests and downstream code.
"""

from ipfs_datasets_py.data_transformation.ipfs_formats.ipfs_multiformats import *  # noqa: F403

# Re-exported names come from the target module.
