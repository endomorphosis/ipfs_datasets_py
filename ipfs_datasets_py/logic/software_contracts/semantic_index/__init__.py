"""Public API for deterministic incremental semantic indexing.

Importing this package only exposes the facade; it does not create a store,
perform a scan, start a watcher, or load optional persistence backends.
"""

from ipfs_datasets_py.logic.software_contracts.semantic_index.index import (
    IncrementalSemanticIndex,
    calculate_invalidation,
    diff_repository_states,
    explain_impact,
    explain_symbol,
    scan_repository,
    watch_repository,
)

__all__ = [
    "IncrementalSemanticIndex",
    "scan_repository",
    "diff_repository_states",
    "calculate_invalidation",
    "explain_symbol",
    "explain_impact",
    "watch_repository",
]
