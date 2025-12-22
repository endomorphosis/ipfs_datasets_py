"""Web archive tools for the MCP server.

These tools allow AI assistants to work with web archives through the MCP protocol.
"""

from __future__ import annotations

from importlib import import_module


def _safe_import(module_name: str, names: list[str]) -> None:
    """Best-effort imports for optional dependencies.

    Many tools have optional third-party deps (e.g. pydantic, torch, fastapi).
    This package should remain importable even when those deps are missing.
    """
    try:
        mod = import_module(module_name, package=__name__)
    except Exception:
        return
    for n in names:
        try:
            globals()[n] = getattr(mod, n)
        except Exception:
            globals().setdefault(n, None)

_safe_import(".create_warc", ["create_warc"])
_safe_import(".extract_dataset_from_cdxj", ["extract_dataset_from_cdxj"])
_safe_import(".extract_links_from_warc", ["extract_links_from_warc"])
_safe_import(".extract_metadata_from_warc", ["extract_metadata_from_warc"])
_safe_import(".extract_text_from_warc", ["extract_text_from_warc"])
_safe_import(".index_warc", ["index_warc"])

# New archiving tools
_safe_import(
    ".common_crawl_search",
    ["search_common_crawl", "get_common_crawl_content", "list_common_crawl_indexes"],
)
_safe_import(
    ".wayback_machine_search",
    ["search_wayback_machine", "get_wayback_content", "archive_to_wayback"],
)
_safe_import(
    ".ipwb_integration",
    [
        "index_warc_to_ipwb",
        "start_ipwb_replay",
        "search_ipwb_archive",
        "get_ipwb_content",
        "verify_ipwb_archive",
    ],
)
_safe_import(
    ".autoscraper_integration",
    [
        "create_autoscraper_model",
        "scrape_with_autoscraper",
        "optimize_autoscraper_model",
        "batch_scrape_with_autoscraper",
        "list_autoscraper_models",
    ],
)
_safe_import(
    ".archive_is_integration",
    [
        "archive_to_archive_is",
        "search_archive_is",
        "get_archive_is_content",
        "check_archive_status",
        "batch_archive_to_archive_is",
    ],
)
_safe_import(
    ".archive_check_submit",
    ["check_and_submit_to_archives", "batch_check_and_submit", "submit_archives_async", "get_archive_job"],
)

# Brave Search tools
_safe_import(
    ".brave_search",
    ["search_brave", "search_brave_news", "search_brave_images", "batch_search_brave", "BraveSearchAPI"],
)

# Google Search tools
_safe_import(".google_search", ["search_google", "search_google_images", "batch_search_google"])

# GitHub Search tools
_safe_import(
    ".github_search",
    [
        "search_github_repositories",
        "search_github_code",
        "search_github_users",
        "search_github_issues",
        "batch_search_github",
    ],
)

# HuggingFace Search tools
_safe_import(
    ".huggingface_search",
    [
        "search_huggingface_models",
        "search_huggingface_datasets",
        "search_huggingface_spaces",
        "get_huggingface_model_info",
        "batch_search_huggingface",
    ],
)

# OpenVerse Search tools
_safe_import(
    ".openverse_search",
    [
        "search_openverse_images",
        "search_openverse_audio",
        "batch_search_openverse",
        "OpenVerseSearchAPI",
    ],
)

# SerpStack Search tools
_safe_import(
    ".serpstack_search",
    ["search_serpstack", "search_serpstack_images", "batch_search_serpstack", "SerpStackSearchAPI"],
)

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
    "batch_archive_to_archive_is",

    # Archive check/submit (async jobs)
    "check_and_submit_to_archives",
    "batch_check_and_submit",
    "submit_archives_async",
    "get_archive_job",
    
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

for _n in __all__:
    globals().setdefault(_n, None)
