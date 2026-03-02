"""
Web archiving and scraping utilities for IPFS Datasets Python.

This module provides tools for web scraping, archiving, and text extraction.

Engine classes:
    - BraveSearchAPI            (brave_search_engine.py)
    - SerpStackSearchAPI        (serpstack_engine.py)
    - OpenVerseSearchAPI        (openverse_engine.py)
    - GitHubRepositoryScraper   (github_repository_engine.py)
    - scrape_github_repository  (github_repository_engine.py)
    - analyze_repository_health (github_repository_engine.py)

Search engine functions:
    - search_huggingface_models, search_huggingface_datasets, ...  (huggingface_search_engine.py)
    - search_github_repositories, search_github_code, ...          (github_search_engine.py)
    - create_autoscraper_model, scrape_with_autoscraper, ...       (autoscraper_engine.py)
    - archive_to_archive_is, search_archive_is, ...                (archive_is_engine.py)
    - search_google, search_google_images, batch_search_google     (google_search_engine.py)
    - search_wayback_machine, get_wayback_content, archive_to_wayback (wayback_machine_engine.py)
    - index_warc_to_ipwb, start_ipwb_replay, search_ipwb_archive   (ipwb_engine.py)

MCP tool wrappers live in:
    ipfs_datasets_py/mcp_server/tools/web_archive_tools/
    ipfs_datasets_py/mcp_server/tools/software_engineering_tools/
"""

from .web_archive import *
from .web_archive_utils import *
from .web_text_extractor import *
from .simple_crawler import *
from .unified_web_scraper import *
from .scraper_testing_framework import *
from .common_crawl_integration import CommonCrawlSearchEngine, create_search_engine
from .contracts import (
    OperationMode,
    ErrorSeverity,
    UnifiedError,
    UnifiedSearchHit,
    UnifiedDocument,
    ExecutionTrace,
    UnifiedSearchRequest,
    UnifiedFetchRequest,
    UnifiedSearchResponse,
    UnifiedFetchResponse,
)
from .metrics import MetricsRegistry, ProviderEvent
from .orchestration import (
    ProviderScorer,
    ProviderScore,
    ScoringTargets,
    ScoringWeights,
    SearchExecutionPlan,
    SearchExecutionResult,
    SearchExecutor,
    SearchPlanner,
    CircuitBreakerConfig,
    CircuitBreakerRecord,
    CircuitBreakerRegistry,
    CircuitState,
    RetryPolicy,
    execute_with_retry,
)
from .unified_api import UnifiedWebArchivingAPI, UnifiedAPIConfig
from .agentic_scrape_optimizer import (
    AgenticExtractionConfig,
    AgenticScrapeOptimizer,
    ParsedScrapeResult,
)
from .compat import legacy_search_web, legacy_fetch_url, legacy_search_and_fetch
from .brave_search_client import (
    BraveSearchClient,
    brave_web_search,
    brave_web_search_page,
    brave_search_cache_stats,
    clear_brave_search_cache
)

# Import search engines module
from . import search_engines

# Try to import IPFS cache (may not be available without ipfshttpclient)
try:
    from .brave_search_ipfs_cache import BraveSearchIPFSCache
    HAVE_IPFS_CACHE = True
except ImportError:
    BraveSearchIPFSCache = None
    HAVE_IPFS_CACHE = False


from .brave_search_engine import BraveSearchAPI  # noqa: F401
from .serpstack_engine import (  # noqa: F401
    SerpStackSearchAPI,
    search_serpstack,
    search_serpstack_images,
    batch_search_serpstack,
)
from .openverse_engine import (  # noqa: F401
    OpenVerseSearchAPI,
    search_openverse_images,
    search_openverse_audio,
    batch_search_openverse,
)
from .github_repository_engine import (  # noqa: F401
    GitHubRepositoryScraper,
    analyze_repository_health,
    scrape_github_repository,
)

try:
    from .huggingface_search_engine import (  # noqa: F401
        batch_search_huggingface,
        get_huggingface_model_info,
        search_huggingface_datasets,
        search_huggingface_models,
        search_huggingface_spaces,
    )
except Exception:
    pass

