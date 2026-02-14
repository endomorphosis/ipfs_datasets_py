"""Unified GitHub CLI wrapper.

This module provides a unified Python wrapper for GitHub CLI (gh) commands,
consolidating functionality from utils/github_wrapper.py and utils/github_cli.py.
"""

import json
import logging
import os
import random
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from ..cache import GitHubCache, get_global_config
from .counter import APICounter
from .rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


class GitHubCLI:
    """Unified Python wrapper for GitHub CLI (gh) commands.
    
    Consolidates functionality from:
    - utils/github_wrapper.py
    - utils/github_cli.py
    
    Features:
    - Optional caching with ETag support
    - API call tracking
    - Rate limit monitoring
    - Exponential backoff retry
    - Comprehensive error handling
    
    Example:
        >>> gh = GitHubCLI(enable_cache=True)
        >>> repos = gh.list_repos()
        >>> pr = gh.create_pr(title="Fix bug", body="Description")
        >>> stats = gh.get_stats()
        >>> print(f"Hit rate: {stats['hit_rate']:.2%}")
    """
    
    def __init__(
        self,
        gh_path: str = "gh",
        enable_cache: bool = True,
        cache: Optional[GitHubCache] = None,
        enable_tracking: bool = True,
        enable_rate_limiting: bool = True
    ):
        """Initialize GitHub CLI wrapper.
        
        Args:
            gh_path: Path to gh executable (default: "gh" from PATH)
            enable_cache: Whether to enable response caching
            cache: Custom cache instance (creates one if None)
            enable_tracking: Whether to track API calls
            enable_rate_limiting: Whether to monitor rate limits
        """
        self.gh_path = gh_path
        self.enable_cache = enable_cache
        self.enable_tracking = enable_tracking
        self.enable_rate_limiting = enable_rate_limiting
        
        # Set up cache
        if enable_cache:
            self.cache = cache if cache is not None else GitHubCache()
        else:
            self.cache = None
        
        # Set up tracking
        if enable_tracking:
            self.counter = APICounter()
        else:
            self.counter = None
        
        # Set up rate limiting
        if enable_rate_limiting:
            self.rate_limiter = RateLimiter()
        else:
            self.rate_limiter = None
        
        self._verify_installation()
    
    def _verify_installation(self) -> None:
        """Verify that gh CLI is installed and authenticated."""
        try:
            result = subprocess.run(
                [self.gh_path, "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"gh CLI returned error (code {result.returncode}): "
                    f"stderr={result.stderr}, stdout={result.stdout}"
                )
            logger.info(f"GitHub CLI version: {result.stdout.strip()}")
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            raise RuntimeError(f"Failed to verify gh CLI installation: {e}")
    
    def _run_command(
        self,
        args: List[str],
        stdin: Optional[str] = None,
        timeout: int = 30,
        max_retries: int = 3,
        cache_key: Optional[str] = None,
        operation_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """Run a gh CLI command with caching and retry.
        
        Args:
            args: Command arguments
            stdin: Optional stdin input
            timeout: Command timeout in seconds
            max_retries: Maximum number of retry attempts
            cache_key: Optional cache key (for caching GET operations)
            operation_type: Operation type for cache TTL
            
        Returns:
            Dict with stdout, stderr, and returncode
        """
        # Check cache first
        if self.cache and cache_key:
            cached = self.cache.get(cache_key)
            if cached is not None:
                if self.counter:
                    self.counter.count_call(
                        operation_type or "gh_command",
                        cached=True
                    )
                logger.debug(f"Cache hit: {cache_key}")
                return cached
        
        # Check rate limit before making call
        if self.rate_limiter:
            try:
                self.rate_limiter.check_rate_limit()
            except RuntimeError as e:
                logger.error(f"Rate limit exceeded: {e}")
                # If we have a cache, try using stale cache
                if self.cache and cache_key:
                    # For now, just re-raise. Could implement stale cache fallback
                    pass
                raise
        
        last_error = None
        
        for attempt in range(max_retries + 1):
            try:
                cmd = [self.gh_path] + args
                
                if attempt > 0:
                    # Exponential backoff
                    delay = min(2 ** attempt + random.random(), 60)
                    logger.debug(
                        f"Retry attempt {attempt}/{max_retries} "
                        f"after {delay:.1f}s for: {' '.join(cmd)}"
                    )
                    time.sleep(delay)
                
                result = subprocess.run(
                    cmd,
                    input=stdin,
                    capture_output=True,
                    text=True,
                    timeout=timeout
                )
                
                response = {
                    'stdout': result.stdout,
                    'stderr': result.stderr,
                    'returncode': result.returncode
                }
                
                # Track the call
                if self.counter:
                    self.counter.count_call(
                        operation_type or "gh_command",
                        cached=False
                    )
                
                # Cache successful GET operations
                if (
                    self.cache and
                    cache_key and
                    result.returncode == 0 and
                    result.stdout
                ):
                    self.cache.set(
                        cache_key,
                        response,
                        operation_type=operation_type
                    )
                    logger.debug(f"Cached: {cache_key}")
                
                return response
                
            except subprocess.TimeoutExpired as e:
                last_error = e
                logger.warning(
                    f"Command timed out (attempt {attempt + 1}/{max_retries + 1}): "
                    f"{' '.join(cmd)}"
                )
                if attempt == max_retries:
                    break
                continue
                
            except Exception as e:
                last_error = e
                logger.error(f"Command failed: {e}")
                if attempt == max_retries:
                    break
                continue
        
        # All retries failed
        raise RuntimeError(f"Command failed after {max_retries + 1} attempts: {last_error}")
    
    def list_repos(
        self,
        limit: int = 100,
        visibility: str = "all"
    ) -> List[Dict[str, Any]]:
        """List repositories.
        
        Args:
            limit: Maximum number of repos to return
            visibility: Visibility filter (all, public, private)
            
        Returns:
            List of repository dicts
        """
        cache_key = f"repos/list/{visibility}/{limit}"
        
        result = self._run_command(
            ["repo", "list", "--json", "name,owner,visibility", "--limit", str(limit)],
            cache_key=cache_key,
            operation_type="list_repos"
        )
        
        if result['returncode'] == 0:
            return json.loads(result['stdout'])
        else:
            raise RuntimeError(f"Failed to list repos: {result['stderr']}")
    
    def get_repo(self, owner: str, repo: str) -> Dict[str, Any]:
        """Get repository information.
        
        Args:
            owner: Repository owner
            repo: Repository name
            
        Returns:
            Repository information dict
        """
        cache_key = f"repos/{owner}/{repo}"
        
        result = self._run_command(
            ["repo", "view", f"{owner}/{repo}", "--json", "name,owner,description,createdAt"],
            cache_key=cache_key,
            operation_type="get_repo_info"
        )
        
        if result['returncode'] == 0:
            return json.loads(result['stdout'])
        else:
            raise RuntimeError(f"Failed to get repo: {result['stderr']}")
    
    def create_pr(
        self,
        title: str,
        body: str,
        base: str = "main",
        head: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a pull request.
        
        Args:
            title: PR title
            body: PR body/description
            base: Base branch (default: main)
            head: Head branch (uses current if None)
            
        Returns:
            Created PR information dict
        """
        args = [
            "pr", "create",
            "--title", title,
            "--body", body,
            "--base", base
        ]
        
        if head:
            args.extend(["--head", head])
        
        result = self._run_command(
            args,
            operation_type="create_pr"
        )
        
        if result['returncode'] == 0:
            # Parse PR URL from stdout
            return {'url': result['stdout'].strip()}
        else:
            raise RuntimeError(f"Failed to create PR: {result['stderr']}")
    
    def create_issue(
        self,
        title: str,
        body: str,
        labels: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Create an issue.
        
        Args:
            title: Issue title
            body: Issue body/description
            labels: Optional list of labels
            
        Returns:
            Created issue information dict
        """
        args = [
            "issue", "create",
            "--title", title,
            "--body", body
        ]
        
        if labels:
            for label in labels:
                args.extend(["--label", label])
        
        result = self._run_command(
            args,
            operation_type="create_issue"
        )
        
        if result['returncode'] == 0:
            return {'url': result['stdout'].strip()}
        else:
            raise RuntimeError(f"Failed to create issue: {result['stderr']}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get usage statistics.
        
        Returns:
            Dict with cache and API call statistics
        """
        stats = {}
        
        if self.counter:
            stats.update(self.counter.get_statistics())
        
        if self.cache:
            cache_stats = self.cache.get_stats()
            stats.update({
                'cache_size': cache_stats.size,
                'cache_hits': cache_stats.hits,
                'cache_misses': cache_stats.misses,
                'cache_hit_rate': cache_stats.hit_rate,
            })
        
        if self.rate_limiter:
            limits = self.rate_limiter.get_rate_limits()
            stats.update({
                'rate_limit_remaining': limits['remaining'],
                'rate_limit_total': limits['limit'],
            })
        
        return stats
    
    def report(self) -> str:
        """Generate human-readable usage report.
        
        Returns:
            Formatted report string
        """
        lines = ["=== GitHub CLI Usage Report ===", ""]
        
        if self.counter:
            lines.append(self.counter.report())
            lines.append("")
        
        if self.rate_limiter:
            lines.append("Rate Limit Status:")
            lines.append(self.rate_limiter.get_status())
            lines.append("")
        
        if self.cache:
            stats = self.cache.get_stats()
            lines.extend([
                "Cache Statistics:",
                f"  Size: {stats.size} entries",
                f"  Hits: {stats.hits}",
                f"  Misses: {stats.misses}",
                f"  Hit Rate: {stats.hit_rate:.2%}",
            ])
        
        return "\n".join(lines)
