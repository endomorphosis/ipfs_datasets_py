"""
Cached GitHub CLI Wrapper

Wraps GitHub CLI calls with distributed P2P cache to reduce API rate limit usage.
Uses pylibp2p for peer-to-peer cache sharing and ipfs_multiformats for content hashing.
"""

import anyio
import json
import logging
from typing import Optional, List, Dict, Any
from functools import wraps

from .distributed_cache import get_cache, DistributedGitHubCache
from ipfs_datasets_py.utils.anyio_compat import run as run_anyio
from ipfs_datasets_py.utils.anyio_compat import in_async_context

logger = logging.getLogger(__name__)


class CachedGitHubCLI:
    """
    Wrapper for GitHub CLI that caches responses in distributed P2P cache
    """
    
    def __init__(self, gh_cli, cache: Optional[DistributedGitHubCache] = None):
        """
        Initialize cached wrapper
        
        Args:
            gh_cli: GitHubCLI instance to wrap
            cache: Distributed cache instance (creates one if not provided)
        """
        self.gh = gh_cli
        self.cache = cache or get_cache()

    def _run_async_from_sync(self, awaitable):
        """Run an awaitable from synchronous code.

        If you're already in an async context, use the explicit async APIs
        (e.g. `await list_repos_async(...)`).
        """

        if in_async_context():
            raise RuntimeError(
                "CachedGitHubCLI sync methods cannot be called from an async context. "
                "Use the corresponding async methods (e.g. await list_repos_async(...))."
            )

        return run_anyio(awaitable)

    async def list_repos_async(
        self,
        owner: Optional[str] = None,
        since_days: int = 1,
        use_cache: bool = True,
    ) -> List[str]:
        """Async version of list_repos()."""

        cache_key = f"repos:{owner}:{since_days}"

        if not use_cache:
            return self.gh.list_repos(owner, since_days)

        cached = self.cache.get(cache_key)
        if cached is not None:
            logger.info(f"Cache hit: {cache_key} (saved API call)")
            return cached

        logger.info(f"Cache miss: {cache_key} (calling GitHub API)")
        repos = self.gh.list_repos(owner, since_days)

        # Store in cache with 10 minute TTL
        await self.cache.set(cache_key, repos, ttl=600)
        return repos
    
    def list_repos(
        self,
        owner: Optional[str] = None,
        since_days: int = 1,
        use_cache: bool = True
    ) -> List[str]:
        """
        List repositories with caching
        
        Args:
            owner: Repository owner
            since_days: Filter repos updated in last N days
            use_cache: Whether to use cache (default: True)
        """
        return self._run_async_from_sync(self.list_repos_async(owner, since_days, use_cache))

    async def get_workflow_runs_async(
        self,
        repo: str,
        owner: Optional[str] = None,
        status: str = "queued",
        limit: int = 10,
        use_cache: bool = True,
    ) -> List[Dict]:
        """Async version of get_workflow_runs()."""

        cache_key = f"runs:{owner}/{repo}:{status}:{limit}"

        if not use_cache:
            return self.gh.get_workflow_runs(repo, owner, status, limit)

        cached = self.cache.get(cache_key)
        if cached is not None:
            logger.info(f"Cache hit: {cache_key} (saved API call)")
            return cached

        logger.info(f"Cache miss: {cache_key} (calling GitHub API)")
        runs = self.gh.get_workflow_runs(repo, owner, status, limit)

        # Cache for 2 minutes (workflow status changes frequently)
        await self.cache.set(cache_key, runs, ttl=120)
        return runs
    
    def get_workflow_runs(
        self,
        repo: str,
        owner: Optional[str] = None,
        status: str = "queued",
        limit: int = 10,
        use_cache: bool = True
    ) -> List[Dict]:
        """
        Get workflow runs with caching
        
        Args:
            repo: Repository name
            owner: Repository owner
            status: Run status filter
            limit: Maximum runs to return
            use_cache: Whether to use cache
        """
        return self._run_async_from_sync(
            self.get_workflow_runs_async(repo, owner, status, limit, use_cache)
        )
    
    def get_workflow_queue_depth(
        self,
        repo: str,
        owner: Optional[str] = None,
        use_cache: bool = True
    ) -> int:
        """
        Get workflow queue depth with caching
        
        Args:
            repo: Repository name
            owner: Repository owner
            use_cache: Whether to use cache
        """
        return self._run_async_from_sync(self.get_workflow_queue_depth_async(repo, owner, use_cache))

    async def get_workflow_queue_depth_async(
        self,
        repo: str,
        owner: Optional[str] = None,
        use_cache: bool = True,
    ) -> int:
        """Async version of get_workflow_queue_depth()."""

        cache_key = f"queue_depth:{owner}/{repo}"

        if not use_cache:
            runs = self.gh.get_workflow_runs(repo, owner, "queued")
            return len(runs)

        cached = self.cache.get(cache_key)
        if cached is not None:
            logger.info(f"Cache hit: {cache_key} (saved API call)")
            return cached

        logger.info(f"Cache miss: {cache_key} (calling GitHub API)")
        runs = self.gh.get_workflow_runs(repo, owner, "queued")
        depth = len(runs)

        # Cache for 1 minute
        await self.cache.set(cache_key, depth, ttl=60)
        return depth
    
    def list_runners(
        self,
        repo: Optional[str] = None,
        owner: Optional[str] = None,
        use_cache: bool = True
    ) -> List[Dict]:
        """
        List runners with caching
        
        Args:
            repo: Repository name (None for org/user level)
            owner: Repository owner
            use_cache: Whether to use cache
        """
        return self._run_async_from_sync(self.list_runners_async(repo, owner, use_cache))

    async def list_runners_async(
        self,
        repo: Optional[str] = None,
        owner: Optional[str] = None,
        use_cache: bool = True,
    ) -> List[Dict]:
        """Async version of list_runners()."""

        cache_key = f"runners:{owner}/{repo}" if repo else f"runners:{owner}"

        if not use_cache:
            return self.gh.list_runners(repo, owner)

        cached = self.cache.get(cache_key)
        if cached is not None:
            logger.info(f"Cache hit: {cache_key} (saved API call)")
            return cached

        logger.info(f"Cache miss: {cache_key} (calling GitHub API)")
        runners = self.gh.list_runners(repo, owner)

        # Cache for 5 minutes
        await self.cache.set(cache_key, runners, ttl=300)
        return runners
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        return self.cache.get_stats()
    
    def invalidate_cache(self, pattern: Optional[str] = None):
        """
        Invalidate cache entries
        
        Args:
            pattern: If provided, only invalidate matching keys
        """
        if pattern:
            # Invalidate matching entries
            keys_to_remove = [k for k in self.cache.local_cache.keys() if pattern in k]
            for key in keys_to_remove:
                del self.cache.local_cache[key]
            logger.info(f"Invalidated {len(keys_to_remove)} cache entries matching '{pattern}'")
        else:
            # Clear all
            self.cache.local_cache.clear()
            logger.info("Cleared all cache entries")
        
        self.cache._save_cache()
    
    # Pass through methods that don't need caching
    def __getattr__(self, name):
        """Forward non-cached methods to underlying GitHubCLI"""
        return getattr(self.gh, name)


async def start_cache_network(
    listen_port: int = 9000,
    bootstrap_peers: Optional[List[str]] = None
):
    """
    Start the distributed cache P2P network
    
    Args:
        listen_port: Port to listen on
        bootstrap_peers: List of peer addresses to connect to
    """
    from .distributed_cache import initialize_cache
    
    cache = await initialize_cache(
        listen_port=listen_port,
        bootstrap_peers=bootstrap_peers
    )
    
    logger.info("Distributed cache network started")
    logger.info(f"  Peer ID: {cache.peer_id}")
    logger.info(f"  Listening on port: {listen_port}")
    logger.info(f"  Bootstrap peers: {len(bootstrap_peers) if bootstrap_peers else 0}")
    
    return cache
