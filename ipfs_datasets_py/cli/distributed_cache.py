"""Backwards-compatible import shim for CLI distributed cache.

The distributed cache implementation lives in :mod:`ipfs_datasets_py.caching.distributed_cache`.
Historically it was imported from :mod:`ipfs_datasets_py.cli.distributed_cache`.
"""

from ipfs_datasets_py.caching.distributed_cache import *  # noqa: F401,F403
