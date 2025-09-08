"""Web archive tools for the MCP server.

These tools allow AI assistants to work with web archives through the MCP protocol.
"""

from .create_warc import create_warc
from .extract_dataset_from_cdxj import extract_dataset_from_cdxj
from .extract_links_from_warc import extract_links_from_warc
from .extract_metadata_from_warc import extract_metadata_from_warc
from .extract_text_from_warc import extract_text_from_warc
from .index_warc import index_warc

# New archiving tools
from .common_crawl_search import search_common_crawl, get_common_crawl_content, list_common_crawl_indexes
from .wayback_machine_search import search_wayback_machine, get_wayback_content, archive_to_wayback
from .ipwb_integration import index_warc_to_ipwb, start_ipwb_replay, search_ipwb_archive, get_ipwb_content, verify_ipwb_archive
from .autoscraper_integration import create_autoscraper_model, scrape_with_autoscraper, optimize_autoscraper_model, batch_scrape_with_autoscraper, list_autoscraper_models
from .archive_is_integration import archive_to_archive_is, search_archive_is, get_archive_is_content, check_archive_status, batch_archive_to_archive_is

__all__ = [
    # Original tools
    "create_warc",
    "extract_dataset_from_cdxj",
    "extract_links_from_warc",
    "extract_metadata_from_warc",
    "extract_text_from_warc",
    "index_warc",
    
    # Common Crawl tools
    "search_common_crawl",
    "get_common_crawl_content", 
    "list_common_crawl_indexes",
    
    # Wayback Machine tools
    "search_wayback_machine",
    "get_wayback_content",
    "archive_to_wayback",
    
    # IPWB tools
    "index_warc_to_ipwb",
    "start_ipwb_replay",
    "search_ipwb_archive",
    "get_ipwb_content",
    "verify_ipwb_archive",
    
    # AutoScraper tools
    "create_autoscraper_model",
    "scrape_with_autoscraper",
    "optimize_autoscraper_model",
    "batch_scrape_with_autoscraper",
    "list_autoscraper_models",
    
    # Archive.is tools
    "archive_to_archive_is",
    "search_archive_is",
    "get_archive_is_content",
    "check_archive_status",
    "batch_archive_to_archive_is"
]
