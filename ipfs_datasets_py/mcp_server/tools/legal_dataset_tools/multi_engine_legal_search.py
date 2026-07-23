"""
Compatibility shim — business logic moved to ipfs_datasets_py.processors.legal_scrapers.multi_engine_legal_search.

Do not add new code here. Use the canonical package location instead.
"""
from typing import Any, Dict, List, Optional

from ipfs_datasets_py.processors.legal_scrapers import (  # noqa: F401
    get_multi_engine_stats as _get_multi_engine_stats,
    multi_engine_legal_search as _multi_engine_legal_search,
)


async def multi_engine_legal_search(
    query: str,
    engines: Optional[List[str]] = None,
    max_results: int = 20,
    parallel_enabled: bool = True,
    fallback_enabled: bool = True,
    deduplication_enabled: bool = True,
    result_aggregation: str = "merge",
    country: str = "US",
    lang: str = "en",
    brave_api_key: Optional[str] = None,
    google_api_key: Optional[str] = None,
    google_cse_id: Optional[str] = None,
) -> Dict[str, Any]:
    return await _multi_engine_legal_search(
        query=query,
        engines=engines,
        max_results=max_results,
        parallel_enabled=parallel_enabled,
        fallback_enabled=fallback_enabled,
        deduplication_enabled=deduplication_enabled,
        result_aggregation=result_aggregation,
        country=country,
        lang=lang,
        brave_api_key=brave_api_key,
        google_api_key=google_api_key,
        google_cse_id=google_cse_id,
    )


async def get_multi_engine_stats() -> Dict[str, Any]:
    return await _get_multi_engine_stats()
