#!/usr/bin/env python

# DEPRECATED: This legacy module is superseded by
#   ipfs_datasets_py.mcp_server.tools.legal_dataset_tools
# See legacy_mcp_tools/MIGRATION_GUIDE.md for migration instructions.
import warnings
warnings.warn(
    "legacy_mcp_tools.patent_scraper is deprecated. "
    "Use ipfs_datasets_py.mcp_server.tools.legal_dataset_tools instead.",
    DeprecationWarning,
    stacklevel=2,
)

"""
Patent Scraper — thin legacy re-export.

Business logic lives in the canonical package module:
    ipfs_datasets_py.processors.legal_scrapers.patent_engine
"""

from ipfs_datasets_py.processors.legal_scrapers.patent_engine import (  # noqa: F401
    Patent,
    PatentDatasetBuilder,
    PatentSearchCriteria,
    USPTOPatentScraper,
    search_patents_by_assignee,
    search_patents_by_inventor,
    search_patents_by_keyword,
)
