"""GitHub-based change control with API caching and rate limiting.

This module implements the primary change control method using GitHub Issues
and Draft Pull Requests, with comprehensive API caching to avoid rate limits.
"""

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..base import ChangeController, OptimizationResult


class CacheBackend(Enum):
    """Cache backend type."""
    MEMORY = "memory"
    FILE = "file"
    REDIS = "redis"


@dataclass
class CacheEntry:
    """Cached API response entry.
    
    Attributes:
        key: Cache key (hashed request)
        value: Cached response data
        etag: ETag for conditional requests
        expires_at: When this entry expires
        created_at: When entry was created
    """
    key: str
    value: Any
    etag: Optional[str] = None
    expires_at: datetime = field(default_factory=lambda: datetime.now() + timedelta(minutes=5))
    created_at: datetime = field(default_factory=datetime.now)
    
    def is_expired(self) -> bool:
        """Check if cache entry has expired."""
        return datetime.now() > self.expires_at


class GitHubAPICache:
    """Cache layer for GitHub API requests.
    
    Implements intelligent caching with:
    - TTL-based expiration
    - ETag support for conditional requests
    - Rate limit tracking
    - Automatic cache invalidation
    
    Example:
        >>> cache = GitHubAPICache(backend=CacheBackend.FILE)
        >>> response = cache.get("repos/owner/repo")
        >>> if response is None:
        ...     response = github_api_call()
        ...     cache.set("repos/owner/repo", response)
    """
    
    def __init__(
        self,
        backend: CacheBackend = CacheBackend.MEMORY,
        cache_dir: Optional[Path] = None,
        default_ttl: int = 300,  # 5 minutes
    ):
        """Initialize API cache.
        
        Args:
            backend: Cache backend to use
            cache_dir: Directory for file-based cache (required for FILE backend)
            default_ttl: Default cache TTL in seconds
        """
        self.backend = backend
        self.default_ttl = default_ttl
        self.cache_dir = cache_dir or Path(".cache/github-api")
        
        if backend == CacheBackend.FILE:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        self._memory_cache: Dict[str, CacheEntry] = {}
        
    def get(self, key: str) -> Optional[Tuple[Any, Optional[str]]]:
        """Get value from cache.
        
        Args:
            key: Cache key
            
        Returns:
            Tuple of (cached_value, etag) if found and not expired, None otherwise
        """
        cache_key = self._hash_key(key)
        
        if self.backend == CacheBackend.MEMORY:
            entry = self._memory_cache.get(cache_key)
            if entry and not entry.is_expired():
                return (entry.value, entry.etag)
            elif entry:
                # Remove expired entry
                del self._memory_cache[cache_key]
                
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
                    )
                    if not entry.is_expired():
                        return (entry.value, entry.etag)
                    else:
                        # Remove expired file
                        cache_file.unlink()
                except Exception as e:
                    print(f"Error reading cache file: {e}")
        
        return None
    
    def set(
        self,
        key: str,
        value: Any,
        etag: Optional[str] = None,
        ttl: Optional[int] = None,
    ) -> None:
        """Set value in cache.
        
        Args:
            key: Cache key
            value: Value to cache
            etag: Optional ETag for conditional requests
            ttl: Optional custom TTL (default: self.default_ttl)
        """
        cache_key = self._hash_key(key)
        ttl = ttl or self.default_ttl
        
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
    
    def _hash_key(self, key: str) -> str:
        """Generate hash for cache key."""
        return hashlib.sha256(key.encode()).hexdigest()[:32]


