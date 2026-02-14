"""Unified GitHub API integration with caching, rate limiting, and call tracking.

DEPRECATED: This module is being phased out in favor of:
- ipfs_datasets_py.utils.cache for caching functionality
- ipfs_datasets_py.utils.github for GitHub operations

This module now re-exports from the unified utils modules while maintaining
backward compatibility for existing optimizer code.

Original functionality consolidated from:
- optimizers/agentic/github_control.py (GitHubAPICache, AdaptiveRateLimiter)
- .github/scripts/github_api_counter.py (API call tracking)

Provides a single source of truth for all GitHub API interactions used by:
- Optimizer workflows (agentic optimization)
- GitHub Actions workflows (.github/workflows/)
- Workflow helper scripts (.github/scripts/)
"""

import logging
import warnings
from pathlib import Path
from typing import Any, Dict, Optional

# Import from unified utils modules
from ...utils.cache import CacheBackend, CacheEntry, GitHubCache
from ...utils.github import APICounter

logger = logging.getLogger(__name__)

# Issue deprecation warning
warnings.warn(
    "optimizers.agentic.github_api_unified is deprecated. "
    "Use ipfs_datasets_py.utils.cache.GitHubCache and "
    "ipfs_datasets_py.utils.github.APICounter instead.",
    DeprecationWarning,
    stacklevel=2
)



