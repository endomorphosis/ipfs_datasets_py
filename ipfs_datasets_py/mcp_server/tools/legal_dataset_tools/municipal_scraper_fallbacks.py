#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Municipal Code Scraper Fallback Methods (thin wrapper).

Business logic lives in
``ipfs_datasets_py.processors.legal_scrapers.municipal_scraper_engine``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ipfs_datasets_py.processors.legal_scrapers.municipal_scraper_engine import (  # noqa: F401
    MunicipalScraperFallbacks,
    scrape_with_fallbacks,
)

# Backward-compatible module-level instance
fallback_scraper = MunicipalScraperFallbacks()
