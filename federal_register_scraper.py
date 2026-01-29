"""Compatibility shim for integration tests.

The integration tests import `federal_register_scraper` as a top-level module.
The implementation lives in the MCP legal dataset tools package.
"""

from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.federal_register_scraper import *  # noqa: F401,F403
