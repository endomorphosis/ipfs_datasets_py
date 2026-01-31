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
from .common_crawl_advanced import (
    search_common_crawl_advanced,
    fetch_warc_record_advanced,
    list_common_crawl_collections_advanced,
    get_common_crawl_collection_info_advanced
)
from .wayback_machine_search import search_wayback_machine, get_wayback_content, archive_to_wayback
from .ipwb_integration import index_warc_to_ipwb, start_ipwb_replay, search_ipwb_archive, get_ipwb_content, verify_ipwb_archive
from .autoscraper_integration import create_autoscraper_model, scrape_with_autoscraper, optimize_autoscraper_model, batch_scrape_with_autoscraper, list_autoscraper_models
from .archive_is_integration import archive_to_archive_is, search_archive_is, get_archive_is_content, check_archive_status, batch_archive_to_archive_is

# Brave Search tools
from .brave_search import search_brave, search_brave_news, search_brave_images, batch_search_brave

# Google Search tools
from .google_search import search_google, search_google_images, batch_search_google

# GitHub Search tools
from .github_search import search_github_repositories, search_github_code, search_github_users, search_github_issues, batch_search_github

# HuggingFace Search tools
from .huggingface_search import search_huggingface_models, search_huggingface_datasets, search_huggingface_spaces, get_huggingface_model_info, batch_search_huggingface

# OpenVerse Search tools
from .openverse_search import search_openverse_images, search_openverse_audio, batch_search_openverse, OpenVerseSearchAPI

# SerpStack Search tools
from .serpstack_search import search_serpstack, search_serpstack_images, batch_search_serpstack, SerpStackSearchAPI

# Search API classes
from .brave_search import BraveSearchAPI

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
    
    # Common Crawl Advanced tools (from submodule)
    "search_common_crawl_advanced",
    "fetch_warc_record_advanced",
    "list_common_crawl_collections_advanced",
    "get_common_crawl_collection_info_advanced",
    
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
    "batch_archive_to_archive_is",
    
    # Brave Search tools
    "search_brave",
    "search_brave_news",
    "search_brave_images",
    "batch_search_brave",
    
    # Google Search tools
    "search_google",
    "search_google_images",
    "batch_search_google",
    
    # GitHub Search tools
    "search_github_repositories",
    "search_github_code",
    "search_github_users",
    "search_github_issues",
    "batch_search_github",
    
    # HuggingFace Search tools
    "search_huggingface_models",
    "search_huggingface_datasets",
    "search_huggingface_spaces",
    "get_huggingface_model_info",
    "batch_search_huggingface",
    
    # OpenVerse Search tools
    "search_openverse_images",
    "search_openverse_audio",
    "batch_search_openverse",
    "OpenVerseSearchAPI",
    
    # SerpStack Search tools
    "search_serpstack",
    "search_serpstack_images",
    "batch_search_serpstack",
    "SerpStackSearchAPI",
    
    # Search API Classes
    "BraveSearchAPI"
]
