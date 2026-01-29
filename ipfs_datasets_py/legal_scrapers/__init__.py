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
]
