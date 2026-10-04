"""State management for resumable scraping operations.

This module is part of the MCP server tool layer and should remain a thin
wrapper. The core implementation lives in
`ipfs_datasets_py.processors.legal_scrapers.scraping_state`.
"""

from ipfs_datasets_py.processors.legal_scrapers.scraping_state import (  # noqa: F401
    ScrapingState,
    delete_scraping_job,
    list_scraping_jobs,
)
