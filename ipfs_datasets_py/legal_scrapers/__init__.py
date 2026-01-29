"""
Legal Scrapers Module

Core implementations for scraping legal datasets from various sources including:
- Federal Register
- US Code
- State Laws
- Municipal Laws
- RECAP Archive (court documents)

This module provides the core scraping logic that can be used by:
- CLI tools (ipfs-datasets)
- MCP server tools
- Direct Python imports
"""

# Import main scraper modules for easy access
from ipfs_datasets_py.legal_scrapers import (
    federal_register_scraper,
    us_code_scraper,
    state_laws_scraper,
    municipal_laws_scraper,
    recap_archive_scraper,
)

# Import utility modules
from ipfs_datasets_py.legal_scrapers import (
    citation_extraction,
    export_utils,
    ipfs_storage_integration,
)

__all__ = [
    "federal_register_scraper",
    "us_code_scraper",
    "state_laws_scraper",
    "municipal_laws_scraper",
    "recap_archive_scraper",
    "citation_extraction",
    "export_utils",
    "ipfs_storage_integration",
]