class UnifiedGitHubAPICache:
    """Unified GitHub API cache with call tracking and statistics.
    
    DEPRECATED: Use GitHubCache from utils.cache and APICounter from utils.github instead.
    
    This is a compatibility wrapper that combines GitHubCache and APICounter
    to maintain backward compatibility with existing optimizer code.
    
    Example:
        >>> # New recommended approach:
        >>> from ipfs_datasets_py.utils.cache import GitHubCache
        >>> from ipfs_datasets_py.utils.github import APICounter
        >>> cache = GitHubCache()
        >>> counter = APICounter()
        
        >>> # Old approach (deprecated but still works):
        >>> cache = UnifiedGitHubAPICache()
    """
    
    def __init__(
        self,
        backend = None,  # Ignored, uses GitHubCache defaults
        cache_dir: Optional[Path] = None,
        default_ttl: int = 300,
        config_file: Optional[Path] = None,
    ):
        """Initialize unified GitHub API cache.
        
        Args:
            backend: DEPRECATED - Ignored, GitHubCache handles backend selection
            cache_dir: DEPRECATED - Configured via .github/cache-config.yml
            default_ttl: Default cache TTL in seconds
            config_file: Optional cache-config.yml file path
        """
        # Use new unified modules
        self._github_cache = GitHubCache(
            maxsize=5000,
            default_ttl=default_ttl,
            config_file=str(config_file) if config_file else None
        )
        self._api_counter = APICounter()
        
        # Store config for backward compatibility
        self.default_ttl = default_ttl
        self.cache_dir = cache_dir or Path(".cache/github-api")
    
    def get(self, key: str, operation_type: Optional[str] = None) -> Optional[Tuple[Any, Optional[str]]]:
        """Get value from cache.
        
        Args:
            key: Cache key
            operation_type: Optional operation type for TTL lookup
            
        Returns:
            Tuple of (cached_value, etag) if found and not expired, None otherwise
        """
        cache_key = self._hash_key(key)
        
        if self.backend == CacheBackend.MEMORY:
            entry = self._memory_cache.get(cache_key)
            if entry and not entry.is_expired():
                entry.access_count += 1
                entry.last_accessed = datetime.now()
                self.cache_hits += 1
                return (entry.value, entry.etag)
            elif entry:
                # Remove expired entry
                del self._memory_cache[cache_key]
                self.cache_misses += 1
                
        elif self.backend == CacheBackend.FILE:
            cache_file = self.cache_dir / f"{cache_key}.json"
            if cache_file.exists():
                try:
                    data = json.loads(cache_file.read_text())
                    entry = CacheEntry(
                        key=cache_key,
                        value=data['value'],
                        etag=data.get('etag'),
                        expires_at=datetime.fromisoformat(data['expires_at']),
                        created_at=datetime.fromisoformat(data['created_at']),
                        access_count=data.get('access_count', 0) + 1,
                        last_accessed=datetime.now(),
                    )
                    if not entry.is_expired():
                        self.cache_hits += 1
                        # Update access stats
                        data['access_count'] = entry.access_count
                        data['last_accessed'] = entry.last_accessed.isoformat()
                        cache_file.write_text(json.dumps(data, indent=2))
                        return (entry.value, entry.etag)
                    else:
                        # Remove expired file
                        cache_file.unlink()
                        self.cache_misses += 1
                except Exception as e:
                    logger.error(f"Error reading cache file: {e}")
                    self.cache_misses += 1
            else:
                self.cache_misses += 1
        
        return None
    
    def set(
        self,
        key: str,
        value: Any,
        etag: Optional[str] = None,
        ttl: Optional[int] = None,
        operation_type: Optional[str] = None,
    ) -> None:
        """Set value in cache.
        
        Args:
            key: Cache key
            value: Value to cache
            etag: Optional ETag for conditional requests
            ttl: Optional custom TTL (overrides operation_type and default)
            operation_type: Optional operation type for TTL lookup
        """
        cache_key = self._hash_key(key)
        
        # Determine TTL: explicit > operation_type > default
        if ttl is None:
            if operation_type and operation_type in self.OPERATION_TTLS:
                ttl = self.OPERATION_TTLS[operation_type]
            else:
                ttl = self.default_ttl
        
        entry = CacheEntry(
            key=cache_key,
            value=value,
            etag=etag,
            expires_at=datetime.now() + timedelta(seconds=ttl),
        )
        
        if self.backend == CacheBackend.MEMORY:
            self._memory_cache[cache_key] = entry
            
        elif self.backend == CacheBackend.FILE:
            cache_file = self.cache_dir / f"{cache_key}.json"
            data = {
                'value': value,
                'etag': etag,
                'expires_at': entry.expires_at.isoformat(),
                'created_at': entry.created_at.isoformat(),
                'access_count': entry.access_count,
                'last_accessed': entry.last_accessed.isoformat(),
            }
            cache_file.write_text(json.dumps(data, indent=2))
    
    def invalidate(self, key: str) -> None:
        """Invalidate cache entry.
        
        Args:
            key: Cache key to invalidate
        """
        cache_key = self._hash_key(key)
        
        if self.backend == CacheBackend.MEMORY:
            self._memory_cache.pop(cache_key, None)
            
        elif self.backend == CacheBackend.FILE:
            cache_file = self.cache_dir / f"{cache_key}.json"
            if cache_file.exists():
                cache_file.unlink()
    
    def clear(self) -> None:
        """Clear all cache entries."""
        if self.backend == CacheBackend.MEMORY:
            self._memory_cache.clear()
            
        elif self.backend == CacheBackend.FILE:
            for cache_file in self.cache_dir.glob("*.json"):
                cache_file.unlink()
    
    def count_api_call(
        self,
        call_type: str,
        count: int = 1,
        metadata: Optional[Dict] = None,
        cached: bool = False,
    ) -> None:
        """Count an API call.
        
        Args:
            call_type: Type of API call
            count: Number of calls (default 1)
            metadata: Additional metadata about the call
            cached: Whether this call was served from cache
        """
        self.call_counts[call_type] = self.call_counts.get(call_type, 0) + count
        
        record = APICallRecord(
            call_type=call_type,
            count=count,
            timestamp=datetime.now(),
            metadata=metadata or {},
            cached=cached,
        )
        self.call_records.append(record)
        
        logger.debug(f"Counted {count} {call_type} call(s) {'(cached)' if cached else ''}")
    
    def detect_command_type(self, command: List[str]) -> str:
        """Detect the type of GitHub command being run.
        
        Args:
            command: Command list
        
        Returns:
            Command type identifier
        """
        cmd_str = ' '.join(command)
        
        # GitHub CLI commands
        patterns = {
            'gh pr list': 'gh_pr_list',
            'gh pr view': 'gh_pr_view',
            'gh pr create': 'gh_pr_create',
            'gh pr comment': 'gh_pr_comment',
            'gh pr edit': 'gh_pr_edit',
            'gh pr close': 'gh_pr_close',
            'gh pr merge': 'gh_pr_merge',
            'gh issue list': 'gh_issue_list',
            'gh issue view': 'gh_issue_view',
            'gh issue create': 'gh_issue_create',
            'gh issue comment': 'gh_issue_comment',
            'gh issue edit': 'gh_issue_edit',
            'gh issue close': 'gh_issue_close',
            'gh run list': 'gh_run_list',
            'gh run view': 'gh_run_view',
            'gh run download': 'gh_run_download',
            'gh repo view': 'gh_repo_view',
            'gh repo list': 'gh_repo_list',
            'gh workflow view': 'gh_workflow_view',
            'gh workflow run': 'gh_workflow_run',
            'gh release list': 'gh_release_list',
            'gh release view': 'gh_release_view',
            'gh release create': 'gh_release_create',
            'gh api': 'gh_api',
        }
        
        for pattern, cmd_type in patterns.items():
            if pattern in cmd_str:
                return cmd_type
        
        # Generic gh command
        return 'gh_api'
    
    def run_gh_command(
        self,
        command: List[str],
        timeout: int = 60,
        check: bool = True,
        **kwargs
    ) -> subprocess.CompletedProcess:
        """Run a GitHub CLI command and count the API call.
        
        Args:
            command: Command to run
            timeout: Timeout in seconds
            check: Whether to raise on non-zero exit
            **kwargs: Additional arguments for subprocess.run
        
        Returns:
            CompletedProcess instance
        """
        # Detect command type and count it
        cmd_type = self.detect_command_type(command)
        self.count_api_call(cmd_type, 1, {'command': ' '.join(command)})
        
        # Run the command
        logger.info(f"Running GitHub command: {' '.join(command)}")
        result = subprocess.run(
            command,
            timeout=timeout,
            check=check,
            capture_output=True,
            text=True,
            **kwargs
        )
        
        return result
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get cache and API call statistics.
        
        Returns:
            Dictionary with statistics:
            - total_api_calls: Total API calls made
            - cache_hits: Number of cache hits
            - cache_misses: Number of cache misses
            - hit_rate: Cache hit rate (0-1)
            - calls_by_type: API calls broken down by type
            - cached_calls: Number of calls served from cache
            - total_cost: Estimated total API cost
        """
        total_calls = sum(self.call_counts.values())
        total_cache = self.cache_hits + self.cache_misses
        hit_rate = self.cache_hits / total_cache if total_cache > 0 else 0
        
        cached_calls = sum(1 for r in self.call_records if r.cached)
        
        # Estimate total API cost
        total_cost = sum(
            count * self.API_COSTS.get(call_type, 1)
            for call_type, count in self.call_counts.items()
        )
        
        return {
            'total_api_calls': total_calls,
            'cache_hits': self.cache_hits,
            'cache_misses': self.cache_misses,
            'hit_rate': hit_rate,
            'calls_by_type': dict(self.call_counts),
            'cached_calls': cached_calls,
            'total_cost': total_cost,
            'workflow_run_id': self.workflow_run_id,
            'workflow_name': self.workflow_name,
            'duration_seconds': (datetime.now() - self.start_time).total_seconds(),
        }
    
    def save_metrics(self, file_path: Optional[Path] = None) -> None:
        """Save metrics to file.
        
        Args:
            file_path: Optional custom file path (defaults to metrics_file)
        """
        file_path = file_path or self.metrics_file
        
        stats = self.get_statistics()
        stats['call_records'] = [
            {
                'call_type': r.call_type,
                'count': r.count,
                'timestamp': r.timestamp.isoformat(),
                'metadata': r.metadata,
                'cached': r.cached,
            }
            for r in self.call_records
        ]
        
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, 'w') as f:
            json.dump(stats, f, indent=2)
        
        logger.info(f"Saved metrics to {file_path}")
    
    def report(self) -> str:
        """Generate a human-readable report.
        
        Returns:
            Formatted report string
        """
        stats = self.get_statistics()
        
        lines = [
            "=" * 60,
            "GitHub API Usage Report",
            "=" * 60,
            f"Workflow: {stats['workflow_name']}",
            f"Run ID: {stats['workflow_run_id']}",
            f"Duration: {stats['duration_seconds']:.1f}s",
            "",
            "API Calls:",
            f"  Total: {stats['total_api_calls']}",
            f"  Estimated Cost: {stats['total_cost']} requests",
            "",
            "Cache Performance:",
            f"  Hits: {stats['cache_hits']}",
            f"  Misses: {stats['cache_misses']}",
            f"  Hit Rate: {stats['hit_rate']:.2%}",
            f"  Cached Calls: {stats['cached_calls']}",
            "",
            "Calls by Type:",
        ]
        
        for call_type, count in sorted(stats['calls_by_type'].items(), key=lambda x: -x[1]):
            lines.append(f"  {call_type}: {count}")
        
        lines.append("=" * 60)
        
        return "\n".join(lines)
    
    def _hash_key(self, key: str) -> str:
        """Generate hash for cache key."""
        return hashlib.sha256(key.encode()).hexdigest()[:32]
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - save metrics."""
        self.save_metrics()
        return False


# Backward compatibility aliases
GitHubAPICache = UnifiedGitHubAPICache
GitHubAPICounter = UnifiedGitHubAPICache
