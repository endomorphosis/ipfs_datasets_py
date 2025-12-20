#!/usr/bin/env python3
"""
Legal Data Scrapers - Multi-Interface Architecture

This package provides unified legal data scrapers that work as:
1. **Package Import** - Use in Python code
2. **CLI Tool** - Run from command line
3. **MCP Server Tool** - Expose via Model Context Protocol

Usage Examples:

    # 1. Package Import
    from legal_scrapers import UnifiedLegalScraper, CourtListenerScraper
    scraper = UnifiedLegalScraper(enable_ipfs=True)
    result = await scraper.scrape_url("https://library.municode.com/wa/seattle")
    
    # 2. CLI Tool
    $ python -m legal_scrapers.cli.unified_cli \\
        https://library.municode.com/wa/seattle \\
        --output seattle.json
    
    # 3. MCP Server
    $ python -m legal_scrapers.mcp.server

Available Scrapers:
    - UnifiedLegalScraper - Automatic scraper selection with fallbacks
    - MunicodeScraper - Municipal codes (3,500+ jurisdictions)
    - CourtListenerScraper - Federal and state court documents
    - SupremeCourtScraper - U.S. Supreme Court opinions
    - CitationResolver - Multi-source citation resolution
    - StateLawsScraper - State statutes and codes
    - FederalRegisterScraper - Federal regulations
    - USCodeScraper - U.S. Code
    - RECAPScraper - Federal court documents (PACER)

Features:
    - Content addressing with IPFS CIDs
    - Automatic deduplication
    - Version tracking (Wayback Machine style)
    - WARC import/export
    - Common Crawl multi-index integration
    - Interplanetary Wayback Machine (IPWB)
    - Batch scraping with multiprocessing
    - Intelligent fallback cascade
    - Citation resolution with multiple sources
"""

__version__ = "2.0.0"
__author__ = "IPFS Datasets Team"

# Core scraper exports
from .core import (
    BaseLegalScraper,
    run_async_scraper,
    MunicodeScraper,
    StateLawsScraper,
    FederalRegisterScraper,
    USCodeScraper,
    ECode360Scraper,
    MunicipalCodeScraper,
    scrape_municode,
    scrape_state_law,
    scrape_federal_register,
    scrape_us_code,
    scrape_ecode360,
    scrape_municipal_code,
)

# New court document scrapers
from .core.courtlistener import (
    CourtListenerScraper,
    search_opinions,
    resolve_citation as cl_resolve_citation,
    get_supreme_court_opinions as cl_get_supreme_court,
    get_circuit_court_opinions,
)

from .core.supreme_court import (
    SupremeCourtScraper,
    get_opinions as sc_get_opinions,
    get_oral_arguments,
    resolve_citation as sc_resolve_citation,
)

from .core.citation_resolver import (
    CitationResolver,
    resolve_citation,
    batch_resolve_citations,
)

# Unified scraper with all fallbacks
from .unified_scraper import UnifiedLegalScraper

# MCP exports
from .mcp import (
    get_registry,
    register_all_legal_scraper_tools,
    list_all_tools,
)

__all__ = [
    # Core
    'BaseLegalScraper',
    'run_async_scraper',
    
    # Unified scraper
    'UnifiedLegalScraper',
    
    # Municipal/State scrapers
    'MunicodeScraper',
    'StateLawsScraper',
    'ECode360Scraper',
    'MunicipalCodeScraper',
    
    # Federal scrapers
    'FederalRegisterScraper',
    'USCodeScraper',
    
    # Court document scrapers
    'CourtListenerScraper',
    'SupremeCourtScraper',
    'CitationResolver',
    
    # Convenience functions - Municipal/State
    'scrape_municode',
    'scrape_state_law',
    'scrape_ecode360',
    'scrape_municipal_code',
    
    # Convenience functions - Federal
    'scrape_federal_register',
    'scrape_us_code',
    
    # Convenience functions - Courts
    'search_opinions',
    'resolve_citation',
    'batch_resolve_citations',
    'get_supreme_court_opinions',
    'get_circuit_court_opinions',
    'get_oral_arguments',
    
    # MCP
    'get_registry',
    'register_all_legal_scraper_tools',
    'list_all_tools',
    
    # Metadata
    '__version__',
]
