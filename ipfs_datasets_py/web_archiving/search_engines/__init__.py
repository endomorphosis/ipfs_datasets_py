"""
Search Engine Adapters for Web Archiving.

This module provides a unified interface for multiple search engines,
enabling flexible search across Brave, DuckDuckGo, Google CSE, and more.

These adapters are used throughout the system for web archiving,
legal search, and other search-dependent features.

Architecture:
- SearchEngineAdapter: Abstract base class defining the interface
- Concrete adapters: BraveSearchEngine, DuckDuckGoSearchEngine, GoogleCSESearchEngine
- MultiEngineOrchestrator: Coordinates multiple engines for parallel/fallback search

Features:
- Unified search interface across engines
- Rate limiting and quota management
- Response caching with TTL
- Fallback and retry logic
- Result normalization
- Performance metrics

Usage:
    from ipfs_datasets_py.web_archiving.search_engines import (
        MultiEngineOrchestrator,
        OrchestratorConfig
    )
    
    config = OrchestratorConfig(
        engines=["brave", "duckduckgo", "google_cse"],
        parallel_enabled=True,
        fallback_enabled=True
    )
    
    orchestrator = MultiEngineOrchestrator(config)
    results = orchestrator.search("EPA water regulations California")
"""

from .base import (
    SearchEngineAdapter,
    SearchEngineResult,
    SearchEngineResponse,
    SearchEngineError,
    SearchEngineConfig,
    SearchEngineType,
    SearchEngineRateLimitError,
    SearchEngineQuotaExceededError,
)

from .brave_adapter import BraveSearchEngine
from .duckduckgo_adapter import DuckDuckGoSearchEngine
from .google_cse_adapter import GoogleCSESearchEngine
from .orchestrator import MultiEngineOrchestrator, OrchestratorConfig

__all__ = [
    # Base classes
    "SearchEngineAdapter",
    "SearchEngineResult",
    "SearchEngineResponse",
    "SearchEngineError",
    "SearchEngineConfig",
    "SearchEngineType",
    "SearchEngineRateLimitError",
    "SearchEngineQuotaExceededError",
    # Concrete adapters
    "BraveSearchEngine",
    "DuckDuckGoSearchEngine",
    "GoogleCSESearchEngine",
    # Orchestrator
    "MultiEngineOrchestrator",
    "OrchestratorConfig",
]