try:
    from .github_search_engine import (  # noqa: F401
        batch_search_github,
        search_github_code,
        search_github_issues,
        search_github_repositories,
        search_github_users,
    )
except Exception:
    pass

try:
    from .autoscraper_engine import (  # noqa: F401
        batch_scrape_with_autoscraper,
        create_autoscraper_model,
        list_autoscraper_models,
        optimize_autoscraper_model,
        scrape_with_autoscraper,
    )
except Exception:
    pass

try:
    from .archive_is_engine import (  # noqa: F401
        archive_to_archive_is,
        batch_archive_to_archive_is,
        check_archive_status,
        get_archive_is_content,
        search_archive_is,
    )
except Exception:
    pass

try:
    from .google_search_engine import (  # noqa: F401
        search_google,
        search_google_images,
        batch_search_google,
    )
except Exception:
    pass

try:
    from .wayback_machine_engine import (  # noqa: F401
        search_wayback_machine,
        get_wayback_content,
        archive_to_wayback,
    )
except Exception:
    pass

try:
    from .ipwb_engine import (  # noqa: F401
        index_warc_to_ipwb,
        start_ipwb_replay,
        search_ipwb_archive,
        get_ipwb_content,
        verify_ipwb_archive,
    )
except Exception:
    pass

__all__ = [
    "BraveSearchAPI",
    "SerpStackSearchAPI",
    "OpenVerseSearchAPI",
    "GitHubRepositoryScraper",
    "scrape_github_repository",
    "analyze_repository_health",
    # HuggingFace
    "search_huggingface_models",
    "search_huggingface_datasets",
    "search_huggingface_spaces",
    "get_huggingface_model_info",
    "batch_search_huggingface",
    # GitHub Search
    "search_github_repositories",
    "search_github_code",
    "search_github_users",
    "search_github_issues",
    "batch_search_github",
    # AutoScraper
    "create_autoscraper_model",
    "scrape_with_autoscraper",
    "optimize_autoscraper_model",
    "batch_scrape_with_autoscraper",
    "list_autoscraper_models",
    # Archive.is
    "archive_to_archive_is",
    "search_archive_is",
    "get_archive_is_content",
    "check_archive_status",
    "batch_archive_to_archive_is",
    # Google Search
    "search_google",
    "search_google_images",
    "batch_search_google",
    # Wayback Machine
    "search_wayback_machine",
    "get_wayback_content",
    "archive_to_wayback",
    # IPWB
    "index_warc_to_ipwb",
    "start_ipwb_replay",
    "search_ipwb_archive",
    "get_ipwb_content",
    "verify_ipwb_archive",
    'web_archive',
    'web_archive_utils',
    'web_text_extractor',
    'simple_crawler',
    'unified_web_scraper',
    'scraper_testing_framework',
    'CommonCrawlSearchEngine',
    'create_search_engine',
    'BraveSearchClient',
    'brave_web_search',
    'brave_web_search_page',
    'brave_search_cache_stats',
    'clear_brave_search_cache',
    'BraveSearchIPFSCache',
    'HAVE_IPFS_CACHE',
    'search_engines',
    'OperationMode',
    'ErrorSeverity',
    'UnifiedError',
    'UnifiedSearchHit',
    'UnifiedDocument',
    'ExecutionTrace',
    'UnifiedSearchRequest',
    'UnifiedFetchRequest',
    'UnifiedSearchResponse',
    'UnifiedFetchResponse',
    'MetricsRegistry',
    'ProviderEvent',
    'ProviderScorer',
    'ProviderScore',
    'ScoringTargets',
    'ScoringWeights',
    'SearchExecutionPlan',
    'SearchExecutionResult',
    'SearchExecutor',
    'SearchPlanner',
    'CircuitBreakerConfig',
    'CircuitBreakerRecord',
    'CircuitBreakerRegistry',
    'CircuitState',
    'RetryPolicy',
    'execute_with_retry',
    'UnifiedWebArchivingAPI',
    'UnifiedAPIConfig',
    'AgenticExtractionConfig',
    'AgenticScrapeOptimizer',
    'ParsedScrapeResult',
    'legacy_search_web',
    'legacy_fetch_url',
    'legacy_search_and_fetch',
]
