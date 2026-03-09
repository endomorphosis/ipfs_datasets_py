# GitHub Folder Integration with Optimizers Module

## Overview

This document describes the integration between `.github/` folder scripts and the `ipfs_datasets_py/optimizers/` module to maximize code reuse and maintain a single source of truth for GitHub API interactions.

## Problem Statement

Previously, GitHub API functionality was duplicated across:
1. `.github/scripts/github_api_counter.py` - API call tracking for workflows
2. `optimizers/agentic/github_control.py` - API caching for agentic optimizers
3. Various workflow helper scripts in `.github/scripts/`

This duplication led to:
- Inconsistent API rate limiting across workflows
- Duplicate cache implementations
- Difficulty maintaining and improving GitHub integrations
- Missed optimization opportunities

## Solution: Unified GitHub API Module

### Architecture

```
ipfs_datasets_py/optimizers/agentic/
├── github_api_unified.py        # NEW - Single source of truth
│   ├── UnifiedGitHubAPICache    # Combines caching + call tracking
│   ├── CacheBackend             # Memory, File, Redis
│   ├── CacheEntry               # With access stats
│   └── APICallRecord            # Call tracking with metadata
│
└── github_control.py            # UPDATED - Uses unified API
    ├── AdaptiveRateLimiter      # Rate limit management
    ├── IssueManager             # GitHub issue operations
    ├── DraftPRManager           # Draft PR operations
    └── GitHubChangeController   # Complete workflow

.github/scripts/
├── github_api_counter_thin.py        # NEW - Thin wrapper
├── copilot_workflow_helper_thin.py   # NEW - Thin wrapper
├── github_api_counter.py             # LEGACY - Keep for compatibility
└── copilot_workflow_helper.py        # LEGACY - Keep for compatibility
```

### Unified GitHub API Cache (`github_api_unified.py`)

Consolidates functionality from:
- `GitHubAPICache` (from `github_control.py`)
- `GitHubAPICounter` (from `.github/scripts/github_api_counter.py`)

**Key Features:**
1. **Caching**: TTL-based with ETag support
2. **Call Tracking**: Records all API calls with metadata
3. **Statistics**: Cache hit rate, API cost estimation
4. **Configuration**: Loads from `.github/cache-config.yml`
5. **P2P Support**: Ready for cache sharing via IPFS
6. **Metrics Export**: Saves metrics for monitoring

**Usage in Optimizers:**
```python
from ipfs_datasets_py.optimizers.agentic import UnifiedGitHubAPICache

cache = UnifiedGitHubAPICache()

# Check cache
response = cache.get("repos/owner/repo")
if response is None:
    # Make API call
    response = github_api_call()
    cache.set("repos/owner/repo", response, operation_type="get_repo_info")
    cache.count_api_call("gh_repo_view")

# Get statistics
stats = cache.get_statistics()
print(f"Cache hit rate: {stats['hit_rate']:.2%}")
```

**Usage in .github/scripts:**
```python
from ipfs_datasets_py.optimizers.agentic import GitHubAPICounter

# Backward compatible alias
counter = GitHubAPICounter()

# Run command with tracking
result = counter.run_gh_command(['gh', 'pr', 'list'])

# Generate report
print(counter.report())
```

### Thin Wrapper Scripts

The `.github/scripts/` directory now contains thin wrappers that import from the optimizers module:

**`github_api_counter_thin.py`:**
```python
from ipfs_datasets_py.optimizers.agentic.github_api_unified import (
    UnifiedGitHubAPICache as GitHubAPICounter
)
```

**`copilot_workflow_helper_thin.py`:**
```python
from ipfs_datasets_py.optimizers.agentic.github_api_unified import UnifiedGitHubAPICache

class CopilotWorkflowHelper:
    def __init__(self):
        self.api_cache = UnifiedGitHubAPICache()
    
    def run_command(self, command):
        return self.api_cache.run_gh_command(command)
```

### Configuration

The unified cache loads configuration from `.github/cache-config.yml`:

```yaml
cache:
  enabled: true
  max_size: 5000
  default_ttl: 300  # 5 minutes
  directory: "~/.cache/github-api-p2p"
  persistence: true

operation_ttls:
  list_repos: 600          # 10 minutes
  get_repo_info: 300       # 5 minutes
  list_workflows: 300      # 5 minutes
  get_workflow_runs: 120   # 2 minutes
  copilot_completion: 3600 # 1 hour

rate_limiting:
  warning_threshold: 100
  aggressive_threshold: 50
  cache_first_mode: true
```

## Migration Path

### Phase 1: ✅ Create Unified Module
- [x] Created `github_api_unified.py` with consolidated functionality
- [x] Supports all features from both implementations
- [x] Backward compatible aliases (`GitHubAPICache`, `GitHubAPICounter`)

### Phase 2: ✅ Create Thin Wrappers
- [x] Created `github_api_counter_thin.py`
- [x] Created `copilot_workflow_helper_thin.py`
- [x] Keep original scripts for backward compatibility

### Phase 3: Update Workflows
- [ ] Update workflows to use thin wrappers
- [ ] Test in staging workflows first
- [ ] Gradually roll out to production workflows
- [ ] Monitor API usage and cache effectiveness

### Phase 4: Deprecation
- [ ] Add deprecation warnings to original scripts
- [ ] Update documentation to use new imports
- [ ] Eventually remove duplicate implementations

## Benefits

### Code Reuse
- **Single Implementation**: One GitHub API cache for all uses
- **Shared Rate Limiting**: All workflows aware of global rate limits
- **Consistent Behavior**: Same caching logic everywhere

