"""Deprecated package location.

Use :mod:`ipfs_datasets_py.processors.legal_scrapers.bluebook_citation_validator`
instead.  This shim re-exports the public API for backwards compatibility and
will be removed in a future release.
"""

import warnings

warnings.warn(
    "ipfs_datasets_py.mcp_server.tools.lizardperson_argparse_programs"
    ".municipal_bluebook_citation_validator is deprecated. "
    "Use ipfs_datasets_py.processors.legal_scrapers.bluebook_citation_validator instead.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.processors.legal_scrapers.bluebook_citation_validator import *  # noqa: F401, F403
from ipfs_datasets_py.processors.legal_scrapers.bluebook_citation_validator import __all__  # noqa: F401
