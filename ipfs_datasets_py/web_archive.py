"""Backwards-compatible import shim for web archiving.

Historically, callers imported :class:`WebArchiveProcessor` from
:mod:`ipfs_datasets_py.web_archive`. The implementation now lives under
:mod:`ipfs_datasets_py.web_archiving.web_archive_utils`.

This shim preserves the old import path.
"""

from ipfs_datasets_py.web_archiving.web_archive_utils import WebArchiveProcessor  # noqa: F401

__all__ = ["WebArchiveProcessor"]
