"""
Web Archiving package — canonical location for web search and archiving engine classes.

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

from .brave_search_engine import BraveSearchAPI  # noqa: F401
from .serpstack_engine import SerpStackSearchAPI  # noqa: F401
from .openverse_engine import OpenVerseSearchAPI  # noqa: F401
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
]
