"""Legal dataset scraping tools for the MCP server.

These tools allow AI assistants to scrape legal datasets including:
- US Code
- Federal Register
- State Laws
- Municipal Laws
- RECAP Archive (Court Documents)
- Brave Legal Search (Natural language search for legal rules)

Also includes:
- IPFS storage integration
- Citation extraction and analysis
- Multi-format export utilities
- Resume capability for interrupted scraping
- Incremental update tracking
- Periodic update scheduling for automated data refresh
- Knowledge base of 21,000+ government entities
"""

from .us_code_scraper import scrape_us_code, get_us_code_titles, search_us_code
from .federal_register_scraper import scrape_federal_register, search_federal_register
from .state_laws_scraper import scrape_state_laws, list_state_jurisdictions
from .municipal_laws_scraper import scrape_municipal_laws, search_municipal_codes
from .recap_archive_scraper import scrape_recap_archive, search_recap_documents, get_recap_document
from .export_utils import export_dataset, export_to_json, export_to_parquet, export_to_csv
from .state_manager import ScrapingState, list_scraping_jobs, delete_scraping_job
from .incremental_updates import (
    IncrementalUpdateTracker, 
    scrape_recap_incremental, 
    scrape_with_incremental_update,
    calculate_update_parameters
)
from .ipfs_storage_integration import (
    IPFSStorageManager,
    store_dataset_to_ipfs,
    retrieve_dataset_from_ipfs,
    list_ipfs_datasets
)
from .citation_extraction import (
    CitationExtractor,
    Citation,
    extract_citations_from_text,
    analyze_document_citations,
    create_citation_network
)
from .state_laws_scheduler import (
    StateLawsUpdateScheduler,
    create_schedule,
    remove_schedule,
    list_schedules,
    run_schedule_now,
    enable_disable_schedule
)
from .brave_legal_search_tools import (
    BRAVE_LEGAL_SEARCH_TOOLS,
    register_brave_legal_search_tools,
    brave_legal_search_tool,
    brave_legal_search_generate_terms_tool,
    brave_legal_search_explain_tool,
    brave_legal_search_entities_tool
)
from .legal_web_archive_tools import (
    LEGAL_WEB_ARCHIVE_TOOLS,
    register_legal_web_archive_tools,
    legal_web_archive_search_tool,
    legal_search_archives_only_tool,
    legal_archive_results_tool,
    legal_get_archive_stats_tool
)

__all__ = [
    # US Code tools
    "scrape_us_code",
    "get_us_code_titles",
    "search_us_code",
    
    # Federal Register tools
    "scrape_federal_register",
    "search_federal_register",
    
    # State Laws tools
    "scrape_state_laws",
    "list_state_jurisdictions",
    
    # Municipal Laws tools
    "scrape_municipal_laws",
    "search_municipal_codes",
    
    # RECAP Archive tools
    "scrape_recap_archive",
    "search_recap_documents",
    "get_recap_document",
    
    # Export utilities
    "export_dataset",
    "export_to_json",
    "export_to_parquet",
    "export_to_csv",
    
    # State management
    "ScrapingState",
    "list_scraping_jobs",
    "delete_scraping_job",
    
    # Incremental updates
    "IncrementalUpdateTracker",
    "scrape_recap_incremental",
    "scrape_with_incremental_update",
    "calculate_update_parameters",
    
    # IPFS storage integration
    "IPFSStorageManager",
    "store_dataset_to_ipfs",
    "retrieve_dataset_from_ipfs",
    "list_ipfs_datasets",
    
    # Citation extraction and analysis
    "CitationExtractor",
    "Citation",
    "extract_citations_from_text",
    "analyze_document_citations",
    "create_citation_network",
    
    # State Laws scheduling
    "StateLawsUpdateScheduler",
    "create_schedule",
    "remove_schedule",
    "list_schedules",
    "run_schedule_now",
    "enable_disable_schedule",
    
    # Brave Legal Search tools
    "BRAVE_LEGAL_SEARCH_TOOLS",
    "register_brave_legal_search_tools",
    "brave_legal_search_tool",
    "brave_legal_search_generate_terms_tool",
    "brave_legal_search_explain_tool",
    "brave_legal_search_entities_tool",
    
    # Legal Web Archive tools (NEW)
    "LEGAL_WEB_ARCHIVE_TOOLS",
    "register_legal_web_archive_tools",
    "legal_web_archive_search_tool",
    "legal_search_archives_only_tool",
    "legal_archive_results_tool",
    "legal_get_archive_stats_tool",
]
