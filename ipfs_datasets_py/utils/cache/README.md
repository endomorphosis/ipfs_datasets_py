# Unified Cache Infrastructure

This module provides a unified caching system with support for:
- Local TTL-based caching
- Distributed P2P caching (planned)
- GitHub API-specific caching
- Configurable via .github/cache-config.yml

## Quick Start

### Local Cache

```python
from ipfs_datasets_py.utils.cache import LocalCache

# Create cache
cache = LocalCache(maxsize=100, default_ttl=300)

# Set value
cache.set("key", {"data": "value"})

# Get value
result = cache.get("key")

# Check statistics
stats = cache.get_stats()
print(f"Hit rate: {stats.hit_rate:.2%}")
```

### GitHub API Cache

```python
from ipfs_datasets_py.utils.cache import GitHubCache

# Create cache (loads config from .github/cache-config.yml)
cache = GitHubCache()

# Cache API response with ETag
cache.set(
    "repos/owner/repo",
    response_data,
    etag="W/\"abc123\"",
    operation_type="get_repo_info"
)

# Get cached response
cached = cache.get("repos/owner/repo")

# Check if still valid using ETag
etag = cache.get_etag("repos/owner/repo")
```

### P2P Cache (Planned)

```python
from ipfs_datasets_py.utils.cache import P2PCache

# Create P2P cache (currently falls back to local)
cache = P2PCache()

# Use like local cache
cache.set("key", "value")
value = cache.get("key")

# P2P features (stubs for now)
cache.broadcast("shared_key", "shared_value")
cache.sync_with_peers()
print(f"Peers: {cache.get_peer_count()}")
```

## Configuration

Cache behavior is configured via `.github/cache-config.yml`:

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

rate_limiting:
  warning_threshold: 100
  aggressive_threshold: 50
  cache_first_mode: true
```

P2P configuration is in `.github/p2p-config.yml` (see config file for details).

## Architecture

```
cache/
├── base.py              - Abstract base classes (BaseCache, DistributedCache)
├── local.py             - Local TTL cache implementation
├── github_cache.py      - GitHub API-specific cache
├── p2p.py               - P2P distributed cache (stub)
├── config_loader.py     - Configuration loader
└── __init__.py          - Public API exports
```

## Migration from Old Code

### From query_cache.py

```python
# Old code
from ipfs_datasets_py.utils.query_cache import QueryCache
cache = QueryCache(maxsize=100, ttl=300)

# New code (recommended)
from ipfs_datasets_py.utils.cache import LocalCache
cache = LocalCache(maxsize=100, default_ttl=300)

# Or use backward-compatible alias
from ipfs_datasets_py.utils.cache import QueryCache
cache = QueryCache(maxsize=100, ttl=300)  # Deprecated warning
```

### From github_wrapper.py

```python
# Old code (if GitHubAPICache was used directly)
from ipfs_datasets_py.utils.github_wrapper import GitHubAPICache

# New code
from ipfs_datasets_py.utils.cache import GitHubCache
cache = GitHubCache()
```

## Statistics and Monitoring

All cache implementations track statistics:

```python
cache = LocalCache()
# ... use cache ...

stats = cache.get_stats()
print(f"Hits: {stats.hits}")
print(f"Misses: {stats.misses}")
print(f"Hit rate: {stats.hit_rate:.2%}")
print(f"Sets: {stats.sets}")
print(f"Evictions: {stats.evictions}")
print(f"Errors: {stats.errors}")
print(f"Size: {stats.size}")
```

## Thread Safety

All cache implementations are thread-safe using RLock internally.

## Custom Cache Implementations

Extend `BaseCache` or `DistributedCache`:

```python
from ipfs_datasets_py.utils.cache import BaseCache

class MyCache(BaseCache):
    def get(self, key: str):
        # Implementation
        pass
    
    def set(self, key: str, value, ttl=None, **metadata):
        # Implementation
        pass
    
    # ... implement other abstract methods
```

## Future Roadmap

### P2P Cache Implementation

Full P2P implementation planned with:
- libp2p integration for networking
- Peer discovery via mDNS, DHT, GitHub Cache API
- Message encryption using GitHub tokens
- Cache synchronization protocol
- NAT traversal (circuit relay, hole punching)
- Content verification and authentication

See `p2p.py` for detailed roadmap.

## See Also

- `.github/cache-config.yml` - Cache configuration
- `.github/p2p-config.yml` - P2P network configuration  
- `docs/REFACTORING_PLAN_GITHUB_UTILS.md` - Overall refactoring plan
- `utils/github/` - GitHub operations using this cache
