"""Incremental update utilities for legal dataset tools (thin wrapper).

Business logic lives in
``ipfs_datasets_py.processors.legal_scrapers.incremental_updates_engine``.
"""

from ipfs_datasets_py.processors.legal_scrapers.incremental_updates_engine import (  # noqa: F401
    IncrementalUpdateTracker,
    calculate_update_parameters,
    scrape_recap_incremental,
    scrape_with_incremental_update,
)
