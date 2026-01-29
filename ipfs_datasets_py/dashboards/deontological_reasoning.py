"""Backwards-compatible shim for dashboard deontological reasoning imports.

Dashboard code historically referenced deontological reasoning via a sibling module.
The implementation lives in :mod:`ipfs_datasets_py.reasoning.deontological_reasoning`.
"""

from ipfs_datasets_py.reasoning.deontological_reasoning import *  # noqa: F401,F403