### Maintainability
- **Single Source of Truth**: Fix bugs in one place
- **Easy Updates**: Improvements benefit all users
- **Clear Ownership**: optimizers module owns GitHub integrations

### Performance
- **Better Caching**: Shared cache across workflows
- **Lower API Usage**: Higher hit rates from shared cache
- **Cost Savings**: Reduced API calls = less rate limit issues

### Integration
- **Optimizer Workflows**: Use same cache as .github/ scripts
- **P2P Ready**: Easy to add IPFS-based cache sharing
- **Metrics**: Unified metrics across all GitHub operations

## Usage Examples

### Optimizer Code

```python
from ipfs_datasets_py.optimizers.agentic import (
    UnifiedGitHubAPICache,
    GitHubChangeController,
)

# Create cache
cache = UnifiedGitHubAPICache(
    config_file=Path('.github/cache-config.yml')
)

# Use in change controller
controller = GitHubChangeController(
    repo_path=Path('.'),
    github_client=github_client,
    cache=cache,
)

# Submit optimization
result = controller.submit_optimization(
    task_id="opt-1",
    changes=changes,
    description="Optimization result",
)

# Check statistics
stats = cache.get_statistics()
print(f"API calls: {stats['total_api_calls']}")
print(f"Cache hit rate: {stats['hit_rate']:.2%}")
```

### GitHub Actions Workflow

```yaml
- name: Track GitHub API Usage
  run: |
    python -c "
    from ipfs_datasets_py.optimizers.agentic import GitHubAPICounter
    
    counter = GitHubAPICounter()
    result = counter.run_gh_command(['gh', 'pr', 'list', '--limit', '100'])
    
    print(counter.report())
    counter.save_metrics()
    "

- name: Show API Statistics
  run: python .github/scripts/github_api_counter_thin.py report
```

### Standalone Script

```python
#!/usr/bin/env python3
from ipfs_datasets_py.optimizers.agentic import UnifiedGitHubAPICache

def main():
    # Initialize with config
    cache = UnifiedGitHubAPICache(
        config_file=Path('.github/cache-config.yml')
    )
    
    # Run multiple operations
    for i in range(10):
        cache.run_gh_command(['gh', 'repo', 'view', f'repo-{i}'])
    
    # Report statistics
    print(cache.report())
    cache.save_metrics()

if __name__ == '__main__':
    main()
```

## API Reference

### UnifiedGitHubAPICache

**Methods:**
- `get(key, operation_type)` - Get cached value
- `set(key, value, etag, ttl, operation_type)` - Cache value
- `count_api_call(call_type, count, metadata, cached)` - Track API call
- `run_gh_command(command, timeout, check)` - Run gh command with tracking
- `get_statistics()` - Get usage statistics
- `save_metrics(file_path)` - Save metrics to file
- `report()` - Generate human-readable report
- `clear()` - Clear all cache entries

**Attributes:**
- `call_counts` - Dict of API calls by type
- `call_records` - List of all API call records
- `cache_hits` - Number of cache hits
- `cache_misses` - Number of cache misses

### Configuration

Loads from `.github/cache-config.yml`:
- `cache.default_ttl` - Default TTL in seconds
- `cache.directory` - Cache directory path
- `operation_ttls.*` - Per-operation TTL overrides
- `rate_limiting.*` - Rate limiting thresholds

## Testing

### Unit Tests

```python
def test_unified_cache():
    cache = UnifiedGitHubAPICache(backend=CacheBackend.MEMORY)
    
    # Test caching
    cache.set("test", {"data": "value"})
    result = cache.get("test")
    assert result is not None
    
    # Test call tracking
    cache.count_api_call("gh_pr_list", 1)
    stats = cache.get_statistics()
    assert stats['total_api_calls'] == 1
    assert stats['cache_hits'] == 1
```

### Integration Tests

```python
def test_workflow_integration():
    cache = UnifiedGitHubAPICache()
    
    # Run actual gh command
    result = cache.run_gh_command(['gh', 'repo', 'view'])
    assert result.returncode == 0
    
    # Check tracking
    stats = cache.get_statistics()
    assert 'gh_repo_view' in stats['calls_by_type']
```

## Monitoring

### Metrics Collection

The unified cache automatically collects:
- Total API calls by type
- Cache hit/miss rates
- API cost estimation
- Operation timing
- Workflow context

### Metrics Export

Saves to `$RUNNER_TEMP/github_api_metrics_{run_id}.json`:
```json
{
  "total_api_calls": 150,
  "cache_hits": 90,
  "cache_misses": 60,
  "hit_rate": 0.6,
  "calls_by_type": {
    "gh_pr_list": 10,
    "gh_issue_view": 25,
    "gh_repo_view": 115
  },
  "total_cost": 150,
  "workflow_run_id": "12345",
  "workflow_name": "CI",
  "duration_seconds": 125.5
}
```

## Next Steps

1. **Test Integration**: Validate in staging workflows
2. **Monitor Effectiveness**: Track cache hit rates and API usage
3. **Add P2P Sharing**: Implement IPFS-based cache sharing
4. **Optimize TTLs**: Tune per-operation TTLs based on data
5. **Deprecate Old Code**: Remove duplicate implementations

## Questions?

- See `ARCHITECTURE_UNIFIED.md` for overall optimizer architecture
- See `ARCHITECTURE_AGENTIC_OPTIMIZERS.md` for agentic framework details
- See `.github/cache-config.yml` for configuration options
