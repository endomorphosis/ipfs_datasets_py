# Unified GitHub Operations

This module provides unified GitHub operations consolidating functionality from multiple sources into a single, consistent API.

## Components

### GitHubCLI - Unified CLI Wrapper

Consolidates `github_wrapper.py` and `github_cli.py` into a single interface:

```python
from ipfs_datasets_py.utils.github import GitHubCLI

# Create client with caching and tracking
gh = GitHubCLI(enable_cache=True)

# List repositories
repos = gh.list_repos(limit=10)

# Get repository info
repo = gh.get_repo("owner", "repo")

# Create pull request
pr = gh.create_pr(
    title="Fix bug",
    body="Description",
    base="main"
)

# Create issue
issue = gh.create_issue(
    title="Bug report",
    body="Details",
    labels=["bug"]
)

# Get statistics
stats = gh.get_stats()
print(f"API calls: {stats['total_api_calls']}")
print(f"Cache hit rate: {stats['cache_hit_rate']:.2%}")

# Generate report
print(gh.report())
```

### APICounter - Call Tracking

Track GitHub API usage and export metrics:

```python
from ipfs_datasets_py.utils.github import APICounter

counter = APICounter()

# Count calls
counter.count_call("gh_pr_list", count=1, cached=False)
counter.count_call("gh_issue_view", count=5, cached=True)

# Run gh commands with tracking
result = counter.run_gh_command(['gh', 'pr', 'list'])

# Get statistics
stats = counter.get_statistics()
print(f"Total calls: {stats['total_api_calls']}")
print(f"Hit rate: {stats['hit_rate']:.2%}")

# Generate report
print(counter.report())

# Save metrics
counter.save_metrics()  # Saves to $RUNNER_TEMP/github_api_metrics_*.json
```

### RateLimiter - Rate Limit Management

Monitor and manage GitHub API rate limits:

```python
from ipfs_datasets_py.utils.github import RateLimiter

limiter = RateLimiter(
    warning_threshold=100,
    aggressive_threshold=50
)

# Check rate limit before operations
try:
    limiter.check_rate_limit()
except RuntimeError as e:
    print(f"Rate limit exhausted: {e}")

# Check if aggressive caching should be used
if limiter.should_cache_aggressively():
    # Use cache-first strategy
    pass

# Get status
print(limiter.get_status())

# Get detailed limits
limits = limiter.get_rate_limits()
print(f"Remaining: {limits['remaining']}/{limits['limit']}")
```

### GitHubCache - API-Specific Cache

Specialized cache for GitHub API responses (re-exported from `utils.cache`):

```python
from ipfs_datasets_py.utils.github import GitHubCache

cache = GitHubCache()

# Cache with ETag and operation-specific TTL
cache.set(
    "repos/owner/repo",
    response_data,
    etag="W/\"abc123\"",
    operation_type="get_repo_info"  # Uses configured TTL
)

# Get cached response
cached = cache.get("repos/owner/repo")

# Get ETag for conditional requests
etag = cache.get_etag("repos/owner/repo")

# Invalidate by operation type
cache.invalidate_by_operation("list_repos")
```

## Integration with GitHubCLI

`GitHubCLI` integrates all components:

```python
gh = GitHubCLI(
    enable_cache=True,           # Uses GitHubCache
    enable_tracking=True,         # Uses APICounter
    enable_rate_limiting=True     # Uses RateLimiter
)

# All operations are cached, tracked, and rate-limited
repos = gh.list_repos()
```

## Configuration

Configuration loaded from `.github/cache-config.yml`:

```yaml
cache:
  enabled: true
  max_size: 5000
  default_ttl: 300

operation_ttls:
  list_repos: 600
  get_repo_info: 300
  list_workflows: 300

rate_limiting:
  warning_threshold: 100
  aggressive_threshold: 50
  cache_first_mode: true
```

## Migration Guide

### From github_wrapper.py

```python
# Old code
from ipfs_datasets_py.utils.github_wrapper import GitHubCLI
gh = GitHubCLI()

# New code
from ipfs_datasets_py.utils.github import GitHubCLI
gh = GitHubCLI()

# Or import from top level (after Phase 2)
from ipfs_datasets_py.utils.github_wrapper import GitHubCLI  # Deprecated, re-exports
```

### From github_cli.py

```python
# Old code
from ipfs_datasets_py.utils.github_cli import GitHubCLI

# New code
from ipfs_datasets_py.utils.github import GitHubCLI
```

### From optimizers/agentic/github_api_unified.py

```python
# Old code
from ipfs_datasets_py.optimizers.agentic.github_api_unified import UnifiedGitHubAPICache

# New code
from ipfs_datasets_py.utils.cache import GitHubCache
from ipfs_datasets_py.utils.github import APICounter

# Use separately or via GitHubCLI
gh = GitHubCLI()  # Integrates both
```

## Usage in .github/scripts

Thin wrapper pattern:

```python
#!/usr/bin/env python3
# .github/scripts/github_api_counter_thin.py

from ipfs_datasets_py.utils.github import APICounter

if __name__ == '__main__':
    counter = APICounter()
    counter.run_gh_command(['gh', 'pr', 'list'])
    print(counter.report())
    counter.save_metrics()
```

## Usage in Workflows

```yaml
- name: Track API Usage
  run: |
    python -c "
    from ipfs_datasets_py.utils.github import GitHubCLI
    
    gh = GitHubCLI()
    repos = gh.list_repos()
    print(gh.report())
    "
```

## Features

### Caching
- ETag support for conditional requests
- Per-operation TTL configuration
- Thread-safe operations
- Cache hit/miss statistics

### Call Tracking
- Track all API calls by type
- Cache hit/miss tracking
- Workflow context (run ID, workflow name)
- Metrics export to JSON

### Rate Limiting
- Monitor current rate limits
- Warning at configurable thresholds
- Aggressive caching when approaching limits
- Automatic error on exhaustion

### Error Handling
- Exponential backoff retry
- Timeout handling
- Comprehensive error messages
- Graceful degradation

## See Also

- `utils/cache/` - Cache infrastructure
- `.github/cache-config.yml` - Configuration
- `docs/REFACTORING_PLAN_GITHUB_UTILS.md` - Overall plan
- `optimizers/GITHUB_INTEGRATION.md` - Optimizer integration
