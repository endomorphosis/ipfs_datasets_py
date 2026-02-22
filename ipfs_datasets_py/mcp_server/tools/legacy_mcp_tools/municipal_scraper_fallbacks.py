#!/usr/bin/env python

# DEPRECATED: This legacy module is superseded by
#   ipfs_datasets_py.mcp_server.tools.legal_dataset_tools
# See legacy_mcp_tools/MIGRATION_GUIDE.md for migration instructions.
import warnings
warnings.warn(
    "legacy_mcp_tools.municipal_scraper_fallbacks is deprecated. "
    "Use ipfs_datasets_py.mcp_server.tools.legal_dataset_tools instead.",
    DeprecationWarning,
    stacklevel=2,
)

# Business logic lives in the canonical package.
from ipfs_datasets_py.processors.legal_scrapers.municipal_scraper_engine import (  # noqa: F401
    MunicipalScraperFallbacks,
    scrape_with_fallbacks,
)

# Backward-compatible instance
fallback_scraper = MunicipalScraperFallbacks()