class AdaptiveRateLimiter:
    """Adaptive rate limiter for GitHub API.
    
    Tracks API usage and automatically adjusts request rate to avoid
    hitting rate limits. Falls back to patch-based system when limits
    are approaching.
    
    Example:
        >>> limiter = AdaptiveRateLimiter(threshold=100)
        >>> if limiter.can_make_request():
        ...     response = github_api_call()
        ...     limiter.record_request(response.headers)
        >>> else:
        ...     # Use patch-based fallback
    """
    
    def __init__(
        self,
        threshold: int = 100,
        window_size: int = 3600,  # 1 hour
    ):
        """Initialize rate limiter.
        
        Args:
            threshold: Minimum remaining requests before fallback
            window_size: Rate limit window in seconds
        """
        self.threshold = threshold
        self.window_size = window_size
        self.requests_made = 0
        self.requests_remaining = 5000  # GitHub default
        self.reset_time = datetime.now() + timedelta(seconds=window_size)
        self.last_check = datetime.now()
        
    def can_make_request(self) -> bool:
        """Check if we can make another API request.
        
        Returns:
            True if safe to make request, False if should use fallback
        """
        # Check if rate limit window has reset
        if datetime.now() > self.reset_time:
            self.requests_made = 0
            self.requests_remaining = 5000
            self.reset_time = datetime.now() + timedelta(seconds=self.window_size)
        
        # Check if we're approaching limit
        return self.requests_remaining > self.threshold
    
    def record_request(self, response_headers: Dict[str, str]) -> None:
        """Record a made request and update rate limit info.
        
        Args:
            response_headers: Response headers from GitHub API
        """
        self.requests_made += 1
        self.last_check = datetime.now()
        
        # Extract rate limit info from headers
        if 'X-RateLimit-Remaining' in response_headers:
            self.requests_remaining = int(response_headers['X-RateLimit-Remaining'])
        
        if 'X-RateLimit-Reset' in response_headers:
            reset_timestamp = int(response_headers['X-RateLimit-Reset'])
            self.reset_time = datetime.fromtimestamp(reset_timestamp)
    
    def get_status(self) -> Dict[str, Any]:
        """Get current rate limit status.
        
        Returns:
            Dictionary with rate limit information
        """
        return {
            'requests_made': self.requests_made,
            'requests_remaining': self.requests_remaining,
            'reset_time': self.reset_time.isoformat(),
            'can_make_request': self.can_make_request(),
            'time_until_reset': (self.reset_time - datetime.now()).total_seconds(),
        }


