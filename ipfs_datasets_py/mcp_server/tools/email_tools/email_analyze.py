"""Email analysis — thin MCP shim.

Business logic lives in
:mod:`ipfs_datasets_py.processors.multimedia.email_analyze_engine`.
"""
from ipfs_datasets_py.processors.multimedia.email_analyze_engine import (  # noqa: F401
    email_analyze_export,
    email_search_export,
)
