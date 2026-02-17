"""Backward-compatible proof_cache exports.

New code should import from `ipfs_datasets_py.logic.integration.caching` or
`ipfs_datasets_py.logic.common.proof_cache`.
"""

from .caching.proof_cache import *  # noqa: F403
