"""Backwards-compatible import shim for web archiving utilities.

The implementation lives under :mod:`ipfs_datasets_py.web_archiving.web_archive_utils`.
"""

from ipfs_datasets_py.web_archiving.web_archive_utils import WebArchiveProcessor  # noqa: F401

__all__ = ["WebArchiveProcessor"]