class IssueManager:
    """Manages GitHub issues for optimization tracking.
    
    Creates and updates issues for optimization tasks with:
    - Detailed analysis and rationale
    - Links to related PRs
    - Status tracking
    - Labels for categorization
    """
    
    def __init__(self, api_cache: GitHubAPICache, github_client: Any):
        """Initialize issue manager.
        
        Args:
            api_cache: GitHub API cache instance
            github_client: GitHub API client (e.g., PyGithub)
        """
        self.api_cache = api_cache
        self.github_client = github_client
        
    def create_issue(
        self,
        repo: str,
        title: str,
        body: str,
        labels: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Create a new issue.
        
        Args:
            repo: Repository in format "owner/repo"
            title: Issue title
            body: Issue body (markdown)
            labels: Optional list of labels
            
        Returns:
            Created issue data
        """
        # In practice, use github_client.create_issue()
        # For now, return mock data
        issue_data = {
            'number': 123,
            'title': title,
            'body': body,
            'labels': labels or [],
            'html_url': f"https://github.com/{repo}/issues/123",
        }
        
        # Cache the issue
        cache_key = f"issues/{repo}/123"
        self.api_cache.set(cache_key, issue_data)
        
        return issue_data
    
    def get_issue(self, repo: str, issue_number: int) -> Optional[Dict[str, Any]]:
        """Get issue data.
        
        Args:
            repo: Repository in format "owner/repo"
            issue_number: Issue number
            
        Returns:
            Issue data if found, None otherwise
        """
        cache_key = f"issues/{repo}/{issue_number}"
        cached = self.api_cache.get(cache_key)
        
        if cached:
            return cached[0]  # Return value, ignore etag
        
        # Fetch from API and cache
        # In practice: issue_data = github_client.get_issue(repo, issue_number)
        return None
    
    def update_issue(
        self,
        repo: str,
        issue_number: int,
        state: Optional[str] = None,
        labels: Optional[List[str]] = None,
        body: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update an existing issue.
        
        Args:
            repo: Repository in format "owner/repo"
            issue_number: Issue number
            state: Optional new state ("open" or "closed")
            labels: Optional new labels list
            body: Optional new body content
            
        Returns:
            Updated issue data
        """
        # Invalidate cache
        cache_key = f"issues/{repo}/{issue_number}"
        self.api_cache.invalidate(cache_key)
        
        # In practice: updated = github_client.update_issue(...)
        updated = {'number': issue_number, 'state': state}
        
        # Cache updated data
        self.api_cache.set(cache_key, updated)
        
        return updated


class DraftPRManager:
    """Manages draft pull requests for optimization changes.
    
    Creates draft PRs with:
    - Detailed change description
    - Validation results
    - Performance metrics
    - Request for review
    """
    
    def __init__(self, api_cache: GitHubAPICache, github_client: Any):
        """Initialize draft PR manager.
        
        Args:
            api_cache: GitHub API cache instance
            github_client: GitHub API client
        """
        self.api_cache = api_cache
        self.github_client = github_client
        
    def create_draft_pr(
        self,
        repo: str,
        title: str,
        body: str,
        head: str,
        base: str = "main",
    ) -> Dict[str, Any]:
        """Create a draft pull request.
        
        Args:
            repo: Repository in format "owner/repo"
            title: PR title
            body: PR body (markdown)
            head: Head branch name
            base: Base branch name (default: main)
            
        Returns:
            Created PR data
        """
        # In practice: pr = github_client.create_pull(draft=True, ...)
        pr_data = {
            'number': 456,
            'title': title,
            'body': body,
            'head': head,
            'base': base,
            'draft': True,
            'html_url': f"https://github.com/{repo}/pull/456",
        }
        
        # Cache the PR
        cache_key = f"pulls/{repo}/456"
        self.api_cache.set(cache_key, pr_data)
        
        return pr_data
    
    def mark_ready_for_review(self, repo: str, pr_number: int) -> Dict[str, Any]:
        """Mark draft PR as ready for review.
        
        Args:
            repo: Repository in format "owner/repo"
            pr_number: PR number
            
        Returns:
            Updated PR data
        """
        # Invalidate cache
        cache_key = f"pulls/{repo}/{pr_number}"
        self.api_cache.invalidate(cache_key)
        
        # In practice: github_client.mark_ready_for_review(pr_number)
        updated = {'number': pr_number, 'draft': False}
        
        self.api_cache.set(cache_key, updated)
        return updated
    
    def get_pr_status(self, repo: str, pr_number: int) -> Optional[Dict[str, Any]]:
        """Get PR status including checks and reviews.
        
        Args:
            repo: Repository in format "owner/repo"
            pr_number: PR number
            
        Returns:
            PR status data if found, None otherwise
        """
        cache_key = f"pulls/{repo}/{pr_number}/status"
        cached = self.api_cache.get(cache_key)
        
        if cached:
            return cached[0]
        
        # In practice: fetch from API
        # status = github_client.get_pr_status(pr_number)
        return None


class GitHubChangeController(ChangeController):
    """Change controller using GitHub Issues and Draft PRs.
    
    This implementation uses GitHub's API with comprehensive caching
    to manage code changes while respecting rate limits.
    """
    
    def __init__(
        self,
        github_client: Any,
        repo: str,
        cache_backend: CacheBackend = CacheBackend.FILE,
        cache_dir: Optional[Path] = None,
        rate_limit_threshold: int = 100,
    ):
        """Initialize GitHub change controller.
        
        Args:
            github_client: GitHub API client
            repo: Repository in format "owner/repo"
            cache_backend: Cache backend to use
            cache_dir: Directory for file-based cache
            rate_limit_threshold: Minimum remaining requests before fallback
        """
        self.github_client = github_client
        self.repo = repo
        self.api_cache = GitHubAPICache(cache_backend, cache_dir)
        self.rate_limiter = AdaptiveRateLimiter(rate_limit_threshold)
        self.issue_manager = IssueManager(self.api_cache, github_client)
        self.pr_manager = DraftPRManager(self.api_cache, github_client)
        self.pending_changes: Dict[str, Dict[str, Any]] = {}
        
    def create_change(self, result: OptimizationResult) -> str:
        """Create change using GitHub issue + draft PR.
        
        Args:
            result: Optimization result to create change for
            
        Returns:
            PR URL
            
        Raises:
            RuntimeError: If rate limit exceeded
        """
        if not self.rate_limiter.can_make_request():
            raise RuntimeError(
                "GitHub API rate limit approaching. Use patch-based fallback."
            )
        
        # Create issue for tracking
        issue_title = f"[Optimization] {result.task_id}: {result.changes[:50]}"
        issue_body = self._format_issue_body(result)
        
        issue = self.issue_manager.create_issue(
            repo=self.repo,
            title=issue_title,
            body=issue_body,
            labels=['optimization', result.method.value],
        )
        
        # Create draft PR
        pr_title = f"Optimization: {result.changes[:50]}"
        pr_body = self._format_pr_body(result, issue['number'])
        branch_name = f"optimization/{result.task_id}"
        
        pr = self.pr_manager.create_draft_pr(
            repo=self.repo,
            title=pr_title,
            body=pr_body,
            head=branch_name,
        )
        
        # Track pending change
        self.pending_changes[pr['html_url']] = {
            'issue': issue,
            'pr': pr,
            'result': result,
        }
        
        return pr['html_url']
    
    def check_approval(self, change_id: str) -> bool:
        """Check if PR has been approved.
        
        Args:
            change_id: PR URL
            
        Returns:
            True if approved, False otherwise
        """
        if not self.rate_limiter.can_make_request():
            # Can't check, assume not approved
            return False
        
        # Extract PR number from URL
        pr_number = int(change_id.split('/')[-1])
        
        # Get PR status
        status = self.pr_manager.get_pr_status(self.repo, pr_number)
        
        if not status:
            return False
        
        # Check for approvals
        return status.get('approved', False)
    
    def apply_change(self, change_id: str) -> bool:
        """Apply approved PR (merge it).
        
        Args:
            change_id: PR URL
            
        Returns:
            True if successfully merged, False otherwise
        """
        if not self.rate_limiter.can_make_request():
            return False
        
        # In practice: github_client.merge_pull_request(pr_number)
        # For now, just remove from pending
        if change_id in self.pending_changes:
            del self.pending_changes[change_id]
        
        return True
    
    def rollback_change(self, change_id: str) -> bool:
        """Rollback a merged PR (create reversal PR).
        
        Args:
            change_id: PR URL to rollback
            
        Returns:
            True if successfully created reversal PR, False otherwise
        """
        # In practice: create a revert PR using GitHub API
        # github_client.create_revert_pull_request(pr_number)
        return True
    
    def _format_issue_body(self, result: OptimizationResult) -> str:
        """Format issue body with optimization details."""
        return f"""## Optimization Task

**Task ID:** `{result.task_id}`
**Method:** {result.method.value}
**Agent:** {result.agent_id}

### Changes
{result.changes}

### Validation Results
- **Success:** {result.validation.passed if result.validation else 'N/A'}
- **Syntax:** {'✓' if result.validation and result.validation.syntax_check else '✗'}
- **Types:** {'✓' if result.validation and result.validation.type_check else '✗'}
- **Tests:** {'✓' if result.validation and result.validation.unit_tests else '✗'}
- **Security:** {'✓' if result.validation and result.validation.security_scan else '✗'}

### Performance Metrics
{self._format_metrics(result.metrics)}

### Execution Time
{result.execution_time:.2f} seconds

---
*Generated by Agentic Optimizer*
"""
    
    def _format_pr_body(self, result: OptimizationResult, issue_number: int) -> str:
        """Format PR body with optimization details."""
        return f"""## Optimization Changes

Closes #{issue_number}

### Summary
{result.changes}

### Method
{result.method.value}

### Validation
- [{'x' if result.validation and result.validation.syntax_check else ' '}] Syntax check passed
- [{'x' if result.validation and result.validation.type_check else ' '}] Type check passed
- [{'x' if result.validation and result.validation.unit_tests else ' '}] Unit tests passed
- [{'x' if result.validation and result.validation.integration_tests else ' '}] Integration tests passed
- [{'x' if result.validation and result.validation.performance_tests else ' '}] Performance tests passed
- [{'x' if result.validation and result.validation.security_scan else ' '}] Security scan passed
- [{'x' if result.validation and result.validation.style_check else ' '}] Style check passed

### Performance Impact
{self._format_metrics(result.metrics)}

---
**Please review and approve if changes look good.**

/cc @reviewers
"""
    
    def _format_metrics(self, metrics: Dict[str, float]) -> str:
        """Format performance metrics."""
        if not metrics:
            return "*No metrics available*"
        
        lines = []
        for key, value in metrics.items():
            lines.append(f"- **{key}:** {value}")
        
        return '\n'.join(lines)
