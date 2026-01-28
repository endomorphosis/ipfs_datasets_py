"""Backwards-compatible import shim for scraper testing framework.

The implementation lives in :mod:`ipfs_datasets_py.web_archiving.scraper_testing_framework`.
This module preserves the historical import path used by tests and downstream code.
"""

from ipfs_datasets_py.web_archiving.scraper_testing_framework import *  # noqa: F403

# Re-exported names come from the target module.
