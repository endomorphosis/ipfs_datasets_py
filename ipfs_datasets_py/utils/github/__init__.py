"""Unified GitHub operations.

This module provides unified GitHub operations consolidating functionality from:
- utils/github_wrapper.py
- utils/github_cli.py
- optimizers/agentic/github_api_unified.py

Public API:
- GitHubCLI: Unified CLI wrapper with caching and tracking
- APICounter: API call tracking and metrics
- RateLimiter: Rate limit monitoring and management
- GitHubCache: GitHub API-specific cache (re-exported from utils.cache)

Example:
    >>> from ipfs_datasets_py.utils.github import GitHubCLI
    >>> 
    >>> gh = GitHubCLI(enable_cache=True)
    >>> repos = gh.list_repos(limit=10)
    >>> pr = gh.create_pr(title="Fix", body="Description")
    >>> 
    >>> print(gh.report())
"""

# Core components
from .cli_wrapper import GitHubCLI
from .counter import APICounter, APICallRecord, GitHubAPICounter
from .rate_limiter import RateLimiter, AdaptiveRateLimiter

# Re-export GitHubCache from cache module
from ..cache import GitHubCache, GitHubCacheEntry

__all__ = [
    # Main API
    'GitHubCLI',
    'APICounter',
    'APICallRecord',
    'RateLimiter',
    'GitHubCache',
    
    # Additional classes
    'GitHubCacheEntry',
    
    # Backward compatibility aliases
    'GitHubAPICounter',
    'AdaptiveRateLimiter',
]
