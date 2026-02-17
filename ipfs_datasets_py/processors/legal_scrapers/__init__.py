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
from .multi_engine_legal_search import MultiEngineLegalSearch
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

# Query Expander - LLM-based query expansion (NEW - Enhancement 9)
try:
    from .query_expander import QueryExpander, ExpandedQuery, expand_query
    HAVE_QUERY_EXPANDER = True
except ImportError:
    QueryExpander = None
    ExpandedQuery = None
    expand_query = None
    HAVE_QUERY_EXPANDER = False

# Enhanced Query Expander - Enhanced with legal synonyms and relationships (Enhancement 12 Phase 2)
try:
    from .enhanced_query_expander import EnhancedQueryExpander, EnhancedExpandedQuery
    HAVE_ENHANCED_QUERY_EXPANDER = True
except ImportError:
    EnhancedQueryExpander = None
    EnhancedExpandedQuery = None
    HAVE_ENHANCED_QUERY_EXPANDER = False

# Result Filter - Advanced result filtering (Enhancement 12 Phase 3)
try:
    from .result_filter import ResultFilter, FilterConfig, FilteredResult
    HAVE_RESULT_FILTER = True
except ImportError:
    ResultFilter = None
    FilterConfig = None
    FilteredResult = None
    HAVE_RESULT_FILTER = False

# Search Result Citation Extractor - Enhanced citation extraction (Enhancement 12 Phase 4)
try:
    from .search_result_citation_extractor import (
        SearchResultCitationExtractor,
        SearchResultWithCitations,
        CitationNetwork
    )
    HAVE_SEARCH_RESULT_CITATION_EXTRACTOR = True
except ImportError:
    SearchResultCitationExtractor = None
    SearchResultWithCitations = None
    CitationNetwork = None
    HAVE_SEARCH_RESULT_CITATION_EXTRACTOR = False

# Legal GraphRAG - GraphRAG integration for legal search (Enhancement 12 Phase 5)
try:
    from .legal_graphrag import (
        LegalGraphRAG,
        LegalEntity,
        LegalRelationship,
        LegalKnowledgeGraph
    )
    HAVE_LEGAL_GRAPHRAG = True
except ImportError:
    LegalGraphRAG = None
    LegalEntity = None
    LegalRelationship = None
    LegalKnowledgeGraph = None
    HAVE_LEGAL_GRAPHRAG = False

# Multi-Language Support - I18n for legal search (Enhancement 12 Phase 6)
try:
    from .multilanguage_support import (
        MultiLanguageSupport,
        LanguageConfig,
        TranslationResult
    )
    HAVE_MULTILANGUAGE_SUPPORT = True
except ImportError:
    MultiLanguageSupport = None
    LanguageConfig = None
    TranslationResult = None
    HAVE_MULTILANGUAGE_SUPPORT = False

# Regulation Version Tracker - Historical tracking (Enhancement 12 Phase 7)
try:
    from .regulation_version_tracker import (
        RegulationVersionTracker,
        RegulationVersion,
        RegulationChange
    )
    HAVE_REGULATION_VERSION_TRACKER = True
except ImportError:
    RegulationVersionTracker = None
    RegulationVersion = None
    RegulationChange = None
    HAVE_REGULATION_VERSION_TRACKER = False

# Legal Report Generator - Automated reports (Enhancement 12 Phase 8)
try:
    from .legal_report_generator import (
        LegalSearchReportGenerator,
        LegalSearchReport,
        ReportConfig,
        ReportSection
    )
    HAVE_LEGAL_REPORT_GENERATOR = True
except ImportError:
    LegalSearchReportGenerator = None
    LegalSearchReport = None
    ReportConfig = None
    ReportSection = None
    HAVE_LEGAL_REPORT_GENERATOR = False

# HuggingFace API search (Enhancement 11 Part 1)
try:
    from .huggingface_api_search import HuggingFaceAPISearch
    HAVE_HF_API_SEARCH = True
except ImportError:
    HuggingFaceAPISearch = None
    HAVE_HF_API_SEARCH = False

# Parallel web archiver (Enhancement 11 Part 2)
try:
    from .parallel_web_archiver import (
        ParallelWebArchiver,
        ArchiveResult,
        ArchiveProgress,
        archive_urls
    )
    HAVE_PARALLEL_ARCHIVER = True
except ImportError:
    ParallelWebArchiver = None
    ArchiveResult = None
    ArchiveProgress = None
    archive_urls = None
    HAVE_PARALLEL_ARCHIVER = False

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
    "MultiEngineLegalSearch",  # Multi-engine search
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
    
    # Query Expander (NEW - Enhancement 9)
    "QueryExpander",
    "ExpandedQuery",
    "expand_query",
    "HAVE_QUERY_EXPANDER",
    
    # Enhanced Query Expander (Enhancement 12 Phase 2)
    "EnhancedQueryExpander",
    "EnhancedExpandedQuery",
    "HAVE_ENHANCED_QUERY_EXPANDER",
    
    # Result Filter (Enhancement 12 Phase 3)
    "ResultFilter",
    "FilterConfig",
    "FilteredResult",
    "HAVE_RESULT_FILTER",
    
    # Search Result Citation Extractor (Enhancement 12 Phase 4)
    "SearchResultCitationExtractor",
    "SearchResultWithCitations",
    "CitationNetwork",
    "HAVE_SEARCH_RESULT_CITATION_EXTRACTOR",
    
    # Legal GraphRAG (Enhancement 12 Phase 5)
    "LegalGraphRAG",
    "LegalEntity",
    "LegalRelationship",
    "LegalKnowledgeGraph",
    "HAVE_LEGAL_GRAPHRAG",
    
    # Multi-Language Support (Enhancement 12 Phase 6)
    "MultiLanguageSupport",
    "LanguageConfig",
    "TranslationResult",
    "HAVE_MULTILANGUAGE_SUPPORT",
    
    # Regulation Version Tracker (Enhancement 12 Phase 7)
    "RegulationVersionTracker",
    "RegulationVersion",
    "RegulationChange",
    "HAVE_REGULATION_VERSION_TRACKER",
    
    # Legal Report Generator (Enhancement 12 Phase 8)
    "LegalSearchReportGenerator",
    "LegalSearchReport",
    "ReportConfig",
    "ReportSection",
    "HAVE_LEGAL_REPORT_GENERATOR",
    
    # HuggingFace API search (Enhancement 11 Part 1)
    "HuggingFaceAPISearch",
    "HAVE_HF_API_SEARCH",
    
    # Parallel web archiver (Enhancement 11 Part 2)
    "ParallelWebArchiver",
    "ArchiveResult",
    "ArchiveProgress",
    "archive_urls",
    "HAVE_PARALLEL_ARCHIVER",
]
