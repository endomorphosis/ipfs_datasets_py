"""
Legal Scrapers Module

Core implementations for scraping legal datasets from various sources including:
- Federal Register
- US Code
- State Laws
- Municipal Laws
- RECAP Archive (court documents)
- Brave Legal Search (natural language search for legal rules)

This module provides the core scraping logic that can be used by:
- CLI tools (ipfs-datasets)
- MCP server tools
- Direct Python imports

New Features:
- Natural language legal search using Brave Search API
- Knowledge base of 21,000+ federal, state, and municipal entities
- Intelligent search term generation from queries
"""

# Import main scraper modules using relative imports
from . import (
    federal_register_scraper,
    us_code_scraper,
    state_laws_scraper,
    municipal_laws_scraper,
    recap_archive_scraper,
)

# Import utility modules
from . import (
    citation_extraction,
    export_utils,
    ipfs_storage_integration,
)

# Scraping state + orchestration helpers
from .scraping_state import ScrapingState, list_scraping_jobs, delete_scraping_job
from .municipal_codes_api import initialize_municipal_codes_job
from .legal_dataset_api import (
    scrape_recap_archive_from_parameters,
    search_recap_documents_from_parameters,
    scrape_state_laws_from_parameters,
    list_scraping_jobs_from_parameters,
    scrape_us_code_from_parameters,
    scrape_municipal_codes_from_parameters,
)

# Re-export key functions from scrapers for direct access
from .federal_register_scraper import (
    search_federal_register,
    scrape_federal_register,
)

from .us_code_scraper import (
    get_us_code_titles,
    scrape_us_code,
    search_us_code,
    fetch_us_code_title,
)

from .state_laws_scraper import (
    list_state_jurisdictions,
    scrape_state_laws,
)

from .municipal_laws_scraper import (
    search_municipal_codes,
    scrape_municipal_laws,
)

from .recap_archive_scraper import (
    search_recap_documents,
    scrape_recap_archive,
    get_recap_document,
)

# Re-export utility functions
from .export_utils import (
    export_dataset,
    export_to_json,
    export_to_parquet,
    export_to_csv,
)

from .citation_extraction import (
    Citation,
    CitationExtractor,
    extract_citations_from_text,
    analyze_document_citations,
    create_citation_network,
)

from .ipfs_storage_integration import (
    IPFSStorageManager,
    store_dataset_to_ipfs,
    retrieve_dataset_from_ipfs,
    list_ipfs_datasets,
)

# Brave Legal Search - Natural language search for legal rules and regulations
from .brave_legal_search import (
    BraveLegalSearch,
    create_legal_search,
    search_legal,
)
from .knowledge_base_loader import (
    LegalKnowledgeBase,
    FederalEntity,
    StateEntity,
    MunicipalEntity,
    load_knowledge_base,
    get_global_knowledge_base,
)
from .query_processor import (
    QueryProcessor,
    QueryIntent,
)
from .search_term_generator import (
    SearchTermGenerator,
    SearchTerm,
    SearchStrategy,
)

# Legal Web Archive Search - Unified search with archiving (NEW)
try:
    from .legal_web_archive_search import LegalWebArchiveSearch
    HAVE_WEB_ARCHIVE_SEARCH = True
except ImportError:
    LegalWebArchiveSearch = None
    HAVE_WEB_ARCHIVE_SEARCH = False

# Common Crawl Index Loader - HuggingFace integration (NEW)
try:
    from .common_crawl_index_loader import CommonCrawlIndexLoader
    HAVE_CC_INDEX_LOADER = True
except ImportError:
    CommonCrawlIndexLoader = None
    HAVE_CC_INDEX_LOADER = False

# Shared components module (NEW - Enhancement 7)
# These components are used by both Brave Legal Search and Complaint Analysis
try:
    from . import common
    HAVE_COMMON_MODULE = True
except ImportError:
    common = None
    HAVE_COMMON_MODULE = False

__all__ = [
    # Modules
    "federal_register_scraper",
    "us_code_scraper",
    "state_laws_scraper",
    "municipal_laws_scraper",
    "recap_archive_scraper",
    "citation_extraction",
    "export_utils",
    "ipfs_storage_integration",
    # Federal Register functions
    "search_federal_register",
    "scrape_federal_register",
    # US Code functions
    "get_us_code_titles",
    "scrape_us_code",
    "search_us_code",
    "fetch_us_code_title",
    # State Laws functions
    "list_state_jurisdictions",
    "scrape_state_laws",
    # Municipal Laws functions
    "search_municipal_codes",
    "scrape_municipal_laws",
    # RECAP Archive functions
    "search_recap_documents",
    "scrape_recap_archive",
    "get_recap_document",
    # Export utilities
    "export_dataset",
    "export_to_json",
    "export_to_parquet",
    "export_to_csv",
    # Citation extraction
    "Citation",
    "CitationExtractor",
    "extract_citations_from_text",
    "analyze_document_citations",
    "create_citation_network",
    # IPFS storage
    "IPFSStorageManager",
    "store_dataset_to_ipfs",
    "retrieve_dataset_from_ipfs",
    "list_ipfs_datasets",

    # Scraping state
    "ScrapingState",
    "list_scraping_jobs",
    "delete_scraping_job",

    # Municipal codes orchestration
    "initialize_municipal_codes_job",

    # Parameter-driven APIs
    "scrape_recap_archive_from_parameters",
    "search_recap_documents_from_parameters",
    "scrape_state_laws_from_parameters",
    "list_scraping_jobs_from_parameters",
    "scrape_us_code_from_parameters",
    "scrape_municipal_codes_from_parameters",
    
    # Brave Legal Search
    "BraveLegalSearch",
    "create_legal_search",
    "search_legal",
    "LegalKnowledgeBase",
    "FederalEntity",
    "StateEntity",
    "MunicipalEntity",
    "load_knowledge_base",
    "get_global_knowledge_base",
    "QueryProcessor",
    "QueryIntent",
    "SearchTermGenerator",
    "SearchTerm",
    "SearchStrategy",
    
    # Legal Web Archive Search (NEW)
    "LegalWebArchiveSearch",
    "HAVE_WEB_ARCHIVE_SEARCH",
    
    # Common Crawl Index Loader (NEW)
    "CommonCrawlIndexLoader",
    "HAVE_CC_INDEX_LOADER",
    
    # Shared components module (NEW - Enhancement 7)
    "common",
    "HAVE_COMMON_MODULE",
]
